# QLean contributor instructions

QLean is an open-source proof of concept for checking a strict subset of Lean 4 inside a deterministic Qwenputer RV32IM circuit composed with Qwen3.5-4B.

## Milestones

1. Research the pinned Qwenputer source and specify the repo layout, Lean subset, verdict protocol, and memory budgets. Stop for the user's explicit approval before writing the kernel.
2. Build the freestanding C kernel, native test executable, and RV32IM ELF. Cross-check the accepted fixture bytes with official Lean 4, exercise adversarial inputs, and complete the requested `review-agent` soundness and memory-safety audit before GPU work.
3. Compile and run the Qwenputer artifact on the authorized remote runtime. Record the hardware, source and artifact revisions, exact verdicts, trace-token counts, guest RAM usage, and wall-clock measurements.
4. Build the single-stream runner and three reproducible demos. Document measured results and current limits in the README.

## Training and storage

- Preserve every learned Qwen3.5-4B tensor unchanged, including embeddings, output weights, and normalization gains. Verify tensor identity across packaging and composition. Build new chip tensors deterministically from source and architecture constants, with no fine-tuning, LoRA, or fitting to data.
- Put the verification program and execution logic in the compiled Qwenputer RV32IM ROM and DeltaNet circuit. The live host runner may transport tokens and display diagnostics. Keep proof parsing, checking, and verdict generation in the guest.
- Run Phase 3 verification via the installed `colab` CLI using ephemeral remote `/tmp/qlean` storage for model weights, Hugging Face caches including `HF_HOME`, compiled artifacts, and trace logs. Use the same path on an SSH CUDA host once the user supplies a host and asks to run there. Check effective paths before setup. Persist to Drive or Hugging Face only after the Phase 3 gates pass and the user directs persistence.
- Keep the local workspace to source, the C kernel under 1 MB, tests, scripts, and requested project documentation. Keep all model weights, Hugging Face caches, compiled `.safetensors`, and trace logs off the local machine. Keep local native testing transient.

## Soundness and runtime evidence

- Cap guest RAM at 28 KiB, including a 4 KiB stack reservation. Use fixed input, arena, context, and work buffers, with 16-bit node indices. Bound every recursive traversal and WHNF budget. Report `ERR_INPUT_TOO_LONG`, `ERR_OOM`, or `ERR_FUEL` at the corresponding limit.
- Keep `Prop : Type 0` and `Type 0 : Type 1` in a noncumulative sort hierarchy. Check every Nat recursor motive, branch, and scrutinee before conversion can use its zero or successor rule. Verify the rules against Lean 4.36.0.
- Keep learned tensor identity and residual-stream isolation as Phase 3 gates. Document the pinned stock RMSNorm width compensation in Phase 3 and verify the original-width normalization path.

- Return `OK` only after receiving a complete, lossless source frame, consuming the entire input, and independently type-checking a closed elaborated proof against the exact stated proposition. Use fixed, audited primitive declarations and conversion rules. Reject unsupported syntax, unchecked axioms, metavariables, unresolved names, extra commands, and unconsumed input.
- Treat every input byte, model token, tactic, and claimed verdict as untrusted. Reject ambiguity, truncation, arithmetic overflow, exhausted resources, and malformed UTF-8. Bound all memory, depth, and execution counters. Every failure path must withhold `OK`.
- Require that each accepted source is valid as a standalone theorem under the pinned official Lean 4 checker and its declared prelude. Cross-check the exact original bytes of accepted fixtures. Include at least 20 accepted and 20 rejected cases, with false statements, ill-typed terms, name and tactic errors, and malformed transport among the rejection tests.
- Bind goal-specific demo success to the requested statement. Recognize a verdict only from a complete, attributable guest-output frame on the original generation stream. Treat model-authored lookalikes, partial output, circuit faults, and missing terminal events as failures. Keep external proof checkers and reference CPU execution out of the live verification path.
- Stage every measured claim behind a reproducible test and record the limits in effect. Treat passing tests as evidence for the audited checker and its integration.
