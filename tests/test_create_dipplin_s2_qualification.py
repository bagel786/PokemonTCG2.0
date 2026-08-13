from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from scripts import create_dipplin_s2_qualification as qualification


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _cell(
    root: Path,
    *,
    cell_id: str,
    order: str,
    wins: int,
    games: int,
) -> dict:
    artifact = root / "artifacts" / "cells" / f"{cell_id}.json"
    _write_json(artifact, {"id": cell_id, "wins": wins, "games": games})
    return {
        "id": cell_id,
        "actual_order": order,
        "games": games,
        "scheduled_games": games,
        "wins": wins,
        "losses": games - wins,
        "draws": 0,
        "failed_games": 0,
        "hero_policy_errors": 0,
        "opponent_policy_errors": 0,
        "hero_illegal_actions": 0,
        "opponent_illegal_actions": 0,
        "source": {
            "path": str(artifact),
            "artifact_sha256": qualification._sha256(artifact),
        },
    }


def _pooled(cells: list[dict]) -> dict:
    result = {
        key: sum(int(cell[key]) for cell in cells)
        for key in (
            "games",
            "scheduled_games",
            "wins",
            "losses",
            "draws",
            "failed_games",
            "hero_policy_errors",
            "opponent_policy_errors",
            "hero_illegal_actions",
            "opponent_illegal_actions",
        )
    }
    result["win_rate"] = result["wins"] / result["games"]
    return result


def _aggregate(rows: list[dict]) -> dict:
    counts = Counter(str(row["classification"]) for row in rows)
    by_episode: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_episode[str(row["episode_id"])].append(row)
    episode_rates = {
        label: (
            sum(
                sum(row["classification"] == label for row in episode_rows)
                / len(episode_rows)
                for episode_rows in by_episode.values()
            )
            / len(by_episode)
            if by_episode
            else 0.0
        )
        for label in qualification.LABELS
    }
    proposal_errors = sum(row.get("proposal_error") is not None for row in rows)
    action_unstable = sum(
        row.get("proposal_error") is not None
        and (
            "unstable" in str(row.get("proposal_error")).lower()
            or str(row.get("uncertifiable_reason") or "").lower()
            in {"candidate_action_unstable", "action_unstable"}
        )
        for row in rows
    )
    decision_archetypes = Counter(
        str(row.get("opponent_archetype") or "unknown") for row in rows
    )
    episode_archetypes = {
        str(row["episode_id"]): str(row.get("opponent_archetype") or "unknown")
        for row in rows
    }
    episode_archetype_counts = Counter(episode_archetypes.values())
    return {
        "decision_count": len(rows),
        "episode_count": len(by_episode),
        "classification_counts": {
            label: counts[label] for label in qualification.LABELS
        },
        "decision_rates": {
            label: counts[label] / len(rows) if rows else 0.0
            for label in qualification.LABELS
        },
        "episode_rates": episode_rates,
        "episode_bootstrap_95": {
            label: [episode_rates[label], episode_rates[label]]
            for label in qualification.LABELS
        },
        "expert_dominates_rate": episode_rates["EXPERT_DOMINATES"],
        "agent_dominates_rate": episode_rates["AGENT_DOMINATES"],
        "quality_counts": {
            "proposal_error_rows": proposal_errors,
            "candidate_policy_error_rows": proposal_errors - action_unstable,
            "candidate_action_unstable_rows": action_unstable,
            "uncertifiable_rows": counts["UNCERTIFIABLE"],
            "incomparable_rows": counts["INCOMPARABLE"],
        },
        "opponent_archetype_decision_counts": dict(sorted(decision_archetypes.items())),
        "opponent_archetype_episode_counts": dict(
            sorted(episode_archetype_counts.items())
        ),
        "opponent_archetypes": dict(sorted(episode_archetype_counts.items())),
        "opponent_archetypes_basis": "unique_episode_id",
    }


