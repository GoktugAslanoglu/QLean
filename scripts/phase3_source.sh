#!/usr/bin/env bash
# Stream a source-only tar archive to stdout.
set -euo pipefail
cd "$(dirname "$0")/.."
{
    find colab kernel -type f \( -name '*.py' -o -name '*.sh' -o -name '*.c' \
        -o -name '*.h' -o -name '*.S' -o -name '*.ld' -o -name '*.inc' -o -name 'Makefile' \) -print0
    printf '%s\0' scripts/check_stack.py
    if [[ ${1:-} == --demos ]]; then
        printf '%s\0' qlean.py LICENSE
        find demos -maxdepth 1 -type f \( -name '*.py' -o -name '*.sh' \) -print0
        find hf -maxdepth 1 -type f \( -name '*.py' -o -name '*.json' -o -name '*.md' \) -print0
    fi
} | tar --null --files-from=- -cf -
