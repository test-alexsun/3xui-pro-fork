#!/usr/bin/env python3
"""Coordinate a scoped backup of the exact BUILD-ALL-04 installation.

This prepares a snapshot and restores services. It never replaces binaries.
"""
from contextlib import closing
import fcntl
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import stat
import subprocess
import tempfile
import time
import urllib.parse
import urllib.error
import urllib.request

import backup_candidate as backup
import upgrade_candidate as ownership

DATA = ownership.DATA
PREFIX = ownership.PREFIX
STATE_ROOT = Path('/var/lib/3xui-pro-fork-transactions')
BACKUP_ROOT = Path('/var/backups/3xui-pro-fork')
LOCK = Path('/run/3xui-pro-fork-prepare.lock')
STOP_ORDER = ('3xui-pro-fork.service', '3xui-pro-fork-awg.service')
START_ORDER = tuple(reversed(STOP_ORDER))
TERMINAL = {'PREPARED', 'FAILED_RECOVERED'}


class HealthAuthenticationError(RuntimeError):
    pass


def private_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o077:
        raise RuntimeError('untrusted transaction directory')
    backup.sync_directory(path.parent)


def write_state(state):
    fd, temporary = tempfile.mkstemp(prefix='.state-', dir=STATE_ROOT)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(state, stream, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, STATE_ROOT / 'current.json')
        backup.sync_directory(STATE_ROOT)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def phase(state, value, **fields):
    state.update(fields, phase=value)
    state['history'].append({'phase': value, 'unit': fields.get('unit')})
    write_state(state)


def process_start(pid):
    # /proc/PID/stat can contain spaces and parentheses in comm.
    return (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()[19]


def checked_unit(unit, expected_state, pid=None, start=None):
    path = Path('/etc/systemd/system') / unit
    ownership.regular_root_file(path)
    if ownership.sha(path) != ownership.UNITS[unit]:
        raise RuntimeError('unit identity changed: ' + unit)
    props = ownership.service_properties(unit)
    if (props.get('FragmentPath') != str(path) or props.get('DropInPaths') or
            props.get('NeedDaemonReload') != 'no' or props.get('ActiveState') != expected_state):
        raise RuntimeError('unit state or identity changed: ' + unit)
    current_pid = int(props.get('MainPID', '0'))
    if expected_state == 'active' and (current_pid != pid or process_start(pid) != start):
        raise RuntimeError('service process identity changed: ' + unit)
    if expected_state == 'active':
        proc = Path('/proc') / str(pid)
        if proc.stat().st_uid != 0:
            raise RuntimeError('service process owner changed: ' + unit)
        if unit == '3xui-pro-fork.service':
            if not os.path.samefile(proc / 'exe', PREFIX / 'panel/x-ui'):
                raise RuntimeError('panel executable changed')
        else:
            args = (proc / 'cmdline').read_bytes().split(b'\0')
            if (not os.path.samefile(proc / 'exe', '/usr/bin/python3') or len(args) < 2 or
                    args[1] != str(PREFIX / 'awg/awg_service.py').encode()):
                raise RuntimeError('AWG controller executable changed')
    if expected_state in ('inactive', 'failed') and current_pid != 0:
        raise RuntimeError('stopped service retains a main process: ' + unit)


def api_health(credentials):
    backup.checked_file(credentials, private=True)
    data = json.loads(credentials.read_text())
    if set(data) != {'username', 'password'} or not all(isinstance(v, str) and v for v in data.values()):
        raise RuntimeError('invalid private health credentials')
    with closing(sqlite3.connect((DATA / 'x-ui.db').as_uri() + '?mode=ro', uri=True)) as db:
        values = dict(db.execute("SELECT key,value FROM settings WHERE key IN "
                                 "('webListen','webPort','webBasePath','webCertFile','webKeyFile')"))
    if values.get('webListen') != '127.0.0.1' or values.get('webCertFile', '') or values.get('webKeyFile', ''):
        raise RuntimeError('health check supports only the known loopback HTTP panel')
    port = int(values.get('webPort', '2053'))
    base = values.get('webBasePath', '/') or '/'
    if not 1 <= port <= 65535 or not base.startswith('/') or '..' in base or '?' in base or '#' in base:
        raise RuntimeError('unsupported panel address')
    base = base.rstrip('/') + '/'
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
                                         urllib.request.ProxyHandler({}))
    def call(path, payload=None, token=None):
        headers = {}
        if payload is not None:
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        if token:
            headers['X-CSRF-Token'] = token
        request = urllib.request.Request('http://127.0.0.1:' + str(port) + base + path, data=payload, headers=headers)
        try:
            with opener.open(request, timeout=5) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise HealthAuthenticationError('panel authentication rejected') from exc
            raise
        if not result.get('success'):
            if path == 'login':
                raise HealthAuthenticationError('panel authentication rejected')
            raise RuntimeError('panel API health check failed')
        return result.get('obj')
    token = call('csrf-token')
    call('login', urllib.parse.urlencode(data).encode(), token)
    call('panel/api/inbounds/list')


