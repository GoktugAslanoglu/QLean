# QLean Phase 3 composition and validation

The source implements an additive P3 compilation path and one decode stream with two isolated residual streams. The original Qwen3.5-4B checkpoint remains the reference for every normal text forward pass. The chip's sparse SwiGLU and Gated DeltaNet coefficients, token features, and immutable firmware boot tensors form a separate artifact. The executor loads that artifact before a proof run. A reference CPU supplies the first-park state during compilation. The live decoder routes token IDs and reads circuit-owned output. [Pinned model configuration](https://huggingface.co/Qwen/Qwen3.5-4B/blob/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a/config.json) [P3 Triton executor](https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/chipformer/rv/tritonexec.py)

## RMSNorm and residual isolation

Qwen's gain is `1 + w`, where `w` is the stored learned parameter. RMSNorm divides the sum of squares by the current hidden width. Stock `merge.py` widens the original residual from `d0` to `hidden`. Even zero-padding changes that denominator. Its width compensation reconstructs the effective gain, scales it by `sqrt(d0 / hidden)`, and stores the result minus one. This runs even with `--no-mute`. Epsilon, extra active dimensions, and rounding also matter to exact parity. [Qwen RMSNorm](https://github.com/huggingface/transformers/blob/v5.19.0/src/transformers/models/qwen3_5/modeling_qwen3_5.py#L751-L765) [Pinned stock merge](https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/chipformer/rv/merge.py#L125-L160)

