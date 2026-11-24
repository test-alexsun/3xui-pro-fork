#!/usr/bin/env python3
"""Private snapshots for the candidate installer; does not perform an upgrade."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import time


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def checked_file(path, private=False):
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or (private and st.st_mode & 0o077):
        raise RuntimeError('unsafe source file: ' + str(path))


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def copy_private(source, destination):
    checked_file(source)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with source.open('rb') as src, os.fdopen(fd, 'wb') as dst:
            fd = -1
            while block := src.read(1024 * 1024):
                dst.write(block)
            dst.flush()
            os.fsync(dst.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    if digest(source) != digest(destination):
        raise RuntimeError('source changed during backup: ' + str(source))


def verify_backup(root):
    root_stat = root.lstat()
    if not stat.S_ISDIR(root_stat.st_mode) or root_stat.st_uid != 0 or root_stat.st_mode & 0o077:
        raise RuntimeError('untrusted backup directory')
    manifest_path = root / 'manifest.json'
    checked_file(manifest_path, private=True)
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get('format') != 1 or not isinstance(manifest.get('files'), dict) or
            not isinstance(manifest.get('versions'), dict) or
            not isinstance(manifest.get('source_metadata'), dict) or
            not isinstance(manifest.get('source_directories'), dict) or
            set(manifest['source_metadata']) != set(manifest['files'])):
        raise RuntimeError('invalid backup manifest')
    for entry in [*manifest['source_metadata'].values(), *manifest['source_directories'].values()]:
        if (not isinstance(entry, dict) or set(entry) != {'uid', 'gid', 'mode'} or
                any(type(entry[key]) is not int or entry[key] < 0 for key in entry) or entry['mode'] > 0o7777):
            raise RuntimeError('invalid source metadata')
    for name in manifest['source_directories']:
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise RuntimeError('unsafe source directory metadata')
    required = {'database/x-ui.db', 'awg/server.setconf', 'awg/client.conf', 'awg/metadata.json'}
    if not required.issubset(manifest['files']):
        raise RuntimeError('required backup files missing from manifest')
    actual = set()
    for entry in root.rglob('*'):
        if entry.is_symlink():
            raise RuntimeError('symlink in backup refused')
        if entry.is_file() and entry != manifest_path:
            actual.add(entry.relative_to(root).as_posix())
    if actual != set(manifest['files']):
        raise RuntimeError('backup inventory mismatch')
    for name, expected in manifest['files'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise RuntimeError('unsafe backup manifest path')
        path = root / relative
        for parent in list(relative.parents)[:-1]:
            st = (root / parent).lstat()
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o077:
                raise RuntimeError('untrusted backup parent')
        checked_file(path, private=True)
        if digest(path) != expected:
            raise RuntimeError('backup integrity failure: ' + name)
    database = root / 'database/x-ui.db'
    # This is an independently completed backup, not a live SQLite database;
    # immutable avoids creating WAL/SHM sidecars during read-only verification.
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise RuntimeError('backup database integrity failure')
    return manifest


def create_backup(*, backup_root, database, awg_dir, components, units, versions,
                  panel_data_dir=None, component_directories=None):
    """Create and reopen a private snapshot. Caller must coordinate writers."""
    os.umask(0o077)
    backup_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = backup_root.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o077:
        raise RuntimeError('private root-owned backup directory required')
    checked_file(database, private=True)
    database_identity = database.lstat()
    if awg_dir.is_symlink() or not awg_dir.is_dir() or awg_dir.stat().st_uid != 0 or awg_dir.stat().st_mode & 0o077:
        raise RuntimeError('private root-owned AWG directory required')
    for name in ('server.setconf', 'client.conf', 'metadata.json'):
        checked_file(awg_dir / name, private=True)
    identifier = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + secrets.token_hex(8)
    root = backup_root / identifier
    root.mkdir(mode=0o700)
    try:
        files = {}
        metadata = {}
        directories = {}
        for name, path in (component_directories or {}).items():
            if Path(name).is_absolute() or '..' in Path(name).parts:
                raise RuntimeError('unsafe component directory name')
            st = path.lstat()
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
                raise RuntimeError('untrusted component directory')
            directories['components/' + name] = {'uid': st.st_uid, 'gid': st.st_gid,
                                                   'mode': stat.S_IMODE(st.st_mode)}
        def remember(source, target):
            before = source.lstat()
            copy_private(source, target)
            after = source.lstat()
            if (before.st_dev, before.st_ino, before.st_uid, before.st_gid, before.st_mode) != (
                    after.st_dev, after.st_ino, after.st_uid, after.st_gid, after.st_mode):
                raise RuntimeError('source identity or metadata changed during backup')
            name = target.relative_to(root).as_posix()
            files[name] = digest(target)
            metadata[name] = {'uid': before.st_uid, 'gid': before.st_gid, 'mode': stat.S_IMODE(before.st_mode)}
        for section, mapping in (('components', components), ('units', units)):
            for name, source in mapping.items():
                if Path(name).is_absolute() or '..' in Path(name).parts:
                    raise RuntimeError('unsafe backup name')
                target = root / section / name
                remember(source, target)
        st = awg_dir.lstat()
        directories['awg'] = {'uid': st.st_uid, 'gid': st.st_gid, 'mode': stat.S_IMODE(st.st_mode)}
        for path in sorted(awg_dir.rglob('*')):
            if path.is_symlink():
                raise RuntimeError('AWG symlink refused')
            if path.is_dir():
                if path.stat().st_uid != 0 or path.stat().st_mode & 0o077:
                    raise RuntimeError('AWG directory not private')
                st = path.lstat()
                directories['awg/' + path.relative_to(awg_dir).as_posix()] = {
                    'uid': st.st_uid, 'gid': st.st_gid, 'mode': stat.S_IMODE(st.st_mode)}
                continue
            checked_file(path, private=True)
            target = root / 'awg' / path.relative_to(awg_dir)
            remember(path, target)
        if panel_data_dir is not None:
            if panel_data_dir != database.parent or awg_dir != panel_data_dir / 'awg':
                raise RuntimeError('unexpected panel data layout')
            st = panel_data_dir.lstat()
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o077:
                raise RuntimeError('panel data directory not private')
            directories['panel-data'] = {'uid': st.st_uid, 'gid': st.st_gid, 'mode': stat.S_IMODE(st.st_mode)}
            for path in sorted(panel_data_dir.rglob('*')):
                relative = path.relative_to(panel_data_dir)
                if relative.parts[0] == 'awg':
                    continue
                if path.is_symlink():
                    raise RuntimeError('panel data symlink refused')
                if len(relative.parts) == 1 and relative.name in ('x-ui.db', 'x-ui.db-wal', 'x-ui.db-shm', 'x-ui.db-journal'):
                    continue
                st = path.lstat()
                if stat.S_ISDIR(st.st_mode):
                    if st.st_uid != 0 or st.st_mode & 0o077:
                        raise RuntimeError('panel data directory not private')
                    directories['panel-data/' + relative.as_posix()] = {
                        'uid': st.st_uid, 'gid': st.st_gid, 'mode': stat.S_IMODE(st.st_mode)}
                else:
                    checked_file(path, private=True)
                    with path.open('rb') as stream:
                        if stream.read(16) == b'SQLite format 3\x00':
                            raise RuntimeError('additional SQLite database requires separate coordination')
                    remember(path, root / 'panel-data' / relative)
        dest = root / 'database/x-ui.db'
        dest.parent.mkdir(mode=0o700)
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as src:
            with closing(sqlite3.connect(dest)) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                    raise RuntimeError('snapshot database integrity failure')
        os.chmod(dest, 0o600)
        with dest.open('rb') as stream:
            os.fsync(stream.fileno())
        files['database/x-ui.db'] = digest(dest)
        st = database.lstat()
        if (st.st_dev, st.st_ino, st.st_uid, st.st_gid, st.st_mode) != (
                database_identity.st_dev, database_identity.st_ino, database_identity.st_uid,
                database_identity.st_gid, database_identity.st_mode):
            raise RuntimeError('database identity or metadata changed during backup')
        metadata['database/x-ui.db'] = {'uid': st.st_uid, 'gid': st.st_gid, 'mode': stat.S_IMODE(st.st_mode)}
        manifest = {'format': 1, 'id': identifier, 'versions': versions, 'files': files,
                    'source_metadata': metadata, 'source_directories': directories}
        manifest_path = root / 'manifest.json'
        with manifest_path.open('x', encoding='utf-8') as stream:
            json.dump(manifest, stream, sort_keys=True, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        for directory in sorted((p for p in root.rglob('*') if p.is_dir()), reverse=True):
            sync_directory(directory)
        sync_directory(root)
        sync_directory(backup_root)
        verify_backup(root)
        return root
    except BaseException:
        # An incomplete private snapshot is retained for inspection, never applied.
        raise
