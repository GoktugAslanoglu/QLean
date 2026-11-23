"""Regression tests for the ownership handoff, without a checkpoint."""
from collections import deque
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "colab"))
from owned import drive_owned


class FakeSession:
    def __init__(self, tokens):
        self.tokens = deque(tokens)
        self.consumed = []
        self.hidden = []
        # Real text tokens are ints. Use a tuple only for chip records here.
        spec = SimpleNamespace(
            tok=lambda family: (family, 0), is_text=lambda token: isinstance(token, int),
            TEXT_TOKEN=0, family=lambda token: token, FAULTS=["test fault"],
        )
        self.chip = SimpleNamespace(spec=spec, text=SimpleNamespace(printable=list(range(258)), NL=10))
        self.frontier = object()

    def consume_owned(self, token):
        self.consumed.append(token)
        logit = self.frontier if token == 10 else None
        return logit, self.tokens.popleft() if self.tokens else None

    def consume_capture(self, ids):
        self.hidden.extend(ids)
        return self.tokens.popleft() if self.tokens else None


def frame(line):
    tokens = []
    for byte in [256, *line, 257]:
        tokens.extend([("BYTE", byte), byte])
    return tokens + [("HALT", 0), 10]


class HandoffTest(unittest.TestCase):
    def test_final_echo_supplies_frontier(self):
        wire = frame(b"QLEAN1 ERR_TYPE_MISMATCH 59\n")
        session = FakeSession(wire)
        logits, verdict, count, _, stream = drive_owned(session, ("GO", 0))
        self.assertIs(logits, session.frontier)
        self.assertEqual(verdict, b"QLEAN1 ERR_TYPE_MISMATCH 59\n")
        self.assertEqual(count, sum(isinstance(token, tuple) for token in stream))
        self.assertEqual(session.consumed, [("GO", 0), *wire])

    def test_bad_echo_fails_closed(self):
        wire = frame(b"QLEAN1 OK\n")
        wire[1] = 10
        with self.assertRaisesRegex(RuntimeError, "Unexpected guest echo"):
            drive_owned(FakeSession(wire), ("GO", 0))

    def test_mismatch_details_reach_the_language_cache(self):
        line = b'QLEAN1 ERR_GOAL_MISMATCH 21 expected="\\xE2\\x88\\x80" got="Nat"\n'
        wire = frame(line)
        session = FakeSession(wire)
        logits, verdict, _, _, _ = drive_owned(session, ("GO", 0))
        self.assertIs(logits, session.frontier)
        self.assertEqual(verdict, line)
        self.assertEqual(session.consumed, [("GO", 0), *wire])

    def test_bare_verdict_uses_its_lf_logits_and_hides_only_transport(self):
        line = b'QLEAN1 ERR_TYPE_MISMATCH 1 expected="P" got="Q"\n'
        session = FakeSession(frame(line))
        logits, verdict, _, _, _ = drive_owned(session, ("GO", 0), bare_verdict=True)
        self.assertIs(logits, session.frontier)
        self.assertEqual(verdict, line)
        self.assertEqual(session.hidden, [256, 257, 10])
        self.assertEqual(bytes(x for x in session.consumed if isinstance(x, int)), line)

    def test_noncanonical_verdict_fails_closed(self):
        for line in (
            b"QLEAN1 OK 0\n",
            b'QLEAN1 ERR_SYNTAX 0 expected="Nat" got="Prop"\n',
            b'QLEAN1 ERR_TYPE_MISMATCH 0 expected="Nat" got="bad\\escape"\n',
            b'QLEAN1 ERR_TYPE_MISMATCH 0 expected="' + b"a" * 64 + b'" got="Prop"\n',
        ):
            with self.subTest(line=line), self.assertRaisesRegex(RuntimeError, "Malformed guest verdict"):
                drive_owned(FakeSession(frame(line)), ("GO", 0))


if __name__ == "__main__":
    unittest.main()
