"""Verify the Debian security Nginx packages used by the public candidate."""
import subprocess


VERSION = '1.26.3-3+deb13u11'
POOL = 'https://deb.debian.org/debian-security/pool/updates/main/n/nginx/'
PACKAGES = {
    'nginx': ('amd64', 'eb3fdf2605e8c3c0ed45fff6aa2f399a65b53aa077a1489452aa32aa924fa3c3'),
    'nginx-common': ('all', '7df3591cba60afd80eb6950aa965ab0b9e34a46c6dff78c4862187a7c9af244b'),
    'libnginx-mod-stream': ('amd64', '6c84287e59c708c2cde309bf8a4a38095a7fbd41e6d915780367c39c3ba66752'),
}


def missing():
    absent = []
    for name in PACKAGES:
        result = subprocess.run(['dpkg-query', '-W', '-f=${db:Status-Status}\t${Version}', name],
                                 capture_output=True, text=True, timeout=10)
        status, _, version = result.stdout.partition('\t')
        if result.returncode == 1 and not status:
            absent.append(name)
        elif result.returncode or status != 'installed' or version != VERSION:
            raise RuntimeError(f'{name}: expected installed Debian package {VERSION}; no automatic replacement')
    return absent


def stage(directory, names, download):
    archives = []
    for name in names:
        arch, checksum = PACKAGES[name]
        filename = f'{name}_{VERSION}_{arch}.deb'
        path = directory / filename
        download(POOL + filename, checksum, path)
        path.chmod(0o644)
        for field, expected in (('Package', name), ('Version', VERSION), ('Architecture', arch)):
            actual = subprocess.check_output(['dpkg-deb', '-f', str(path), field], text=True).strip()
            if actual != expected:
                raise RuntimeError(f'{filename}: invalid {field}')
        archives.append(str(path))
    return archives
