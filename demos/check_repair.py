"""Verify the unhinted handoff and cross-check the accepted source with Lean."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def check_handoff(data):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "colab"))
    from paths import BASE, add_upstream

    add_upstream()
    from chipformer.rv.bridge import Text

    text = Text(BASE / "tokenizer.json")
    first, second = data["attempts"]
    assert first["verdict"].startswith("QLEAN1 ERR_") and second["verdict"] == "QLEAN1 OK"
    assert first["model_tokens"] < second["model_tokens"]
    for attempt in (first, second):
        echo = f'<tool_response>{attempt["verdict"]}\n</tool_response>\n'
        assert text.decode_bytes(attempt["guest_echo_ids"]) == echo.encode()
        assert attempt["guest_echo_text"] == echo
        if not data["structured"]:
            bare = attempt["verdict"] + "\n"
            assert text.decode_bytes(attempt["model_echo_ids"]).decode() == bare
            assert attempt["model_echo_text"] == bare

    events = data["protocol_events"]
    for event in events:
        assert text.decode_bytes(event["token_ids"]).decode("utf-8", errors="backslashreplace") == event["text"]
        if event["reason"] == "keep mixed separator token in Qwen":
            sampled_index = event["after_sampled_tokens"] - 1
            assert event["token_ids"] == [data["generated_ids"][sampled_index]]
    model_control = [event for event in events
                     if first["model_tokens"] <= event["after_sampled_tokens"] < second["model_tokens"]
                     and event["route"] != "guest"
                     and event["reason"] != "keep mixed separator token in Qwen"]
    expected_role = "<|im_end|>\n<|im_start|>user\n"
    if data["structured"]:
        assistant = "<|im_end|>\n<|im_start|>assistant\n"
        assistant += "<think>\n" if data["thinking"] else "<think>\n\n</think>\n\n"
        assert len(model_control) == 2 and all(event["route"] == "model" for event in model_control)
        assert model_control[0]["text"] == expected_role
        assert model_control[1]["text"] == "\nTry again." + assistant
    else:
        assert not model_control
    assert all(event["after_sampled_tokens"] == first["model_tokens"] for event in model_control)

    # Check that the guest received the fixed declaration and the sampled body bytes.
    start, end = second["sampled_proof_span"]
    assert first["model_tokens"] <= start < end <= second["model_tokens"]
    body = text.decode_bytes(data["generated_ids"][start:end]).lstrip(b" \t\r\n")
    assert second["source"].encode() == data["target"].encode() + b" " + body
    return body.decode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("lean", type=Path)
    args = parser.parse_args()
    data = json.loads(args.transcript.read_text())
    attempts = data["attempts"]
    assert data["outcome"] == "verified" and len(attempts) == 2, "No second-attempt repair"
    body = check_handoff(data)
    version = subprocess.check_output([args.lean, "--version"], text=True, timeout=30).strip()
    assert "version 4.36.0," in version and "commit 611c117bfaf7b7ae1cfcf246ce6fba31e8f509e9," in version
    source = args.transcript.with_name("accepted-proof.lean")
    source.write_bytes(attempts[-1]["source"].encode("utf-8"))
    completed = subprocess.run([args.lean, source], capture_output=True, text=True, timeout=60)
    if completed.returncode:
        raise RuntimeError(f"Lean rejected the exact source: {completed.stdout}{completed.stderr}")
    probe = source.with_name("axiom-probe.lean")
    try:
        probe.write_bytes(source.read_bytes() + b"\n#print axioms qlean_target\n")
        check = subprocess.run([args.lean, probe], capture_output=True, text=True, timeout=60, check=True)
        assert "'qlean_target' does not depend on any axioms" in check.stdout
    finally:
        probe.unlink(missing_ok=True)
    retry = ("framed guest verdict, generic Try again. header, and chat role delimiters"
             if data["structured"] else "bare guest verdict")
    diagnostics = (completed.stdout + completed.stderr).replace(str(source), source.name)
    report = {"version": version, "source": source.name, "compile_exit": 0, "axioms": [],
              "lean_diagnostics": diagnostics,
              "retry": retry, "sampled_proof_body": body}
    source.with_name("lean-validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"{version}\nAccepted proof compiled. Zero axiom dependencies.", flush=True)


if __name__ == "__main__":
    main()
