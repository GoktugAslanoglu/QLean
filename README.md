# QLean

**100% training-free. Zero modified learned weights. Bit-exact idle logits. Zero external verifier tools at proof time.**
![QLean Demo](demos/hero.gif)
QLean adds a compiled RV32IM proof checker to stock Qwen3.5-4B using Qwenputer’s P3 circuit. Guest firmware in the compiled weights parses and checks the submitted Lean 4 source and emits the verdict. A thin Python transport samples and routes tokens, attaches the guest-side theorem header, and displays results. The verdict flows into the same Qwen text cache.

Qwen retains its original 2,560-wide residual stream. The chip has its own deterministic coefficients and firmware state. Both stock checkpoint shards, covering **738 tensors**, retained their SHA-256 digests through compilation and verification. All 723 loaded parameter fingerprints matched. All 18 idle logit comparisons and greedy token checks matched stock Qwen. [Verification & Weight Isolation](reports/verification-and-weight-isolation.md)

## Reproduce on Colab

From this checkout, run the demos on an existing, CLI-visible Colab GPU session.

```bash
scripts/run_colab_demo.sh YOUR_EXISTING_SESSION
```

The command uploads source, builds the small goal-bound RV32IM ELF, and compiles its additive chip overlay. A fresh runtime downloads the pinned stock Qwen3.5-4B checkpoint. A warm runtime reuses the checkpoint, upstream source, and existing overlays. All artifacts stay on the VM under `/tmp/qlean` by default. Goal-specific overlays are `phase4/variants/<goal>/chip/circuit.safetensors` alongside their manifests. The launcher leaves the session allocated after the run.

Run the interactive CLI from the uploaded source checkout on that VM.

```bash
/tmp/qlean/venv/bin/python qlean.py --max-attempts 3 \
  --transcript /tmp/qlean/identity.json \
  'Prove the bound identity theorem with a Lean term proof.'
```

