import sys
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))

from cg.api import AreaType, OptionType, to_observation_class

from ptcg_ai.agent import grimmsnarl_mirror_publicly_detected
from ptcg_ai.direct import DirectPolicy, NumpyDirectPolicyModel, NumpyRelationalDirectPolicyModel
from ptcg_ai.features import encode_observation
from training.schema5 import DirectPolicyNet, export_direct, pairwise_preference_loss
from training.schema5_relational import RelationalDirectPolicyNet, export_relational, load_relational
from training.schema4 import legacy_a2_batch
from training.train_bc import collate


def _player(active=None, bench=None, hand=None, your=True):
    return {
        "active": active or [], "bench": bench or [], "benchMax": 5,
        "deckCount": 42, "discard": [], "prize": [None] * 6,
        "handCount": len(hand or []) if your else 5, "hand": hand if your else None,
        "poisoned": False, "burned": False, "asleep": False,
        "paralyzed": False, "confused": False,
    }


def _pokemon(card_id, serial, hp=70):
    return {
        "id": card_id, "serial": serial, "hp": hp, "maxHp": hp,
        "appearThisTurn": False, "energies": [], "energyCards": [],
        "tools": [], "preEvolution": [],
    }


def observation(opponent_cards=(646, 112)):
    me = _player(
        active=[_pokemon(646, 3)],
        hand=[{"id": 1079, "serial": 31, "playerIndex": 0}],
    )
    opponent = _player(
        active=[_pokemon(opponent_cards[0], 71)],
        bench=[_pokemon(card_id, 72 + index, 110 if card_id == 112 else 70)
               for index, card_id in enumerate(opponent_cards[1:])],
        your=False,
    )
    return to_observation_class({
        "select": {
            "type": 0, "context": 0, "minCount": 1, "maxCount": 1,
            "remainDamageCounter": 0, "remainEnergyCost": 0,
            "option": [{"type": 7, "index": 0}, {"type": 14}],
            "deck": None, "contextCard": None, "effect": None,
        },
        "logs": [],
        "current": {
            "turn": 3, "turnActionCount": 2, "yourIndex": 0, "firstPlayer": 0,
            "supporterPlayed": False, "stadiumPlayed": False,
            "energyAttached": False, "retreated": False, "result": -1,
            "stadium": [], "looking": None, "players": [me, opponent],
        },
        "search_begin_input": "state",
    })


def test_schema5_keeps_targeted_ordered_event_history():
    history = [{
        "context": 16, "option_type": 3,
        "source_card": 112, "source_serial": 72,
        "target_card": 648, "target_serial": 88,
        "attack_id": 937, "numeric": [0.1] * 12,
    }]
    features = encode_observation(observation(), 5, action_history=history)
    assert len(features.events) == 1
    event = features.events[0]
    assert (event.context, event.source_card, event.target_card, event.attack_id) == (16, 112, 648, 937)
    assert event.source_serial == 72 and event.target_serial == 88
    assert len(event.numeric) == 12


def test_schema5_followup_option_binds_causal_source_to_selected_target():
    obs = observation()
    obs.select.context = 15
    obs.select.effect = obs.current.players[1].bench[0]  # Munkidori using the ability
    option = obs.select.option[0]
    option.type = OptionType.CARD
    option.area = AreaType.ACTIVE
    option.index = 0
    option.playerIndex = 1
    obs.select.option = [option]
    encoded = encode_observation(obs, 5)
    assert encoded.options[0].source_card == 112
    assert encoded.options[0].source_serial == obs.select.effect.serial
    assert encoded.options[0].target_card == 646
    assert encoded.options[0].target_serial == obs.current.players[1].active[0].serial


def test_numpy_direct_export_matches_torch(tmp_path):
    torch.manual_seed(29)
    features = encode_observation(observation(), 5, action_history=[{
        "context": 21, "option_type": 8, "source_card": 7,
        "source_serial": 64, "target_card": 112, "target_serial": 72,
        "attack_id": 0, "numeric": [0.0] * 12,
    }])
    batch = collate([{"features": features.to_json(), "action": [0], "reward": 1.0}])
    model = DirectPolicyNet().eval()
    with torch.no_grad():
        expected_logits, expected_counts = model(batch)
    artifact = tmp_path / "direct.npz"
    export_direct(model, artifact)
    actual_logits, actual_counts = NumpyDirectPolicyModel(artifact).predict(features)
    np.testing.assert_allclose(actual_logits, expected_logits.numpy(), atol=3e-2, rtol=3e-2)
    np.testing.assert_allclose(actual_counts, expected_counts.numpy()[0], atol=3e-2, rtol=3e-2)