def _signed_manifest() -> dict:
    payload = {
        "schema_version": 1,
        "dataset": "dipplin_fresh_expert_replay_eval_v1",
        "split": "VALIDATION",
        "sealed": False,
        "episode_count": 4,
        "episodes": [
            {
                "episode_id": index,
                "opponent": {"archetype": "synthetic"},
            }
            for index in range(1, 5)
        ],
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest().upper()
    return {**payload, "manifest_payload_sha256": digest}


def _fixture(tmp_path: Path) -> tuple[qualification.QualificationContract, dict]:
    root = tmp_path.resolve()
    evaluator = root / "scripts" / "evaluate_dipplin_replay_regret.py"
    stage_evaluator = root / "scripts" / "evaluate_dipplin_s2_stages.py"
    creator = root / "scripts" / "create_dipplin_s2_qualification.py"
    evaluator.parent.mkdir(parents=True, exist_ok=True)
    evaluator.write_text("# frozen evaluator\n", encoding="utf-8")
    stage_evaluator.write_text("# frozen stage evaluator\n", encoding="utf-8")
    creator.write_text("# frozen creator\n", encoding="utf-8")

    pins = {
        "s1_archive_sha256": "1" * 64,
        "s1_manifest_sha256": "2" * 64,
        "s1_extracted_tree_sha256": "3" * 64,
        "s1_runtime_tree_sha256": "4" * 64,
        "s2_archive_sha256": "5" * 64,
        "s2_manifest_sha256": "6" * 64,
        "s2_extracted_tree_sha256": "7" * 64,
        "s2_runtime_tree_sha256": "8" * 64,
    }
    spec_path = root / "data" / "stage_spec.json"
    _write_json(spec_path, {"schema": "synthetic-frozen-stage-spec-v1"})
    pins.update({
        "stage_evaluator_sha256": qualification._sha256(stage_evaluator),
        "stage_evaluator_git_blob_sha1": qualification._git_blob_sha1(
            stage_evaluator
        ),
        "stage_spec_sha256": qualification._sha256(spec_path),
        "stage_spec_git_blob_sha1": qualification._git_blob_sha1(spec_path),
    })

    stage_map = {}
    for name in ("stage1", "stage2", "stage3"):
        baseline = [_cell(root, cell_id=f"{name}_s1", order="second", wins=50, games=100)]
        candidate = [_cell(root, cell_id=f"{name}_s2", order="second", wins=55, games=100)]
        stage_map[name] = {
            "status": "EVALUATED",
            "baseline_cells": baseline,
            "candidate_cells": candidate,
            "pooled": {"baseline": _pooled(baseline), "candidate": _pooled(candidate)},
            "decision": (
                {
                    "verdict": "STRONG",
                    "gates": {
                        "minimum_3pp_pooled_lift": True,
                        "strong_5pp_pooled_lift": True,
                        "zero_failures_and_policy_errors": True,
                    },
                }
                if name == "stage1"
                else {
                    "verdict": "STRONG" if name == "stage2" else "PASS",
                    "passed": True,
                        "gates": {"zero_quality_errors": True, "strength_gate": True},
                }
            ),
        }
    stage4_baseline = [
        _cell(root, cell_id="stage4_s1_first", order="first", wins=302, games=500),
        _cell(root, cell_id="stage4_s1_second", order="second", wins=197, games=500),
    ]
    stage4_candidate = [
        _cell(root, cell_id="stage4_s2_first", order="first", wins=180, games=300),
        _cell(root, cell_id="stage4_s2_second", order="second", wins=120, games=300),
    ]
    stage_map["stage4"] = {
        "status": "EVALUATED",
        "baseline_cells": stage4_baseline,
        "candidate_cells": stage4_candidate,
        "pooled": {
            "baseline": _pooled(stage4_baseline),
            "candidate": _pooled(stage4_candidate),
        },
        "decision": {
            "verdict": "PASS",
            "passed": True,
            "gates": {
                "zero_quality_errors": True,
                "per_order_floor": True,
                "balanced_pool_floor": True,
                "no_clear_loss": True,
            },
        },
    }
    report = {
        "schema": "dipplin-s2-stage-evaluation-v1",
        "spec": {"path": str(spec_path), "sha256": qualification._sha256(spec_path)},
        "baseline": {
            "archive_sha256": pins["s1_archive_sha256"],
            "tree_sha256": pins["s1_extracted_tree_sha256"],
            "package_manifest": {
                "sha256": pins["s1_manifest_sha256"],
                "variant": "s1",
            },
        },
        "candidate": {
            "archive_sha256": pins["s2_archive_sha256"],
            "tree_sha256": pins["s2_extracted_tree_sha256"],
            "package_manifest": {
                "sha256": pins["s2_manifest_sha256"],
                "variant": "s2",
            },
        },
        "stages": stage_map,
    }
    stage_report = root / "artifacts/general_strength/s2_stage5/stage5_evaluation.json"

    manifest_path = root / "data/dipplin_replay_eval/frozen/validation_manifest.json"
    manifest = _signed_manifest()
    _write_json(manifest_path, manifest)
    pins["manifest_file_sha256"] = qualification._sha256(manifest_path)
    pins["manifest_payload_sha256"] = manifest["manifest_payload_sha256"]

    s1_rows = [
        {
            "record_id": "r0", "episode_id": 1, "classification": "EXPERT_DOMINATES",
            "decision_family": "attack", "uncertifiable_reason": None, "proposal_error": None,
        },
        {
            "record_id": "r1", "episode_id": 2, "classification": "EXPERT_DOMINATES",
            "decision_family": "attack", "uncertifiable_reason": None, "proposal_error": None,
        },
        {
            "record_id": "r2", "episode_id": 3, "classification": "EQUIVALENT",
            "decision_family": "routine", "uncertifiable_reason": None, "proposal_error": None,
        },
        {
            "record_id": "r3", "episode_id": 4, "classification": "UNCERTIFIABLE",
            "decision_family": "recovery", "uncertifiable_reason": "rng", "proposal_error": None,
        },
    ]
    for index, row in enumerate(s1_rows):
        row.update({
            "replay_sha256": f"replay-{index}",
            "seat": index % 2,
            "step": index + 10,
            "turn": index + 1,
            "own_turn_ordinal": index + 1,
            "expert_action": [index],
            "expert_semantic": f"expert-{index}",
            "actual_order": "second",
            "hero_deck_family": "dipplin",
            "opponent_archetype": "synthetic",
        })
    s1_validation = root / "artifacts/general_strength/replay/validation_regret_s1.json"
    _write_json(s1_validation, {
        "schema": "dipplin-replay-regret-v1",
        "split": "VALIDATION",
        "sealed": False,
        "aggregate": _aggregate(s1_rows),
        "decision_rows": s1_rows,
    })
    pins["s1_validation_sha256"] = qualification._sha256(s1_validation)

    primary_rows = copy.deepcopy(s1_rows)
    primary_rows[0]["classification"] = "EQUIVALENT"
    for row in primary_rows:
        row.update({
            "candidate_variant": "s2",
            "candidate_s2_enabled": True,
            "s2_override_telemetry_trustworthy": True,
            "s2_pre_attack_sequence_proof_overrides_delta": 0,
        })
    exploratory_rows = [{
        "record_id": "x0",
        "episode_id": 5,
        "classification": "AGENT_DOMINATES",
        "decision_family": "setup",
        "opponent_archetype": "synthetic",
        "candidate_variant": "s2",
        "candidate_s2_enabled": True,
        "s2_override_telemetry_trustworthy": True,
        "s2_pre_attack_sequence_proof_overrides_delta": 1,
        "semantic_equivalent": False,
        "proposal_error": None,
    }]
    evaluator_provenance = qualification._provenance(evaluator, root)
    primary_aggregate = _aggregate(primary_rows)
    s2_validation = root / "artifacts/general_strength/replay/validation_regret_s2.json"
    _write_json(s2_validation, {
        "schema": "dipplin-replay-regret-v2",
        "split": "VALIDATION",
        "sealed": False,
        "candidate_variant": "s2",
        "headline_set": "paired_primary",
        "manifest_payload_sha256": pins["manifest_payload_sha256"],
        "aggregate_alias": "evaluation_sets.paired_primary.aggregate",
        "aggregate": primary_aggregate,
        "combined_rate_permitted": False,
        "baseline_incumbent_s1": {
            "validation_result_sha256": pins["s1_validation_sha256"],
            "archive_sha256": pins["s1_archive_sha256"],
            "manifest_sha256": pins["s1_manifest_sha256"],
            "extracted_tree_sha256": pins["s1_extracted_tree_sha256"],
            "runtime_source_tree_sha256": pins["s1_runtime_tree_sha256"],
        },
        "evaluated_candidate": {
            "archive_sha256": pins["s2_archive_sha256"],
            "manifest_sha256": pins["s2_manifest_sha256"],
            "extracted_tree_sha256": pins["s2_extracted_tree_sha256"],
            "runtime_source_tree_sha256": pins["s2_runtime_tree_sha256"],
        },
        "run_contract": {
            "candidate": "s2",
            "evaluator": evaluator_provenance,
            "validation_manifest_file_sha256": pins["manifest_file_sha256"],
            "validation_manifest_payload_sha256": pins["manifest_payload_sha256"],
            "baseline_s1_validation_result_sha256": pins["s1_validation_sha256"],
            "parameters": {
                "cap_per_episode": 24,
                "sample_seed": 20260813,
                "bootstrap_samples": 10000,
                "repeat_passes": 2,
                "proposal_repeats": 3,
            },
            "full_manifest_episode_count": 4,
        },
        "universe_counts": {
            "manifest_episode_count": 4,
            "useful_prompt_count": 6,
            "paired_primary_record_count": 4,
            "out_of_primary_useful_prompt_count": 2,
            "s2_override_prompt_count": 1,
            "paired_primary_s2_override_prompt_count": 0,
            "out_of_primary_s2_override_prompt_count": 1,
            "out_of_primary_s2_override_expert_equivalent_count": 0,
            "out_of_primary_s2_override_disagreement_count": 1,
            "s2_exploratory_record_count": 1,
            "s2_exploratory_hard_ceiling": 256,
        },
        "evaluation_sets": {
            "paired_primary": {
                "role": "qualification_primary",
                "selection": {
                    "mode": "exact_frozen_s1_record_ids",
                    "source_result_sha256": pins["s1_validation_sha256"],
                    "record_count": 4,
                    "record_id_sequence_sha256": qualification._object_sha256(
                        [row["record_id"] for row in s1_rows]
                    ),
                    "order_preserved": True,
                },
                "aggregate": primary_aggregate,
                "decision_rows": primary_rows,
            },
            "s2_exploratory": {
                "role": "exploratory_safety_veto_only",
                "safety_veto_only": True,
                "eligible_for_efficacy_rate": False,
                "selection": {
                    "mode": "exhaustive_disjoint_out_of_primary_s2_override_disagreements",
                    "requires_trustworthy_s2_override_delta": True,
                    "requires_candidate_expert_disagreement": True,
                    "hard_ceiling": 256,
                    "disjoint_from": "paired_primary",
                },
                "aggregate": _aggregate(exploratory_rows),
                "decision_rows": exploratory_rows,
            },
        },
    })

    stage5_gates = {
        "primary_expert_dominates_count_decreased": True,
        "primary_expert_dominates_episode_rate_decreased": True,
        "favorable_ed_exits_exceed_reverse_ed_entries": True,
        "zero_certified_exploratory_expert_dominates": True,
        "zero_certified_exploratory_incomparable": True,
        "no_new_failure_family": True,
        "zero_candidate_policy_errors": True,
        "primary_incomparable_uncertifiable_burden_not_increased": True,
    }
    stage_map["stage5"] = {
        "status": "EVALUATED",
        "baseline": {
            "source": {
                "path": str(s1_validation),
                "artifact_sha256": qualification._sha256(s1_validation),
            },
            **qualification._verify_aggregate(
                json.loads(s1_validation.read_text())["aggregate"],
                s1_rows,
                "fixture S1",
            ),
        },
        "candidate": {
            "source": {
                "path": str(s2_validation),
                "artifact_sha256": qualification._sha256(s2_validation),
            },
            **qualification._verify_aggregate(
                primary_aggregate,
                primary_rows,
                "fixture S2",
                require_quality_counts=True,
            ),
        },
        "paired_record_ids": {
            "count": 4,
            "sequence_sha256": qualification._object_sha256(
                [row["record_id"] for row in s1_rows]
            ),
            "exact_order_match": True,
        },
        "paired_transitions": {
            "ed_to_non_ed": 1,
            "non_ed_to_ed": 0,
            "matrix": {
                before: {
                    after: sum(
                        1
                        for old, new in zip(s1_rows, primary_rows)
                        if old["classification"] == before
                        and new["classification"] == after
                    )
                    for after in qualification.LABELS
                }
                for before in qualification.LABELS
            },
            "ed_count_identity_verified": True,
            "ed_to_non_ed_definition": (
                "EXPERT_DOMINATES to EQUIVALENT or AGENT_DOMINATES only"
            ),
        },
        "exploratory_safety_veto": {
            **qualification._verify_aggregate(
                _aggregate(exploratory_rows),
                exploratory_rows,
                "fixture exploratory",
                require_quality_counts=True,
            ),
            "efficacy_credit_permitted": False,
        },
        "failure_families": {
            "baseline": [
                {
                    "classification": item[0],
                    "decision_family": item[1],
                    "reason": item[2],
                }
                for item in sorted(
                    {
                        qualification._failure_family(row)
                        for row in s1_rows
                    }
                    - {None}
                )
            ],
            "candidate": [
                {
                    "classification": item[0],
                    "decision_family": item[1],
                    "reason": item[2],
                }
                for item in sorted(
                    {
                        qualification._failure_family(row)
                        for row in [*primary_rows, *exploratory_rows]
                    }
                    - {None}
                )
            ],
            "new": [],
        },
        "decision": {"verdict": "PASS", "passed": True, "gates": stage5_gates},
    }
    _write_json(stage_report, report)

    output = root / "data/dipplin_replay_eval/frozen/s2_qualification.json"
    contract = qualification.QualificationContract(
        root=root,
        output=output,
        stage_report=stage_report,
        s1_validation=s1_validation,
        s2_validation=s2_validation,
        validation_manifest=manifest_path,
        evaluator=evaluator,
        stage_evaluator=stage_evaluator,
        stage_spec=spec_path,
        creator=creator,
        pins=pins,
        primary_record_count=4,
        validation_episode_count=4,
        exploratory_hard_ceiling=256,
        validation_parameters={
            "cap_per_episode": 24,
            "sample_seed": 20260813,
            "bootstrap_samples": 10000,
            "repeat_passes": 2,
            "proposal_repeats": 3,
        },
    )
    return contract, report


def _recompute(report: dict):
    return lambda _spec: copy.deepcopy(report)


def test_build_recomputes_all_rules_and_binds_every_source(tmp_path: Path):
    contract, report = _fixture(tmp_path)

    payload = qualification.build_qualification_payload(
        contract, stage_recompute=_recompute(report)
    )

    assert payload["status"] == "QUALIFIED"
    assert payload["staged_evaluation"]["verdicts"] == {
        "stage1": "STRONG",
        "stage2": "STRONG",
        "stage3": "PASS",
        "stage4": "PASS",
        "stage5": "PASS",
    }
    assert len(payload["staged_evaluation"]["source_artifacts"]) == 12
    stage4 = payload["staged_evaluation"]["independent_reaggregation"]["stage4"]
    assert stage4["controls"]["first"]["wins"] == 302
    assert stage4["controls"]["second"]["wins"] == 197
    assert stage4["balanced_pooled_candidate_minus_control"] == pytest.approx(0.001)
    transitions = payload["rules"]["recomputed_validation"]["transitions"]
    assert transitions["ed_to_non_ed"] == 1
    assert transitions["non_ed_to_ed"] == 0
    assert transitions["matrix"]["EXPERT_DOMINATES"]["EQUIVALENT"] == 1
    unsigned = dict(payload)
    claimed = unsigned.pop("qualification_payload_sha256")
    assert claimed == qualification._object_sha256(unsigned)


def test_missing_later_artifact_is_explicitly_pending(tmp_path: Path):
    contract, report = _fixture(tmp_path)
    contract.s2_validation.unlink()

    with pytest.raises(qualification.QualificationError, match="pending; missing.*S2 paired"):
        qualification.build_qualification_payload(
            contract, stage_recompute=_recompute(report)
        )


@pytest.mark.parametrize("failure", ["exploratory_ed", "new_family", "reverse_transition"])
def test_validation_safety_rules_fail_closed(tmp_path: Path, failure: str):
    contract, report = _fixture(tmp_path)
    s2 = json.loads(contract.s2_validation.read_text(encoding="utf-8"))
    primary = s2["evaluation_sets"]["paired_primary"]["decision_rows"]
    exploratory = s2["evaluation_sets"]["s2_exploratory"]["decision_rows"]
    if failure == "exploratory_ed":
        exploratory[0]["classification"] = "EXPERT_DOMINATES"
        s2["evaluation_sets"]["s2_exploratory"]["aggregate"] = _aggregate(exploratory)
    elif failure == "new_family":
        primary[3]["decision_family"] = "brand_new_failure"
    else:
        primary[2]["classification"] = "EXPERT_DOMINATES"
        primary[2]["decision_family"] = "attack"
        aggregate = _aggregate(primary)
        s2["evaluation_sets"]["paired_primary"]["aggregate"] = aggregate
        s2["aggregate"] = aggregate
    _write_json(contract.s2_validation, s2)

    with pytest.raises(
        qualification.QualificationError,
        match="qualification|failure family|safety|source artifact hash",
    ):
        qualification.build_qualification_payload(
            contract, stage_recompute=_recompute(report)
        )


def test_stage4_uses_immutable_order_controls_not_point_five(tmp_path: Path):
    contract, report = _fixture(tmp_path)
    stage4 = report["stages"]["stage4"]
    # 56% actual-first looks good versus .5, but is >4pp below the frozen
    # actual-first S1 control (302/500) and therefore breaches the order floor.
    candidate = stage4["candidate_cells"][0]
    candidate["wins"] = 168
    candidate["losses"] = 132
    stage4["pooled"]["candidate"] = _pooled(stage4["candidate_cells"])
    _write_json(contract.stage_report, report)

    with pytest.raises(qualification.QualificationError, match="stage4.*gate"):
        qualification.build_qualification_payload(
            contract, stage_recompute=_recompute(report)
        )


def test_creator_is_atomic_write_once_and_verifier_recomputes(tmp_path: Path):
    contract, report = _fixture(tmp_path)
    recompute = _recompute(report)

    result = qualification.create_qualification(
        contract, stage_recompute=recompute
    )

    assert result["status"] == "QUALIFIED"
    assert contract.output.is_file()
    with pytest.raises(qualification.QualificationError, match="write-once"):
        qualification.create_qualification(contract, stage_recompute=recompute)

    tampered = json.loads(contract.output.read_text(encoding="utf-8"))
    tampered["rules"]["recomputed_validation"]["transitions"]["ed_to_non_ed"] = 99
    unsigned = dict(tampered)
    unsigned.pop("qualification_payload_sha256", None)
    tampered["qualification_payload_sha256"] = qualification._object_sha256(unsigned)
    _write_json(contract.output, tampered)
    with pytest.raises(qualification.QualificationError, match="differs from recomputed"):
        qualification.verify_qualification_file(
            contract.output, contract, stage_recompute=recompute
        )


def test_stage_report_status_and_source_hash_are_not_trusted(tmp_path: Path):
    contract, report = _fixture(tmp_path)
    report["stages"]["stage2"]["decision"]["verdict"] = "KILL"
    _write_json(contract.stage_report, report)
    with pytest.raises(qualification.QualificationError, match="stage2 did not pass"):
        qualification.build_qualification_payload(
            contract, stage_recompute=_recompute(report)
        )

    contract, report = _fixture(tmp_path / "source")
    source = Path(report["stages"]["stage3"]["candidate_cells"][0]["source"]["path"])
    source.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(qualification.QualificationError, match="source artifact hash"):
        qualification.build_qualification_payload(
            contract, stage_recompute=_recompute(report)
        )


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        ("quality", "quality counts"),
        ("archetype", "opponent_archetype_episode_counts"),
        ("identity", "stable row identity"),
        ("numeric_string", "must be an integer"),
    ],
)
def test_independent_validation_reaggregation_rejects_tampering(
    tmp_path: Path, tamper: str, message: str
):
    contract, _report = _fixture(tmp_path)
    payload = json.loads(contract.s2_validation.read_text(encoding="utf-8"))
    primary = payload["evaluation_sets"]["paired_primary"]
    if tamper == "quality":
        primary["aggregate"]["quality_counts"]["candidate_policy_error_rows"] = 1
        payload["aggregate"] = primary["aggregate"]
    elif tamper == "archetype":
        primary["aggregate"]["opponent_archetype_episode_counts"] = {
            "tampered": 4
        }
        payload["aggregate"] = primary["aggregate"]
    elif tamper == "identity":
        primary["decision_rows"][0]["turn"] += 1
    else:
        payload["universe_counts"]["useful_prompt_count"] = "6"
    _write_json(contract.s2_validation, payload)

    with pytest.raises(qualification.QualificationError, match=message):
        qualification._verify_validations(contract)


def test_independent_validation_rejects_ed_shift_into_uncertifiable(tmp_path: Path):
    contract, _report = _fixture(tmp_path)
    payload = json.loads(contract.s2_validation.read_text(encoding="utf-8"))
    primary = payload["evaluation_sets"]["paired_primary"]
    rows = primary["decision_rows"]
    rows[0]["classification"] = "UNCERTIFIABLE"
    rows[0]["uncertifiable_reason"] = "rng"
    primary["aggregate"] = _aggregate(rows)
    payload["aggregate"] = primary["aggregate"]
    _write_json(contract.s2_validation, payload)

    with pytest.raises(qualification.QualificationError, match="safety rule"):
        qualification._verify_validations(contract)


def test_action_unstable_failure_family_is_candidate_name_agnostic():
    base = {
        "classification": "UNCERTIFIABLE",
        "decision_family": "attack_threshold",
        "proposal_error": None,
    }
    assert qualification._failure_family(
        {**base, "uncertifiable_reason": "s1_action_unstable"}
    ) == qualification._failure_family(
        {**base, "uncertifiable_reason": "candidate_action_unstable"}
    )
