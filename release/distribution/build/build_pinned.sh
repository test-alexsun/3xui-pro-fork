#!/bin/bash
set -Eeuo pipefail
umask 077
export PATH=/usr/local/go/bin:/usr/sbin:/usr/bin:/sbin:/bin GOTOOLCHAIN=local GOENV=off
here=$(cd -- "$(dirname -- "$0")" && pwd)
[[ $(uname -s) == Linux && $(uname -m) == x86_64 && -f /.dockerenv ]] || { echo 'requires isolated Linux amd64 container' >&2; exit 2; }
. /etc/os-release
[[ $ID == debian && $VERSION_ID == 13 ]] || { echo 'requires Debian 13' >&2; exit 2; }
for cmd in go gcc make python3 sha256sum dpkg-query; do command -v "$cmd" >/dev/null || { echo "missing dependency: $cmd" >&2; exit 2; }; done
[[ $(go version) == 'go version go1.27.3 linux/amd64' ]] || { echo 'requires Go 1.27.3 linux/amd64' >&2; exit 2; }
[[ $(sha256sum "$(command -v go)" | cut -d' ' -f1) == 5f5eb6d0b2fb6aa0bb5d5f8c5f1c944e0de955c925f0111af92a9d8f79680b5b ]] || { echo 'Go executable SHA256 mismatch' >&2; exit 2; }
[[ $# -ge 2 && $# -le 3 ]] || { echo 'usage: build_pinned.sh BUILD_DIR SOURCE_CACHE [--offline]' >&2; exit 2; }
build=$1; cache=$2; mode=${3:-}
[[ -z $mode || $mode == --offline ]] || exit 2
[[ ! -e $build ]] || { echo 'build directory must not exist' >&2; exit 2; }
mkdir -p "$(dirname "$build")"; mkdir "$build"; build=$(cd "$build" && pwd)
python3 "$here/prepare_sources.py" --cache "$cache" ${mode:+"$mode"}
python3 "$here/extract_sources.py" "$cache/runtime.tar.gz" "$build" amneziawg-go-b5928efb6ca19f0153958460c3d141f04abc5c2e
python3 "$here/extract_sources.py" "$cache/tools.tar.gz" "$build" amneziawg-tools-ee0f0a9aa34ff0a0da4b3433b9512781cfe02843
runtime=$build/amneziawg-go-b5928efb6ca19f0153958460c3d141f04abc5c2e
tools=$build/amneziawg-tools-ee0f0a9aa34ff0a0da4b3433b9512781cfe02843
[[ -f $runtime/go.mod && -f $runtime/main.go && -f $tools/src/Makefile && -f $tools/src/wg.c ]] || { echo 'unexpected source layout' >&2; exit 1; }
printf 'package main\n\nconst Version = "v3.1.20260828"\n' > "$runtime/version.go"
mkdir "$build/bin"
if [[ $mode == --offline ]]; then export GOPROXY=off GOSUMDB=off; fi
(cd "$runtime" && CGO_ENABLED=0 go build -mod=readonly -trimpath -buildvcs=false -o "$build/bin/amneziawg-go" .)
make -C "$tools/src" V=1 wg
install -m 0755 "$tools/src/wg" "$build/bin/awg"
"$build/bin/awg" --version
"$build/bin/amneziawg-go" --version
python3 - "$build" "$cache" <<'PY'
import hashlib,json,os,platform,subprocess,sys
from pathlib import Path
b=Path(sys.argv[1]); c=Path(sys.argv[2])
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
r={'source':{'runtime':{'commit':'b5928efb6ca19f0153958460c3d141f04abc5c2e','sha256':sha(c/'runtime.tar.gz')},'tools':{'commit':'ee0f0a9aa34ff0a0da4b3433b9512781cfe02843','sha256':sha(c/'tools.tar.gz')}},'go':subprocess.check_output(['go','version'],text=True).strip(),'go_origin':'golang@sha256:d9b6a1beb9474adc2a1ce842573639b44b2a0dd49b6669f51d3821baf9ec37c9 /usr/local/go','flags':{'go':'CGO_ENABLED=0 -mod=readonly -trimpath -buildvcs=false','tools':'make V=1 wg'},'dependencies':subprocess.check_output(['dpkg-query','-W','gcc','libc6-dev','make','python3'],text=True).splitlines(),'binaries':{n:sha(b/'bin'/n) for n in ('awg','amneziawg-go')}}
(b/'manifest.json').write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps(r,indent=2))
PY
