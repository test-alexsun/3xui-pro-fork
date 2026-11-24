#!/usr/bin/env python3
"""Supervise one exclusively created named AWG TUN; never delete by name."""
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import signal
import socket
import stat
import struct
import subprocess
import sys
import time

INTERFACE = 'xproawg0'
CONFIG = Path('/var/lib/3xui-pro-fork/awg/server.setconf')
META = Path('/var/lib/3xui-pro-fork/awg/metadata.json')
AWG = '/opt/3xui-pro-fork/awg/awg'
GO = '/opt/3xui-pro-fork/awg/amneziawg-go'
TUNSETIFF = 0x400454ca
IFF_TUN = 0x0001
IFF_NO_PI = 0x1000
IFF_VNET_HDR = 0x4000
IFF_TUN_EXCL = 0x8000
stopping = False


def on_signal(_signal, _frame):
    global stopping
    stopping = True


def checked_file(path):
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o077:
        raise RuntimeError('private root-owned file required: ' + str(path))


def run(*args):
    subprocess.run(args, check=True, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def notify_ready():
    address = os.environ.get('NOTIFY_SOCKET')
    if address:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect('\0' + address[1:] if address.startswith('@') else address)
            sock.sendall(b'READY=1')


def main():
    if os.geteuid() != 0 or not stat.S_ISCHR(os.stat('/dev/net/tun').st_mode):
        raise RuntimeError('root and /dev/net/tun character device required')
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    if not int(status['CapEff'].strip(), 16) & (1 << 12):
        raise RuntimeError('CAP_NET_ADMIN required')
    for path in (CONFIG, META):
        checked_file(path)
    address = ipaddress.ip_interface(json.loads(META.read_text())['server_address'])
    if address.version != 4 or address.network.prefixlen != 30:
        raise RuntimeError('invalid server address')
    lock = os.open('/run/3xui-pro-fork-awg.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        lock_stat = os.fstat(lock)
        if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_uid != 0 or lock_stat.st_mode & 0o077:
            raise RuntimeError('invalid lock file')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        control_socket = Path('/var/run/amneziawg/' + INTERFACE + '.sock')
        if control_socket.exists() or control_socket.is_symlink():
            raise RuntimeError('existing AWG control socket refused')
        tun = os.open('/dev/net/tun', os.O_RDWR | os.O_CLOEXEC)
        child = None
        try:
            # EXCL makes an existing interface a hard error, not an attachment.
            fcntl.ioctl(tun, TUNSETIFF, struct.pack('16sH22x', INTERFACE.encode(),
                                                   IFF_TUN | IFF_NO_PI | IFF_VNET_HDR | IFF_TUN_EXCL))
            index = socket.if_nametoindex(INTERFACE)
            env = {key: value for key, value in os.environ.items() if not key.startswith('WG_')}
            env['WG_TUN_FD'] = str(tun)
            child = subprocess.Popen([GO, '-f', INTERFACE], env=env, pass_fds=(tun,))
            for _ in range(100):
                if stopping or child.poll() is not None:
                    raise RuntimeError('AWG process exited during startup')
                if control_socket.is_socket():
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError('AWG control socket not ready')
            for command in ((AWG, 'setconf', INTERFACE, str(CONFIG)),
                            ('/usr/sbin/ip', 'address', 'add', str(address), 'dev', INTERFACE),
                            ('/usr/sbin/ip', 'link', 'set', 'dev', INTERFACE, 'up')):
                if socket.if_nametoindex(INTERFACE) != index:
                    raise RuntimeError('interface identity changed')
                run(*command)
            if child.poll() is not None:
                raise RuntimeError('AWG process exited before readiness')
            notify_ready()
            print('AWG interface ready', flush=True)
            while not stopping and child.poll() is None:
                time.sleep(0.2)
            if not stopping:
                raise RuntimeError('AWG process exited unexpectedly')
        finally:
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
            os.close(tun)
    finally:
        os.close(lock)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print('AWG_SERVICE_FAILED:', exc, file=sys.stderr, flush=True)
        raise SystemExit(1)
