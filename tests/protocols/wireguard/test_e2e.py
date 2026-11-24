"""Live Debian 13 laboratory E2E verification for native WireGuard (no AWG binaries).

Imports cleanly on any platform. Unit discovery skips the live test unless
PREVIEW08_RUN_E2E=1 is set; direct CLI execution runs the full E2E suite.
"""
import argparse
import base64
import copy
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
import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_DIR = REPO_ROOT / 'release'
if str(RELEASE_DIR) not in sys.path:
    sys.path.insert(0, str(RELEASE_DIR))

import preview_wireguard as wg

DATA_DIR = Path('/var/lib/3xui-pro-fork')
VPN_STATE = DATA_DIR / 'preview-vpn-inbounds.json'
LAB_MARKER = Path('/var/lib/3xui-preview08-lab')
DEFAULT_CA_CANDIDATES = (
    Path('/var/lib/3xui-preview-acme/config/live/3xui-preview/fullchain.pem'),
    Path('/tmp/preview06a-ca/root.pem'),
    Path('/tmp/preview06a-ca/ca.pem'),
)

ORIGIN_IP = '10.77.5.2'
TARGET_IP = '198.18.0.10'
ORIGIN_PORT = 18099
DEFAULT_NS = 'preview-client'
WG_IFACE = 'p08wg0'
LOCAL_HTTP_PROXY_PORT = 19819
LOCAL_SOCKS_PROXY_PORT = 19820
TCP_PAYLOAD_BYTES = 65536
UDP_PACKETS = 16
UDP_PACKET_BYTES = 512


def _load_native():
    import preview_panel_inbounds as native
    return native


def _resolve_ca(ca_arg):
    if ca_arg:
        ca_path = Path(ca_arg)
        if not ca_path.is_file():
            raise RuntimeError(f'CA file not found: {ca_path}')
        return str(ca_path)
    for candidate in DEFAULT_CA_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError('no CA certificate found; pass --ca explicitly')


class _OriginHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        data = self.rfile.read(length)
        self.send_response(200)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data[::-1])

    def log_message(self, *_args):
        pass


def _serve_origin():
    http_server = ThreadingHTTPServer((ORIGIN_IP, ORIGIN_PORT), _OriginHandler)
    threading.Thread(target=http_server.serve_forever, daemon=True).start()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.bind((ORIGIN_IP, ORIGIN_PORT))
        while True:
            data, address = udp.recvfrom(8192)
            udp.sendto(data[::-1], address)


def _run_cmd(*args, input_text=None, timeout=30, check=True):
    proc = subprocess.run(
        args,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f'command {args[0]} failed with exit={proc.returncode}')
    return proc


def _wait_tcp_port(host, port, process=None, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError('background process exited unexpectedly during startup')
        try:
            with socket.create_connection((host, port), timeout=0.3):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f'timed out waiting for TCP {host}:{port}')


def _wait_wg_ready(native, wg_port, timeout=45):
    deadline = time.monotonic() + timeout
    stable = 0
    while time.monotonic() < deadline:
        try:
            native.verify_ready()
            xray_pid = native.native_pid()
            wg.verify_live_listener(wg_port, xray_pid)
            live_inbounds = native.core_api('lsi', '-isOnlyTags=false').get('inbounds', [])
            if not any(item.get('tag') == wg.WG_TAG for item in live_inbounds):
                raise RuntimeError('WIREGUARD inbound not active in Xray core')
            stable += 1
            if stable >= 2:
                return xray_pid
        except (RuntimeError, OSError, ValueError, KeyError):
            stable = 0
        time.sleep(0.25)
    raise RuntimeError('WireGuard Xray readiness check timed out')


def _verify_lab_environment(native):
    if os.name != 'posix' or os.geteuid() != 0:
        raise RuntimeError('WireGuard E2E requires root on Debian 13')
    web = native.private_json(native.WEB_STATE)
    pub_addr = ipaddress.ip_address(web['public_address'])
    if pub_addr.version != 4 or not any(pub_addr in net for net in wg.RFC1918_NETWORKS):
        raise RuntimeError('WireGuard E2E refused: RFC1918 laboratory public_address required')
    if LAB_MARKER.exists() or LAB_MARKER.is_symlink():
        native.ownership.regular_root_file(LAB_MARKER, private=True)
        if LAB_MARKER.read_text(encoding='utf-8').strip() != 'PREVIEW-XONIX-08':
            raise RuntimeError('invalid PREVIEW-XONIX-08 laboratory marker')
    return web


