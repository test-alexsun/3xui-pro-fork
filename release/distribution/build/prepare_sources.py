#!/usr/bin/env python3
"""Fetch only the pinned upstream source archives, validating every cache hit."""
import argparse
import hashlib
import os
from pathlib import Path
import tempfile
import urllib.request

SOURCES = {
    "runtime": ("https://codeload.github.com/amnezia-vpn/amneziawg-go/tar.gz/b5928efb6ca19f0153958460c3d141f04abc5c2e", "10bf7458e090bf52f87df27adcd3904a60e4d17fab844d9415e46379147f1ab4"),
    "tools": ("https://codeload.github.com/amnezia-vpn/amneziawg-tools/tar.gz/ee0f0a9aa34ff0a0da4b3433b9512781cfe02843", "22438f231d39ea27e4bdc69707ec3103357f3cecc9ad3eecba18a61e5b39c9b9"),
}


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def prepare(cache, offline):
    cache.mkdir(parents=True, exist_ok=True)
    for name, (url, expected) in SOURCES.items():
        target = cache / (name + ".tar.gz")
        if target.exists():
            if not target.is_file() or digest(target) != expected:
                raise ValueError(f"{name}: cache SHA256 mismatch")
        else:
            if offline:
                raise ValueError(f"{name}: missing pinned source in offline mode")
            fd, tmp = tempfile.mkstemp(prefix=".download-", dir=cache)
            try:
                with os.fdopen(fd, "wb") as out, urllib.request.urlopen(url, timeout=60) as response:
                    while chunk := response.read(1024 * 1024):
                        out.write(chunk)
                if digest(Path(tmp)) != expected:
                    raise ValueError(f"{name}: downloaded SHA256 mismatch")
                os.replace(tmp, target)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        print(f"{name}: verified sha256={expected}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    try:
        prepare(args.cache, args.offline)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"source preparation failed: {exc}\n")


if __name__ == "__main__":
    main()
