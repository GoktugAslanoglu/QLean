"""Assemble the upload folder from verified artifacts on the GPU host."""
import json
from pathlib import Path
import shutil
import sys
import tempfile

from immutability import tensor_hashes

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "colab"))
from paths import BASE, BASE_REPO, BASE_REV, ROOT, UPSTREAM, configure, digest


def copy_overlay(folder, run, expected):
    chip = run / "chip"
    manifest = json.loads((chip / "manifest.json").read_text())
    artifact = chip / "circuit.safetensors"
    capture = run / "firmware/capture.json"
    if (manifest["artifact_sha256"] != expected or digest(artifact) != expected
            or json.loads(capture.read_text())["firmware_sha256"] != manifest["firmware_sha256"]):
        raise RuntimeError("Release overlay provenance mismatch")
    folder.mkdir(parents=True)
    for path in (artifact, chip / "manifest.json", capture):
        shutil.copyfile(path, folder / path.name)
    if digest(folder / artifact.name) != expected:
        raise RuntimeError("Staged overlay digest mismatch")


def stage():
    configure()
    output = ROOT / "hf-release"
    phase3 = ROOT / "phase3"
    benchmark = phase3 / "traces/phase3-results.json"
    results = json.loads(benchmark.read_text())
    shards = sorted(BASE.glob("*.safetensors"))
    if ({p.name: digest(p) for p in shards} != results["checkpoint_shard_sha256"]
            or results["modified_learned_tensors"] != 0 or results["checkpoint_tensor_count"] != 738):
        raise RuntimeError("Stock checkpoint failed release identity gate")
    cases = {case["test"]: case for case in results["runs"]}
    if any(' expected="' not in cases[name]["verdict"] for name in ("invalid_proof", "wrong_theorem")):
        raise RuntimeError("Release requires the diagnostic firmware")

    with tempfile.TemporaryDirectory(prefix="hf-staging.", dir=ROOT) as scratch:
        folder = Path(scratch) / "release"
        folder.mkdir()
        for name in ("README.md", "config.json", "configuration_qlean.py", "modeling_qlean.py", "immutability.py"):
            shutil.copyfile(SOURCE / "hf" / name, folder / name)
        shutil.copyfile(SOURCE / "LICENSE", folder / "LICENSE")
        shutil.copyfile(benchmark, folder / "benchmarks.json")
        runtime = folder / "runtime"
        runtime.mkdir()
        (runtime / "__init__.py").touch()
        runner = (SOURCE / "qlean.py").read_text()
        for name in ("paths", "composition", "owned"):
            runner = runner.replace(f"from {name} import", f"from .{name} import")
            shutil.copyfile(SOURCE / "colab" / f"{name}.py", runtime / f"{name}.py")
        (runtime / "qlean_runner.py").write_text(runner)
        vendor = folder / "vendor"
        shutil.copytree(UPSTREAM / "experimental/riscv/chipformer", vendor / "chipformer",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copyfile(UPSTREAM / "LICENSE", vendor / "LICENSE")

        tensors = tensor_hashes(shards)
        if len(tensors) != 738:
            raise RuntimeError("Expected exactly 738 stock tensor hashes")
        identity = {"base_model": BASE_REPO, "base_revision": BASE_REV,
                    "shards": results["checkpoint_shard_sha256"], "tensors": tensors}
        (folder / "tensor-sha256.json").write_text(json.dumps(identity, sort_keys=True, indent=2) + "\n")
        copy_overlay(folder / "overlays/identity", phase3, results["artifact_sha256"])
        captures = ROOT / "phase4/captures"
        for filename, name in (("self-correction.json", None), ("hallucination-wall.json", "false-arithmetic")):
            path = captures / filename
            if not path.exists():
                continue
            data = json.loads(path.read_text())
            name = name or data["variant"]
            copy_overlay(folder / "overlays" / name, ROOT / "phase4/variants" / name, data["artifact_sha256"])
        if output.exists():
            shutil.rmtree(output)
        folder.rename(output)
    print(f"Staged {len(tensors)} per-tensor hashes and compiled overlays at {output}", flush=True)


if __name__ == "__main__":
    stage()
