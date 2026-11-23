"""Compile only QLean's additive P3 layers and immutable firmware boot tensors."""
import json
from pathlib import Path
import re
import types

from paths import BASE, BASE_REV, BUILD, CHIP, QWENPUTER, TARGET, add_upstream, configure, digest


def hardened_core(core):
    """Small, checked overlay of the pinned capture circuit."""
    source = Path(core.__file__).read_text()
    edits = (
        (
            '        caprow = {i: capt[i - 1] - (capt[i] if i < S.CAP_MAX else 0)\n'
            '                  for i in range(1, S.CAP_MAX + 1)}',
            '        caprow = {i: capt[i - 1] - (capt[i] if i < S.CAP_MAX else 0)\n'
            '                  for i in range(1, S.CAP_MAX + 1)}\n'
            '        opens = c.counter("qlean.opens", isGO, c.isTCO)\n'
            '        opened = c.thermo(opens, isGO, 2, "qlean.open")\n'
            '        nested = c.and_([c.isTCO, opened[1]], "qlean.nested")\n'
            '        qlean_start = c.and_([c.isTCC, opened[0]], "qlean.start")\n'
            '        caprow[S.CAP_MAX] += nested\n'
            '        cap_write = capw + nested',
        ),
        ('"beta": capw,', '"beta": cap_write,'),
        ('cases.append(([c.isTCC], "GO", 0))', 'cases.append(([qlean_start], "GO", 0))'),
        ('c.t_and([c.isTCC, one - running])', 'c.t_and([qlean_start, one - running])'),
    )
    for old, new in edits:
        if source.count(old) != 1:
            raise RuntimeError(f"Capture overlay no longer matches the pinned source: {old}")
        source = source.replace(old, new)
    module = types.ModuleType("qlean_hardened_core")
    exec(compile(source, core.__file__, "exec"), module.__dict__)
    return module


def feature_bank(circuit, core, spec, text):
    """Materialize the pinned token functions for both vocabularies."""
    import numpy as np
    import torch

    family = np.zeros(spec.VOCAB, dtype=np.uint8)
    payload = np.zeros(spec.VOCAB, dtype=np.int32)
    for name, (offset, count) in spec.FAMILIES.items():
        family[offset:offset + count] = core.FAM_ID[name]
        payload[offset:offset + count] = np.arange(count)
    for name, token in spec.CONTROLS.items():
        family[token] = core.FAM_ID[name]

    q_ids = np.array(text.printable, dtype=np.int32)
    q_code = np.arange(len(q_ids), dtype=np.int32)
    # The last row is the rejection sentinel for padded or out-of-vocabulary IDs.
    text_rows = np.frombuffer(b"".join(text.row_bytes(i) for i in range(text.n + 1)), np.uint8)
    text_bits = np.unpackbits(text_rows.reshape(-1, 16), axis=1, bitorder="little")
    cols = [d for d in circuit.token_fns if not circuit.dims[d].name.endswith("]")]
    bank = np.zeros((spec.VOCAB + text.n + 1, len(cols)), dtype=np.float32)
    chip, natural = bank[:spec.VOCAB], bank[spec.VOCAB:]

    for i, d in enumerate(cols):
        name = circuit.dims[d].name
        if name.startswith("code"):
            bit = int(name[4:])
            values = family if bit < core.NFAM else payload
            p = bit if bit < core.NFAM else bit - core.NFAM
            chip[:, i] = core.CODE_AMP * (2 * ((values.astype(np.int32) >> p) & 1) - 1)
            qval = core.FAM_ID["Q"] if bit < core.NFAM else q_code
            natural[q_ids, i] = core.CODE_AMP * (2 * ((qval >> p) & 1) - 1)
        elif name.startswith("tb"):
            byte, bit = (int(x) for x in re.fullmatch(r"tb(\d+)\.b(\d+)", name).groups())
            natural[:, i] = text_bits[:, 8 * byte + bit]
        elif name in ("isTCO", "isTCC"):
            natural[text.TCO if name == "isTCO" else text.TCC, i] = 1
        elif name == "is_text":
            natural[:, i] = 1
        elif name == "mu":
            chip[:, i] = 1
        elif name == "tau":
            chip[:, i], natural[:, i] = -1, core.TAU_TEXT
        elif name.startswith("digit=="):
            k = int(name.split("==")[1])
            chip[:, i] = (((family == core.FAM_ID["QS"]) & (payload == k))
                          | ((family == core.FAM_ID["QD"]) & ((payload >> 4) == k - 1)))
        elif name.startswith("is"):
            chip[:, i] = family == core.FAM_ID[name[2:]]
        else:
            label, bit = name.split(".b")
            chip[:, i] = np.where(family == core.FAM_ID[label], payload >> int(bit) & 1, 0)

    # Check the vectorized materialization against the genuine upstream token callbacks.
    rng = np.random.default_rng(507)
    samples = set(rng.integers(0, len(bank), 512).tolist())
    samples.update(spec.VOCAB + q for q in [text.TCO, text.TCC, *text.printable])
    samples.update(spec.CONTROLS.values())
    samples.add(len(bank) - 1)
    samples.update(i for start, length in spec.FAMILIES.values() for i in (start, start + length - 1))
    for row in samples:
        token = row if row < spec.VOCAB else spec.TEXT_TOKEN + row - spec.VOCAB
        expected = np.array([circuit.feature_value(d, token) for d in cols], dtype=np.float32)
        if not np.array_equal(bank[row], expected):
            raise RuntimeError(f"Compiled token features disagree for token {token}")
    return {"embed.data": torch.from_numpy(bank), "embed.cols": torch.tensor(cols)}


