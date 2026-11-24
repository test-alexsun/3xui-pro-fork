#!/usr/bin/env python3
"""Read-only ownership checks for a future constrained candidate upgrade.

No service stop, replacement, migration or rollback is performed here.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess


PREFIX = Path('/opt/3xui-pro-fork')
DATA = Path('/var/lib/3xui-pro-fork')
UNITS = {
    '3xui-pro-fork.service': '4dab75591a00295e56b10f2a96a65e585bbe78216c332123e96aad1cd4f5bea1',
    '3xui-pro-fork-awg.service': '42cd710c66589711a7464e251beb57dba3e495ba78b1aca50e8154638a8bdcd4',
}
BASELINE_SCRIPTS = {
    'awg/awg_service.py': '2e9e06dbbcb1958cc04c30e12d033a56abe29fedffc85f266cf4440f6cc1e404',
    'awg/config_candidate.py': 'db1c55707a0fcf1b3557a8a91ffab4dc9d4f900c1f6d4d63371320a733a06a7b',
}
PINNED_FILES = {
    'panel/x-ui': 'fb7b3776334fce69299f90168c8c31377b69f89c7787088e6dbf561d07b3d345',
    'panel/bin/xray-linux-amd64': 'e87bce586acdb9136aa5b1f1d9c8db9f1ea1d145b6d86368c7f6f662f9f6a66d',
    'panel/bin/geoip.dat': 'a6271d3c96361d96156e6d3f7cf1550ef21b00d2f951deb772f464db91e89ac5',
    'panel/bin/geosite.dat': 'e16ee9af893247f9c8b15c5259e5c0a6ae491b85ee351c22f1954e696ebb8997',
    'awg/awg': 'a604430b4b85e1cfb2e5a9fbd3ca0219e5cd1a0a0173243c0a4201332b522d28',
    'awg/amneziawg-go': 'fdfee29667271d584be54459a100c53e91772ca55585d3f214d173d98ef13b59',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regular_root_file(path, private=False):
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022 or (private and st.st_mode & 0o077):
        raise RuntimeError('untrusted file: ' + str(path))


def root_dir(path, private=False):
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022 or (private and st.st_mode & 0o077):
        raise RuntimeError('untrusted directory: ' + str(path))


def service_properties(unit):
    output = subprocess.check_output(['systemctl', 'show', unit, '--property=FragmentPath',
        '--property=DropInPaths', '--property=MainPID', '--property=NeedDaemonReload',
        '--property=ActiveState'], text=True, timeout=15)
    return dict(line.split('=', 1) for line in output.splitlines() if '=' in line)


def inspect_installed(candidate_manifest, *, require_standalone_awg=True):
    """Refuse anything outside the exact BUILD-ALL-04 tuple and units.

    This read-only inspection is a prerequisite, not a durable ownership proof.
    """
    if (candidate_manifest.get('panel'), candidate_manifest.get('xray'),
            candidate_manifest.get('awg_runtime'), candidate_manifest.get('awg_tools')) != (
            '3.11.0', '26.11.9', '3.1.20260828', '3.1.20260812'):
        raise RuntimeError('unsupported component tuple')
    if candidate_manifest.get('files') != PINNED_FILES:
        raise RuntimeError('component manifest does not match the pinned baseline')
    private_dirs = (PREFIX, DATA, DATA / 'awg') if require_standalone_awg else (PREFIX, DATA)
    for path in private_dirs:
        root_dir(path, private=True)
    for path in (PREFIX / 'panel', PREFIX / 'panel/bin', PREFIX / 'awg'):
        root_dir(path)
    regular_root_file(DATA / 'x-ui.db', private=True)
    if require_standalone_awg:
        for name in ('server.setconf', 'client.conf', 'metadata.json'):
            regular_root_file(DATA / 'awg' / name, private=True)
    installed = {}
    for name, expected in candidate_manifest['files'].items():
        path = PREFIX / name
        regular_root_file(path)
        if sha(path) != expected:
            raise RuntimeError('installed component differs from pinned tuple: ' + name)
        installed[name] = expected
    for name, expected in BASELINE_SCRIPTS.items():
        path = PREFIX / name
        regular_root_file(path, private=True)
        if sha(path) != expected:
            raise RuntimeError('installed AWG helper is not the known baseline: ' + name)
        installed[name] = expected
    processes = {}
    for unit, expected in UNITS.items():
        path = Path('/etc/systemd/system') / unit
        if not require_standalone_awg and unit == '3xui-pro-fork-awg.service':
            if path.exists() or path.is_symlink():
                regular_root_file(path)
                if sha(path) != expected:
                    raise RuntimeError('unknown unit content: ' + unit)
            p = service_properties(unit)
            if p.get('ActiveState') not in ('inactive', 'failed', '') or int(p.get('MainPID', '0') or '0') != 0:
                raise RuntimeError('standalone AWG unit must remain inactive in native embedded mode')
            continue
        regular_root_file(path)
        if sha(path) != expected:
            raise RuntimeError('unknown unit content: ' + unit)
        p = service_properties(unit)
        if (p.get('FragmentPath') != str(path) or p.get('DropInPaths') or
                p.get('NeedDaemonReload') != 'no' or p.get('ActiveState') != 'active'):
            raise RuntimeError('service state, unit path or override not verified: ' + unit)
        pid = int(p.get('MainPID', '0'))
        if pid <= 0 or Path('/proc').joinpath(str(pid)).stat().st_uid != 0:
            raise RuntimeError('service process identity unavailable: ' + unit)
        executable = Path('/proc') / str(pid) / 'exe'
        cmdline = (Path('/proc') / str(pid) / 'cmdline').read_bytes().split(b'\0')
        if unit == '3xui-pro-fork.service':
            if not os.path.samefile(executable, PREFIX / 'panel/x-ui'):
                raise RuntimeError('panel process executable mismatch')
        elif (not os.path.samefile(executable, '/usr/bin/python3') or
              len(cmdline) < 2 or cmdline[1] != str(PREFIX / 'awg/awg_service.py').encode()):
            raise RuntimeError('AWG controller process mismatch')
        processes[unit] = pid
    return {'tuple': '3.11.0/26.11.9/AWG3.1', 'installed': installed, 'processes': processes,
            'ownership': 'CANDIDATE_ONLY_NOT_DURABLE'}


if __name__ == '__main__':
    raise SystemExit('Read-only helper only. Upgrade and rollback are not implemented.')
