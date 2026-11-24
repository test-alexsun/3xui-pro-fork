#!/usr/bin/env python3
"""Fresh-install candidate and read-only upgrade inspection; upgrade is disabled."""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PREFIX = Path('/opt/3xui-pro-fork')
DATA = Path('/var/lib/3xui-pro-fork')
LOG = Path('/var/log/3xui-pro-fork')
UNIT = Path('/etc/systemd/system/3xui-pro-fork.service')
AWG_UNIT = Path('/etc/systemd/system/3xui-pro-fork-awg.service')
FILES = {'panel/x-ui', 'panel/bin/xray-linux-amd64', 'panel/bin/geoip.dat',
         'panel/bin/geosite.dat', 'awg/awg', 'awg/amneziawg-go'}


def check_components(root):
    manifest = json.loads((root / 'components-manifest.json').read_text())
    if manifest.get('status') != 'STAGED_NOT_A_RELEASE' or set(manifest.get('files', {})) != FILES:
        raise RuntimeError('unexpected component manifest')
    for name, expected in manifest['files'].items():
        path = root / name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError('component integrity failure: ' + name)


def run(*args, **kw):
    return subprocess.run(args, check=True, **kw)


def main():
    parser = argparse.ArgumentParser(description='Fresh-install candidate; upgrade is disabled')
    parser.add_argument('--mode', choices=('install', 'inspect-upgrade', 'prepare-upgrade'), default='install')
    parser.add_argument('--health-credentials', type=Path, help='root-only JSON with panel username and password')
    parser.add_argument('--awg-endpoint', help='client-reachable IPv4 address or DNS name')
    parser.add_argument('--awg-subnet', help='unused private IPv4 /30 for the AWG peer pair')
    parser.add_argument('--awg-port', type=int, default=29177)
    parser.add_argument('--no-standalone-awg', action='store_true',
                        help='skip standalone AWG service/config creation when panel manages embedded AWG 3.1')
    args = parser.parse_args()
    if os.geteuid() != 0 or platform.machine() != 'x86_64':
        raise RuntimeError('requires root and amd64')
    if not Path('/etc/os-release').is_file():
        raise RuntimeError('cannot determine OS')
    os_release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    if os_release.get('ID', '').strip('"') != 'debian' or os_release.get('VERSION_ID', '').strip('"') != '13':
        raise RuntimeError('requires Debian 13')
    if Path('/proc/1/comm').read_text().strip() != 'systemd' or not shutil.which('systemctl'):
        raise RuntimeError('running systemd is required')
    if args.mode in ('inspect-upgrade', 'prepare-upgrade'):
        if args.awg_endpoint is not None or args.awg_subnet is not None or args.awg_port != 29177:
            raise RuntimeError('AWG installation options are not valid for inspection')
        check_components(ROOT)
        from upgrade_candidate import inspect_installed
        manifest = json.loads((ROOT / 'components-manifest.json').read_text())
        if args.mode == 'inspect-upgrade':
            if args.health_credentials is not None:
                raise RuntimeError('health credentials are not required for inspection')
            result = inspect_installed(manifest)
            print(json.dumps({'status': 'INSPECTED_NOT_AUTHORIZED', 'tuple': result['tuple']}))
        else:
            if args.health_credentials is None:
                raise RuntimeError('private --health-credentials file required')
            from prepare_candidate import prepare
            print(json.dumps(prepare(manifest, args.health_credentials)))
        return
    if args.health_credentials is not None:
        raise RuntimeError('health credentials are only used for prepare-upgrade')
    if not shutil.which('ip') or not Path('/dev/net/tun').is_char_device():
        raise RuntimeError('iproute2 and /dev/net/tun are required')
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    if not int(status['CapEff'].strip(), 16) & (1 << 12):
        raise RuntimeError('CAP_NET_ADMIN is required')
    subnet = None
    if args.no_standalone_awg:
        if args.awg_endpoint is not None or args.awg_subnet is not None or args.awg_port != 29177:
            raise RuntimeError('standalone AWG options cannot be combined with --no-standalone-awg')
    else:
        if args.awg_endpoint is None or args.awg_subnet is None:
            raise RuntimeError('fresh installation requires --awg-endpoint and --awg-subnet')
        if not 1 <= args.awg_port <= 65535:
            raise RuntimeError('invalid AWG UDP port')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', args.awg_endpoint) or '..' in args.awg_endpoint:
            raise RuntimeError('invalid AWG endpoint hostname')
        subnet = ipaddress.ip_network(args.awg_subnet, strict=True)
        if subnet.version != 4 or subnet.prefixlen != 30 or not any(subnet.subnet_of(ipaddress.ip_network(x)) for x in
                ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
            raise RuntimeError('a dedicated private IPv4 /30 is required')
        routes = json.loads(subprocess.check_output(['ip', '-j', '-4', 'route', 'show', 'table', 'all'], text=True))
        for route in routes:
            dst = route.get('dst', 'default')
            if dst != 'default' and subnet.overlaps(ipaddress.ip_network(dst, strict=False)):
                raise RuntimeError('AWG subnet overlaps a local route')
        try:
            socket.if_nametoindex('xproawg0')
        except OSError:
            pass
        else:
            raise RuntimeError('AWG interface name already exists')
    check_components(ROOT)
    for path in (PREFIX, DATA, LOG, UNIT, AWG_UNIT, Path('/etc/x-ui'), Path('/usr/local/x-ui'),
                 Path('/etc/systemd/system/x-ui.service')):
        if path.exists() or path.is_symlink():
            raise RuntimeError('existing path refused: ' + str(path))
    if shutil.disk_usage('/').free < 512 * 1024 * 1024:
        raise RuntimeError('at least 512 MiB free space required')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 2053))
    if not args.no_standalone_awg:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind(('0.0.0.0', args.awg_port))
    os.umask(0o077)
    PREFIX.mkdir(mode=0o700)
    DATA.mkdir(mode=0o700)
    LOG.mkdir(mode=0o700)
    for name in ('panel', 'awg'):
        shutil.copytree(ROOT / name, PREFIX / name, symlinks=False)
    shutil.copyfile(ROOT / 'awg_config_candidate.py', PREFIX / 'awg/config_candidate.py')
    shutil.copyfile(ROOT / 'awg_service.py', PREFIX / 'awg/awg_service.py')
    (PREFIX / 'awg/config_candidate.py').chmod(0o700)
    (PREFIX / 'awg/awg_service.py').chmod(0o700)
    for name in ('panel/x-ui', 'panel/bin/xray-linux-amd64', 'awg/awg', 'awg/amneziawg-go'):
        (PREFIX / name).chmod(0o700)
    env = {key: value for key, value in os.environ.items() if not key.startswith('XUI_')}
    env.update(XUI_DB_FOLDER=str(DATA), XUI_DB_TYPE='sqlite', XUI_BIN_FOLDER=str(PREFIX / 'panel/bin'), XUI_LOG_FOLDER=str(LOG))
    run(str(PREFIX / 'panel/x-ui'), 'setting', '-listenIP', '127.0.0.1', '-port', '2053', cwd=PREFIX / 'panel', env=env)
    with sqlite3.connect(DATA / 'x-ui.db') as db:
        values = dict(db.execute("SELECT key,value FROM settings WHERE key IN ('webListen','webPort')"))
        if values.get('webListen') != '127.0.0.1' or values.get('webPort') != '2053':
            raise RuntimeError('panel loopback settings verification failed')
        if db.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise RuntimeError('SQLite integrity check failed')
    if not args.no_standalone_awg:
        run(sys.executable, str(PREFIX / 'awg/config_candidate.py'), '--awg', str(PREFIX / 'awg/awg'),
            '--output', str(DATA / 'awg'), '--endpoint-host', args.awg_endpoint, '--port', str(args.awg_port),
            '--subnet', str(subnet))
    shutil.copyfile(ROOT / '3xui-pro-fork.service', UNIT)
    shutil.copyfile(ROOT / '3xui-pro-fork-awg.service', AWG_UNIT)
    UNIT.chmod(0o644)
    AWG_UNIT.chmod(0o644)
    run('systemctl', 'daemon-reload')
    if args.no_standalone_awg:
        run('systemctl', 'enable', '--now', UNIT.name)
        run('systemctl', 'is-active', '--quiet', UNIT.name)
        run('systemctl', 'disable', AWG_UNIT.name)
        print('Candidate panel service started on loopback. Initial credentials are in its root-readable journal.')
        print('Standalone AWG unit left disabled/inactive for native panel-managed embedded AWG 3.1.')
    else:
        for service in (UNIT, AWG_UNIT):
            run('systemctl', 'enable', '--now', service.name)
            run('systemctl', 'is-active', '--quiet', service.name)
        print('Candidate panel service started on loopback. Initial credentials are in its root-readable journal.')
        print('AWG client configuration is root-only under /var/lib/3xui-pro-fork/awg/client.conf.')
    print('Upgrade and rollback are not implemented; do not use as a production release.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, sqlite3.Error) as exc:
        print('INSTALL_INCOMPLETE:', exc, file=sys.stderr)
        print('No automatic cleanup or rollback was attempted; inspect owned paths before retry.', file=sys.stderr)
        raise SystemExit(1)