QLean keeps the base at its original width of 2,560. The dispatcher sends shared text tokens to the original Qwen forward pass and to the compiled chip. Only the chip advances on internal RV32 tokens. A machine-owned verdict echo enters the same Qwen cache as ordinary text. The chip's numeric activations stay out of Qwen's embedding, residual, and normalization path. The identity gate checks SHA-256 for every original checkpoint shard around compilation and runtime, plus a SHA-256 per loaded parameter around the GPU tests. Idle parity compares the full stock and composed logits with `torch.equal` and checks greedy IDs on two prompts using separate caches. [Original model config](https://huggingface.co/Qwen/Qwen3.5-4B/blob/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a/config.json)

## Capture and proof evidence

- The compiler emits exact BPE fragment bytes, with a sentinel for fragments that cannot fit a row. The firmware checks row 80 for overflow. The controlled circuit overlay marks nested openings in that row and requires an opening before it can own a closing delimiter. Historical prompt tokens enter Qwen through a separate prefill method.
- The verification suite compares the committed guest input buffer **and its actual stored length** to the submitted source. Cases include ordinary pinned BPE and byte-token splits within both `∀` and `→`, with LF and two-space tactic indentation. It also exercises oversized tokens, overflow, nested opens, and a closing delimiter without an opener.
- The test uses controlled candidate tokens, including a valid proof, an invalid proof using a proposition where a proof is required, and a valid proof of a different theorem. It requires an exact circuit-owned `OK`, `ERR_TYPE_MISMATCH`, and `ERR_GOAL_MISMATCH` respectively, complete guest echoes, and normal HALT. A repeated invalid proof from identical boot state must emit identical stream hashes.
- The runner records chip tokens from GO through HALT and separately counts text echoes. It times synchronized consumption of the input, chip run, and verdict echoes. It records the GPU, peak allocated and reserved CUDA memory, and guest static RAM plus observed stack usage. For the verification run, raw traces and the result summary stay in the remote VM at `/tmp/qlean/phase3/traces/`.

## Ephemeral Colab operation

The launcher uploads only source and runs through the installed CLI. The VM uses `/tmp/qlean` for `HF_HOME`, checkpoint shards, package and CUDA caches, the goal-bound ELF, compiled chip tensors, and traces. The verification path has no persistence step. The T4 is compute capability 7.5. It falls below the supported NVIDIA Triton target and lacks native BF16 Tensor Cores. [Colab CLI](https://github.com/googlecolab/google-colab-cli#usage-notes) [NVIDIA capabilities](https://www.nvidia.com/content/cuda/cuda-gpus.html) [Triton compatibility](https://github.com/triton-lang/triton#compatibility)

```bash
COLAB_SESSION=your-session-name
scripts/allocate_phase3.sh "$COLAB_SESSION"
scripts/run_phase3.sh "$COLAB_SESSION"
```

## CUDA Linux SSH fallback

Use an Ampere-class or newer NVIDIA GPU. The command below streams only source from the checkout. The remote launcher uses the host's CUDA-capable PyTorch when present and can install PyTorch's CUDA 12.8 wheel when needed. The host needs a compatible NVIDIA driver. The launcher uses Python 3.11 or newer and can install Python 3.12 under `/tmp/qlean` on an older image. It detects an RV32-capable LLVM or GNU cross-toolchain and can install missing system packages on Debian or Ubuntu with root or passwordless sudo. [PyTorch wheel matrix](https://pytorch.org/get-started/previous-versions/)

```bash
# Run from the QLean checkout root.
QLEAN_SSH='user@gpu-host'
QLEAN_SSH_PORT=22
set -o pipefail
scripts/phase3_source.sh | ssh -p "$QLEAN_SSH_PORT" "$QLEAN_SSH" '
  set -eu
  umask 077
  test ! -L /tmp/qlean
  mkdir -p /tmp/qlean
  test -O /tmp/qlean
  src=$(mktemp -d /tmp/qlean/source.XXXXXX)
  tar -xf - -C "$src"
  exec bash "$src/colab/run_phase3_vm.sh"
'
```

The verification summary stays at `/tmp/qlean/phase3/traces/phase3-results.json` on the GPU host.

## Initial allocation attempts

The CPU preflight endpoint was already gone when the stop request reached Colab. `colab sessions` pruned its stale local entry and reported no active runtimes on the server.

| Allocation round | L4 | A100 | G4 | H100 |
| --- | --- | --- | --- | --- |
| 1 | HTTP 503 | HTTP 503 | HTTP 503 | HTTP 503 |
| 2, after 5 seconds | HTTP 503 | HTTP 503 | HTTP 503 | HTTP 503 |
| 3, after 10 seconds | HTTP 503 | HTTP 503 | HTTP 503 | HTTP 503 |

The launcher and source archive passed local syntax checks and tests with a mocked CLI. The path guard rejects local invocation and confines remote runtime paths to the ephemeral root. These initial allocation attempts did not reach a CUDA host.

## Interrupted L4 run

The user-provided runtime reported an NVIDIA L4, 23,034 MiB of total VRAM, driver 580.82.07, and CUDA 13.0. Both `/tmp` and `/content` had 252,951,629,824 free bytes. The verification launch selected remote `/tmp/qlean`, and Colab confirmed the source-only upload.

Colab dropped the execution connection. A reconnect returned the CLI's 404/401 lost-session diagnostic, and the server registry then reported no active sessions. QLean issued neither an allocation nor a termination request. No verification summary was retrieved. A detached launch mode is available for the next run, and its shell and generated Python passed local syntax checks.

This run ended before the verification suite returned results.

## Verified L4 run

**Phase 3 passed.** The detached run exited 0 on an NVIDIA L4 with 23,034 MiB of total VRAM. Both storage paths had 236 GiB free, so the run kept the checkpoint, cache, firmware, compiled chip, and traces in remote `/tmp/qlean`. The runtime used PyTorch `2.14.1+cu130`, Transformers `5.19.0`, and Triton `3.8.0`. The goal-bound RV32 firmware passed a 3,712-byte linked stack bound against the 4,096-byte reservation.

- **Immutability.** Both checkpoint shards retained their SHA-256 digests through compilation and verification, covering all 738 checkpoint tensors. All 723 loaded parameters retained their fingerprints.
- **Residual isolation.** All 18 full-logit comparisons were bit-exact and all greedy token IDs matched. This covered 9 calls on a plain prompt and 9 calls on a chat-template prompt using separate stock and composed caches.
- **Lossless capture.** The 73-byte source containing `∀`, `→`, line breaks, and tactic indentation matched the guest buffer and its recorded length. Both the natural BPE path and the UTF-8 code points split into byte tokens produced the same guest hash and `OK`. The invalid proof and wrong-theorem source buffers also matched.
- **Circuit-owned verdicts.** The valid, ill-typed, and wrong-theorem proofs returned their expected verdicts. Two fresh invalid-proof replays produced identical complete stream hashes. A closing delimiter without an opener left the chip idle. Nested, overflowing, and oversized captures were rejected.

| Case | Guest verdict | Chip trace tokens | Wall time | Peak allocated | Peak reserved |
| --- | --- | ---: | ---: | ---: | ---: |
| `valid_bpe` | `QLEAN1 OK` | 41,534 | 11.519 s | 9.090 GiB | 9.205 GiB |
| `invalid_proof` | `QLEAN1 ERR_TYPE_MISMATCH 59` | 41,717 | 12.769 s | 9.092 GiB | 9.207 GiB |
| `wrong_theorem` | `QLEAN1 ERR_GOAL_MISMATCH 34` | 19,137 | 7.058 s | 9.091 GiB | 9.207 GiB |
| `split_utf8` | `QLEAN1 OK` | 41,523 | 11.531 s | 9.098 GiB | 9.211 GiB |
| `nested_open` | `QLEAN1 ERR_INPUT_TOO_LONG -` | 12,009 | 5.245 s | 9.098 GiB | 9.211 GiB |
| `row_overflow` | `QLEAN1 ERR_INPUT_TOO_LONG -` | 12,559 | 5.389 s | 9.125 GiB | 9.250 GiB |
| `oversized_token` | `QLEAN1 ERR_TRANSPORT -` | 5,180 | 3.163 s | 9.104 GiB | 9.258 GiB |
| `invalid_replay_1` | `QLEAN1 ERR_TYPE_MISMATCH 59` | 41,716 | 12.763 s | 9.091 GiB | 9.258 GiB |
| `invalid_replay_2` | `QLEAN1 ERR_TYPE_MISMATCH 59` | 41,716 | 12.776 s | 9.091 GiB | 9.258 GiB |

The peak observed guest stack was 336 bytes and the peak guest RAM was 18,244 bytes. Wall times include proof-token submission, the chip trace, and verdict echoes. VRAM columns are PyTorch allocator high-water marks for each run. Warm-up and artifact loading are outside the timed proof runs.

The run used `/tmp/qlean/models/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` for the original checkpoint and `/tmp/qlean/phase3/chip/circuit.safetensors` for the chip artifact. The chip SHA-256 was `499a5a468506d8f97368b7e98e0246ad4fed73259dc4d7ff234a59210450b8ad`, and the firmware SHA-256 was `62792e7a43bd974abb682f918b1bb0b6bb5e28497230cbdec58039f7abc1de28`. The only artifact retrieved from this run was the 6,591-byte `phase3-results.json`.
