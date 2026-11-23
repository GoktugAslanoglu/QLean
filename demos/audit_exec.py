"""Capture exec events during a live, model-generated proof check."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import re
import subprocess
import sys

EVENT = re.compile(r"^\s*(?:\d+\s+)?(\d+\.\d+)\s+(execve(?:at)?)\(")
PROMPT = ("For this execution-audit fixture, submit the Lean term fun P h => h. "
          "Output the bare term on one line, without a theorem header, code fence, or tactics.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    raw = args.output / "execve.raw.log"
    marker = args.output / "execve-start.ns"
    transcript = args.output / "zero-subprocess.json"
    marker.unlink(missing_ok=True)
    command = ["strace", "-f", "-ttt", "-e", "trace=execve,execveat", "-o", str(raw),
               sys.executable, "-B", "qlean.py", "--structured", "--max-attempts", "3", "--max-tokens", "256",
               "--started-marker", str(marker), "--transcript", str(transcript), "--json", PROMPT]
    completed = subprocess.run(command, stdout=subprocess.PIPE, text=True)
    result = json.loads(transcript.read_text())
    assert json.loads(completed.stdout) == result, "JSON stdout differs from the transcript file"
    print(result["terminal"], end="", flush=True)
    completed.check_returncode()
    trace = raw.read_text().splitlines()
    boundary_us = int(marker.read_text()) // 1000
    starts = []
    for line in trace:
        match = EVENT.match(line)
        if match:
            starts.append((int(Decimal(match[1]) * 1_000_000), match[2]))
        elif re.search(r"\bexecve(?:at)?\(", line):
            raise RuntimeError("An exec event could not be parsed")
    assert starts, "The trace omitted the traced Python startup"
    after = [event for event in starts if event[0] >= boundary_us]
    assert result["outcome"] == "verified" and result["attempts"][-1]["verdict"] == "QLEAN1 OK"
    report = {
        "scope": "After model/chip warm-up and prompt prefill through verifier verdict and process exit",
        "trace": "strace -f -ttt -e trace=execve,execveat",
        "verification_start_epoch_us": boundary_us,
        "startup_exec_calls": len(starts) - len(after),
        "verification_exec_calls": len(after),
        "verdict": result["attempts"][-1]["verdict"],
    }
    (args.output / "execve-audit.json").write_text(json.dumps(report, indent=2) + "\n")
    timeline = [f"{timestamp} {kind} [arguments omitted]" for timestamp, kind in starts]
    timeline.append(f"{boundary_us} verification start")
    timeline.sort()
    summary = [f"{key}: {value}" for key, value in report.items()]
    (args.output / "execve-sanitized.log").write_text("\n".join(summary + [""] + timeline) + "\n")
    if after:
        raise RuntimeError(f"{len(after)} post-startup exec calls")
    print("0 execve/execveat calls during the measured proof-verification interval.", flush=True)


if __name__ == "__main__":
    main()