def health(credentials):
    for unit in STOP_ORDER:
        if ownership.service_properties(unit).get('ActiveState') != 'active':
            raise RuntimeError('service not active: ' + unit)
    metadata = json.loads((DATA / 'awg/metadata.json').read_text())
    public = subprocess.check_output([str(PREFIX / 'awg/awg'), 'show', 'xproawg0', 'public-key'],
                                     text=True, timeout=10).strip()
    if public != metadata['server_public_key']:
        raise RuntimeError('AWG public identity mismatch')
    api_health(credentials)


def await_health(credentials):
    last = None
    for _ in range(20):
        try:
            health(credentials)
            return
        except HealthAuthenticationError:
            raise
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
            last = exc
            time.sleep(0.5)
    raise RuntimeError('health check did not recover: ' + type(last).__name__)


def refuse_external_writers():
    """Fail closed when an observable external process holds managed data writable."""
    targets = set()
    for root in (DATA, PREFIX):
        for path in root.rglob('*'):
            if path.is_symlink():
                raise RuntimeError('symlink in managed files refused')
            if path.is_file():
                st = path.stat()
                targets.add((st.st_dev, st.st_ino))
    for unit in STOP_ORDER:
        st = (Path('/etc/systemd/system') / unit).stat()
        targets.add((st.st_dev, st.st_ino))
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            fds = list((proc / 'fd').iterdir())
        except FileNotFoundError:
            continue
        except PermissionError as exc:
            raise RuntimeError('cannot inspect process file descriptors') from exc
        for fd in fds:
            try:
                st = fd.stat()
                if (st.st_dev, st.st_ino) not in targets:
                    continue
                fields = (proc / 'fdinfo' / fd.name).read_text().splitlines()
                flags = next(int(x.split()[1], 8) for x in fields if x.startswith('flags:'))
                if flags & os.O_ACCMODE != os.O_RDONLY:
                    raise RuntimeError('external process holds managed data writable')
            except FileNotFoundError:
                continue
            except PermissionError as exc:
                raise RuntimeError('cannot inspect managed file descriptor') from exc


def configuration_fingerprint():
    result = {}
    for root, prefix in ((DATA, 'data/'), (PREFIX, 'components/')):
        for path in sorted(root.rglob('*')):
            relative = path.relative_to(root)
            if path.is_symlink():
                raise RuntimeError('symlink in managed files refused')
            if path.is_dir():
                st = path.stat()
                result[prefix + relative.as_posix() + '/'] = (st.st_dev, st.st_ino, st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode))
                continue
            if not path.is_file() or (root == DATA and len(relative.parts) == 1 and relative.name in
                                      ('x-ui.db', 'x-ui.db-wal', 'x-ui.db-shm', 'x-ui.db-journal')):
                continue
            backup.checked_file(path, private=(root == DATA))
            st = path.stat()
            result[prefix + relative.as_posix()] = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns,
                                                     st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode), backup.digest(path))
    return result