def _locate_wg_inbound(native, api):
    rows = api.call('inbounds/list') or []
    matches = [r for r in rows if r.get('tag') == wg.WG_TAG or r.get('protocol') == wg.WG_PROTOCOL]
    if len(matches) != 1:
        raise RuntimeError(f'expected exactly 1 WIREGUARD inbound, found {len(matches)}')
    row = matches[0]
    if row.get('tag') != wg.WG_TAG or row.get('protocol') != wg.WG_PROTOCOL:
        raise RuntimeError('WIREGUARD inbound tag/protocol mismatch')
    if not row.get('enable'):
        raise RuntimeError('WIREGUARD inbound is disabled')

    if VPN_STATE.exists() or VPN_STATE.is_symlink():
        vpn_state = native.private_json(VPN_STATE)
        if vpn_state.get('profiles', {}).get(wg.WG_TAG) != row.get('id'):
            raise RuntimeError('WIREGUARD inbound ID differs from preview-vpn-inbounds.json')
        if vpn_state.get('ports', {}).get(wg.WG_TAG) != row.get('port'):
            raise RuntimeError('WIREGUARD port differs from preview-vpn-inbounds.json')

    settings = native.object_value(row['settings'])
    stream_settings = native.object_value(row.get('streamSettings', {}))
    wg.verify_inbound_settings(settings, stream_settings)
    if row.get('port') == wg.AWG_RESERVED_PORT:
        raise RuntimeError('WIREGUARD must never bind AWG port 29177')
    return row, settings


def _configure_lab_origin_for_wg(native, api, wg_port):
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

    changed = False
    outbounds = template.setdefault('outbounds', [])
    existing_out = [o for o in outbounds if o.get('tag') == 'preview08-origin']
    if not existing_out:
        outbounds.append(expected_outbound)
        changed = True
    elif existing_out[0] != expected_outbound:
        raise RuntimeError('existing preview08-origin outbound differs unexpectedly')

    rules = template.setdefault('routing', {}).setdefault('rules', [])
    origin_rules = [r for r in rules if r.get('outboundTag') == 'preview08-origin']
    if not origin_rules:
        rules.insert(0, {
            'type': 'field',
            'inboundTag': [wg.WG_TAG],
            'ip': [f'{TARGET_IP}/32'],
            'port': str(ORIGIN_PORT),
            'outboundTag': 'preview08-origin',
        })
        changed = True
    else:
        rule = origin_rules[0]
        if rule.get('ip') != [f'{TARGET_IP}/32'] or str(rule.get('port')) != str(ORIGIN_PORT):
            raise RuntimeError('existing preview08-origin routing rule targets different endpoint')
        tags = list(rule.get('inboundTag') or [])
        if wg.WG_TAG not in tags:
            tags.append(wg.WG_TAG)
            rule['inboundTag'] = tags
            changed = True

    if changed:
        api.call(
            'xray/update',
            {
                'xraySetting': json.dumps(template),
                'outboundTestUrl': raw.get('outboundTestUrl', ''),
            },
            form=True,
        )
        _run_cmd('systemctl', 'restart', native.PANEL_UNIT)
        _wait_wg_ready(native, wg_port)


def _detect_client_driver(ns):
    if not shutil.which('wg'):
        return 'xray-wireguard-outbound'
    _run_cmd('ip', 'netns', 'exec', ns, 'ip', 'link', 'del', WG_IFACE, check=False)
    probe = _run_cmd('ip', 'netns', 'exec', ns, 'ip', 'link', 'add', 'dev', WG_IFACE, 'type', 'wireguard', check=False)
    if probe.returncode == 0:
        _run_cmd('ip', 'netns', 'exec', ns, 'ip', 'link', 'del', WG_IFACE, check=False)
        return 'linux-kernel-wireguard'
    return 'xray-wireguard-outbound'


def _split_allowed_ips(value):
    if isinstance(value, str):
        return [part.strip() for part in value.split(',') if part.strip()]
    return list(value or [])


