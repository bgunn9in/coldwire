#!/usr/bin/env python3
"""Reproduce the pinned Xray binary bundle on the operator/build computer."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import urllib.request
import zipfile

VERSION = '26.10.21'
UPSTREAM_SHA256 = '0eec3ed4163c273d8c8bf821f7d219e257921cf584aa3fb970715e458e631978'
URL = f'https://github.com/XTLS/Xray-core/releases/download/v{VERSION}/Xray-linux-64.zip'


def main():
    root = Path(__file__).resolve().parents[1]
    destination = root / 'dist/xray-native-linux-amd64.tar.gz'
    if destination.exists():
        raise FileExistsError('Never overwrite a released bundle; use a separate build checkout')
    with urllib.request.urlopen(URL, timeout=120) as response:
        raw = response.read(40_000_001)
    if len(raw) > 40_000_000 or hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('Upstream archive SHA256 mismatch')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        files = {name: archive.read(name) for name in ('xray', 'LICENSE')}
    manifest = {'version': VERSION, 'platform': 'linux-amd64', 'upstream_sha256': UPSTREAM_SHA256,
                'source': f'https://github.com/XTLS/Xray-core/tree/v{VERSION}',
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    files['manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    with destination.open('xb') as output, gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for name, data in sorted(files.items()):
                member = tarfile.TarInfo(name)
                member.size, member.mode = len(data), 0o755 if name == 'xray' else 0o644
                archive.addfile(member, io.BytesIO(data))
    checksum = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_name('xray-native-linux-amd64.sha256').write_text(checksum + '  ' + destination.name + '\n', encoding='ascii')
    print('Verified Xray', VERSION, 'bundle SHA256', checksum)


if __name__ == '__main__':
    main()
