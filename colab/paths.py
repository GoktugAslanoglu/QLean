"""Ephemeral storage shared by the Colab and SSH Phase 3 entry points."""
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import sys

QWENPUTER = "0cab57038a8b218dabe481f994174c3437405e3d"
BASE_REPO = "Qwen/Qwen3.5-4B"
BASE_REV = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
ROOT = Path(os.environ.get("QLEAN_ROOT", "/tmp/qlean"))
VARIANT = os.environ.get("QLEAN_VARIANT", "")
if VARIANT and not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", VARIANT):
    raise ValueError("Invalid QLean artifact variant")
RUN = ROOT / "phase4" / "variants" / VARIANT if VARIANT else ROOT / "phase3"
BASE = ROOT / "models" / BASE_REV
UPSTREAM = ROOT / "phase3/upstream"
BUILD = RUN / "firmware"
CHIP = RUN / "chip"
TRACES = RUN / "traces"
DEFAULT_TARGET = "theorem qlean_target : ∀ P : Prop, P → P :="
TARGET = os.environ.get("QLEAN_TARGET", DEFAULT_TARGET)
if TARGET != DEFAULT_TARGET and not VARIANT:
    raise ValueError("Use a separate QLean artifact variant to set a different target")


def on_remote():
    if os.environ.get("SSH_CONNECTION") or os.environ.get("COLAB_RELEASE_TAG"):
        return True
    try:
        return importlib.util.find_spec("google.colab") is not None
    except ModuleNotFoundError:
        return False


def configure():
    if not on_remote():
        raise RuntimeError("Run Phase 3 in the Colab VM or an authorized SSH runtime")
    if ROOT not in (Path("/tmp/qlean"), Path("/content/qlean")):
        raise RuntimeError("QLean storage must be /tmp/qlean or /content/qlean on the VM")
    if ROOT.resolve() != ROOT or (ROOT.exists() and ROOT.stat().st_uid != os.getuid()):
        raise RuntimeError("The ephemeral QLean root must be owned by the remote user")
    ROOT.mkdir(mode=0o700, exist_ok=True)
    settings = {
        "HF_HOME": ROOT / "hf",
        "HF_HUB_CACHE": ROOT / "hf/hub",
        "HF_XET_CACHE": ROOT / "hf/xet",
        "XDG_CACHE_HOME": ROOT / "cache",
        "TRITON_CACHE_DIR": ROOT / "cache/triton",
        "CUDA_CACHE_PATH": ROOT / "cache/cuda",
        "TORCHINDUCTOR_CACHE_DIR": ROOT / "cache/torchinductor",
        "TORCH_HOME": ROOT / "cache/torch",
        "PIP_CACHE_DIR": ROOT / "cache/pip",
        "TMPDIR": ROOT / "tmp",
    }
    for key, path in settings.items():
        if not path.resolve().is_relative_to(ROOT.resolve()):
            raise RuntimeError(f"{key} leaves the ephemeral remote QLean directory")
        path.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(path)
    os.environ.update(HF_HUB_DISABLE_XET="1", PYTHONDONTWRITEBYTECODE="1",
                      GIT_LFS_SKIP_SMUDGE="1",
                      TOKENIZERS_PARALLELISM="false", HF_HUB_DISABLE_PROGRESS_BARS="1")
    for path in (BASE, RUN, BUILD, CHIP, TRACES, ROOT / "venv"):
        if not path.resolve().is_relative_to(ROOT.resolve()):
            raise RuntimeError(f"{path} leaves the ephemeral remote QLean directory")
        path.mkdir(parents=True, exist_ok=True)
    sys.dont_write_bytecode = True


def require_cuda():
    import torch

    if (not torch.cuda.is_available() or torch.cuda.get_device_capability()[0] < 8
            or not torch.cuda.is_bf16_supported(including_emulation=False)):
        raise RuntimeError("The pinned P3 executor requires an Ampere-class or newer GPU")
    from chipformer.rv.tritonexec import _apply_kernel
    x = torch.zeros(32, device="cuda")
    y = torch.ones_like(x)
    _apply_kernel[(1, 1)](x, y, x, 32, HIST=False, BLOCK=32)
    torch.cuda.synchronize()
    if not torch.equal(x, torch.ones_like(x)):
        raise RuntimeError("Triton probe failed")
    return torch.cuda.get_device_name()


def add_upstream():
    sys.path.insert(0, str(UPSTREAM / "experimental/riscv"))


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()
