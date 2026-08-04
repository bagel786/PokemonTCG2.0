import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))

try:
    import torch
except ImportError:  # pragma: no cover
    torch = None

from ptcg_ai.features import DecisionFeatures, OptionFeatures, V2_GLOBAL_SIZE


@unittest.skipIf(torch is None, "training dependencies are not installed")
class ReplayRefreshTests(unittest.TestCase):
    def row(self, episode, team="team", seat=0, step=1, action=None):
        features = DecisionFeatures(
            [0.0] * V2_GLOBAL_SIZE,
            [1],
            [
                OptionFeatures(3, 0, 0, 0, 0, 0, 0, [0.0] * 12),
                OptionFeatures(3, 0, 1, 0, 0, 0, 0, [0.0] * 12),
            ],
            2,
        )
        features.global_features[28] = 1 / 9
        features.global_features[29] = 1 / 9
        return {
            "episode_id": episode,
            "team": team,
            "seat": seat,
            "step": step,
            "deck": [648],
            "features": features.to_json(),
            "action": [0] if action is None else action,
            "reward": 1,
        }

    @staticmethod
    def write_rows(path, rows):
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")

    def test_manifest_is_deterministic_disjoint_and_deduplicated(self):
        from training.replay_refresh import build_split_manifest, classify_fresh_row

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            temporal = root / "temporal"
            temporal.mkdir()
            (temporal / "temporal-1.json").write_text("{}")
            heldout_team = next(f"held-{i}" for i in range(100) if __import__("zlib").crc32(f"held-{i}".encode()) % 10 == 0)
            rows = [
                self.row("temporal-1"),
                self.row("held-episode", heldout_team),
                self.row("train-episode"),
                self.row("train-episode"),
            ]
            fresh = root / "fresh.gz"
            rehearsal = root / "old.gz"
            self.write_rows(fresh, rows)
            self.write_rows(rehearsal, [self.row("old", heldout_team), self.row("old-ok")])
            first = build_split_manifest(fresh, rehearsal, temporal)
            second = build_split_manifest(fresh, rehearsal, temporal)
            self.assertEqual(first, second)
            self.assertEqual(first["duplicate_rows_skipped"]["fresh"], 1)
            self.assertEqual(first["counts"]["temporal"], 1)
            self.assertEqual(first["counts"]["team_holdout"], 1)
            self.assertEqual(first["counts"]["rehearsal_heldout_excluded"], 1)
            self.assertEqual(classify_fresh_row(rows[0], first), "temporal")
            self.assertEqual(classify_fresh_row(rows[1], first), "team_holdout")

    def test_mixed_sampler_has_exact_ratio_and_reproducible_order(self):
        from training.replay_refresh import mixed_row_batches

        fresh = [{"sample_source": "fresh", "id": i} for i in range(192)]
        old = [{"sample_source": "rehearsal", "id": i} for i in range(8)]
        make = lambda: list(mixed_row_batches(lambda: iter(fresh), lambda: iter(old), 64, 0.75, 7, shuffle_buffer=8))
        first = make()
        second = make()
        flat = [row for batch in first for row in batch]
        self.assertEqual(sum(row["sample_source"] == "fresh" for row in flat), 192)
        self.assertEqual(sum(row["sample_source"] == "rehearsal" for row in flat), 64)
        self.assertEqual(first, second)

    def test_targeted_sampler_has_exact_50_25_25_mix(self):
        from training.replay_refresh import weighted_row_batches

        make = lambda name: lambda: iter([{"sample_source": name, "id": index} for index in range(7)])
        batches = weighted_row_batches(
            {"hard": make("hard"), "fresh": make("fresh"), "rehearsal": make("rehearsal")},
            {"hard": 0.50, "fresh": 0.25, "rehearsal": 0.25},
            batch_size=64,
            seed=9,
            total_records=256,
            shuffle_buffer=4,
        )
        rows = [row for batch in batches for row in batch]
        counts = {name: sum(row["sample_source"] == name for row in rows) for name in ("hard", "fresh", "rehearsal")}
        self.assertEqual(counts, {"hard": 128, "fresh": 64, "rehearsal": 64})

    def test_distillation_is_zero_for_identical_models_and_gradients_are_scoped(self):
        from training.replay_refresh import policy_distillation_loss, set_trainable_modules
        from training.train_bc import PolicyNet, collate

        batch = collate([self.row("one")])
        teacher = PolicyNet(2).eval()
        student = PolicyNet(2)
        student.load_state_dict(teacher.state_dict())
        set_trainable_modules(student, ("option_linear", "score", "count", "value"))
        with torch.no_grad():
            teacher_logits, teacher_count, _ = teacher(batch)
        student_logits, student_count, _ = student(batch)
        action_kl, count_kl = policy_distillation_loss(
            student_logits, student_count, teacher_logits, teacher_count, batch
        )
        self.assertAlmostEqual(float(action_kl.detach()), 0.0, places=6)
        self.assertAlmostEqual(float(count_kl.detach()), 0.0, places=6)
        (action_kl + count_kl + student_logits.sum() * 0.01).backward()
        for name, parameter in student.named_parameters():
            if name.split(".", 1)[0] in ("option_linear", "score", "count", "value"):
                continue
            self.assertIsNone(parameter.grad, name)

    def test_auto_device_priority_and_fallback(self):
        from training.replay_refresh import auto_device

        with patch("torch.cuda.is_available", return_value=True):
            self.assertEqual(str(auto_device()), "cuda")
        with patch("torch.cuda.is_available", return_value=False), patch("torch.backends.mps.is_available", return_value=False):
            self.assertEqual(str(auto_device()), "cpu")


if __name__ == "__main__":
    unittest.main()
