"""Search a bounded set of unhinted runs and publish only a verified semantic repair."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from qlean import Display, generate, load_overlay, load_runtime
from paths import BASE, ROOT

TARGETS = {
    "nat-hypothesis": "theorem qlean_target (n : Nat) (h : n = 7) : n + 0 = 7 :=",
    "projection": "theorem qlean_target : ∀ P Q : Prop, P → Q → P :=",
    "composition": "theorem qlean_target : ∀ P Q R : Prop, (P → Q) → (Q → R) → P → R :=",
}
TERM_TARGETS = {**TARGETS,
                "premise-selection": "theorem qlean_target (P Q : Prop) (hP : Q) (hQ : P) : P :="}
TERM_ORDER = ("nat-hypothesis", "premise-selection", "composition")
PROMPT = ("Prove the stated theorem in the documented QLean subset. Prefer a short proof. "
          "Use a Lean term, or write by and put the supported tactics on separate "
          "lines indented by two spaces. Submit only the proof body within the requested framing.")
TERM_PROMPT = ("Submit a single Lean expression for the stated goal. Omit tactic blocks, "
               "library lemmas, dotted names, and explanations. Use only the documented term "
               "forms such as a bound name, function application, fun, or rfl.")
SETTINGS = ((0.55, 0, True), (0.7, 4, False), (0.8, 11, True))
TERM_SETTINGS = ((0.4, 2, False), (0.8, 8, False), (0.9, 19, False))


def variant(name):
    directory = ROOT / "phase4/variants" / name
    if not (directory / "chip/manifest.json").is_file():
        env = {**os.environ, "QLEAN_VARIANT": name, "QLEAN_TARGET": TERM_TARGETS[name]}
        for args in (("colab/setup.py", "--firmware-only"), ("colab/compile.py",)):
            subprocess.run([sys.executable, "-B", *args], cwd=SOURCE, env=env, check=True)
    chip, manifest, capture = load_overlay(BASE, directory / "chip", directory / "firmware/capture.json")
    if manifest["target"] != TERM_TARGETS[name]:
        raise RuntimeError("Compiled overlay targets a different theorem")
    return chip, manifest, capture


def search(out, *, terms_only=False):
    torch, model, tokenizer, _, _, _ = load_runtime()
    search_log = out / "repair-search.json"
    summary = json.loads(search_log.read_text()) if terms_only and search_log.exists() else []
    phases = [(True, TERM_PROMPT, TERM_SETTINGS, 180, TERM_ORDER)]
    if not terms_only:
        phases[:0] = [(mode, PROMPT, SETTINGS, 1100, TARGETS) for mode in (False, True)]
    for structured, prompt, settings, max_tokens, names in phases:
        for name in names:
            runtime = torch, model, tokenizer, *variant(name)
            for temperature, seed, thinking in settings:
                args = SimpleNamespace(temperature=temperature, seed=seed, thinking=thinking,
                                       structured=structured, max_attempts=2, max_tokens=max_tokens,
                                       prompt=prompt, started_marker=None)
                data = {"attempts": [], "generated_ids": [], "protocol_events": [], "variant": name}
                print(f"Repair trial {name}, seed {seed}, structured={structured}", flush=True)
                generate(args, Display(quiet=True), data, runtime)
                summary.append({"variant": name, "structured": structured, "seed": seed,
                                "term_only": prompt == TERM_PROMPT, "outcome": data["outcome"],
                                "attempts": data["attempts"]})
                search_log.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
                verdicts = [attempt["verdict"] for attempt in data["attempts"]]
                print(verdicts, flush=True)
                if (len(verdicts) == 2 and verdicts[0].startswith("QLEAN1 ERR_TYPE_MISMATCH ")
                        and ' expected="' in verdicts[0] and verdicts[1] == "QLEAN1 OK"):
                    transcript = out / "self-correction.json"
                    transcript.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
                    lean = ROOT / "phase4/tools/lean-4.36.0-linux/bin/lean"
                    subprocess.run([sys.executable, "-B", str(SOURCE / "demos/check_repair.py"),
                                    str(transcript), str(lean)], check=True)
                    print(data["terminal"], flush=True)
                    return 0
            del runtime
    print("The selected trials did not demonstrate a two-attempt semantic repair", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(search(Path(sys.argv[1]), terms_only="--terms-only" in sys.argv[2:]))
