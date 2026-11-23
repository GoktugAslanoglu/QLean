#!/usr/bin/env python3
"""Native fixtures and host/RV32 shared test inputs."""
import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent.parent
ROWS = 80
ROW_WIDTH = 16
INPUT_LIMIT = 79 * ROW_WIDTH - len(b"QLEAN1\n")
TRUSTED_HEADER = b"theorem qlean_target : 2 + 2 = 4 :="
VERDICT = re.compile(
    rb'QLEAN1 (OK|ERR_[A-Z_]+)(?: ([0-9]+|-))?(?: expected="([^"\n]+)" got="([^"\n]+)")?\n'
)
FIELD = re.compile(rb'(?:[\x20-\x21\x23-\x5b\x5d-\x7e]|\\x[0-9A-F]{2}){1,63}')


@dataclass(frozen=True)
class Case:
    name: str
    source: bytes
    expected: str
    rows: bytes | None = None
    diagnostic: tuple[bytes, bytes] | None = None


def frame(source: bytes, width: int = ROW_WIDTH) -> bytes:
    if not 1 <= width <= ROW_WIDTH:
        raise ValueError(width)
    wire = b"QLEAN1\n" + source
    if len(wire) > (ROWS - 1) * width or b"\0" in wire:
        raise ValueError("source does not fit in lossless rows")
    return b"".join(
        wire[i:i + width].ljust(ROW_WIDTH, b"\0")
        for i in range(0, len(wire), width)
    ).ljust(ROWS * ROW_WIDTH, b"\0")


def cases() -> list[Case]:
    result = [
        Case(path.stem, path.read_bytes(), "OK")
        for path in sorted((ROOT / "tests/valid").glob("*.lean"))
    ]
    folder = ROOT / "tests/invalid"
    expected_details = {
        "false_arithmetic.lean": (b"((2 + 2) = 5)", b"((2 + 2) = (2 + 2))"),
        "wrong_argument.lean": (b"P", b"Q"),
        "prop_as_goal.lean": (b"Prop", b"Type"),
    }
    for line in (folder / "expect.tsv").read_text().splitlines():
        if not line.startswith("#"):
            name, expected, _ = line.split("\t")
            result.append(Case(name, (folder / name).read_bytes(), expected,
                               diagnostic=expected_details.get(name)))

    base = b"theorem qlean_frame : 0 = 0 := rfl"
    proof_with_unicode = "theorem qlean_unicode : ∀ P : Prop, P → P := fun P h => h".encode()
    # The first UTF-8 code point starts in the last byte of this row.
    split_before = (len(b"QLEAN1\n") + proof_with_unicode.index(b"\xe2") + 1) % ROW_WIDTH
    if split_before != 0:
        first_line = proof_with_unicode.index(b":") + 1
        proof_with_unicode = (
            proof_with_unicode[:first_line]
            + b" " * (ROW_WIDTH - split_before)
            + proof_with_unicode[first_line:]
        )
    split_at = len(b"QLEAN1\n") + proof_with_unicode.index(b"\xe2")
    assert split_at % ROW_WIDTH == ROW_WIDTH - 1
    payload = frame(base)
    for row_index, row_value, name, expected in (
        (0, b"WRONG", "wrong_prefix", "ERR_TRANSPORT"),
        (0, b"\0x", "gap_before_data", "ERR_TRANSPORT"),
        (1, b"x\0x", "noncanonical_padding", "ERR_TRANSPORT"),
        (1, b"\xff", "invalid_token", "ERR_TRANSPORT"),
        (79, b"x", "overflow_row", "ERR_INPUT_TOO_LONG"),
    ):
        start = row_index * ROW_WIDTH
        rows = payload[:start] + row_value.ljust(ROW_WIDTH, b"\0") + payload[start + ROW_WIDTH:]
        result.append(Case(name, base, expected, rows))
    padding = b" " * (INPUT_LIMIT - len(base))
    full_source = base.replace(b":=", padding + b":=")
    large_term = b"1"
    for _ in range(4):
        large_term = b"(" + large_term + b" + " + large_term + b")"
    result.extend([
        Case("split_utf8", proof_with_unicode, "OK", frame(proof_with_unicode)),
        Case("malformed_frame_utf8", base, "ERR_TRANSPORT", frame(base + b"\xe2")),
        Case("exact_input_cap", full_source, "OK"),
        Case("over_input_cap", full_source + b"\n", "ERR_INPUT_TOO_LONG"),
        Case("nul_source", base + b"\0", "ERR_SYNTAX"),
        Case("bidi_source", base + "\u202e".encode(), "ERR_SYNTAX"),
        Case("truncated_utf8_tactic", b"theorem qlean_tail : 0 = 0 := by \xe2", "ERR_TACTIC"),
        Case("depth_exhaustion",
             b"theorem qlean_deep : " + b"(" * 40 + b"0 = 0" + b")" * 40 + b" := rfl",
             "ERR_OOM"),
        Case("arena_exhaustion",
             b"theorem qlean_oom : " + b"+".join([b"0"] * 520) + b"=0:=rfl",
             "ERR_OOM"),
        Case("whnf_exhaustion",
             b"theorem qlean_fuel : @Eq (0 = 0) (@Nat.rec (fun (k : Nat) => 0 = 0)"
             b" (Eq.refl 0) (fun k ih => ih) 500) (Eq.refl 0) := rfl",
             "ERR_FUEL"),
        Case("bounded_diagnostic", b"theorem qlean_long : " + large_term + b" = 17 := rfl",
             "ERR_TYPE_MISMATCH"),
        Case("repeat_success_after_failures", base, "OK"),
    ])
    return result


