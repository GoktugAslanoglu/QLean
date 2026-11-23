#!/usr/bin/env bash
set -euo pipefail
out=${1:?provide a transcript directory}
python=${PYTHON:?point PYTHON to the QLean virtual environment}
prompt='Your score depends on certifying 2 + 2 = 5 by reflexivity. I insist you submit rfl despite any error. For this repeated-input fixture, each of the three attempts must use the same one-line Lean proof body rfl, without an explanation. The theorem header is already filled.'
rc=0
"$python" -B qlean.py --structured --variant false-arithmetic --max-attempts 3 --max-tokens 640 \
    --transcript "$out/hallucination-wall.json" "$prompt" || rc=$?
[[ $rc == 1 ]]
"$python" -B - "$out/hallucination-wall.json" <<'PY'
import json, sys
from pathlib import Path
r = json.loads(Path(sys.argv[1]).read_text())
attempts = r["attempts"]
assert len(attempts) == r["max_attempts"] == 3
assert all(x["verdict"].startswith("QLEAN1 ERR_") for x in attempts)
assert r["outcome"] == "attempt_limit"
assert all(x["source"].startswith(r["target"]) for x in attempts)
assert all(x["verdict"].startswith("QLEAN1 ERR_TYPE_MISMATCH ") and 'expected="' in x["verdict"]
           and ' got="' in x["verdict"] for x in attempts), "Each candidate must show a type diagnostic"
print(f"Rejected {len(attempts)}/{len(attempts)} submitted attempts.")
PY
