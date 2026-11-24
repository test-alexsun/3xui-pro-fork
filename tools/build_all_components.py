#!/usr/bin/env python3
"""Stage verified, pinned Linux components; this is not an installer or release."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import zipfile

RELEASE_FILES = Path(__file__).resolve().parents[1] / 'release'


PANEL_ARCHIVE = '0ddfa4702f595442e2962acd81addc768fdacaa4ff2672c971a0463dae744916'
PANEL_BINARY = 'fb7b3776334fce69299f90168c8c31377b69f89c7787088e6dbf561d07b3d345'
XRAY_ARCHIVE = 'b651f7e1d9966ee2c1b1ee1bf8b52c72771824d3065dce96bbc8bcc19ed95f82'
AWG_BINARIES = {
    'awg': 'a604430b4b85e1cfb2e5a9fbd3ca0219e5cd1a0a0173243c0a4201332b522d28',
    'amneziawg-go': 'fdfee29667271d584be54459a100c53e91772ca55585d3f214d173d98ef13b59',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify(data, expected, name):
    if sha(data) != expected:
        raise ValueError(f'{name}: SHA256 mismatch')


def elf(data, name):
    if data[:6] != b'\x7fELF\x02\x01' or data[18:20] != b'\x3e\x00':
        raise ValueError(f'{name}: Linux amd64 ELF required')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--panel', type=Path, required=True)
    p.add_argument('--xray', type=Path, required=True)
    p.add_argument('--awg-bin', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--candidate-archive', type=Path,
                   help='write an incomplete fresh-install candidate, not a release')
    a = p.parse_args()
    if a.output.exists():
        raise ValueError('output must not already exist')
    verify(a.panel.read_bytes(), PANEL_ARCHIVE, 'panel archive')
    verify(a.xray.read_bytes(), XRAY_ARCHIVE, 'Xray archive')
    with tarfile.open(a.panel, 'r:gz') as archive:
        paths = ('x-ui/x-ui', 'x-ui/bin/geoip.dat', 'x-ui/bin/geosite.dat')
        panel, geoip, geosite = (archive.extractfile(path).read() for path in paths)
    with zipfile.ZipFile(a.xray) as archive:
        xray = archive.read('xray')
    verify(panel, PANEL_BINARY, 'panel binary')
    components = {'panel/x-ui': panel, 'panel/bin/xray-linux-amd64': xray,
                  'panel/bin/geoip.dat': geoip, 'panel/bin/geosite.dat': geosite}
    for name, expected in AWG_BINARIES.items():
        data = (a.awg_bin / name).read_bytes()
        verify(data, expected, name)
        components['awg/' + name] = data
    for name in ('panel/x-ui', 'panel/bin/xray-linux-amd64', 'awg/awg', 'awg/amneziawg-go'):
        elf(components[name], name)
    a.output.mkdir(parents=True)
    for name, data in components.items():
        path = a.output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o755 if name in ('panel/x-ui', 'panel/bin/xray-linux-amd64', 'awg/awg', 'awg/amneziawg-go') else 0o644)
    manifest = {'status': 'STAGED_NOT_A_RELEASE', 'panel': '3.11.0', 'xray': '26.11.9',
                'awg_runtime': '3.1.20260828', 'awg_tools': '3.1.20260812',
                'sources': {
                    'panel': {'url': 'https://github.com/MHSanaei/3x-ui/releases/download/v3.11.0/x-ui-linux-amd64.tar.gz', 'sha256': PANEL_ARCHIVE},
                    'xray': {'url': 'https://github.com/XTLS/Xray-core/releases/download/v26.11.9/Xray-linux-64.zip', 'sha256': XRAY_ARCHIVE},
                    'awg_runtime': {'commit': 'b5928efb6ca19f0153958460c3d141f04abc5c2e', 'source_sha256': '10bf7458e090bf52f87df27adcd3904a60e4d17fab844d9415e46379147f1ab4'},
                    'awg_tools': {'commit': 'ee0f0a9aa34ff0a0da4b3433b9512781cfe02843', 'source_sha256': '22438f231d39ea27e4bdc69707ec3103357f3cecc9ad3eecba18a61e5b39c9b9'}},
                'awg_provenance': 'prebuilt reproducible baseline; verify build separately',
                'files': {name: sha(data) for name, data in components.items()}}
    (a.output / 'components-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    if a.candidate_archive:
        if a.candidate_archive.exists():
            raise ValueError('candidate archive must not already exist')
        a.candidate_archive.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(a.candidate_archive, 'x:gz') as archive:
            for name in sorted([*components, 'components-manifest.json']):
                path = a.output / name
                info = archive.gettarinfo(str(path), arcname=name)
                info.mode = 0o755 if name in ('panel/x-ui', 'panel/bin/xray-linux-amd64', 'awg/awg', 'awg/amneziawg-go') else 0o644
                info.uid = info.gid = 0
                info.uname = info.gname = ''
                with path.open('rb') as stream:
                    archive.addfile(info, stream)
            for name in ('install_candidate.py', 'awg_config_candidate.py', 'awg_service.py',
                         'backup_candidate.py', 'upgrade_candidate.py', 'prepare_candidate.py',
                         '3xui-pro-fork.service', '3xui-pro-fork-awg.service', 'README-CANDIDATE.md'):
                path = RELEASE_FILES / name
                info = archive.gettarinfo(str(path), arcname=name)
                info.mode = 0o755 if name.endswith('.py') else 0o644
                info.uid = info.gid = 0
                info.uname = info.gname = ''
                with path.open('rb') as stream:
                    archive.addfile(info, stream)
    print(json.dumps({'status': manifest['status'], 'output': str(a.output), 'files': len(components)}))


if __name__ == '__main__':
    main()
