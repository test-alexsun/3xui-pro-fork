"""Isolated Certbot lineage and renewal units for the public preview."""
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import tempfile
import subprocess
import urllib.parse
import urllib.request

from preview_transport import names


ACME = Path('/var/lib/3xui-preview-acme')
CERT_NAME = '3xui-preview'
DEFAULT_DIRECTORY = 'https://acme-v02.api.letsencrypt.org/directory'
SERVICE = Path('/etc/systemd/system/3xui-preview-renew.service')
TIMER = SERVICE.with_suffix('.timer')
HOOK = ACME / 'renew-deploy'
HOOK_SCRIPT = b'#!/bin/sh\nset -eu\n/usr/sbin/nginx -t\n/usr/bin/systemctl reload nginx\n'


def validate_network(domain, address, directory, ca, subscription_domain=None):
    ip = ipaddress.IPv4Address(address)
    if ip.is_loopback or ip.is_unspecified or ip.is_multicast or ip.is_link_local:
        raise RuntimeError('public mode needs a specific non-loopback unicast IPv4 address')
    if directory:
        test = urllib.parse.urlsplit(directory)
        if (test.scheme != 'https' or test.username or test.password or test.query or test.fragment
                or not re.fullmatch(r'/[a-zA-Z0-9/_-]+', test.path)):
            raise RuntimeError('invalid ACME test directory')
        try:
            peer = ipaddress.IPv4Address(test.hostname)
        except (ValueError, TypeError):
            raise RuntimeError('ACME test directory needs a local IPv4 endpoint') from None
        if peer.is_global or ip.is_global or ca is None:
            raise RuntimeError('ACME test mode requires private addresses and explicit test trust')
    elif ca is not None or not ip.is_global:
        raise RuntimeError('public ACME requires a globally routable IPv4 address')
    with socket.socket() as probe:
        probe.bind((str(ip), 0))
    for host in names(domain, subscription_domain):
        addresses = {item[4][0] for item in socket.getaddrinfo(host, 80, type=socket.SOCK_STREAM)}
        if addresses != {str(ip)}:
            raise RuntimeError(f'DNS for {host} must resolve solely to {ip}')


def dirs():
    return ['--config-dir', str(ACME/'config'), '--work-dir', str(ACME/'work'),
            '--logs-dir', str(ACME/'logs')]


def context(domain, address, directory, ca, atomic, regular, subscription_domain=None):
    owner = ACME / 'owner.json'
    identity = {'domain': domain, 'address': address, 'server': directory, 'test_ca': str(ca) if ca else None}
    if subscription_domain:
        identity['subscription_domain'] = subscription_domain
    payload = (json.dumps(identity) + '\n').encode()
    try:
        ACME.mkdir(mode=0o700)
    except FileExistsError:
        info = ACME.lstat()
        if not ACME.is_dir() or ACME.is_symlink() or info.st_uid != 0 or info.st_mode & 0o077:
            raise RuntimeError('untrusted ACME directory')
        regular(owner)
        if owner.read_bytes() != payload:
            raise RuntimeError('ACME state belongs to a different domain or mode')
    else:
        atomic(owner, payload, 0o600)


def issue(domain, email, directory, ca, webroot, run, subscription_domain=None):
    env = os.environ.copy()
    for key in ('REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE'):
        env.pop(key, None)
    if ca:
        env['REQUESTS_CA_BUNDLE'] = str(ca)
    command = ['certbot', 'certonly', '--non-interactive', '--agree-tos',
               '--email', email, '--keep-until-expiring', '--no-directory-hooks',
               '--webroot', '--webroot-path', str(webroot), '--preferred-challenges', 'http',
               '--cert-name', CERT_NAME, '--server', directory, *dirs()]
    for host in names(domain, subscription_domain):
        command.extend(('-d', host))
    run(*command, env=env)
    return certificate()


