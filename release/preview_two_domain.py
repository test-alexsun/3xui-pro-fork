"""Strict two-name deployment, with explicit REALITY ports and owned panel setup."""
import http.cookiejar
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

PANEL = Path('/opt/3xui-pro-fork/panel/x-ui')
DATA = Path('/var/lib/3xui-pro-fork')
PANEL_STATE = DATA / 'preview-panel.json'


def dns_name(name):
    return (isinstance(name, str) and len(name) <= 253 and
            re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', name))


def layout(args, regular):
    if not args.subscription_domain:
        if args.panel_path or args.p0_port != 8443 or args.p3_port != 9443 or args.subscription_port != 2096:
            raise RuntimeError('two-domain options require --subscription-domain')
        return None
    if not args.public_bind or args.public_subscriptions:
        raise RuntimeError('--subscription-domain requires public mode; subscriptions are automatic')
    if not dns_name(args.domain) or not dns_name(args.subscription_domain) or args.domain == args.subscription_domain:
        raise RuntimeError('two distinct lower-case DNS domains required')
    ports = (args.p0_port, args.p3_port, args.subscription_port)
    reserved = {22, 53, 80, 443, 2053, 18080, 18443, 19440, 19441, 19443, 19444, 29177}
    if len(set(ports)) != 3 or any(not 1024 <= x <= 65535 or x in reserved for x in ports):
        raise RuntimeError('conflicting or invalid two-domain port')
    saved = None
    if PANEL_STATE.exists() or PANEL_STATE.is_symlink():
        regular(PANEL_STATE)
        if PANEL_STATE.stat().st_mode & 0o077:
            raise RuntimeError('panel setup state is not private')
        saved = json.loads(PANEL_STATE.read_text())
    path = args.panel_path or (saved['layout']['panel_path'] if saved else '/console-' + secrets.token_hex(16) + '/')
    if not re.fullmatch(r'/[A-Za-z0-9_-]{16,80}/', path) or path.startswith(('/xhttp', '/sub', '/json', '/clash')):
        raise RuntimeError('panel path must be one private segment of 16-80 safe characters')
    result = {'subscription_domain': args.subscription_domain, 'p0_port': args.p0_port,
              'p3_port': args.p3_port, 'subscription_port': args.subscription_port, 'panel_path': path}
    if saved and saved.get('layout') != result:
        raise RuntimeError('two-domain panel identity changed; automatic migration refused')
    return result


def settings():
    with sqlite3.connect((DATA / 'x-ui.db').as_uri() + '?mode=ro', uri=True) as db:
        return dict(db.execute('SELECT key,value FROM settings'))


def desired_settings(domain, spec):
    sub = spec['subscription_domain']
    return {'webBasePath': spec['panel_path'], 'webListen': '127.0.0.1', 'webPort': 2053,
            'webDomain': domain, 'subEnable': True, 'subListen': '127.0.0.1',
            'subPort': spec['subscription_port'], 'subDomain': sub,
            'subCertFile': '', 'subKeyFile': '', 'subPath': '/sub/', 'subJsonEnable': True,
            'subJsonPath': '/json/', 'subClashEnable': True, 'subClashPath': '/clash/',
            'subURI': f'https://{sub}/sub/', 'subJsonURI': f'https://{sub}/json/',
            'subClashURI': f'https://{sub}/clash/'}


def same_settings(values, desired):
    def canonical(value):
        return str(value).lower() if isinstance(value, bool) else str(value)
    return all(canonical(values.get(k, '')) == canonical(v) for k, v in desired.items())


def check_subscription_port(spec):
    port = spec['subscription_port']
    if subprocess.check_output(['ss', '-H', '-ltnp', f'sport = :{port}'], text=True).strip():
        raise RuntimeError('subscription port already has a listener')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))


