import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

from scripts import audit_grim_guardrail_candidate as audit
from scripts.build_grim_5k_training_bank import deck_hash


def test_non_development_is_refused_before_any_input_verification(monkeypatch):
    touched = []

    def forbidden(**_kwargs):
        touched.append(True)
        raise AssertionError("input verification must not run")

    monkeypatch.setattr(audit, "verify_inputs", forbidden)
    with pytest.raises(ValueError, match="hard-locked to development"):
        audit.run(split="calibration", output_path=None)
    with pytest.raises(ValueError, match="hard-locked to development"):
        audit.run(split="untouched_holdout", output_path=None)
    assert touched == []


def test_hash_binding_and_development_row_refusal(tmp_path):
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"frozen")
    digest = hashlib.sha256(b"frozen").hexdigest().upper()
    assert audit._require_file_hash(artifact, digest, label="fixture") == digest
    with pytest.raises(ValueError, match="hash mismatch"):
        audit._require_file_hash(artifact, "0" * 64, label="fixture")

    shard = tmp_path / "rows.jsonl.gz"
    with gzip.open(shard, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"split": "calibration"}) + "\n")
    with pytest.raises(ValueError, match="not development"):
        audit._read_development_rows(shard, row_kind="fixture")


def test_d842_intent_matches_original_sort_and_count(monkeypatch):
    monkeypatch.setattr(audit, "encode_observation", lambda _obs, _version: object())

    class Model:
        feature_version = 2

        @staticmethod
        def predict(_features):
            return np.asarray([0.1, 0.9, 0.4]), np.asarray([0.0, 0.2, 1.3]), 0.0

    obs = NS(select=NS(option=[object(), object(), object()], minCount=0, maxCount=2))
    ranked, desired, action = audit.d842_intent(Model(), obs)
    assert ranked == [1, 2, 0]
    assert desired == 2
    assert action == [1, 2]


@pytest.mark.parametrize(
    "value,match",
    [
        (([0], 1), "must return"),
        (([0, 0], 1, "named"), "malformed"),
        (([0], True, "named"), "integer"),
        (([0], 1, ""), "non-empty"),
    ],
)
def test_guardrail_contract_is_fail_closed(value, match):
    obs = NS(select=NS(option=[object()]))
    with pytest.raises(ValueError, match=match):
        audit._validate_guardrail_result(obs, value)


def _raw_observation():
    return {
        "current": {"yourIndex": 0, "firstPlayer": 0},
        "select": {
            "type": 1,
            "context": 1,
            "minCount": 1,
            "maxCount": 1,
            "option": [{"type": 18}, {"type": 17}],
        },
    }


def _converted_observation(raw):
    select = raw["select"]
    return NS(
        current=NS(yourIndex=0, firstPlayer=0),
        select=NS(
            option=[NS(type=item["type"]) for item in select["option"]],
            minCount=select["minCount"],
            maxCount=select["maxCount"],
        ),
    )


def _sequential_fixture(tmp_path: Path):
    hero_deck = [7] * 60
    opponent_deck = [8] * 60
    first_obs = _raw_observation()
    second_obs = _raw_observation()
    replay = {
        "info": {"EpisodeId": 1},
        "steps": [
            [
                {"status": "INACTIVE", "action": hero_deck},
                {"status": "INACTIVE", "action": opponent_deck},
            ],
            [{"status": "ACTIVE", "observation": first_obs}, {}],
            [{"status": "ACTIVE", "observation": second_obs, "action": [0]}, {}],
            [{"status": "DONE", "action": [0]}, {}],
        ],
    }
    payload = json.dumps(replay, separators=(",", ":")).encode("utf-8")
    replay_path = tmp_path / "episode.json"
    replay_path.write_bytes(payload)
    expected = audit.FrozenDevelopmentHashes(
        model_sha256="A" * 64,
        deck_file_sha256="B" * 64,
        deck_canonical_sha256=deck_hash(hero_deck),
        bank_manifest_sha256="C" * 64,
        bank_development_sha256="D" * 64,
        bank_id="E" * 64,
        correction_sha256="F" * 64,
        correction_manifest_sha256="1" * 64,
        model_behavior_sha256="2" * 64,
        units=1,
        decisions=2,
        corrections=2,
    )
    unit = {
        "episode_id": "1",
        "hero_seat": 0,
        "actual_first_player": 0,
        "actual_order": "first",
        "hero_decisions": 2,
        "replay_path": replay_path.name,
        "replay_sha256": hashlib.sha256(payload).hexdigest().upper(),
        "replay_bytes": len(payload),
    }

    baseline_id = audit._public_semantic_id(first_obs, [0])
    candidate_id = audit._public_semantic_id(first_obs, [1])
    corrections = {
        ("1", 0, 1): {
            "observation": first_obs,
            "candidate_semantic_id": candidate_id,
            "baseline_semantic_id": baseline_id,
        },
        ("1", 0, 2): {
            "observation": second_obs,
            "candidate_semantic_id": baseline_id,
            "baseline_semantic_id": baseline_id,
        },
    }
    inputs = audit.VerifiedInputs(
        units=(unit,),
        corrections=corrections,
        bank_manifest={"source_replay_root": str(tmp_path)},
        hero_deck=tuple(hero_deck),
        provenance={},
        expected=expected,
    )
    return inputs


