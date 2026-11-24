"""Single disposable-lab acceptance of panel-owned WG/AWG3.1/HY2.

Uses native supported API and independent client processes; emits no credentials.
Never run against a production host. Existing P0/P1/P3 acceptance is separate.
"""
import argparse
import copy
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.parse

os.umask(0o077)
HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'release'))
import preview_panel_inbounds as native

DATA = Path('/var/lib/3xui-pro-fork')
STATE = DATA / 'preview-vpn-inbounds.json'
WORK = Path('/tmp/preview08-acceptance')
XRAY = '/opt/3xui-pro-fork/panel/bin/xray-linux-amd64'
AWG = '/opt/3xui-pro-fork/awg/awg'
AWG_GO = '/opt/3xui-pro-fork/awg/amneziawg-go'
TAGS = ['WIREGUARD', 'AMNEZIAWG-3.1', 'HYSTERIA2']
ORIGIN = '10.77.5.2'
TARGET = '198.18.0.10'
PORT = 18099
NS = 'preview-client'


def run(*args, **kwargs):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, **kwargs)
    if result.returncode:
        diagnostic = WORK / ('command-failure-' + str(time.time_ns()) + '.private.log')
        output = result.stdout + result.stderr
        diagnostic.write_bytes(output.encode() if isinstance(output, str) else output)
        raise RuntimeError('external command rejected, exit=' + str(result.returncode) + '; private diagnostics retained')
    return result


def guard():
    native.ownership.regular_root_file(Path('/var/lib/3xui-preview08-lab'), private=True)
    assert Path('/var/lib/3xui-preview08-lab').read_text().strip() == 'PREVIEW-XONIX-08'
    assert native.private_json(native.WEB_STATE)['public_address'] == '10.77.5.1'


class Origin(BaseHTTPRequestHandler):
    def do_POST(self):
        data = self.rfile.read(int(self.headers['Content-Length']))
        self.send_response(200)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data[::-1])

    def log_message(self, *_):
        pass


def origin():
    server = ThreadingHTTPServer((ORIGIN, PORT), Origin)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.bind((ORIGIN, PORT))
        while True:
            data, address = udp.recvfrom(8192)
            udp.sendto(data[::-1], address)


def wait_port(process, port):
    until = time.monotonic() + 30
    while process.poll() is None and time.monotonic() < until:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.2):
                return
        except OSError:
            time.sleep(.1)
    raise RuntimeError('client local proxy did not start')


def wait_server_ready(state):
    """Wait for real listener owners and unchanged native clients after restart."""
    until = time.monotonic() + 45
    stable = 0
    while time.monotonic() < until:
        try:
            native.verify_ready()
            xray_pid = native.native_pid()
            panel_pid = int(native.ownership.service_properties(native.PANEL_UNIT)['MainPID'])
            for tag in TAGS:
                output = run('ss', '-H', '-lunp', 'sport = :' + str(state['ports'][tag]), text=True).stdout
                owners = {int(pid) for pid in re.findall(r'pid=(\d+)', output)}
                expected = panel_pid if tag == 'AMNEZIAWG-3.1' else xray_pid
                if not expected or owners != {expected}:
                    raise RuntimeError('native VPN listener owner not ready')
            stable += 1
            if stable >= 2:
                return
        except (RuntimeError, OSError, ValueError, KeyError):
            stable = 0
        time.sleep(.25)
    raise RuntimeError('server readiness timed out; actual UDP owners/native clients not stable')


def wireguard_outbound(state):
    client = state['clients']['WIREGUARD']
    settings = state['settings']['WIREGUARD']
    public = run(AWG, 'pubkey', input=settings['secretKey'] + '\n', text=True).stdout.strip()
    peer = {'publicKey': public, 'endpoint': state['public_address'] + ':' + str(state['ports']['WIREGUARD']),
            'allowedIPs': [TARGET + '/32'], 'keepAlive': 10}
    if client.get('preSharedKey'):
        peer['preSharedKey'] = client['preSharedKey']
    return {'protocol': 'wireguard', 'settings': {'secretKey': client['privateKey'],
            'address': client['allowedIPs'], 'noKernelTun': True, 'mtu': settings.get('mtu', 1420), 'peers': [peer]}}


