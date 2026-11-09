#!/usr/bin/env bash
# Build on Ubuntu 22.04 amd64, once on a build machine, never on the small VPS.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run on a build machine as root'; exit 1; }
source /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 22.04 && $(uname -m) == x86_64 ]] || { echo 'Only Ubuntu 22.04 amd64 is supported; other versions have not been tested'; exit 1; }
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
[[ ! -e $repo/dist/awg-native-linux-amd64.tar.gz ]] || { echo 'Bundle already exists; never overwrite a released build'; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends build-essential ca-certificates curl git
work=$(mktemp -d /tmp/awg-native-build.XXXXXXXX)
trap 'rm -rf -- "$work"' EXIT
curl --fail --location --retry 3 -o "$work/go.tar.gz" https://go.dev/dl/go1.25.12.linux-amd64.tar.gz
printf '234828b7a89e0e303d2556310ee549fbcf253d28de937bac3da13d6294262ac1  %s\n' "$work/go.tar.gz" | sha256sum -c -
tar -xzf "$work/go.tar.gz" -C "$work"
git init -q "$work/go-source"
git -C "$work/go-source" fetch -q --depth=1 https://github.com/amnezia-vpn/amneziawg-go.git 1b86b2ae0e493e7ea93f8c1a0f0cb6735b1551f1
git -C "$work/go-source" checkout -q FETCH_HEAD
git init -q "$work/tools-source"
git -C "$work/tools-source" fetch -q --depth=1 https://github.com/amnezia-vpn/amneziawg-tools.git ee0f0a9aa34ff0a0da4b3433b9512781cfe02843
git -C "$work/tools-source" checkout -q FETCH_HEAD
mkdir "$work/bundle"
export GOTOOLCHAIN=local GOMAXPROCS=2 CGO_ENABLED=0
cd "$work/go-source"
"$work/go/bin/go" mod download
"$work/go/bin/go" mod verify
"$work/go/bin/go" build -trimpath -ldflags='-s -w -buildid=' -o "$work/bundle/amneziawg-go" .
make -C "$work/tools-source/src" -j2 WIREGUARD_TOOLS_VERSION=3.1.20260812
install -m755 "$work/tools-source/src/wg" "$work/bundle/awg"
strip "$work/bundle/awg"
cp "$work/go-source/LICENSE" "$work/bundle/LICENSE.amneziawg-go"
cp "$work/tools-source/COPYING" "$work/bundle/COPYING.amneziawg-tools"
# Include corresponding source for the GPL tool; other source is pinned in the manifest.
git -C "$work/tools-source" archive --format=tar.gz HEAD > "$work/bundle/amneziawg-tools-source.tar.gz"
export AWG_BUILD_WORK="$work" AWG_BUILD_REPO="$repo"
python3 - <<'PY'
import hashlib,json,os,pathlib,tarfile
work=pathlib.Path(os.environ['AWG_BUILD_WORK']);repo=pathlib.Path(os.environ['AWG_BUILD_REPO']);bundle=work/'bundle'
manifest={'format':1,'platform':'linux-amd64','minimum_glibc':'2.35','go_version':'1.25.12',
          'awg_go_commit':'1b86b2ae0e493e7ea93f8c1a0f0cb6735b1551f1','awg_tools_commit':'ee0f0a9aa34ff0a0da4b3433b9512781cfe02843',
          'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(bundle.iterdir())}}
(bundle/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
(repo/'dist').mkdir(exist_ok=True)
archive=repo/'dist/awg-native-linux-amd64.tar.gz'
with tarfile.open(archive,'w:gz') as out:
    for p in sorted(bundle.iterdir()):out.add(p,arcname=p.name)
checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
(repo/'dist/awg-native-linux-amd64.sha256').write_text(checksum+'  awg-native-linux-amd64.tar.gz\n')
print('Built native bundle, bytes:',archive.stat().st_size,'SHA256:',checksum)
PY
