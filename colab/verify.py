"""Run the Phase 3 gates and save evidence in ephemeral remote storage."""
import hashlib
import json
import re
import time

from paths import (BASE, BASE_REV, BUILD, CHIP, QWENPUTER, TARGET, TRACES, add_upstream,
                   configure, digest, require_cuda)

from owned import MISMATCH, VERDICT, drive_owned, guest_source


def tensor_fingerprints(model):
    import torch

    result = {}
    for name, value in model.named_parameters():
        raw = value.detach().reshape(-1).contiguous().view(torch.uint8).cpu()
        result[name] = (str(value.dtype), list(value.shape),
                        hashlib.sha256(memoryview(raw.numpy())).hexdigest())
    return result


def verify_idle(model, chip, tokenizer, torch):
    from composition import Composition, StockStream

    text = "Write a short explanation of the symbol ∀."
    plain = tokenizer.encode("Explain why the sky is blue in one sentence.",
                             add_special_tokens=False)
    chat = tokenizer.apply_chat_template([{"role": "user", "content": text}],
                                         tokenize=True, return_dict=False,
                                         add_generation_prompt=True, enable_thinking=False)
    report = []
    for shape, ids in (("plain", plain), ("chat_template", chat)):
        chip.reset()
        baseline = StockStream(model)
        candidate = Composition(model, chip)
        tokens = []
        for i in range(9):
            expected = baseline.consume(ids)
            actual, owned = candidate.consume_text(ids)
            if owned is not None or not torch.equal(expected, actual):
                raise RuntimeError(f"Idle logit or ownership mismatch at step {i}")
            greedy = int(expected[0, -1].argmax())
            if greedy != int(actual[0, -1].argmax()):
                raise RuntimeError(f"Idle greedy mismatch at step {i}")
            tokens.append(greedy)
            ids = [greedy]
        report.append({"input_format": shape, "bit_exact_logit_calls": 9, "greedy_ids": tokens})
    return report


def encoded_source(text, source, split_unicode):
    content = "QLEAN1\n" + source
    if split_unicode:
        ids = []
        for part in re.split(r"([∀→])", content):
            if part in ("∀", "→"):
                ids.extend(text.byte_token[byte] for byte in part.encode())
            elif part:
                ids.extend(text.encode(part))
    else:
        ids = text.encode(content)
    if text.decode_bytes(ids) != content.encode():
        raise RuntimeError("Pinned tokenizer changed source bytes")
    if not 1 <= len(ids) <= 79 or any(
        len(text.bytes[q]) > 16 or b"\0" in text.bytes[q] or not text.bytes[q] for q in ids
    ):
        raise RuntimeError("Test fixture exceeds the admitted capture budget")
    return [text.TCO, *ids, text.TCC]


def run_proof(session, ids, expected, source, capture_map, trace_file, torch, case):
    chip = session.chip
    evidence = {"test": case, "input_ids": ids, "expected": expected}
    chip.start_measurement()
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    try:
        _, token = session.consume_text(ids)
        _, verdict, trace_count, echoed, stream = drive_owned(session, token)
        evidence["stream_ids"] = stream
        torch.cuda.synchronize()
        evidence["wall_seconds"] = time.perf_counter() - started
        parsed = VERDICT.fullmatch(verdict)
        actual = (parsed[1] or parsed[2]).decode()
        if source is not None and parsed[3] not in (None, b"-") and int(parsed[3]) > len(source):
            raise RuntimeError("Guest failure offset is outside the captured source")
        evidence.update(verdict=verdict.decode().strip(), chip_trace_tokens=trace_count,
                        echoed_text_tokens=echoed, input_text_tokens=len(ids),
                        peak_allocated_vram_bytes=torch.cuda.max_memory_allocated(),
                        peak_reserved_vram_bytes=torch.cuda.max_memory_reserved(),
                        stream_sha256=hashlib.sha256(json.dumps(stream).encode()).hexdigest())
        evidence.update(chip.guest_memory())
        if actual != expected:
            raise RuntimeError(f"Expected {expected}; got {actual}")
        if parsed[2] in MISMATCH and (parsed[4] is None or parsed[5] is None):
            raise RuntimeError("Upgraded firmware omitted mismatch diagnostics")
        if source is not None:
            capture = guest_source(chip, capture_map)
            if capture != source:
                raise RuntimeError("Guest RAM differs from the exact BPE source bytes")
            evidence.update(source_bytes=len(source), guest_source_sha256=hashlib.sha256(capture).hexdigest())
    finally:
        trace_file.write_text(json.dumps(evidence) + "\n")
    return {k: v for k, v in evidence.items() if k not in ("stream_ids", "input_ids")}


