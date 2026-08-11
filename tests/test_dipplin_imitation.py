from __future__ import annotations

import json
from pathlib import Path

from cg.api import to_observation_class

from ptcg_ai.dipplin.imitation import option_features, rank_main_options
from ptcg_ai.dipplin.plan import build_macro_plan


ROOT = Path(__file__).resolve().parents[1]


def test_public_replay_ranker_has_heldout_episode_evidence():
    payload = json.loads((ROOT / "ptcg_ai/dipplin/imitation_weights.json").read_text())

    assert payload["schema"] == "dipplin-public-replay-main-ranker-v1"
    assert payload["submission_id"] == 55408594
    assert payload["examples"] == 3526
    assert payload["episodes"] == 88
    assert payload["heldout_episodes"] == 18
    assert payload["heldout_accuracy"] >= 0.80
    assert len(payload["weights"]) == 4403


def test_ranker_features_are_opponent_identity_blind_and_rank_legal_options():
    raw = json.loads((ROOT / "artifacts/dipplin_prompt_audit/main_do_the_wave.json").read_text())["observation"]
    obs = to_observation_class(raw)
    plan = build_macro_plan(obs)
    features = option_features(obs, plan, 0)
    ranked, margin = rank_main_options(obs, plan)

    assert not any("opp_id" in feature or "opponent_id" in feature for feature in features)
    assert sorted(ranked) == list(range(len(obs.select.option)))
    assert margin >= 0.0
