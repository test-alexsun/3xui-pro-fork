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
import time
import urllib.error
import urllib.parse
import urllib.request

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'release'))
import install_candidate as candidate
import preview_transport as transport
import preview_acme as acme
import preview_nginx_packages as nginx_packages
import preview_two_domain as two
import preview_panel_inbounds as native
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


def nginx_config(domain, port, sandbox=None, subscriptions=None, transports=False, public_address=None, layout=None):
    if layout:
        return two.nginx(domain, port, sandbox, subscriptions, public_address, layout)
    challenge = ('location ^~ /.well-known/acme-challenge/ { '
                 'root /var/www/3xui-pro-fork/decoy; try_files $uri =404; }') if sandbox or public_address else ''
    http_names = ' '.join(transport.names(domain)) if public_address else domain
    config = (f'''# Managed by 3xui-pro-fork preview; do not edit manually.
server {{
    listen {port};
    server_name {http_names};
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
    # A successful systemctl reload can precede the new Nginx workers accepting.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(f'http://127.0.0.1:{port}/', headers={'Host': domain})
    for _ in range(30):
        try:
            with opener.open(request, timeout=3) as response:
                if response.status == 200 and response.read() == expected:
                    return
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(.1)
    raise RuntimeError('XONIX HTTP verification failed after Nginx reload readiness wait')



def check_http_redirect(domain, port):
    """Check the exact public authority without following redirects or weakening TLS."""
    for _ in range(30):
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
        try:
            connection.request('GET', '/', headers={'Host': domain})
            response = connection.getresponse()
            valid = response.status == 308 and response.getheader('Location') == f'https://{domain}/'
            response.read()
            if valid:
                return
        except (OSError, http.client.HTTPException):
            pass
        finally:
            connection.close()
        time.sleep(.1)
    raise RuntimeError('HTTP to HTTPS redirect verification failed after Nginx reload')


def check_sandbox_https(domain, expected, certificate=None, public_address=None, layout=None):
    verified = bool(certificate or public_address)
    context = (ssl.create_default_context(cafile=certificate) if verified else
               ssl._create_unverified_context())  # Existing isolated 04A mode.
    port = 443 if verified else 18443
    def get(name, path='/'):
        with socket.create_connection((public_address or '127.0.0.1', port), timeout=10) as raw:
            with context.wrap_socket(raw, server_hostname=name) as tls:
                tls.sendall(f'GET {path} HTTP/1.1\r\nHost: {name}\r\nConnection: close\r\n\r\n'.encode())
                response = http.client.HTTPResponse(tls)
                response.begin()
                return response.status, response.read()
    if get(domain) != (200, expected):
        raise RuntimeError('sandbox HTTPS XONIX verification failed')
    if layout:
        if get(layout['subscription_domain'])[0] != 404:
            raise RuntimeError('subscription root must be 404')
        status, panel = get(domain, layout['panel_path'])
    else:
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


def preflight_nginx(domain, port, public_address=None, layout=None):
    for path in (WEB, NGINX):
        if path.exists() or path.is_symlink():
            raise RuntimeError('unowned path refused: ' + str(path))
    config = subprocess.check_output(['nginx', '-T'], stderr=subprocess.STDOUT, text=True)
    config = re.sub(r'#.*', '', config)
    domains = transport.names(domain, layout['subscription_domain'] if layout else None) if public_address else (domain,)
    for declaration in re.findall(r'\bserver_name\s+([^;]+);', config):
        for name in declaration.split():
            name = name.strip('\"\'')
            if (name.startswith(('~', '.')) or '*' in name or '$' in name or
                    name.rstrip('.').lower() in {host.lower() for host in domains}):
                raise RuntimeError('existing nginx server_name may conflict: ' + name)
    listeners = subprocess.check_output(['ss', '-H', '-ltnp', f'sport = :{port}'], text=True)
    if listeners.strip():
        if any('"nginx"' not in line for line in listeners.splitlines()):
            raise RuntimeError(f'port {port} has a non-nginx or unidentified listener')
        run('systemctl', 'is-active', '--quiet', 'nginx')
    else:
        with socket.socket() as probe:
            probe.bind(('0.0.0.0', port))


def publish(domain, port, html, sandbox=None, subscriptions=None, transports=False,
            public_address=None, ca=None, test_origin=None, layout=None, panel_managed=False):
    """Replace only files proven by the previous private state; fail closed."""
    state = None
    if STATE.exists() or STATE.is_symlink():
        regular(STATE)
        if STATE.stat().st_mode & 0o077:
            raise RuntimeError('preview state is not private')
        state = json.loads(STATE.read_text())
        if state.get('domain') != domain or state.get('port') != port or state.get('phase') != 'READY':
            raise RuntimeError('RECOVERY_REQUIRED: preview state is incomplete or differs')
        if state.get('layout') != layout:
            raise RuntimeError('strict two-domain identity differs; migration refused')
        if state.get('public_address') != public_address:
            raise RuntimeError('public listener or mode differs from the managed state')
        if state.get('sandbox') and not sandbox:
            raise RuntimeError('existing sandbox HTTPS requires the original sandbox options')
        if state.get('subscriptions') and not subscriptions:
            raise RuntimeError('existing subscription routes require --sandbox-subscriptions')
        for path, key in ((WEB, 'html'), (NGINX, 'nginx')):
            regular(path)
            if digest(path.read_bytes()) != state.get(key):
                raise RuntimeError('managed file changed externally: ' + str(path))
    else:
        if public_address:
            preflight_nginx(domain, port, public_address, layout)
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
        if panel_managed:
            native.verify_ready()
        else:
            run('systemctl', 'is-active', '--quiet', transport.UNIT.name)
    additions = {}
    if transports and not existing_transport:
        if public_address:
            transport.check_available(public_address, layout)
        else:
            transport.check_available()
        transport.check_nginx()
        additions = transport.new_files(domain, sandbox, public_address, test_origin, layout)
    if sandbox and not transports and not (state and state.get('sandbox')):
        sandbox_listener_available()
    newconfig = (nginx_config(domain, port, sandbox, subscriptions, transports=transports,
                              public_address=public_address, layout=layout) if public_address else
                 nginx_config(domain, port, sandbox, subscriptions, transports=True) if transports else
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
        if layout and sandbox:
            for host in transport.names(domain, layout['subscription_domain']):
                check_http_redirect(host, port)
        else:
            check_http(domain, port, html)
        if transports:
            if panel_managed:
                native.verify_ready(web_state=state)
            else:
                run('systemctl', 'is-active', '--quiet', transport.UNIT.name)
            if public_address:
                check_sandbox_https(domain, html, ca, public_address, layout)
            else:
                check_sandbox_https(domain, html, sandbox[0])
        elif sandbox:
            check_sandbox_https(domain, html)
        ready = {'phase': 'READY', 'domain': domain, 'port': port,
                 'html': digest(html), 'nginx': digest(newconfig), 'sandbox': bool(sandbox)}
        if layout:
            ready['layout'] = layout
            if sandbox:
                ready['http_redirect'] = True
        if panel_managed:
            ready['panel_managed_inbounds'] = True
        if public_address:
            ready['public_address'] = public_address
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
                # The older reviewed revision served HTTP content even with TLS.
                # Verify the restored state's actual contract, not the new one.
                if state.get('http_redirect') and layout:
                    for host in transport.names(domain, layout['subscription_domain']):
                        check_http_redirect(host, port)
                else:
                    check_http(domain, port, oldweb)
                if existing_transport and public_address:
                    check_sandbox_https(domain, oldweb, ca, public_address, layout)
                elif existing_transport:
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
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument('--domain', required=True)
    p.add_argument('--subscription-domain', help='strict two-domain mode; automatic isolated subscription backend')
    p.add_argument('--panel-path', help='optional private base path: one safe segment, 16-80 characters')
    p.add_argument('--p0-port', type=int, default=8443, help='strict-mode REALITY XHTTP public TCP port')
    p.add_argument('--p3-port', type=int, default=9443, help='strict-mode REALITY Vision public TCP port')
    p.add_argument('--subscription-port', type=int, default=2096, help='strict-mode loopback subscription port')
    p.add_argument('--panel-inbounds', action='store_true', help='strict native panel ownership of real P0/P1/P3')
    p.add_argument('--migrate-panel-inbounds', action='store_true', help='explicit opt-in handoff of an existing standalone installation')
    p.add_argument('--components', type=Path, help='local verified candidate directory; default fetches pinned components')
    p.add_argument('--awg-subnet', required=True, help='unused private IPv4 /30')
    p.add_argument('--test-mode', action='store_true', help='use isolated HTTP port 18080')
    p.add_argument('--sandbox-tls-cert', type=Path, help='root-owned test certificate, sandbox only')
    p.add_argument('--sandbox-tls-key', type=Path, help='root-only test private key, sandbox only')
    p.add_argument('--sandbox-subscriptions', action='store_true', help='proxy explicit loopback subscription settings in sandbox')
    p.add_argument('--sandbox-transports', action='store_true',
                   help='install P0/P1/P3 and SNI routing on loopback TCP 443 in a disposable VM')
    p.add_argument('--public-bind', metavar='IPV4', help='public preview TCP 443 listener')
    p.add_argument('--acme-email', help='required contact email for public TLS')
    p.add_argument('--public-subscriptions', action='store_true', help='proxy explicit panel subscription settings over TCP 443')
    p.add_argument('--acme-test-directory', help='private HTTPS ACME directory, isolated test only')
    p.add_argument('--acme-test-ca', type=Path, help='explicit trust for private ACME and its issued TLS certificate')
    args = p.parse_args()
    if args.public_bind:
        if any((args.test_mode, args.sandbox_tls_cert, args.sandbox_tls_key,
                args.sandbox_transports, args.sandbox_subscriptions)):
            p.error('public mode and sandbox options cannot be combined')
        if not args.acme_email or not re.fullmatch(r'[^\s@]+@[^\s@]+', args.acme_email):
            p.error('public mode requires a valid --acme-email')
    elif any((args.public_subscriptions, args.acme_email, args.acme_test_directory, args.acme_test_ca)):
        p.error('public ACME and subscription options require --public-bind')
    if bool(args.acme_test_directory) != bool(args.acme_test_ca):
        p.error('both ACME test directory and CA are required')
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
    args.layout = two.layout(args, regular)
    native.requested(args)
    if args.public_bind:
        if args.acme_test_ca:
            ca = args.acme_test_ca
            if not re.fullmatch(r'/[A-Za-z0-9_./-]+', str(ca)):
                raise RuntimeError('test CA must be a safe absolute regular file')
            regular(ca)
        acme.validate_network(args.domain, args.public_bind, args.acme_test_directory, args.acme_test_ca, args.subscription_domain)
    if args.components:
        install(args, args.components.resolve())
    else:
        sys.path.insert(0, str(REPO / 'tools'))
        from fetch_preview_components import prepare
        with tempfile.TemporaryDirectory(prefix='3xui-preview-components-') as scratch:
            install(args, prepare(Path(scratch)))


def install_dependencies(public, routed):
    packages = []
    if not shutil.which('ip') or not shutil.which('ss'):
        packages.append('iproute2')
    pinned_nginx = nginx_packages.missing() if public else []
    if not public and not shutil.which('nginx'):
        packages.append('nginx')
    if not public and routed and not transport.MODULE.is_file():
        packages.append('libnginx-mod-stream')
    if routed and not shutil.which('openssl'):
        packages.append('openssl')
    if public and not shutil.which('certbot'):
        packages.append('certbot')
    if not (packages or pinned_nginx):
        return
    if not shutil.which('apt-get'):
        raise RuntimeError('apt-get is required to install missing dependencies')
    env = os.environ.copy()
    env['DEBIAN_FRONTEND'] = 'noninteractive'
    run('apt-get', 'update', env=env)
    if pinned_nginx:
        sys.path.insert(0, str(REPO / 'tools'))
        from fetch_preview_components import download
        with tempfile.TemporaryDirectory(prefix='3xui-preview-nginx-') as scratch:
            directory = Path(scratch)
            directory.chmod(0o755)
            archives = nginx_packages.stage(directory, pinned_nginx, download)
            run('apt-get', 'install', '-y', '--no-install-recommends', *packages, *archives, env=env)
        if nginx_packages.missing():
            raise RuntimeError('pinned Nginx packages did not install')
    else:
        run('apt-get', 'install', '-y', '--no-install-recommends', *packages, env=env)


def install(args, components):
    layout = args.layout
    panel_managed = native.requested(args)
    # Refuse old-mode adoption and changed owned files before any strict-mode mutation.
    if layout and (STATE.exists() or STATE.is_symlink()):
        regular(STATE)
        old = json.loads(STATE.read_text())
        if (old.get('layout') != layout or old.get('domain') != args.domain or
                old.get('public_address') != args.public_bind or old.get('phase') != 'READY'):
            raise RuntimeError('strict deployment differs from existing state; migration refused')
        for path, key in ((WEB, 'html'), (NGINX, 'nginx')):
            regular(path)
            if digest(path.read_bytes()) != old.get(key):
                raise RuntimeError('managed web file changed externally')
        for name, (path, mode) in transport.FILES.items():
            if old.get('transport'):
                regular(path)
                if path.stat().st_mode & 0o777 != mode or digest(path.read_bytes()) != old['transport'].get(name):
                    raise RuntimeError('managed transport file changed externally')
    fresh = not (DATA.exists() or DATA.is_symlink())
    if layout and fresh and shutil.which('ss'):
        two.check_subscription_port(layout)
    manifest = verify_package(components)
    sandbox = sandbox_certificate(args.sandbox_tls_cert, args.sandbox_tls_key) if args.sandbox_tls_cert else None
    routed = args.sandbox_transports or bool(args.public_bind)
    if routed and not (STATE.exists() or STATE.is_symlink()) and shutil.which('ss'):
        transport.check_available(args.public_bind, layout)
    if args.public_bind:
        for path, data, _ in acme.renewal_files(args.acme_test_ca):
            if path.exists() or path.is_symlink():
                regular(path)
                if path.read_bytes() != data:
                    raise RuntimeError(f'unowned renewal file refused: {path}')
    install_dependencies(args.public_bind, routed)
    if not shutil.which('ss'):
        raise RuntimeError('iproute2 ss is required for listener checks')
    run('nginx', '-t')
    run('systemctl', 'start', 'nginx')
    port = 80 if routed or not args.test_mode else 18080
    if not (STATE.exists() or STATE.is_symlink()):
        preflight_nginx(args.domain, port, args.public_bind, layout)
        if routed:
            transport.check_available(args.public_bind, layout)
            transport.check_nginx()
    if not (DATA.exists() or DATA.is_symlink()):
        run(sys.executable, str(components / 'install_candidate.py'),
            '--awg-endpoint', args.domain, '--awg-subnet', args.awg_subnet)
    installed = ownership.inspect_installed(manifest)
    if panel_managed:
        native.verify_ready()
    ownership.root_dir(DATA, private=True)
    lock = DATA / 'preview-web.lock'
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ensure_web_directories()
        html = (REPO / 'assets/decoy/xonix/index.html').read_bytes()
        if layout:
            two.panel_setup(args.domain, layout, fresh, atomic, regular, lambda: ownership.inspect_installed(manifest))
            installed = ownership.inspect_installed(manifest)
        subscriptions = (subscription_config(DATA / 'x-ui.db', args.subscription_domain or args.domain,
                         installed['processes']['3xui-pro-fork.service'],
                         443 if routed else 18443) if args.sandbox_subscriptions or args.public_subscriptions or layout else None)
        if args.public_bind:
            server = args.acme_test_directory or acme.DEFAULT_DIRECTORY
            if STATE.exists() or STATE.is_symlink():
                regular(STATE)
                state = json.loads(STATE.read_text())
                if state.get('public_address') != args.public_bind or state.get('domain') != args.domain:
                    raise RuntimeError('public state belongs to another mode or identity')
            else:
                state = {}
            acme.context(args.domain, args.public_bind, server, args.acme_test_ca, atomic, regular, args.subscription_domain)
            if not state.get('sandbox'):
                publish(args.domain, port, html, public_address=args.public_bind, layout=layout)
                acme.verify_http01(args.domain, args.public_bind, WEB.parent, args.subscription_domain)
                sandbox = acme.issue(args.domain, args.acme_email, server, args.acme_test_ca, WEB.parent, run, args.subscription_domain)
            else:
                sandbox = acme.certificate()
            if layout:
                acme.exact_names(sandbox[0], args.domain, args.subscription_domain)
            publish(args.domain, port, html, sandbox=sandbox, subscriptions=subscriptions, transports=True,
                    public_address=args.public_bind, ca=args.acme_test_ca, layout=layout,
                    test_origin=(urllib.parse.urlsplit(args.acme_test_directory).hostname
                                 if args.acme_test_directory else None), panel_managed=panel_managed)
            acme.enable_renewal(args.acme_test_ca, atomic, regular, run)
            if getattr(args, 'panel_inbounds', False) and not panel_managed:
                native.migrate(manifest, atomic, test_origin=(urllib.parse.urlsplit(args.acme_test_directory).hostname
                    if args.acme_test_directory else None))
        else:
            publish(args.domain, port, html, sandbox=sandbox,
                    subscriptions=subscriptions, transports=args.sandbox_transports)
    print('PREVIEW_INSTALLED: experimental preview; public TLS is not verified.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, urllib.error.URLError) as error:
        print('PREVIEW_INSTALL_INCOMPLETE:', error, file=sys.stderr)
        raise SystemExit(1)