def main():
    configure()
    add_upstream()
    import torch
    import transformers
    import triton
    from safetensors import safe_open
    from safetensors.torch import load_file
    from chipformer.rv.bridge import Text
    from composition import Chip, Composition

    gpu = require_cuda()
    metadata = json.loads((CHIP / "manifest.json").read_text())
    if (metadata["qwenputer"], metadata["base"], metadata["target"]) != (QWENPUTER, BASE_REV, TARGET):
        raise RuntimeError("Compiled manifest pin mismatch")
    artifact = CHIP / "circuit.safetensors"
    if (digest(artifact) != metadata["artifact_sha256"]
            or digest(BUILD / "qlean.elf") != metadata["firmware_sha256"]
            or digest(BASE / "config.json") != metadata["config_sha256"]
            or digest(BASE / "tokenizer.json") != metadata["tokenizer_sha256"]):
        raise RuntimeError("Chip, ELF, config or tokenizer digest mismatch")
    paths = sorted(BASE.glob("*.safetensors"))
    if {p.name: digest(p) for p in paths} != metadata["base_sha256"]:
        raise RuntimeError("Original checkpoint shard hashes disagree")
    original_tensors = 0
    for path in paths:
        with safe_open(path, framework="pt") as shard:
            original_tensors += len(shard.keys())

    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    model = transformers.Qwen3_5ForConditionalGeneration.from_pretrained(
        BASE, dtype="auto", device_map={"": "cuda"}, local_files_only=True,
        attn_implementation="eager",
    ).eval()
    if model.config.text_config.hidden_size != 2560:
        raise RuntimeError("Unexpected residual width for the pinned Qwen3.5-4B")
    before = tensor_fingerprints(model)
    text = Text(BASE / "tokenizer.json")
    tokenizer = transformers.AutoTokenizer.from_pretrained(BASE, local_files_only=True)
    tensors = load_file(artifact, device="cuda")
    chip = Chip(metadata, tensors, text)
    parity = verify_idle(model, chip, tokenizer, torch)
    def fresh_stream():
        chip.reset()
        stream = Composition(model, chip)
        stream.prefill(text.encode("Check the supplied Lean proof.\n"))
        return stream

    session = fresh_stream()
    capture_map = json.loads((BUILD / "capture.json").read_text())
    if capture_map["firmware_sha256"] != metadata["firmware_sha256"]:
        raise RuntimeError("Guest capture symbol does not belong to the compiled ELF")
    valid = TARGET + " by\n  intro P h\n  exact h\n"
    invalid = TARGET + " by\n  intro P h\n  exact P\n"
    wrong = "theorem qlean_other : 2 + 2 = 4 := by rfl\n"
    cases = [
        ("valid_bpe", valid, False, "OK"),
        ("invalid_proof", invalid, False, "ERR_TYPE_MISMATCH"),
        ("wrong_theorem", wrong, False, "ERR_GOAL_MISMATCH"),
        ("split_utf8", valid, True, "OK"),
    ]
    runs = []
    for name, source, split, want in cases:
        ids = encoded_source(text, source, split)
        runs.append(run_proof(session, ids, want, source.encode(), capture_map,
                              TRACES / (name + ".json"), torch, name))
    # No stale proof is authorized by a closing token alone.
    _, owned = session.consume_text([text.TCC])
    if owned is not None:
        raise RuntimeError("Unmatched closing token started another proof")
    valid_ids = encoded_source(text, valid, False)
    nested = [text.TCO, *valid_ids]
    payload = valid_ids[1:-1]
    overflow = [text.TCO, *payload, *([text.byte_token[32]] * (80 - len(payload))), text.TCC]
    long_id = next(i for i, token in enumerate(text.bytes) if len(token) > 16
                   and i not in text.tok.get_added_tokens_decoder())
    oversized = [*valid_ids[:-1], long_id, text.TCC]
    for name, ids, want in (
        ("nested_open", nested, "ERR_INPUT_TOO_LONG"), ("row_overflow", overflow, "ERR_INPUT_TOO_LONG"),
        ("oversized_token", oversized, "ERR_TRANSPORT"),
    ):
        runs.append(run_proof(session, ids, want, None, capture_map,
                              TRACES / (name + ".json"), torch, name))
    del session
    repeats = []
    for i in range(2):
        case = f"invalid_replay_{i + 1}"
        repeats.append(run_proof(fresh_stream(), encoded_source(text, invalid, False),
                                 "ERR_TYPE_MISMATCH", invalid.encode(), capture_map,
                                 TRACES / (case + ".json"), torch, case))
    if repeats[0]["stream_sha256"] != repeats[1]["stream_sha256"]:
        raise RuntimeError("Identical invalid-proof replays produced different token streams")
    runs.extend(repeats)
    after = tensor_fingerprints(model)
    modified = sorted(set(before) ^ set(after) | {k for k in before.keys() & after.keys()
                                                if before[k] != after[k]})
    if modified or {p.name: digest(p) for p in paths} != metadata["base_sha256"]:
        raise RuntimeError(f"Original learned tensors changed: {modified[:5]}")
    result = {
        "gpu": gpu, "total_vram_bytes": torch.cuda.get_device_properties(0).total_memory,
        "torch": str(torch.__version__), "transformers": transformers.__version__,
        "triton": triton.__version__, "checkpoint_tensor_count": original_tensors,
        "loaded_parameter_count": len(before), "modified_learned_tensors": len(modified),
        "checkpoint_shard_sha256": metadata["base_sha256"], "idle_parity": parity,
        "firmware_sha256": metadata["firmware_sha256"], "artifact_sha256": metadata["artifact_sha256"],
        "runs": runs,
    }
    (TRACES / "phase3-results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
