# QLean Phase 1 engineering specification

QLean can target the public Qwenputer P3 RV32IM circuit with **256 KiB of instruction ROM, 128 KiB of read-only data ROM, and 32 KiB of writable guest RAM**. The stock merger changes learned Qwen normalization gains, and the stock text bridge can silently lose source bytes. The proposed implementation preserves the original Qwen model at its original width, adds a deterministic compiled chip and immutable firmware initialization tensors, and hardens the capture path before it can authorize a verdict. Phase 2 can validate the freestanding checker independently. The custom composition, firmware packaging, and end-to-end verification remain Phase 3 gates. [P3 memory map][spec] [Merger][merge] [Text bridge][capture]

## The public ELF loader defines the RV32IM target

Target `divagr18/qwenputer` commit `0cab57038a8b218dabe481f994174c3437405e3d` under `experimental/riscv/`. The pinned design notes refer to `env/rom.ld`, whose pinned public path returned 404 during research. Use the published ELF loader and reference-machine initialization as the ABI authority for a small QLean-owned linker script. The upstream code is MIT and the pinned Qwen3.5-4B checkpoint is Apache-2.0. Retain the applicable terms and notices for reused code and model artifacts. [Pinned source][upstream] [Design notes][linkerdocs] [Documented linker path][missingld] [ELF loader][elf] [Reference startup][init] [Upstream license][rvlicense] [Qwen checkpoint license][qwenlicense]

| Guest region | Address range, exclusive end | P3 capacity | Proposed QLean ceiling |
| --- | --- | ---: | ---: |
| Instruction ROM | `0x40000–0x80000` | 256 KiB | 64 KiB of executable code |
| Data ROM | `0x20000–0x40000` | 128 KiB | 16 KiB of strings, tables and constants |
| Writable RAM | `0x00000–0x08000` | 32 KiB (0.03125 MiB) | 28 KiB (0.02734 MiB) including stack |
| Text MMIO | `0x08000–0x08800` | 2 KiB, loads only | 79 usable 16-byte capture rows, including framing |

The proposed RAM budget assigns 16 KiB to the term arena, 4 KiB to input buffers and fixed state, 4 KiB to lexer, goal and normalization work storage, and 4 KiB to the downward-growing stack. Start writable static data at `0x100` and initialize `sp` to `0x8000`. This leaves 3.75 KiB of margin after the low 256-byte reservation. Enforce ceilings and stack separation in the linker script. Confirm actual section sizes, stack bounds, and measured arena and stack high-water marks during verification. [Machine constants][spec] [Reference startup][init]

Produce a static, little-endian RISC-V ELF32 executable with `ENTRY(_start)`. Use disjoint `PT_LOAD` segments for RX `.text*` in ROM, R `.rodata*` and `.srodata*` in DROM, and RW `.data*`, `.sdata*`, `.bss*` and `.sbss*` in RAM. Each segment, including padding, must fit its region under `p_vaddr` and `p_memsz`. The loader copies `p_filesz` bytes and zero-fills the remainder. Put instruction fetch at a four-byte-aligned entry in ROM and keep load-addressable constants in DROM. Place ELF/program headers outside the mapped segments if their inclusion would extend any segment below its region. Validate with `readelf -h -l -S -A`, symbol and disassembly inspection, and a boot through the pinned ELF loader and reference CPU. Reject dynamic sections, interpreters, TLS, unresolved runtime calls, unsupported instructions, and data or stack overlap. [ELF loader][elf] [Address definitions][spec] [Instruction decoder][isa]

Pin a bare-metal `riscv64-unknown-elf-gcc` toolchain for Phase 2. Start with `-Os -march=rv32im -mabi=ilp32 -mstrict-align -mno-relax -msmall-data-limit=0 -ffreestanding -fno-builtin -fno-pic -fno-stack-protector -nostdlib -static`. Supply any emitted memory intrinsics in freestanding C. Use 32-bit RV32I/M instructions and naturally aligned loads and stores. Keep startup to a small assembly stub and the firmware loop. P3 implements additional Zba and internal operations, but the kernel targets RV32IM and the two defined guest calls. [Instruction decoder][isa] [Upstream build notes][linkerdocs]