def panel_setup(domain, spec, fresh, atomic, regular, inspect):
    """Use pinned CLI/API contracts; never write the panel SQLite database directly."""
    expected = desired_settings(domain, spec)
    saved = None
    if PANEL_STATE.exists():
        regular(PANEL_STATE)
        saved = json.loads(PANEL_STATE.read_text())
        if saved.get('layout') != spec or saved.get('domain') != domain:
            raise RuntimeError('panel setup owner differs')
        if saved.get('phase') == 'READY':
            if not same_settings(settings(), expected):
                raise RuntimeError('managed panel settings changed externally; refusing overwrite')
            return
    if not saved:
        if not fresh:
            raise RuntimeError('existing panel has no strict-mode ownership; automatic adoption refused')
        env = {k: v for k, v in os.environ.items() if not k.startswith('XUI_')}
        env.update(XUI_DB_FOLDER=str(DATA), XUI_DB_TYPE='sqlite',
                   XUI_BIN_FOLDER=str(PANEL.parent / 'bin'), XUI_LOG_FOLDER='/var/log/3xui-pro-fork')
        result = subprocess.run([str(PANEL), 'setting', '-getApiToken',
                                 '-tokenName', 'preview-two-domain-setup', '-tokenScope', 'admin'],
                                cwd=PANEL.parent, env=env, capture_output=True, text=True, timeout=30)
        match = re.search(r'^apiToken: (\S+)$', result.stdout, re.M)
        if result.returncode or not match:
            raise RuntimeError('pinned panel CLI setup token unavailable (output withheld)')
        saved = {'phase': 'CONFIGURING', 'domain': domain, 'layout': spec, 'api_token': match[1]}
        atomic(PANEL_STATE, (json.dumps(saved) + '\n').encode(), 0o600)
    current = settings()
    base = current.get('webBasePath', '/') or '/'
    if not re.fullmatch(r'/(?:[A-Za-z0-9_-]+/)*', base):
        raise RuntimeError('unsupported existing panel base path')
    # Never follow redirects carrying the admin token off the verified loopback backend.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise RuntimeError('panel API redirect refused')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    def call(path, payload):
        req = urllib.request.Request('http://127.0.0.1:2053' + base + 'panel/api/' + path,
              data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json',
              'Authorization': 'Bearer ' + saved['api_token'], 'Host': current.get('webDomain') or domain})
        try:
            with opener.open(req, timeout=15) as response:
                result = json.load(response)
        except (OSError, ValueError) as exc:
            raise RuntimeError('panel API setup failed (response withheld): ' + type(exc).__name__) from None
        if not result.get('success'):
            raise RuntimeError('panel API rejected setup (response withheld)')
        return result.get('obj')
    if not same_settings(current, expected):
        all_settings = call('setting/all', {})
        all_settings.update(expected)
        call('setting/update', all_settings)
    subprocess.run(['systemctl', 'restart', '3xui-pro-fork.service'], check=True, timeout=30)
    for _ in range(60):
        try:
            inspect()
            with socket.create_connection(('127.0.0.1', spec['subscription_port']), timeout=.3):
                pass
            if same_settings(settings(), expected):
                break
        except (OSError, RuntimeError, subprocess.SubprocessError):
            pass
        time.sleep(.5)
    else:
        raise RuntimeError('configured panel did not become ready; private setup state retained')
    saved['phase'] = 'READY'
    atomic(PANEL_STATE, (json.dumps(saved) + '\n').encode(), 0o600)


def nginx(domain, port, sandbox, subscriptions, address, spec):
    sub = spec['subscription_domain']
    challenge = "location ^~ /.well-known/acme-challenge/ { root /var/www/3xui-pro-fork/decoy; try_files $uri =404; }"
    private_logs = 'access_log off; error_log /dev/null crit;'
    site_root = 'location = / { root /var/www/3xui-pro-fork/decoy; try_files /index.html =404; }'
    deny = 'location ~ (^|/)\\. { return 404; } location / { return 404; }'
    config = '# Managed by 3xui-pro-fork preview; strict two-domain mode.\n'
    for name in (domain, sub):
        root = site_root if name == domain else ''
        config += f'server {{ listen {port}; server_name {name}; {private_logs} if ($host != {name}) {{ return 404; }} {challenge} {root} {deny} }}\n'
    if not sandbox:
        return config.encode()
    cert, key = sandbox
    def tls(name):
        return f"listen 127.0.0.1:18443 ssl; http2 on; port_in_redirect off; server_name {name}; ssl_certificate {cert}; ssl_certificate_key {key}; {private_logs} if ($ssl_server_name != {name}) {{ return 421; }} if ($host != {name}) {{ return 421; }}"
    panel = spec['panel_path']
    config += f"""
map $http_upgrade $preview_connection_upgrade {{ default upgrade; '' close; }}
server {{ listen 127.0.0.1:18443 ssl default_server; ssl_reject_handshake on; {private_logs} }}
server {{
    {tls(domain)}
    {site_root}
    location ^~ /xhttp/ {{ access_log off; grpc_pass grpc://127.0.0.1:19441;
        grpc_set_header Host {domain}; client_max_body_size 0; grpc_read_timeout 120s; grpc_send_timeout 120s; }}
    location = {panel.rstrip('/')} {{ return 308 {panel}; }}
    location ^~ {panel} {{
        proxy_pass http://127.0.0.1:2053;
        proxy_http_version 1.1;
        proxy_set_header Host {domain};
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $preview_connection_upgrade;
        proxy_cookie_flags ~ secure httponly samesite=lax;
    }}
    {deny}
}}
server {{ {tls(sub)}
    add_header Referrer-Policy no-referrer always;
    add_header Cache-Control no-store always;
"""
    if subscriptions:
        for path in subscriptions['paths']:
            config += f"""
    location ^~ {path} {{
        proxy_pass http://127.0.0.1:{subscriptions['port']};
        proxy_cache off;
        proxy_set_header Host {sub};
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
    }}
"""
    config += f"{deny} }}\n"
    # Separate TLS1.3/H2 cover endpoint: no admin or subscription routes.
    config += f"""
server {{ listen 127.0.0.1:19444 ssl; http2 on; server_name {domain};
    ssl_certificate {cert}; ssl_certificate_key {key}; ssl_protocols TLSv1.3;
    {private_logs}
    if ($ssl_server_name != {domain}) {{ return 421; }}
    location / {{ return 404; }}
}}
"""
    return config.encode()
