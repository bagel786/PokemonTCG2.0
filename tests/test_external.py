import unittest
import sys
from pathlib import Path

from ptcg_ai.external import ExternalSubmissionAgent


ROOT = Path(__file__).resolve().parents[1]


class ExternalSubmissionTests(unittest.TestCase):
    def test_submission_loads_in_isolated_namespace(self):
        newer = ExternalSubmissionAgent(
            ROOT / "freshstart" / "elite_submissions" / "alakazam_2_7",
            {"DIRECT_POLICY": "1"},
        )
        older = ExternalSubmissionAgent(
            ROOT / "freshstart" / "elite_submissions" / "alakazam_2_4a",
            {"DIRECT_POLICY": "1"},
        )
        self.assertEqual(len(newer.deck), 60)
        self.assertTrue(newer.module.__name__.startswith("_ptcg_external_"))
        self.assertIn("alakazam_2_7", newer.module.policy.__file__)
        self.assertIn("alakazam_2_4a", older.module.policy.__file__)
        owned = set(newer._owned_module_names) | set(older._owned_module_names)
        newer.close()
        older.close()
        self.assertTrue(all(name not in sys.modules for name in owned))


if __name__ == "__main__":
    unittest.main()