The initial `ecall` with `a7=93` parks the CPU. Each bridge GO resumes at the following instruction. The kernel reads the capture window, processes one request, emits its response, resets per-attempt state, and parks again. `ecall` with `a7=1` emits BYTE from `a0 & 511`. Values 0–255 produce byte echoes, and 256–259 echo the opening and closing tool-response and thinking tags. HALT emits a newline before the language model regains control. The reference handles an exit argument in `a0`, but the trace HALT has no payload for it. A CPU fault emits a fault token, eight PC nibbles, and HALT. [Reference machine calls and faults][ecall] [Bridge echoes and resume][echo] [Echo ownership][own]

## A single Lean theorem elaborates to a closed proof

Target **official Lean 4.36.0** with implicit `Init`, default options, and the submitted exact bytes as the complete contents of a fresh standalone file. Each theorem name uses `qlean_[a-z][a-z0-9_]*`. Check the prefix against the pinned initial environment. Local names match `[A-Za-z][A-Za-z0-9_]*`, excluding the audited pinned syntax keywords, reserved builtins, and conflicting names. Resolve locals only in their lexical context and require freshness within the active context. Grouped binders share a type checked before introducing any names from the group. The available global constants are the ones in the grammar. [Lean release][lean] [Source files][files] [Theorem declarations][theorems]

```ebnf
file     = "theorem" name { typed } ":" expr ":=" proof [ LF ] EOF
typed    = "(" id { id } ":" expr ")"
proof    = expr | "by" terminal
         | "by" LF indent { step LF indent } terminal
step     = "intro" id { id } | "apply" id
terminal = "exact" expr | "rfl"
expr     = "∀" quant "," expr | "fun" lbind { lbind } "=>" expr | arrow
quant    = id { id } ":" expr | typed { typed }
lbind    = id | typed
arrow    = equality [ "→" arrow ]
equality = sum [ "=" sum ]
sum      = app { "+" app }
app      = atom { atom }
atom     = id | digits | "Prop" | "Type" | "Nat" | "Nat.zero"
         | "Nat.succ" | "Nat.add" | "Eq" | "Eq.refl" | "rfl"
         | "@Eq" | "@Eq.subst" | "@Nat.rec" | "(" expr ")"
name     = "qlean_" lower { lower | digit | "_" }
id       = letter { letter | digit | "_" }
digits   = "0" | nonzero { digit }
lower    = "a" … "z"
letter   = lower | "A" … "Z"
digit    = "0" | nonzero
nonzero  = "1" … "9"
indent   = exactly two ASCII spaces
```

The theorem starts in column 1. Statements and term proofs use one physical line. An inline `by` has a single terminal tactic, while a multiline `by` uses the exact indentation shown, one tactic per line and zero blank lines. Use ASCII spaces to separate adjacent word tokens and juxtaposed arguments. Recognize complete longest tokens with word boundaries, including dotted builtin names and `@` forms. Application and `+` associate left, `→` associates right, and `=` permits one comparison. Use parentheses around quantifiers and lambdas appearing as operands. Accept decimal numerals with zero as the only leading-zero form. The only non-ASCII source characters are literal UTF-8 `∀` and `→`. Reject malformed UTF-8, tabs, CR, BOM, NUL, bidi, other control characters, comments, holes, `sorry`, `admit`, extra commands, and unconsumed input. [Function types][pi] [Functions][lambda] [Function application][app]

