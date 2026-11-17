#!/usr/bin/env python3
"""Generate one AWG 3.1 peer pair; does not create or manage interfaces."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess


def call(awg, *args, data=None):
    result = subprocess.run([str(awg), *args], input=data, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=10)
    value = result.stdout.strip()
    if not re.fullmatch(r'[A-Za-z0-9+/]{43}=', value):
        raise ValueError('unexpected key output')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--awg', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--endpoint-host', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--subnet', required=True, help='dedicated IPv4 /30 network')
    a = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', a.endpoint_host) or '..' in a.endpoint_host:
        raise ValueError('endpoint must be an IPv4 address or DNS name')
    if not 1 <= a.port <= 65535:
        raise ValueError('invalid UDP port')
    subnet = ipaddress.ip_network(a.subnet, strict=True)
    if subnet.version != 4 or subnet.prefixlen != 30:
        raise ValueError('a dedicated IPv4 /30 is required')
    if not any(subnet.subnet_of(ipaddress.ip_network(block)) for block in
               ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
        raise ValueError('subnet must be in RFC 1918 private space')
    server_ip, client_ip = list(subnet.hosts())
    if a.output.exists() or a.output.is_symlink():
        raise ValueError('output directory already exists')
    server_private = call(a.awg, 'genkey')
    server_public = call(a.awg, 'pubkey', data=server_private + '\n')
    client_private = call(a.awg, 'genkey')
    client_public = call(a.awg, 'pubkey', data=client_private + '\n')
    header_key = call(a.awg, 'genkey')
    common = '\n'.join(('S1 = 12', 'S2 = 12', 'S3 = 12', 'S4 = 12',
                        'H1 = 1', 'H2 = 2', 'H3 = 3', 'H4 = 4',
                        'HeaderProtectionKey = ' + header_key))
    server = (f'[Interface]\nPrivateKey = {server_private}\nListenPort = {a.port}\n{common}\n'
              f'[Peer]\nPublicKey = {client_public}\nAllowedIPs = {client_ip}/32\n')
    client = (f'[Interface]\nPrivateKey = {client_private}\nAddress = {client_ip}/30\n{common}\n'
              f'[Peer]\nPublicKey = {server_public}\nAllowedIPs = {server_ip}/32\n'
              f'Endpoint = {a.endpoint_host}:{a.port}\nPersistentKeepalive = 25\n')
    os.umask(0o077)
    a.output.mkdir(mode=0o700)
    for name, contents in (('server.setconf', server), ('client.conf', client)):
        fd = os.open(a.output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(contents)
    metadata = {'server_address': f'{server_ip}/30', 'client_address': f'{client_ip}/30',
                'port': a.port, 'server_public_key': server_public, 'client_public_key': client_public}
    fd = os.open(a.output / 'metadata.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(metadata, stream, indent=2)
        stream.write('\n')
    print('Private configuration created; interface creation and service management are not implemented.')


if __name__ == '__main__':
    main()
