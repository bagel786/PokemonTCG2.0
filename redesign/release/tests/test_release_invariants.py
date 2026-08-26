"""Independent invariants shipped with the public evidence package."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CODE_ROOT = ROOT / "code" if (ROOT / "code/benchmark").exists() else ROOT
sys.path.insert(0, str(CODE_ROOT))

from benchmark.classifier import build_bundle, classify_branch  # noqa: E402
from benchmark.rng_manager import EventKeyedRNG  # noqa: E402


class Artifact:
    system = "fixture"
    adapter_version = "1"
    adapter_hash = "abc"
    declared_seed = 42
    effective_seed = 42

    def __init__(self, digest: str = "same", draw_log=None):
        self._digest = digest
        self.draw_log = [] if draw_log is None else draw_log

    def projection_digest(self):
        return self._digest


def wilson_fixture(x: int, n: int, z: float = 1.959964):
    p = x / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return p, center - half, center + half


class ReleaseInvariantTests(unittest.TestCase):
    def test_wilson_toy_equation(self):
        estimate, low, high = wilson_fixture(38, 40)
        self.assertEqual(round(estimate, 3), 0.950)
        self.assertEqual(round(low, 3), 0.835)
        self.assertEqual(round(high, 3), 0.986)

    def test_event_keyed_draw_is_order_invariant(self):
        first = EventKeyedRNG("stream")
        a = first.draw("event-a")
        b = first.draw("event-b")
        second = EventKeyedRNG("stream")
        self.assertEqual(second.draw("event-b"), b)
        self.assertEqual(second.draw("event-a"), a)

    def test_classifier_fail_closed_without_replay_evidence(self):
        bundle = build_bundle(
            {"row_id": "fixture", "seed": 42, "condition_a": "A",
             "condition_b": "B", "coupling_type": None},
            Artifact(), Artifact(),
        )
        self.assertEqual(classify_branch(bundle, "BRANCH_C"), "FAIL_CLOSED")

    def test_classifier_inputs_exclude_outcomes(self):
        bundle = build_bundle(
            {"row_id": "fixture", "seed": 42, "condition_a": "A",
             "condition_b": "B", "coupling_type": None},
            Artifact(), Artifact(),
        )
        forbidden = {"outcome", "payoff", "effect", "p_value", "result"}
        self.assertTrue(forbidden.isdisjoint(bundle))
        source = inspect.getsource(classify_branch).lower()
        self.assertNotIn("p_value", source)

    def test_raw_snapshot_hash_and_counts(self):
        candidates = [
            ROOT / "results/final/raw/decisions_and_pairs.jsonl",
            ROOT / "data/raw/decisions_and_pairs.jsonl",
        ]
        raw = next(path for path in candidates if path.exists())
        digest = hashlib.sha256(raw.read_bytes()).hexdigest()
        decisions = pairs = 0
        with raw.open() as stream:
            for line in stream:
                level = json.loads(line)["level"]
                decisions += level == "decision"
                pairs += level == "outcome_pair"
        self.assertEqual(digest, "ead6dd392c61767c914f9bb1956b7a82213c5889f3e95faf15c4a3f3ec5d2540")
        self.assertEqual((decisions, pairs), (34160, 854))


if __name__ == "__main__":
    unittest.main()