def pack_steps(ex):
    import torch

    state, steps, tables = {}, [], {}
    for i, step in enumerate(ex.steps):
        layout = {}
        head = 0
        for node in step.get("heads", ()):
            count = len(node.vheads())
            tables[node.name] = [i, head, count]
            head += count
        for key, value in step.items():
            if key in ("heads", "hist"):
                continue
            if isinstance(value, torch.Tensor):
                name = f"step.{i}.{key}"
                state[name] = value
                layout[key] = {"tensor": name}
            elif isinstance(value, list):
                names = [f"step.{i}.{key}.{j}" for j in range(len(value))]
                state.update(zip(names, value))
                layout[key] = {"tensors": names}
            else:
                layout[key] = value
        steps.append(layout)
    return state, steps, tables


def main():
    configure()
    add_upstream()
    from chipformer.rv import bridge, core, elf, ref, spec
    from chipformer.rv.tritonexec import Executor2
    from safetensors.torch import save_file

    tokenizer = BASE / "tokenizer.json"

    class ExactText(bridge.Text):
        def __init__(self, path):
            super().__init__(path)
            self.added = set(self.tok.get_added_tokens_decoder())
            self.rows = [self.row(i) for i in range(self.n)]

        def row(self, i):
            fragment = self.bytes[i]
            if i in self.added or not 1 <= len(fragment) <= spec.TEXT_ROW or b"\0" in fragment:
                fragment = b"\xff"
            return fragment.ljust(spec.TEXT_ROW, b"\0")

        def row_bytes(self, i):
            return self.rows[i] if 0 <= i < self.n else b"\xff" + bytes(spec.TEXT_ROW - 1)

    files = sorted(BASE.glob("*.safetensors"))
    if not files:
        raise RuntimeError("No pinned base checkpoint in /tmp/qlean")
    before = {p.name: digest(p) for p in files}
    text = ExactText(tokenizer)
    config = json.loads((BASE / "config.json").read_text())["text_config"]
    target = core.Target(config["linear_num_key_heads"], config["linear_num_value_heads"],
                         config["intermediate_size"])
    phase3 = hardened_core(core)
    circuit = phase3.build(target, text)
    firmware = BUILD / "qlean.elf"
    machine = ref.Machine.from_program(elf.program(firmware))
    bridge.park(machine, max_records=100)
    phase3.snapshot(circuit, machine)
    circuit.tables["qlean.opens"].init = [phase3.counter_rows(0)]
    executor = Executor2(circuit, device="cpu")
    executor.load_init()
    tensors, steps, tables = pack_steps(executor)
    tensors.update(feature_bank(circuit, core, spec, text))
    artifact = CHIP / "circuit.safetensors"
    temporary = artifact.with_suffix(".partial")
    save_file(tensors, temporary, metadata={"base": BASE_REV, "qwenputer": QWENPUTER})
    temporary.replace(artifact)
    after = {p.name: digest(p) for p in files}
    if before != after:
        raise RuntimeError("A learned-weight shard changed during chip compilation")
    metadata = {
        "qwenputer": QWENPUTER, "base": BASE_REV, "target": TARGET, "D": executor.D,
        "steps": steps, "tables": tables, "code": circuit.keep[:-2],
        "register_cols": [circuit.reg_cols[i] for i in range(32)],
        "static_ram_bytes": max(addr + len(data) - spec.DATA_BASE
                                for addr, data in elf.segments(firmware)[1] if addr < spec.SP_INIT),
        "base_sha256": before, "firmware_sha256": digest(firmware),
        "config_sha256": digest(BASE / "config.json"),
        "tokenizer_sha256": digest(tokenizer), "artifact_sha256": digest(artifact),
    }
    (CHIP / "manifest.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    print(f"Compiled {len(steps)} P3 sublayers. All {len(files)} original shards stayed bit-exact.",
          flush=True)


if __name__ == "__main__":
    main()
