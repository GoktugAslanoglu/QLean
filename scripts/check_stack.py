#!/usr/bin/env python3
"""Conservative stack bound for the audited RV32 linker and Clang build."""
import argparse
from functools import cache
from pathlib import Path
import re
import struct

GUARDED = frozenset({"expr", "elaborate", "tactic", "infer", "whnf", "rewrite", "convert"})
# expr obtains its lookahead before enter. Include that path at rejected depth.
BEFORE_ENTER = {"expr": frozenset({"peek"})}
def stack_frames(build: Path) -> dict[str, int]:
    frames = {"_start": 0}
    for path in sorted(build.glob("*/*.su")):
        for line in path.read_text().splitlines():
            label, size, kind = line.split("\t")
            name = label.rsplit(":", 1)[-1]
            if kind != "static" or name in frames:
                raise ValueError(f"invalid stack usage for {name}: {line}")
            frames[name] = int(size)
    return frames


def rv32_functions(path: Path) -> dict[int, tuple[str, tuple[int, ...]]]:
    """Read sized function symbols and code from the linked ELF32 image."""
    data = path.read_bytes()
    if data[:7] != b"\x7fELF\x01\x01\x01" or struct.unpack_from("<H", data, 18)[0] != 243:
        raise ValueError("Expected a little-endian ELF32 RISC-V image")
    if struct.unpack_from("<I", data, 36)[0] != 0:
        raise ValueError("Stack audit requires the uncompressed RV32IM ABI")
    offset = struct.unpack_from("<I", data, 32)[0]
    size, count = struct.unpack_from("<HH", data, 46)
    sections = [struct.unpack_from("<10I", data, offset + i * size) for i in range(count)]
    functions = {}
    for section in sections:
        if section[1] != 2:  # SHT_SYMTAB
            continue
        names = sections[section[6]]
        strings = data[names[4]:names[4] + names[5]]
        for at in range(section[4], section[4] + section[5], section[9]):
            index, addr, length, flags, _, code = struct.unpack_from("<IIIBBH", data, at)
            if flags & 15 != 2 or not length or not 0 < code < len(sections):
                continue
            executable = sections[code]
            if not executable[2] & 4:
                continue
            name = strings[index:strings.index(b"\0", index)].decode()
            off = executable[4] + addr - executable[3]
            if addr % 4 or length % 4 or addr in functions:
                raise ValueError(f"Unexpected function layout for {name}")
            words = struct.unpack_from(f"<{length // 4}I", data, off)
            functions[addr] = (name, words)
    if not functions:
        raise ValueError("No sized executable function symbols found")
    return functions


def sign(value: int, bits: int) -> int:
    msb = 1 << (bits - 1)
    return (value ^ msb) - msb


def call_graph(binary: Path, frames: dict[str, int]) -> dict[str, set[str]]:
    # Decode transfers from the bytes. Older llvm-objdump omits call-target
    # annotations for linked AUIPC/JALR pairs.
    functions = rv32_functions(binary)
    graph = {name: set() for name in frames}
    for addr, (name, words) in functions.items():
        if name not in graph:
            raise ValueError(f"no stack record for {name}")
        for i, word in enumerate(words):
            pc = addr + 4 * i
            op, rd, rs = word & 127, (word >> 7) & 31, (word >> 15) & 31
            if op == 0x6F:  # JAL, including j
                imm = ((word >> 31) << 20) | ((word >> 21) & 0x3FF) << 1
                imm |= ((word >> 20) & 1) << 11 | (word & 0xFF000)
                target = pc + sign(imm, 21)
            elif op == 0x67:  # JALR, including ret and tail calls
                imm = sign(word >> 20, 12)
                if rd == 0 and rs == 1 and imm == 0:
                    continue
                previous = words[i - 1] if i else 0
                if previous & 127 != 0x17 or (previous >> 7) & 31 != rs:
                    raise ValueError(f"Unresolved JALR in {name} at {pc:#x}")
                target = ((pc - 4 + sign(previous & 0xFFFFF000, 32) + imm) & 0xFFFFFFFF) & ~1
            elif op == 0x63:  # conditional branch
                imm = ((word >> 31) << 12) | ((word >> 7) & 1) << 11
                imm |= ((word >> 25) & 63) << 5 | ((word >> 8) & 15) << 1
                target, rd = pc + sign(imm, 13), 0
            else:
                continue
            if rd == 0 and addr <= target < addr + 4 * len(words):
                continue
            if target not in functions:
                raise ValueError(f"Unresolved transfer in {name}: {pc:#x} to {target:#x}")
            graph[name].add(functions[target][0])
    return graph


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", type=Path)
    args = parser.parse_args()
    cap_source = Path(__file__).resolve().parent.parent / "kernel/src/internal.h"
    depth_cap = int(re.search(r"\bQL_DEPTH\s*=\s*(\d+)", cap_source.read_text())[1])
    frames = stack_frames(args.build)
    graph = call_graph(args.build / "qlean.elf", frames)
    if any("enter" not in graph[f] for f in GUARDED):
        raise ValueError("guarded function is missing the expected entry guard")
    if frames["enter"] or any(frames[k] != 0 for k in graph["enter"]):
        raise ValueError("audit stack use of entry-guard path before proceeding")

    @cache
    def maximum(name: str, depth: int) -> int:
        next_depth = depth + (name in GUARDED)
        children = graph[name] if next_depth <= depth_cap else BEFORE_ENTER.get(name, ())
        # Charge the prologue even if enter refuses the operation. Also keep a
        # caller's frame when the compiler happened to emit a tail call.
        return frames[name] + max((maximum(child, next_depth) for child in children), default=0)

    upper = maximum("_start", 0)
    if upper > 4096:
        raise ValueError(f"conservative stack bound {upper} exceeds 4096-byte partition")
    print(f"Linked RV32 stack bound: {upper:,} / 4,096 B (depth cap {depth_cap})")


if __name__ == "__main__":
    main()
