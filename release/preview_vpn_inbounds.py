#!/usr/bin/env python3
"""Opt-in PREVIEW-XONIX-08 laboratory integration; never a production migrator.

Plan is read-only. Apply requires an explicit lab marker and an RFC1918 bind.
The existing native READY journal and three VLESS identities are immutable.
An interrupted apply retains a private journal and requires manual recovery.
"""
import argparse
import base64
import copy
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import time

import preview_panel_inbounds as native
import upgrade_candidate as ownership

DATA = native.DATA
STATE = DATA / 'preview-vpn-inbounds.json'
MARKER = Path('/var/lib/3xui-preview08-lab')
AWG_UNIT = '3xui-pro-fork-awg.service'
AWG = '/opt/3xui-pro-fork/awg/awg'
TAGS = ('WIREGUARD', 'AMNEZIAWG-3.1', 'HYSTERIA2')
RFC1918 = tuple(ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def command(*args, data=None):
    try:
        return subprocess.check_output(args, input=data, text=True,
                                       stderr=subprocess.PIPE, timeout=30).strip()
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError('component command failed; private output withheld') from None


def key(value):
    if not isinstance(value, str):
        raise RuntimeError('invalid tunnel key')
    try:
        if len(base64.b64decode(value, validate=True)) != 32:
            raise ValueError()
    except (ValueError, TypeError):
        raise RuntimeError('invalid tunnel key') from None
    return value


def atomic(path, value):
    # Parent is verified private; exclusive temporary creation and fsync protect
    # journal replacement. Never follow an existing state file symlink.
    if path.exists() or path.is_symlink():
        ownership.regular_root_file(path, private=True)
    tmp = path.parent / ('.vpn08-' + secrets.token_hex(12))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(value, out, indent=2)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if tmp.exists():
            tmp.unlink()


def listener(port):
    return command('ss', '-H', '-ltnup', 'sport = :' + str(port))


def owned_awg_listener(text, props):
    """An active unit name alone cannot establish socket ownership."""
    if props.get('ActiveState') != 'active' or props.get('FragmentPath') != '/etc/systemd/system/' + AWG_UNIT:
        return False
    if props.get('DropInPaths') or props.get('NeedDaemonReload') != 'no':
        return False
    pids = {int(x) for x in re.findall(r'pid=(\d+)', text)}
    if not pids:
        return False
    expected = '/system.slice/' + AWG_UNIT
    try:
        return all(any(line.split(':', 2)[-1] == expected
                       for line in Path('/proc/' + str(pid) + '/cgroup').read_text().splitlines())
                   for pid in pids)
    except (OSError, ValueError):
        return False


def preserved_rows(rows):
    fields = ('id', 'tag', 'protocol', 'port', 'listen', 'enable', 'settings',
              'streamSettings', 'sniffing', 'shareAddr', 'shareAddrStrategy', 'disableFlow')
    return [{k: row.get(k) for k in fields} for row in sorted(rows, key=lambda r: r['id'])
            if row.get('tag') in native.TAGS.values()]


def validate_awg(settings):
    if not isinstance(settings, dict) or set(settings) != {'server', 'clients'}:
        raise RuntimeError('AWG input requires server and clients only')
    server = settings['server']
    if not isinstance(server, dict) or server.get('kernelMode', False):
        raise RuntimeError('only embedded AWG 3.1 is qualified for this laboratory utility')
    key(server.get('privateKey'))
    key(server.get('publicKey'))
    network = ipaddress.ip_network(str(server.get('subnetIp')) + '/' + str(server.get('subnetCidr')), strict=True)
    if network.version != 4 or not any(network.subnet_of(n) for n in RFC1918):
        raise RuntimeError('private AWG IPv4 subnet required')
    if type(server.get('mtu')) is not int or not 1280 <= server['mtu'] <= 65535:
        raise RuntimeError('AWG MTU must be explicitly preserved')
    clients = settings['clients']
    if not isinstance(clients, list) or len(clients) != 1:
        raise RuntimeError('laboratory fixture requires exactly one AWG peer')
    client = clients[0]
    key(client.get('privateKey'))
    key(client.get('publicKey'))
    if not client.get('enable') or not client.get('allowedIPs'):
        raise RuntimeError('enabled AWG peer/address required')
    for address in client['allowedIPs']:
        address = ipaddress.ip_interface(address)
        if address.version != 4 or address.network.prefixlen != 32 or address.ip not in network:
            raise RuntimeError('AWG peer must have one host address in server subnet')
    return settings


def validate_lab_handoff(settings):
    """Prove the JSON fixture carries the existing single-peer identity."""
    import configparser
    config = DATA / 'awg/server.setconf'
    ownership.regular_root_file(config, private=True)
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read_string(config.read_text())
    if set(parser.sections()) != {'Interface', 'Peer'}:
        raise RuntimeError('only existing single-peer laboratory AWG can be transferred')
    server, client = settings['server'], settings['clients'][0]
    if parser['Interface'].get('PrivateKey') != server['privateKey'] or parser['Peer'].get('PublicKey') != client['publicKey']:
        raise RuntimeError('AWG handoff would change existing keys')
    if parser['Interface'].get('ListenPort') != '29177':
        raise RuntimeError('existing AWG port differs')
    if set(x.strip() for x in parser['Peer'].get('AllowedIPs', '').split(',')) != set(client['allowedIPs']):
        raise RuntimeError('AWG handoff would change existing peer addresses')
    if parser['Peer'].get('PresharedKey', parser['Peer'].get('PreSharedKey', '')) != client.get('preSharedKey', ''):
        raise RuntimeError('AWG handoff would change peer preshared key')
    fields = {'Jc': 'jc', 'Jmin': 'jmin', 'Jmax': 'jmax', 'S1': 's1', 'S2': 's2',
              'S3': 's3', 'S4': 's4', 'H1': 'h1', 'H2': 'h2', 'H3': 'h3', 'H4': 'h4',
              'I1': 'i1', 'I2': 'i2', 'I3': 'i3', 'I4': 'i4', 'I5': 'i5',
              'HeaderProtectionKey': 'headerProtectionKey', 'ContentPaddingAddition': 'contentPaddingAddition',
              'RekeyAfterTime': 'rekeyAfterTime', 'RekeyTimeout': 'rekeyTimeout',
              'RejectAfterTime': 'rejectAfterTime', 'KeepaliveTimeout': 'keepaliveTimeout',
              'MaxHandshakeAttempts': 'maxHandshakeAttempts', 'RandomTrailers': 'randomTrailers',
              'DisableCookies': 'disableCookies'}
    allowed = set(fields) | {'PrivateKey', 'ListenPort'}
    if set(parser['Interface']) - allowed:
        raise RuntimeError('unsupported existing AWG interface setting; handoff refused')
    for config_key, json_key in fields.items():
        if config_key in parser['Interface']:
            previous = parser['Interface'][config_key]
            current = server.get(json_key, '')
            if isinstance(current, bool):
                same = previous.casefold() in ('true', 'on', '1') if current else previous.casefold() in ('false', 'off', '0')
            else:
                same = str(current) == previous
            if not same:
                raise RuntimeError('AWG handoff would change obfuscation parameters')
    link = json.loads(command('ip', '-j', 'link', 'show', 'dev', 'xproawg0'))
    if len(link) != 1 or link[0]['mtu'] != server['mtu']:
        raise RuntimeError('AWG handoff must preserve observed server MTU')


def plan(args, api):
    if type(args.wg_port) is not int or type(args.hy2_port) is not int:
        raise RuntimeError('explicit --wg-port and --hy2-port required')
    ports = {'WIREGUARD': args.wg_port, 'AMNEZIAWG-3.1': 29177, 'HYSTERIA2': args.hy2_port}
    if len(set(ports.values())) != 3 or any(not 1 <= n <= 65535 for n in ports.values()):
        raise RuntimeError('distinct valid VPN ports required; AWG owns 29177')
    native.verify_ready()
    rows = api.call('inbounds/list') or []
    if len(rows) != 3 or {r.get('tag') for r in rows} != set(native.TAGS.values()):
        raise RuntimeError('exact existing P0/P1/P3 required; unknown rows are never adopted')
    if STATE.exists() or STATE.is_symlink():
        raise RuntimeError('existing VPN journal: inspect it; repeat apply/adoption refused')
    # Disabled rows reserve their ports too. This is deliberately conservative
    # about TCP versus UDP sharing; the user supplies ports after inspection.
    for row in rows:
        if row.get('port') in ports.values():
            raise RuntimeError('port reserved by panel database')
    awg_properties = ownership.service_properties(AWG_UNIT)
    awg_active = awg_properties.get('ActiveState') == 'active'
    awg_owned = False
    for tag, port in ports.items():
        text = listener(port)
        if text and tag == 'AMNEZIAWG-3.1':
            awg_owned = owned_awg_listener(text, awg_properties)
        if text and not (tag == 'AMNEZIAWG-3.1' and awg_owned):
            raise RuntimeError('requested port has existing TCP/UDP listener')
    return {'ports': ports, 'vless': preserved_rows(rows), 'awg_service_active': awg_active,
            'awg_listener_owned': awg_owned,
            'ready_sha256': hashlib.sha256(native.STATE.read_bytes()).hexdigest()}


def assert_lab(args):
    if not args.lab:
        raise RuntimeError('production apply refused: AWG ownership handoff is not production-qualified')
    ownership.regular_root_file(MARKER, private=True)
    if MARKER.read_text().strip() != 'PREVIEW-XONIX-08':
        raise RuntimeError('explicit PREVIEW-XONIX-08 lab marker required')
    web = native.private_json(native.WEB_STATE)
    address = ipaddress.ip_address(web['public_address'])
    if address.version != 4 or not any(address in net for net in RFC1918):
        raise RuntimeError('laboratory requires RFC1918 public bind')
    return web


def backup():
    root = DATA / ('preview08-backup-' + secrets.token_hex(8))
    root.mkdir(mode=0o700)
    ownership.root_dir(root, private=True)
    with sqlite3.connect((DATA / 'x-ui.db').as_uri() + '?mode=ro', uri=True) as src:
        with sqlite3.connect(root / 'x-ui.db') as dst:
            src.backup(dst)
            if dst.execute('pragma integrity_check').fetchone() != ('ok',):
                raise RuntimeError('SQLite backup integrity failure')
    os.chmod(root / 'x-ui.db', 0o600)
    for name in ('server.setconf', 'client.conf', 'metadata.json'):
        src = DATA / 'awg' / name
        ownership.regular_root_file(src, private=True)
        dst = root / name
        dst.write_bytes(src.read_bytes())
        dst.chmod(0o600)
    return root


def apply(args, api, proposal):
    web = assert_lab(args)
    if not args.awg_settings_file:
        raise RuntimeError('--awg-settings-file private fixture required for all six inbounds')
    ownership.regular_root_file(args.awg_settings_file, private=True)
    awg_settings = validate_awg(json.loads(args.awg_settings_file.read_text()))
    # Verify actual Curve25519 identity instead of trusting JSON annotations.
    for item in (awg_settings['server'], awg_settings['clients'][0]):
        if command(AWG, 'pubkey', data=item['privateKey'] + '\n') != item['publicKey']:
            raise RuntimeError('AWG keypair mismatch')
    if proposal['awg_service_active'] and not args.lab_handoff_awg:
        raise RuntimeError('existing AWG service requires explicit --lab-handoff-awg')
    if proposal['awg_service_active']:
        validate_lab_handoff(awg_settings)
    existing = api.call('clients/list') or []
    emails = {str(x.get('client', x).get('email', '')).casefold() for x in existing}
    for email in ('preview08-wireguard', 'preview08-amneziawg', 'preview08-hysteria2'):
        if email.casefold() in emails:
            raise RuntimeError('fixture client identity already exists')
    private = command(AWG, 'genkey')
    wg_client_private = command(AWG, 'genkey')
    wg_client = {'email': 'preview08-wireguard', 'enable': True, 'privateKey': wg_client_private,
                 'publicKey': command(AWG, 'pubkey', data=wg_client_private + '\n'),
                 'allowedIPs': ['10.89.8.2/32'], 'keepAlive': 25, 'subId': secrets.token_urlsafe(24)}
    awg_client = copy.deepcopy(awg_settings['clients'][0])
    awg_client.update(email='preview08-amneziawg', subId=secrets.token_urlsafe(24))
    hy_client = {'email': 'preview08-hysteria2', 'enable': True,
                 'auth': secrets.token_urlsafe(32), 'subId': secrets.token_urlsafe(24)}
    awg_network = ipaddress.ip_network(str(awg_settings['server']['subnetIp']) + '/' + str(awg_settings['server']['subnetCidr']))
    if awg_network.overlaps(ipaddress.ip_network('10.89.8.0/24')):
        raise RuntimeError('laboratory WG/AWG tunnel subnets overlap')
    cert = Path('/var/lib/3xui-preview-acme/config/live/3xui-preview/fullchain.pem')
    cert_key = cert.parent / 'privkey.pem'
    # ACME live paths are intentional managed symlinks. Validate resolved files.
    for path in (cert, cert_key):
        ownership.regular_root_file(path.resolve(strict=True), private=path == cert_key)
    settings = {'WIREGUARD': {'secretKey': private, 'peers': [], 'clients': [], 'mtu': 1420,
                              'noKernelTun': True, 'subnetIp': '10.89.8.0', 'subnetCidr': 24},
                'AMNEZIAWG-3.1': {'server': awg_settings['server'], 'clients': []},
                'HYSTERIA2': {'version': 2, 'clients': []}}
    streams = {'WIREGUARD': {}, 'AMNEZIAWG-3.1': {},
               'HYSTERIA2': {'network': 'hysteria', 'security': 'tls',
                              'hysteriaSettings': {'version': 2, 'udpIdleTimeout': 60},
                              'tlsSettings': {'serverName': web['domain'], 'alpn': ['h3'],
                                              'certificates': [{'certificateFile': str(cert), 'keyFile': str(cert_key)}]}}}
    saved = backup()
    state = {'version': 1, 'phase': 'PREPARING', 'profiles': {}, 'ports': proposal['ports'],
             'clients': dict(zip(TAGS, (wg_client, awg_client, hy_client))), 'settings': settings,
             'domain': web['domain'], 'public_address': web['public_address'], 'backup': str(saved),
             'preserved': proposal, 'history': []}

    def phase(name):
        state['phase'] = name
        state['history'].append({'phase': name, 'time': int(time.time())})
        atomic(STATE, state)

    phase('PREPARING')
    try:
        for tag, protocol in zip(TAGS, ('wireguard', 'amneziawg', 'hysteria')):
            row = {'tag': tag, 'remark': tag, 'enable': False, 'listen': web['public_address'],
                   'port': proposal['ports'][tag], 'protocol': protocol,
                   'settings': json.dumps(settings[tag]), 'streamSettings': json.dumps(streams[tag]),
                   'sniffing': json.dumps({'enabled': False}),
                   'shareAddrStrategy': 'custom', 'shareAddr': web['domain']}
            phase('STAGING_' + tag)
            created = api.call('inbounds/add', row)
            if created.get('tag') != tag:
                raise RuntimeError('panel did not preserve requested tag')
            state['profiles'][tag] = created['id']
            phase('STAGED_' + tag)
            api.call('clients/add', {'client': state['clients'][tag], 'inboundIds': [created['id']]})
        if proposal['awg_service_active']:
            phase('STOPPING_LAB_STANDALONE_AWG')
            props = ownership.service_properties(AWG_UNIT)
            if props.get('FragmentPath') != '/etc/systemd/system/' + AWG_UNIT or props.get('DropInPaths') or props.get('NeedDaemonReload') != 'no':
                raise RuntimeError('laboratory AWG unit ownership differs')
            command('systemctl', 'stop', AWG_UNIT)
            if listener(29177):
                raise RuntimeError('AWG port not released; refusing native activation')
            command('systemctl', 'disable', AWG_UNIT)
        phase('ACTIVATING')
        for identity in state['profiles'].values():
            api.call('inbounds/setEnable/' + str(identity), {'enable': True})
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if all(listener(port) for port in state['ports'].values()):
                break
            time.sleep(.25)
        else:
            raise RuntimeError('native VPN listeners did not become ready')
        native.verify_ready()
        rows = api.call('inbounds/list') or []
        if len(rows) != 6 or preserved_rows(rows) != proposal['vless']:
            raise RuntimeError('six-row registry or VLESS preservation check failed')
        if hashlib.sha256(native.STATE.read_bytes()).hexdigest() != proposal['ready_sha256']:
            raise RuntimeError('native READY journal changed unexpectedly')
        for tag, identity in state['profiles'].items():
            row = next(r for r in rows if r['id'] == identity)
            state['settings'][tag] = native.object_value(row['settings'])
        phase('CONFIGURED_NOT_ACCEPTED')
    except Exception:
        phase('RECOVERY_REQUIRED')
        raise RuntimeError('RECOVERY_REQUIRED: private VPN journal/backup retained; no automatic rollback') from None
    print('LAB_VPN_CONFIGURED_NOT_ACCEPTED: six rows/listeners; real traffic acceptance still required')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wg-port', type=int, required=True)
    parser.add_argument('--hy2-port', type=int, required=True)
    parser.add_argument('--awg-settings-file', type=Path)
    parser.add_argument('--lab', action='store_true')
    parser.add_argument('--lab-handoff-awg', action='store_true')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('root required to inspect private installation')
    os.umask(0o077)
    ownership.root_dir(DATA, private=True)
    # Lock only apply, so read-only plan never creates files.
    if args.apply:
        assert_lab(args)
        import fcntl
        lock = os.open(DATA / '.preview-vpn-inbounds.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        ownership.regular_root_file(DATA / '.preview-vpn-inbounds.lock', private=True)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    api = native.api_client()
    proposal = plan(args, api)
    if args.apply:
        apply(args, api, proposal)
    else:
        print(json.dumps({'mode': 'PLAN_ONLY', 'ports': proposal['ports'],
                          'production_apply': 'REFUSED_UNQUALIFIED_AWG_HANDOFF',
                          'existing_vless_count': len(proposal['vless']),
                          'awg_service_active': proposal['awg_service_active'],
                          'awg_handoff_required': proposal['awg_service_active'],
                          'awg_listener_owned': proposal['awg_listener_owned']}))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print('VPN_INBOUNDS_REFUSED:', str(error))
        raise SystemExit(1)