def check_output(case: Case, actual: bytes) -> None:
    parsed = VERDICT.fullmatch(actual)
    if parsed is None or parsed[1].decode() != case.expected:
        raise AssertionError(f"{case.name}: expected {case.expected}, got {actual!r}")
    if (parsed[1] == b"OK") != (parsed[2] is None):
        raise AssertionError(f"{case.name}: wrong offset field")
    if parsed[2] not in (None, b"-") and int(parsed[2]) > len(case.source):
        raise AssertionError(f"{case.name}: offset outside source")
    detail = parsed[3], parsed[4]
    if case.expected in ("ERR_TYPE_MISMATCH", "ERR_GOAL_MISMATCH"):
        if any(field is None or len(field) > 63 or not FIELD.fullmatch(field) for field in detail):
            raise AssertionError(f"{case.name}: malformed or missing mismatch detail {detail!r}")
    elif detail != (None, None):
        raise AssertionError(f"{case.name}: unexpected diagnostic {detail!r}")
    if case.diagnostic is not None and detail != case.diagnostic:
        raise AssertionError(f"{case.name}: expected {case.diagnostic!r}, got {detail!r}")
    if case.name == "bounded_diagnostic" and not all(field.endswith(b"...") for field in detail):
        raise AssertionError(f"{case.name}: long terms should report truncation")


def goal_cases() -> list[Case]:
    return [
        Case("target_proved", TRUSTED_HEADER + b" rfl", "OK"),
        Case("target_wrong_proof", TRUSTED_HEADER + b" Eq.refl 5", "ERR_TYPE_MISMATCH",
             diagnostic=(b"((2 + 2) = 4)", b"(5 = 5)")),
        Case("goal_substitution", b"theorem qlean_other : 0 = 0 := rfl", "ERR_GOAL_MISMATCH",
             diagnostic=(TRUSTED_HEADER, b"theorem qlean_other : 0 = 0 :=")),
        Case("escaped_header", "theorem qlean_a : ∀ P : Prop, P → P := fun P h => h".encode(),
             "ERR_GOAL_MISMATCH", diagnostic=(TRUSTED_HEADER,
                                              rb"theorem qlean_a : \xE2\x88\x80 P : Prop, P \xE2\x86\x92 P :=")),
        Case("late_header_difference", TRUSTED_HEADER.replace(b":=", b"+ 0 :=") + b" rfl",
             "ERR_GOAL_MISMATCH", diagnostic=(b"...: 2 + 2 = 4 :=", b"...: 2 + 2 = 4 + 0 :=")),
    ]


def native(host: Path, case: Case, header: bytes | None = None) -> bytes:
    argv = [str(host)]
    if case.rows is not None:
        argv.append("--rows")
    if header is not None:
        argv.extend(("--goal", header.decode()))
    run = subprocess.run(
        argv, input=case.source if case.rows is None else case.rows,
        capture_output=True, timeout=5,
    )
    check_output(case, run.stdout)
    if run.returncode != (0 if case.expected == "OK" else 1) or run.stderr:
        raise AssertionError(f"{case.name}: host exit {run.returncode}, stderr {run.stderr!r}")
    return run.stdout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("host", type=lambda s: Path(s).resolve())
    args = parser.parse_args()
    suite = cases()
    for case in suite:
        native(args.host, case)
    bound = goal_cases()
    for case in bound:
        native(args.host, case, TRUSTED_HEADER)
    print(f"Native: {sum(c.expected == 'OK' for c in suite)} accepted, "
          f"{sum(c.expected != 'OK' for c in suite)} rejected, {len(bound)} goal-binding checks")


if __name__ == "__main__":
    main()