Use a bidirectional dependent checker with capture-safe de Bruijn terms, sorts, dependent products, typed lambdas, applications, and fixed constants. `Prop = Sort 0`, `Type = Sort 1`, and `Sort i : Sort (i + 1)` with checked universe arithmetic. Set the proposed internal ceiling at `Sort 3` and return `ERR_LIMIT` if a judgment requires a higher sort. For domain and codomain of sorts `i` and `j`, the dependent product has sort 0 when `j = 0`, otherwise `max(i,j)`. Elaborate declaration binders around the statement and proof, require the statement to be a closed proposition, and independently check the completed core proof at exactly that type. Require an expected Pi for untyped lambdas and validate each argument against its substituted domain. Reject unresolved names, metavariables, recursive theorem references, inferred global instances, and implicit user binders. [Lean universes][universes] [Lean propositions][props]

`x = y` and `Eq x y` elaborate as saturated homogeneous equality with an independently checked common carrier. `@Eq A x y` supplies the carrier. `Eq.refl x` supplies the endpoint and synthesizes its carrier. Infix `+` and decimal numerals are Nat-only, using pinned default Nat elaboration for closed numeral expressions and a checked Nat carrier for typed operands. Reject ambiguous or unverified elaboration cases. Conversion uses checked beta reduction, Nat addition's recursion on its second argument, and `Nat.rec` constructor reduction. At v1, omit optional `eta` and proof irrelevance from QLean conversion, which can narrow acceptance. Bound input size, lexical and binder depth, arena and work storage, and normalization fuel. Start with source numerals at most 65,535 and packed closed Nat intermediates at most `UINT32_MAX`. Reject exhaustion or inexact arithmetic. [Lean Nat and numerals][nat] [Pinned Nat.add definition][natadd] [Equality typing and reflexivity][eq]

`intro` exposes explicit Pi binders and builds lambdas. `apply f` accepts a local `f` with one explicit nondependent premise and a rigid non-Pi conclusion convertible to the only goal, then opens one premise goal and builds `f t` when that premise closes. Initially a rigid goal is a local proposition, a local predicate applied to checked arguments, or homogeneous equality. `exact` checks and closes the current goal. Term and tactic `rfl` require a homogeneous equality goal with convertible endpoints and build explicit reflexivity. Validate the final proof independently of the tactic state. [Lean tactic reference][tactics]

Use fully applied `@Nat.rec m z s n` for cases and induction in term mode, with `m : Nat → Prop`, `z : m Nat.zero`, `s : ∀ k : Nat, m k → m (Nat.succ k)`, and `n : Nat`. Check its result at `m n`. Permit fully applied `@Eq.subst A P a b h pa` for transport with a Prop-valued motive, using its pinned type and treating it as opaque during conversion. These builtins cover the first inductive fragment. Surface `cases` and `induction` tactics, general `match`, and user-defined inductive declarations are outside v1. [Lean inductive types][inductives] [Nat.rec signature][rec] [Eq.subst signature][eq]

Proposed fixtures, each in its own file.

```lean
theorem qlean_add_four : 2 + 2 = 4 := by rfl
```

```lean
theorem qlean_use : ∀ (A : Type) (P : A → Prop) (a : A), (∀ x : A, P x) → P a := fun A P a h => h a
```

```lean
theorem qlean_apply : ∀ P Q : Prop, (P → Q) → P → Q := by
  intro P Q f h
  apply f
  exact h
```

```lean
theorem qlean_zero_add (n : Nat) : 0 + n = n := @Nat.rec (fun (k : Nat) => 0 + k = k) rfl (fun k ih => @Eq.subst Nat (fun (j : Nat) => Nat.succ (0 + k) = Nat.succ j) (0 + k) k ih rfl) n
```

These fixtures are proposals pending execution under the pinned official compiler in Phase 2.

## Lossless capture ties compact verdicts to the submitted proof

