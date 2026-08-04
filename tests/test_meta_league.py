import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MetaLeagueTests(unittest.TestCase):
    def test_top_ten_decks_are_present_and_legal_length(self):
        league = json.loads((ROOT / "training" / "meta_league.json").read_text())
        evaluated = [entry for entry in league["opponents"] if entry.get("evaluate")]
        self.assertEqual(len(evaluated), 10)
        self.assertEqual(len({entry["name"] for entry in evaluated}), 10)
        for entry in league["opponents"]:
            deck = ROOT / entry["deck"]
            cards = [int(line) for line in deck.read_text().splitlines() if line.strip()]
            self.assertEqual(len(cards), 60, entry["name"])
            self.assertGreater(entry.get("train_weight", 0), 0)

    def test_external_alakazam_training_mass_is_capped(self):
        league = json.loads((ROOT / "training" / "meta_league.json").read_text())
        external = [entry for entry in league["opponents"] if entry.get("submission")]
        self.assertEqual(
            {entry["name"] for entry in external},
            {"alakazam_2_7_external", "alakazam_2_4a_external_fast"},
        )
        self.assertLessEqual(sum(entry["train_weight"] for entry in external), 8)


if __name__ == "__main__":
    unittest.main()