def hysteria_outbound(state, ca):
    return {'protocol': 'hysteria', 'settings': {'version': 2, 'address': state['public_address'],
            'port': state['ports']['HYSTERIA2']}, 'streamSettings': {'network': 'hysteria', 'security': 'tls',
            'hysteriaSettings': {'version': 2, 'auth': state['clients']['HYSTERIA2']['auth']},
            'tlsSettings': {'serverName': state['domain'], 'alpn': ['h3'],
                'certificates': [{'certificateFile': ca, 'usage': 'verify'}]}}}


def socks_udp(proxy, expected):
    with socket.create_connection(('127.0.0.1', proxy), timeout=5) as control:
        control.sendall(b'\x05\x01\x00')
        assert control.recv(2) == b'\x05\x00'
        control.sendall(b'\x05\x03\x00\x01\x00\x00\x00\x00\x00\x00')
        response = control.recv(64)
        assert response[:4] == b'\x05\x00\x00\x01'
        address = (socket.inet_ntoa(response[4:8]), int.from_bytes(response[8:10], 'big'))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.settimeout(8 if expected else 2)
            for _ in range(16 if expected else 1):
                data = secrets.token_bytes(512)
                udp.sendto(b'\x00\x00\x00\x01' + socket.inet_aton(TARGET) + PORT.to_bytes(2, 'big') + data, address)
                success = False
                try:
                    result = udp.recv(8192)
                    success = result[10:] == data[::-1]
                except socket.timeout:
                    pass
                if success != expected:
                    raise RuntimeError('UDP authorization or payload differs')


def proxy_transfer(tag, state, ca, expected):
    outbound = wireguard_outbound(state) if tag == 'WIREGUARD' else hysteria_outbound(state, ca)
    config = {'log': {'loglevel': 'warning'}, 'inbounds': [
        {'listen': '127.0.0.1', 'port': 19809, 'protocol': 'http', 'settings': {}},
        {'listen': '127.0.0.1', 'port': 19810, 'protocol': 'socks', 'settings': {'auth': 'noauth', 'udp': True}}],
        'outbounds': [outbound]}
    path = WORK / ('client-' + tag + '.private.json')
    path.write_text(json.dumps(config)); path.chmod(0o600)
    run(XRAY, 'run', '-test', '-config', str(path))
    with (WORK / ('client-' + tag + '.private.log')).open('ab') as log:
        process = subprocess.Popen([XRAY, 'run', '-config', str(path)], stdout=log, stderr=log)
        try:
            wait_port(process, 19809)
            connection = http.client.HTTPConnection('127.0.0.1', 19809, timeout=15 if expected else 3)
            data = secrets.token_bytes(65536)
            success = False
            try:
                connection.request('POST', 'http://' + TARGET + ':' + str(PORT) + '/verified', data)
                response = connection.getresponse()
                success = response.status == 200 and response.read() == data[::-1]
            except (OSError, http.client.HTTPException):
                pass
            finally:
                connection.close()
            if success != expected:
                raise RuntimeError('TCP authorization or payload differs')
            socks_udp(19810, expected)
        finally:
            process.terminate()
            process.wait(timeout=8)


