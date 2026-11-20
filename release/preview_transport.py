"""Owned loopback Xray and TCP 443 routing for the Debian preview sandbox."""
import json
from pathlib import Path
import re
import secrets
import socket
import subprocess
import uuid

from preview_profiles import VERSION, render_pair

XRAY = Path('/opt/3xui-pro-fork/panel/bin/xray-linux-amd64')
UNIT = Path('/etc/systemd/system/3xui-preview-xray.service')
STREAM = Path('/etc/nginx/modules-enabled/99-3xui-preview-stream.conf')
MODULE = Path('/etc/nginx/modules-enabled/50-mod-stream.conf')
STATE_DIR = Path('/var/lib/3xui-pro-fork')
CONFIG = STATE_DIR / 'preview-xray.json'
CLIENTS = STATE_DIR / 'preview-xray-clients.json'
FILES = {'stream': (STREAM, 0o644), 'unit': (UNIT, 0o644),
         'xray': (CONFIG, 0o600), 'clients': (CLIENTS, 0o600)}
HTTPS_PORT = 18443
PORTS = {'P0': 19440, 'P1': 19441, 'P3': 19443}
COVER_PORT = 19444
ORIGIN_PORT = 18099
XHTTP_PATH = '/xhttp/'

SERVICE = b'''[Unit]
Description=3xui preview sandbox Xray transports
After=network.target nginx.service

[Service]
Type=simple
ExecStart=/opt/3xui-pro-fork/panel/bin/xray-linux-amd64 run -config /var/lib/3xui-pro-fork/preview-xray.json
Restart=on-failure
UMask=0077
NoNewPrivileges=true
CapabilityBoundingSet=
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6

[Install]
WantedBy=multi-user.target
'''


def names(domain):
    return (domain, 'panel.' + domain, 'p0.' + domain, 'p3.' + domain)


def stream_config(domain, address=None):
    site, panel, p0, p3 = names(domain)
    return f'''# Managed by 3xui-pro-fork preview.
stream {{
    map $ssl_preread_server_name $preview_backend {{
        {p0} 127.0.0.1:{PORTS['P0']};
        {p3} 127.0.0.1:{PORTS['P3']};
        {site} 127.0.0.1:{HTTPS_PORT};
        {panel} 127.0.0.1:{HTTPS_PORT};
        default 127.0.0.1:{HTTPS_PORT};
    }}
    server {{
        listen {address or "127.0.0.1"}:443;
        ssl_preread on;
        proxy_pass $preview_backend;
    }}
}}
'''.encode()


def web_extras(domain, cert, key):
    site, panel, p0, p3 = names(domain)
    def verify_sni(name):
        return f'http2 on; if ($ssl_server_name != {name}) {{ return 421; }}'
    site_routes = f'''{verify_sni(site)}
    location ^~ {XHTTP_PATH} {{
        access_log off;
        grpc_pass grpc://127.0.0.1:{PORTS['P1']};
        grpc_set_header Host {site};
        client_max_body_size 0;
        grpc_read_timeout 120s;
        grpc_send_timeout 120s;
    }}'''
    defaults = f'''
server {{
    listen 127.0.0.1:{HTTPS_PORT} ssl default_server;
    ssl_reject_handshake on;
}}
server {{
    listen 127.0.0.1:{COVER_PORT} ssl;
    http2 on;
    server_name {p0} {p3};
    ssl_certificate {cert};
    ssl_certificate_key {key};
    ssl_protocols TLSv1.3;
    location / {{ return 404; }}
}}
'''
    return site_routes, verify_sni(panel), defaults


def check_available(address=None):
    for path, _ in FILES.values():
        if path.exists() or path.is_symlink():
            raise RuntimeError(f'unowned transport file refused: {path}')
    for port in (443, HTTPS_PORT, COVER_PORT, *PORTS.values()):
        listeners = subprocess.check_output(['ss', '-H', '-ltnp', f'sport = :{port}'], text=True)
        if listeners.strip():
            raise RuntimeError(f'transport TCP {port} already has a listener')
        with socket.socket() as probe:
            probe.bind(((address if port == 443 and address else '127.0.0.1'), port))


def check_nginx():
    if not MODULE.is_file():
        raise RuntimeError('Debian nginx stream module is required')
    text = subprocess.check_output(['nginx', '-T'], stderr=subprocess.STDOUT, text=True)
    text = re.sub(r'#.*', '', text)
    if re.search(r'\bstream\s*\{', text):
        raise RuntimeError('existing nginx stream context requires manual integration')


def new_files(domain, certificate, address=None, test_origin=None):
    _, _, p0, p3 = names(domain)
    cert, key = certificate
    for host in names(domain):
        subprocess.run(['openssl', 'x509', '-in', cert, '-noout', '-checkhost', host],
                       stdout=subprocess.DEVNULL, check=True)
    keys = subprocess.check_output([str(XRAY), 'x25519'], text=True)
    values = dict(line.split(': ', 1) for line in keys.splitlines() if ': ' in line)
    private = values.get('PrivateKey')
    public = next((values[k] for k in ('Password (PublicKey)', 'Password', 'PublicKey') if k in values), None)
    if not private or not public:
        raise RuntimeError('pinned Xray did not generate a REALITY key pair')
    config = {'log': {'loglevel': 'info'},
              'inbounds': [], 'outbounds': [{'protocol': 'freedom', 'tag': 'direct',
              'settings': {'finalRules': [{'action': 'allow', 'network': 'tcp',
                                          'port': ORIGIN_PORT, 'ip': ['127.0.0.1/32']}]}}]}
    if address:
        # Public mode retains the pinned Xray private destination guard.
        config['outbounds'][0].pop('settings')
        if test_origin:
            # Only an explicitly private ACME fixture gets a narrow test origin.
            config['outbounds'][0]['settings'] = {'finalRules': [{'action': 'allow',
                'network': 'tcp', 'port': ORIGIN_PORT, 'ip': [test_origin + '/32']}]}
    clients = {}
    for index, (profile, host) in enumerate((('P0', p0), ('P1', domain), ('P3', p3))):
        params = {'xray_version': VERSION, 'uuid': str(uuid.uuid4()), 'host': host,
                  'path': XHTTP_PATH, 'port': 443, 'proxy_port': 19500 + index,
                  'target': f'127.0.0.1:{COVER_PORT}', 'private_key': private,
                  'public_key': public, 'short_id': secrets.token_hex(8), 'cert': cert, 'key': key}
        server, client = render_pair(profile, params)
        inbound = server['inbounds'][0]
        inbound['port'] = PORTS[profile]
        inbound['settings']['clients'][0]['email'] = f'preview-{profile}'
        if profile == 'P1':
            # Nginx terminates TLS; grpc_pass uses HTTP/2 cleartext to Xray.
            inbound['streamSettings'].pop('tlsSettings')
            inbound['streamSettings']['security'] = 'none'
        config['inbounds'].append(inbound)
        if address:
            outbound = client['outbounds'][0]
            outbound['settings']['vnext'][0]['address'] = domain
            if profile == 'P1':
                # The public profile uses the client's system trust.
                outbound['streamSettings']['tlsSettings'].pop('certificates')
        clients[profile] = client
    def encode(value):
        return (json.dumps(value, indent=2) + '\n').encode()
    return {'stream': stream_config(domain, address), 'unit': SERVICE,
            'xray': encode(config), 'clients': encode(clients)}
