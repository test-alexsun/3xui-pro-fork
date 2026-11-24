"""Laboratory E2E acceptance suite for embedded AmneziaWG 3.1 in 3x-ui 3.11.0.

Cleanly importable on any OS; unittest skips unless PREVIEW08_RUN_E2E=1.
Never run against a production host; never modifies WireGuard, Hysteria2, or VLESS.
"""
import argparse
import base64
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import subprocess
import sys
import threading
import time
import unittest
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'release'))
import preview_amneziawg31 as awg31
import preview_panel_inbounds as native
import upgrade_candidate as ownership

DEFAULT_CA = '/var/lib/3xui-preview-acme/config/live/3xui-preview/fullchain.pem'
DEFAULT_OUTPUT = '/tmp/preview08-amneziawg31-results.json'
DEFAULT_NS = 'preview-client'

LAB_MARKER = Path('/var/lib/3xui-preview08-lab')
XRAY_BIN = '/opt/3xui-pro-fork/panel/bin/xray-linux-amd64'
ORIGIN_IP = '10.77.5.2'
TARGET_IP = '198.18.0.10'
ORIGIN_PORT = 18099
CLIENT_IFACE = 'awg31e2e'
WORK = Path('/tmp/preview08-awg31-e2e')


def _run(*args, input_text=None, timeout=30):
    result = subprocess.run(
        args,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if result.returncode:
        WORK.mkdir(mode=0o700, exist_ok=True)
        diag = WORK / f'cmd-fail-{time.time_ns()}.private.log'
        diag.write_text((result.stdout or '') + (result.stderr or ''))
        diag.chmod(0o600)
        raise RuntimeError(f'command failed exit={result.returncode}; private log retained')
    return result


def _lab_guard(ca_path):
    ownership.regular_root_file(LAB_MARKER, private=True)
    if LAB_MARKER.read_text().strip() != 'PREVIEW-XONIX-08':
        raise RuntimeError('explicit PREVIEW-XONIX-08 lab marker required')
    web = native.private_json(native.WEB_STATE)
    pub_addr = ipaddress.ip_address(web['public_address'])
    if pub_addr.version != 4 or not any(pub_addr in net for net in awg31.RFC1918_NETWORKS):
        raise RuntimeError('laboratory requires RFC1918 public_address')
    panel = native.private_json(native.two.PANEL_STATE)
    sub_domain = panel['layout']['subscription_domain']
    if not Path(ca_path).is_file():
        raise RuntimeError('CA file not found')
    return web, sub_domain


class _OriginHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers['Content-Length'])
        data = self.rfile.read(length)
        self.send_response(200)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data[::-1])

    def log_message(self, *_):
        pass


def _serve_origin():
    http_srv = ThreadingHTTPServer((ORIGIN_IP, ORIGIN_PORT), _OriginHandler)
    threading.Thread(target=http_srv.serve_forever, daemon=True).start()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.bind((ORIGIN_IP, ORIGIN_PORT))
        while True:
            data, addr = udp.recvfrom(8192)
            udp.sendto(data[::-1], addr)


def _wait_awg_sock_gone(iface=CLIENT_IFACE):
    sock = Path(f'/var/run/amneziawg/{iface}.sock')
    deadline = time.monotonic() + 10
    while sock.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    if sock.exists():
        sock.unlink()