The stock bridge captures the token fragments between its tool-call tags in rows 1–80 at `0x8000 + 16*i`. It zero-pads fragments shorter than 16 bytes, truncates longer fragments, and overwrites row 80 on continued input. Another opening tag resets capture. UTF-8 code points can span token fragments. The raw 1,280-byte slot capacity is therefore neither a guaranteed payload size nor a check on input identity. [Token mapping][row] [Capture and saturation][capture] [Circuit text table][texttable]

Propose an exact frame of a circuit-recognized opening `<tool_call>` token, literal `QLEAN1` and LF, one source file as defined above, and a circuit-recognized `</tool_call>` token. Compile chip token features with exact 1–16 byte fragments or a nonempty invalid row starting with `0xff` for oversized, empty, embedded-NUL or disallowed tokens. Require a fresh contiguous capture, reserve row 80 as an overflow marker, and reject any occupied row 80, invalid row, gap, or missing frame boundary. Cap the entire interior at 79 tokens and 1,264 reconstructed bytes, including the seven-byte prefix. Concatenate valid rows before UTF-8 validation and remove exactly the prefix. Hold an in-circuit invalid-frame flag through nested opening tags until closure, and arm capture only for a new generated attempt. An unmatched or incomplete delimiter yields no verdict. Verify row and ownership behavior against the pinned tokenizer and compiled executor before treating model submissions as checked. This proposed hardening retains the original Qwen tokens and moves loss detection into the chip and guest. [Bridge rules][capture] [Counter constraints][counter] [Prompt and first token handling][prefill]

The guest emits a circuit-owned `<tool_response>` tag, a single ASCII status line, then a circuit-owned `</tool_response>` tag and normal HALT. A line is either `QLEAN1 OK` followed by LF, or `QLEAN1 ERR_<CODE> <offset>` followed by LF. Use a canonical decimal zero-based source byte offset, including the EOF position, or `-` when no source position exists. Return the first deterministic error in pipeline order of transport, lexing and parsing, theorem binding, elaboration, and core checking. Check budgets at the point of use. Only the completed guest-owned frame conveys the verifier status.

| Code | Meaning |
| --- | --- |
| `OK` | Entire source consumed and the closed proof checked at the declared proposition |
| `ERR_TRANSPORT` | Closed form received with invalid capture, framing, or UTF-8 |
| `ERR_SYNTAX` | Unsupported syntax, lexical or layout error, or extra input |
| `ERR_GOAL_MISMATCH` | Statement differs from the trusted target for this run |
| `ERR_UNBOUND` | Unresolved or conflicting identifier |
| `ERR_TACTIC` | Unsupported tactic or invalid tactic step |
| `ERR_TYPE_MISMATCH` | Statement or proof fails a type or conversion check |
| `ERR_LIMIT` | Continuing would exceed a size, depth, universe, arena, fuel or Nat bound |

A missing response, chip fault, host interruption, timeout, or token exhaustion is a run failure with no certified verdict. Count success only after one complete circuit-origin response in the matching GO-to-normal-HALT span. For goal-bound demos, put the expected standalone theorem header bytes in the trusted firmware manifest and DROM and compare each submission's header byte-for-byte inside the guest. Reset all per-attempt state before the next GO. Keep the theorem prefix, offsets, and proof bytes visible in test evidence so a valid proof of a different theorem cannot pass a demo. [Reference fault and HALT behavior][ecall] [Circuit output ownership][own]

## Phase 2 gates the checker before GPU execution

The proposed source tree assigns each milestone a small set of entry points. Only `AGENTS.md` and this specification are Phase 1 deliverables.

