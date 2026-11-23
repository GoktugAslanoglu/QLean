#!/usr/bin/env python3
"""Stream a Qwen proof and the in-weights verifier on one text cache."""
import argparse
import codecs
import hashlib
import json
import os
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / "colab"))

PROTOCOL = """You are proving one fixed theorem in Lean 4 with QLean.
A candidate is the Lean proof body that follows := in the theorem below. Write only its body.
Avoid code fences and additional declarations.
A QLEAN1 error is a request to revise the proof in this same turn.
Do not use sorry, admit, imports, or other declarations.
Supported forms include one-line terms, by rfl, by exact TERM, and multiline by
with two-space-indented intro/apply/exact/rfl tactics, one per line.
For equality transport use @Eq.subst A M a b h ha, where h : a = b and ha : M a.
Its result has type M b. Use typed parentheses in a motive.
"""
RETRY_HEADER = "\nTry again.<|im_end|>\n<|im_start|>assistant\n"


class Display:
    def __init__(self, quiet=False):
        self.quiet = quiet
        self.last = 0.0
        self.line_width = 0
        self.tty = sys.stdout.isatty()

    def text(self, value):
        if not self.quiet:
            print("".join(c for c in value if c in "\n\t" or c.isprintable()),
                  end="", flush=True)

    def status(self, tokens, seconds, ram=None, verdict="Checking…", final=False):
        if self.quiet or (not self.tty and not final):
            return
        now = time.perf_counter()
        if not final and now - self.last < 0.2:
            return
        memory = f" | {ram / 1024:.1f} KiB RAM" if ram is not None else ""
        line = f"[In-Weights Kernel | {tokens:,} trace tokens | {seconds:.1f}s{memory} | {verdict}]"
        if final:
            if self.tty:
                print("\r" + line.ljust(self.line_width), flush=True)
            else:
                print(line, flush=True)
            self.line_width = 0
        else:
            print("\r" + line.ljust(self.line_width), end="", flush=True)
            self.line_width = len(line)
        self.last = now


def load_overlay(base, directory, capture_path):
    from paths import BASE_REV, QWENPUTER, digest
    from safetensors.torch import load_file
    from chipformer.rv.bridge import Text
    from composition import Chip

    manifest = json.loads((directory / "manifest.json").read_text())
    artifact = directory / "circuit.safetensors"
    capture = json.loads(capture_path.read_text())
    if (manifest["qwenputer"], manifest["base"]) != (QWENPUTER, BASE_REV):
        raise RuntimeError("Compiled model pin mismatch")
    if capture["firmware_sha256"] != manifest["firmware_sha256"]:
        raise RuntimeError("Guest capture symbol does not match firmware")
    for path, expected in ((artifact, manifest["artifact_sha256"]),
                           (base / "config.json", manifest["config_sha256"]),
                           (base / "tokenizer.json", manifest["tokenizer_sha256"])):
        if digest(path) != expected:
            raise RuntimeError(f"Artifact digest mismatch: {path.name}")
    chip = Chip(manifest, load_file(artifact, device="cuda"), Text(base / "tokenizer.json"))
    return chip, manifest, capture


def load_runtime():
    from paths import BASE, BUILD, CHIP, add_upstream, configure, digest

    configure()
    add_upstream()
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    import torch
    from transformers import AutoTokenizer, Qwen3_5ForConditionalGeneration

    manifest = json.loads((CHIP / "manifest.json").read_text())
    if {p.name: digest(p) for p in BASE.glob("*.safetensors")} != manifest["base_sha256"]:
        raise RuntimeError("Pinned checkpoint shard digest mismatch")

    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    model = Qwen3_5ForConditionalGeneration.from_pretrained(
        BASE, dtype="auto", device_map={"": "cuda"}, local_files_only=True,
        attn_implementation="eager",
    ).eval()
    if model.config.text_config.hidden_size != 2560:
        raise RuntimeError("Unexpected original Qwen residual width")
    tokenizer = AutoTokenizer.from_pretrained(BASE, local_files_only=True)
    chip, manifest, capture = load_overlay(BASE, CHIP, BUILD / "capture.json")
    return torch, model, tokenizer, chip, manifest, capture


