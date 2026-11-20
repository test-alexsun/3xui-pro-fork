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
import sqlite3
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
import preview_transport as transport
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


def ensure_web_directories():
    for directory in (WEB.parent.parent, WEB.parent):
        created = False
        try:
            directory.mkdir(mode=0o755)
            created = True
        except FileExistsError:
            pass
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError('untrusted web directory: ' + str(directory))
        if created:
            directory.chmod(0o755)
        elif info.st_mode & 0o755 != 0o755:
            raise RuntimeError('existing web directory is not accessible: ' + str(directory))


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


def nginx_config(domain, port, sandbox=None, subscriptions=None, transports=False):
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
        site_extra, panel_extra, defaults = (
            transport.web_extras(domain, cert, key) if transports else ('', '', ''))
        locations = ''
        if subscriptions:
            for path in subscriptions['paths']:
                locations += f'''
    location ^~ {path} {{
        access_log off;
        error_log /dev/null crit;
        proxy_cache off;
        proxy_hide_header Referrer-Policy;
        add_header Referrer-Policy no-referrer always;
        proxy_pass http://127.0.0.1:{subscriptions['port']};
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }}
'''
        config += f'''
server {{
    listen 127.0.0.1:18443 ssl;
    server_name {domain};
    ssl_certificate {cert};
    ssl_certificate_key {key};
    autoindex off;
    {challenge}
    {locations}
    {site_extra}
    location = / {{ root /var/www/3xui-pro-fork/decoy; try_files /index.html =404; }}
    location ~ (^|/)\\. {{ return 404; }}
    location / {{ return 404; }}
}}
server {{
    listen 127.0.0.1:18443 ssl;
    server_name panel.{domain};
    ssl_certificate {cert};
    ssl_certificate_key {key};
    {panel_extra}
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
{defaults}
'''
    return config.encode()


def check_http(domain, port, expected):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(f'http://127.0.0.1:{port}/', headers={'Host': domain})
    with opener.open(request, timeout=10) as response:
        if response.status != 200 or response.read() != expected:
            raise RuntimeError('XONIX HTTP verification failed')


def check_sandbox_https(domain, expected, certificate=None):
    context = (ssl.create_default_context(cafile=certificate) if certificate else
               ssl._create_unverified_context())  # Existing isolated 04A mode.
    port = 443 if certificate else 18443
    def get(name):
        with socket.create_connection(('127.0.0.1', port), timeout=10) as raw:
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


def subscription_config(database, domain, panel_pid, https_port=18443):
    """Read explicit local panel settings; never create or alter panel data."""
    regular(database)
    keys = ('subEnable', 'subListen', 'subPort', 'subPath', 'subJsonEnable',
            'subJsonPath', 'subClashEnable', 'subClashPath', 'subCertFile',
            'subKeyFile', 'subDomain', 'subURI', 'subJsonURI', 'subClashURI')
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
        rows = db.execute('SELECT key,value FROM settings WHERE key IN (' +
                          ','.join('?' for _ in keys) + ')', keys).fetchall()
    if len(rows) != len({key for key, _ in rows}):
        raise RuntimeError('ambiguous subscription settings')
    values = dict(rows)
    if values.get('subEnable', 'true').lower() != 'true':
        raise RuntimeError('subscription service is disabled')
    if values.get('subListen', '') != '127.0.0.1':
        raise RuntimeError('subscription service must explicitly listen on 127.0.0.1')
    if any(values.get(k, '') for k in ('subCertFile', 'subKeyFile')):
        raise RuntimeError('custom subscription backend TLS needs manual integration')
    if values.get('subDomain', '').lower() not in ('', domain.lower()):
        raise RuntimeError('subscription domain differs from sandbox domain')
    try:
        port = int(values.get('subPort', '2096'))
    except (TypeError, ValueError):
        raise RuntimeError('invalid subscription port') from None
    if not 1 <= port <= 65535 or port in (80, 443, 2053, 18080, 18443,
                                          transport.COVER_PORT, *transport.PORTS.values()):
        raise RuntimeError('invalid or conflicting subscription port')
    paths = []
    for flag, key, uri_key in ((None, 'subPath', 'subURI'),
                               ('subJsonEnable', 'subJsonPath', 'subJsonURI'),
                               ('subClashEnable', 'subClashPath', 'subClashURI')):
        if flag and values.get(flag, 'false').lower() != 'true':
            continue
        path = values.get(key, '')
        if not re.fullmatch(r'/(?:[A-Za-z0-9_-]+/)+', path or ''):
            raise RuntimeError('unsupported or missing subscription path')
        if any(path.startswith(prefix) or prefix.startswith(path)
               for prefix in ('/panel/', '/xhttp/', '/.well-known/')):
            raise RuntimeError('subscription path conflicts with a reserved route')
        if any(path.startswith(other) or other.startswith(path) for other in paths):
            raise RuntimeError('overlapping subscription paths')
        configured_uri = values.get(uri_key, '')
        authority = domain if https_port == 443 else f'{domain}:{https_port}'
        if configured_uri != f'https://{authority}{path}':
            raise RuntimeError('explicit subscription URL must match sandbox route')
        paths.append(path)
    output = subprocess.check_output(['ss', '-H', '-ltnp', f'sport = :{port}'], text=True)
    listeners = [line for line in output.splitlines() if line.strip()]
    if len(listeners) != 1:
        raise RuntimeError('subscription listener identity is ambiguous')
    columns = listeners[0].split()
    owners = set(re.findall(r'pid=(\d+)', listeners[0]))
    if len(columns) < 4 or columns[3] != f'127.0.0.1:{port}' or owners != {str(panel_pid)}:
        raise RuntimeError('subscription listener is not owned by the verified panel process')
    with socket.create_connection(('127.0.0.1', port), timeout=3):
        pass
    return {'port': port, 'paths': paths}


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


