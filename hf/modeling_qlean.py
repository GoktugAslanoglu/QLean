"""Transformers entry point for an additive QLean overlay on pinned stock Qwen."""
from hashlib import sha256
from importlib import import_module, util
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

from huggingface_hub import snapshot_download
import torch
from transformers import AutoTokenizer, PreTrainedModel, Qwen3_5ForConditionalGeneration

from .configuration_qlean import QLeanConfig
from .immutability import tensor_hashes


def packaged_runtime(root):
    directory = root / "runtime"
    name = "_qlean_runtime_" + sha256(str(directory.resolve()).encode()).hexdigest()[:16]
    if name not in sys.modules:
        spec = util.spec_from_file_location(name, directory / "__init__.py",
                                            submodule_search_locations=[str(directory)])
        module = util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return import_module(name + ".qlean_runner")


class QLeanModel(PreTrainedModel):
    config_class = QLeanConfig
    base_model_prefix = "stock"

    def __init__(self, config, stock, tokenizer, chip, manifest, capture, runner):
        super().__init__(config)
        self.stock = stock
        self.runner = runner
        self.tokenizer = tokenizer
        self._proof_runtime = torch, stock, tokenizer, chip, manifest, capture

    @classmethod
    def from_pretrained(cls, pretrained_model_name_or_path, *args, config=None, **kwargs):
        hub = {key: kwargs.pop(key) for key in ("revision", "token", "cache_dir", "local_files_only")
               if key in kwargs}
        config = config or QLeanConfig.from_pretrained(pretrained_model_name_or_path, **hub)
        overlay = kwargs.pop("overlay", config.overlay)
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", overlay):
            raise ValueError("Invalid overlay name")
        if args or not torch.cuda.is_available() or torch.cuda.get_device_capability()[0] < 8:
            raise RuntimeError("QLean requires an Ampere-class or newer CUDA GPU")

        root = Path(pretrained_model_name_or_path)
        if not root.is_dir():
            root = Path(snapshot_download(str(root), allow_patterns=["runtime/*", "vendor/*",
                        f"overlays/{overlay}/*", "tensor-sha256.json"], **hub))
        # The result of AutoConfig resolves the remote code revision independently.
        base_options = {key: value for key, value in hub.items() if key != "revision"}
        base_override = kwargs.pop("base_path", None)
        base = Path(base_override or snapshot_download(config.base_model,
                    revision=config.base_revision, allow_patterns=["*.json", "*.jinja", "*.safetensors"],
                    **base_options))
        identity = json.loads((root / "tensor-sha256.json").read_text())
        if (identity["base_model"], identity["base_revision"]) != (config.base_model, config.base_revision):
            raise RuntimeError("Stock checkpoint identity pin mismatch")
        if tensor_hashes(base.glob("*.safetensors")) != identity["tensors"]:
            raise RuntimeError("Stock tensor fingerprints disagree")

        vendored = str(root / "vendor")
        if vendored not in sys.path:
            sys.path.insert(0, vendored)
        runner = packaged_runtime(root)
        directory = root / "overlays" / overlay
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        stock = Qwen3_5ForConditionalGeneration.from_pretrained(
            base, dtype="auto", device_map={"": "cuda"}, local_files_only=True,
            attn_implementation="eager",
        ).eval()
        tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True)
        chip, manifest, capture = runner.load_overlay(base, directory, directory / "capture.json")
        return cls(config, stock, tokenizer, chip, manifest, capture, runner).eval()

    def forward(self, *args, **kwargs):
        return self.stock(*args, **kwargs)

    def generate(self, *args, **kwargs):
        return self.stock.generate(*args, **kwargs)

    def prove(self, prompt, *, max_tokens=680, max_attempts=2, structured=False,
              thinking=True, temperature=0.55, seed=0):
        args = SimpleNamespace(prompt=prompt, max_tokens=max_tokens, max_attempts=max_attempts,
                               structured=structured, thinking=thinking, temperature=temperature,
                               seed=seed, started_marker=None)
        transcript = {"attempts": [], "generated_ids": [], "protocol_events": []}
        self.runner.generate(args, self.runner.Display(quiet=True), transcript, self._proof_runtime)
        return transcript
