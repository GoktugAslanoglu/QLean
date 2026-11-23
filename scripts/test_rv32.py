#!/usr/bin/env python3
"""Validate the P3 ELF and replay padded, lossless MMIO rows in its reference CPU."""
import argparse
from pathlib import Path
import struct
import sys

sys.dont_write_bytecode = True
from test_kernel import (
    Case, INPUT_LIMIT, ROW_WIDTH, TRUSTED_HEADER, cases, check_output, frame,
    goal_cases, native,
)

PIN = "0cab57038a8b218dabe481f994174c3437405e3d"
REGIONS = {
    0x40000: (5, 64 * 1024),
    0x20000: (4, 16 * 1024),
    0x00100: (6, 24 * 1024),
}
RECORD_LIMIT = 2_000_000


def layout(path: Path) -> dict[int, int]:
    binary = path.read_bytes()
    assert binary[:7] == b"\x7fELF\x01\x01\x01", "expected little-endian ELF32"
    e_type, machine, version, entry, phoff, _, flags, _, size, count = struct.unpack_from(
        "<HHIIIIIHHH", binary, 16
    )
    assert (e_type, machine, version, entry, flags, size) == (2, 243, 1, 0x40000, 0, 32)
    segments = {}
    for i in range(count):
        kind, off, start, paddr, file_size, mem_size, permissions, align = struct.unpack_from(
            "<8I", binary, phoff + i * size
        )
        if kind != 1:
            assert kind == 0x70000003, f"unexpected program header {kind:#x}"
            continue
        assert start in REGIONS and start not in segments and paddr == start
        expect_permissions, capacity = REGIONS[start]
        assert 0 <= file_size <= mem_size <= capacity and off + file_size <= len(binary)
        assert permissions == expect_permissions and (start - off) % align == 0
        segments[start] = mem_size
    assert set(segments) == set(REGIONS)
    assert 0x100 + segments[0x100] <= 0x7000
    assert segments[0x40000] % 4 == 0
    return segments


def replay(binary: Path, host: Path, inputs: list[Case], header: bytes | None) -> None:
    from chipformer.rv import bridge, elf, ref, spec

    segments = layout(binary)
    program = elf.program(binary)
    illegal = {"ILLEGAL", "EBREAK", "CSRRS"} | set(ref.CUSTOM) | {"SH1ADD", "SH2ADD", "SH3ADD"}
    assert all(ref.decode(word).op not in illegal for word in program.text)
    cpu = ref.Machine.from_program(program)
    bridge.park(cpu, max_records=100)
    peak_stack = 0
    total_steps = 0
    total_cases = 0
    for case in inputs:
        if case.rows is not None:
            rows = case.rows
        elif len(case.source) > INPUT_LIMIT:
            # The raw-source and captured-input APIs have different overflow locations.
            rows = frame(b"")[:-ROW_WIDTH] + b"x".ljust(ROW_WIDTH, b"\0")
        elif b"\0" in case.source or b"\xe2" == case.source[-1:]:
            # NUL and partial UTF-8 cannot reach the guest source parser losslessly.
            continue
        else:
            rows = frame(case.source)
        expected = native(host, case, header)
        if case.rows is None and len(case.source) > INPUT_LIMIT:
            expected = native(host, Case(case.name, case.source, case.expected, rows), header)
        cpu.text = [bytes(ROW_WIDTH)] + [
            rows[i:i + ROW_WIDTH] for i in range(0, len(rows), ROW_WIDTH)
        ]
        cpu.halted = False
        cpu.out.clear()
        start_steps = cpu.steps
        echoes = []
        for _ in range(RECORD_LIMIT):
            record = cpu.record()
            for token in record:
                family, value = spec.family(token)
                if family == "BYTE":
                    echoes.append(value)
            assert 0x7000 <= cpu.x[2] <= 0x8000, (case.name, hex(cpu.x[2]))
            peak_stack = max(peak_stack, 0x8000 - cpu.x[2])
            if cpu.halted:
                break
        assert cpu.halted and cpu.fault is None, (case.name, cpu.fault, cpu.steps - start_steps)
        assert len(echoes) >= 2 and echoes[0] == 256 and echoes[-1] == 257, (case.name, echoes)
        actual = bytes(echoes[1:-1])
        check_output(case, actual)
        assert actual == expected, (case.name, expected, actual)
        assert (cpu.exit_code == 0) == (case.expected == "OK"), (case.name, cpu.exit_code)
        total_steps += cpu.steps - start_steps
        total_cases += 1

    print(f"Official P3 reference: {total_cases} matching verdicts including repeat calls, "
          f"{total_steps:,} RV32 instructions")
    print(f"ELF: {segments[0x40000]:,} B code, {segments[0x20000]:,} B DROM, "
          f"{segments[0x100]:,} B static RAM, {peak_stack:,} B peak observed stack")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("elf", type=Path)
    parser.add_argument("host", type=lambda s: Path(s).resolve())
    parser.add_argument("qwenputer_riscv", type=lambda s: Path(s).resolve(),
                        help=f"experimental/riscv from Qwenputer {PIN}")
    parser.add_argument("--goal-elf", type=Path, help="ELF with TRUSTED_HEADER in DROM")
    args = parser.parse_args()
    sys.path.insert(0, str(args.qwenputer_riscv))

    replay(args.elf, args.host, cases(), None)
    if args.goal_elf:
        inputs = goal_cases()
        replay(args.goal_elf, args.host, inputs + inputs[:1], TRUSTED_HEADER)


if __name__ == "__main__":
    main()
