"""Consume a circuit-owned prefix and return the original text-cache frontier."""
import re

FIELD = rb'(?=[^"\n]{1,63}")((?:[\x20-\x21\x23-\x5b\x5d-\x7e]|\\x[0-9A-F]{2})+)'
VERDICT = re.compile(
    rb"QLEAN1 (?:(OK)|(ERR_[A-Z_]+) (0|[1-9][0-9]*|-)(?: expected=\""
    + FIELD + rb'" got="' + FIELD + rb'")?)\n'
)
MISMATCH = frozenset({b"ERR_TYPE_MISMATCH", b"ERR_GOAL_MISMATCH"})
TRACE_LIMIT = 500_000


def drive_owned(session, token, observe=None, *, bare_verdict=False):
    chip = session.chip
    spec, text = chip.spec, chip.text
    if token != spec.tok("GO"):
        raise RuntimeError("Expected a circuit-owned GO")
    stream, payload = [], []
    trace_count, echoed = 0, 0
    halted, echo_pending, logits = False, None, None
    echo_is_verdict = False

    while token is not None:
        if len(stream) >= TRACE_LIMIT:
            raise RuntimeError("P3 token limit reached")
        stream.append(token)
        if spec.is_text(token):
            if token - spec.TEXT_TOKEN != echo_pending:
                raise RuntimeError("Unexpected guest echo")
            echo_pending = None
            echoed += 1
            if bare_verdict and not echo_is_verdict:
                token = session.consume_capture([token - spec.TEXT_TOKEN])
            else:
                logits, token = session.consume_owned(token)
            if halted and token is not None:
                raise RuntimeError("Chip ownership persisted after the HALT newline")
            continue
        if echo_pending is not None or halted:
            raise RuntimeError("P3 omitted a required echo")
        trace_count += 1
        family, byte = spec.family(token)
        if family == "FLT":
            raise RuntimeError(f"RV32 fault: {spec.FAULTS[byte]}")
        if family == "BYTE":
            if not 0 <= byte < len(text.printable):
                raise RuntimeError("Invalid guest byte")
            payload.append(byte)
            echo_pending = text.printable[byte]
            echo_is_verdict = byte <= 255
        elif family == "HALT":
            halted, echo_pending = True, text.NL
            echo_is_verdict = False
        _, token = session.consume_owned(token)
        if observe is not None:
            observe(trace_count)

    if not halted or echo_pending is not None or payload[:1] != [256] or payload[-1:] != [257]:
        raise RuntimeError("Missing guest verdict frame or normal completion")
    if any(value > 255 for value in payload[1:-1]):
        raise RuntimeError("Unexpected control byte in guest verdict")
    verdict = bytes(payload[1:-1])
    parsed = VERDICT.fullmatch(verdict)
    if parsed is None or logits is None or (parsed[4] is not None and parsed[2] not in MISMATCH):
        raise RuntimeError("Malformed guest verdict or absent continuation")
    return logits, verdict, trace_count, echoed, stream


def guest_source(chip, capture_map):
    encoded_length = chip.guest_bytes(capture_map["source_length_address"], 2)
    captured_length = int.from_bytes(encoded_length, "little")
    if captured_length > capture_map["capacity"]:
        raise RuntimeError("Invalid guest capture length")
    return chip.guest_bytes(capture_map["source_address"], captured_length)
