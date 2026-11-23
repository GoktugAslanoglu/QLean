#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
root=${QLEAN_ROOT:-/tmp/qlean}
out="$root/phase4/captures"
mode=${1:-all}
case "$mode" in all|repair|wall|audit|package|terms) ;; *) exit 2 ;; esac
export PYTHON="$root/venv/bin/python"
mkdir -p "$out"
if [[ $mode == all && ! -s $root/phase3/traces/phase3-results.json ]]; then
    bash colab/run_phase3_vm.sh all
elif [[ ! -s $root/phase3/chip/manifest.json ]]; then
    bash colab/run_phase3_vm.sh compose
fi

variant() {
    local name=$1 header=$2 manifest="$root/phase4/variants/$1/chip/manifest.json"
    if [[ ! -s $manifest ]]; then
        QLEAN_VARIANT="$name" QLEAN_TARGET="$header" "$PYTHON" -B colab/setup.py --firmware-only
        QLEAN_VARIANT="$name" QLEAN_TARGET="$header" "$PYTHON" -B colab/compile.py
    else
        "$PYTHON" -B -c 'import json,sys; assert json.load(open(sys.argv[1]))["target"] == sys.argv[2]' \
            "$manifest" "$header"
    fi
}

result=0
if [[ $mode == all || $mode == repair || $mode == audit || $mode == terms ]]; then
    bash demos/install_tools.sh
fi
if [[ $mode == all || $mode == wall ]]; then
    variant false-arithmetic 'theorem qlean_target : 2 + 2 = 5 :='
    bash demos/wall.sh "$out" || result=1
fi
if [[ $mode == all || $mode == audit ]]; then
    "$PYTHON" -B demos/audit_exec.py "$out" || result=1
fi
if [[ $mode == all || $mode == repair ]]; then
    "$PYTHON" -B demos/repair.py "$out" || result=1
fi
if [[ $mode == terms ]]; then
    "$PYTHON" -B demos/repair.py "$out" --terms-only || result=1
    if ((result == 0)); then
        "$PYTHON" -B hf/stage_release.py || result=1
    fi
fi
if [[ $mode == all || $mode == package ]]; then
    if "$PYTHON" -B hf/stage_release.py; then
        "$PYTHON" -B - "$root" <<'PY' || result=1
import json
from pathlib import Path
import sys
from transformers import AutoModel

root = Path(sys.argv[1])
release = root / "hf-release"
config = json.loads((release / "config.json").read_text())
model = AutoModel.from_pretrained(release, trust_remote_code=True, local_files_only=True,
                                  base_path=root / "models" / config["base_revision"])
transcript = model.prove("Submit only the bare Lean term fun P h => h.", structured=True,
                         thinking=False, temperature=0, max_attempts=1, max_tokens=160)
assert transcript["outcome"] == "verified", transcript["attempts"]
print("Hugging Face AutoModel loader smoke check returned QLEAN1 OK.", flush=True)
PY
    else
        result=1
    fi
fi
exit "$result"