def _extract_wireguard_uris(obj):
    uris = []
    if isinstance(obj, str):
        for line in obj.splitlines():
            line = line.strip()
            if line.lower().startswith('wireguard://'):
                uris.append(line)
    elif isinstance(obj, list):
        for item in obj:
            uris.extend(_extract_wireguard_uris(item))
    elif isinstance(obj, dict):
        for value in obj.values():
            uris.extend(_extract_wireguard_uris(value))
    return uris


def _contains_awg_key(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(key, str) and key in wg.AWG_CONTAMINATION_KEYS:
                return key
            found = _contains_awg_key(value)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _contains_awg_key(item)
            if found:
                return found
    return None


def _ns_https_get(ns, url, ca_path):
    script = (
        'import ssl, sys, urllib.request\n'
        'ctx = ssl.create_default_context(cafile=sys.argv[2])\n'
        'opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx))\n'
        'with opener.open(sys.argv[1], timeout=20) as resp:\n'
        '    sys.stdout.buffer.write(resp.read())\n'
    )
    proc = subprocess.run(
        ['ip', 'netns', 'exec', ns, sys.executable, '-c', script, url, ca_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f'subscription HTTPS GET failed with exit={proc.returncode}')
    return proc.stdout.decode('utf-8')


def _decode_sub_body(body):
    if '://' in body:
        return body
    stripped = ''.join(body.split())
    padded = stripped + ('=' * (-len(stripped) % 4))
    return base64.b64decode(padded, validate=False).decode('utf-8')


def _verify_client_exports(api, ns, ca_path, sub_domain, share_host, wg_port, server_pub, client, mtu):
    links_obj = api.call('clients/links/' + urllib.parse.quote(client['email'], safe=''))
    panel_uris = _extract_wireguard_uris(links_obj)
    if not panel_uris:
        raise RuntimeError('clients/links returned no wireguard:// URI')
    for uri in panel_uris:
        wg.validate_wireguard_link(
            uri,
            expected_host=share_host,
            expected_port=wg_port,
            expected_server_pub=server_pub,
            expected_client_priv=client['privateKey'],
            expected_address=client['allowedIPs'][0],
        )

    sub_raw = _ns_https_get(ns, f'https://{sub_domain}/sub/{client["subId"]}', ca_path)
    sub_text = _decode_sub_body(sub_raw)
    sub_uris = _extract_wireguard_uris(sub_text)
    matching_sub = [
        uri for uri in sub_uris
        if re.search(rf':{wg_port}(?:[/?#]|$)', uri)
    ]
    if not matching_sub:
        raise RuntimeError('/sub/<subId> missing matching wireguard:// entry')
    for uri in matching_sub:
        wg.validate_wireguard_link(
            uri,
            expected_host=share_host,
            expected_port=wg_port,
            expected_server_pub=server_pub,
            expected_client_priv=client['privateKey'],
            expected_address=client['allowedIPs'][0],
        )

    json_raw = _ns_https_get(ns, f'https://{sub_domain}/json/{client["subId"]}', ca_path)
    json_data = json.loads(json_raw)
    configs = json_data if isinstance(json_data, list) else [json_data]
    wg_outbounds = []
    for cfg in configs:
        for outbound in cfg.get('outbounds', []):
            if outbound.get('protocol') == 'wireguard':
                wg_outbounds.append(outbound)
    if not wg_outbounds:
        raise RuntimeError('/json/<subId> missing wireguard outbound')
    matched_json = False
    for outbound in wg_outbounds:
        bad_awg = _contains_awg_key(outbound)
        if bad_awg:
            raise RuntimeError(f'/json/<subId> contains forbidden AWG parameter: {bad_awg}')
        settings = outbound.get('settings', {})
        peers = settings.get('peers', [])
        if settings.get('secretKey') == client['privateKey'] and any(
            p.get('publicKey') == server_pub and p.get('endpoint') == f'{share_host}:{wg_port}'
            for p in peers
        ):
            matched_json = True
    if not matched_json:
        raise RuntimeError('/json/<subId> wireguard outbound key/endpoint mismatch')

    conf_text = wg.render_client_conf(
        endpoint_host=share_host,
        port=wg_port,
        server_public_key=server_pub,
        client=client,
        allowed_ips=(f'{TARGET_IP}/32',),
        mtu=mtu,
    )
    parsed_conf = wg.parse_client_conf(conf_text)
    if parsed_conf['interface']['private_key'] != client['privateKey']:
        raise RuntimeError('rendered .conf key mismatch')


def _kernel_wg_worker(fixture, expected):
    setconf_lines = [
        '[Interface]',
        f"PrivateKey = {fixture['client']['privateKey']}",
        '',
        '[Peer]',
        f"PublicKey = {fixture['server_public_key']}",
        f'AllowedIPs = {TARGET_IP}/32',
        f"Endpoint = {fixture['endpoint_host']}:{fixture['port']}",
        'PersistentKeepalive = 5',
    ]
    if fixture['client'].get('preSharedKey'):
        setconf_lines.append(f"PresharedKey = {fixture['client']['preSharedKey']}")

    with tempfile.TemporaryDirectory() as tmp:
        conf_path = Path(tmp) / 'wg.setconf'
        conf_path.write_text('\n'.join(setconf_lines) + '\n', encoding='utf-8')
        conf_path.chmod(0o600)

        _run_cmd('ip', 'link', 'del', WG_IFACE, check=False)
        _run_cmd('ip', 'link', 'add', 'dev', WG_IFACE, 'type', 'wireguard')
        try:
            _run_cmd('wg', 'setconf', WG_IFACE, str(conf_path))
            _run_cmd('ip', 'address', 'add', fixture['client']['allowedIPs'][0], 'dev', WG_IFACE)
            _run_cmd('ip', 'link', 'set', 'dev', WG_IFACE, 'mtu', str(fixture['mtu']), 'up')
            _run_cmd('ip', 'route', 'replace', f'{TARGET_IP}/32', 'dev', WG_IFACE)

            tcp_ok = False
            conn = http.client.HTTPConnection(TARGET_IP, ORIGIN_PORT, timeout=15 if expected else 3)
            payload = secrets.token_bytes(TCP_PAYLOAD_BYTES)
            try:
                conn.request('POST', '/verified', payload)
                resp = conn.getresponse()
                tcp_ok = resp.status == 200 and resp.read() == payload[::-1]
            except (OSError, http.client.HTTPException):
                tcp_ok = False
            finally:
                conn.close()
            if tcp_ok != expected:
                raise RuntimeError(f'kernel WireGuard TCP verification failed (expected={expected}, actual={tcp_ok})')

            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                udp.settimeout(8 if expected else 2)
                for _ in range(UDP_PACKETS if expected else 1):
                    dgram = secrets.token_bytes(UDP_PACKET_BYTES)
                    udp.sendto(dgram, (TARGET_IP, ORIGIN_PORT))
                    udp_ok = False
                    try:
                        udp_ok = udp.recv(8192) == dgram[::-1]
                    except socket.timeout:
                        udp_ok = False
                    if udp_ok != expected:
                        raise RuntimeError(
                            f'kernel WireGuard UDP verification failed (expected={expected}, actual={udp_ok})'
                        )

            handshake_ts = 0
            if expected:
                handshakes = _run_cmd('wg', 'show', WG_IFACE, 'latest-handshakes').stdout
                for line in handshakes.splitlines():
                    parts = line.split()
                    if len(parts) >= 2 and int(parts[1]) > 0:
                        handshake_ts = max(handshake_ts, int(parts[1]))
                if handshake_ts <= 0:
                    raise RuntimeError('kernel WireGuard handshake timestamp missing (> 0 required)')
        finally:
            _run_cmd('ip', 'link', 'del', WG_IFACE, check=False)

    print(json.dumps({'handshake': 'PASS' if expected else 'DENIED', 'latest_handshake': handshake_ts}))


def _socks5_udp_check(proxy_port, expected):
    with socket.create_connection(('127.0.0.1', proxy_port), timeout=5) as ctrl:
        ctrl.sendall(b'\x05\x01\x00')
        if ctrl.recv(2) != b'\x05\x00':
            raise RuntimeError('SOCKS5 auth negotiation failed')
        ctrl.sendall(b'\x05\x03\x00\x01\x00\x00\x00\x00\x00\x00')
        resp = ctrl.recv(64)
        if resp[:4] != b'\x05\x00\x00\x01':
            raise RuntimeError('SOCKS5 UDP associate failed')
        relay_addr = (socket.inet_ntoa(resp[4:8]), int.from_bytes(resp[8:10], 'big'))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.settimeout(8 if expected else 2)
            for _ in range(UDP_PACKETS if expected else 1):
                dgram = secrets.token_bytes(UDP_PACKET_BYTES)
                header = b'\x00\x00\x00\x01' + socket.inet_aton(TARGET_IP) + ORIGIN_PORT.to_bytes(2, 'big')
                udp.sendto(header + dgram, relay_addr)
                udp_ok = False
                try:
                    reply = udp.recv(8192)
                    udp_ok = reply[10:] == dgram[::-1]
                except socket.timeout:
                    udp_ok = False
                if udp_ok != expected:
                    raise RuntimeError(
                        f'Xray WireGuard UDP verification failed (expected={expected}, actual={udp_ok})'
                    )


def _xray_wg_worker(fixture, expected):
    peer = {
        'publicKey': fixture['server_public_key'],
        'endpoint': f"{fixture['endpoint_host']}:{fixture['port']}",
        'allowedIPs': [f'{TARGET_IP}/32'],
        'keepAlive': 5,
    }
    if fixture['client'].get('preSharedKey'):
        peer['preSharedKey'] = fixture['client']['preSharedKey']

    config = {
        'log': {'loglevel': 'warning'},
        'inbounds': [
            {'listen': '127.0.0.1', 'port': LOCAL_HTTP_PROXY_PORT, 'protocol': 'http', 'settings': {}},
            {
                'listen': '127.0.0.1',
                'port': LOCAL_SOCKS_PROXY_PORT,
                'protocol': 'socks',
                'settings': {'auth': 'noauth', 'udp': True},
            },
        ],
        'outbounds': [{
            'protocol': 'wireguard',
            'settings': {
                'secretKey': fixture['client']['privateKey'],
                'address': fixture['client']['allowedIPs'],
                'noKernelTun': True,
                'mtu': fixture['mtu'],
                'peers': [peer],
            },
        }],
    }

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        cfg_path = tmp_path / 'wg-client.json'
        log_path = tmp_path / 'wg-client.log'
        cfg_path.write_text(json.dumps(config), encoding='utf-8')
        cfg_path.chmod(0o600)
        _run_cmd(wg.XRAY_BIN, 'run', '-test', '-config', str(cfg_path))
        with log_path.open('wb') as log:
            proc = subprocess.Popen([wg.XRAY_BIN, 'run', '-config', str(cfg_path)], stdout=log, stderr=log)
            try:
                _wait_tcp_port('127.0.0.1', LOCAL_HTTP_PROXY_PORT, process=proc, timeout=25)
                tcp_ok = False
                conn = http.client.HTTPConnection('127.0.0.1', LOCAL_HTTP_PROXY_PORT, timeout=15 if expected else 3)
                payload = secrets.token_bytes(TCP_PAYLOAD_BYTES)
                try:
                    conn.request('POST', f'http://{TARGET_IP}:{ORIGIN_PORT}/verified', payload)
                    resp = conn.getresponse()
                    tcp_ok = resp.status == 200 and resp.read() == payload[::-1]
                except (OSError, http.client.HTTPException):
                    tcp_ok = False
                finally:
                    conn.close()
                if tcp_ok != expected:
                    raise RuntimeError(
                        f'Xray WireGuard TCP verification failed (expected={expected}, actual={tcp_ok})'
                    )
                _socks5_udp_check(LOCAL_SOCKS_PROXY_PORT, expected)
            finally:
                proc.terminate()
                proc.wait(timeout=8)

    print(json.dumps({'handshake': 'PASS' if expected else 'DENIED', 'latest_handshake': None}))


def run_e2e(ca_path=None, output_path='/tmp/preview08-wireguard-results.json', ns=DEFAULT_NS):
    """Execute full live WireGuard E2E suite on Debian 13 lab VM and write sanitized report."""
    native = _load_native()
    resolved_ca = _resolve_ca(ca_path)
    web = _verify_lab_environment(native)
    api = native.api_client()

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
        'protocol': wg.WG_TAG,
        'status': 'FAIL',
        'client_driver': 'NOT_SELECTED',
        'port': None,
        'checks': checks,
        'details': {},
    }

    work_dir = Path(tempfile.mkdtemp(prefix='preview08-wg-'))
    work_dir.chmod(0o700)
    origin_proc = None
    created_email = None

    try:
        row, settings = _locate_wg_inbound(native, api)
        wg_inbound_id = row['id']
        wg_port = row['port']
        wg_mtu = settings['mtu']
        subnet_str = f"{settings['subnetIp']}/{settings['subnetCidr']}"
        server_pub = wg.public_key_from_private(settings['secretKey'])
        share_host = row.get('shareAddr') or web['domain']
        sub_domain = web['layout']['subscription_domain']
        report['port'] = wg_port

        xray_pid = _wait_wg_ready(native, wg_port)
        checks['backend'] = 'PASS'
        checks['inbound'] = 'PASS'
        report['details']['xray_pid'] = xray_pid

        _configure_lab_origin_for_wg(native, api, wg_port)

        origin_proc = subprocess.Popen(
            ['ip', 'netns', 'exec', ns, sys.executable, str(Path(__file__).resolve()), '--origin'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_tcp_port(ORIGIN_IP, ORIGIN_PORT, process=origin_proc, timeout=30)

        client_driver = _detect_client_driver(ns)
        report['client_driver'] = client_driver

        wg_net, _, _ = wg.validate_subnet(subnet_str)
        used_cidrs = []
        for existing in settings.get('clients', []):
            used_cidrs.extend(existing.get('allowedIPs', []))
        for item in api.call('clients/list') or []:
            rec = item.get('client', item)
            for cidr in _split_allowed_ips(rec.get('allowedIPs')):
                try:
                    if ipaddress.ip_interface(cidr).ip in wg_net:
                        used_cidrs.append(cidr)
                except ValueError:
                    pass

        client_ip = wg.allocate_client_ip(subnet_str, used_cidrs)
        email = 'preview08-wg-' + secrets.token_hex(4)
        client = wg.build_client_payload(email=email, client_ip=client_ip, keep_alive=25)
        api.call('clients/add', {'client': client, 'inboundIds': [wg_inbound_id]})
        created_email = email
        _wait_wg_ready(native, wg_port)

        fetched = api.call('clients/get/' + urllib.parse.quote(email, safe=''))
        fetched_client = fetched.get('client', fetched)
        if (
            fetched_client.get('email') != email
            or not fetched_client.get('enable')
            or fetched_client.get('privateKey') != client['privateKey']
            or fetched_client.get('publicKey') != client['publicKey']
            or _split_allowed_ips(fetched_client.get('allowedIPs')) != client['allowedIPs']
            or wg_inbound_id not in (fetched.get('inboundIds') or [])
        ):
            raise RuntimeError('clients/get returned mismatched WireGuard client state')
        checks['ui_api'] = 'PASS'

        _verify_client_exports(
            api=api,
            ns=ns,
            ca_path=resolved_ca,
            sub_domain=sub_domain,
            share_host=share_host,
            wg_port=wg_port,
            server_pub=server_pub,
            client=client,
            mtu=wg_mtu,
        )
        checks['client_config'] = 'PASS'

        def transfer(client_obj, stage, expected=True):
            fixture_path = work_dir / f'{stage}.private.json'
            fixture_data = {
                'endpoint_host': web['public_address'],
                'port': wg_port,
                'server_public_key': server_pub,
                'client': client_obj,
                'mtu': wg_mtu,
            }
            fixture_path.write_text(json.dumps(fixture_data), encoding='utf-8')
            fixture_path.chmod(0o600)
            cmd = [
                'ip', 'netns', 'exec', ns, sys.executable,
                str(Path(__file__).resolve()),
                '--client-driver', client_driver,
                '--fixture', str(fixture_path),
            ]
            if not expected:
                cmd.append('--negative')
            try:
                proc = _run_cmd(*cmd, timeout=70)
                return json.loads(proc.stdout.strip().splitlines()[-1])
            finally:
                fixture_path.unlink(missing_ok=True)

        initial_info = transfer(client, 'initial', expected=True)
        checks['handshake'] = 'PASS'
        checks['tcp_traffic'] = 'PASS'
        checks['udp_traffic'] = 'PASS'
        report['details']['initial_handshake_epoch'] = initial_info.get('latest_handshake')
        report['details']['tcp_payload_bytes'] = TCP_PAYLOAD_BYTES
        report['details']['udp_payload_bytes'] = UDP_PACKETS * UDP_PACKET_BYTES

        old_client = copy.deepcopy(client)
        client = wg.rotate_client_keys(client)
        api.call('clients/update/' + urllib.parse.quote(email, safe=''), client)
        _wait_wg_ready(native, wg_port)
        time.sleep(1.0)
        transfer(old_client, 'old-key-denied', expected=False)
        transfer(client, 'rotated-key-allowed', expected=True)

        disabled_client = copy.deepcopy(client)
        disabled_client['enable'] = False
        api.call('clients/update/' + urllib.parse.quote(email, safe=''), disabled_client)
        _wait_wg_ready(native, wg_port)
        time.sleep(1.0)
        transfer(client, 'disabled-denied', expected=False)

        client['enable'] = True
        api.call('clients/update/' + urllib.parse.quote(email, safe=''), client)
        _wait_wg_ready(native, wg_port)
        time.sleep(1.0)
        transfer(client, 'reenabled-allowed', expected=True)
        checks['crud'] = 'PASS'

        _run_cmd('systemctl', 'restart', native.PANEL_UNIT)
        post_restart_pid = _wait_wg_ready(native, wg_port)
        persisted = api.call('clients/get/' + urllib.parse.quote(email, safe='')).get('client', {})
        if (
            persisted.get('privateKey') != client['privateKey']
            or persisted.get('publicKey') != client['publicKey']
            or _split_allowed_ips(persisted.get('allowedIPs')) != client['allowedIPs']
            or persisted.get('subId') != client['subId']
            or not persisted.get('enable')
        ):
            raise RuntimeError('WireGuard client state did not persist across service restart')
        checks['persistence'] = 'PASS'
        transfer(client, 'after-restart', expected=True)
        checks['restart'] = 'PASS'
        report['details']['post_restart_xray_pid'] = post_restart_pid

        api.call('clients/del/' + urllib.parse.quote(email, safe=''), {})
        created_email = None
        remaining_emails = {
            str(item.get('client', item).get('email', '')).casefold()
            for item in (api.call('clients/list') or [])
        }
        if email.casefold() in remaining_emails:
            raise RuntimeError('deleted WireGuard client still listed in clients/list')
        _wait_wg_ready(native, wg_port)
        time.sleep(1.0)
        transfer(client, 'deleted-denied', expected=False)
        report['details']['delete_verified'] = 'PASS'

        if all(value == 'PASS' for value in checks.values()):
            report['status'] = 'PASS'
    finally:
        if created_email:
            try:
                api.call('clients/del/' + urllib.parse.quote(created_email, safe=''), {})
            except Exception:
                pass
        if origin_proc is not None:
            origin_proc.terminate()
            origin_proc.wait(timeout=8)
        shutil.rmtree(work_dir, ignore_errors=True)
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

    return report


class WireGuardLiveE2ETests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get('PREVIEW08_RUN_E2E') == '1',
        'live Debian 13 WireGuard E2E requires PREVIEW08_RUN_E2E=1',
    )
    def test_wireguard_live_e2e(self):
        report = run_e2e(
            ca_path=os.environ.get('PREVIEW08_CA'),
            output_path=os.environ.get('PREVIEW08_WG_OUTPUT', '/tmp/preview08-wireguard-results.json'),
            ns=os.environ.get('PREVIEW08_NS', DEFAULT_NS),
        )
        self.assertEqual(report['status'], 'PASS')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ca', default=None, help='Optional CA PEM path for HTTPS subscription checks')
    parser.add_argument('--output', default='/tmp/preview08-wireguard-results.json')
    parser.add_argument('--ns', default=DEFAULT_NS)
    parser.add_argument('--origin', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument(
        '--client-driver',
        choices=('linux-kernel-wireguard', 'xray-wireguard-outbound'),
        help=argparse.SUPPRESS,
    )
    parser.add_argument('--fixture', help=argparse.SUPPRESS)
    parser.add_argument('--negative', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.origin:
        _serve_origin()
        return

    if args.client_driver:
        if not args.fixture:
            raise RuntimeError('--fixture is required for client worker')
        fixture = json.loads(Path(args.fixture).read_text(encoding='utf-8'))
        expected = not args.negative
        if args.client_driver == 'linux-kernel-wireguard':
            _kernel_wg_worker(fixture, expected)
        else:
            _xray_wg_worker(fixture, expected)
        return

    report = run_e2e(ca_path=args.ca, output_path=args.output, ns=args.ns)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['status'] == 'PASS' else 1)


if __name__ == '__main__':
    main()