def prepare(manifest, credentials):
    os.umask(0o077)
    lock = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        st = os.fstat(lock)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o077:
            raise RuntimeError('untrusted lock file')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('PREPARE_LOCKED') from exc
        private_dir(STATE_ROOT)
        private_dir(BACKUP_ROOT)
        state_path = STATE_ROOT / 'current.json'
        if state_path.exists() or state_path.is_symlink():
            backup.checked_file(state_path, private=True)
            previous = json.loads(state_path.read_text())
            if previous.get('phase') not in TERMINAL:
                raise RuntimeError('RECOVERY_REQUIRED: previous preparation is incomplete')
        estimated = 0
        for root in (DATA, PREFIX):
            for path in root.rglob('*'):
                if path.is_symlink():
                    raise RuntimeError('symlink in managed files refused')
                st = path.lstat()
                if stat.S_ISREG(st.st_mode):
                    estimated += st.st_size
                elif not stat.S_ISDIR(st.st_mode):
                    raise RuntimeError('special file in managed tree refused')
        required = max(512 * 1024 * 1024, 2 * estimated + 128 * 1024 * 1024)
        if shutil.disk_usage(BACKUP_ROOT).free < required:
            raise RuntimeError('insufficient backup disk space')
        info = ownership.inspect_installed(manifest)
        starts = {unit: process_start(pid) for unit, pid in info['processes'].items()}
        await_health(credentials)
        state = {'format': 1, 'id': secrets.token_hex(16), 'initial': {u: 'active' for u in STOP_ORDER},
                 'identities': {u: {'pid': info['processes'][u], 'start_time': starts[u]} for u in STOP_ORDER},
                 'phase': 'PREFLIGHT', 'backup': None, 'history': [{'phase': 'PREFLIGHT', 'unit': None}]}
        write_state(state)
        stopped = []
        try:
            for unit in STOP_ORDER:
                checked_unit(unit, 'active', info['processes'][unit], starts[unit])
                phase(state, 'STOPPING', unit=unit, stopped=list(stopped))
                subprocess.run(['systemctl', 'stop', unit], check=True, timeout=30)
                checked_unit(unit, 'inactive')
                stopped.append(unit)
                phase(state, 'STOPPED', unit=unit, stopped=list(stopped))
            refuse_external_writers()
            before_configs = configuration_fingerprint()
            # A separate connection can read the consistent cut while this
            # reserved lock excludes cooperating SQLite writers.
            with closing(sqlite3.connect(DATA / 'x-ui.db', timeout=2)) as guard:
                guard.execute('BEGIN IMMEDIATE')
                phase(state, 'SNAPSHOTTING', stopped=list(stopped))
                components = {}
                component_directories = {'.': PREFIX}
                for path in sorted(PREFIX.rglob('*')):
                    if path.is_symlink():
                        raise RuntimeError('symlink in component tree refused')
                    name = path.relative_to(PREFIX).as_posix()
                    if path.is_dir():
                        component_directories[name] = path
                    elif path.is_file():
                        ownership.regular_root_file(path)
                        components[name] = path
                    else:
                        raise RuntimeError('special file in component tree refused')
                units = {name: Path('/etc/systemd/system') / name for name in STOP_ORDER}
                result = backup.create_backup(backup_root=BACKUP_ROOT, database=DATA / 'x-ui.db',
                    awg_dir=DATA / 'awg', panel_data_dir=DATA, components=components, units=units,
                    component_directories=component_directories,
                    versions={'tuple': info['tuple'], 'component_sha256': info['installed']})
                backup.verify_backup(result)
                refuse_external_writers()
                if configuration_fingerprint() != before_configs:
                    raise RuntimeError('managed configuration changed during snapshot')
                phase(state, 'SNAPSHOT_VERIFIED', backup=str(result), stopped=list(stopped))
                guard.rollback()
            for unit in START_ORDER:
                checked_unit(unit, 'inactive')
                phase(state, 'STARTING', unit=unit, stopped=list(stopped))
                subprocess.run(['systemctl', 'start', unit], check=True, timeout=45)
                stopped.remove(unit)
                phase(state, 'STARTED', unit=unit, stopped=list(stopped))
            await_health(credentials)
            phase(state, 'PREPARED', stopped=[])
            return {'status': 'PREPARED', 'id': state['id'], 'backup': str(result),
                    'reuse_for_upgrade': False}
        except BaseException as exc:
            recovery_errors = []
            confirmed_active = []
            for unit in START_ORDER:
                try:
                    props = ownership.service_properties(unit)
                    if props.get('ActiveState') in ('inactive', 'failed'):
                        checked_unit(unit, props['ActiveState'])
                        subprocess.run(['systemctl', 'start', unit], check=True, timeout=45)
                    elif props.get('ActiveState') == 'active':
                        pid = int(props.get('MainPID', '0'))
                        if pid <= 0:
                            raise RuntimeError('active service has no main process')
                        checked_unit(unit, 'active', pid, process_start(pid))
                    else:
                        raise RuntimeError('uncertain service state')
                    current = ownership.service_properties(unit)
                    pid = int(current.get('MainPID', '0'))
                    if current.get('ActiveState') != 'active' or pid <= 0:
                        raise RuntimeError('service did not return to active state')
                    checked_unit(unit, 'active', pid, process_start(pid))
                    confirmed_active.append(unit)
                except Exception:
                    recovery_errors.append(unit)
            if not recovery_errors:
                try:
                    ownership.inspect_installed(manifest)
                    await_health(credentials)
                except Exception:
                    recovery_errors.append('health')
            try:
                phase(state, 'RECOVERY_REQUIRED' if recovery_errors else 'FAILED_RECOVERED',
                      recovery_errors=recovery_errors, recovery_confirmed_active=confirmed_active,
                      stopped=[] if len(confirmed_active) == len(STOP_ORDER) else state.get('stopped', []),
                      error_type=type(exc).__name__)
            except Exception:
                recovery_errors.append('durable_state')
            if recovery_errors:
                raise RuntimeError('SERVICE_RECOVERY_FAILED: ' + ','.join(recovery_errors)) from exc
            raise RuntimeError('PREPARE_FAILED_SERVICES_RECOVERED: ' + type(exc).__name__) from exc
    finally:
        os.close(lock)