def test_sequential_pass_commits_candidate_and_marks_counterfactual_tail(tmp_path, monkeypatch):
    inputs = _sequential_fixture(tmp_path)
    monkeypatch.setattr(audit, "to_observation_class", _converted_observation)
    instances = []

    class Director:
        def __init__(self):
            self.committed = []
            self.calls = 0
            self.resets = 0
            instances.append(self)

        def reset(self):
            self.resets += 1

        def apply(self, _obs, ranked, desired):
            self.calls += 1
            if self.calls == 1:
                return [1, 0], desired, "setup:test_choice"
            # The historical response to the first decision is [0].  Seeing
            # [1] here proves the audit committed the emitted candidate.
            assert self.committed == [[1]]
            return ranked, desired, None

        def commit(self, _obs, action):
            self.committed.append(list(action))

    def intent(_model, _obs):
        return [0, 1], 1, [0]

    first = audit.audit_pass(
        inputs,
        model=object(),
        director_factory=Director,
        intent_fn=intent,
    )
    second = audit.audit_pass(
        inputs,
        model=object(),
        director_factory=Director,
        intent_fn=intent,
    )
    assert first.errors == []
    assert first.invalid_actions == 0
    assert len(first.decision_rows) == 2
    assert first.decision_rows[0]["semantic_changed"] is True
    assert first.decision_rows[0]["post_counterfactual_divergence"] is False
    assert first.decision_rows[1]["post_counterfactual_divergence"] is True
    assert first.correction_rows[0]["conservative_proxy_eligible"] is True
    assert first.correction_rows[1]["conservative_proxy_eligible"] is False
    assert first.decision_digest == second.decision_digest
    assert all(instance.resets == 1 for instance in instances)
    assert instances[0].committed == [[1], [0]]


def test_clustered_bound_is_deterministic_and_episode_atomic():
    rows = [
        {"episode_id": "a", "candidate_match": 1, "baseline_match": 0},
        {"episode_id": "a", "candidate_match": 1, "baseline_match": 0},
        {"episode_id": "b", "candidate_match": 0, "baseline_match": 1},
    ]
    first = audit.clustered_lower_bound(rows, samples=250, seed=19)
    second = audit.clustered_lower_bound(list(reversed(rows)), samples=250, seed=19)
    assert first == second
    assert -1.0 <= first <= 1.0


def test_coordinated_mode_uses_choose_telemetry_and_never_double_commits(
    tmp_path, monkeypatch
):
    inputs = _sequential_fixture(tmp_path)
    monkeypatch.setattr(audit, "to_observation_class", _converted_observation)

    class Coordinator:
        def __init__(self):
            self.calls = 0

        def reset(self):
            self.calls = 0

        def choose(self, _obs, _ranked, _desired):
            self.calls += 1
            return [1] if self.calls == 1 else [0]

        def telemetry(self):
            return {
                "last": {
                    "status": "tactical_action" if self.calls == 1 else "d842_action",
                    "source": "tactical" if self.calls == 1 else "d842",
                    "guardrail_reason": None,
                    "tactical_reason": (
                        "end_with_productive_attack" if self.calls == 1 else None
                    ),
                    "suppressed_tactical_reason": None,
                    "proof_reason": None,
                    "error_stage": None,
                    "error_type": None,
                }
            }

    result = audit.audit_pass(
        inputs,
        model=object(),
        director_factory=Coordinator,
        intent_fn=lambda _model, _obs: ([0, 1], 1, [0]),
        candidate_mode="coordinated_no_proof",
    )
    assert result.errors == []
    assert result.decision_rows[0]["reason"] == (
        "tactical:end_with_productive_attack"
    )
    assert result.decision_rows[0]["coordinator_source"] == "tactical"
    assert result.decision_rows[1]["coordinator_source"] == "d842"