def awg_transfer(state, expected):
    client = state['clients']['AMNEZIAWG-3.1']
    server = state['settings']['AMNEZIAWG-3.1']['server']
    public = server.get('publicKey') or run(AWG, 'pubkey', input=server['privateKey'] + '\n', text=True).stdout.strip()
    lines = ['[Interface]', 'PrivateKey = ' + client['privateKey'], 'ListenPort = 0']
    mapping = {'jc': 'Jc', 'jmin': 'Jmin', 'jmax': 'Jmax',
               **{'s'+str(n): 'S'+str(n) for n in range(1, 5)},
               **{'h'+str(n): 'H'+str(n) for n in range(1, 5)},
               **{'i'+str(n): 'I'+str(n) for n in range(1, 6)},
               'headerProtectionKey': 'HeaderProtectionKey', 'contentPaddingAddition': 'ContentPaddingAddition',
               'rekeyAfterTime': 'RekeyAfterTime', 'rekeyTimeout': 'RekeyTimeout',
               'rejectAfterTime': 'RejectAfterTime', 'keepaliveTimeout': 'KeepaliveTimeout',
               'maxHandshakeAttempts': 'MaxHandshakeAttempts', 'randomTrailers': 'RandomTrailers',
               'disableCookies': 'DisableCookies'}
    for field, name in mapping.items():
        if field in server and server[field] not in ('', None):
            value = server[field]
            lines.append(name + ' = ' + (('on' if value else 'off') if isinstance(value, bool) else str(value)))
    lines += ['[Peer]', 'PublicKey = ' + public, 'AllowedIPs = ' + TARGET + '/32',
              'Endpoint = ' + state['public_address'] + ':29177', 'PersistentKeepalive = 5']
    if client.get('preSharedKey'):
        lines.append('PresharedKey = ' + client['preSharedKey'])
    path = WORK / 'awg-client.private.setconf'
    path.write_text('\n'.join(lines) + '\n'); path.chmod(0o600)
    assert not Path('/var/run/amneziawg/p08awg.sock').exists(), 'foreign test interface refused'
    with (WORK / 'awg-client.private.log').open('ab') as log:
        process = subprocess.Popen([AWG_GO, '-f', 'p08awg'], stdout=log, stderr=log)
        try:
            until = time.monotonic() + 30
            while not Path('/var/run/amneziawg/p08awg.sock').exists():
                if process.poll() is not None or time.monotonic() > until:
                    raise RuntimeError('AWG client did not start')
                time.sleep(.1)
            run(AWG, 'setconf', 'p08awg', str(path))
            run('ip', 'address', 'add', client['allowedIPs'][0], 'dev', 'p08awg')
            run('ip', 'link', 'set', 'dev', 'p08awg', 'mtu', str(server.get('mtu', 1420)), 'up')
            run('ip', 'route', 'add', TARGET + '/32', 'dev', 'p08awg')
            connection = http.client.HTTPConnection(TARGET, PORT, timeout=15 if expected else 3)
            data = secrets.token_bytes(65536)
            success = False
            try:
                connection.request('POST', '/verified', data)
                response = connection.getresponse()
                success = response.status == 200 and response.read() == data[::-1]
            except (OSError, http.client.HTTPException):
                pass
            finally:
                connection.close()
            if success != expected:
                raise RuntimeError('AWG TCP authorization or payload differs')
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                udp.settimeout(8 if expected else 2)
                for _ in range(16 if expected else 1):
                    data = secrets.token_bytes(512); udp.sendto(data, (TARGET, PORT)); success = False
                    try:
                        success = udp.recv(8192) == data[::-1]
                    except socket.timeout:
                        pass
                    if success != expected:
                        raise RuntimeError('AWG UDP authorization or payload differs')
            if expected:
                handshakes = run(AWG, 'show', 'p08awg', 'latest-handshakes', text=True).stdout
                assert any(int(line.split()[1]) > 0 for line in handshakes.splitlines()), 'AWG handshake missing'
        finally:
            process.terminate(); process.wait(timeout=8)


