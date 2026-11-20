"""Fetch the pinned official binaries and build the preview candidate in a scratch directory."""
import hashlib
from http.client import HTTPException
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request

import build_all_components as builder


PANEL_URL = 'https://github.com/MHSanaei/3x-ui/releases/download/v3.11.0/x-ui-linux-amd64.tar.gz'
XRAY_URL = 'https://github.com/XTLS/Xray-core/releases/download/v26.11.9/Xray-linux-64.zip'
ROOT = Path(__file__).resolve().parents[1]
AWG_ARCHIVE = ROOT / 'release/distribution/awg-linux-amd64.tar.gz'
AWG_SHA256 = '1273dc4a82b2eff7624db91b77a18f0f603365606e938d052a3a0dc17323d50b'
MAX_ARCHIVE = 96 * 1024 * 1024


class HTTPSRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).scheme != 'https':
            raise RuntimeError('component download refused a non-HTTPS redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, expected, path):
    opener = urllib.request.build_opener(HTTPSRedirects())
    checksum = hashlib.sha256()
    received = 0
    try:
        request = urllib.request.Request(url, headers={'User-Agent': '3xui-pro-fork-preview'})
        with opener.open(request, timeout=30) as response, path.open('xb') as output:
            for block in iter(lambda: response.read(1024 * 1024), b''):
                received += len(block)
                if received > MAX_ARCHIVE:
                    raise RuntimeError('component archive exceeds size limit')
                checksum.update(block)
                output.write(block)
    except (OSError, HTTPException) as error:
        raise RuntimeError(f'download failed: {url}: {error}') from error
    if checksum.hexdigest() != expected:
        raise RuntimeError(f'upstream archive SHA256 mismatch: {url}')


def unpack_awg(archive_path, output):
    builder.verify(archive_path.read_bytes(), AWG_SHA256, 'AWG distribution archive')
    output.mkdir(mode=0o700)
    with tarfile.open(archive_path, 'r:gz') as archive:
        members = archive.getmembers()
        if len(members) != len(builder.AWG_BINARIES) or {m.name for m in members} != set(builder.AWG_BINARIES):
            raise RuntimeError('unexpected AWG archive members')
        for member in members:
            if not member.isfile():
                raise RuntimeError('AWG archive member is not a regular file')
            data = archive.extractfile(member).read()
            builder.verify(data, builder.AWG_BINARIES[member.name], member.name)
            (output / member.name).write_bytes(data)


def prepare(scratch):
    panel, xray, awg = (scratch / name for name in ('panel.tgz', 'xray.zip', 'awg'))
    output = scratch / 'staged'
    unpack_awg(AWG_ARCHIVE, awg)
    download(PANEL_URL, builder.PANEL_ARCHIVE, panel)
    download(XRAY_URL, builder.XRAY_ARCHIVE, xray)
    subprocess.run([sys.executable, str(ROOT / 'tools/build_all_components.py'),
                    '--panel', str(panel), '--xray', str(xray), '--awg-bin', str(awg),
                    '--output', str(output)], check=True)
    # Include the exact installer helpers used by the existing candidate verifier.
    for path in (ROOT / 'release').iterdir():
        if path.is_file() and path.name in (
                'install_candidate.py', 'awg_config_candidate.py', 'awg_service.py',
                'backup_candidate.py', 'upgrade_candidate.py', 'prepare_candidate.py',
                '3xui-pro-fork.service', '3xui-pro-fork-awg.service', 'README-CANDIDATE.md'):
            shutil.copyfile(path, output / path.name)
    return output
