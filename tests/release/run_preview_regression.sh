#!/bin/sh
set -eu

# Mount the historical archive at /src and the current preview at /preview.
# The historical runner requires native Docker volumes at /work and /checkpoint.
if [ ! -f /.dockerenv ] || [ "$(id -u)" -ne 0 ] ||
   [ "$(ls /sys/class/net)" != lo ]; then
    echo 'Run in a root Debian container with --network none.' >&2
    exit 2
fi
if [ ! -f /src/tests/awg31/run_full_regression.sh ] ||
   [ ! -f /preview/release/preview_install.py ]; then
    echo 'Mount the separate historical and preview trees.' >&2
    exit 2
fi

printf '%s\n' '=== Historical unified regression (/src -> /work) ==='
historical_status=0
sh /src/tests/awg31/run_full_regression.sh || historical_status=$?

printf '%s\n' '=== Current preview regression (/preview) ==='
preview_status=0
cd /preview
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/release -v ||
    preview_status=$?

printf 'Historical exit: %s; preview exit: %s\n' "$historical_status" "$preview_status"
if [ "$historical_status" -ne 0 ]; then
    exit "$historical_status"
fi
exit "$preview_status"