def certificate():
    lineage = ACME / 'config/live' / CERT_NAME
    archive = ACME / 'config/archive' / CERT_NAME
    result = []
    for filename in ('fullchain.pem', 'privkey.pem'):
        path = lineage / filename
        target = path.resolve(strict=True)
        if target.parent != archive or target.stat().st_uid != 0 or not target.is_file():
            raise RuntimeError('unexpected Certbot certificate target')
        if filename == 'privkey.pem' and target.stat().st_mode & 0o077:
            raise RuntimeError('Certbot key is not private')
        result.append(str(path))
    renewal = ACME / 'config/renewal' / (CERT_NAME + '.conf')
    if not renewal.is_file() or renewal.is_symlink() or renewal.stat().st_uid != 0:
        raise RuntimeError('Certbot renewal configuration is missing')
    return tuple(result)


def renewal_files(ca):
    environment = f'Environment=REQUESTS_CA_BUNDLE={ca}\n' if ca else ''
    command = ' '.join(['/usr/bin/flock', '/var/lib/3xui-pro-fork/preview-web.lock',
                        '/usr/bin/certbot', 'renew', '--non-interactive', '--cert-name', CERT_NAME,
                        '--no-directory-hooks', '--deploy-hook', str(HOOK), *dirs()])
    service = ('[Unit]\nDescription=Renew the isolated 3xui preview certificate\n'
               'After=network-online.target nginx.service\n\n[Service]\nType=oneshot\n'
               f'{environment}ExecStart={command}\n').encode()
    timer = ('[Unit]\nDescription=Check the 3xui preview certificate for renewal\n\n'
             '[Timer]\nOnCalendar=*-*-* 03,15:00:00\nRandomizedDelaySec=3600\n'
             'Persistent=true\n\n[Install]\nWantedBy=timers.target\n').encode()
    return ((SERVICE, service, 0o644), (TIMER, timer, 0o644), (HOOK, HOOK_SCRIPT, 0o700))


def enable_renewal(ca, atomic, regular, run):
    for path, data, mode in renewal_files(ca):
        if path.exists() or path.is_symlink():
            regular(path)
            if path.read_bytes() != data:
                raise RuntimeError(f'unowned renewal file refused: {path}')
        else:
            atomic(path, data, mode)
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', '--now', TIMER.name)
    run('systemctl', 'is-active', '--quiet', TIMER.name)

def verify_http01(domain, address, webroot, subscription_domain=None):
    challenge = webroot / '.well-known/acme-challenge'
    for directory in (challenge.parent, challenge):
        try:
            directory.mkdir(mode=0o755)
        except FileExistsError:
            if not directory.is_dir() or directory.is_symlink():
                raise RuntimeError('untrusted HTTP-01 directory')
        else:
            directory.chmod(0o755)
        st = directory.lstat()
        if st.st_uid != 0 or st.st_mode & 0o022:
            raise RuntimeError('untrusted HTTP-01 directory permissions')
    fd, name = tempfile.mkstemp(prefix='preview-check-', dir=challenge)
    try:
        with os.fdopen(fd, 'wb') as file:
            os.fchmod(file.fileno(), 0o644)
            file.write(b'3xui-preview-http01')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for host in names(domain, subscription_domain):
            request = urllib.request.Request(
                f'http://{address}/.well-known/acme-challenge/{Path(name).name}',
                headers={'Host': host})
            with opener.open(request, timeout=10) as result:
                if result.status != 200 or result.read(100) != b'3xui-preview-http01':
                    raise RuntimeError(f'HTTP-01 probe failed for {host}')
    finally:
        Path(name).unlink()


def exact_names(cert, domain, subscription_domain):
    text = subprocess.check_output(['openssl', 'x509', '-in', cert, '-noout', '-ext', 'subjectAltName'], text=True)
    identifiers = [x.strip() for x in text.split('\n', 1)[1].strip().split(',')]
    if sorted(identifiers) != sorted(['DNS:' + domain, 'DNS:' + subscription_domain]):
        raise RuntimeError('strict certificate must contain exactly the two requested DNS SANs')
