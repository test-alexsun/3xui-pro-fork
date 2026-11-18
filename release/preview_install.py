#!/usr/bin/env python3
"""Experimental Debian 13 preview installer. No binary upgrade is performed."""
import argparse
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'release'))
import install_candidate as candidate
import upgrade_candidate as ownership

DATA = Path('/var/lib/3xui-pro-fork')
WEB = Path('/var/www/3xui-pro-fork/decoy/index.html')
NGINX = Path('/etc/nginx/conf.d/3xui-pro-fork-preview.conf')
STATE = DATA / 'preview-web.json'


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeError('untrusted file: ' + str(path))


def atomic(path, data, mode):
    fd, name = tempfile.mkstemp(prefix='.preview-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            os.fchmod(f.fileno(), mode)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def verify_package(path):
    candidate.check_components(path)
    manifest = json.loads((path / 'components-manifest.json').read_text())
    if manifest.get('files') != ownership.PINNED_FILES:
        raise RuntimeError('component manifest differs from pinned baseline')
    if tuple(manifest.get(x) for x in ('panel', 'xray', 'awg_runtime', 'awg_tools')) != (
            '3.11.0', '26.11.9', '3.1.20260828', '3.1.20260812'):
        raise RuntimeError('unsupported component versions')
    for name in ('install_candidate.py', 'awg_config_candidate.py', 'awg_service.py',
                 '3xui-pro-fork.service', '3xui-pro-fork-awg.service'):
        if (path / name).is_symlink() or (path / name).read_bytes() != (REPO / 'release' / name).read_bytes():
            raise RuntimeError('candidate executable differs from reviewed source: ' + name)
    for name in ('panel/x-ui', 'panel/bin/xray-linux-amd64', 'awg/awg', 'awg/amneziawg-go'):
        head = (path / name).read_bytes()[:20]
        if head[:6] != b'\x7fELF\x02\x01' or head[18:20] != b'\x3e\x00':
            raise RuntimeError('not a Linux amd64 executable: ' + name)
    return manifest


def nginx_config(domain, port, sandbox=None):
    challenge = ('location ^~ /.well-known/acme-challenge/ { '
                 'root /var/www/3xui-pro-fork/decoy; try_files $uri =404; }') if sandbox else ''
    config = (f'''# Managed by 3xui-pro-fork preview; do not edit manually.
server {{
    listen {port};
    server_name {domain};
    autoindex off;
    {challenge}
    location = / {{ root /var/www/3xui-pro-fork/decoy; try_files /index.html =404; }}
    location ~ (^|/)\\. {{ return 404; }}
    location / {{ return 404; }}
}}
''')
    if sandbox:
        cert, key = sandbox
        config += f'''
server {{
    listen 127.0.0.1:18443 ssl;
    server_name {domain};
    ssl_certificate {cert};
    ssl_certificate_key {key};
    autoindex off;
    {challenge}
    location = / {{ root /var/www/3xui-pro-fork/decoy; try_files /index.html =404; }}
    location ~ (^|/)\\. {{ return 404; }}
    location / {{ return 404; }}
}}
server {{
    listen 127.0.0.1:18443 ssl;
    server_name panel.{domain};
    ssl_certificate {cert};
    ssl_certificate_key {key};
    location / {{
        proxy_pass http://127.0.0.1:2053;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $http_connection;
    }}
}}
'''
    return config.encode()


def check_http(domain, port, expected):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(f'http://127.0.0.1:{port}/', headers={'Host': domain})
    with opener.open(request, timeout=10) as response:
        if response.status != 200 or response.read() != expected:
            raise RuntimeError('XONIX HTTP verification failed')


def check_sandbox_https(domain, expected):
    context = ssl._create_unverified_context()  # Isolated test certificates only.
    def get(name):
        with socket.create_connection(('127.0.0.1', 18443), timeout=10) as raw:
            with context.wrap_socket(raw, server_hostname=name) as tls:
                tls.sendall(f'GET / HTTP/1.1\r\nHost: {name}\r\nConnection: close\r\n\r\n'.encode())
                response = http.client.HTTPResponse(tls)
                response.begin()
                return response.status, response.read()
    if get(domain) != (200, expected):
        raise RuntimeError('sandbox HTTPS XONIX verification failed')
    status, panel = get('panel.' + domain)
    if status not in (200, 301, 302, 303) or panel == expected:
        raise RuntimeError('sandbox HTTPS panel verification failed')


def sandbox_certificate(cert, key):
    result = []
    for path in (cert, key):
        if not path.is_absolute() or not re.fullmatch(r'/[A-Za-z0-9_./-]+', str(path)):
            raise RuntimeError('sandbox certificate paths must be safe absolute paths')
        regular(path)
        result.append(str(path))
    if key.stat().st_mode & 0o077:
        raise RuntimeError('sandbox private key must be root-only')
    return tuple(result)


def sandbox_listener_available():
    config = subprocess.check_output(['nginx', '-T'], stderr=subprocess.STDOUT, text=True)
    config = re.sub(r'#.*', '', config)
    if any(re.search(r'(^|[:\s])18443(?:\s|$)', entry)
           for entry in re.findall(r'\blisten\s+([^;]+);', config)):
        raise RuntimeError('sandbox port 18443 already exists in nginx configuration')
    listeners = subprocess.check_output(['ss', '-H', '-ltnp', 'sport = :18443'], text=True)
    if listeners.strip():
        raise RuntimeError('sandbox port 18443 is already occupied')


def preflight_nginx(domain, port):
    for path in (WEB, NGINX):
        if path.exists() or path.is_symlink():
            raise RuntimeError('unowned path refused: ' + str(path))
    config = subprocess.check_output(['nginx', '-T'], stderr=subprocess.STDOUT, text=True)
    config = re.sub(r'#.*', '', config)
    for declaration in re.findall(r'\bserver_name\s+([^;]+);', config):
        for name in declaration.split():
            name = name.strip('\"\'')
            if (name.startswith(('~', '.')) or '*' in name or '$' in name or
                    name.rstrip('.').lower() == domain.lower()):
                raise RuntimeError('existing nginx server_name may conflict: ' + name)
    listeners = subprocess.check_output(['ss', '-H', '-ltnp', f'sport = :{port}'], text=True)
    if listeners.strip():
        if any('"nginx"' not in line for line in listeners.splitlines()):
            raise RuntimeError(f'port {port} has a non-nginx or unidentified listener')
        run('systemctl', 'is-active', '--quiet', 'nginx')
    else:
        with socket.socket() as probe:
            probe.bind(('0.0.0.0', port))


def publish(domain, port, html, sandbox=None):
    """Replace only files proven by the previous private state; fail closed."""
    state = None
    if STATE.exists() or STATE.is_symlink():
        regular(STATE)
        if STATE.stat().st_mode & 0o077:
            raise RuntimeError('preview state is not private')
        state = json.loads(STATE.read_text())
        if state.get('domain') != domain or state.get('port') != port or state.get('phase') != 'READY':
            raise RuntimeError('RECOVERY_REQUIRED: preview state is incomplete or differs')
        if state.get('sandbox') and not sandbox:
            raise RuntimeError('existing sandbox HTTPS requires the original sandbox options')
        for path, key in ((WEB, 'html'), (NGINX, 'nginx')):
            regular(path)
            if digest(path.read_bytes()) != state.get(key):
                raise RuntimeError('managed file changed externally: ' + str(path))
    else:
        preflight_nginx(domain, port)
    if sandbox and not (state and state.get('sandbox')):
        sandbox_listener_available()
    newconfig = nginx_config(domain, port, sandbox) if sandbox else nginx_config(domain, port)
    oldweb = WEB.read_bytes() if state else None
    oldconfig = NGINX.read_bytes() if state else None
    # Persistent private backups remain available for operator review.
    backup = DATA / 'preview-web-backups'
    backup.mkdir(mode=0o700, exist_ok=True)
    if backup.is_symlink() or backup.stat().st_uid != 0 or backup.stat().st_mode & 0o077:
        raise RuntimeError('untrusted backup directory')
    if state:
        run_dir = Path(tempfile.mkdtemp(prefix='before-', dir=backup))
        atomic(run_dir / 'index.html', oldweb, 0o600)
        atomic(run_dir / 'nginx.conf', oldconfig, 0o600)
    pending = {'phase': 'RECOVERY_REQUIRED', 'domain': domain, 'port': port}
    atomic(STATE, (json.dumps(pending) + '\n').encode(), 0o600)
    replaced = []
    try:
        atomic(WEB, html, 0o644)
        replaced.append((WEB, oldweb, html))
        atomic(NGINX, newconfig, 0o644)
        replaced.append((NGINX, oldconfig, newconfig))
        run('nginx', '-t')
        run('systemctl', 'reload', 'nginx')
        check_http(domain, port, html)
        if sandbox:
            check_sandbox_https(domain, html)
        ready = {'phase': 'READY', 'domain': domain, 'port': port,
                 'html': digest(html), 'nginx': digest(newconfig), 'sandbox': bool(sandbox)}
        atomic(STATE, (json.dumps(ready) + '\n').encode(), 0o600)
    except Exception as error:
        try:
            for path, old, new in reversed(replaced):
                if path.exists():
                    regular(path)
                    if path.read_bytes() != new:
                        raise RuntimeError('changed during rollback: ' + str(path))
                    if old is None:
                        path.unlink()
                    else:
                        atomic(path, old, 0o644)
            run('nginx', '-t')
            run('systemctl', 'reload', 'nginx')
            if state:
                check_http(domain, port, oldweb)
                if state.get('sandbox'):
                    check_sandbox_https(domain, oldweb)
                atomic(STATE, (json.dumps(state) + '\n').encode(), 0o600)
        except Exception as recovery:
            raise RuntimeError(f'RECOVERY_REQUIRED: {error}; restoration failed: {recovery}') from recovery
        if state is None:
            raise RuntimeError(f'RECOVERY_REQUIRED: initial publication failed; inspect retained state: {error}') from error
        raise RuntimeError(f'publication failed; previous configuration restored: {error}') from error


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--domain', required=True)
    p.add_argument('--components', required=True, type=Path, help='unpacked verified candidate directory')
    p.add_argument('--awg-subnet', required=True, help='unused private IPv4 /30')
    p.add_argument('--test-mode', action='store_true', help='use isolated HTTP port 18080')
    p.add_argument('--sandbox-tls-cert', type=Path, help='root-owned test certificate, sandbox only')
    p.add_argument('--sandbox-tls-key', type=Path, help='root-only test private key, sandbox only')
    args = p.parse_args()
    if (args.sandbox_tls_cert is None) != (args.sandbox_tls_key is None):
        raise RuntimeError('sandbox certificate and key must be provided together')
    if args.sandbox_tls_cert and not args.test_mode:
        raise RuntimeError('sandbox TLS requires --test-mode; it listens only on loopback')
    if os.geteuid() != 0 or os.uname().machine != 'x86_64':
        raise RuntimeError('root on Linux amd64 required')
    release = Path('/etc/os-release').read_text()
    if not re.search(r'^ID=debian$', release, re.M) or not re.search(r'^VERSION_ID="?13"?$', release, re.M):
        raise RuntimeError('Debian 13 required')
    if len(args.domain) > 253 or not re.fullmatch(r'(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}', args.domain):
        raise RuntimeError('a valid DNS domain is required')
    if not shutil.which('systemctl') or Path('/proc/1/comm').read_text().strip() != 'systemd':
        raise RuntimeError('running systemd is required')
    manifest = verify_package(args.components.resolve())
    sandbox = sandbox_certificate(args.sandbox_tls_cert, args.sandbox_tls_key) if args.sandbox_tls_cert else None
    if not shutil.which('nginx') or not shutil.which('ip'):
        if not shutil.which('apt-get'):
            raise RuntimeError('apt-get is required to install missing dependencies')
        env = os.environ.copy()
        env['DEBIAN_FRONTEND'] = 'noninteractive'
        run('apt-get', 'update', env=env)
        run('apt-get', 'install', '-y', '--no-install-recommends', 'nginx', 'iproute2', env=env)
    if not shutil.which('ss'):
        raise RuntimeError('iproute2 ss is required for listener checks')
    run('nginx', '-t')
    run('systemctl', 'start', 'nginx')
    port = 18080 if args.test_mode else 80
    if not (STATE.exists() or STATE.is_symlink()):
        preflight_nginx(args.domain, port)
    if not (DATA.exists() or DATA.is_symlink()):
        run(sys.executable, str(args.components.resolve() / 'install_candidate.py'),
            '--awg-endpoint', args.domain, '--awg-subnet', args.awg_subnet)
    else:
        ownership.inspect_installed(manifest)
    ownership.root_dir(DATA, private=True)
    lock = DATA / 'preview-web.lock'
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for directory in (WEB.parent.parent, WEB.parent):
            directory.mkdir(mode=0o755, exist_ok=True)
            if directory.is_symlink() or directory.stat().st_uid != 0 or directory.stat().st_mode & 0o022:
                raise RuntimeError('untrusted web directory: ' + str(directory))
        publish(args.domain, port,
                (REPO / 'assets/decoy/xonix/index.html').read_bytes(), sandbox=sandbox)
    print('PREVIEW_INSTALLED: experimental preview; public TLS and transports are not verified.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, urllib.error.URLError) as error:
        print('PREVIEW_INSTALL_INCOMPLETE:', error, file=sys.stderr)
        raise SystemExit(1)