```text
QLean/
  AGENTS.md
  README.md                              # Phase 4
  reports/QLean Phase One Specification.md
  lean-toolchain                         # Lean 4.36.0 pin
  kernel/
    Makefile                             # host, rv32 and local validation targets
    include/qlean.h                      # length-delimited checker and result types
    src/{lex,parse,elab,check,arena}.c
    host/main.c                          # native test binary
    rv32/{start.S,io.c,qwenputer.ld}       # production board and firmware loop
  tests/
    valid/*.lean
    invalid/*.lean
    transport/                           # row, frame and repeat-call fixtures
  scripts/
    check_lean.sh                        # exact-byte official Lean comparison
    test_rv32.py                         # loader, reference CPU and ABI checks
  colab/
    {setup,compile,verify}.py              # Phase 3, run with installed colab CLI
  qlean.py                               # Phase 4, integrated single-stream runner
  demos/
    {self_correction,hallucination_wall,zero_subprocess}.py
```

Use one checker core for native and RV32IM builds. Run more than 20 accepted cases and more than 20 rejected cases through both, with matching verdicts and source offsets where applicable. Cover propositional identity and composition, first-order specialization under `Type` and Nat, predicate transport, beta and reflexivity, closed addition, symbolic right zero, and term-mode cases and induction. Exercise false equality and swapped implication, free and shadowed names, wrong sorts and carriers, wrong recursor premises, incomplete and bogus tactics, trailing commands and admissions, malformed bytes, overflows, depth and fuel limits, and invalid or repeated transport. Include deliberately unsupported Lean-valid cases in the rejection corpus as a test of conservative acceptance.

Run the official Lean cross-check on each exact original accepted fixture byte sequence in a fresh file. Check the toolchain version, compile status and diagnostics, and require an empty dependency list from a separate `#print axioms` check for the allowlisted builtin fragment. Validate false-statement and ill-typed negative fixtures under Lean too. Use native sanitizers, focused parser mutations, boundary inputs, stack usage and linker-map checks, and reference-CPU parity. The requested `review-agent` audit must examine Lean syntax and elaboration correspondence, substitution and scoping, universes and conversion, inductive branch typing, deterministic budget exhaustion, and C memory safety. Test results complement the soundness argument that every accepted source elaborates under pinned Lean and produces a well-typed proof of its exact statement. [Lean proof validation][validate]

## An immutable composition and same-stream verdict gate GPU work

The upstream `python -m chipformer.rv.merge BASE --out DIR` builds 11 deterministic chip layers into a widened checkpoint. It applies a width compensation to learned RMSNorm gains even with `--no-mute`, and the default path also constructs fitted anti-sink directions for new columns. Its merge command takes no firmware ELF. Instead, `core.snapshot` maps predecoded instructions and DROM from the supplied ELF into recurrent DeltaNet state, plus PC, registers, and RAM initialization. This is a usable circuit and firmware layout reference. Its stock checkpoint fails QLean's immutable-learned-tensor gate. [RV32 design][design] [Exact merger implementation][merge] [Anti-sink construction][mute] [Firmware snapshot][snapshot] [Chat bootstrap][prefill]

Propose one integrated decode loop with the original `Qwen/Qwen3.5-4B` base at model revision `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`, and deterministic additive DeltaNet/SwiGLU chip layers and ROM/DROM initialization tensors in the compiled model package. Build the firmware-specific tensors offline from the audited ELF. Load an immutable, validated first-park snapshot into the recurrent heads at startup, then run proof execution in the compiled chip layers. Require byte-for-byte tensor identity against the pinned base, including its learned embeddings, head and normalization gains, and use the original dimensions and ordinary text-cache path. Record model, source, toolchain, firmware and artifact hashes. The proposed firmware artifact is a static tensor package whose ROM becomes recurrent state during execution. Phase 3 must demonstrate this firmware packaging and immutable base composition together. QwenFX demonstrates separate base and chip weights with boot state for a different circuit. [Pinned base model][base] [P3 snapshot format][snapshot] [QwenFX artifact precedent][qfx]

