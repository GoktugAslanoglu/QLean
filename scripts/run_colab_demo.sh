#!/usr/bin/env bash
# Use an existing Colab GPU session. Only source crosses the upload boundary.
set -euo pipefail
cd "$(dirname "$0")/.."
session=${1:?usage: scripts/run_colab_demo.sh EXISTING_COLAB_SESSION}
root=${QLEAN_ROOT:-/tmp/qlean}
mode=${2:-all}
case "$root" in /tmp/qlean|/content/qlean) ;; *) exit 2 ;; esac
case "$mode" in all|repair|wall|audit|phase3|package|terms) ;; *) exit 2 ;; esac

launcher=$(cat <<'PY'
import json, os, subprocess, sys, tarfile, tempfile, time
from pathlib import Path

os.umask(0o077)
root = Path(sys.argv[1])
if root.resolve() != root or (root.exists() and root.stat().st_uid != os.getuid()):
    raise RuntimeError("Unsafe ephemeral QLean storage root")
root.mkdir(mode=0o700, exist_ok=True)
source = Path(tempfile.mkdtemp(prefix="demo-source.", dir=root))
with tarfile.open(fileobj=sys.stdin.buffer, mode="r|*") as payload:
    payload.extractall(source, filter="data")
log, status = source / "demo.log", source / "demo.exit"
with log.open("wb") as output:
    entry = source / ("colab/run_phase3_vm.sh" if sys.argv[2] == "phase3" else "demos/run.sh")
    mode = "all" if sys.argv[2] == "phase3" else sys.argv[2]
    job = subprocess.Popen(
        ["bash", "-c", 'bash "$1" "$2"; rc=$?; printf "%s\\n" "$rc" > "$3"; exit "$rc"',
         "qlean-demos", str(entry), mode, str(status)],
        stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
        start_new_session=True, env={**os.environ, "QLEAN_ROOT": str(root)},
    )
info = {"pid": job.pid, "source": str(source), "log": str(log), "status": str(status)}
(root / "latest-demo.json").write_text(json.dumps(info))
print(json.dumps(info), flush=True)
with log.open(encoding="utf-8", errors="replace") as output:
    while job.poll() is None:
        data = output.read()
        if data:
            print(data, end="", flush=True)
        else:
            print("QLean demo job is running", flush=True)
        time.sleep(15)
    print(output.read(), end="", flush=True)
raise SystemExit(job.wait())
PY
)

scripts/phase3_source.sh --demos | colab ssh -s "$session" -- python3 -c "$launcher" "$root" "$mode"