def configure_lab_origins(api):
    settings = native.object_value(api.call('xray/', {}))
    template = settings['xraySetting']
    expected_outbound = {'tag': 'preview08-origin', 'protocol': 'freedom', 'settings': {
        'redirect': ORIGIN + ':' + str(PORT), 'finalRules': [
            {'action': 'allow', 'network': 'tcp,udp', 'ip': [ORIGIN + '/32'], 'port': PORT}, {'action': 'block'}]}}
    expected_rule = {'type': 'field', 'inboundTag': TAGS, 'ip': [TARGET + '/32'],
                     'port': str(PORT), 'outboundTag': 'preview08-origin'}
    matching_outbounds = [o for o in template['outbounds'] if o.get('tag') == 'preview08-origin']
    rules = template.setdefault('routing', {}).setdefault('rules', [])
    matching_rules = [r for r in rules if r.get('outboundTag') == 'preview08-origin']
    if matching_outbounds or matching_rules:
        assert matching_outbounds == [expected_outbound] and matching_rules == [expected_rule], 'existing test routing differs'
        return
    template['outbounds'].append(expected_outbound)
    rules.insert(0, expected_rule)
    api.call('xray/update', {'xraySetting': json.dumps(template),
                           'outboundTestUrl': settings['outboundTestUrl']}, form=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', action='store_true')
    parser.add_argument('--client', choices=TAGS)
    parser.add_argument('--protocol', nargs='+', choices=TAGS,
                        help='Target only failed protocols; prior results remain separate evidence')
    parser.add_argument('--restart-only', action='store_true',
                        help='Recheck initial and post-restart transfer only; reuse separately recorded CRUD results')
    parser.add_argument('--negative', action='store_true')
    parser.add_argument('--ca', required=True)
    parser.add_argument('--output', default='/tmp/preview08-final-results.json')
    args = parser.parse_args()
    guard(); WORK.mkdir(mode=0o700, exist_ok=True)
    if args.origin:
        origin(); return
    state = native.private_json(STATE)
    if args.client:
        if args.client == 'AMNEZIAWG-3.1':
            awg_transfer(state, not args.negative)
        else:
            proxy_transfer(args.client, state, args.ca, not args.negative)
        return
    api = native.api_client()
    before = native.read_journal()
    native.verify_ready()
    selected = args.protocol or TAGS
    rows = {tag: {} for tag in selected}
    result = {'status': 'INCOMPLETE', 'scope': 'disposable Debian13 native panel',
              'targeted_recheck': bool(args.protocol or args.restart_only),
              'restart_only': args.restart_only, 'protocols': rows}
    snapshot = {x['id']: x for x in api.call('inbounds/list')}
    assert len(snapshot) == 6 and {x['tag'] for x in snapshot.values()} == set(native.TAGS.values()) | set(TAGS)
    configure_lab_origins(api)
    run('systemctl', 'restart', native.PANEL_UNIT)
    wait_server_ready(state)
    origin_process = subprocess.Popen(['ip', 'netns', 'exec', NS, 'python3', str(HERE), '--origin', '--ca', args.ca],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # The origin process also starts under TCG. Observe its listener instead
        # of treating a fixed delay as proof it is ready.
        wait_port_deadline = time.monotonic() + 30
        while True:
            assert origin_process.poll() is None, 'controlled origin exited during startup'
            try:
                with socket.create_connection((ORIGIN, PORT), timeout=.3):
                    break
            except OSError:
                if time.monotonic() >= wait_port_deadline:
                    raise RuntimeError('controlled origin startup timed out')
                time.sleep(.1)
        def transfer(tag, stage, negative=False):
            command = ['ip', 'netns', 'exec', NS, 'python3', str(HERE), '--client', tag, '--ca', args.ca]
            if negative:
                command.append('--negative')
            process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=70)
            (WORK / (tag + '-' + stage + '.private.log')).write_bytes(process.stdout + process.stderr)
            rows[tag][stage] = 'PASS' if process.returncode == 0 else 'FAIL'
            print(tag, stage, rows[tag][stage], flush=True)
            return process.returncode == 0
        for tag in selected:
            transfer(tag, 'initial')
        run('systemctl', 'restart', native.PANEL_UNIT)
        wait_server_ready(state)
        for tag in selected:
            transfer(tag, 'after_restart')
        for tag in ([] if args.restart_only else selected):
            client = copy.deepcopy(state['clients'][tag]); client['enable'] = False
            api.call('clients/update/' + urllib.parse.quote(client['email'], safe=''), client)
            time.sleep(.5)
            transfer(tag, 'disabled', negative=True)
            client['enable'] = True
            api.call('clients/update/' + urllib.parse.quote(client['email'], safe=''), client)
            time.sleep(.5)
            transfer(tag, 'reenabled')
            api.call('clients/del/' + urllib.parse.quote(client['email'], safe=''), {})
            time.sleep(.5)
            transfer(tag, 'deleted', negative=True)
            api.call('clients/add', {'client': state['clients'][tag], 'inboundIds': [state['profiles'][tag]]})
            time.sleep(.5)
            transfer(tag, 'recreated')
        active = {item['tag']: item for item in api.call('inbounds/list')}
        result['final_listeners'] = {}
        for tag in TAGS:
            assert active[tag]['enable'], 'test inbound disabled after CRUD'
            listeners = run('ss', '-H', '-lunp', 'sport = :' + str(state['ports'][tag]), text=True).stdout
            assert listeners.strip() and 'pid=' in listeners, 'UDP listener missing after CRUD'
            result['final_listeners'][tag] = 'PASS'
            if tag in rows:
                rows[tag]['final_listener'] = 'PASS'
        native.verify_ready()
        assert native.read_journal() == before, 'existing READY journal changed'
        result['existing_native_preserved'] = 'PASS'
        result['panel_six_records'] = 'PASS'
        result['tcp_payload_bytes_per_direction'] = 65536
        result['udp_payload_bytes_per_direction'] = 8192
        result['status'] = 'PASS' if all(v == 'PASS' for row in rows.values() for v in row.values()) else 'FAIL'
    finally:
        origin_process.terminate(); origin_process.wait(timeout=8)
        Path(args.output).write_text(json.dumps(result, indent=2) + '\n')
    raise SystemExit(0 if result['status'] == 'PASS' else 1)


if __name__ == '__main__':
    main()