def _client_awg_exercise(spec_path, expected):
    spec = json.loads(Path(spec_path).read_text())
    setconf_path = Path(spec['setconf_path'])
    addr_cidr = spec['address_cidr']
    mtu = int(spec['mtu'])
    sock = Path(f'/var/run/amneziawg/{CLIENT_IFACE}.sock')
    if sock.exists():
        raise RuntimeError(f'existing test socket refused: {sock}')
    WORK.mkdir(mode=0o700, exist_ok=True)
    log_path = WORK / 'awg31-client.private.log'
    with log_path.open('ab') as log:
        proc = subprocess.Popen([awg31.AWG_GO_BIN, '-f', CLIENT_IFACE], stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 30
            while not sock.exists():
                if proc.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError('amneziawg-go client failed to create control socket')
                time.sleep(0.1)
            _run(awg31.AWG_BIN, 'setconf', CLIENT_IFACE, str(setconf_path))
            _run('ip', 'address', 'add', addr_cidr, 'dev', CLIENT_IFACE)
            _run('ip', 'link', 'set', 'dev', CLIENT_IFACE, 'mtu', str(mtu), 'up')
            _run('ip', 'route', 'add', f'{TARGET_IP}/32', 'dev', CLIENT_IFACE)

            tcp_ok = False
            conn = http.client.HTTPConnection(TARGET_IP, ORIGIN_PORT, timeout=15 if expected else 3)
            payload = secrets.token_bytes(65536)
            try:
                conn.request('POST', '/verified', payload)
                resp = conn.getresponse()
                tcp_ok = resp.status == 200 and resp.read() == payload[::-1]
            except (OSError, http.client.HTTPException):
                pass
            finally:
                conn.close()
            if tcp_ok != expected:
                raise RuntimeError(f'AWG TCP transfer mismatch: expected={expected}, actual={tcp_ok}')

            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                udp.settimeout(8 if expected else 2)
                for _ in range(16 if expected else 1):
                    dgram = secrets.token_bytes(512)
                    udp.sendto(dgram, (TARGET_IP, ORIGIN_PORT))
                    udp_ok = False
                    try:
                        udp_ok = udp.recv(8192) == dgram[::-1]
                    except socket.timeout:
                        pass
                    if udp_ok != expected:
                        raise RuntimeError(f'AWG UDP transfer mismatch: expected={expected}, actual={udp_ok}')

            if expected:
                hs = _run(awg31.AWG_BIN, 'show', CLIENT_IFACE, 'latest-handshakes').stdout
                if not any(int(line.split()[1]) > 0 for line in hs.splitlines() if len(line.split()) >= 2):
                    raise RuntimeError('AWG 3.1 latest-handshakes missing positive timestamp')
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            _wait_awg_sock_gone()


def _wait_local_port(proc, port):
    deadline = time.monotonic() + 30
    while proc.poll() is None and time.monotonic() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError('Xray plain-WG negative probe did not start')


def _client_plain_wg_negative(spec_path):
    """Attempt plain WireGuard (no AWG 3.1 obfuscation) against AWG 3.1 UDP port; MUST fail."""
    spec = json.loads(Path(spec_path).read_text())
    config = {
        'log': {'loglevel': 'warning'},
        'inbounds': [
            {'listen': '127.0.0.1', 'port': 19829, 'protocol': 'http', 'settings': {}},
            {'listen': '127.0.0.1', 'port': 19830, 'protocol': 'socks', 'settings': {'auth': 'noauth', 'udp': True}},
        ],
        'outbounds': [{
            'protocol': 'wireguard',
            'settings': {
                'secretKey': spec['client_private_key'],
                'address': spec['allowed_ips'],
                'noKernelTun': True,
                'mtu': int(spec['mtu']),
                'peers': [{
                    'publicKey': spec['server_public_key'],
                    'endpoint': f"{spec['public_address']}:{spec['port']}",
                    'allowedIPs': [f'{TARGET_IP}/32'],
                    'keepAlive': 5,
                }],
            },
        }],
    }
    cfg_path = WORK / 'plain-wg-negative.private.json'
    cfg_path.write_text(json.dumps(config))
    cfg_path.chmod(0o600)
    _run(XRAY_BIN, 'run', '-test', '-config', str(cfg_path))
    with (WORK / 'plain-wg-negative.private.log').open('ab') as log:
        proc = subprocess.Popen([XRAY_BIN, 'run', '-config', str(cfg_path)], stdout=log, stderr=log)
        try:
            _wait_local_port(proc, 19829)
            conn = http.client.HTTPConnection('127.0.0.1', 19829, timeout=3)
            try:
                conn.request('POST', f'http://{TARGET_IP}:{ORIGIN_PORT}/verified', secrets.token_bytes(1024))
                resp = conn.getresponse()
                if resp.status == 200:
                    raise RuntimeError('SECURITY FAILURE: plain WireGuard TCP succeeded against AWG 3.1 port')
            except (OSError, http.client.HTTPException):
                pass
            finally:
                conn.close()

            with socket.create_connection(('127.0.0.1', 19830), timeout=3) as ctl:
                ctl.sendall(b'\x05\x01\x00')
                if ctl.recv(2) != b'\x05\x00':
                    raise RuntimeError('local SOCKS handshake failed')
                ctl.sendall(b'\x05\x03\x00\x01\x00\x00\x00\x00\x00\x00')
                rep = ctl.recv(64)
                relay = (socket.inet_ntoa(rep[4:8]), int.from_bytes(rep[8:10], 'big'))
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                    udp.settimeout(2)
                    udp.sendto(
                        b'\x00\x00\x00\x01' + socket.inet_aton(TARGET_IP) + ORIGIN_PORT.to_bytes(2, 'big') + b'ping',
                        relay,
                    )
                    try:
                        data = udp.recv(4096)
                        if data[10:] == b'gnip':
                            raise RuntimeError('SECURITY FAILURE: plain WireGuard UDP succeeded against AWG 3.1 port')
                    except socket.timeout:
                        pass
        finally:
            proc.terminate()
            proc.wait(timeout=8)


def _fetch_sub_file(url, sub_domain, public_address, ca_path, out_path):
    orig_getaddrinfo = socket.getaddrinfo

    def patched_getaddrinfo(host, port, *args, **kwargs):
        target = public_address if host == sub_domain else host
        return orig_getaddrinfo(target, port, *args, **kwargs)

    socket.getaddrinfo = patched_getaddrinfo
    try:
        ctx = ssl.create_default_context(cafile=ca_path)
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=ctx),
        )
        req = urllib.request.Request(url, headers={'User-Agent': 'AmneziaVPN'})
        with opener.open(req, timeout=20) as resp:
            body = resp.read()
    finally:
        socket.getaddrinfo = orig_getaddrinfo

    out_path.write_bytes(body)
    out_path.chmod(0o600)


