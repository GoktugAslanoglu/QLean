#!/usr/bin/env bash
# Try three ordered rounds. Each CLI invocation makes one allocation request.
set -euo pipefail

session=${1:-qlean-phase3}
output=$(mktemp /tmp/qlean-colab-allocation.XXXXXX)
trap 'rm -f -- "$output"' EXIT
for round in 1 2 3; do
    for gpu in L4 A100 G4 H100; do
        printf 'Round %s/3: %s\n' "$round" "$gpu"
        if COLAB_CLI_ASSIGN_RETRIES=0 COLAB_CLI_REQUEST_TIMEOUT=75 \
            colab new -s "$session" --gpu "$gpu" >"$output" 2>&1; then
            cat "$output"
            exit 0
        fi
        if grep -Eiq 'service unavailable|HTTP( error)? 503' "$output"; then
            printf 'Round %s: %s returned HTTP 503\n' "$round" "$gpu"
        elif grep -Eiq 'ReadTimeout|timed out' "$output"; then
            printf 'Round %s: %s timed out\n' "$round" "$gpu"
        else
            printf 'Round %s: %s allocation failed\n' "$round" "$gpu"
            tail -n 8 "$output" >&2
        fi
    done
    if ((round < 3)); then
        delay=$((5 * 2 ** (round - 1)))
        printf 'Waiting %s seconds before round %s\n' "$delay" "$((round + 1))"
        sleep "$delay"
    fi
done
exit 75
