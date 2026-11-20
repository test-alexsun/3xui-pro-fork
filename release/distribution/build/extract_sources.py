#!/usr/bin/env python3
"""Extract the two hash-verified upstream tarballs, refusing links and special files."""
import sys, tarfile
from pathlib import Path, PurePosixPath

archive, destination, expected = sys.argv[1:]
dest = Path(destination)
with tarfile.open(archive, 'r:gz') as tar:
    members = tar.getmembers()
    if not members:
        raise ValueError('empty archive')
    selected = []
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != expected:
            raise ValueError(f'unsafe or unexpected archive path: {member.name}')
        if member.issym():
            continue  # The tools archive includes an unused convenience link.
        if not (member.isfile() or member.isdir()):
            raise ValueError(f'unsupported archive member: {member.name}')
        selected.append(member)
    tar.extractall(dest, members=selected, filter='data')