Use the pinned CUDA Triton `chipformer.rv.tritonexec.Executor2` path as the executor target. Upstream compiles circuit IR into GPU tensors, fuses operations with Triton and replays a CUDA graph per chip token. `RvChat(executor=True)` selects that path. Its stock CLI uses host reference lockstep and its bootstrap runs the reference CPU to first park. Use those only for offline development comparisons. The production proof run must load the persisted compiled artifact or its serialized executor coefficients and match the compiled circuit on bounded trace replay. Upstream reports approximately 3,200 chip tokens/s on an L4 for its calculator demos. Upstream's API defaults to 4,000 text tokens and 60,000 chip tokens. Both are runner settings. QLean throughput, memory, and trace counts are unmeasured. [Executor selection][executor] [Executor implementation][triton] [Upstream L4 results][design] [API defaults][prefill] [CLI lockstep][cli]

For Phase 3, use the installed `colab` CLI with `colab new -s "$COLAB_SESSION" --gpu L4`, `colab drivemount -s "$COLAB_SESSION" /content/drive`, and `colab exec -s "$COLAB_SESSION" -f colab/verify.py` after setup and compilation. Set `COLAB_SESSION` to the session name. Prefer a CUDA BF16-capable L4-class or better runtime. Verify allocated GPU, driver and pinned dependencies with a Triton CUDA-graph smoke test, plus host RAM and Drive quota before model I/O. Confirm the Drive mount uses the intended account. Set `HF_HOME` to `/content/drive/MyDrive/QLean/hf`, `HF_HUB_CACHE` to its `hub` subdirectory, and keep model files, other model and build caches, compiled artifacts, metrics and raw traces in the `/content/drive/MyDrive/QLean/` tree. Keep the local checkout source-only aside from the requested documents and transient native testing. CLI 0.7.5 was installed at the time. Resolving the CLI logging context, authenticating, selecting hardware and mounting Drive were Phase 3 preflight tasks. [Colab CLI][colab] [Colab resource availability][colabfaq] [Triton GPU compatibility][compat] [Pinned Python lock][lock]

Run a fixed small theorem repeatedly with identical firmware and input on the GPU. Compare the complete circuit-origin verdict, trace and relevant state to development references, test matching rejection paths, and verify the trained tensor identity and artifact-load path. Record chip trace tokens, language tokens, guest peak RAM from static data, arena and stack high-water marks, GPU allocated and reserved VRAM, host peak RSS, and device-synchronized proof wall time. Measure setup and warmup separately. If the input is a controlled generated-span token fixture, record that provenance. A complete call in prompt prefill is history in stock P3. [Prefill and CLI replay][prefill] [Text and chip token routing][routing]

In Phase 4 retain one original language cache and text position for each generation. Chip-only tokens advance the compiled circuit, while ordinary output and chip-owned verdict echoes advance Qwen's text state. Include provenance in the display event stream, count trace tokens in the single-line status, and let the model read the actual guest echo through its existing stream. The host handles routing and display. Run the self-correction demo with a genuine generated bad candidate, authenticated guest error, and corrected candidate finishing at `OK` on the same target. Drive the adversarial demo with the requested false theorem and retain evidence of every attempt and its outcome. For a whole-launch zero-subprocess claim, prepare a compatible compiled cache offline and trace the runner and children from launch through exit with `strace`. Cold Triton JIT can invoke `ptxas`. A trace captured after setup and warmup supports only a labeled proof-interval claim. Record process creation and exec events and keep the evidence on Drive. Document the usable Lean subset and measured input, firmware, memory and latency limits in the README. Mathlib's environment and tactics exceed the P3 memory windows and the supported grammar. [Same-cache routing][routing] [Triton NVIDIA compilation][ptxas]

## Phase boundary

Explicit approval of this specification opens Phase 2. The meaningful downstream test is whether an exact, goal-bound Lean source yields the same certified verdict through native C, the pinned RV32IM ABI, and a persisted deterministic chip artifact in the original Qwen generation stream. Phase 1 inspected source and established the design and its gates. Compiler runs, artifacts, and GPU measurements are pending.

