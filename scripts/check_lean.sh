#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "usage: $0 /path/to/qlean-host" >&2
    exit 2
fi
root=$(cd "$(dirname "$0")/.." && pwd)
host=$(realpath "$1")
lean=$(command -v "${LEAN:-lean}")
pin=$(<"$root/lean-toolchain")
want=${pin##*:v}
version=$("$lean" --version)
if [[ $version != "Lean (version $want, "* || $version != *"commit 611c117bfaf7b7ae1cfcf246ce6fba31e8f509e9,"* ]]; then
    echo "Expected official Lean $want, got $version" >&2
    exit 2
fi

scratch=$(mktemp -d /tmp/qlean-lean-check.XXXXXX)
trap 'rm -r -- "$scratch"' EXIT
cd "$scratch"
unset LEAN_PATH LEAN_SRC_PATH
check() {
    timeout 30 "$lean" --root="$scratch" "$1" >lean.log 2>&1
}
valid=0
invalid=0
PYTHONDONTWRITEBYTECODE=1 python3 - "$root" <<'PY'
from pathlib import Path
import sys

sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
from test_kernel import TRUSTED_HEADER, cases

Path("valid").mkdir()
for case in cases():
    if case.expected == "OK":
        Path("valid", case.name + ".lean").write_bytes(case.source)
Path("valid/goal_binding.lean").write_bytes(TRUSTED_HEADER + b" rfl")
PY
for file in valid/*.lean; do
    if [[ $("$host" <"$file") != "QLEAN1 OK" ]]; then
        echo "Native checker rejected $file" >&2
        exit 1
    fi
    cp -- "$file" fixture.lean
    cmp -- "$file" fixture.lean
    if ! check fixture.lean || grep -Eq '(error[:(]|uses .sorry.)' lean.log; then
        echo "Lean rejected the original source in $file" >&2
        cat lean.log >&2
        exit 1
    fi
    name=$(sed -nE '1s/^theorem (qlean_[a-z][a-z0-9_]*).*/\1/p' fixture.lean)
    cp -- fixture.lean axioms.lean
    printf '\n#print axioms %s\n' "$name" >>axioms.lean
    if ! check axioms.lean || ! grep -Fxq "'$name' does not depend on any axioms" lean.log; then
        echo "Axiom check failed for $file" >&2
        cat lean.log >&2
        exit 1
    fi
    ((valid += 1))
done
while IFS=$'\t' read -r name expected also_lean; do
    [[ $name == '#'* || $also_lean != 1 ]] && continue
    cp -- "$root/tests/invalid/$name" fixture.lean
    status=0
    check fixture.lean || status=$?
    if [[ $status -ne 1 ]] || ! grep -Eq 'error[:(]' lean.log; then
        echo "Lean did not report a source error for $name (status $status)" >&2
        cat lean.log >&2
        exit 1
    fi
    ((invalid += 1))
done <"$root/tests/invalid/expect.tsv"

cp -- "$root/tests/lean_oracle.lean" oracle.lean
if ! check oracle.lean || [[ -s lean.log ]]; then
    echo "Lean sort or Nat.rec oracle failed" >&2
    cat lean.log >&2
    exit 1
fi

printf '%s\n' "$version"
printf '%d exact-byte accepted theorems with zero axioms, %d negative Lean source rejections\n' "$valid" "$invalid"
printf '%s\n' 'Lean sort hierarchy, Nat.rec signature, and zero/successor reduction agree'
