#!/usr/bin/env bash
set -euo pipefail
root=${QLEAN_ROOT:-/tmp/qlean}
tools="$root/phase4/tools"
mkdir -p "$tools"
if ! command -v strace >/dev/null || ! command -v zstd >/dev/null; then
    admin=()
    if ((EUID != 0)); then admin=(sudo -n); fi
    "${admin[@]}" apt-get -qq install -y strace zstd
fi
if [[ ! -x $tools/lean-4.36.0-linux/bin/lean ]]; then
    curl -fsSL --retry 2 https://github.com/leanprover/lean4/releases/download/v4.36.0/lean-4.36.0-linux.tar.zst |
        tar -I zstd -x -C "$tools" --wildcards '*/bin/lean' '*/lib/lean/Init*' \
            '*/lib/lean/liblean*.so' '*/lib/lean/libInit_shared.so'
fi
"$tools/lean-4.36.0-linux/bin/lean" --version
