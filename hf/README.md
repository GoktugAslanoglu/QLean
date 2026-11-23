---
license: mit
library_name: transformers
pipeline_tag: text-generation
base_model: Qwen/Qwen3.5-4B
tags:
- lean4
- formal-verification
- qwenputer
---

# QLean-Qwen3.5-4B

QLean attaches a deterministic RV32IM Lean proof checker to the original Qwen3.5-4B checkpoint. Qwenputer’s P3 circuit runs the checker in compiled weights. The Python runtime frames proof bytes, schedules the two paths, and routes the guest verdict into Qwen’s text cache.

This repository distributes compiled overlays and runtime code. The loader obtains the original Qwen checkpoint at its pinned revision, then verifies its 738 tensor payloads against `tensor-sha256.json`. It loads the stock model at its original dtype and width. The stock checkpoint carries its Apache-2.0 license.

## Usage

```python
from transformers import AutoModel

model = AutoModel.from_pretrained("SkyAsl/QLean-Qwen3.5-4B", trust_remote_code=True)
result = model.prove("Submit only the bare Lean term fun P h => h.",
                     structured=True, thinking=False, temperature=0, max_attempts=1)
print(result["attempts"])
```

The loader executes the repository’s Python code and needs CUDA with BF16 and Triton support. The release uses PyTorch, Transformers 5.19.0, Accelerate and Safetensors. Use `model.prove` to run proof transport. The standard `forward` and `generate` methods delegate to stock Qwen. Choose a shipped goal-bound overlay with `overlay="..."`. Its manifest identifies the exact theorem accepted by the firmware. In bare-verdict mode (`structured=False`), Qwen must generate the proof frame itself and may stop or close it empty.

## Benchmarks and Verification

The guest accepts a strict Lean 4 subset. `benchmarks.json` records the L4 benchmark results, idle parity, and the original checkpoint shard digests.

The L4 run matched all 18 idle-logit comparisons and preserved every stock tensor. In the composition demo, Qwen repaired a real type error on the same text cache after the guest diagnostic and a generic `Try again.` chat turn. Lean 4.36.0 accepted the sampled proof with zero axiom dependencies. The bare-verdict trials did not produce a semantic repair across the three theorem candidates tested.

## Code & Reproducibility

Source code, C kernel, `strace` traces, and Colab reproduction scripts are available on GitHub: [GoktugAslanoglu/QLean](https://github.com/GoktugAslanoglu/QLean).

## Citation

```bibtex
@misc{aslanoglu2026qlean,
  author       = {Aslano{\u{g}}lu, G{\"o}ktu{\u{g}}},
  title        = {{QLean: Compiling a Lean 4 Proof Checker into Qwen3.5-4B's Weights}},
  year         = {2026},
  url = {[https://github.com/GoktugAslanoglu/QLean](https://github.com/GoktugAslanoglu/QLean)}
}
