import json
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))

from cg.api import to_observation_class

from ptcg_ai.features import encode_observation
from ptcg_ai.relational import NumpyRelationalResidualModel, ResidualEnsemblePolicy
from ptcg_ai.replay import episode_order
from training.schema4 import RelationalResidualNet, export_residual
from training.train_bc import PolicyNet, collate, export_npz


def observation():
    player = {
        "active": [{
            "id": 646, "serial": 3, "hp": 70, "maxHp": 70,
            "appearThisTurn": False, "energies": [], "energyCards": [],
            "tools": [], "preEvolution": [],
        }],
        "bench": [], "benchMax": 5, "deckCount": 45, "discard": [],
        "prize": [None] * 6, "handCount": 2,
        "hand": [
            {"id": 1079, "serial": 31, "playerIndex": 0},
            {"id": 1137, "serial": 43, "playerIndex": 0},
        ],
        "poisoned": False, "burned": False, "asleep": False,
        "paralyzed": False, "confused": False,
    }
    opponent = dict(player)
    opponent.update({"active": [], "hand": None, "handCount": 5})
    return to_observation_class({
        "select": {
            "type": 0, "context": 0, "minCount": 1, "maxCount": 1,
            "remainDamageCounter": 0, "remainEnergyCost": 0,
            "option": [{"type": 7, "index": 0}, {"type": 7, "index": 1}, {"type": 14}],
            "deck": None, "contextCard": None, "effect": None,
        },
        "logs": [],
        "current": {
            "turn": 3, "turnActionCount": 1, "yourIndex": 0, "firstPlayer": 0,
            "supporterPlayed": False, "stadiumPlayed": False,
            "energyAttached": False, "retreated": False, "result": -1,
            "stadium": [], "looking": None, "players": [player, opponent],
        },
        "search_begin_input": "state",
    })


def test_schema4_binds_play_to_exact_hand_instances_but_legacy_stays_frozen():
    obs = observation()
    legacy = encode_observation(obs, 3)
    relational = encode_observation(obs, 4)
    assert [option.source_card for option in legacy.options[:2]] == [0, 0]
    assert [option.source_card for option in relational.options[:2]] == [1079, 1137]
    assert [option.source_serial for option in relational.options[:2]] == [31, 43]
    assert all(option.source_entity >= 0 for option in relational.options[:2])
    for option in relational.options[:2]:
        assert relational.entities[option.source_entity].serial == option.source_serial


def test_order_parser_separates_chooser_choice_and_first_player():
    choice = {
        "select": {"context": 41, "option": [{"type": 1}, {"type": 2}]},
        "current": {"firstPlayer": -1},
    }
    decided = {"select": None, "current": {"firstPlayer": 1}}
    episode = {
        "steps": [
            [{"observation": choice, "action": []}, {"observation": {}, "action": []}],
            [{"observation": decided, "action": [1]}, {"observation": decided, "action": []}],
        ]
    }
    assert episode_order(episode) == (0, "second", 1)


def test_numpy_relational_export_matches_torch(tmp_path):
    torch.manual_seed(19)
    obs = observation()
    features = encode_observation(obs, 4)
    row = {"features": features.to_json(), "action": [0], "reward": 1.0}
    batch = collate([row])
    model = RelationalResidualNet("r1").eval()
    torch.nn.init.normal_(model.score.weight, std=0.02)
    torch.nn.init.normal_(model.count.weight, std=0.02)
    with torch.no_grad():
        expected_logits, expected_count, expected_value = model(batch)
    path = tmp_path / "residual.npz"
    export_residual(model, path)
    actual_logits, actual_count, actual_value = NumpyRelationalResidualModel(path).predict(features)
    np.testing.assert_allclose(actual_logits, expected_logits.numpy(), atol=2e-2, rtol=2e-2)
    np.testing.assert_allclose(actual_count, expected_count.numpy()[0], atol=2e-2, rtol=2e-2)
    assert abs(actual_value - float(expected_value.numpy()[0])) < 2e-2


def test_zero_residual_ensemble_preserves_base_action(tmp_path):
    torch.manual_seed(23)
    export_npz(PolicyNet(2).eval(), tmp_path / "base.npz")
    heads = []
    for seed in range(3):
        torch.manual_seed(seed)
        path = tmp_path / f"head-{seed}.npz"
        export_residual(RelationalResidualNet("r0").eval(), path)
        heads.append(path.name)
    manifest = tmp_path / "residual_manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": 4,
        "base_model": "base.npz",
        "residual_heads": heads,
    }))
    policy = ResidualEnsemblePolicy(manifest, fallback=None)
    action = policy.choose(observation())
    base_logits, base_count, _ = policy.base.predict(encode_observation(observation(), 2))
    expected = [int(np.argmax(base_logits))]
    assert action == expected