def _decode_subscription_links(raw_bytes):
    text = raw_bytes.decode('utf-8', errors='strict')
    if 'vpn://' in text:
        lines = text.splitlines()
    else:
        compact = ''.join(text.split())
        padded = compact + '=' * (-len(compact) % 4)
        decoded = base64.b64decode(padded.encode('ascii')).decode('utf-8')
        lines = decoded.splitlines()
    return [line.strip() for line in lines if line.strip().startswith('vpn://')]


def _verify_awg_binary_versions():
    go_res = subprocess.run(
        [awg31.AWG_GO_BIN, '--version'],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=15,
    )
    awg_res = subprocess.run(
        [awg31.AWG_BIN, '--version'],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=15,
    )
    go_ver = (go_res.stdout + go_res.stderr).strip()
    awg_ver = (awg_res.stdout + awg_res.stderr).strip()
    if '3.1.20260828' not in go_ver:
        raise RuntimeError(f'unexpected amneziawg-go version: {go_ver!r}')
    if '3.1.20260812' not in awg_ver:
        raise RuntimeError(f'unexpected awg tools version: {awg_ver!r}')
    if ownership.sha(Path(awg31.AWG_GO_BIN)) != ownership.PINNED_FILES['awg/amneziawg-go']:
        raise RuntimeError('amneziawg-go binary SHA256 mismatch')
    if ownership.sha(Path(awg31.AWG_BIN)) != ownership.PINNED_FILES['awg/awg']:
        raise RuntimeError('awg binary SHA256 mismatch')
    return {'amneziawg_go': go_ver, 'awg_tools': awg_ver}


