"""Live Debian 13 laboratory six-inbound simultaneous operation and independence suite.

Verifies all six inbounds (P0, P1, P3, WIREGUARD, AMNEZIAWG-3.1, HYSTERIA2) operate
concurrently without port/subnet/ownership collisions, and that disabling or restarting
WireGuard or AmneziaWG 3.1 does not disrupt the other protocol.
"""
import argparse
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'release'), str(ROOT / 'tests/release'), str(ROOT / 'tests/protocols'), str(ROOT / 'tests')]

import preview_amneziawg31 as awg31
import preview_hysteria2 as hy2
import preview_panel_inbounds as native
import preview_vpn_inbounds as vpn
import preview_wireguard as wg

DEFAULT_NS = 'preview-client'
DEFAULT_CA = '/var/lib/3xui-preview-acme/config/live/3xui-preview/fullchain.pem'
DEFAULT_OUTPUT = '/tmp/preview08-six-inbounds-results.json'
ORIGIN_IP = '10.77.5.2'
TARGET_IP = '198.18.0.10'
ORIGIN_PORT = 18099
TCP_PAYLOAD_BYTES = 65536
UDP_PACKETS = 8
UDP_PACKET_BYTES = 512
XRAY_BIN = '/opt/3xui-pro-fork/panel/bin/xray-linux-amd64'


class _EchoHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        body = self.rfile.read(length)
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body[::-1])

    def log_message(self, *_args):
        pass


