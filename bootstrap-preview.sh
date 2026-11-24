#!/bin/sh
# Bootstrap one reviewed commit of the standalone Debian preview from GitHub.
set -eu
umask 077

usage() {
    echo 'Usage: sudo sh bootstrap-preview.sh 40_HEX_COMMIT --domain DOMAIN --awg-subnet SUBNET [installer options]' >&2
    exit 2
}

[ "$#" -ge 2 ] || usage
revision=$1
shift
case "$revision" in *[!0123456789abcdef]*) usage ;; esac
[ "${#revision}" -eq 40 ] || usage
for option do
    case "$option" in --components|--components=*|--comp*) usage ;; esac
done
[ "$(id -u)" -eq 0 ] || { echo 'Root is required.' >&2; exit 2; }
[ "$(uname -s):$(uname -m)" = 'Linux:x86_64' ] || { echo 'Linux amd64 is required.' >&2; exit 2; }
if ! grep -qx 'ID=debian' /etc/os-release ||
   ! grep -Eq '^VERSION_ID="?13"?$' /etc/os-release; then
    echo 'Debian 13 is required.' >&2
    exit 2
fi
[ "$(cat /proc/1/comm)" = 'systemd' ] || { echo 'Running systemd is required.' >&2; exit 2; }

missing=
for dependency in git ca-certificates python3; do
    case "$dependency" in
        ca-certificates) [ -s /etc/ssl/certs/ca-certificates.crt ] && continue ;;
        *) command -v "$dependency" >/dev/null 2>&1 && continue ;;
    esac
    missing="${missing:-} $dependency"
done
if [ -n "${missing:-}" ]; then
    command -v apt-get >/dev/null
    DEBIAN_FRONTEND=noninteractive apt-get update
    # Each word comes from the fixed dependency allowlist above.
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends $missing
fi

checkout=$(mktemp -d)
trap 'rm -rf -- "$checkout"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_TERMINAL_PROMPT=0
git -c init.defaultBranch=preview init -q "$checkout"
git -C "$checkout" -c fetch.fsckObjects=true fetch --quiet --depth=1 --no-tags \
    https://github.com/test-alexsun/3xui-pro-fork.git "$revision"
[ "$(git -C "$checkout" rev-parse 'FETCH_HEAD^{commit}')" = "$revision" ] ||
    { echo 'GitHub revision verification failed.' >&2; exit 1; }
git -C "$checkout" -c core.hooksPath=/dev/null switch --quiet --detach "$revision"
sh "$checkout/install-preview.sh" "$@"
