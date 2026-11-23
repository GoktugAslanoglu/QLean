# QLean Phase 2 build and audit

The shared freestanding C checker builds as a native executable and as an RV32IM ELF for Qwenputer P3. The ELF enters at `0x40000`, parks before reading text, and emits a framed `QLEAN1` result before parking again. The host and reference firmware use the same parser, elaborator, and type checker. [Pinned P3 ELF loader](https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/chipformer/rv/elf.py) [Pinned P3 reference CPU](https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/chipformer/rv/ref.py)

## Resource limits

| Resource | Limit or measurement |
| --- | ---: |
| Source input | 1,257 bytes after the 7-byte frame prefix |
| Arena | 2,048 eight-byte slots, with index zero reserved |
| Context | 32 entries |
| Simultaneous guarded calls | 28 |
| WHNF budget | 2,048 loop iterations per proof attempt |
| Shared traversal budget | 32,768 charged operations per attempt |
| Linked instruction ROM | 15,224 bytes |
| Linked data ROM | 2,988 bytes |
| Static RAM | 17,905 bytes |
| Stack reservation | 4,096 bytes |
| Conservative linked stack bound | 3,696 bytes |
| Peak stack observed in the main reference suite | 2,432 bytes |
| Static RAM plus full stack reservation | 22,001 bytes of the 28 KiB budget |

The linker independently caps static RAM at 24 KiB and reserves the final 4 KiB of the guest address space for the stack. The guarded C call bound includes the frame of a call refused at maximum depth. Arena, context and call depth exhaustion produce `ERR_OOM`. The input and evaluator budgets produce `ERR_INPUT_TOO_LONG` and `ERR_FUEL`. Tests reach both the actual node-arena limit and the WHNF limit.

## Soundness and compatibility review

- The checker consumes the full source and elaborates tactics into explicit, closed terms. A second pass infers the final core proof type, then compares it against the exact declared proposition. De Bruijn shifting and substitution preserve binder scope, with grouped binders checked under the no-shadowing rule. The lexer uses the pinned Init keyword table for local identifiers.
- Internally, `Prop` is `Sort 0` with type `Sort 1`, and bare `Type` is `Sort 1` with type `Sort 2`. Products use Lean's impredicative `imax` rule. Conversion is intentionally conservative on proof irrelevance and eta. The approved surface grammar admits bare `Type`.
- `@Nat.rec` accepts a Prop-valued motive, a zero proof, a successor proof with a typed induction hypothesis, and a Nat scrutinee. Every argument is checked before any iota rule uses a branch. The independent Lean oracle checks the sort hierarchy and recursor type, then reduces distinguishable zero and successor branches with proof reduction enabled. [Lean 4.36.0 release](https://github.com/leanprover/lean4/releases/tag/v4.36.0) [Lean inductive types](https://lean-lang.org/doc/reference/4.36.0/The-Type-System/Inductive-Types/)
- The independent review found a malformed UTF-8 cursor overread in the first tactic parser draft and an initial 32-frame depth cap whose conservative stack bound exceeded 4 KiB. The final parser consumes a full multibyte token only when it matches, and the final cap is 28. The reviewed build passed the corresponding regressions. The review confirmed the universe, substitution, typed iota, and final proof-checking invariants.

## Validation results

| Check | Result |
| --- | --- |
| Native suite | 34 accepted, 48 rejected, and 3 goal-binding checks |
| Official Lean 4.36.0 | 35 exact-source successes with empty axiom dependencies, including the goal-bound success, and 26 expected source rejections |
| Pinned P3 reference CPU | 80 exact host/RV32 verdict matches on the main ELF, including transport and repeat calls |
| Goal-bound P3 ELF | Target proof accepted, bad proof and substituted theorem rejected, and target accepted again after rejection |
| ASan and UBSan | 10,366 exact-length inputs checked twice each, plus the native suite |
| Independent differential review | 194 accepted out of 1,176 source variants and 30 accepted out of 237 identifier tests. Every accepted variant compiled with official Lean. |

The main ELF used Clang 23.1.3 with `-march=rv32im -mabi=ilp32` and GNU cross linker 2.47.20260726. Its SHA-256 was `a4f25badcd9870983deec614158f73a386233dc7a85f2189ce171b03d9253193`. The reference CPU checks modeled preframed MMIO rows and actual firmware execution, including the guest response tags and HALT. AddressSanitizer and UndefinedBehaviorSanitizer ran with LeakSanitizer disabled because the local sandbox cannot run its process inspection. The kernel itself uses fixed static allocation.

## Reproduce

Supply the official Lean 4.36.0 executable and the source-only checkout of the pinned Qwenputer revision. Use the `experimental/riscv` directory as `QWENPUTER_RISCV`. Set `RV_LD` to an ELF32-capable RISC-V GNU linker, such as `riscv64-elf-ld` on Arch. Build from scratch when changing compiler, flags, or bound goal.

```bash
build=$(mktemp -d /tmp/qlean-build.XXXXXX)
make -C kernel BUILD="$build" RV_LD="$RV_LD"
python3 scripts/test_kernel.py "$build/qlean-host"
python3 scripts/check_stack.py "$build"
LEAN="$LEAN" scripts/check_lean.sh "$build/qlean-host"
python3 scripts/test_rv32.py "$build/qlean.elf" "$build/qlean-host" "$QWENPUTER_RISCV"
make -C kernel BUILD="$build" sanitize-run
```

To check a goal-bound firmware build, create a second build directory and put the single C string literal `"theorem qlean_target : 2 + 2 = 4 :="` in a file called `goal.inc`. Pass its absolute path as the quoted preprocessor macro `QLEAN_GOAL_FILE` via `RV_EXTRA`, then pass the resulting ELF as `--goal-elf` to `scripts/test_rv32.py`.

Phase 3 still requires byte-identical learned tensors, original-width RMSNorm isolation, the hardened circuit capture and its provenance, and actual Triton execution on Colab. Phase 2 leaves the project tree source-only.
