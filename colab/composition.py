"""Original-width Qwen plus a compiled P3 chip in one decode stream."""
import torch


class Chip:
    def __init__(self, metadata, weights, text):
        from chipformer.dsl.graph import ONE
        from chipformer.q35.ir import A_BIT, HD
        from chipformer.rv import core, spec
        from chipformer.rv.tritonexec import Executor2

        self.core, self.spec, self.text, self.one = core, spec, text, ONE
        self.tables = metadata["tables"]
        ex = Executor2.__new__(Executor2)
        ex.D, ex.B, ex.dev = metadata["D"], 1, "cuda"
        ex.y = torch.zeros((1, ex.D), dtype=torch.float32, device="cuda")
        ex.steps = []
        self.boot = []
        for layout in metadata["steps"]:
            step = {k: self.materialize(v, weights) for k, v in layout.items()}
            if step["kind"] == "head":
                self.boot.append((step, step["S"]))
                step["S"] = step["S"].clone()
                step["hist"] = torch.zeros((1, 3, ex.D), dtype=torch.float32, device="cuda")
            ex.steps.append(step)
        self.executor = ex
        self.bank = weights["embed.data"]
        if self.bank.shape[0] != spec.VOCAB + text.n + 1:
            raise RuntimeError("Compiled token bank and tokenizer size disagree")
        self.cols = weights["embed.cols"]
        self.index = torch.zeros(1, dtype=torch.long, device="cuda")
        self.features = torch.zeros((1, self.bank.shape[1]), dtype=torch.float32, device="cuda")
        self.x = torch.zeros_like(ex.y)
        self.code_cols = torch.tensor(metadata["code"], device="cuda")
        self.code = torch.zeros(len(metadata["code"]), dtype=torch.float32, device="cuda")
        reg_step, reg_head, _ = self.tables["regs.rs1"]
        self.sp_row = ex.steps[reg_step]["S"][0, reg_head, 2]
        self.static_ram = metadata["static_ram_bytes"]
        coefficients = [0.0] * HD
        for bit, slots in enumerate(metadata["register_cols"]):
            for slot in slots:
                coefficients[slot] = 2.0**bit / A_BIT
        self.sp_weights = torch.tensor(coefficients, device="cuda")
        self.min_sp = torch.full((), float(spec.SP_INIT), device="cuda")
        self.max_sp = self.min_sp.clone()
        self.graph = torch.cuda.CUDAGraph()
        self.capture()

    @staticmethod
    def materialize(value, weights):
        if not isinstance(value, dict):
            return value
        if "tensor" in value:
            return weights[value["tensor"]]
        return [weights[name] for name in value["tensors"]]

    @torch.inference_mode()
    def body(self):
        torch.index_select(self.bank, 0, self.index, out=self.features)
        self.x.zero_()
        self.x[:, self.one].fill_(1)
        self.x.index_copy_(1, self.cols, self.features)
        self.executor.step(self.x)
        torch.index_select(self.x[0], 0, self.code_cols, out=self.code)
        sp = torch.dot(self.sp_row, self.sp_weights)
        torch.minimum(self.min_sp, sp, out=self.min_sp)
        torch.maximum(self.max_sp, sp, out=self.max_sp)

    @torch.inference_mode()
    def capture(self):
        self.index.fill_(self.spec.VOCAB + self.text.NL)
        stream = torch.cuda.Stream()
        stream.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(stream):
            for _ in range(3):
                self.body()
        torch.cuda.current_stream().wait_stream(stream)
        with torch.cuda.graph(self.graph):
            self.body()
        self.reset()

    @torch.inference_mode()
    def reset(self):
        self.executor.y.zero_()
        for step, boot in self.boot:
            step["S"].copy_(boot)
            step["hist"].zero_()

    @torch.inference_mode()
    def start_measurement(self):
        self.min_sp.fill_(self.spec.SP_INIT)
        self.max_sp.fill_(self.spec.SP_INIT)

    def guest_memory(self):
        low, high = int(self.min_sp.item()), int(self.max_sp.item())
        if not 0x7000 <= low <= high <= self.spec.SP_INIT:
            raise RuntimeError(f"Guest stack outside its partition: {low:#x} to {high:#x}")
        stack = self.spec.SP_INIT - low
        return {"guest_peak_stack_bytes": stack, "guest_peak_ram_bytes": self.static_ram + stack}

    @torch.inference_mode()
    def step(self, token):
        spec = self.spec
        if spec.is_text(token):
            qid = token - spec.TEXT_TOKEN
            row = spec.VOCAB + min(qid, self.text.n)
        elif 0 <= token < spec.VOCAB:
            row = token
        else:
            raise ValueError(f"Invalid P3 stream token {token}")
        self.index.fill_(row)
        self.graph.replay()
        code = self.code.tolist()
        if not any(code):
            return None
        if any(value not in (-self.core.KAPPA, self.core.KAPPA) for value in code):
            raise RuntimeError("P3 returned a malformed ownership code")
        nf = self.core.NFAM
        family = sum((bit > 0) << i for i, bit in enumerate(code[:nf]))
        payload = sum((bit > 0) << i for i, bit in enumerate(code[nf:]))
        token = self.core.decode_code(family, payload, self.text)
        if token < 0:
            raise RuntimeError("P3 predicted an invalid token")
        return token

    def guest_bytes(self, address, length):
        """Read back the actual C input buffer from P3's committed RAM heads."""
        from chipformer.q35.ir import A_BIT

        if not 0 <= address <= address + length <= 0x8000:
            raise ValueError("RAM readback range")
        result = bytearray()
        for word in range(address // 4, (address + length + 3) // 4):
            table = word & 15 | ((word >> 12) << 4)
            step_no, first, count = self.tables[f"ram{table}"]
            if count != 2:
                raise RuntimeError("P3 RAM table ABI changed")
            head = first + ((word >> 4) & 1)
            row = (word >> 5) & 127
            # SW and the byte/halfword store path use separate column ranges.
            slots = self.executor.steps[step_no]["S"][0, head, row]
            bits = (slots[2:34] + slots[34:66]).tolist()
            if any(bit not in (0.0, A_BIT) for bit in bits):
                raise RuntimeError("Invalid P3 RAM bit")
            value = sum((bit == A_BIT) << i for i, bit in enumerate(bits))
            result.extend(value.to_bytes(4, "little"))
        start = address % 4
        return bytes(result[start:start + length])


class StockStream:
    def __init__(self, model):
        self.model = model
        self.cache = None

    @torch.inference_mode()
    def consume(self, ids):
        batch = torch.tensor([ids], dtype=torch.long, device="cuda")
        out = self.model(input_ids=batch, past_key_values=self.cache, use_cache=True)
        self.cache = out.past_key_values
        return out.logits


class Composition:
    """Text tokens reach both streams. Only the chip sees internal RV tokens."""

    def __init__(self, model, chip):
        self.qwen = StockStream(model)
        self.chip = chip

    def prefill(self, ids):
        # Historical prompts cannot arm the bridge.
        return self.qwen.consume(ids)

    def consume_capture(self, ids):
        """Advance the chip on transport tokens and report any ownership change."""
        choice = None
        for ident in ids:
            if choice is not None:
                raise RuntimeError("Text input cannot override an owned chip position")
            choice = self.chip.step(self.chip.spec.TEXT_TOKEN + ident)
        return choice

    def consume_text(self, ids):
        choice = self.consume_capture(ids)
        logits = self.qwen.consume(ids)
        return logits, choice

    def consume_chip(self, token):
        return self.consume_owned(token)[1]

    def consume_owned(self, token):
        if self.chip.spec.is_text(token):
            return self.consume_text([token - self.chip.spec.TEXT_TOKEN])
        return None, self.chip.step(token)
