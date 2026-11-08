#!/usr/bin/env bash
# Refresh allowed_ips4.txt and allowed_ips6.txt from the official FortiWeb Cloud lists.
set -euo pipefail

cd "$(dirname "$0")"

for v in 4 6; do
    tmp="$(mktemp)"
    curl -fsSL --retry 3 "https://www.fortiweb-cloud.com/ips-v${v}" -o "$tmp"
    # Make sure the content looks like a CIDR list before overwriting the file
    if [ ! -s "$tmp" ] || grep -qvE '^[0-9A-Fa-f:.]+/[0-9]+$|^$' "$tmp"; then
        echo "Unexpected content in ips-v${v}; file not updated." >&2
        rm -f "$tmp"
        exit 1
    fi
    grep -v '^$' "$tmp" | sort -u -V > "allowed_ips${v}.txt"
    rm -f "$tmp"
    echo "allowed_ips${v}.txt: $(wc -l < "allowed_ips${v}.txt" | tr -d ' ') addresses"
done