def test_mirror_route_uses_one_line_card_and_deck_compatibility():
    exact = [646, 112] + [7] * 58
    assert grimmsnarl_mirror_publicly_detected(observation((646, 112)), exact)
    assert grimmsnarl_mirror_publicly_detected(observation((646,)), exact)
    assert not grimmsnarl_mirror_publicly_detected(observation((646, 112, 999)), exact)


def test_direct_runtime_disqualified_context_uses_fallback(tmp_path):
    model = DirectPolicyNet().eval()
    artifact = tmp_path / "direct_policy.npz"
    export_direct(model, artifact)
    (tmp_path / "direct_runtime.json").write_text(json.dumps({
        "model_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "enabled_contexts": [7],
        "disqualified_contexts": [0],
    }))

    class Fallback:
        def reset(self):
            pass

        def choose(self, obs):
            return [1]

    policy = DirectPolicy(artifact, Fallback())
    assert policy.choose(observation()) == [1]
    assert policy.fallback_telemetry["unrepresented"] == 1


def test_direct_runtime_hash_mismatch_fails_closed(tmp_path):
    artifact = tmp_path / "direct_policy.npz"
    export_direct(DirectPolicyNet().eval(), artifact)
    (tmp_path / "direct_runtime.json").write_text(json.dumps({"model_sha256": "wrong"}))
    with pytest.raises(ValueError, match="hash mismatch"):
        DirectPolicy(artifact)


def test_pairwise_complete_action_loss_prefers_certified_alternative():
    global_features = torch.zeros((1, 124))
    global_features[0, 28] = global_features[0, 29] = 1 / 9
    batch = {
        "record_rejected_actions": [[1]],
        "record_actions": [[0]],
        "record_options": [(0, 2)],
        "global": global_features,
        "weights": torch.ones(1),
    }
    counts = torch.zeros((1, 61))
    good = pairwise_preference_loss(torch.tensor([3.0, -1.0]), counts, batch)
    bad = pairwise_preference_loss(torch.tensor([-1.0, 3.0]), counts, batch)
    assert good < bad


def test_causal_card_binding_reconstructs_frozen_a2_selected_source():
    batch = {
        "global": torch.zeros((1, 124)),
        "numeric": torch.zeros((2, 19)),
        "type": torch.tensor([3, 7]),
        "source": torch.tensor([112, 1079]),
        "target": torch.tensor([648, 0]),
    }
    legacy = legacy_a2_batch(batch)
    assert legacy["source"].tolist() == [648, 0]


def test_relational_d1_zero_residual_reproduces_m0_and_numpy(tmp_path):
    torch.manual_seed(71)
    features = encode_observation(observation(), 5, action_history=[{
        "context": 16, "option_type": 3, "source_card": 112,
        "source_serial": 72, "target_card": 648, "target_serial": 88,
        "attack_id": 0, "numeric": [0.0] * 12,
    }])
    batch = collate([{"features": features.to_json(), "action": [0], "reward": 1.0}])
    m0 = DirectPolicyNet().eval()
    m0_artifact = tmp_path / "m0.npz"
    export_direct(m0, m0_artifact)
    # Compare against the serialized M0 artifact, not its pre-float16 in-memory weights.
    from training.schema5 import load_direct
    load_direct(m0, m0_artifact)
    d1 = RelationalDirectPolicyNet().eval()
    assert load_relational(d1, m0_artifact) == 1
    with torch.no_grad():
        m0_logits, m0_counts = m0(batch)
        d1_logits, d1_counts = d1(batch)
    assert torch.equal(m0_logits, d1_logits)
    assert torch.equal(m0_counts, d1_counts)
    artifact = tmp_path / "d1.npz"
    export_relational(d1, artifact)
    numpy_logits, numpy_counts = NumpyRelationalDirectPolicyModel(artifact).predict(features)
    np.testing.assert_allclose(numpy_logits, d1_logits.numpy(), atol=3e-2, rtol=3e-2)
    np.testing.assert_allclose(numpy_counts, d1_counts.numpy()[0], atol=3e-2, rtol=3e-2)
