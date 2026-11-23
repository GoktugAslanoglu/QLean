#!/usr/bin/env python3
"""Replay QLean Demo 1 from the saved capture."""
import argparse
import json
from pathlib import Path
import sys
import time


CAPTURE = Path(__file__).resolve().parents[1] / "demos/captures/self-correction.json"
PLAYBACK_SPEED = 4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instant", action="store_true", help="Replay without pauses")
    args = parser.parse_args()

    capture = json.loads(CAPTURE.read_text(encoding="utf-8"))
    retries = {
        event["after_sampled_tokens"]: event["text"].partition("<|im_end|>")[0].strip()
        for event in capture["protocol_events"]
        if event["reason"] == "generic retry header"
    }
    progress = sys.stdout.isatty() and not args.instant
    speed = "" if args.instant else f" ({PLAYBACK_SPEED}× speed)"
    print(f"QLean Demo 1 | Recorded replay{speed}", flush=True)

    attempts = capture["attempts"]
    for index, attempt in enumerate(attempts, 1):
        print("\n" + attempt["source"].rstrip("\n"), flush=True)
        if progress:
            print("[In-Weights Kernel | Checking…]", end="", flush=True)
        if not args.instant:
            time.sleep(attempt["wall_seconds"] / PLAYBACK_SPEED)
        if progress:
            print("\r\x1b[2K", end="")
        verdict, separator, diagnostic = attempt["verdict"].partition(" expected=")
        print(
            f"[In-Weights Kernel | {attempt['chip_trace_tokens']:,} trace tokens | "
            f"{attempt['wall_seconds']:.1f}s | {attempt['guest_peak_ram_bytes'] / 1024:.1f} KiB RAM | "
            f"{verdict}]",
            flush=True,
        )
        if separator:
            expected, got = diagnostic.split('" got="', 1)
            print(f'  expected={expected}"\n  got="{got}', flush=True)
        retry = retries.get(attempt["model_tokens"])
        if not args.instant and index < len(attempts):
            time.sleep(0.75)
        if retry:
            print(f"\nRetry header: {retry}", flush=True)
            if not args.instant:
                time.sleep(0.75)


if __name__ == "__main__":
    main()