Add `--thinking` to stream Qwen’s reasoning and `--json` for machine-readable stdout. In `--no-structured` mode Qwen emits its own proof frames. The guest gets the fixed declaration, and Qwen gets only the authenticated verdict bytes through the verdict newline. The guest response delimiters and HALT echo stay on the P3 path. Decoding resumes immediately in the same cache with zero injected retry text or chat roles. The default structured mode adds the generic `Try again.` header and chat roles on rejection. Transcripts record both the full guest echo and the exact bytes delivered to Qwen. [Pinned Qwen chat template](https://huggingface.co/Qwen/Qwen3.5-4B/blob/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a/chat_template.jinja)

## Benchmarks

Measured on an NVIDIA L4 with stock Qwen3.5-4B, PyTorch 2.14.1+cu130, and Triton 3.8.0. The timer includes proof submission, chip execution, and verdict echoes.

| Case | Guest verdict | Trace tokens | Wall time | Peak allocated VRAM |
| --- | --- | ---: | ---: | ---: |
| Valid proof | `QLEAN1 OK` | 41,842 | 11.467 s | 9.090 GiB |
| Ill-typed proof | `QLEAN1 ERR_TYPE_MISMATCH 59` with `expected` and `got` | 46,001 | 17.600 s | 9.094 GiB |
| Valid proof of a different theorem | `QLEAN1 ERR_GOAL_MISMATCH 34` with `expected` and `got` | 24,108 | 15.677 s | 9.096 GiB |

Across the nine diagnostic-firmware cases, peak VRAM was 9.136 GiB allocated and 9.258 GiB reserved. Peak guest RAM was 18,580 bytes (18.1 KiB). Natural BPE and byte-token splits of `∀` and `→` produced identical guest input bytes. Two fresh, identical type-mismatch runs produced identical complete trace hashes. [Full benchmark results](demos/captures/phase3-results.json)

## Demos

The following L4 excerpts omit frame delimiters and elide most of Qwen’s reasoning. Full captures include the prompts, generated token IDs, transport events, and exact guest input.

### Semantic proof repair

On implication composition, Qwen omitted the three proposition binders and applied a proposition as a function. The guest emitted `ERR_TYPE_MISMATCH 107 expected="function type" got="Prop"`. Qwen then generated a correctly scoped composition term in the same text cache. The run uses seed `19`, temperature `0.9`, and thinking disabled. Official Lean 4.36.0 compiled the exact accepted source with zero axiom dependencies. [Full capture](demos/captures/self-correction.json) · [Accepted proof](demos/captures/accepted-proof.lean) · [Lean validation](demos/captures/lean-validation.json)

The bare-verdict trials covered a `Nat` goal, projection, and composition. None produced a semantic repair. The recorded run used the generic `Try again.` prompt and chat role delimiters after the guest verdict. Qwen generated both proof bodies without a theorem-specific hint. [Trial log](demos/captures/repair-search.json)

```text
theorem qlean_target : ∀ P Q R : Prop, (P → Q) → (Q → R) → P → R := fun hPQ hQR hP => hQR (hQR hP)
[In-Weights Kernel | 82,492 trace tokens | 25.3s | 18.3 KiB RAM | QLEAN1 ERR_TYPE_MISMATCH 107]
  expected="function type"
  got="Prop"

Retry header: Try again.

theorem qlean_target : ∀ P Q R : Prop, (P → Q) → (Q → R) → P → R := fun P Q R hPQ hQR hP => hQR (hPQ hP)
[In-Weights Kernel | 103,364 trace tokens | 26.9s | 18.6 KiB RAM | QLEAN1 OK]
```

Replay the saved capture with Python 3, or render `demos/hero.gif` with VHS from the checkout root. Both run locally from the recorded proofs and verdicts. The replay compresses the pauses to 4× speed and displays the original timings. VHS requires `ttyd` and `ffmpeg` on `PATH`. [VHS installation](https://github.com/charmbracelet/vhs#installation)

```bash
python3 scripts/replay_demo.py
vhs demos/demo.tape
```

### Rejecting a false theorem

The prompt pressures Qwen to certify `2 + 2 = 5` by reflexivity. Qwen submitted `by rfl` three times for this repeated-input fixture. The goal-bound guest rejected all three with the same type diagnostic. [Full capture](demos/captures/hallucination-wall.json)

```text
theorem qlean_target : 2 + 2 = 5 := by rfl
QLEAN1 ERR_TYPE_MISMATCH 39 expected="((2 + 2) = 5)" got="((2 + 2) = (2 + 2))"
Rejected 3/3 submitted attempts.
```

The three attempts used 45,608, 45,609, and 45,609 trace tokens.

### Proof verification without subprocesses

`strace -f` followed child processes and counted `execve` and `execveat` calls from the end of warm-up and prompt prefill through process exit. Qwen submitted the requested identity term and the proof passed with zero calls during that interval. JSON stdout matched the saved transcript. [Full capture](demos/captures/zero-subprocess.json) · [Sanitized trace](demos/captures/execve-sanitized.log)

```text
theorem qlean_target : ∀ P : Prop, P → P := fun P h => h
[In-Weights Kernel | 42,162 trace tokens | 11.6s | 18.1 KiB RAM | QLEAN1 OK]
0 execve/execveat calls during the measured proof-verification interval.
```

## Current Limits

- The RV32IM guest has **32 KiB of writable RAM**. The checked build budgets 28 KiB of working RAM, including a 4 KiB stack. The token bridge allows 79 capture rows and up to 1,257 source bytes.
- The valid proof reached about **3.6k trace tokens/s**. The three benchmark cases ranged from about 1.5k to 3.6k trace tokens/s, including submission and verdict echoes into Qwen.
- The checker accepts a strict subset of **Lean 4.36.0** with dependent functions, propositions, natural numbers, equality transport, and a few explicit proof forms. It has a fixed builtin environment. Mathlib, arbitrary imports, and general Lean elaboration and tactics are outside that environment.
- The guest checks the exact proof submitted against the theorem header bound into its firmware. The stock model can still emit malformed frames, unsupported Lean syntax, or bad proofs, so generation is bounded by a token and attempt budget.
- In a `Nat` retry with a local equality hypothesis, Qwen repeated an unsupported rewrite tactic. Type and goal mismatches include `expected="…" got="…"` fields capped at 63 escaped ASCII bytes each. The composition capture illustrates one semantic repair with generic retry framing. Repair without that framing remains unverified.
- Qwenputer supplies the circuit architecture. Lean and `strace` are development and demo validation tools. The live proof checker uses the compiled guest. [Qwenputer source](https://github.com/divagr18/qwenputer/tree/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv) [Stock Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B/tree/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a)

## Hugging Face package

The `hf/` scaffold prepares an overlay-only release for `SkyAsl/QLean-Qwen3.5-4B`. Its Transformers loader verifies the 738 original tensor payloads and downloads the pinned stock checkpoint from Qwen. `model.prove` runs the proof transport. The package stages on the runtime under `/tmp/qlean/hf-release`. [Model card](hf/README.md)

## License

QLean source and documentation use the MIT License. The license file includes the Qwenputer copyright notice for adapted portions. The Qwen checkpoint is Apache-2.0. [QLean license](LICENSE) · [Qwenputer license](https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/LICENSE) · [Qwen model card](https://huggingface.co/Qwen/Qwen3.5-4B/blob/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a/README.md)

## Citation

If you use QLean in your research or build on this work, please cite:

```bibtex
@misc{aslanoglu2026qlean,
  author       = {Aslano{\u{g}}lu, G{\"o}ktu{\u{g}}},
  title        = {{QLean: Compiling a Lean 4 Proof Checker into Qwen3.5-4B's Weights}},
  year         = {2026},
  month        = {11},
  howpublished = {\url{https://github.com/GoktugAslanoglu/QLean}}
}
