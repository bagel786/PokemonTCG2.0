import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))

from ptcg_ai.replay import episode_reward, iter_decisions


class ReplayAlignmentTests(unittest.TestCase):
    def test_action_comes_from_following_step(self):
        observation = {
            "select": {
                "type": 9,
                "context": 41,
                "minCount": 1,
                "maxCount": 1,
                "remainDamageCounter": 0,
                "remainEnergyCost": 0,
                "option": [{"type": 1}, {"type": 2}],
                "deck": None,
                "contextCard": None,
                "effect": None,
            },
            "logs": [],
            "current": {
                "turn": 0,
                "turnActionCount": 0,
                "yourIndex": 0,
                "firstPlayer": -1,
                "supporterPlayed": False,
                "stadiumPlayed": False,
                "energyAttached": False,
                "retreated": False,
                "result": -1,
                "stadium": [],
                "looking": None,
                "players": [
                    {"active": [], "bench": [], "benchMax": 5, "deckCount": 60, "discard": [], "prize": [], "handCount": 0, "hand": [], "poisoned": False, "burned": False, "asleep": False, "paralyzed": False, "confused": False},
                    {"active": [], "bench": [], "benchMax": 5, "deckCount": 60, "discard": [], "prize": [], "handCount": 0, "hand": None, "poisoned": False, "burned": False, "asleep": False, "paralyzed": False, "confused": False},
                ],
            },
            "search_begin_input": "x",
        }
        episode = {
            "info": {"EpisodeId": 1, "TeamNames": ["elite", "other"]},
            "rewards": [1, -1],
            "steps": [
                [{"status": "ACTIVE", "observation": observation, "action": []}, {"status": "INACTIVE", "observation": {}, "action": []}],
                [{"status": "INACTIVE", "observation": observation, "action": [1]}, {"status": "ACTIVE", "observation": {}, "action": []}],
            ],
        }
        records = list(iter_decisions(episode, {"elite"}))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].action, [1])

    def test_stale_inactive_selection_is_not_a_decision(self):
        observation = {
            "select": {
                "type": 9, "context": 2, "minCount": 0, "maxCount": 1,
                "remainDamageCounter": 0, "remainEnergyCost": 0,
                "option": [{"type": 7, "index": 0}], "deck": None,
                "contextCard": None, "effect": None,
            },
            "logs": [],
            "current": {
                "turn": 0, "turnActionCount": 0, "yourIndex": 0,
                "firstPlayer": 0, "supporterPlayed": False,
                "stadiumPlayed": False, "energyAttached": False,
                "retreated": False, "result": -1, "stadium": [],
                "looking": None,
                "players": [
                    {"active": [], "bench": [], "benchMax": 5, "deckCount": 60, "discard": [], "prize": [], "handCount": 0, "hand": [], "poisoned": False, "burned": False, "asleep": False, "paralyzed": False, "confused": False},
                    {"active": [], "bench": [], "benchMax": 5, "deckCount": 60, "discard": [], "prize": [], "handCount": 0, "hand": None, "poisoned": False, "burned": False, "asleep": False, "paralyzed": False, "confused": False},
                ],
            },
            "search_begin_input": "x",
        }
        episode = {
            "info": {"EpisodeId": 2, "TeamNames": ["elite", "other"]},
            "rewards": [1, -1],
            "steps": [
                [{"status": "INACTIVE", "observation": observation, "action": []}, {"status": "ACTIVE", "observation": {}, "action": []}],
                [{"status": "ACTIVE", "observation": observation, "action": []}, {"status": "INACTIVE", "observation": {}, "action": []}],
            ],
        }
        self.assertEqual(list(iter_decisions(episode, {"elite"})), [])

    def test_null_rewards_use_terminal_winner(self):
        episode = {
            "rewards": [None, None],
            "steps": [
                [{"observation": {"current": {"result": -1}}}],
                [{"observation": {"current": {"result": 1}}}],
            ],
        }
        self.assertEqual(episode_reward(episode, 0), 0.0)
        self.assertEqual(episode_reward(episode, 1), 1.0)

    def test_unfinished_null_reward_is_unknown(self):
        episode = {
            "info": {"TeamNames": ["elite", "other"]},
            "rewards": [None, None],
            "steps": [
                [{"observation": {"current": {"result": -1}}}],
                [{"observation": {"current": {"result": -1}}}],
            ],
        }
        self.assertIsNone(episode_reward(episode, 0))
        self.assertEqual(list(iter_decisions(episode)), [])


if __name__ == "__main__":
    unittest.main()
