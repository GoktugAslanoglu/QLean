#!/usr/bin/env bash
# Launch Phase 3 on a named Colab CLI session using ephemeral VM storage.
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "usage: $0 COLAB_SESSION [all|prepare|verify]" >&2
    exit 2
fi
session=$1
mode=${2:-all}
vm_root=${QLEAN_ROOT:-/tmp/qlean}
detach=${QLEAN_DETACH:-0}
case "$vm_root" in
    /tmp/qlean|/content/qlean) ;;
    *) echo "Unsupported VM storage root: $vm_root" >&2; exit 2 ;;
esac
case "$detach" in
    0|1) ;;
    *) echo "QLEAN_DETACH must be 0 or 1" >&2; exit 2 ;;
esac
case "$mode" in
    all|prepare|verify) ;;
    *) echo "Unknown Phase 3 mode: $mode" >&2; exit 2 ;;
esac
root=$(cd "$(dirname "$0")/.." && pwd)
archive=$(mktemp /tmp/qlean-phase3-source.XXXXXX)
trap 'rm -f -- "$archive"' EXIT
"$root/scripts/phase3_source.sh" >"$archive"
colab upload -s "$session" "$archive" content/qlean-phase3-source.tar
colab exec -s "$session" --timeout 7200 <<PY
import os
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile

os.umask(0o077)
root = Path("$vm_root")
if root.resolve() != root or (root.exists() and root.stat().st_uid != os.getuid()):
    raise RuntimeError("Unsafe ephemeral storage root")
root.mkdir(mode=0o700, exist_ok=True)
source = Path(tempfile.mkdtemp(prefix="source.", dir=root))
archive = Path("/content/qlean-phase3-source.tar")
with tarfile.open(archive) as payload:
    payload.extractall(source, filter="data")
archive.unlink()
command = ["bash", str(source / "colab/run_phase3_vm.sh"), "$mode"]
env = {**os.environ, "QLEAN_ROOT": str(root)}
if "$detach" == "1":
    status = source / "run.exit"
    log = source / "run.log"
    wrapper = 'bash "\$1" "\$2"; rc=\$?; printf "%s\\n" "\$rc" > "\$3"; exit "\$rc"'
    with log.open("wb") as stream:
        job = subprocess.Popen(
            ["bash", "-c", wrapper, "qlean-job", command[1], command[2], str(status)],
            stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
            start_new_session=True, env=env,
        )
    info = {"pid": job.pid, "source": str(source), "log": str(log), "status": str(status)}
    (root / "latest-job.json").write_text(json.dumps(info))
    print(json.dumps(info), flush=True)
else:
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, bufsize=1, env=env) as job:
        for line in job.stdout:
            print(line, end="", flush=True)
        if job.wait():
            raise RuntimeError(f"QLean verification failed with status {job.returncode}")
PY