[upstream]: https://github.com/divagr18/qwenputer/commit/0cab57038a8b218dabe481f994174c3437405e3d
[rvlicense]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/LICENSE
[qwenlicense]: https://huggingface.co/Qwen/Qwen3.5-4B/tree/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a
[spec]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/chipformer/rv/spec.py#L65-L80
[merge]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/chipformer/rv/merge.py#L119-L183
[capture]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/chipformer/rv/bridge.py#L119-L164
[linkerdocs]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/docs/rv32.md#L134-L156
[missingld]: https://raw.githubusercontent.com/divagr18/qwenputer/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/env/rom.ld
[elf]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/chipformer/rv/elf.py#L8-L41
[init]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/chipformer/rv/ref.py#L375-L389
[isa]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/chipformer/rv/ref.py#L93-L143
[ecall]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/chipformer/rv/ref.py#L416-L505
[echo]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/chipformer/rv/bridge.py#L140-L165
[own]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/chipformer/rv/core.py#L1057-L1070
[lean]: https://github.com/leanprover/lean4/releases/tag/v4.36.0
[files]: https://lean-lang.org/doc/reference/4.36.0/Source-Files-and-Modules/
[theorems]: https://lean-lang.org/doc/reference/4.36.0/Definitions/Theorems/
[pi]: https://lean-lang.org/doc/reference/4.36.0/Terms/Function-Types/
[lambda]: https://lean-lang.org/doc/reference/4.36.0/Terms/Functions/
[app]: https://lean-lang.org/doc/reference/4.36.0/Terms/Function-Application/
[universes]: https://lean-lang.org/doc/reference/4.36.0/The-Type-System/Universes/
[props]: https://lean-lang.org/doc/reference/4.36.0/The-Type-System/Propositions/
[nat]: https://lean-lang.org/doc/reference/4.36.0/Basic-Types/Natural-Numbers/
[natadd]: https://github.com/leanprover/lean4/blob/v4.36.0/src/Init/Prelude.lean#L1708-L1724
[eq]: https://lean-lang.org/doc/reference/4.36.0/Basic-Propositions/Propositional-Equality/
[tactics]: https://lean-lang.org/doc/reference/4.36.0/Tactic-Proofs/Tactic-Reference/
[inductives]: https://lean-lang.org/doc/reference/4.36.0/The-Type-System/Inductive-Types/
[rec]: https://lean-lang.org/theorem_proving_in_lean4/Inductive-Types/#defining-the-natural-numbers
[row]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/chipformer/rv/bridge.py#L39-L73
[texttable]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/chipformer/rv/core.py#L832-L859
[counter]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/docs/rv32.md#L125-L127
[validate]: https://lean-lang.org/doc/reference/4.36.0/ValidatingProofs/
[design]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/docs/rv32.md
[mute]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/chipformer/q35/mute.py#L61-L83
[snapshot]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/chipformer/rv/core.py#L1156-L1208
[prefill]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/chipformer/rv/chat.py#L293-L354
[base]: https://huggingface.co/Qwen/Qwen3.5-4B/commit/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a
[qfx]: https://github.com/divagr18/QwenFX#how-it-works
[executor]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/chipformer/rv/chat.py#L90-L126
[triton]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/chipformer/rv/tritonexec.py#L230-L285
[cli]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/chipformer/rv/chat.py#L457-L479
[colab]: https://github.com/googlecolab/google-colab-cli#usage-notes
[colabfaq]: https://research.google.com/colaboratory/faq.html#resource-limits
[compat]: https://github.com/triton-lang/triton#compatibility
[lock]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/uv.lock#L1200-L1276
[routing]: https://github.com/divagr18/qwenputer/blob/0cab57038a8b218dabe481f994174c3437405e3d/experimental/riscv/chipformer/rv/chat.py#L362-L402
[ptxas]: https://github.com/triton-lang/triton/blob/main/third_party/nvidia/backend/compiler.py#L565-L570
