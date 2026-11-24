"""Live disposable-lab E2E acceptance test for Hysteria2 v2 (skipped unless PREVIEW08_RUN_E2E=1)."""
import argparse
import copy
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import secrets
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

HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
RELEASE = ROOT / 'release'
if str(RELEASE) not in sys.path:
    sys.path.insert(0, str(RELEASE))

import preview_hysteria2 as hy2

XRAY = Path('/opt/3xui-pro-fork/panel/bin/xray-linux-amd64')
LAB_MARKER = Path('/var/lib/3xui-preview08-lab')
ORIGIN = '10.77.5.2'
TARGET = '198.18.0.10'
ORIGIN_PORT = 18099
DEFAULT_NS = 'preview-client'
DEFAULT_OUTPUT = '/tmp/preview08-hysteria2-results.json'
TCP_PAYLOAD_BYTES = 65536
UDP_PACKET_COUNT = 16
UDP_PACKET_BYTES = 512
RFC1918 = tuple(ipaddress.ip_network(net) for net in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


class _OriginHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        data = self.rfile.read(length)
        self.send_response(200)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data[::-1])

    def log_message(self, *_):
        pass


def _run_origin():
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind((ORIGIN, ORIGIN_PORT))
    server = ThreadingHTTPServer((ORIGIN, ORIGIN_PORT), _OriginHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print('PREVIEW08_HY2_ORIGIN_READY', flush=True)
    try:
        while True:
            data, address = udp.recvfrom(8192)
            udp.sendto(data[::-1], address)
    finally:
        server.shutdown()
        udp.close()


def _ssl_context(ca_file):
    ctx = ssl.create_default_context(cafile=str(ca_file))
    if hasattr(ssl, 'VERIFY_X509_PARTIAL_CHAIN'):
        ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    return ctx


def _fetch_sub_in_ns(stdin_data):
    request = json.loads(stdin_data)
    sub_domain = request['sub_domain']
    public_address = request['public_address']
    sub_id = request['sub_id']
    ca_file = request['ca_file']

    original_getaddrinfo = socket.getaddrinfo

    def resolved_getaddrinfo(host, port, *args, **kwargs):
        target_host = public_address if host == sub_domain else host
        return original_getaddrinfo(target_host, port, *args, **kwargs)

    socket.getaddrinfo = resolved_getaddrinfo
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=_ssl_context(ca_file)),
        )
        req = urllib.request.Request(
            f'https://{sub_domain}/sub/{urllib.parse.quote(sub_id, safe="")}',
            headers={'User-Agent': 'v2rayNG/1.9'},
        )
        with opener.open(req, timeout=20) as response:
            body = response.read().decode('utf-8')
            if response.status != 200 or not body.strip():
                raise RuntimeError('subscription HTTP response empty or invalid')
            sys.stdout.write(body)
    finally:
        socket.getaddrinfo = original_getaddrinfo


def _pick_local_ports():
    socks = []
    ports = []
    try:
        for _ in range(2):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(('127.0.0.1', 0))
            ports.append(s.getsockname()[1])
            socks.append(s)
    finally:
        for s in socks:
            s.close()
    return ports[0], ports[1]


def _wait_tcp_port(process, port, timeout=30.0):
    deadline = time.monotonic() + timeout
    while process.poll() is None and time.monotonic() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f'local client port {port} did not become ready')


def _socks5_udp_echo(socks_port, expected):
    with socket.create_connection(('127.0.0.1', socks_port), timeout=5) as control:
        control.sendall(b'\x05\x01\x00')
        if control.recv(2) != b'\x05\x00':
            raise RuntimeError('SOCKS5 greeting failed')
        control.sendall(b'\x05\x03\x00\x01\x00\x00\x00\x00\x00\x00')
        reply = control.recv(64)
        if len(reply) < 10 or reply[:4] != b'\x05\x00\x00\x01':
            raise RuntimeError('SOCKS5 UDP ASSOCIATE rejected')
        relay_addr = (socket.inet_ntoa(reply[4:8]), int.from_bytes(reply[8:10], 'big'))
        if relay_addr[0] == '0.0.0.0':
            relay_addr = ('127.0.0.1', relay_addr[1])
        packet_header = b'\x00\x00\x00\x01' + socket.inet_aton(TARGET) + ORIGIN_PORT.to_bytes(2, 'big')
        count = UDP_PACKET_COUNT if expected else 1
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.settimeout(8.0 if expected else 2.5)
            for _ in range(count):
                payload = secrets.token_bytes(UDP_PACKET_BYTES)
                udp.sendto(packet_header + payload, relay_addr)
                try:
                    response = udp.recv(8192)
                except OSError:
                    if expected:
                        return False
                    continue
                matched = len(response) > 10 and response[10:] == payload[::-1]
                if not matched and expected:
                    return False
                if matched and not expected:
                    return True
        return expected