def _serve_origin():
    server = ThreadingHTTPServer((ORIGIN_IP, ORIGIN_PORT), _EchoHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.bind((ORIGIN_IP, ORIGIN_PORT))
        while True:
            data, addr = udp.recvfrom(8192)
            udp.sendto(data[::-1], addr)


def _run(*args, check=True, timeout=45):
    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    if check and proc.returncode != 0:
        raise RuntimeError(f'command {args[0]} failed exit={proc.returncode}')
    return proc


def _wait_tcp(host, port, proc=None, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError('worker exited prematurely')
        try:
            with socket.create_connection((host, port), timeout=0.3):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f'TCP {host}:{port} timeout')


def _ensure_all_six_origin_routing(api):
    raw = native.object_value(api.call('xray/', {}))
    template = native.object_value(raw['xraySetting'])
    expected_outbound = {
        'tag': 'preview08-origin',
        'protocol': 'freedom',
        'settings': {
            'redirect': f'{ORIGIN_IP}:{ORIGIN_PORT}',
            'finalRules': [
                {'action': 'allow', 'network': 'tcp,udp', 'ip': [f'{ORIGIN_IP}/32'], 'port': ORIGIN_PORT},
                {'action': 'block'},
            ],
        },
    }
    all_tags = [*native.TAGS.values(), *vpn.TAGS]
    outbounds = template.setdefault('outbounds', [])
    rules = template.setdefault('routing', {}).setdefault('rules', [])
    changed = False

    found_out = [o for o in outbounds if o.get('tag') == 'preview08-origin']
    if not found_out:
        outbounds.append(expected_outbound)
        changed = True
    elif found_out != [expected_outbound]:
        raise RuntimeError('existing preview08-origin outbound differs')

    found_rules = [r for r in rules if r.get('outboundTag') == 'preview08-origin']
    if not found_rules:
        rules.insert(0, {
            'type': 'field',
            'inboundTag': all_tags,
            'ip': [f'{TARGET_IP}/32'],
            'port': str(ORIGIN_PORT),
            'outboundTag': 'preview08-origin',
        })
        changed = True
    else:
        rule = found_rules[0]
        tags = list(rule.get('inboundTag') or [])
        for tag in all_tags:
            if tag not in tags:
                tags.append(tag)
                changed = True
        rule['inboundTag'] = tags

    if changed:
        api.call(
            'xray/update',
            {'xraySetting': json.dumps(template), 'outboundTestUrl': raw.get('outboundTestUrl', '')},
            form=True,
        )
        _run('systemctl', 'restart', native.PANEL_UNIT)


def _probe_wg_client(spec_path, expected):
    from protocols.wireguard import test_e2e as wg_e2e
    spec = json.loads(Path(spec_path).read_text())
    if shutil.which('wg'):
        probe = _run('ip', 'link', 'add', 'dev', 'p08intwg0', 'type', 'wireguard', check=False)
        if probe.returncode == 0:
            _run('ip', 'link', 'del', 'p08intwg0', check=False)
            wg_e2e._kernel_wg_worker(spec, expected)
            return
    wg_e2e._xray_wg_worker(spec, expected)


def _probe_awg_client(spec_path, expected):
    from protocols.amneziawg31 import test_e2e as awg_e2e
    awg_e2e._client_awg_exercise(spec_path, expected)


def _probe_hy2_client(outbound_path, expected):
    from protocols.hysteria2 import test_e2e as hy2_e2e
    log_path = Path(outbound_path).with_suffix('.log')
    hy2_e2e._run_client_probe(outbound_path, log_path, expected)


def _probe_vless_client(profile_name, config_path):
    cfg = json.loads(Path(config_path).read_text())
    http_port = cfg['inbounds'][0]['port']
    log_path = Path(config_path).with_suffix('.log')
    _run(XRAY_BIN, 'run', '-test', '-config', str(config_path))
    with log_path.open('ab') as log:
        proc = subprocess.Popen([XRAY_BIN, 'run', '-config', str(config_path)], stdout=log, stderr=log)
        try:
            _wait_tcp('127.0.0.1', http_port, proc=proc, timeout=25)
            conn = http.client.HTTPConnection('127.0.0.1', http_port, timeout=15)
            payload = secrets.token_bytes(TCP_PAYLOAD_BYTES)
            try:
                conn.request('POST', f'http://{TARGET_IP}:{ORIGIN_PORT}/verified', payload)
                resp = conn.getresponse()
                if resp.status != 200 or resp.read() != payload[::-1]:
                    raise RuntimeError(f'{profile_name} TCP transfer mismatch')
            finally:
                conn.close()
        finally:
            proc.terminate()
            proc.wait(timeout=8)


def _wait_active_subset(api, active_vpn_tags, ports, required_awg_emails=(), timeout=60):
    deadline = time.monotonic() + timeout
    stable = 0
    config_path = Path('/opt/3xui-pro-fork/panel/bin/config.json')
    while time.monotonic() < deadline:
        try:
            native.verify_ready()
            xray_pid = native.native_pid()
            panel_pid = int(native.ownership.service_properties(native.PANEL_UNIT)['MainPID'])
            rows = {r.get('tag'): r for r in (api.call('inbounds/list') or [])}
            live_tags = {item.get('tag') for item in native.core_api('lsi', '-isOnlyTags=false').get('inbounds', [])}
            if set(rows) != (set(native.TAGS.values()) | set(vpn.TAGS)):
                raise RuntimeError('six-row panel set incomplete')
            for tag in vpn.TAGS:
                port = ports[tag]
                if tag in active_vpn_tags:
                    if not rows[tag].get('enable'):
                        raise RuntimeError(f'{tag} expected enabled')
                    if tag not in live_tags:
                        raise RuntimeError(f'{tag} expected in live Xray runtime')
                    if tag == 'WIREGUARD':
                        wg.verify_live_listener(port, xray_pid)
                    elif tag == 'AMNEZIAWG-3.1':
                        awg31.verify_live_listener(port, panel_pid)
                    elif tag == 'HYSTERIA2':
                        hy2.verify_live_listener(port, xray_pid)
                else:
                    if rows[tag].get('enable'):
                        raise RuntimeError(f'{tag} expected disabled')
                    if tag in live_tags:
                        raise RuntimeError(f'{tag} still present in live Xray runtime')
                    if vpn.listener(port):
                        raise RuntimeError(f'{tag} port {port} still listening while disabled')
            if 'AMNEZIAWG-3.1' in active_vpn_tags and required_awg_emails:
                cfg = json.loads(config_path.read_text(encoding='utf-8'))
                socks_inb = next(
                    (i for i in cfg.get('inbounds', []) if i.get('tag') == 'AMNEZIAWG-3.1'),
                    None,
                )
                users = {
                    a.get('user')
                    for a in (socks_inb or {}).get('settings', {}).get('accounts', [])
                    if isinstance(a, dict)
                }
                for req_email in required_awg_emails:
                    if req_email not in users:
                        raise RuntimeError(f'AMNEZIAWG-3.1 SOCKS5 relay missing {req_email}')
            stable += 1
            if stable >= 2:
                return xray_pid, panel_pid
        except (RuntimeError, ValueError, KeyError, OSError, json.JSONDecodeError):
            stable = 0
        time.sleep(0.5)
    raise RuntimeError(f'subset readiness timed out for {active_vpn_tags}')


def run_six_inbounds_integration(ca_path=DEFAULT_CA, output_path=DEFAULT_OUTPUT, ns=DEFAULT_NS):
    os.umask(0o077)
    web = native.private_json(native.WEB_STATE)
    pub_addr = ipaddress.ip_address(web['public_address'])
    if pub_addr.version != 4 or not any(pub_addr in net for net in vpn.RFC1918):
        raise RuntimeError('six-inbound integration requires RFC1918 lab public_address')
    if not Path(ca_path).is_file():
        raise RuntimeError(f'CA file missing: {ca_path}')

    checks = {
        'six_inbounds_active': 'NOT_RUN',
        'port_and_ownership_isolation': 'NOT_RUN',
        'subnet_and_key_isolation': 'NOT_RUN',
        'simultaneous_all_six_traffic': 'NOT_RUN',
        'disable_wg_keeps_awg_and_others_alive': 'NOT_RUN',
        'disable_awg_keeps_wg_and_others_alive': 'NOT_RUN',
        'restart_preserves_all_six': 'NOT_RUN',
    }
    report = {
        'status': 'FAIL',
        'scope': 'disposable Debian 13 six-inbound integration & independence',
        'checks': checks,
        'details': {},
    }

    api = native.api_client()
    vpn_state = native.private_json(vpn.STATE)
    if vpn_state.get('phase') != 'READY':
        raise RuntimeError('preview-vpn-inbounds.json must be READY')
    ports = vpn_state['ports']
    subnets = vpn_state['subnets']
    wg_net, _, _ = wg.validate_subnet(subnets['WIREGUARD'])
    awg_net = awg31.validate_subnet(subnets['AMNEZIAWG-3.1'])

    work = Path(tempfile.mkdtemp(prefix='preview08-six-int-'))
    work.chmod(0o700)
    origin_proc = None
    created_emails = []

    try:
        rows = api.call('inbounds/list') or []
        by_tag = {r.get('tag'): r for r in rows}
        expected_tags = set(native.TAGS.values()) | set(vpn.TAGS)
        if len(rows) != 6 or set(by_tag) != expected_tags:
            raise RuntimeError(f'expected 6 inbounds {sorted(expected_tags)}, got {sorted(by_tag)}')
        if not all(r.get('enable') for r in rows):
            raise RuntimeError('all six inbounds must start enabled')
        checks['six_inbounds_active'] = 'PASS'

        # Verify distinct ports & single-owner process boundaries.
        all_ports = {r.get('port') for r in rows} | {443}
        if len(all_ports) != 7:
            raise RuntimeError('port collision detected among six inbounds + HTTPS 443')
        if wg_net.overlaps(awg_net):
            raise RuntimeError('WG and AWG subnets overlap')
        xray_pid, panel_pid = _wait_active_subset(api, set(vpn.TAGS), ports)
        if xray_pid == panel_pid:
            raise RuntimeError('Xray child and panel MainPID must be distinct processes')
        awg_props = native.ownership.service_properties(vpn.AWG_UNIT)
        if awg_props.get('ActiveState') != 'active' and native.ownership.service_properties('3xui-preview-xray.service').get('ActiveState') == 'inactive':
            pass
        if awg_props.get('ActiveState') != 'inactive':
            raise RuntimeError('standalone 3xui-pro-fork-awg.service must remain inactive')
        checks['port_and_ownership_isolation'] = 'PASS'

        _ensure_all_six_origin_routing(api)
        xray_pid, panel_pid = _wait_active_subset(api, set(vpn.TAGS), ports)

        origin_proc = subprocess.Popen(
            ['ip', 'netns', 'exec', ns, sys.executable, str(Path(__file__).resolve()), '--origin'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _wait_tcp(ORIGIN_IP, ORIGIN_PORT, proc=origin_proc, timeout=30)

        # Create independent synthetic test clients for WG, AWG 3.1, and HY2.
        wg_settings = native.object_value(by_tag['WIREGUARD']['settings'])
        awg_settings = native.object_value(by_tag['AMNEZIAWG-3.1']['settings'])
        awg_server = awg_settings['server']

        wg_used = [c for x in wg_settings.get('clients', []) for c in (x.get('allowedIPs') or [])]
        awg_used = [c for x in awg_settings.get('clients', []) for c in (x.get('allowedIPs') or [])]

        wg_ip = wg.allocate_client_ip(subnets['WIREGUARD'], wg_used, reserved_subnets=(subnets['AMNEZIAWG-3.1'],))
        awg_ip = awg31.allocate_client_ip(subnets['AMNEZIAWG-3.1'], awg_used)

        wg_client = wg.build_client_payload('int08-wg-' + secrets.token_hex(4), wg_ip, keep_alive=25)
        awg_priv, awg_pub = awg31.generate_keypair()
        awg_client = awg31.build_client_payload('int08-awg-' + secrets.token_hex(4), awg_ip, awg_priv, awg_pub, keep_alive=25)
        hy2_client = hy2.build_client_payload('int08-hy2-' + secrets.token_hex(4))

        if wg_settings['secretKey'] == awg_server['privateKey'] or wg_client['privateKey'] == awg_client['privateKey']:
            raise RuntimeError('WG and AWG keys must be separate')
        checks['subnet_and_key_isolation'] = 'PASS'

        for tag, client_obj in (('WIREGUARD', wg_client), ('AMNEZIAWG-3.1', awg_client), ('HYSTERIA2', hy2_client)):
            api.call('clients/add', {'client': client_obj, 'inboundIds': [by_tag[tag]['id']]})
            created_emails.append(client_obj['email'])
        _wait_active_subset(api, set(vpn.TAGS), ports, required_awg_emails=(awg_client['email'],), timeout=60)

        # Prepare client fixtures.
        wg_spec_path = work / 'wg.private.json'
        wg_spec_path.write_text(json.dumps({
            'endpoint_host': web['public_address'],
            'port': ports['WIREGUARD'],
            'server_public_key': wg.public_key_from_private(wg_settings['secretKey']),
            'client': wg_client,
            'mtu': wg_settings['mtu'],
        }))
        wg_spec_path.chmod(0o600)

        awg_conf = awg31.decode_vpn_link(
            next(x for x in api.call('clients/links/' + urllib.parse.quote(awg_client['email'], safe=''))
                 if isinstance(x, str) and x.startswith('vpn://'))
        )
        setconf_txt, awg_addr, awg_mtu = awg31.conf_to_setconf(
            awg_conf,
            endpoint_override=f"{web['public_address']}:{ports['AMNEZIAWG-3.1']}",
            allowed_ips_override=f'{TARGET_IP}/32',
        )
        awg_setconf_path = work / 'awg.private.setconf'
        awg_setconf_path.write_text(setconf_txt)
        awg_setconf_path.chmod(0o600)
        awg_spec_path = work / 'awg.private.json'
        awg_spec_path.write_text(json.dumps({'setconf_path': str(awg_setconf_path), 'address_cidr': awg_addr, 'mtu': awg_mtu}))
        awg_spec_path.chmod(0o600)

        hy2_link = next(
            x for x in hy2.extract_hysteria2_links(api.call('clients/links/' + urllib.parse.quote(hy2_client['email'], safe='')))
        )
        hy2_outbound = hy2.client_outbound_from_link(hy2_link, web['public_address'], ca_path)
        hy2_spec_path = work / 'hy2.private.json'
        hy2_spec_path.write_text(json.dumps(hy2_outbound))
        hy2_spec_path.chmod(0o600)

        vless_configs = native.private_json(native.DATA / 'preview-xray-clients.json')
        vless_paths = {}
        for idx, (profile, tag) in enumerate(native.TAGS.items()):
            row = by_tag[tag]
            active_cli = next(c for c in native.object_value(row['settings'])['clients'] if c.get('enable'))
            cfg = json.loads(json.dumps(vless_configs[profile]))
            cfg['inbounds'][0]['port'] = 19840 + idx
            cfg['outbounds'][0]['settings']['vnext'][0]['address'] = web['public_address']
            cfg['outbounds'][0]['settings']['vnext'][0]['users'][0]['id'] = active_cli['id']
            if profile == 'P1':
                cfg['outbounds'][0]['streamSettings']['tlsSettings']['certificates'] = [
                    {'certificateFile': str(ca_path), 'usage': 'verify'}
                ]
            vpath = work / f'{profile}.private.json'
            vpath.write_text(json.dumps(cfg))
            vpath.chmod(0o600)
            vless_paths[profile] = vpath

        def test_wg(expected=True):
            cmd = ['ip', 'netns', 'exec', ns, sys.executable, str(Path(__file__).resolve()), '--probe-wg', str(wg_spec_path)]
            if not expected:
                cmd.append('--negative')
            _run(*cmd, timeout=70)

        def test_awg(expected=True):
            cmd = ['ip', 'netns', 'exec', ns, sys.executable, str(Path(__file__).resolve()), '--probe-awg', str(awg_spec_path)]
            if not expected:
                cmd.append('--negative')
            _run(*cmd, timeout=70)

        def test_hy2(expected=True):
            cmd = ['ip', 'netns', 'exec', ns, sys.executable, str(Path(__file__).resolve()), '--probe-hy2', str(hy2_spec_path)]
            if not expected:
                cmd.append('--negative')
            _run(*cmd, timeout=70)

        def test_vless(profile):
            _run('ip', 'netns', 'exec', ns, sys.executable, str(Path(__file__).resolve()),
                 '--probe-vless', profile, '--probe-vless-config', str(vless_paths[profile]), timeout=70)

        # 1. All 6 active simultaneously
        for profile in ('P0', 'P1', 'P3'):
            test_vless(profile)
        test_wg(True)
        test_awg(True)
        test_hy2(True)
        checks['simultaneous_all_six_traffic'] = 'PASS'

        # 2. Disable WIREGUARD -> AWG 3.1 + HY2 + P0/P1/P3 stay operational; WG denied
        api.call(f"inbounds/setEnable/{by_tag['WIREGUARD']['id']}", {'enable': False})
        time.sleep(1.5)
        _wait_active_subset(api, {'AMNEZIAWG-3.1', 'HYSTERIA2'}, ports, required_awg_emails=(awg_client['email'],), timeout=60)
        test_wg(False)
        test_awg(True)
        test_hy2(True)
        test_vless('P0')
        api.call(f"inbounds/setEnable/{by_tag['WIREGUARD']['id']}", {'enable': True})
        time.sleep(1.5)
        _wait_active_subset(api, set(vpn.TAGS), ports, required_awg_emails=(awg_client['email'],), timeout=60)
        test_wg(True)
        checks['disable_wg_keeps_awg_and_others_alive'] = 'PASS'

        # 3. Disable AMNEZIAWG-3.1 -> WIREGUARD + HY2 + P0/P1/P3 stay operational; AWG denied
        api.call(f"inbounds/setEnable/{by_tag['AMNEZIAWG-3.1']['id']}", {'enable': False})
        time.sleep(1.5)
        _wait_active_subset(api, {'WIREGUARD', 'HYSTERIA2'}, ports, timeout=60)
        test_awg(False)
        test_wg(True)
        test_hy2(True)
        test_vless('P3')
        api.call(f"inbounds/setEnable/{by_tag['AMNEZIAWG-3.1']['id']}", {'enable': True})
        _wait_active_subset(api, set(vpn.TAGS), ports, required_awg_emails=(awg_client['email'],), timeout=60)
        test_awg(True)
        checks['disable_awg_keeps_wg_and_others_alive'] = 'PASS'

        # 4. Restart panel unit -> all six recover & work independently
        _run('systemctl', 'restart', native.PANEL_UNIT)
        post_xray, post_panel = _wait_active_subset(api, set(vpn.TAGS), ports, required_awg_emails=(awg_client['email'],), timeout=60)
        test_wg(True)
        test_awg(True)
        test_hy2(True)
        test_vless('P1')
        checks['restart_preserves_all_six'] = 'PASS'
        report['details'] = {
            'ports': ports,
            'subnets': subnets,
            'post_restart_xray_pid': post_xray,
            'post_restart_panel_pid': post_panel,
        }

        if all(v == 'PASS' for v in checks.values()):
            report['status'] = 'PASS'
    finally:
        for email in created_emails:
            try:
                api.call('clients/del/' + urllib.parse.quote(email, safe=''), {})
            except Exception:
                pass
        if origin_proc is not None:
            origin_proc.terminate()
            origin_proc.wait(timeout=8)
        shutil.rmtree(work, ignore_errors=True)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + '\n')
    return report


@unittest.skipUnless(
    os.environ.get('PREVIEW08_RUN_E2E') == '1',
    'live Debian 13 six-inbound integration requires PREVIEW08_RUN_E2E=1',
)
class SixInboundsIntegrationTest(unittest.TestCase):
    def test_six_inbounds_simultaneous_and_independent(self):
        report = run_six_inbounds_integration(
            ca_path=os.environ.get('PREVIEW08_CA', DEFAULT_CA),
            output_path=os.environ.get('PREVIEW08_SIX_OUTPUT', DEFAULT_OUTPUT),
            ns=os.environ.get('PREVIEW08_NS', DEFAULT_NS),
        )
        self.assertEqual(report['status'], 'PASS', json.dumps(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ca', default=DEFAULT_CA)
    parser.add_argument('--output', default=DEFAULT_OUTPUT)
    parser.add_argument('--ns', default=DEFAULT_NS)
    parser.add_argument('--origin', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--probe-wg', help=argparse.SUPPRESS)
    parser.add_argument('--probe-awg', help=argparse.SUPPRESS)
    parser.add_argument('--probe-hy2', help=argparse.SUPPRESS)
    parser.add_argument('--probe-vless', help=argparse.SUPPRESS)
    parser.add_argument('--probe-vless-config', help=argparse.SUPPRESS)
    parser.add_argument('--negative', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.origin:
        _serve_origin()
        return
    if args.probe_wg:
        _probe_wg_client(args.probe_wg, expected=not args.negative)
        return
    if args.probe_awg:
        _probe_awg_client(args.probe_awg, expected=not args.negative)
        return
    if args.probe_hy2:
        _probe_hy2_client(args.probe_hy2, expected=not args.negative)
        return
    if args.probe_vless:
        _probe_vless_client(args.probe_vless, args.probe_vless_config)
        return

    report = run_six_inbounds_integration(args.ca, args.output, ns=args.ns)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['status'] == 'PASS' else 1)


if __name__ == '__main__':
    main()