def generate(args, display, transcript, runtime):
    from composition import Composition
    from owned import drive_owned, guest_source

    torch, model, tokenizer, chip, manifest, capture = runtime
    chip.reset()
    session = Composition(model, chip)
    frame_protocol = (
        "The verifier's transport adds framing. Omit tool tags from your answer.\n"
        if args.structured else
        "Open each candidate with <tool_call> and end it with </tool_call>. "
        "When a QLEAN1 error line appears, continue immediately with a new proof in its own frame.\n"
        "The transport fills in the fixed theorem header after you open the frame.\n"
    )
    instruction = (PROTOCOL + frame_protocol + f"Attempt budget: {args.max_attempts}.\n"
                   + f"Exact theorem header:\n{manifest['target']}\n")
    messages = [{"role": "system", "content": instruction},
                {"role": "user", "content": args.prompt}]
    prompt_ids = tokenizer.apply_chat_template(
        messages, tokenize=True, return_dict=False, add_generation_prompt=True,
        enable_thinking=args.thinking,
    )
    logits = session.prefill(prompt_ids)
    eos = model.generation_config.eos_token_id
    stops = {eos} if isinstance(eos, int) else set(eos or ())
    for spelling in ("<|im_end|>", "<|endoftext|>"):
        eos_id = chip.text.tok.token_to_id(spelling)
        if eos_id is not None:
            stops.add(eos_id)
    think_end = chip.text.tok.token_to_id("</think>")
    generator = torch.Generator(device="cuda").manual_seed(args.seed)
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    attempts = transcript["attempts"]
    transcript.update(target=manifest["target"], artifact_sha256=manifest["artifact_sha256"],
                      seed=args.seed, temperature=args.temperature, prompt=args.prompt,
                      thinking=args.thinking, max_attempts=args.max_attempts,
                      max_tokens=args.max_tokens, structured=args.structured,
                      initial_messages=messages)
    prefix = "QLEAN1\n" + manifest["target"] + " "
    prefix_ids = chip.text.encode(prefix)
    if chip.text.decode_bytes(prefix_ids) != prefix.encode() or len(prefix_ids) >= 79:
        raise RuntimeError("The ROM-bound header does not fit the capture protocol")
    displayed = []
    transcript["terminal"] = ""
    in_frame = False
    body_start = 0
    body_tokens = 0
    waiting_for_reasoning = args.structured and args.thinking

    def show(ids):
        raw = b"".join(chip.text.bytes[t] for t in ids if t < chip.text.n)
        fragment = decoder.decode(raw)
        if fragment:
            displayed.append(fragment)
            display.text(fragment)

    def control(ids, reason, *, visible=True, route="both"):
        transcript["protocol_events"].append({
            "after_sampled_tokens": len(transcript["generated_ids"]),
            "reason": reason, "token_ids": ids, "route": route,
            "text": chip.text.decode_bytes(ids).decode("utf-8", errors="backslashreplace"),
        })
        if visible:
            show(ids)
        if route == "guest":
            output, owned = None, session.consume_capture(ids)
        elif route == "model":
            output, owned = session.qwen.consume(ids), None
        else:
            output, owned = session.consume_text(ids)
        if owned is not None and reason != "close at model end":
            raise RuntimeError("Unexpected ownership while opening the proof frame")
        return output, owned

    def open_frame():
        nonlocal in_frame, body_tokens, body_start
        in_frame, body_tokens = True, 0
        body_start = len(transcript["generated_ids"]) - 1
        control([chip.text.TCO, *prefix_ids], "open and fill fixed header", route="guest")

    if args.started_marker:
        args.started_marker.write_text(str(time.time_ns()) + "\n")
    for _ in range(args.max_tokens):
        last = logits[0, -1]
        if args.temperature:
            top, candidates = torch.topk(last.float(), 40)
            pos = torch.multinomial((top / args.temperature).softmax(0), 1, generator=generator)
            token = int(candidates[pos])
        else:
            token = int(last.argmax())
        transcript["generated_ids"].append(token)
        if token in stops:
            if not in_frame:
                transcript["outcome"] = "end_of_generation"
                break
            _, owned = control([chip.text.TCC], "close at model end", route="guest")
        else:
            payload = None
            starting_body = args.structured and not waiting_for_reasoning and not in_frame
            bare_separator = not args.structured and in_frame and body_tokens == 0
            if (starting_body or bare_separator) and token not in (chip.text.TCO, chip.text.TCC):
                raw = chip.text.bytes[token] if token < chip.text.n else b""
                body = raw.lstrip(b" \t\r\n")
                if raw and not body:
                    # Qwen emits a chat separator after </think> before its answer.
                    show([token])
                    logits = session.qwen.consume([token])
                    if bare_separator:
                        body_start = len(transcript["generated_ids"])
                    continue
                if starting_body:
                    open_frame()
                if body != raw:
                    payload = [chip.text.byte_token[byte] for byte in body]
            show([token])
            if payload is None:
                logits, owned = session.consume_text([token])
            else:
                logits = session.qwen.consume([token])
                _, owned = control(payload, "capture proof suffix losslessly", visible=False, route="guest")
            if token == chip.text.TCO and not in_frame:
                waiting_for_reasoning = False
                in_frame, body_tokens = True, 0
                body_start = len(transcript["generated_ids"])
                control(prefix_ids, "fill fixed header", route="guest")
            elif waiting_for_reasoning and token == think_end:
                waiting_for_reasoning = False
            elif in_frame and token != chip.text.TCC:
                body_tokens += len(payload) if payload is not None else 1
                if body_tokens + len(prefix_ids) >= 80:
                    _, owned = control([chip.text.TCC], "close at model end", route="guest")
        if owned is None:
            continue
        in_frame = False

        if args.structured:
            role = chip.text.encode("<|im_end|>\n<|im_start|>user\n")
            control(role, "open the guest response role", visible=False, route="model")
        start = time.perf_counter()
        chip.start_measurement()
        if not display.quiet:
            print(flush=True)
        last_sample = 0.0

        def progress(count):
            nonlocal last_sample
            if display.tty and not display.quiet and count % 128 == 1:
                elapsed = time.perf_counter() - start
                if elapsed - last_sample >= 0.2:
                    ram = chip.guest_memory()["guest_peak_ram_bytes"]
                    display.status(count, elapsed, ram)
                    last_sample = elapsed

        logits, verdict, count, echoed, stream = drive_owned(
            session, owned, progress, bare_verdict=not args.structured,
        )
        torch.cuda.synchronize()
        elapsed = time.perf_counter() - start
        memory = chip.guest_memory()
        value = verdict.decode().strip()
        source = guest_source(chip, capture)
        body_end = len(transcript["generated_ids"]) - (token in stops or token == chip.text.TCC)
        echo_ids = [item - chip.spec.TEXT_TOKEN for item in stream if chip.spec.is_text(item)]
        model_echo_ids = echo_ids if args.structured else echo_ids[1:-2]
        model_echo_text = chip.text.decode_bytes(model_echo_ids).decode("utf-8")
        if not args.structured and model_echo_text.encode() != verdict:
            raise RuntimeError("Language cache echo differs from the bare guest verdict")
        attempt = dict(number=len(attempts) + 1, verdict=value,
                       source=source.decode("utf-8", errors="replace"), chip_trace_tokens=count,
                       echoed_text_tokens=echoed, wall_seconds=elapsed,
                       stream_sha256=hashlib.sha256(json.dumps(stream).encode()).hexdigest(),
                       model_tokens=len(transcript["generated_ids"]),
                       sampled_proof_span=[body_start, body_end],
                       guest_echo_ids=echo_ids,
                       guest_echo_text=chip.text.decode_bytes(echo_ids).decode("utf-8"),
                       model_echo_ids=model_echo_ids, model_echo_text=model_echo_text, **memory)
        if attempt["source"].encode("utf-8") != source:
            if value == "QLEAN1 OK":
                raise RuntimeError("Certified source was not valid UTF-8")
            attempt["source_hex"] = source.hex()
        attempts.append(attempt)
        displayed.append(
            f"\n[In-Weights Kernel | {count:,} trace tokens | {elapsed:.1f}s | "
            f"{memory['guest_peak_ram_bytes'] / 1024:.1f} KiB RAM | {value}]\n"
        )
        display.status(count, elapsed, memory["guest_peak_ram_bytes"], value, final=True)
        if value == "QLEAN1 OK":
            if not source:
                raise RuntimeError("Certified verdict omitted the guest source")
            transcript["outcome"] = "verified"
            break
        if len(attempts) == args.max_attempts:
            transcript["outcome"] = "attempt_limit"
            break
        if args.structured:
            # The genuine guest echo is already in the original text cache.
            header = RETRY_HEADER + ("<think>\n" if args.thinking else "<think>\n\n</think>\n\n")
            logits, _ = control(chip.text.encode(header), "generic retry header", visible=False, route="model")
            waiting_for_reasoning = args.thinking
    else:
        transcript["outcome"] = "token_limit"
    tail = decoder.decode(b"", final=True)
    displayed.append(tail)
    display.text(tail)
    transcript["terminal"] = "".join(displayed)
    if not display.quiet and not transcript["terminal"].endswith("\n"):
        print()
    return transcript["outcome"] == "verified"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", help="Instruction for the ROM-bound goal")
    parser.add_argument("--variant", default="", help="Select a separately compiled goal")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=640)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--thinking", action="store_true")
    parser.add_argument("--structured", action=argparse.BooleanOptionalAction, default=True,
                        help="Supply the proof frame and retry cue (default: enabled)")
    parser.add_argument("--transcript", type=Path, help="Write a JSON transcript")
    parser.add_argument("--json", action="store_true", help="Emit JSON on stdout")
    parser.add_argument("--started-marker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.max_attempts < 1 or args.max_tokens < 1 or not 0.0 <= args.temperature <= 2.0:
        parser.error("Provide positive budgets and a temperature between 0 and 2")
    os.environ["QLEAN_VARIANT"] = args.variant
    transcript = {"attempts": [], "generated_ids": [], "protocol_events": []}
    accepted = False
    try:
        runtime = load_runtime()
        accepted = generate(args, Display(args.json), transcript, runtime)
    finally:
        body = json.dumps(transcript, ensure_ascii=False, indent=2) + "\n"
        if args.transcript:
            args.transcript.parent.mkdir(parents=True, exist_ok=True)
            args.transcript.write_text(body, encoding="utf-8")
        if args.json:
            print(body, end="")
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
