"""Set up the remote runtime and fetch immutable inputs to ephemeral storage."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

from paths import (BASE, BASE_REPO, BASE_REV, BUILD, QWENPUTER, TARGET, UPSTREAM,
                   add_upstream, configure, digest, require_cuda)

SOURCE = Path(__file__).resolve().parent.parent


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--prepare-only", action="store_true",
                       help="Prepare artifacts in this VM without running CUDA")
    modes.add_argument("--runtime-only", action="store_true",
                       help="Set up a GPU runtime for existing ephemeral artifacts")
    modes.add_argument("--firmware-only", action="store_true",
                       help="Rebuild just the goal-bound ELF and its symbol map")
    args = parser.parse_args()
    configure()
    if args.runtime_only and not (UPSTREAM / ".git").exists():
        raise RuntimeError(f"The pinned upstream checkout is missing from {UPSTREAM}")
    if not (UPSTREAM / ".git").exists():
        run("git", "init", "-q", str(UPSTREAM))
    current = subprocess.run(("git", "-C", str(UPSTREAM), "rev-parse", "HEAD"),
                             capture_output=True, text=True)
    if current.stdout.strip() != QWENPUTER:
        if args.runtime_only:
            raise RuntimeError("The ephemeral checkout must match the upstream revision pin")
        run("git", "-C", str(UPSTREAM), "fetch", "--depth=1",
            "https://github.com/divagr18/qwenputer.git", QWENPUTER)
        run("git", "-C", str(UPSTREAM), "checkout", "--detach", "FETCH_HEAD")
    add_upstream()
    device = None
    if not args.firmware_only:
        run(sys.executable, "-m", "pip", "install", "-q", "transformers==5.19.0", "accelerate",
            "safetensors")
        if importlib.util.find_spec("triton") is None:
            run(sys.executable, "-m", "pip", "install", "-q", "triton==3.8.0")
        device = "CPU preflight" if args.prepare_only else require_cuda()
    if args.runtime_only:
        print(f"QLean Triton preflight complete on {device}.", flush=True)
        return
    clang = shutil.which("clang")
    linker = next((path for tool in ("riscv64-linux-gnu-ld", "riscv64-elf-ld",
                                    "riscv64-unknown-elf-ld", "ld.lld")
                   if (path := shutil.which(tool))), None)
    if not clang or not linker:
        raise RuntimeError("Clang and an ELF32-capable RISC-V linker are required")
    goal = BUILD / "goal.inc"
    goal.write_text(json.dumps(TARGET, ensure_ascii=False) + "\n", encoding="utf-8")
    run("make", "-B", "-C", str(SOURCE / "kernel"), "rv32", f"BUILD={BUILD}",
        f"RV_CC={clang}", f"RV_LD={linker}",
        f"RV_EXTRA=-DQLEAN_CAPTURE_TELEMETRY -DQLEAN_GOAL_FILE='\"{goal}\"'")
    run(sys.executable, str(SOURCE / "scripts/check_stack.py"), str(BUILD))
    elf = BUILD / "qlean.elf"
    symbols = run("llvm-nm", "-S", str(elf), capture_output=True, text=True)
    locations = {}
    for line in symbols.stdout.splitlines():
        fields = line.split()
        if fields[-1:] in (["source"], ["source_length"]):
            locations[fields[-1]] = [int(value, 16) for value in fields[:2]]
    address, size = locations["source"]
    length_address, length_size = locations["source_length"]
    if length_size != 2:
        raise RuntimeError("Unexpected guest capture length type")
    (BUILD / "capture.json").write_text(json.dumps(
        {"source_address": address, "source_length_address": length_address,
         "capacity": size, "firmware_sha256": digest(elf)}
    ))
    if args.firmware_only:
        return

    from huggingface_hub import snapshot_download

    path = snapshot_download(repo_id=BASE_REPO, revision=BASE_REV, local_dir=BASE,
                             allow_patterns=["*.json", "*.safetensors", "*.txt", "*.jinja"],
                             max_workers=3)
    if Path(path).resolve() != BASE.resolve() or not list(BASE.glob("*.safetensors")):
        raise RuntimeError(f"Pinned snapshot missing from {BASE}")
    print(f"QLean setup complete on {device}. Checkpoint at {BASE}, ELF at {elf}.", flush=True)


if __name__ == "__main__":
    main()