def _run_client_probe(config_path, log_path, expected):
    outbound = json.loads(Path(config_path).read_text(encoding='utf-8'))
    http_port, socks_port = _pick_local_ports()
    client_config = {
        'log': {'loglevel': 'warning'},
        'inbounds': [
            {'listen': '127.0.0.1', 'port': http_port, 'protocol': 'http', 'settings': {}},
            {'listen': '127.0.0.1', 'port': socks_port, 'protocol': 'socks', 'settings': {'auth': 'noauth', 'udp': True}},
        ],
        'outbounds': [outbound],
    }
    runtime_cfg = Path(config_path).with_suffix('.runtime.json')
    runtime_cfg.write_text(json.dumps(client_config), encoding='utf-8')
    runtime_cfg.chmod(0o600)
    try:
        subprocess.run(
            [str(XRAY), 'run', '-test', '-config', str(runtime_cfg)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
        )
        with Path(log_path).open('ab') as log_file:
            process = subprocess.Popen(
                [str(XRAY), 'run', '-config', str(runtime_cfg)],
                stdout=log_file,
                stderr=log_file,
            )
            try:
                _wait_tcp_port(process, http_port)
                _wait_tcp_port(process, socks_port)
                tcp_ok = False
                conn = http.client.HTTPConnection('127.0.0.1', http_port, timeout=15 if expected else 3)
                try:
                    payload = secrets.token_bytes(TCP_PAYLOAD_BYTES)
                    conn.request('POST', f'http://{TARGET}:{ORIGIN_PORT}/verified', payload)
                    response = conn.getresponse()
                    tcp_ok = response.status == 200 and response.read() == payload[::-1]
                except (OSError, http.client.HTTPException):
                    tcp_ok = False
                finally:
                    conn.close()
                udp_ok = _socks5_udp_echo(socks_port, expected)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    finally:
        if runtime_cfg.exists():
            runtime_cfg.unlink()

    result = {'tcp_ok': bool(tcp_ok), 'udp_ok': bool(udp_ok), 'expected': bool(expected)}
    print(json.dumps(result), flush=True)
    raise SystemExit(0 if (tcp_ok is expected and udp_ok is expected) else 1)


def _assert_lab_environment(native):
    if os.geteuid() != 0:
        raise RuntimeError('root is required to run live Hysteria2 E2E on the lab VM')
    native.ownership.regular_root_file(LAB_MARKER, private=True)
    if LAB_MARKER.read_text(encoding='utf-8').strip() != 'PREVIEW-XONIX-08':
        raise RuntimeError('PREVIEW-XONIX-08 lab marker mismatch')
    web = native.private_json(native.WEB_STATE)
    address = ipaddress.ip_address(web['public_address'])
    if address.version != 4 or not any(address in net for net in RFC1918):
        raise RuntimeError('live E2E refused outside RFC1918 laboratory bind')
    panel_state = native.private_json(native.two.PANEL_STATE)
    native.verify_ready()
    return web, panel_state


def _wait_server_ready(native, hy2_port, timeout=45.0):
    deadline = time.monotonic() + timeout
    stable = 0
    while time.monotonic() < deadline:
        try:
            native.verify_ready()
            xray_pid = native.native_pid()
            hy2.verify_live_listener(hy2_port, xray_pid)
            live_tags = {item.get('tag') for item in native.core_api('lsi', '-isOnlyTags=false').get('inbounds', [])}
            if hy2.TAG not in live_tags:
                raise RuntimeError('HYSTERIA2 inbound not yet active in Xray runtime')
            stable += 1
            if stable >= 2:
                return xray_pid
        except (RuntimeError, OSError, ValueError, KeyError):
            stable = 0
        time.sleep(0.25)
    raise RuntimeError('Hysteria2 server readiness timed out')


def _verify_inbound_and_listener(api, native, public_address, domain):
    rows = api.call('inbounds/list') or []
    matches = [row for row in rows if row.get('tag') == hy2.TAG]
    if len(matches) != 1:
        raise RuntimeError('expected exactly one HYSTERIA2 inbound in panel')
    row = matches[0]
    if not row.get('enable'):
        raise RuntimeError('HYSTERIA2 inbound is disabled')
    if row.get('protocol') != hy2.PROTOCOL:
        raise RuntimeError('HYSTERIA2 inbound protocol mismatch')
    if row.get('listen') != public_address:
        raise RuntimeError('HYSTERIA2 listen address mismatch')

    settings = native.object_value(row['settings'])
    stream = native.object_value(row['streamSettings'])
    hy2.validate_inbound_payload(
        {
            'tag': row.get('tag'),
            'remark': row.get('remark'),
            'enable': row.get('enable'),
            'listen': row.get('listen'),
            'port': row.get('port'),
            'protocol': row.get('protocol'),
            'settings': settings,
            'streamSettings': stream,
        }
    )
    tls = stream['tlsSettings']
    if tls.get('serverName') != domain:
        raise RuntimeError('HYSTERIA2 TLS serverName does not match primary domain')
    cert_entry = tls['certificates'][0]
    if cert_entry['certificateFile'] != hy2.DEFAULT_CERT.as_posix() or cert_entry['keyFile'] != hy2.DEFAULT_KEY.as_posix():
        raise RuntimeError('HYSTERIA2 certificate path must reuse existing managed ACME lineage')
    native.ownership.regular_root_file(hy2.DEFAULT_CERT.resolve(strict=True), private=False)
    native.ownership.regular_root_file(hy2.DEFAULT_KEY.resolve(strict=True), private=True)

    xray_pid = native.native_pid()
    hy2.verify_live_listener(row['port'], xray_pid)
    live_tags = {item.get('tag') for item in native.core_api('lsi', '-isOnlyTags=false').get('inbounds', [])}
    if hy2.TAG not in live_tags:
        raise RuntimeError('HYSTERIA2 missing from live Xray runtime')
    return row['id'], row['port']


def _ensure_lab_routing(api, native, hy2_port):
    xray_data = native.object_value(api.call('xray/', {}))
    original = copy.deepcopy(xray_data)
    template = copy.deepcopy(native.object_value(xray_data['xraySetting']))
    expected_outbound = {
        'tag': 'preview08-origin',
        'protocol': 'freedom',
        'settings': {
            'redirect': f'{ORIGIN}:{ORIGIN_PORT}',
            'finalRules': [
                {'action': 'allow', 'network': 'tcp,udp', 'ip': [f'{ORIGIN}/32'], 'port': ORIGIN_PORT},
                {'action': 'block'},
            ],
        },
    }
    outbounds = template.setdefault('outbounds', [])
    matching_outbounds = [o for o in outbounds if o.get('tag') == 'preview08-origin']
    changed = False
    if matching_outbounds:
        if matching_outbounds != [expected_outbound]:
            raise RuntimeError('existing preview08-origin outbound differs from lab topology')
    else:
        outbounds.append(expected_outbound)
        changed = True

    rules = template.setdefault('routing', {}).setdefault('rules', [])
    matching_rules = [r for r in rules if r.get('outboundTag') == 'preview08-origin']
    if matching_rules:
        rule = matching_rules[0]
        if rule.get('ip') != [f'{TARGET}/32'] or str(rule.get('port')) != str(ORIGIN_PORT):
            raise RuntimeError('existing preview08-origin routing rule differs from lab topology')
        inbound_tags = list(rule.get('inboundTag', []))
        if hy2.TAG not in inbound_tags:
            inbound_tags.append(hy2.TAG)
            rule['inboundTag'] = inbound_tags
            changed = True
    else:
        rules.insert(
            0,
            {
                'type': 'field',
                'inboundTag': [hy2.TAG],
                'ip': [f'{TARGET}/32'],
                'port': str(ORIGIN_PORT),
                'outboundTag': 'preview08-origin',
            },
        )
        changed = True

    if changed:
        api.call(
            'xray/update',
            {
                'xraySetting': json.dumps(template),
                'outboundTestUrl': xray_data.get('outboundTestUrl', ''),
            },
            form=True,
        )
        subprocess.run(['systemctl', 'restart', native.PANEL_UNIT], check=True, timeout=30)
        _wait_server_ready(native, hy2_port)
    return changed, original


def _start_origin(ns):
    proc = subprocess.Popen(
        ['ip', 'netns', 'exec', ns, sys.executable, str(HERE), '--origin'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError('controlled origin exited during startup')
        line = proc.stdout.readline().strip()
        if line == 'PREVIEW08_HY2_ORIGIN_READY':
            return proc
    proc.terminate()
    raise RuntimeError('controlled origin startup timed out')


def _fetch_exported_links(api, ns, sub_domain, public_address, ca_file, email, sub_id, domain, hy2_port, expected_auth):
    quoted_email = urllib.parse.quote(email, safe='')
    api_links_obj = api.call(f'clients/links/{quoted_email}')
    api_links = [
        uri for uri in hy2.extract_hysteria2_links(api_links_obj)
        if hy2.parse_hysteria2_link(uri)['port'] == hy2_port
    ]
    if not api_links:
        raise RuntimeError('clients/links returned no hysteria2:// link for HYSTERIA2 port')
    hy2.validate_hysteria2_link(api_links[0], domain, hy2_port, expected_auth, domain)

    sub_req = json.dumps(
        {
            'sub_domain': sub_domain,
            'public_address': public_address,
            'sub_id': sub_id,
            'ca_file': str(ca_file),
        }
    )
    sub_proc = subprocess.run(
        ['ip', 'netns', 'exec', ns, sys.executable, str(HERE), '--fetch-sub'],
        input=sub_req,
        text=True,
        capture_output=True,
        timeout=30,
    )
    if sub_proc.returncode != 0:
        raise RuntimeError('HTTPS /sub/<subId> fetch failed inside client namespace')
    sub_links = [
        uri for uri in hy2.extract_hysteria2_links(sub_proc.stdout)
        if hy2.parse_hysteria2_link(uri)['port'] == hy2_port
    ]
    if not sub_links:
        raise RuntimeError('/sub/<subId> returned no hysteria2:// link for HYSTERIA2 port')
    hy2.validate_hysteria2_link(sub_links[0], domain, hy2_port, expected_auth, domain)
    return api_links[0], sub_links[0]


def _transfer_check(ns, work_dir, stage_name, outbound, expected):
    cfg_path = work_dir / f'{stage_name}.outbound.private.json'
    log_path = work_dir / f'{stage_name}.private.log'
    cfg_path.write_text(json.dumps(outbound), encoding='utf-8')
    cfg_path.chmod(0o600)

    attempts = 2
    for attempt in range(attempts):
        proc = subprocess.run(
            [
                'ip',
                'netns',
                'exec',
                ns,
                sys.executable,
                str(HERE),
                '--client-config',
                str(cfg_path),
                *([] if expected else ['--negative']),
                '--log-file',
                str(log_path),
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        if proc.returncode == 0:
            return
        if attempt + 1 < attempts:
            time.sleep(1.0)
    raise RuntimeError(f'{stage_name} transfer check failed (expected={expected})')


def run_e2e(ca_file, output_path, ns=DEFAULT_NS):
    """Execute the full live Hysteria2 E2E acceptance suite and write a sanitized JSON report."""
    os.umask(0o077)
    import preview_panel_inbounds as native

    ca_resolved = Path(ca_file)
    if not ca_resolved.is_file():
        raise RuntimeError('explicit --ca file does not exist')

    checks = {
        'inbound_and_listener_ownership': 'NOT_RUN',
        'client_create_and_export': 'NOT_RUN',
        'initial_transfer': 'NOT_RUN',
        'rotate_auth_old_denied': 'NOT_RUN',
        'rotate_auth_new_transfer': 'NOT_RUN',
        'disabled_denied': 'NOT_RUN',
        'reenabled_transfer': 'NOT_RUN',
        'restart_persistence_listener': 'NOT_RUN',
        'restart_persistence_transfer': 'NOT_RUN',
        'deleted_denied': 'NOT_RUN',
    }
    report = {
        'protocol': hy2.TAG,
        'status': 'FAIL',
        'scope': 'disposable Debian13 native panel',
        'tcp_payload_bytes_per_direction': TCP_PAYLOAD_BYTES,
        'udp_packets': UDP_PACKET_COUNT,
        'udp_packet_bytes_per_direction': UDP_PACKET_BYTES,
        'checks': checks,
        'export_validation': {
            'clients_links_valid': False,
            'subscription_sub_valid': False,
            'security': 'tls',
            'alpn': ['h3'],
            'sni_matches_domain': False,
            'tls_verify_enforced': True,
        },
    }

    web, panel_state = _assert_lab_environment(native)
    domain = web['domain']
    sub_domain = panel_state['layout']['subscription_domain']
    public_address = web['public_address']
    report['domain'] = domain
    report['subscription_domain'] = sub_domain

    api = native.api_client()
    email = f'hy2-e2e-{secrets.token_hex(6)}'
    quoted_email = urllib.parse.quote(email, safe='')
    old_auth = hy2.generate_auth()
    sub_id = secrets.token_urlsafe(24)
    routing_changed = False
    original_xray = None
    origin_proc = None
    client_created = False
    hy2_port = None

    with tempfile.TemporaryDirectory(prefix='preview08-hy2-') as tmp_dir:
        work_dir = Path(tmp_dir)
        os.chmod(work_dir, 0o700)
        try:
            inbound_id, hy2_port = _verify_inbound_and_listener(api, native, public_address, domain)
            report['port'] = hy2_port
            checks['inbound_and_listener_ownership'] = 'PASS'

            routing_changed, original_xray = _ensure_lab_routing(api, native, hy2_port)
            origin_proc = _start_origin(ns)

            add_payload = hy2.build_client_add_payload(
                inbound_id,
                email,
                auth=old_auth,
                enable=True,
                sub_id=sub_id,
            )
            api.call('clients/add', add_payload)
            client_created = True
            time.sleep(0.8)

            api_link, sub_link = _fetch_exported_links(
                api, ns, sub_domain, public_address, ca_resolved, email, sub_id, domain, hy2_port, old_auth
            )
            api_outbound = hy2.client_outbound_from_link(api_link, public_address, ca_resolved)
            old_outbound = hy2.client_outbound_from_link(sub_link, public_address, ca_resolved)
            if api_outbound != old_outbound:
                raise RuntimeError('clients/links and /sub/<subId> produced mismatched client outbounds')
            report['export_validation'].update(
                {
                    'clients_links_valid': True,
                    'subscription_sub_valid': True,
                    'sni_matches_domain': True,
                }
            )
            checks['client_create_and_export'] = 'PASS'

            _transfer_check(ns, work_dir, 'initial', old_outbound, expected=True)
            checks['initial_transfer'] = 'PASS'

            new_auth = hy2.generate_auth()
            rotate_payload = hy2.build_client_update_payload(email, enable=True, auth=new_auth, sub_id=sub_id)
            api.call(f'clients/update/{quoted_email}', rotate_payload)
            time.sleep(1.0)

            rotated_api_link, rotated_sub_link = _fetch_exported_links(
                api, ns, sub_domain, public_address, ca_resolved, email, sub_id, domain, hy2_port, new_auth
            )
            new_outbound = hy2.client_outbound_from_link(rotated_sub_link, public_address, ca_resolved)
            if hy2.client_outbound_from_link(rotated_api_link, public_address, ca_resolved) != new_outbound:
                raise RuntimeError('rotated clients/links and /sub/<subId> produced mismatched client outbounds')

            _transfer_check(ns, work_dir, 'rotate_old_denied', old_outbound, expected=False)
            checks['rotate_auth_old_denied'] = 'PASS'
            _transfer_check(ns, work_dir, 'rotate_new', new_outbound, expected=True)
            checks['rotate_auth_new_transfer'] = 'PASS'

            disable_payload = hy2.build_client_update_payload(email, enable=False, sub_id=sub_id)
            api.call(f'clients/update/{quoted_email}', disable_payload)
            time.sleep(1.0)
            _transfer_check(ns, work_dir, 'disabled', new_outbound, expected=False)
            checks['disabled_denied'] = 'PASS'

            reenable_payload = hy2.build_client_update_payload(email, enable=True, sub_id=sub_id)
            api.call(f'clients/update/{quoted_email}', reenable_payload)
            time.sleep(1.0)
            _fetch_exported_links(
                api, ns, sub_domain, public_address, ca_resolved, email, sub_id, domain, hy2_port, new_auth
            )
            _transfer_check(ns, work_dir, 'reenabled', new_outbound, expected=True)
            checks['reenabled_transfer'] = 'PASS'

            subprocess.run(['systemctl', 'restart', native.PANEL_UNIT], check=True, timeout=30)
            _wait_server_ready(native, hy2_port)
            checks['restart_persistence_listener'] = 'PASS'

            _fetch_exported_links(
                api, ns, sub_domain, public_address, ca_resolved, email, sub_id, domain, hy2_port, new_auth
            )
            _transfer_check(ns, work_dir, 'after_restart', new_outbound, expected=True)
            checks['restart_persistence_transfer'] = 'PASS'

            api.call(f'clients/del/{quoted_email}', {})
            client_created = False
            time.sleep(1.0)
            _transfer_check(ns, work_dir, 'deleted', new_outbound, expected=False)
            checks['deleted_denied'] = 'PASS'

            report['status'] = 'PASS'
        except Exception as exc:
            for key, value in checks.items():
                if value == 'NOT_RUN':
                    checks[key] = 'FAIL'
                    break
            report['error_type'] = type(exc).__name__
            report['status'] = 'FAIL'
        finally:
            if client_created:
                try:
                    api.call(f'clients/del/{quoted_email}', {})
                except Exception:
                    pass
            if origin_proc is not None:
                origin_proc.terminate()
                try:
                    origin_proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    origin_proc.kill()
                    origin_proc.wait(timeout=5)
            if routing_changed and original_xray is not None:
                try:
                    api.call(
                        'xray/update',
                        {
                            'xraySetting': json.dumps(native.object_value(original_xray['xraySetting'])),
                            'outboundTestUrl': original_xray.get('outboundTestUrl', ''),
                        },
                        form=True,
                    )
                    subprocess.run(['systemctl', 'restart', native.PANEL_UNIT], check=True, timeout=30)
                    if hy2_port:
                        _wait_server_ready(native, hy2_port)
                except Exception:
                    pass
            if output_path:
                out_file = Path(output_path)
                out_file.parent.mkdir(parents=True, exist_ok=True)
                out_file.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


@unittest.skipUnless(
    os.environ.get('PREVIEW08_RUN_E2E') == '1',
    'Set PREVIEW08_RUN_E2E=1 on disposable Debian 13 lab VM to run live Hysteria2 E2E',
)
class Hysteria2E2ETest(unittest.TestCase):
    def test_hysteria2_live_e2e(self):
        report = run_e2e(
            ca_file=os.environ.get('PREVIEW08_CA', hy2.DEFAULT_CERT.as_posix()),
            output_path=os.environ.get('PREVIEW08_OUTPUT', DEFAULT_OUTPUT),
            ns=os.environ.get('PREVIEW08_NS', DEFAULT_NS),
        )
        self.assertEqual(report['status'], 'PASS', msg=json.dumps(report))


def main(argv=None):
    """CLI entrypoint for live Hysteria2 E2E acceptance and netns helper subprocesses."""
    parser = argparse.ArgumentParser(description='Hysteria2 live laboratory E2E verification')
    parser.add_argument('--ca', default=hy2.DEFAULT_CERT.as_posix(), help='Path to explicit TLS verification CA/cert PEM')
    parser.add_argument('--output', default=DEFAULT_OUTPUT, help='Sanitized JSON report output path')
    parser.add_argument('--ns', default=DEFAULT_NS, help='Client network namespace name')
    parser.add_argument('--origin', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--fetch-sub', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--client-config', help=argparse.SUPPRESS)
    parser.add_argument('--log-file', help=argparse.SUPPRESS)
    parser.add_argument('--negative', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.origin:
        _run_origin()
        return 0
    if args.fetch_sub:
        _fetch_sub_in_ns(sys.stdin.read())
        return 0
    if args.client_config:
        if not args.log_file:
            raise SystemExit('--log-file required with --client-config')
        _run_client_probe(args.client_config, args.log_file, expected=not args.negative)
        return 0

    report = run_e2e(args.ca, args.output, ns=args.ns)
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