def _wait_server_ready(awg_port, required_email=None, absent_email=None, timeout=60):
    deadline = time.monotonic() + timeout
    stable = 0
    config_path = Path('/opt/3xui-pro-fork/panel/bin/config.json')
    while time.monotonic() < deadline:
        try:
            props = ownership.service_properties(awg31.PANEL_UNIT)
            if props.get('ActiveState') != 'active':
                raise RuntimeError('panel service not active')
            panel_pid = int(props['MainPID'])
            awg31.verify_live_listener(awg_port, panel_pid)
            if native.STATE.exists() and native.read_journal().get('phase') == 'READY':
                native.verify_ready()
            native.native_pid()
            live_tags = {
                item.get('tag')
                for item in native.core_api('lsi', '-isOnlyTags=false').get('inbounds', [])
            }
            if 'AMNEZIAWG-3.1' not in live_tags:
                raise RuntimeError('AMNEZIAWG-3.1 SOCKS5 relay missing from live Xray core')
            if required_email is not None or absent_email is not None:
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
                if required_email is not None and required_email not in users:
                    raise RuntimeError(f'AWG SOCKS5 relay missing account {required_email}')
                if absent_email is not None and absent_email in users:
                    raise RuntimeError(f'AWG SOCKS5 relay still retains {absent_email}')
            stable += 1
            if stable >= 2:
                return panel_pid
        except (RuntimeError, OSError, ValueError, KeyError, json.JSONDecodeError):
            stable = 0
        time.sleep(0.5)
    raise RuntimeError('server readiness timed out waiting for AWG 3.1 panel MainPID and Xray SOCKS5 convergence')


def _configure_awg_origin_route(api, awg_port):
    settings = native.object_value(api.call('xray/', {}))
    template = settings['xraySetting']
    if isinstance(template, str):
        template = json.loads(template)
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
    outbounds = template.setdefault('outbounds', [])
    rules = template.setdefault('routing', {}).setdefault('rules', [])
    changed = False

    matching_out = [o for o in outbounds if o.get('tag') == 'preview08-origin']
    if not matching_out:
        outbounds.append(expected_outbound)
        changed = True
    elif matching_out != [expected_outbound]:
        raise RuntimeError('existing preview08-origin outbound differs unexpectedly')

    matching_rule = next(
        (
            r for r in rules
            if r.get('outboundTag') == 'preview08-origin'
            and r.get('ip') == [f'{TARGET_IP}/32']
            and str(r.get('port')) == str(ORIGIN_PORT)
        ),
        None,
    )
    if matching_rule is None:
        rules.insert(0, {
            'type': 'field',
            'inboundTag': ['AMNEZIAWG-3.1'],
            'ip': [f'{TARGET_IP}/32'],
            'port': str(ORIGIN_PORT),
            'outboundTag': 'preview08-origin',
        })
        changed = True
    elif 'AMNEZIAWG-3.1' not in matching_rule.get('inboundTag', []):
        matching_rule.setdefault('inboundTag', []).append('AMNEZIAWG-3.1')
        changed = True

    if changed:
        api.call(
            'xray/update',
            {'xraySetting': json.dumps(template), 'outboundTestUrl': settings.get('outboundTestUrl', '')},
            form=True,
        )
        _run('systemctl', 'restart', awg31.PANEL_UNIT)
        _wait_server_ready(awg_port)


def _fetch_and_validate_exports(api, ns, email, sub_id, server, client_priv, domain, sub_domain, public_address, awg_port, ca_path):
    raw_links = api.call('clients/links/' + urllib.parse.quote(email, safe=''))
    if not isinstance(raw_links, list):
        raise RuntimeError('clients/links returned unexpected non-list payload')
    api_vpn_links = [item.strip() for item in raw_links if isinstance(item, str) and item.strip().startswith('vpn://')]
    if len(api_vpn_links) != 1:
        raise RuntimeError(f'expected 1 vpn:// link from clients/links, got {len(api_vpn_links)}')
    api_conf = awg31.decode_vpn_link(api_vpn_links[0])
    awg31.validate_awg31_conf(api_conf, server, client_priv, domain, awg_port)

    sub_out = WORK / f'sub-{secrets.token_hex(4)}.private.txt'
    sub_url = f'https://{sub_domain}/sub/{sub_id}'
    _run(
        'ip', 'netns', 'exec', ns, sys.executable, str(Path(__file__).resolve()),
        '--fetch-sub', '--sub-url', sub_url, '--sub-host', sub_domain,
        '--public-address', public_address, '--ca', ca_path, '--sub-output', str(sub_out),
    )
    sub_vpn_links = _decode_subscription_links(sub_out.read_bytes())
    sub_out.unlink(missing_ok=True)
    matched = []
    for link in sub_vpn_links:
        conf_candidate = awg31.decode_vpn_link(link)
        try:
            awg31.validate_awg31_conf(conf_candidate, server, client_priv, domain, awg_port)
            matched.append(conf_candidate)
        except ValueError:
            continue
    if len(matched) != 1 or matched[0] != api_conf:
        raise RuntimeError('/sub/<subId> AWG 3.1 export missing or diverges from clients/links')
    return api_conf