def publish(domain, port, html, sandbox=None, subscriptions=None, transports=False):
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
        if state.get('subscriptions') and not subscriptions:
            raise RuntimeError('existing subscription routes require --sandbox-subscriptions')
        for path, key in ((WEB, 'html'), (NGINX, 'nginx')):
            regular(path)
            if digest(path.read_bytes()) != state.get(key):
                raise RuntimeError('managed file changed externally: ' + str(path))
    else:
        preflight_nginx(domain, port)
    existing_transport = state.get('transport') if state else None
    if existing_transport and not transports:
        raise RuntimeError('existing transports require --sandbox-transports')
    if existing_transport:
        for name, (path, mode) in transport.FILES.items():
            regular(path)
            if path.stat().st_mode & 0o777 != mode or digest(path.read_bytes()) != existing_transport.get(name):
                raise RuntimeError('managed transport file changed externally: ' + str(path))
        run('systemctl', 'is-active', '--quiet', transport.UNIT.name)
    additions = {}
    if transports and not existing_transport:
        transport.check_available()
        transport.check_nginx()
        additions = transport.new_files(domain, sandbox)
    if sandbox and not transports and not (state and state.get('sandbox')):
        sandbox_listener_available()
    newconfig = (nginx_config(domain, port, sandbox, subscriptions, transports=True) if transports else
                 nginx_config(domain, port, sandbox, subscriptions) if subscriptions else
                 nginx_config(domain, port, sandbox) if sandbox else nginx_config(domain, port))
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
    starting_transport = False
    try:
        atomic(WEB, html, 0o644)
        replaced.append((WEB, oldweb, html))
        atomic(NGINX, newconfig, 0o644)
        replaced.append((NGINX, oldconfig, newconfig))
        for name, data in additions.items():
            path, mode = transport.FILES[name]
            if path.exists() or path.is_symlink():
                raise RuntimeError('transport file appeared: ' + str(path))
            atomic(path, data, mode)
            replaced.append((path, None, data))
        if additions:
            run(str(transport.XRAY), 'run', '-test', '-config', str(transport.CONFIG))
        run('nginx', '-t')
        if additions:
            run('systemctl', 'daemon-reload')
            starting_transport = True
            run('systemctl', 'enable', '--now', transport.UNIT.name)
        run('systemctl', 'reload', 'nginx')
        check_http(domain, port, html)
        if transports:
            run('systemctl', 'is-active', '--quiet', transport.UNIT.name)
            check_sandbox_https(domain, html, sandbox[0])
        elif sandbox:
            check_sandbox_https(domain, html)
        ready = {'phase': 'READY', 'domain': domain, 'port': port,
                 'html': digest(html), 'nginx': digest(newconfig), 'sandbox': bool(sandbox)}
        if subscriptions:
            ready['subscriptions'] = subscriptions
        if transports:
            ready['transport'] = existing_transport or {name: digest(data) for name, data in additions.items()}
        atomic(STATE, (json.dumps(ready) + '\n').encode(), 0o600)
    except Exception as error:
        try:
            if starting_transport:
                run('systemctl', 'disable', '--now', transport.UNIT.name)
            for path, old, new in reversed(replaced):
                if path.exists():
                    regular(path)
                    if path.read_bytes() != new:
                        raise RuntimeError('changed during rollback: ' + str(path))
                    if old is None:
                        path.unlink()
                    else:
                        atomic(path, old, 0o644)
            if starting_transport:
                run('systemctl', 'daemon-reload')
            run('nginx', '-t')
            run('systemctl', 'reload', 'nginx')
            if state:
                check_http(domain, port, oldweb)
                if existing_transport:
                    check_sandbox_https(domain, oldweb, sandbox[0])
                elif state.get('sandbox'):
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
    p.add_argument('--sandbox-subscriptions', action='store_true', help='proxy explicit loopback subscription settings in sandbox')
    p.add_argument('--sandbox-transports', action='store_true',
                   help='install P0/P1/P3 and SNI routing on loopback TCP 443 in a disposable VM')
    args = p.parse_args()
    if (args.sandbox_tls_cert is None) != (args.sandbox_tls_key is None):
        raise RuntimeError('sandbox certificate and key must be provided together')
    if args.sandbox_tls_cert and not args.test_mode:
        raise RuntimeError('sandbox TLS requires --test-mode; it listens only on loopback')
    if args.sandbox_transports and not args.sandbox_tls_cert:
        raise RuntimeError('sandbox transports require sandbox TLS')
    if args.sandbox_subscriptions and not args.sandbox_tls_cert:
        raise RuntimeError('sandbox subscriptions require sandbox TLS')
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
    if args.sandbox_transports and not (STATE.exists() or STATE.is_symlink()):
        if shutil.which('ss'):
            transport.check_available()
    packages = [name for name, binary in (('nginx', 'nginx'), ('iproute2', 'ip'))
                if not shutil.which(binary)]
    if args.sandbox_transports:
        if not transport.MODULE.is_file():
            packages.append('libnginx-mod-stream')
        if not shutil.which('openssl'):
            packages.append('openssl')
    if packages:
        if not shutil.which('apt-get'):
            raise RuntimeError('apt-get is required to install missing dependencies')
        env = os.environ.copy()
        env['DEBIAN_FRONTEND'] = 'noninteractive'
        run('apt-get', 'update', env=env)
        run('apt-get', 'install', '-y', '--no-install-recommends', *packages, env=env)
    if not shutil.which('ss'):
        raise RuntimeError('iproute2 ss is required for listener checks')
    run('nginx', '-t')
    run('systemctl', 'start', 'nginx')
    port = 80 if args.sandbox_transports or not args.test_mode else 18080
    if not (STATE.exists() or STATE.is_symlink()):
        preflight_nginx(args.domain, port)
        if args.sandbox_transports:
            transport.check_available()
            transport.check_nginx()
    if not (DATA.exists() or DATA.is_symlink()):
        run(sys.executable, str(args.components.resolve() / 'install_candidate.py'),
            '--awg-endpoint', args.domain, '--awg-subnet', args.awg_subnet)
    installed = ownership.inspect_installed(manifest)
    ownership.root_dir(DATA, private=True)
    lock = DATA / 'preview-web.lock'
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ensure_web_directories()
        subscriptions = (subscription_config(DATA / 'x-ui.db', args.domain,
                         installed['processes']['3xui-pro-fork.service'],
                         443 if args.sandbox_transports else 18443) if args.sandbox_subscriptions else None)
        publish(args.domain, port,
                (REPO / 'assets/decoy/xonix/index.html').read_bytes(), sandbox=sandbox,
                subscriptions=subscriptions, transports=args.sandbox_transports)
    print('PREVIEW_INSTALLED: experimental preview; public TLS is not verified.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, urllib.error.URLError) as error:
        print('PREVIEW_INSTALL_INCOMPLETE:', error, file=sys.stderr)
        raise SystemExit(1)
