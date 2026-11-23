"""Exercise the generated P0/P1/P3 clients against installed TCP 443."""
import argparse
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import socket
import ssl
import subprocess
import tempfile
import threading
import time


def wait_for_proxy(process, port):
    until = time.monotonic() + 12
    while process.poll() is None and time.monotonic() < until:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.3):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError('Xray client did not open its local proxy')


class Origin(BaseHTTPRequestHandler):
    def do_POST(self):
        data = self.rfile.read(int(self.headers['Content-Length']))
        body = data[::-1]
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def exercise(binary, cert, profile, config, origin_address):
    ctx = ssl.create_default_context(cafile=cert)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'client.json'
        path.write_text(json.dumps(config))
        path.chmod(0o600)
        args = [str(binary), 'run', '-config', str(path)]
        subprocess.run([str(binary), 'run', '-test', '-config', str(path)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        with (Path(tmp) / 'client.log').open('w+') as log:
            client = subprocess.Popen(args, stdout=log, stderr=log)
            try:
                port = config['inbounds'][0]['port']
                wait_for_proxy(client, port)
                payload = secrets.token_bytes(65536)
                connection = http.client.HTTPSConnection('127.0.0.1', port, timeout=25, context=ctx)
                connection.set_tunnel(origin_address, 18099)
                try:
                    connection.request('POST', '/transferred', body=payload)
                    response = connection.getresponse()
                    if response.status != 200 or response.read() != payload[::-1]:
                        raise RuntimeError('HTTPS origin reply differs')
                finally:
                    connection.close()
            except Exception as exc:
                raise RuntimeError(f'{profile} tunnel failed: {type(exc).__name__}: {exc}') from exc
            finally:
                if client.poll() is None:
                    client.terminate()
                client.wait(timeout=8)
            log.seek(0)
            if profile in ('P0', 'P1') and not re.search(r'HTTP\s+version\s+2\b', log.read(), re.I):
                raise RuntimeError(f'{profile} client did not report HTTP version 2')
        print(f'{profile}_HANDSHAKE_DATA_PASS uploaded=65536 downloaded=65536', flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary', type=Path)
    p.add_argument('clients', type=Path)
    p.add_argument('cert', type=Path)
    p.add_argument('key', type=Path)
    p.add_argument('--server-log', type=Path)
    p.add_argument('--origin-address', default='10.77.5.2')
    p.add_argument('--p1-ca', type=Path, required=True)
    args = p.parse_args()
    config = json.loads(args.clients.read_text())
    for profile in ('P0', 'P1', 'P3'):
        dial = config[profile]['outbounds'][0]
        assert dial['settings']['vnext'][0]['port'] == {'P0':8443,'P1':443,'P3':9443}[profile]
        assert dial['settings']['vnext'][0]['address'] == 'de126.alexsun55.ru'
        if profile == 'P3':
            assert dial['settings']['vnext'][0]['users'][0]['flow'] == 'xtls-rprx-vision'
        if profile == 'P1':
            tls = dial['streamSettings']['tlsSettings']
            assert tls['alpn'] == ['h2'] and not tls.get('allowInsecure')
            tls['certificates'] = [{'certificateFile': str(args.p1_ca), 'usage': 'verify'}]
    with ThreadingHTTPServer((args.origin_address, 18099), Origin) as origin:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(args.cert, args.key)
        origin.socket = context.wrap_socket(origin.socket, server_side=True)
        thread = threading.Thread(target=origin.serve_forever, daemon=True)
        thread.start()
        try:
            for profile in ('P0', 'P1', 'P3'):
                exercise(args.binary, args.cert, profile, config[profile], args.origin_address)
        finally:
            origin.shutdown()
            thread.join(timeout=5)
    if args.server_log:
        logs = args.server_log.read_text()
    else:
        logs = subprocess.check_output(['journalctl', '-u', '3xui-preview-xray.service',
                                         '--since=-2min', '-o', 'cat', '--no-pager'], text=True)
    for profile in ('P0', 'P1', 'P3'):
        if not any(re.search(rf'\[{profile} (?:->|>>) direct\]', line) and ' accepted ' in line and f'preview-{profile}' in line and
                   f'{args.origin_address}:18099' in line for line in logs.splitlines()):
            raise RuntimeError(f'{profile} is missing server correlation')
        print(f'{profile}_SERVER_CORRELATION_PASS', flush=True)


if __name__ == '__main__':
    main()