def run_e2e(ca_path=DEFAULT_CA, output_path=DEFAULT_OUTPUT, ns=DEFAULT_NS):
    os.umask(0o077)
    WORK.mkdir(mode=0o700, exist_ok=True)
    checks = {
        'backend': 'NOT_RUN',
        'inbound': 'NOT_RUN',
        'client_config': 'NOT_RUN',
        'handshake': 'NOT_RUN',
        'tcp_traffic': 'NOT_RUN',
        'udp_traffic': 'NOT_RUN',
        'crud': 'NOT_RUN',
        'restart': 'NOT_RUN',
        'persistence': 'NOT_RUN',
        'ui_api': 'NOT_RUN',
    }
    report = {
        'protocol': 'AMNEZIAWG-3.1',
        'status': 'FAIL',
        'scope': 'disposable Debian 13 lab VM',
        'checks': checks,
    }

    web, sub_domain = _lab_guard(ca_path)
    public_address = web['public_address']
    domain = web['domain']
    api = native.api_client()

    created_email = None
    origin_proc = None
    try:
        versions = _verify_awg_binary_versions()
        report['runtime_versions'] = versions
        checks['backend'] = 'PASS'

        inbounds = api.call('inbounds/list') or []
        awg_row = next((r for r in inbounds if r.get('tag') == 'AMNEZIAWG-3.1'), None)
        if not awg_row or not awg_row.get('enable') or awg_row.get('protocol') != 'amneziawg':
            raise RuntimeError('active AMNEZIAWG-3.1 panel inbound required')
        awg_port = int(awg_row['port'])
        if awg_port != awg31.DEFAULT_PORT or awg_row.get('listen') != public_address:
            raise RuntimeError(f'AMNEZIAWG-3.1 endpoint mismatch: {awg_row.get("listen")}:{awg_port}')
        awg_settings = native.object_value(awg_row['settings'])
        server = awg_settings['server']
        if server.get('kernelMode', False):
            raise RuntimeError('AMNEZIAWG-3.1 kernelMode must be False')
        if server.get('mtu', awg31.DEFAULT_MTU) != awg31.DEFAULT_MTU:
            raise RuntimeError(f'AMNEZIAWG-3.1 server MTU must remain {awg31.DEFAULT_MTU}')
        awg31.validate_key(server.get('headerProtectionKey'))
        if awg31.public_key(server['privateKey']) != server['publicKey']:
            raise RuntimeError('AMNEZIAWG-3.1 server keypair mismatch')
        panel_pid = _wait_server_ready(awg_port)
        awg31.verify_live_listener(awg_port, panel_pid)
        report['port'] = awg_port
        report['mtu'] = server.get('mtu', awg31.DEFAULT_MTU)
        checks['inbound'] = 'PASS'

        _configure_awg_origin_route(api, awg_port)

        origin_proc = subprocess.Popen(
            ['ip', 'netns', 'exec', ns, sys.executable, str(Path(__file__).resolve()), '--origin'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 30
        while True:
            if origin_proc.poll() is not None:
                raise RuntimeError('controlled origin exited during startup')
            try:
                with socket.create_connection((ORIGIN_IP, ORIGIN_PORT), timeout=0.3):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('controlled origin startup timed out')
                time.sleep(0.1)

        subnet = f"{server['subnetIp']}/{server['subnetCidr']}"
        used_cidrs = [
            cidr
            for existing in awg_settings.get('clients', [])
            for cidr in (existing.get('allowedIPs') or [])
        ]
        client_ip = awg31.allocate_client_ip(subnet, used_cidrs)
        priv1, pub1 = awg31.generate_keypair()
        email = f'e2e-awg31-{secrets.token_hex(6)}'
        client1 = awg31.build_client_payload(email, client_ip, priv1, pub1, keep_alive=25, enable=True)
        api.call('clients/add', {'client': client1, 'inboundIds': [awg_row['id']]})
        created_email = email
        _wait_server_ready(awg_port, required_email=email, timeout=60)

        conf1 = _fetch_and_validate_exports(
            api, ns, email, client1['subId'], server, priv1, domain, sub_domain, public_address, awg_port, ca_path,
        )
        checks['client_config'] = 'PASS'
        checks['ui_api'] = 'PASS'

        neg_spec = WORK / 'neg-wg.private.json'
        neg_spec.write_text(json.dumps({
            'client_private_key': priv1,
            'allowed_ips': client1['allowedIPs'],
            'server_public_key': server['publicKey'],
            'public_address': public_address,
            'port': awg_port,
            'mtu': server.get('mtu', awg31.DEFAULT_MTU),
        }))
        neg_spec.chmod(0o600)
        _run('ip', 'netns', 'exec', ns, sys.executable, str(Path(__file__).resolve()), '--client-plain-wg', '--client-spec', str(neg_spec))
        report['negative_plain_wg_rejected'] = 'PASS'

        def run_awg_phase(conf_text, expected):
            setconf_text, addr_cidr, mtu = awg31.conf_to_setconf(
                conf_text,
                endpoint_override=f'{public_address}:{awg_port}',
                allowed_ips_override=f'{TARGET_IP}/32',
            )
            setconf_path = WORK / 'awg31.private.setconf'
            setconf_path.write_text(setconf_text)
            setconf_path.chmod(0o600)
            spec_path = WORK / 'awg31-spec.private.json'
            spec_path.write_text(json.dumps({
                'setconf_path': str(setconf_path),
                'address_cidr': addr_cidr,
                'mtu': mtu,
            }))
            spec_path.chmod(0o600)
            cmd = ['ip', 'netns', 'exec', ns, sys.executable, str(Path(__file__).resolve()), '--client-awg', '--client-spec', str(spec_path)]
            if not expected:
                cmd.append('--negative')
            _run(*cmd, timeout=70)

        run_awg_phase(conf1, expected=True)
        checks['handshake'] = 'PASS'
        checks['tcp_traffic'] = 'PASS'
        checks['udp_traffic'] = 'PASS'

        # Key rotation via clients/update/:email
        priv2, pub2 = awg31.generate_keypair()
        client2 = awg31.build_client_payload(
            email, client_ip, priv2, pub2, keep_alive=25, enable=True, sub_id=client1['subId'],
        )
        api.call('clients/update/' + urllib.parse.quote(email, safe=''), client2)
        time.sleep(1.5)
        _wait_server_ready(awg_port, required_email=email, timeout=60)
        run_awg_phase(conf1, expected=False)
        conf2 = _fetch_and_validate_exports(
            api, ns, email, client2['subId'], server, priv2, domain, sub_domain, public_address, awg_port, ca_path,
        )
        run_awg_phase(conf2, expected=True)

        # Disable & re-enable
        api.call('clients/update/' + urllib.parse.quote(email, safe=''), {**client2, 'enable': False})
        _wait_server_ready(awg_port, absent_email=email, timeout=60)
        run_awg_phase(conf2, expected=False)
        api.call('clients/update/' + urllib.parse.quote(email, safe=''), client2)
        _wait_server_ready(awg_port, required_email=email, timeout=60)
        run_awg_phase(conf2, expected=True)

        # Panel restart & persistence verification
        _run('systemctl', 'restart', awg31.PANEL_UNIT)
        new_panel_pid = _wait_server_ready(awg_port, required_email=email, timeout=60)
        awg31.verify_live_listener(awg_port, new_panel_pid)
        refetched_inbounds = api.call('inbounds/list') or []
        refetched_row = next((r for r in refetched_inbounds if r.get('tag') == 'AMNEZIAWG-3.1'), None)
        if not refetched_row or not refetched_row.get('enable'):
            raise RuntimeError('AMNEZIAWG-3.1 inbound missing or disabled after restart')
        refetched_clients = native.object_value(refetched_row['settings']).get('clients', [])
        persisted = next((c for c in refetched_clients if c.get('email') == email), None)
        if not persisted or persisted.get('publicKey') != pub2 or not persisted.get('enable'):
            raise RuntimeError('rotated AWG 3.1 client failed persistence after restart')
        run_awg_phase(conf2, expected=True)
        checks['restart'] = 'PASS'
        checks['persistence'] = 'PASS'

        # Delete client & verify revocation
        api.call('clients/del/' + urllib.parse.quote(email, safe=''), {})
        created_email = None
        _wait_server_ready(awg_port, absent_email=email, timeout=60)
        run_awg_phase(conf2, expected=False)
        awg31.verify_live_listener(awg_port, new_panel_pid)
        checks['crud'] = 'PASS'

        report['tcp_payload_bytes'] = 65536
        report['udp_datagrams'] = 16
        report['udp_payload_bytes_per_datagram'] = 512
        report['status'] = 'PASS' if all(v == 'PASS' for v in checks.values()) else 'FAIL'
    finally:
        if created_email is not None:
            try:
                api.call('clients/del/' + urllib.parse.quote(created_email, safe=''), {})
            except Exception:
                pass
        if origin_proc is not None:
            origin_proc.terminate()
            try:
                origin_proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                origin_proc.kill()
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(report, indent=2) + '\n')
        try:
            out_file.chmod(0o600)
        except OSError:
            pass
    return report


@unittest.skipUnless(
    os.environ.get('PREVIEW08_RUN_E2E') == '1',
    'Requires live Debian 13 lab VM with PREVIEW08_RUN_E2E=1',
)
class TestAmneziaWG31E2E(unittest.TestCase):
    def test_end_to_end(self):
        report = run_e2e(
            ca_path=os.environ.get('PREVIEW08_CA', DEFAULT_CA),
            output_path=os.environ.get('PREVIEW08_OUTPUT', DEFAULT_OUTPUT),
            ns=os.environ.get('PREVIEW08_NS', DEFAULT_NS),
        )
        self.assertEqual(report['status'], 'PASS', json.dumps(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ca', default=DEFAULT_CA)
    parser.add_argument('--output', default=DEFAULT_OUTPUT)
    parser.add_argument('--ns', default=DEFAULT_NS)
    parser.add_argument('--origin', action='store_true')
    parser.add_argument('--client-awg', action='store_true')
    parser.add_argument('--client-plain-wg', action='store_true')
    parser.add_argument('--client-spec')
    parser.add_argument('--negative', action='store_true')
    parser.add_argument('--fetch-sub', action='store_true')
    parser.add_argument('--sub-url')
    parser.add_argument('--sub-host')
    parser.add_argument('--public-address')
    parser.add_argument('--sub-output')
    args = parser.parse_args()

    if args.origin:
        _serve_origin()
        return
    if args.client_awg:
        _client_awg_exercise(args.client_spec, expected=not args.negative)
        return
    if args.client_plain_wg:
        _client_plain_wg_negative(args.client_spec)
        return
    if args.fetch_sub:
        _fetch_sub_file(args.sub_url, args.sub_host, args.public_address, args.ca, Path(args.sub_output))
        return

    report = run_e2e(ca_path=args.ca, output_path=args.output, ns=args.ns)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['status'] == 'PASS' else 1)


if __name__ == '__main__':
    main()
