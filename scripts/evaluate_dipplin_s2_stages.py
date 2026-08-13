#!/usr/bin/env python3
"""Fail-closed staged comparison of Dipplin S2 against exact S1 artifacts.

The evaluator only reads result artifacts named by a frozen JSON spec.  It does
not run games, inspect replays, or treat native-engine schedules as paired.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_SCHEMA = "dipplin-s2-stage-evaluation-spec-v1"
REPORT_SCHEMA = "dipplin-s2-stage-evaluation-v1"
RESULT_SCHEMA = "dipplin-authentic-evaluation-v1"
REPLAY_BASELINE_SCHEMA = "dipplin-replay-regret-v1"
REPLAY_CANDIDATE_SCHEMA = "dipplin-replay-regret-v2"
REPLAY_CLASSIFICATIONS = (
    "EQUIVALENT",
    "AGENT_DOMINATES",
    "EXPERT_DOMINATES",
    "INCOMPARABLE",
    "UNCERTIFIABLE",
)
SEQUENTIAL_STAGES = ("stage1", "stage2", "stage3", "stage4", "stage5", "stage6")
STAGE1_MINIMUM_PROMISING_DELTA = 0.03
STAGE1_STRONG_SIGNAL_DELTA = 0.05
FLOAT_COMPARISON_TOLERANCE = 1e-12
S2_PROOF_KEYS = (
    "s2_pre_attack_sequence_proof_checked",
    "s2_pre_attack_sequence_proof_admitted",
    "s2_pre_attack_sequence_proof_overrides",
)
QUALITY_KEYS = (
    "hero_policy_errors",
    "opponent_policy_errors",
    "hero_illegal_actions",
    "opponent_illegal_actions",
)
OPERATIONAL_TELEMETRY_MARKERS = (
    "error",
    "timeout",
    "cleanup",
    "failure",
    "unknown_context",
)
NONFATAL_SEARCH_FALLBACK_KEYS = {
    "d1_errors",
    "d1_timeouts",
    "d1_abstention_reason_engine_error",
    "d1_abstention_reason_timeout",
}
NONFATAL_SEARCH_FALLBACK_PREFIXES = ("d1_error_detail_",)
LATER_STAGE_DECISION_CONTRACT = {
    "stage2": {
        "screen": "serious_forced_second",
        "expected_actual_order": "second",
        "expected_matchups": ["A2", "d842", "AZ2.4a", "AZ2.7"],
        "requested_games_per_arm_per_matchup": 300,
        "require_zero_failures_policy_errors_illegal_actions": True,
        "minimum_candidate_pooled_win_rate": 0.5,
        "minimum_candidate_macro_win_rate": 0.5,
        "minimum_candidate_minus_s1_pooled_delta": 0.0,
        "catastrophic_matchup_drop_delta": -0.1,
        "strong_target_candidate_pooled_or_macro_win_rate": 0.55,
        "statistics": [
            "wilson_per_arm",
            "independent_newcombe_wilson_difference",
        ],
        "paired": False,
    },
    "stage3": {
        "screen": "forced_first_regression",
        "expected_actual_order": "first",
        "expected_matchups": ["A2", "d842", "AZ2.4a", "AZ2.7"],
        "requested_games_per_arm_per_matchup": 100,
        "require_zero_failures_policy_errors_illegal_actions": True,
        "minimum_candidate_minus_s1_pooled_delta": -0.04,
        "minimum_candidate_minus_s1_macro_delta": -0.04,
        "catastrophic_matchup_drop_delta": -0.1,
        "paired": False,
    },
    "stage4": {
        "screen": "same_deck_s2_vs_s1",
        "orders": ["first", "second"],
        "candidate_games_per_order": 300,
        "candidate_games_total": 600,
        "control_games_per_order": 500,
        "control_wins_by_order": {"first": 302, "second": 197},
        "require_zero_failures_policy_errors_illegal_actions": True,
        "minimum_pooled_s2_win_rate": 0.47,
        "minimum_candidate_minus_control_pooled_delta": -0.03,
        "minimum_candidate_minus_control_each_order_delta": -0.04,
        "require_no_significant_loss": True,
        "significant_loss_definition": (
            "Reject if a relevant independent Newcombe candidate-minus-control "
            "difference 95% upper bound is below zero."
        ),
        "statistics": [
            "wilson_per_arm",
            "independent_newcombe_wilson_difference",
        ],
        "paired": False,
    },
    "stage5": {
        "screen": "paired_frozen_validation_regret",
        "split": "VALIDATION",
        "paired_by_episode_and_decision": True,
        "primary_only_for_improvement": True,
        "exploratory_improvements_can_help": False,
        "require_s2_expert_dominates_primary_count_below_s1": True,
        "require_s2_expert_dominates_primary_rate_below_s1": True,
        "require_favorable_ed_exits_exceed_reverse_ed_entries": True,
        "maximum_certified_exploratory_expert_dominates": 0,
        "maximum_certified_exploratory_incomparable": 0,
        "require_no_new_failure_family": True,
        "require_zero_candidate_policy_errors": True,
        "require_no_primary_incomparable_uncertifiable_burden_increase": True,
    },
}
STAGE4_CONTROL_CONTRACT = [
    {
        "id": "s1_vs_s1_first_500",
        "matchup": "S1",
        "opponent_name": "S1",
        "actual_order": "first",
        "path": "../../artifacts/general_strength/s1_mirror/s1_vs_s1_first_500.json",
        "artifact_sha256": "c1dd38044323376cf090c95e834718b029af323a48e815a24f74455c2d3fc286",
        "requested_games": 500,
        "expected_wins": 302,
        "tree_sha256": "940654489ea1f286982226f1f0cba4dd7340378b997a3f88ab6915c5d67f6c98",
        "archive_sha256": "ec74efe096473c58a2057cabfee93bf337bc18848c202a6e3d36bcba802db171",
    },
    {
        "id": "s1_vs_s1_second_500",
        "matchup": "S1",
        "opponent_name": "S1",
        "actual_order": "second",
        "path": "../../artifacts/general_strength/s1_mirror/s1_vs_s1_second_500.json",
        "artifact_sha256": "5ef530f3bec98947d09700ed818c572fd0347b6f1a91f8b329ae224540447e6d",
        "requested_games": 500,
        "expected_wins": 197,
        "tree_sha256": "940654489ea1f286982226f1f0cba4dd7340378b997a3f88ab6915c5d67f6c98",
        "archive_sha256": "ec74efe096473c58a2057cabfee93bf337bc18848c202a6e3d36bcba802db171",
    },
]
STAGE4_CONTROL_EVALUATION_CONTRACT = {
    "deck_a_sha256": "269bc5808a0db862c7afe8f2daaa3d0b3b6e3c68bd651dd515d14f9d85392326",
    "engine_sha256": "7a157f045d333f99d1996d49c12bdbdd148072a619af246385c7295518776e30",
    "evaluator_sha256": "d7d4a3d21f7a2a8f066165caa96696719db33186234ce7ca3e9ea314f6878755",
    "external_adapter_sha256": "f18294f2e1ee60630fdcc8a63422aa1115365a0b31edeb4ffa6079a270944283",
    "evaluation_schema_sha256": "bc111f3f2e539b89d2b5ac2ed3a5447e5e2db1f4d7adbcdf7089c8541de7fcf4",
}
STAGE5_BASELINE_CONTRACT = {
    "path": "../../artifacts/general_strength/replay/validation_regret_s1.json",
    "artifact_sha256": "9f1205b2b282b2da37bc284054f51a3ebce7214507da7da4fa75309d5870e87d",
    "schema": REPLAY_BASELINE_SCHEMA,
    "split": "VALIDATION",
    "sealed": False,
    "decision_count": 1145,
    "episode_count": 50,
    "record_id_sequence_sha256": "c41f7a918033fac52212193c759264b81d1b2f379346c33c0ab7a5ae36c6863b",
    "classification_counts": {
        "EQUIVALENT": 658,
        "AGENT_DOMINATES": 10,
        "EXPERT_DOMINATES": 17,
        "INCOMPARABLE": 16,
        "UNCERTIFIABLE": 444,
    },
    "expert_dominates_episode_rate": 0.014166666666666666,
}
STAGE5_RUN_CONTRACT = {
    "baseline_package": {
        "archive_sha256": "ec74efe096473c58a2057cabfee93bf337bc18848c202a6e3d36bcba802db171",
        "manifest_sha256": "4071c03a020446436b8d33e1951fdaf5229ae4ab760a8283dc7d6f323e02f92c",
        "extracted_tree_sha256": "940654489ea1f286982226f1f0cba4dd7340378b997a3f88ab6915c5d67f6c98",
        "runtime_source_tree_sha256": "d5aaefab29b5850b298810c21dc628880822381c05bdbad5ecea1716bcef4241",
    },
    "candidate_package": {
        "archive_sha256": "813fab9efd432738856e7d7b784809c7b0c5aef51b3c677d7205f203490d1510",
        "manifest_sha256": "4801239bc3d328909bbd4e5461b84b140dd8931e3b581636ecbc662a97bad1bc",
        "extracted_tree_sha256": "c822bb76fa40a138a6bb07fcfd6e6cc58f8ade0dd65c49425bc703f3170da922",
        "runtime_source_tree_sha256": "b4290fff9b4fa3374f1bc14b7eefd6e9309dc13f3dcbebb2d9e4ea167650189f",
    },
    "replay_run": {
        "validation_manifest_file_sha256": "f147f14c670223b22bf9cba28f6ea166a4bbb5153c0efea941c61f39ff2bb163",
        "validation_manifest_payload_sha256": "d6cc5a7339dcc466546e68c8ea29301c150966be1f287adc00003bd86716c4c1",
        "baseline_s1_validation_result_sha256": "9f1205b2b282b2da37bc284054f51a3ebce7214507da7da4fa75309d5870e87d",
        "parameters": {
            "cap_per_episode": 24,
            "sample_seed": 20260813,
            "bootstrap_samples": 10000,
            "repeat_passes": 2,
            "proposal_repeats": 3,
        },
        "evaluator": {
            "path": "scripts/evaluate_dipplin_replay_regret.py",
            "sha256": "3F18456B0AE14A967F4443736E72EB95D4C7CB1823C6CD0735F3DE94E4F678A7",
            "git_blob_sha1": "D0DEED4A71E970F540E17CF489D4DF3EDAE70711",
        },
    },
    "exploratory_hard_ceiling": 256,
}


class StageEvaluationError(ValueError):
    """Raised when frozen evidence fails an integrity or schema check."""


def _mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise StageEvaluationError(f"{field} must be an object")
    return value


def _sequence(value: object, *, field: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise StageEvaluationError(f"{field} must be an array")
    return value


def _string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise StageEvaluationError(f"{field} must be a non-empty string")
    return value


def _scalar_identifier(value: object, *, field: str) -> int | str:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise StageEvaluationError(f"{field} must be an integer or non-empty string")
    if isinstance(value, str) and not value:
        raise StageEvaluationError(f"{field} must be an integer or non-empty string")
    return value


def _integer(value: object, *, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise StageEvaluationError(f"{field} must be an integer >= {minimum}")
    return value


def _number(value: object, *, field: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StageEvaluationError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise StageEvaluationError(f"{field} must be a finite number")
    return result


def _counter(value: object, *, field: str) -> int:
    return _integer(value, field=field, minimum=0)


def _boolean(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise StageEvaluationError(f"{field} must be boolean")
    return value


def _same_number(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-12)


def _hash(value: object, *, field: str) -> str:
    digest = _string(value, field=field).lower()
    if len(digest) != 64:
        raise StageEvaluationError(f"{field} must be a SHA-256 digest")
    try:
        bytes.fromhex(digest)
    except ValueError as error:
        raise StageEvaluationError(f"{field} must be a SHA-256 digest") from error
    return digest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise StageEvaluationError(f"cannot read {path}: {error}") from error
    return digest.hexdigest()


def _object_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json(path: Path, *, field: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StageEvaluationError(f"cannot read {field} {path}: {error}") from error
    return _mapping(value, field=field)


def _resolve(spec_path: Path, raw: object, *, field: str) -> Path:
    path = Path(_string(raw, field=field))
    resolved = path.resolve() if path.is_absolute() else (spec_path.parent / path).resolve()
    _repo_relative_path(resolved, field=field)
    return resolved


def _repo_relative_path(path: Path, *, field: str) -> str:
    """Encode one verified repository file as a portable canonical POSIX path."""

    resolved = path.resolve()
    try:
        relative = resolved.relative_to(REPO_ROOT.resolve())
    except ValueError as error:
        raise StageEvaluationError(f"{field} escapes the repository") from error
    encoded = relative.as_posix()
    if not encoded or encoded == ".":
        raise StageEvaluationError(f"{field} must name a repository file")
    return encoded


def _resolve_report_path(raw: object, *, field: str) -> Path:
    """Decode a canonical report path against the repository, never the CWD."""

    encoded = _string(raw, field=field)
    path = Path(encoded)
    if path.is_absolute() or "\\" in encoded:
        raise StageEvaluationError(f"{field} is not a repo-relative POSIX path")
    resolved = (REPO_ROOT / path).resolve()
    if _repo_relative_path(resolved, field=field) != encoded:
        raise StageEvaluationError(f"{field} is not a canonical repository path")
    return resolved


def _validate_evidence_files(
    spec: Mapping[str, Any], *, spec_path: Path
) -> list[dict[str, str]]:
    evidence = _sequence(spec.get("evidence_files"), field="evidence_files")
    if not evidence:
        raise StageEvaluationError("evidence_files must not be empty")
    result: list[dict[str, str]] = []
    identifiers: set[str] = set()
    for offset, value in enumerate(evidence):
        item = _mapping(value, field=f"evidence_files[{offset}]")
        identifier = _string(item.get("id"), field=f"evidence_files[{offset}].id")
        if identifier in identifiers:
            raise StageEvaluationError(f"duplicate evidence id {identifier}")
        identifiers.add(identifier)
        path = _resolve(
            spec_path, item.get("path"), field=f"evidence_files[{offset}].path"
        )
        expected = _hash(
            item.get("sha256"), field=f"evidence_files[{offset}].sha256"
        )
        actual = sha256_file(path)
        if actual != expected:
            raise StageEvaluationError(f"evidence file {identifier} hash mismatch")
        result.append(
            {
                "id": identifier,
                "path": _repo_relative_path(
                    path, field=f"evidence_files[{offset}].path"
                ),
                "sha256": actual,
            }
        )
    return result


def _validate_package_manifest(
    identity: Mapping[str, Any], *, spec_path: Path, field: str
) -> dict[str, Any]:
    declaration = _mapping(
        identity.get("package_manifest"), field=f"{field}.package_manifest"
    )
    path = _resolve(
        spec_path, declaration.get("path"), field=f"{field}.package_manifest.path"
    )
    expected_hash = _hash(
        declaration.get("sha256"), field=f"{field}.package_manifest.sha256"
    )
    actual_hash = sha256_file(path)
    if actual_hash != expected_hash:
        raise StageEvaluationError(f"{field}.package_manifest hash mismatch")
    manifest = _read_json(path, field=f"{field}.package_manifest")
    expected_variant = _string(identity.get("variant"), field=f"{field}.variant")
    if manifest.get("variant") != expected_variant:
        raise StageEvaluationError(f"{field}.package_manifest variant mismatch")
    output = _mapping(manifest.get("output"), field=f"{field}.package_manifest.output")
    tree = _hash(output.get("extracted_tree_sha256"), field=f"{field}.manifest.tree")
    archive = _hash(output.get("archive_sha256"), field=f"{field}.manifest.archive")
    if tree != _hash(identity.get("tree_sha256"), field=f"{field}.tree_sha256"):
        raise StageEvaluationError(f"{field}.package_manifest tree mismatch")
    if archive != _hash(
        identity.get("archive_sha256"), field=f"{field}.archive_sha256"
    ):
        raise StageEvaluationError(f"{field}.package_manifest archive mismatch")
    expected_configuration = identity.get("expected_runtime_configuration")
    if expected_configuration is not None:
        expected = _mapping(
            expected_configuration,
            field=f"{field}.expected_runtime_configuration",
        )
        runtime = _mapping(manifest.get("runtime"), field=f"{field}.manifest.runtime")
        actual = _mapping(
            runtime.get("evaluated_configuration"),
            field=f"{field}.manifest.runtime.evaluated_configuration",
        )
        for key, value in expected.items():
            if actual.get(key) != value:
                raise StageEvaluationError(
                    f"{field}.package_manifest runtime setting {key} mismatch"
                )
    expected_values = _mapping(
        identity.get("expected_manifest_values"),
        field=f"{field}.expected_manifest_values",
    )
    for dotted_path, expected in expected_values.items():
        path_parts = _string(
            dotted_path, field=f"{field}.expected_manifest_values key"
        ).split(".")
        actual: object = manifest
        for part in path_parts:
            if not isinstance(actual, Mapping) or part not in actual:
                raise StageEvaluationError(
                    f"{field}.package_manifest lacks {dotted_path}"
                )
            actual = actual[part]
        if actual != expected:
            raise StageEvaluationError(
                f"{field}.package_manifest {dotted_path} mismatch"
            )
    return {
        "path": _repo_relative_path(path, field=f"{field}.package_manifest.path"),
        "sha256": actual_hash,
        "variant": expected_variant,
    }


def wilson(wins: int, games: int, z: float = 1.959963984540054) -> list[float]:
    """Two-sided Wilson score interval, matching the audited D0/D1 comparator."""

    if games <= 0:
        return [0.0, 1.0]
    proportion = wins / games
    denominator = 1.0 + z * z / games
    center = (proportion + z * z / (2.0 * games)) / denominator
    margin = (
        z
        * math.sqrt(
            (proportion * (1.0 - proportion) + z * z / (4.0 * games))
            / games
        )
        / denominator
    )
    return [max(0.0, center - margin), min(1.0, center + margin)]


def independent_difference(
    candidate: Mapping[str, Any], baseline: Mapping[str, Any]
) -> dict[str, Any]:
    """Newcombe hybrid-score interval for two independent binomial arms."""

    n1, w1 = int(candidate["games"]), int(candidate["wins"])
    n0, w0 = int(baseline["games"]), int(baseline["wins"])
    if n1 <= 0 or n0 <= 0:
        return {
            "estimate": 0.0,
            "confidence_95": [-1.0, 1.0],
            "method": "independent_newcombe_wilson_difference",
            "paired": False,
        }
    p1, p0 = w1 / n1, w0 / n0
    l1, u1 = wilson(w1, n1)
    l0, u0 = wilson(w0, n0)
    lower = p1 - p0 - math.sqrt((p1 - l1) ** 2 + (u0 - p0) ** 2)
    upper = p1 - p0 + math.sqrt((u1 - p1) ** 2 + (p0 - l0) ** 2)
    return {
        "estimate": p1 - p0,
        "confidence_95": [max(-1.0, lower), min(1.0, upper)],
        "method": "independent_newcombe_wilson_difference",
        "paired": False,
    }


def _latency(value: object, *, field: str) -> dict[str, int | float]:
    source = _mapping(value, field=field)
    count = _counter(source.get("count"), field=f"{field}.count")
    result: dict[str, int | float] = {"count": count}
    for key in ("mean", "p50", "p95", "p99", "max"):
        result[key] = _number(source.get(key), field=f"{field}.{key}", minimum=0.0)
    if not (
        float(result["p50"])
        <= float(result["p95"])
        <= float(result["p99"])
        <= float(result["max"])
    ):
        raise StageEvaluationError(f"{field} quantiles/max are not monotonic")
    if float(result["mean"]) > float(result["max"]):
        raise StageEvaluationError(f"{field}.mean exceeds max")
    return result


def _proof_counter(value: object, *, field: str) -> float:
    result = _number(value, field=field, minimum=0.0)
    if not result.is_integer():
        raise StageEvaluationError(f"{field} must be an integer-valued counter")
    return result


def _is_operational_telemetry_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in OPERATIONAL_TELEMETRY_MARKERS)


def _is_nonfatal_search_fallback(key: str) -> bool:
    return key in NONFATAL_SEARCH_FALLBACK_KEYS or key.startswith(
        NONFATAL_SEARCH_FALLBACK_PREFIXES
    )


def _artifact_summary(
    declaration_value: object,
    *,
    spec_path: Path,
    identity: Mapping[str, Any],
    evaluation_contract: Mapping[str, Any],
    opponent_contracts: Mapping[str, Any],
    role: str,
) -> dict[str, Any]:
    declaration = _mapping(declaration_value, field=f"{role} cell")
    cell_id = _string(declaration.get("id"), field=f"{role}.id")
    matchup = _string(declaration.get("matchup"), field=f"{role}.{cell_id}.matchup")
    opponent_name = _string(
        declaration.get("opponent_name"),
        field=f"{role}.{cell_id}.opponent_name",
    )
    opponent_contract = _mapping(
        opponent_contracts.get(matchup), field=f"opponents.{matchup}"
    )
    if opponent_contract.get("opponent_name") != opponent_name:
        raise StageEvaluationError(f"{role}.{cell_id} opponent contract mismatch")
    order = _string(
        declaration.get("actual_order"), field=f"{role}.{cell_id}.actual_order"
    )
    if order not in {"first", "second"}:
        raise StageEvaluationError(f"{role}.{cell_id}.actual_order is invalid")
    requested = _integer(
        declaration.get("requested_games"),
        field=f"{role}.{cell_id}.requested_games",
        minimum=1,
    )
    artifact_path = _resolve(
        spec_path, declaration.get("path"), field=f"{role}.{cell_id}.path"
    )
    expected_artifact_hash = _hash(
        declaration.get("artifact_sha256"),
        field=f"{role}.{cell_id}.artifact_sha256",
    )
    actual_artifact_hash = sha256_file(artifact_path)
    if actual_artifact_hash != expected_artifact_hash:
        raise StageEvaluationError(
            f"{role}.{cell_id} artifact hash mismatch: "
            f"expected {expected_artifact_hash}, got {actual_artifact_hash}"
        )
    artifact = _read_json(artifact_path, field=f"{role}.{cell_id} artifact")
    if artifact.get("schema") != RESULT_SCHEMA:
        raise StageEvaluationError(f"{role}.{cell_id} has an unsupported result schema")
    if artifact.get("opponent_name") != opponent_name:
        raise StageEvaluationError(f"{role}.{cell_id}.opponent_name mismatch")
    expected_hero_name = _string(
        identity.get("result_hero_name"), field=f"{role}.result_hero_name"
    )
    if artifact.get("hero_name") != expected_hero_name:
        raise StageEvaluationError(f"{role}.{cell_id}.hero_name mismatch")

    rows_value = _sequence(
        artifact.get("game_rows"), field=f"{role}.{cell_id}.game_rows"
    )
    if len(rows_value) != requested:
        raise StageEvaluationError(
            f"{role}.{cell_id} row count {len(rows_value)} != requested {requested}"
        )

    row_totals = {
        "games": 0,
        "wins": 0,
        "draws": 0,
        "failed_games": 0,
        **{key: 0 for key in QUALITY_KEYS},
    }
    proof_totals = {key: 0.0 for key in S2_PROOF_KEYS}
    expected_s2_enabled = _boolean(
        identity.get("expected_s2_enabled"), field=f"{role}.expected_s2_enabled"
    )
    s2_enabled_total = 0.0
    operational_telemetry_totals: dict[str, float] = {}
    override_games: list[dict[str, Any]] = []
    game_indices: set[int] = set()
    hero_seat_counts = {0: 0, 1: 0}
    row_latency_count = 0
    for offset, row_value in enumerate(rows_value):
        field = f"{role}.{cell_id}.game_rows[{offset}]"
        row = _mapping(row_value, field=field)
        game_index = _integer(row.get("game_index"), field=f"{field}.game_index")
        if game_index in game_indices:
            raise StageEvaluationError(
                f"{role}.{cell_id} repeats game_index {game_index}"
            )
        game_indices.add(game_index)
        if row.get("hero_name") != expected_hero_name:
            raise StageEvaluationError(f"{field}.hero_name mismatch")
        if row.get("opponent_name") != opponent_name:
            raise StageEvaluationError(f"{field}.opponent_name mismatch")
        hero_seat = _integer(row.get("hero_seat"), field=f"{field}.hero_seat")
        opponent_seat = _integer(
            row.get("opponent_seat"), field=f"{field}.opponent_seat"
        )
        first_player = _integer(
            row.get("first_player"), field=f"{field}.first_player"
        )
        if hero_seat not in (0, 1) or opponent_seat != 1 - hero_seat:
            raise StageEvaluationError(f"{field} has invalid seat accounting")
        if first_player not in (0, 1):
            raise StageEvaluationError(f"{field}.first_player is invalid")
        derived_order = "first" if first_player == hero_seat else "second"
        if derived_order != order:
            raise StageEvaluationError(f"{field} seat/order accounting mismatch")
        hero_seat_counts[hero_seat] += 1
        if row.get("actual_order") != order:
            raise StageEvaluationError(f"{field}.actual_order does not match {order}")
        if not isinstance(row.get("completed"), bool):
            raise StageEvaluationError(f"{field}.completed must be boolean")
        completed = bool(row["completed"])
        win = _counter(row.get("win"), field=f"{field}.win")
        draw = _counter(row.get("draw"), field=f"{field}.draw")
        if win not in (0, 1) or draw not in (0, 1) or win + draw > 1:
            raise StageEvaluationError(f"{field} has invalid win/draw indicators")
        if not completed and (win or draw):
            raise StageEvaluationError(f"{field} records an outcome for a failed game")
        outcome = _string(row.get("outcome"), field=f"{field}.outcome")
        cleanup_errors = _sequence(
            row.get("cleanup_errors"), field=f"{field}.cleanup_errors"
        )
        result_seat = row.get("result_seat")
        if completed:
            if row.get("failure") is not None or cleanup_errors:
                raise StageEvaluationError(f"{field} completed with failure metadata")
            expected_outcome = "win" if win else "draw" if draw else "loss"
            if outcome != expected_outcome:
                raise StageEvaluationError(f"{field}.outcome is inconsistent")
            if not isinstance(result_seat, int) or isinstance(result_seat, bool):
                raise StageEvaluationError(f"{field}.result_seat is invalid")
            if win and result_seat != hero_seat:
                raise StageEvaluationError(f"{field}.result_seat contradicts win")
            if not win and not draw and result_seat != opponent_seat:
                raise StageEvaluationError(f"{field}.result_seat contradicts loss")
            if draw and result_seat in (0, 1):
                raise StageEvaluationError(f"{field}.result_seat contradicts draw")
        elif outcome != "failed" or result_seat is not None:
            raise StageEvaluationError(f"{field} has invalid failed-game metadata")
        if completed:
            row_totals["games"] += 1
            row_totals["wins"] += win
            row_totals["draws"] += draw
        else:
            row_totals["failed_games"] += 1
        for key in QUALITY_KEYS:
            row_totals[key] += _counter(row.get(key), field=f"{field}.{key}")

        telemetry = _mapping(row.get("hero_telemetry"), field=f"{field}.hero_telemetry")
        for key, raw_value in telemetry.items():
            if not isinstance(key, str) or not _is_operational_telemetry_key(key):
                continue
            value = _proof_counter(raw_value, field=f"{field}.hero_telemetry.{key}")
            operational_telemetry_totals[key] = (
                operational_telemetry_totals.get(key, 0.0) + value
            )
        row_s2_enabled = _proof_counter(
            telemetry.get("s2_enabled", 0), field=f"{field}.s2_enabled"
        )
        expected_row_s2 = 1.0 if expected_s2_enabled else 0.0
        if row_s2_enabled != expected_row_s2:
            raise StageEvaluationError(f"{field}.s2_enabled mode mismatch")
        s2_enabled_total += row_s2_enabled
        row_proof: dict[str, float] = {}
        for key in S2_PROOF_KEYS:
            value = _proof_counter(telemetry.get(key, 0), field=f"{field}.{key}")
            row_proof[key] = value
            proof_totals[key] += value
        if not (
            row_proof[S2_PROOF_KEYS[0]]
            >= row_proof[S2_PROOF_KEYS[1]]
            >= row_proof[S2_PROOF_KEYS[2]]
        ):
            raise StageEvaluationError(f"{field} has inconsistent S2 proof counters")
        if row_proof[S2_PROOF_KEYS[2]] > 0:
            override_games.append(
                {
                    "cell_id": cell_id,
                    "game_index": game_index,
                    "completed": completed,
                    "outcome": _string(row.get("outcome"), field=f"{field}.outcome"),
                    "override_count": int(row_proof[S2_PROOF_KEYS[2]]),
                }
            )
        row_latency = _latency(
            row.get("hero_latency_ms"), field=f"{field}.hero_latency_ms"
        )
        row_latency_count += int(row_latency["count"])

    if game_indices != set(range(requested)):
        raise StageEvaluationError(f"{role}.{cell_id} game indices are not 0..N-1")
    if abs(hero_seat_counts[0] - hero_seat_counts[1]) > 1:
        raise StageEvaluationError(
            f"{role}.{cell_id} physical hero seats are unbalanced"
        )

    scheduled_games = _integer(
        artifact.get("scheduled_games"), field=f"{role}.{cell_id}.scheduled_games"
    )
    if scheduled_games != requested:
        raise StageEvaluationError(
            f"{role}.{cell_id}.scheduled_games {scheduled_games} "
            f"!= requested {requested}"
        )
    top_checks = {
        "games": "games",
        "wins_a": "wins",
        "failed_games": "failed_games",
        **{key: key for key in QUALITY_KEYS},
    }
    for artifact_key, total_key in top_checks.items():
        actual = _counter(
            artifact.get(artifact_key), field=f"{role}.{cell_id}.{artifact_key}"
        )
        if actual != row_totals[total_key]:
            raise StageEvaluationError(
                f"{role}.{cell_id}.{artifact_key} disagrees with game_rows"
            )
    if row_totals["games"] + row_totals["failed_games"] != requested:
        raise StageEvaluationError(f"{role}.{cell_id} game accounting is incomplete")
    expected_rate = (
        row_totals["wins"] / row_totals["games"] if row_totals["games"] else 0.0
    )
    top_rate = _number(
        artifact.get("win_rate_a"), field=f"{role}.{cell_id}.win_rate_a"
    )
    if not _same_number(top_rate, expected_rate):
        raise StageEvaluationError(f"{role}.{cell_id}.win_rate_a mismatch")
    top_wilson = _sequence(
        artifact.get("wilson_95"), field=f"{role}.{cell_id}.wilson_95"
    )
    if len(top_wilson) != 2 or any(
        not _same_number(
            _number(value, field=f"{role}.{cell_id}.wilson_95"), expected
        )
        for value, expected in zip(
            top_wilson, wilson(row_totals["wins"], row_totals["games"])
        )
    ):
        raise StageEvaluationError(f"{role}.{cell_id}.wilson_95 mismatch")
    if artifact.get("forced_actual_order") != order:
        raise StageEvaluationError(f"{role}.{cell_id}.forced_actual_order mismatch")
    if artifact.get("forced_order_accounting_complete") is not True:
        raise StageEvaluationError(
            f"{role}.{cell_id} forced-order accounting is incomplete"
        )

    overall = _mapping(artifact.get("overall"), field=f"{role}.{cell_id}.overall")
    overall_checks = {
        "scheduled_games": requested,
        "games": row_totals["games"],
        "wins": row_totals["wins"],
        "draws": row_totals["draws"],
        "losses": row_totals["games"] - row_totals["wins"] - row_totals["draws"],
        "failed_games": row_totals["failed_games"],
        **{key: row_totals[key] for key in QUALITY_KEYS},
    }
    for key, expected in overall_checks.items():
        actual = _counter(
            overall.get(key), field=f"{role}.{cell_id}.overall.{key}"
        )
        if actual != expected:
            raise StageEvaluationError(f"{role}.{cell_id}.overall.{key} mismatch")
    overall_rate = _number(
        overall.get("win_rate"), field=f"{role}.{cell_id}.overall.win_rate"
    )
    if not _same_number(overall_rate, expected_rate):
        raise StageEvaluationError(f"{role}.{cell_id}.overall.win_rate mismatch")
    overall_wilson = _sequence(
        overall.get("wilson_95"), field=f"{role}.{cell_id}.overall.wilson_95"
    )
    if len(overall_wilson) != 2 or any(
        not _same_number(
            _number(value, field=f"{role}.{cell_id}.overall.wilson_95"), expected
        )
        for value, expected in zip(
            overall_wilson, wilson(row_totals["wins"], row_totals["games"])
        )
    ):
        raise StageEvaluationError(f"{role}.{cell_id}.overall.wilson_95 mismatch")

    expected_tree = _hash(identity.get("tree_sha256"), field=f"{role}.tree_sha256")
    expected_archive = _hash(
        identity.get("archive_sha256"), field=f"{role}.archive_sha256"
    )
    provenance = _mapping(
        artifact.get("artifact_provenance"),
        field=f"{role}.{cell_id}.artifact_provenance",
    )
    for key in ("submission_a_sha256", "post_evaluation_submission_a_sha256"):
        actual = _hash(provenance.get(key), field=f"{role}.{cell_id}.{key}")
        if actual != expected_tree:
            raise StageEvaluationError(f"{role}.{cell_id}.{key} tree mismatch")
    actual_archive = _hash(
        provenance.get("archive_a_sha256"), field=f"{role}.{cell_id}.archive_a_sha256"
    )
    if actual_archive != expected_archive:
        raise StageEvaluationError(f"{role}.{cell_id}.archive_a_sha256 mismatch")
    provenance_hashes: dict[str, str] = {}
    for key in (
        "deck_a_sha256",
        "engine_sha256",
        "evaluator_sha256",
        "external_adapter_sha256",
        "evaluation_schema_sha256",
    ):
        expected = _hash(
            evaluation_contract.get(key), field=f"evaluation_contract.{key}"
        )
        actual = _hash(provenance.get(key), field=f"{role}.{cell_id}.{key}")
        if actual != expected:
            raise StageEvaluationError(f"{role}.{cell_id}.{key} mismatch")
        provenance_hashes[key] = actual
    expected_opponent_tree = _hash(
        opponent_contract.get("tree_sha256"),
        field=f"opponents.{matchup}.tree_sha256",
    )
    for key in (
        "submission_b_sha256",
        "post_evaluation_submission_b_sha256",
        "artifact_b_sha256",
    ):
        actual = _hash(provenance.get(key), field=f"{role}.{cell_id}.{key}")
        if actual != expected_opponent_tree:
            raise StageEvaluationError(f"{role}.{cell_id}.{key} opponent mismatch")
        provenance_hashes[key] = actual
    expected_opponent_archive = opponent_contract.get("archive_sha256")
    if expected_opponent_archive is not None:
        actual_opponent_archive = _hash(
            provenance.get("archive_b_sha256"),
            field=f"{role}.{cell_id}.archive_b_sha256",
        )
        if actual_opponent_archive != _hash(
            expected_opponent_archive,
            field=f"opponents.{matchup}.archive_sha256",
        ):
            raise StageEvaluationError(
                f"{role}.{cell_id}.archive_b_sha256 opponent mismatch"
            )
        provenance_hashes["archive_b_sha256"] = actual_opponent_archive
    expected_opponent_deck = _hash(
        opponent_contract.get("deck_sha256"),
        field=f"opponents.{matchup}.deck_sha256",
    )
    actual_opponent_deck = _hash(
        provenance.get("deck_b_sha256"), field=f"{role}.{cell_id}.deck_b_sha256"
    )
    if actual_opponent_deck != expected_opponent_deck:
        raise StageEvaluationError(f"{role}.{cell_id}.deck_b_sha256 mismatch")
    provenance_hashes["deck_b_sha256"] = actual_opponent_deck
    if provenance.get("forced_actual_order") != order:
        raise StageEvaluationError(f"{role}.{cell_id} provenance order mismatch")
    if provenance.get("submission_artifacts_unchanged_during_evaluation") is not True:
        raise StageEvaluationError(
            f"{role}.{cell_id} artifacts changed during evaluation"
        )
    runtime_environment = _mapping(
        provenance.get("runtime_environment"),
        field=f"{role}.{cell_id}.runtime_environment",
    )
    process_environment = _mapping(
        provenance.get("process_behavior_environment"),
        field=f"{role}.{cell_id}.process_behavior_environment",
    )
    max_decisions = _integer(
        provenance.get("max_decisions"), field=f"{role}.{cell_id}.max_decisions"
    )
    blinding = _mapping(
        provenance.get("runtime_blinding_contract"),
        field=f"{role}.{cell_id}.runtime_blinding_contract",
    )
    if (
        blinding.get("hero_receives_opponent_label") is not False
        or blinding.get("hero_receives_opponent_package_identity") is not False
        or blinding.get("agent_call_payload") != "engine_observation_only"
        or blinding.get("labels_added_in_parent_after_game") is not True
    ):
        raise StageEvaluationError(f"{role}.{cell_id} runtime blinding mismatch")
    provenance_rng = _mapping(
        provenance.get("rng_contract"), field=f"{role}.{cell_id}.rng_contract"
    )
    if (
        provenance_rng.get("engine") != "independent_std_random_device"
        or provenance_rng.get("paired_deals") is not False
        or provenance_rng.get("common_random_numbers") is not False
    ):
        raise StageEvaluationError(f"{role}.{cell_id} provenance RNG is not unpaired")
    result_rng = _mapping(
        artifact.get("rng_provenance"), field=f"{role}.{cell_id}.rng_provenance"
    )
    if (
        result_rng.get("engine") != "unpaired_std_random_device"
        or result_rng.get("paired_deals") is not False
        or result_rng.get("common_random_numbers") is not False
    ):
        raise StageEvaluationError(f"{role}.{cell_id} result RNG is not unpaired")

    expected_wins = declaration.get("expected_wins")
    if expected_wins is not None and _counter(
        expected_wins, field=f"{role}.{cell_id}.expected_wins"
    ) != row_totals["wins"]:
        raise StageEvaluationError(f"{role}.{cell_id}.expected_wins mismatch")

    top_latency = _mapping(
        artifact.get("latency_ms"), field=f"{role}.{cell_id}.latency_ms"
    )
    hero_latency = _latency(
        top_latency.get("hero"), field=f"{role}.{cell_id}.latency_ms.hero"
    )
    if int(hero_latency["count"]) != row_latency_count:
        raise StageEvaluationError(
            f"{role}.{cell_id} latency count disagrees with rows"
        )

    top_telemetry = _mapping(
        artifact.get("hero_telemetry"), field=f"{role}.{cell_id}.hero_telemetry"
    )
    top_s2_enabled = _proof_counter(
        top_telemetry.get("s2_enabled", 0),
        field=f"{role}.{cell_id}.hero_telemetry.s2_enabled",
    )
    if top_s2_enabled != s2_enabled_total:
        raise StageEvaluationError(
            f"{role}.{cell_id}.hero_telemetry.s2_enabled disagrees with rows"
        )
    for key, expected in proof_totals.items():
        actual = _proof_counter(
            top_telemetry.get(key, 0), field=f"{role}.{cell_id}.hero_telemetry.{key}"
        )
        if actual != expected:
            raise StageEvaluationError(
                f"{role}.{cell_id}.hero_telemetry.{key} disagrees with rows"
            )
    top_operational_keys = {
        key
        for key in top_telemetry
        if isinstance(key, str) and _is_operational_telemetry_key(key)
    }
    if top_operational_keys != set(operational_telemetry_totals):
        raise StageEvaluationError(
            f"{role}.{cell_id} operational telemetry key set disagrees with rows"
        )
    for key, expected in operational_telemetry_totals.items():
        actual = _proof_counter(
            top_telemetry.get(key), field=f"{role}.{cell_id}.hero_telemetry.{key}"
        )
        if actual != expected:
            raise StageEvaluationError(
                f"{role}.{cell_id}.hero_telemetry.{key} disagrees with rows"
            )

    nonfatal_search_fallbacks = {
        key: int(value)
        for key, value in sorted(operational_telemetry_totals.items())
        if value and _is_nonfatal_search_fallback(key)
    }
    fatal_operational_telemetry = {
        key: int(value)
        for key, value in sorted(operational_telemetry_totals.items())
        if value and not _is_nonfatal_search_fallback(key)
    }

    games = row_totals["games"]
    wins = row_totals["wins"]
    return {
        "id": cell_id,
        "matchup": matchup,
        "opponent_name": opponent_name,
        "actual_order": order,
        "source": {
            "path": _repo_relative_path(
                artifact_path, field=f"{role}.{cell_id}.path"
            ),
            "artifact_sha256": actual_artifact_hash,
            "tree_sha256": expected_tree,
            "archive_sha256": expected_archive,
        },
        "evaluation_identity": {
            "hero_name": expected_hero_name,
            "opponent_name": opponent_name,
            "s2_enabled": expected_s2_enabled,
            "runtime_environment": dict(runtime_environment),
            "process_behavior_environment": dict(process_environment),
            "max_decisions": max_decisions,
            **provenance_hashes,
        },
        "scheduled_games": requested,
        "games": games,
        "wins": wins,
        "draws": row_totals["draws"],
        "losses": games - wins - row_totals["draws"],
        "failed_games": row_totals["failed_games"],
        "win_rate": wins / games if games else 0.0,
        "wilson_95": wilson(wins, games),
        **{key: row_totals[key] for key in QUALITY_KEYS},
        "latency_ms": hero_latency,
        "operational_telemetry": {
            "nonfatal_search_fallback_counts": nonfatal_search_fallbacks,
            "fatal_counts": fatal_operational_telemetry,
            "fatal_count": sum(fatal_operational_telemetry.values()),
            "policy": (
                "D1 engine-error/node-budget and timeout counters are explicit "
                "search abstentions with baseline fallback; unknown error, timeout, "
                "cleanup, failure, or unknown-context counters are fatal."
            ),
        },
        "s2_proof": {
            "checked": int(proof_totals[S2_PROOF_KEYS[0]]),
            "admitted": int(proof_totals[S2_PROOF_KEYS[1]]),
            "overrides": int(proof_totals[S2_PROOF_KEYS[2]]),
            "games_with_override_count": len(override_games),
            "completed_games_with_override_count": sum(
                int(game["completed"]) for game in override_games
            ),
            "completed_game_override_rate": (
                sum(int(game["completed"]) for game in override_games) / games
                if games
                else 0.0
            ),
            "games_with_override": sorted(
                override_games, key=lambda item: int(item["game_index"])
            ),
            "source": "exact hero_telemetry s2_pre_attack_sequence_proof_* counters",
            "d1_intervention_fields_used": False,
        },
    }


def _aggregate(cells: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    selected = list(cells)
    totals = {
        "scheduled_games": sum(int(cell["scheduled_games"]) for cell in selected),
        "games": sum(int(cell["games"]) for cell in selected),
        "wins": sum(int(cell["wins"]) for cell in selected),
        "draws": sum(int(cell["draws"]) for cell in selected),
        "losses": sum(int(cell["losses"]) for cell in selected),
        "failed_games": sum(int(cell["failed_games"]) for cell in selected),
        **{
            key: sum(int(cell[key]) for cell in selected)
            for key in QUALITY_KEYS
        },
    }
    nonfatal_fallbacks: dict[str, int] = {}
    fatal_counts: dict[str, int] = {}
    for cell in selected:
        operational = _mapping(
            cell.get("operational_telemetry"), field="cell.operational_telemetry"
        )
        for output, source_key in (
            (nonfatal_fallbacks, "nonfatal_search_fallback_counts"),
            (fatal_counts, "fatal_counts"),
        ):
            source = _mapping(
                operational.get(source_key), field=f"operational.{source_key}"
            )
            for key, value in source.items():
                output[str(key)] = output.get(str(key), 0) + int(value)
    totals["operational_telemetry"] = {
        "nonfatal_search_fallback_counts": dict(sorted(nonfatal_fallbacks.items())),
        "fatal_counts": dict(sorted(fatal_counts.items())),
        "fatal_count": sum(fatal_counts.values()),
    }
    games = totals["games"]
    wins = totals["wins"]
    totals["win_rate"] = wins / games if games else 0.0
    totals["wilson_95"] = wilson(wins, games)
    return totals


def _aggregate_latency(cells: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    selected = list(cells)
    count = sum(int(cell["latency_ms"]["count"]) for cell in selected)
    weighted = sum(
        int(cell["latency_ms"]["count"]) * float(cell["latency_ms"]["mean"])
        for cell in selected
    )
    return {
        "count": count,
        "weighted_mean": weighted / count if count else 0.0,
        "p50_max_across_cells": max(
            (float(cell["latency_ms"]["p50"]) for cell in selected), default=0.0
        ),
        "p95_max_across_cells": max(
            (float(cell["latency_ms"]["p95"]) for cell in selected), default=0.0
        ),
        "p99_max_across_cells": max(
            (float(cell["latency_ms"]["p99"]) for cell in selected), default=0.0
        ),
        "max": max(
            (float(cell["latency_ms"]["max"]) for cell in selected), default=0.0
        ),
        "quantile_note": (
            "Cross-cell quantiles are maxima, not fabricated pooled quantiles."
        ),
    }


def _aggregate_proof(cells: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    selected = list(cells)
    games = [
        game
        for cell in selected
        for game in _sequence(
            _mapping(cell["s2_proof"], field="s2_proof").get("games_with_override"),
            field="s2_proof.games_with_override",
        )
    ]
    games.sort(key=lambda item: (str(item["cell_id"]), int(item["game_index"])))
    completed_games = sum(int(cell["games"]) for cell in selected)
    completed_override_games = sum(int(game["completed"]) for game in games)
    return {
        "checked": sum(int(cell["s2_proof"]["checked"]) for cell in selected),
        "admitted": sum(int(cell["s2_proof"]["admitted"]) for cell in selected),
        "overrides": sum(int(cell["s2_proof"]["overrides"]) for cell in selected),
        "games_with_override_count": len(games),
        "completed_games_with_override_count": completed_override_games,
        "completed_games": completed_games,
        "completed_game_override_rate": (
            completed_override_games / completed_games if completed_games else 0.0
        ),
        "games_with_override": games,
        "source": "exact game_rows hero_telemetry S2 counters",
        "d1_intervention_fields_used": False,
    }


def _group_cells(
    cells: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], list[Mapping[str, Any]]]:
    result: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for cell in cells:
        key = (str(cell["matchup"]), str(cell["actual_order"]))
        result.setdefault(key, []).append(cell)
    return result


def _stage_comparison(
    stage_name: str,
    stage: Mapping[str, Any],
    *,
    spec_path: Path,
    baseline_identity: Mapping[str, Any],
    candidate_identity: Mapping[str, Any],
    evaluation_contract: Mapping[str, Any],
    opponent_contracts: Mapping[str, Any],
    top_baselines: object,
) -> dict[str, Any]:
    expected_keys = (
        {"candidate_cells"}
        if stage_name == "stage1"
        else {"baseline_cells", "candidate_cells"}
    )
    if set(stage) != expected_keys:
        raise StageEvaluationError(
            f"stages.{stage_name} keys must be exactly {sorted(expected_keys)}"
        )
    baseline_values = top_baselines if stage_name == "stage1" else stage.get(
        "baseline_cells"
    )
    baseline_declarations = _sequence(
        baseline_values, field=f"stages.{stage_name}.baseline_cells"
    )
    candidate_declarations = _sequence(
        stage.get("candidate_cells"), field=f"stages.{stage_name}.candidate_cells"
    )
    if not baseline_declarations or not candidate_declarations:
        raise StageEvaluationError(f"stages.{stage_name} must declare both arms")
    baselines = [
        _artifact_summary(
            value,
            spec_path=spec_path,
            identity=baseline_identity,
            evaluation_contract=evaluation_contract,
            opponent_contracts=opponent_contracts,
            role=f"stages.{stage_name}.baseline",
        )
        for value in baseline_declarations
    ]
    candidates = [
        _artifact_summary(
            value,
            spec_path=spec_path,
            identity=candidate_identity,
            evaluation_contract=evaluation_contract,
            opponent_contracts=opponent_contracts,
            role=f"stages.{stage_name}.candidate",
        )
        for value in candidate_declarations
    ]
    for label, cells in (("baseline", baselines), ("candidate", candidates)):
        ids = [str(cell["id"]) for cell in cells]
        if len(ids) != len(set(ids)):
            raise StageEvaluationError(
                f"stages.{stage_name}.{label} has duplicate cell ids"
            )

    baseline_groups = _group_cells(baselines)
    candidate_groups = _group_cells(candidates)
    if set(baseline_groups) != set(candidate_groups):
        raise StageEvaluationError(
            f"stages.{stage_name} candidate matchup/order cells do not match baseline"
        )
    matchup_rows: dict[str, Any] = {}
    for matchup, order in sorted(baseline_groups):
        baseline_group = baseline_groups[(matchup, order)]
        candidate_group = candidate_groups[(matchup, order)]
        shared_identity_keys = {
            "opponent_name",
            "deck_a_sha256",
            "engine_sha256",
            "evaluator_sha256",
            "external_adapter_sha256",
            "evaluation_schema_sha256",
            "runtime_environment",
            "process_behavior_environment",
            "max_decisions",
            "submission_b_sha256",
            "post_evaluation_submission_b_sha256",
            "artifact_b_sha256",
            "deck_b_sha256",
        }
        identities = [
            {key: cell["evaluation_identity"].get(key) for key in shared_identity_keys}
            for cell in [*baseline_group, *candidate_group]
        ]
        if any(identity != identities[0] for identity in identities[1:]):
            raise StageEvaluationError(
                f"stages.{stage_name} {matchup}|{order} cross-arm identity mismatch"
            )
        baseline = _aggregate(baseline_group)
        candidate = _aggregate(candidate_group)
        matchup_rows[f"{matchup}|{order}"] = {
            "matchup": matchup,
            "actual_order": order,
            "baseline": baseline,
            "candidate": candidate,
            "candidate_minus_baseline": independent_difference(candidate, baseline),
        }

    baseline_pool = _aggregate(baselines)
    candidate_pool = _aggregate(candidates)
    baseline_quality_total = int(baseline_pool["failed_games"]) + sum(
        int(baseline_pool[key]) for key in QUALITY_KEYS
    ) + int(baseline_pool["operational_telemetry"]["fatal_count"])
    if baseline_quality_total:
        raise StageEvaluationError(
            f"stages.{stage_name} baseline contains failures, policy errors, "
            "or illegal actions"
        )
    baseline_macro = sum(
        row["baseline"]["win_rate"] for row in matchup_rows.values()
    ) / len(matchup_rows)
    candidate_macro = sum(
        row["candidate"]["win_rate"] for row in matchup_rows.values()
    ) / len(matchup_rows)
    return {
        "status": "EVALUATED",
        "baseline_cells": baselines,
        "candidate_cells": candidates,
        "per_matchup": matchup_rows,
        "pooled": {
            "baseline": baseline_pool,
            "candidate": candidate_pool,
            "candidate_minus_baseline": independent_difference(
                candidate_pool, baseline_pool
            ),
        },
        "macro": {
            "matchup_count": len(matchup_rows),
            "baseline_win_rate": baseline_macro,
            "candidate_win_rate": candidate_macro,
            "candidate_minus_baseline": candidate_macro - baseline_macro,
            "method": "unweighted_mean_of_matchup_order_cell_win_rates",
        },
        "candidate_s2_proof": _aggregate_proof(candidates),
        "candidate_latency_ms": _aggregate_latency(candidates),
        "statistical_contract": {
            "arms": "independent_unpaired_native_engine_randomness",
            "per_arm_interval": "wilson_score_95",
            "difference_interval": "independent_newcombe_wilson_difference_95",
            "same_schedule_is_paired": False,
        },
    }


def _stage1_decision(
    comparison: Mapping[str, Any], contract_value: object
) -> dict[str, Any]:
    contract = _mapping(contract_value, field="stage1_decision")
    expected_order = _string(
        contract.get("expected_actual_order"),
        field="stage1_decision.expected_actual_order",
    )
    if expected_order != "second":
        raise StageEvaluationError("Stage1 must be an actual-second screen")
    expected_matchups = [
        _string(value, field="stage1_decision.expected_matchups[]")
        for value in _sequence(
            contract.get("expected_matchups"),
            field="stage1_decision.expected_matchups",
        )
    ]
    if not expected_matchups or len(expected_matchups) != len(set(expected_matchups)):
        raise StageEvaluationError(
            "Stage1 expected_matchups must be unique and non-empty"
        )
    requested_per_matchup = _integer(
        contract.get("requested_games_per_matchup"),
        field="stage1_decision.requested_games_per_matchup",
        minimum=1,
    )
    expected_baseline_games = _integer(
        contract.get("expected_baseline_games"),
        field="stage1_decision.expected_baseline_games",
        minimum=1,
    )
    expected_baseline_wins = _integer(
        contract.get("expected_baseline_wins"),
        field="stage1_decision.expected_baseline_wins",
    )
    minimum = _number(
        contract.get("minimum_promising_pooled_delta"),
        field="stage1_decision.minimum_promising_pooled_delta",
        minimum=0.0,
    )
    strong = _number(
        contract.get("strong_signal_pooled_delta"),
        field="stage1_decision.strong_signal_pooled_delta",
        minimum=minimum,
    )
    if not math.isclose(
        minimum, STAGE1_MINIMUM_PROMISING_DELTA, rel_tol=0.0, abs_tol=1e-12
    ) or not math.isclose(
        strong, STAGE1_STRONG_SIGNAL_DELTA, rel_tol=0.0, abs_tol=1e-12
    ):
        raise StageEvaluationError(
            "Stage1 must freeze the prompt's +3pp promising and +5pp strong gates"
        )
    def drop_threshold(key: str) -> float | None:
        if key not in contract:
            raise StageEvaluationError(f"stage1_decision.{key} must be declared")
        raw = contract[key]
        if raw is None:
            return None
        value = _number(raw, field=f"stage1_decision.{key}")
        if value < -1.0 or value >= 0.0:
            raise StageEvaluationError(
                f"stage1_decision.{key} must be in [-1, 0) or null"
            )
        return value

    material_drop = drop_threshold("material_pooled_drop_delta")
    catastrophic = drop_threshold("catastrophic_matchup_drop_delta")
    if (
        material_drop is not None
        and catastrophic is not None
        and catastrophic > material_drop
    ):
        raise StageEvaluationError(
            "catastrophic_matchup_drop_delta must be at least as severe as "
            "material_pooled_drop_delta"
        )

    pooled = _mapping(comparison.get("pooled"), field="stage1.pooled")
    baseline = _mapping(pooled.get("baseline"), field="stage1.pooled.baseline")
    candidate = _mapping(pooled.get("candidate"), field="stage1.pooled.candidate")
    difference = _mapping(
        pooled.get("candidate_minus_baseline"),
        field="stage1.pooled.candidate_minus_baseline",
    )
    delta = _number(difference.get("estimate"), field="stage1 pooled delta")
    if (
        int(baseline["games"]) != expected_baseline_games
        or int(baseline["wins"]) != expected_baseline_wins
    ):
        raise StageEvaluationError(
            "Stage1 baseline pool does not match its frozen games/wins contract"
        )
    per_matchup = _mapping(
        comparison.get("per_matchup"), field="stage1.per_matchup"
    )
    observed_matchups: list[str] = []
    for row_key, row_value in per_matchup.items():
        row = _mapping(row_value, field=f"stage1.per_matchup.{row_key}")
        matchup = _string(row.get("matchup"), field=f"stage1.{row_key}.matchup")
        observed_matchups.append(matchup)
        if row.get("actual_order") != expected_order:
            raise StageEvaluationError(f"Stage1 cell {row_key} is not actual-second")
        for arm_name in ("baseline", "candidate"):
            arm = _mapping(row.get(arm_name), field=f"stage1.{row_key}.{arm_name}")
            if int(arm["scheduled_games"]) != requested_per_matchup:
                raise StageEvaluationError(
                    f"Stage1 {row_key} {arm_name} scheduled-games mismatch"
                )
    if sorted(observed_matchups) != sorted(expected_matchups):
        raise StageEvaluationError(
            "Stage1 matchup set does not match its frozen contract"
        )
    failures = int(candidate["failed_games"])
    policy_errors = int(candidate["hero_policy_errors"]) + int(
        candidate["opponent_policy_errors"]
    )
    illegal_actions = int(candidate["hero_illegal_actions"]) + int(
        candidate["opponent_illegal_actions"]
    )
    fatal_operational_errors = int(
        candidate["operational_telemetry"]["fatal_count"]
    )
    matchup_deltas = {
        key: float(row["candidate_minus_baseline"]["estimate"])
        for key, row in _mapping(
            comparison.get("per_matchup"), field="stage1.per_matchup"
        ).items()
    }
    if material_drop is None and delta < 0.0:
        raise StageEvaluationError(
            "Stage1 pooled result declined, but 'material' has no frozen "
            "numeric threshold"
        )
    negative_matchups = [key for key, value in matchup_deltas.items() if value < 0.0]
    if catastrophic is None and negative_matchups:
        raise StageEvaluationError(
            "A Stage1 matchup declined, but 'catastrophic' has no frozen "
            "numeric threshold"
        )
    collapses = (
        []
        if catastrophic is None
        else [key for key, value in matchup_deltas.items() if value <= catastrophic]
    )

    reasons: list[str] = []
    if failures or policy_errors:
        reasons.append("ERRORS_OR_FAILURES_GT_ZERO")
    if illegal_actions:
        reasons.append("ILLEGAL_ACTIONS_GT_ZERO")
    if fatal_operational_errors:
        reasons.append("FATAL_OPERATIONAL_TELEMETRY_GT_ZERO")
    if material_drop is not None and delta <= material_drop:
        reasons.append("MATERIAL_POOLED_DROP")
    if collapses:
        reasons.append("CATASTROPHIC_MATCHUP_COLLAPSE")
    if delta + FLOAT_COMPARISON_TOLERANCE < minimum:
        reasons.append("POOLED_LIFT_BELOW_3PP_SCREEN")

    if reasons:
        verdict = "KILL"
    elif delta + FLOAT_COMPARISON_TOLERANCE >= strong:
        verdict = "STRONG"
        reasons.append("POOLED_LIFT_AT_OR_ABOVE_STRONG_SIGNAL")
    else:
        verdict = "PROMISING"
        reasons.append("POOLED_LIFT_AT_OR_ABOVE_PROMISING_SIGNAL")
    return {
        "verdict": verdict,
        "reasons": reasons,
        "thresholds": {
            "expected_actual_order": expected_order,
            "expected_matchups": expected_matchups,
            "requested_games_per_matchup": requested_per_matchup,
            "expected_baseline_games": expected_baseline_games,
            "expected_baseline_wins": expected_baseline_wins,
            "minimum_promising_pooled_delta": minimum,
            "strong_signal_pooled_delta": strong,
            "material_pooled_drop_delta": material_drop,
            "catastrophic_matchup_drop_delta": catastrophic,
        },
        "observed": {
            "pooled_delta": delta,
            "failed_games": failures,
            "policy_errors": policy_errors,
            "illegal_actions": illegal_actions,
            "fatal_operational_telemetry": fatal_operational_errors,
            "catastrophic_matchup_cells": collapses,
        },
        "gates": {
            "zero_failures_and_policy_errors": failures == 0 and policy_errors == 0,
            "zero_illegal_actions": illegal_actions == 0,
            "zero_fatal_operational_telemetry": fatal_operational_errors == 0,
            "no_material_pooled_drop": (
                delta >= 0.0 if material_drop is None else delta > material_drop
            ),
            "no_catastrophic_matchup_collapse": not collapses,
            "minimum_3pp_pooled_lift": (
                delta + FLOAT_COMPARISON_TOLERANCE >= minimum
            ),
        },
        "targets": {
            "strong_5pp_pooled_lift": (
                delta + FLOAT_COMPARISON_TOLERANCE >= strong
            ),
        },
    }


def _candidate_quality(comparison: Mapping[str, Any], *, field: str) -> dict[str, int]:
    candidate = _mapping(
        _mapping(comparison.get("pooled"), field=f"{field}.pooled").get("candidate"),
        field=f"{field}.pooled.candidate",
    )
    return {
        "failed_games": int(candidate["failed_games"]),
        "policy_errors": int(candidate["hero_policy_errors"])
        + int(candidate["opponent_policy_errors"]),
        "illegal_actions": int(candidate["hero_illegal_actions"])
        + int(candidate["opponent_illegal_actions"]),
        "fatal_operational_telemetry": int(
            candidate["operational_telemetry"]["fatal_count"]
        ),
    }


def _stage2_decision(comparison: Mapping[str, Any]) -> dict[str, Any]:
    contract = LATER_STAGE_DECISION_CONTRACT["stage2"]
    per_matchup = _mapping(comparison.get("per_matchup"), field="stage2.per_matchup")
    expected_matchups = list(contract["expected_matchups"])
    if sorted(row["matchup"] for row in per_matchup.values()) != sorted(
        expected_matchups
    ):
        raise StageEvaluationError("Stage2 matchup set mismatch")
    requested = int(contract["requested_games_per_arm_per_matchup"])
    for key, row in per_matchup.items():
        if row["actual_order"] != contract["expected_actual_order"]:
            raise StageEvaluationError(f"Stage2 {key} is not actual-second")
        if any(
            int(row[arm]["scheduled_games"]) != requested
            for arm in ("baseline", "candidate")
        ):
            raise StageEvaluationError(f"Stage2 {key} requested-games mismatch")
    pooled = _mapping(comparison.get("pooled"), field="stage2.pooled")
    candidate_rate = float(pooled["candidate"]["win_rate"])
    macro_rate = float(comparison["macro"]["candidate_win_rate"])
    pooled_delta = float(pooled["candidate_minus_baseline"]["estimate"])
    collapses = [
        key
        for key, row in per_matchup.items()
        if float(row["candidate_minus_baseline"]["estimate"])
        <= float(contract["catastrophic_matchup_drop_delta"])
        + FLOAT_COMPARISON_TOLERANCE
    ]
    quality = _candidate_quality(comparison, field="stage2")
    checks = {
        "zero_quality_errors": all(value == 0 for value in quality.values()),
        "candidate_pooled_rate_at_least_50pct": candidate_rate
        + FLOAT_COMPARISON_TOLERANCE
        >= float(contract["minimum_candidate_pooled_win_rate"]),
        "candidate_macro_rate_at_least_50pct": macro_rate
        + FLOAT_COMPARISON_TOLERANCE
        >= float(contract["minimum_candidate_macro_win_rate"]),
        "candidate_pooled_delta_nonnegative": pooled_delta
        + FLOAT_COMPARISON_TOLERANCE
        >= float(contract["minimum_candidate_minus_s1_pooled_delta"]),
        "no_catastrophic_matchup_drop": not collapses,
    }
    passed = all(checks.values())
    strong = (
        passed
        and max(candidate_rate, macro_rate) + FLOAT_COMPARISON_TOLERANCE
        >= float(contract["strong_target_candidate_pooled_or_macro_win_rate"])
    )
    return {
        "verdict": "STRONG" if strong else "PASS" if passed else "KILL",
        "passed": passed,
        "gates": checks,
        "observed": {
            **quality,
            "candidate_pooled_win_rate": candidate_rate,
            "candidate_macro_win_rate": macro_rate,
            "candidate_minus_s1_pooled_delta": pooled_delta,
            "catastrophic_matchup_cells": collapses,
        },
        "thresholds": dict(contract),
        "targets": {"strong_55pct_target_met": strong},
    }


def _stage3_decision(comparison: Mapping[str, Any]) -> dict[str, Any]:
    contract = LATER_STAGE_DECISION_CONTRACT["stage3"]
    per_matchup = _mapping(comparison.get("per_matchup"), field="stage3.per_matchup")
    if sorted(row["matchup"] for row in per_matchup.values()) != sorted(
        contract["expected_matchups"]
    ):
        raise StageEvaluationError("Stage3 matchup set mismatch")
    requested = int(contract["requested_games_per_arm_per_matchup"])
    for key, row in per_matchup.items():
        if row["actual_order"] != contract["expected_actual_order"]:
            raise StageEvaluationError(f"Stage3 {key} is not actual-first")
        if any(
            int(row[arm]["scheduled_games"]) != requested
            for arm in ("baseline", "candidate")
        ):
            raise StageEvaluationError(f"Stage3 {key} requested-games mismatch")
    pooled_delta = float(comparison["pooled"]["candidate_minus_baseline"]["estimate"])
    macro_delta = float(comparison["macro"]["candidate_minus_baseline"])
    collapses = [
        key
        for key, row in per_matchup.items()
        if float(row["candidate_minus_baseline"]["estimate"])
        <= float(contract["catastrophic_matchup_drop_delta"])
        + FLOAT_COMPARISON_TOLERANCE
    ]
    quality = _candidate_quality(comparison, field="stage3")
    checks = {
        "zero_quality_errors": all(value == 0 for value in quality.values()),
        "pooled_delta_above_regression_floor": pooled_delta
        + FLOAT_COMPARISON_TOLERANCE
        >= float(contract["minimum_candidate_minus_s1_pooled_delta"]),
        "macro_delta_above_regression_floor": macro_delta
        + FLOAT_COMPARISON_TOLERANCE
        >= float(contract["minimum_candidate_minus_s1_macro_delta"]),
        "no_catastrophic_matchup_drop": not collapses,
    }
    passed = all(checks.values())
    return {
        "verdict": "PASS" if passed else "KILL",
        "passed": passed,
        "gates": checks,
        "observed": {
            **quality,
            "candidate_minus_s1_pooled_delta": pooled_delta,
            "candidate_minus_s1_macro_delta": macro_delta,
            "catastrophic_matchup_cells": collapses,
        },
        "thresholds": dict(contract),
    }


def _stage4_evaluation(
    stage: Mapping[str, Any],
    *,
    spec: Mapping[str, Any],
    spec_path: Path,
    baseline_identity: Mapping[str, Any],
    candidate_identity: Mapping[str, Any],
    evaluation_contract: Mapping[str, Any],
    opponent_contracts: Mapping[str, Any],
) -> dict[str, Any]:
    control_contract = _mapping(
        spec.get("stage4_control_evaluation_contract"),
        field="stage4_control_evaluation_contract",
    )
    control_declarations = _sequence(
        spec.get("stage4_controls"), field="stage4_controls"
    )
    candidate_declarations = _sequence(
        stage.get("candidate_cells"), field="stages.stage4.candidate_cells"
    )
    if len(control_declarations) != 2 or len(candidate_declarations) != 2:
        raise StageEvaluationError(
            "Stage4 requires exactly two immutable controls and two candidate cells"
        )
    for index, declaration_value in enumerate(control_declarations):
        declaration = _mapping(
            declaration_value, field=f"stage4_controls[{index}]"
        )
        if (
            _hash(
                declaration.get("tree_sha256"),
                field=f"stage4_controls[{index}].tree_sha256",
            )
            != _hash(
                baseline_identity.get("tree_sha256"), field="baseline.tree_sha256"
            )
            or _hash(
                declaration.get("archive_sha256"),
                field=f"stage4_controls[{index}].archive_sha256",
            )
            != _hash(
                baseline_identity.get("archive_sha256"),
                field="baseline.archive_sha256",
            )
        ):
            raise StageEvaluationError("Stage4 control package identity mismatch")
    controls = [
        _artifact_summary(
            declaration,
            spec_path=spec_path,
            identity=baseline_identity,
            evaluation_contract=control_contract,
            opponent_contracts=opponent_contracts,
            role="stages.stage4.baseline",
        )
        for declaration in control_declarations
    ]
    candidates = [
        _artifact_summary(
            declaration,
            spec_path=spec_path,
            identity=candidate_identity,
            evaluation_contract=evaluation_contract,
            opponent_contracts=opponent_contracts,
            role="stages.stage4.candidate",
        )
        for declaration in candidate_declarations
    ]

    def by_order(
        cells: Sequence[Mapping[str, Any]], *, field: str
    ) -> dict[str, Mapping[str, Any]]:
        result: dict[str, Mapping[str, Any]] = {}
        for cell in cells:
            order = str(cell["actual_order"])
            if order not in {"first", "second"} or order in result:
                raise StageEvaluationError(f"{field} must contain one cell per order")
            result[order] = cell
        if set(result) != {"first", "second"}:
            raise StageEvaluationError(f"{field} order set mismatch")
        return result

    controls_by_order = by_order(controls, field="Stage4 controls")
    candidates_by_order = by_order(candidates, field="Stage4 candidates")
    comparable_keys = {
        "deck_a_sha256",
        "engine_sha256",
        "external_adapter_sha256",
        "evaluation_schema_sha256",
        "submission_b_sha256",
        "post_evaluation_submission_b_sha256",
        "artifact_b_sha256",
        "archive_b_sha256",
        "deck_b_sha256",
        "runtime_environment",
        "process_behavior_environment",
        "max_decisions",
    }
    for order in ("first", "second"):
        control_identity = controls_by_order[order]["evaluation_identity"]
        candidate_identity_value = candidates_by_order[order]["evaluation_identity"]
        if any(
            control_identity.get(key) != candidate_identity_value.get(key)
            for key in comparable_keys
        ):
            raise StageEvaluationError(
                f"Stage4 {order} candidate/control gameplay identity mismatch"
            )

    control_pool = _aggregate(controls)
    candidate_pool = _aggregate(candidates)
    control_quality = int(control_pool["failed_games"]) + sum(
        int(control_pool[key]) for key in QUALITY_KEYS
    ) + int(control_pool["operational_telemetry"]["fatal_count"])
    if control_quality:
        raise StageEvaluationError("Stage4 immutable control contains a quality error")
    per_order: dict[str, Any] = {}
    for order in ("first", "second"):
        control = _aggregate([controls_by_order[order]])
        candidate = _aggregate([candidates_by_order[order]])
        per_order[order] = {
            "control": control,
            "candidate": candidate,
            "candidate_minus_control": independent_difference(candidate, control),
        }
    return {
        "status": "EVALUATED",
        "baseline_cells": controls,
        "candidate_cells": candidates,
        "per_order": per_order,
        "pooled": {
            "baseline": control_pool,
            "candidate": candidate_pool,
            "candidate_minus_baseline": independent_difference(
                candidate_pool, control_pool
            ),
        },
        "candidate_s2_proof": _aggregate_proof(candidates),
        "candidate_latency_ms": _aggregate_latency(candidates),
        "statistical_contract": {
            "arms": "independent_unpaired_historical_initiative_controls",
            "controls": "immutable_exact_current_tree_s1_vs_s1_by_order",
            "per_arm_interval": "wilson_score_95",
            "difference_interval": "independent_newcombe_wilson_difference_95",
            "same_schedule_is_paired": False,
            "control_evaluator_may_differ_but_is_hash_pinned": True,
        },
    }


def _stage4_decision(evaluation: Mapping[str, Any]) -> dict[str, Any]:
    contract = LATER_STAGE_DECISION_CONTRACT["stage4"]
    per_order = _mapping(evaluation.get("per_order"), field="stage4.per_order")
    if set(per_order) != set(contract["orders"]):
        raise StageEvaluationError("Stage4 order set mismatch")
    order_deltas: dict[str, float] = {}
    clear_losses: list[str] = []
    for order in contract["orders"]:
        row = _mapping(per_order[order], field=f"stage4.per_order.{order}")
        control = _mapping(row.get("control"), field=f"stage4.{order}.control")
        candidate = _mapping(row.get("candidate"), field=f"stage4.{order}.candidate")
        difference = _mapping(
            row.get("candidate_minus_control"), field=f"stage4.{order}.difference"
        )
        if (
            int(control["scheduled_games"]) != int(contract["control_games_per_order"])
            or int(control["games"]) != int(contract["control_games_per_order"])
            or int(control["wins"]) != int(contract["control_wins_by_order"][order])
        ):
            raise StageEvaluationError(f"Stage4 {order} immutable control mismatch")
        if (
            int(candidate["scheduled_games"]) != int(contract["candidate_games_per_order"])
            or int(candidate["games"]) != int(contract["candidate_games_per_order"])
        ):
            raise StageEvaluationError(f"Stage4 {order} candidate-games mismatch")
        order_deltas[order] = float(difference["estimate"])
        confidence = _sequence(
            difference.get("confidence_95"), field=f"stage4.{order}.confidence_95"
        )
        if len(confidence) != 2 or float(confidence[1]) < 0.0:
            clear_losses.append(order)

    pooled = _mapping(evaluation.get("pooled"), field="stage4.pooled")
    control_pool = _mapping(pooled.get("baseline"), field="stage4.pooled.control")
    candidate_pool = _mapping(pooled.get("candidate"), field="stage4.pooled.candidate")
    difference_pool = _mapping(
        pooled.get("candidate_minus_baseline"), field="stage4.pooled.difference"
    )
    if (
        int(control_pool["games"])
        != int(contract["control_games_per_order"]) * 2
        or int(control_pool["wins"])
        != sum(int(value) for value in contract["control_wins_by_order"].values())
        or int(candidate_pool["scheduled_games"]) != int(contract["candidate_games_total"])
        or int(candidate_pool["games"]) != int(contract["candidate_games_total"])
    ):
        raise StageEvaluationError("Stage4 pooled game/control contract mismatch")
    pooled_delta = float(difference_pool["estimate"])
    pooled_confidence = _sequence(
        difference_pool.get("confidence_95"), field="stage4.pooled.confidence_95"
    )
    if len(pooled_confidence) != 2 or float(pooled_confidence[1]) < 0.0:
        clear_losses.append("balanced_pooled")
    candidate_rate = float(candidate_pool["win_rate"])
    quality = _candidate_quality(evaluation, field="stage4")
    gates = {
        "zero_quality_errors": all(value == 0 for value in quality.values()),
        "candidate_pooled_rate_at_least_47pct": candidate_rate
        + FLOAT_COMPARISON_TOLERANCE
        >= float(contract["minimum_pooled_s2_win_rate"]),
        "balanced_pooled_delta_above_floor": pooled_delta
        + FLOAT_COMPARISON_TOLERANCE
        >= float(contract["minimum_candidate_minus_control_pooled_delta"]),
        "each_order_delta_above_floor": all(
            delta + FLOAT_COMPARISON_TOLERANCE
            >= float(contract["minimum_candidate_minus_control_each_order_delta"])
            for delta in order_deltas.values()
        ),
        "no_statistically_clear_loss": not clear_losses,
    }
    passed = all(gates.values())
    return {
        "verdict": "PASS" if passed else "KILL",
        "passed": passed,
        "gates": gates,
        "observed": {
            **quality,
            "candidate_pooled_win_rate": candidate_rate,
            "candidate_minus_control_pooled_delta": pooled_delta,
            "candidate_minus_control_by_order": order_deltas,
            "statistically_clear_loss_cells": clear_losses,
        },
        "thresholds": dict(contract),
    }


def _replay_aggregate_summary(
    aggregate_value: object,
    rows: Sequence[Mapping[str, Any]],
    *,
    field: str,
    require_quality_counts: bool = False,
) -> dict[str, Any]:
    aggregate = _mapping(aggregate_value, field=field)
    counts = {label: 0 for label in REPLAY_CLASSIFICATIONS}
    by_episode: dict[str, list[str]] = {}
    for offset, row in enumerate(rows):
        label = _string(
            row.get("classification"), field=f"{field}.rows[{offset}].classification"
        )
        if label not in counts:
            raise StageEvaluationError(f"{field} has unknown classification {label}")
        episode_id = _scalar_identifier(
            row.get("episode_id"), field=f"{field}.rows[{offset}].episode_id"
        )
        counts[label] += 1
        by_episode.setdefault(str(episode_id), []).append(label)
    decision_count = len(rows)
    episode_rates = {
        label: (
            sum(labels.count(label) / len(labels) for labels in by_episode.values())
            / len(by_episode)
            if by_episode
            else 0.0
        )
        for label in REPLAY_CLASSIFICATIONS
    }
    claimed_counts = _mapping(
        aggregate.get("classification_counts"), field=f"{field}.classification_counts"
    )
    claimed_decision_rates = _mapping(
        aggregate.get("decision_rates"), field=f"{field}.decision_rates"
    )
    claimed_episode_rates = _mapping(
        aggregate.get("episode_rates"), field=f"{field}.episode_rates"
    )
    if _integer(aggregate.get("decision_count"), field=f"{field}.decision_count") != decision_count:
        raise StageEvaluationError(f"{field}.decision_count does not reaggregate")
    if _integer(aggregate.get("episode_count"), field=f"{field}.episode_count") != len(by_episode):
        raise StageEvaluationError(f"{field}.episode_count does not reaggregate")
    for label in REPLAY_CLASSIFICATIONS:
        if _counter(claimed_counts.get(label), field=f"{field}.counts.{label}") != counts[label]:
            raise StageEvaluationError(f"{field}.{label} count does not reaggregate")
        expected_decision_rate = counts[label] / decision_count if decision_count else 0.0
        if not _same_number(
            _number(
                claimed_decision_rates.get(label),
                field=f"{field}.decision_rates.{label}",
            ),
            expected_decision_rate,
        ):
            raise StageEvaluationError(f"{field}.{label} decision rate mismatch")
        if not _same_number(
            _number(
                claimed_episode_rates.get(label),
                field=f"{field}.episode_rates.{label}",
            ),
            episode_rates[label],
        ):
            raise StageEvaluationError(f"{field}.{label} episode rate mismatch")
    for alias, label in (
        ("expert_dominates_rate", "EXPERT_DOMINATES"),
        ("agent_dominates_rate", "AGENT_DOMINATES"),
    ):
        if not _same_number(
            _number(aggregate.get(alias), field=f"{field}.{alias}"),
            episode_rates[label],
        ):
            raise StageEvaluationError(f"{field}.{alias} mismatch")
    quality_counts: dict[str, int] | None = None
    archetype_decision_counts: dict[str, int] | None = None
    archetype_episode_counts: dict[str, int] | None = None
    if require_quality_counts:
        proposal_errors = sum(int(row.get("proposal_error") is not None) for row in rows)
        action_unstable = sum(
            int(
                row.get("proposal_error") is not None
                and (
                    "unstable" in str(row.get("proposal_error")).lower()
                    or str(row.get("uncertifiable_reason") or "").lower()
                    in {"candidate_action_unstable", "action_unstable"}
                )
            )
            for row in rows
        )
        quality_counts = {
            "proposal_error_rows": proposal_errors,
            "candidate_policy_error_rows": proposal_errors - action_unstable,
            "candidate_action_unstable_rows": action_unstable,
            "uncertifiable_rows": counts["UNCERTIFIABLE"],
            "incomparable_rows": counts["INCOMPARABLE"],
        }
        claimed_quality = _mapping(
            aggregate.get("quality_counts"), field=f"{field}.quality_counts"
        )
        if set(claimed_quality) != set(quality_counts) or any(
            _integer(claimed_quality.get(key), field=f"{field}.quality_counts.{key}")
            != expected
            for key, expected in quality_counts.items()
        ):
            raise StageEvaluationError(f"{field}.quality_counts does not reaggregate")
        decision_archetypes: dict[str, int] = {}
        episode_archetypes: dict[str, str] = {}
        for offset, row in enumerate(rows):
            episode_id = str(
                _scalar_identifier(
                    row.get("episode_id"),
                    field=f"{field}.rows[{offset}].episode_id",
                )
            )
            archetype = str(row.get("opponent_archetype") or "unknown")
            if (
                episode_id in episode_archetypes
                and episode_archetypes[episode_id] != archetype
            ):
                raise StageEvaluationError(
                    f"{field} episode has inconsistent opponent archetypes"
                )
            episode_archetypes[episode_id] = archetype
            decision_archetypes[archetype] = decision_archetypes.get(archetype, 0) + 1
        episode_counts: dict[str, int] = {}
        for archetype in episode_archetypes.values():
            episode_counts[archetype] = episode_counts.get(archetype, 0) + 1
        archetype_decision_counts = dict(sorted(decision_archetypes.items()))
        archetype_episode_counts = dict(sorted(episode_counts.items()))
        for key, expected in (
            ("opponent_archetype_decision_counts", archetype_decision_counts),
            ("opponent_archetype_episode_counts", archetype_episode_counts),
            ("opponent_archetypes", archetype_episode_counts),
        ):
            claimed = _mapping(aggregate.get(key), field=f"{field}.{key}")
            if set(claimed) != set(expected) or any(
                _integer(claimed.get(name), field=f"{field}.{key}.{name}")
                != count
                for name, count in expected.items()
            ):
                raise StageEvaluationError(f"{field}.{key} does not reaggregate")
        if aggregate.get("opponent_archetypes_basis") != "unique_episode_id":
            raise StageEvaluationError(f"{field}.opponent_archetypes_basis mismatch")
    intervals = _mapping(
        aggregate.get("episode_bootstrap_95"),
        field=f"{field}.episode_bootstrap_95",
    )
    for label in REPLAY_CLASSIFICATIONS:
        interval = _sequence(
            intervals.get(label), field=f"{field}.episode_bootstrap_95.{label}"
        )
        if len(interval) != 2:
            raise StageEvaluationError(f"{field}.{label} bootstrap interval malformed")
        lower = _number(interval[0], field=f"{field}.{label}.lower", minimum=0.0)
        upper = _number(interval[1], field=f"{field}.{label}.upper", minimum=0.0)
        if lower > upper or upper > 1.0:
            raise StageEvaluationError(f"{field}.{label} bootstrap interval invalid")
    result = {
        "episode_count": len(by_episode),
        "decision_count": decision_count,
        "classification_counts": counts,
        "episode_rates": episode_rates,
    }
    if quality_counts is not None:
        result["quality_counts"] = quality_counts
        result["opponent_archetype_decision_counts"] = archetype_decision_counts
        result["opponent_archetype_episode_counts"] = archetype_episode_counts
        result["opponent_archetypes"] = archetype_episode_counts
        result["opponent_archetypes_basis"] = "unique_episode_id"
    return result


def _replay_failure_family(
    row: Mapping[str, Any],
) -> tuple[str, str, str] | None:
    label = str(row.get("classification") or "")
    if label not in {"EXPERT_DOMINATES", "INCOMPARABLE", "UNCERTIFIABLE"}:
        return None
    reason = ""
    if label == "UNCERTIFIABLE":
        raw = str(
            row.get("uncertifiable_reason") or row.get("proposal_error") or "unknown"
        )
        lowered = raw.lower()
        if "action_unstable" in lowered:
            reason = "action_unstable"
        elif "policy_error" in lowered or row.get("proposal_error"):
            reason = "policy_error"
        else:
            reason = raw
    return (label, str(row.get("decision_family") or "unknown"), reason)


def _stage5_evaluation(
    stage: Mapping[str, Any],
    *,
    spec: Mapping[str, Any],
    spec_path: Path,
) -> dict[str, Any]:
    baseline_declaration = _mapping(
        spec.get("stage5_baseline"), field="stage5_baseline"
    )
    candidate_declaration = _mapping(
        stage.get("candidate_result"), field="stages.stage5.candidate_result"
    )
    run_contract = _mapping(
        spec.get("stage5_run_contract"), field="stage5_run_contract"
    )

    baseline_path = _resolve(
        spec_path,
        baseline_declaration.get("path"),
        field="stage5_baseline.path",
    )
    baseline_hash = sha256_file(baseline_path)
    if baseline_hash != _hash(
        baseline_declaration.get("artifact_sha256"),
        field="stage5_baseline.artifact_sha256",
    ):
        raise StageEvaluationError("Stage5 frozen S1 baseline hash mismatch")
    baseline = _read_json(baseline_path, field="Stage5 S1 baseline")
    baseline_rows_value = _sequence(
        baseline.get("decision_rows"), field="Stage5 S1 decision_rows"
    )
    baseline_rows = [
        _mapping(row, field=f"Stage5 S1 decision_rows[{index}]")
        for index, row in enumerate(baseline_rows_value)
    ]
    if (
        baseline.get("schema") != REPLAY_BASELINE_SCHEMA
        or baseline.get("split") != "VALIDATION"
        or baseline.get("sealed") is not False
    ):
        raise StageEvaluationError("Stage5 frozen S1 baseline schema/split mismatch")
    baseline_summary = _replay_aggregate_summary(
        baseline.get("aggregate"), baseline_rows, field="Stage5 S1 aggregate"
    )
    expected_count = _integer(
        baseline_declaration.get("decision_count"),
        field="stage5_baseline.decision_count",
        minimum=1,
    )
    expected_episodes = _integer(
        baseline_declaration.get("episode_count"),
        field="stage5_baseline.episode_count",
        minimum=1,
    )
    expected_counts = _mapping(
        baseline_declaration.get("classification_counts"),
        field="stage5_baseline.classification_counts",
    )
    if set(expected_counts) != set(REPLAY_CLASSIFICATIONS):
        raise StageEvaluationError("Stage5 baseline classification key set mismatch")
    if (
        baseline_summary["decision_count"] != expected_count
        or baseline_summary["episode_count"] != expected_episodes
        or baseline_summary["classification_counts"]
        != {
            label: _counter(
                expected_counts.get(label),
                field=f"stage5_baseline.classification_counts.{label}",
            )
            for label in REPLAY_CLASSIFICATIONS
        }
        or not _same_number(
            baseline_summary["episode_rates"]["EXPERT_DOMINATES"],
            _number(
                baseline_declaration.get("expert_dominates_episode_rate"),
                field="stage5_baseline.expert_dominates_episode_rate",
            ),
        )
    ):
        raise StageEvaluationError("Stage5 frozen S1 baseline metrics mismatch")
    baseline_ids = [
        _string(row.get("record_id"), field=f"Stage5 S1 rows[{index}].record_id")
        for index, row in enumerate(baseline_rows)
    ]
    if len(set(baseline_ids)) != len(baseline_ids):
        raise StageEvaluationError("Stage5 S1 record IDs are not unique")
    if _object_sha256(baseline_ids) != _hash(
        baseline_declaration.get("record_id_sequence_sha256"),
        field="stage5_baseline.record_id_sequence_sha256",
    ):
        raise StageEvaluationError("Stage5 S1 record-ID sequence hash mismatch")

    candidate_path = _resolve(
        spec_path,
        candidate_declaration.get("path"),
        field="stages.stage5.candidate_result.path",
    )
    candidate_hash = sha256_file(candidate_path)
    if candidate_hash != _hash(
        candidate_declaration.get("artifact_sha256"),
        field="stages.stage5.candidate_result.artifact_sha256",
    ):
        raise StageEvaluationError("Stage5 S2 candidate result hash mismatch")
    candidate = _read_json(candidate_path, field="Stage5 S2 candidate")
    sets = _mapping(candidate.get("evaluation_sets"), field="Stage5 evaluation_sets")
    primary = _mapping(sets.get("paired_primary"), field="Stage5 paired_primary")
    exploratory = _mapping(
        sets.get("s2_exploratory"), field="Stage5 s2_exploratory"
    )
    primary_rows = [
        _mapping(row, field=f"Stage5 primary rows[{index}]")
        for index, row in enumerate(
            _sequence(primary.get("decision_rows"), field="Stage5 primary rows")
        )
    ]
    exploratory_rows = [
        _mapping(row, field=f"Stage5 exploratory rows[{index}]")
        for index, row in enumerate(
            _sequence(
                exploratory.get("decision_rows"), field="Stage5 exploratory rows"
            )
        )
    ]
    if (
        candidate.get("schema") != REPLAY_CANDIDATE_SCHEMA
        or candidate.get("split") != "VALIDATION"
        or candidate.get("sealed") is not False
        or candidate.get("candidate_variant") != "s2"
        or candidate.get("headline_set") != "paired_primary"
        or candidate.get("aggregate_alias")
        != "evaluation_sets.paired_primary.aggregate"
        or candidate.get("aggregate") != primary.get("aggregate")
        or "decision_rows" in candidate
        or "combined_rate" in candidate
        or candidate.get("combined_rate_permitted") is not False
    ):
        raise StageEvaluationError("Stage5 S2 dual-set schema contract mismatch")
    primary_selection = _mapping(
        primary.get("selection"), field="Stage5 primary selection"
    )
    primary_ids = [
        _string(row.get("record_id"), field=f"Stage5 primary[{index}].record_id")
        for index, row in enumerate(primary_rows)
    ]
    if (
        primary.get("role") != "qualification_primary"
        or primary_selection.get("mode") != "exact_frozen_s1_record_ids"
        or _hash(
            primary_selection.get("source_result_sha256"),
            field="Stage5 primary selection source_result_sha256",
        )
        != baseline_hash
        or _integer(
            primary_selection.get("record_count"),
            field="Stage5 primary selection record_count",
        )
        != expected_count
        or _hash(
            primary_selection.get("record_id_sequence_sha256"),
            field="Stage5 primary selection record_id_sequence_sha256",
        )
        != _object_sha256(baseline_ids)
        or primary_selection.get("order_preserved") is not True
        or primary_ids != baseline_ids
    ):
        raise StageEvaluationError("Stage5 paired-primary ordered-ID contract mismatch")
    if len(set(primary_ids)) != len(primary_ids):
        raise StageEvaluationError("Stage5 paired-primary IDs are not unique")
    immutable_row_fields = (
        "episode_id",
        "replay_sha256",
        "seat",
        "step",
        "expert_action",
        "expert_semantic",
        "actual_order",
        "turn",
        "own_turn_ordinal",
        "hero_deck_family",
        "opponent_archetype",
    )
    for offset, (before, after) in enumerate(zip(baseline_rows, primary_rows)):
        for key in immutable_row_fields:
            if before.get(key) != after.get(key):
                raise StageEvaluationError(
                    f"Stage5 paired row {offset} immutable field {key} mismatch"
                )

    candidate_provenance = _mapping(
        candidate.get("evaluated_candidate"), field="Stage5 evaluated_candidate"
    )
    baseline_provenance = _mapping(
        candidate.get("baseline_incumbent_s1"),
        field="Stage5 baseline_incumbent_s1",
    )
    candidate_package = _mapping(
        run_contract.get("candidate_package"), field="stage5_run_contract.candidate_package"
    )
    baseline_package = _mapping(
        run_contract.get("baseline_package"), field="stage5_run_contract.baseline_package"
    )
    for key in (
        "archive_sha256",
        "manifest_sha256",
        "extracted_tree_sha256",
        "runtime_source_tree_sha256",
    ):
        if str(candidate_provenance.get(key) or "").lower() != _hash(
            candidate_package.get(key), field=f"stage5 candidate_package.{key}"
        ):
            raise StageEvaluationError(f"Stage5 candidate package {key} mismatch")
        if str(baseline_provenance.get(key) or "").lower() != _hash(
            baseline_package.get(key), field=f"stage5 baseline_package.{key}"
        ):
            raise StageEvaluationError(f"Stage5 baseline package {key} mismatch")
    if str(baseline_provenance.get("validation_result_sha256") or "").lower() != baseline_hash:
        raise StageEvaluationError("Stage5 baseline provenance result hash mismatch")
    run = _mapping(candidate.get("run_contract"), field="Stage5 run_contract")
    expected_run = _mapping(
        run_contract.get("replay_run"), field="stage5_run_contract.replay_run"
    )
    for key in (
        "validation_manifest_file_sha256",
        "validation_manifest_payload_sha256",
        "baseline_s1_validation_result_sha256",
    ):
        if str(run.get(key) or "").lower() != _hash(
            expected_run.get(key), field=f"stage5_run_contract.replay_run.{key}"
        ):
            raise StageEvaluationError(f"Stage5 run {key} mismatch")
    if (
        run.get("candidate") != "s2"
        or run.get("parameters") != expected_run.get("parameters")
        or run.get("full_manifest_episode_count") != expected_episodes
        or run.get("evaluator") != expected_run.get("evaluator")
        or str(candidate.get("manifest_payload_sha256") or "").lower()
        != _hash(
            expected_run.get("validation_manifest_payload_sha256"),
            field="stage5_run_contract.replay_run.validation_manifest_payload_sha256",
        )
    ):
        raise StageEvaluationError("Stage5 replay run provenance mismatch")

    exploratory_selection = _mapping(
        exploratory.get("selection"), field="Stage5 exploratory selection"
    )
    exploratory_ids = [
        _string(row.get("record_id"), field=f"Stage5 exploratory[{index}].record_id")
        for index, row in enumerate(exploratory_rows)
    ]
    hard_ceiling = _integer(
        run_contract.get("exploratory_hard_ceiling"),
        field="stage5_run_contract.exploratory_hard_ceiling",
    )
    universe = _mapping(candidate.get("universe_counts"), field="Stage5 universe_counts")
    if (
        exploratory.get("role") != "exploratory_safety_veto_only"
        or exploratory.get("safety_veto_only") is not True
        or exploratory.get("eligible_for_efficacy_rate") is not False
        or exploratory_selection.get("mode")
        != "exhaustive_disjoint_out_of_primary_s2_override_disagreements"
        or exploratory_selection.get("requires_trustworthy_s2_override_delta")
        is not True
        or exploratory_selection.get("requires_candidate_expert_disagreement")
        is not True
        or exploratory_selection.get("hard_ceiling") != hard_ceiling
        or exploratory_selection.get("disjoint_from") != "paired_primary"
        or len(exploratory_rows) > hard_ceiling
        or len(set(exploratory_ids)) != len(exploratory_ids)
        or set(primary_ids).intersection(exploratory_ids)
        or _integer(
            universe.get("s2_exploratory_record_count"),
            field="Stage5 universe s2_exploratory_record_count",
        )
        != len(exploratory_rows)
        or _integer(
            universe.get("out_of_primary_s2_override_disagreement_count"),
            field="Stage5 universe out_of_primary disagreement count",
        )
        != len(exploratory_rows)
    ):
        raise StageEvaluationError("Stage5 exploratory safety-set contract mismatch")
    universe_values = {
        key: _integer(universe.get(key), field=f"Stage5 universe {key}")
        for key in (
            "manifest_episode_count",
            "useful_prompt_count",
            "paired_primary_record_count",
            "out_of_primary_useful_prompt_count",
            "s2_override_prompt_count",
            "paired_primary_s2_override_prompt_count",
            "out_of_primary_s2_override_prompt_count",
            "out_of_primary_s2_override_expert_equivalent_count",
            "out_of_primary_s2_override_disagreement_count",
            "s2_exploratory_record_count",
            "s2_exploratory_hard_ceiling",
        )
    }
    primary_override_prompt_count = sum(
        _integer(
            row.get("s2_pre_attack_sequence_proof_overrides_delta"),
            field=f"Stage5 primary row {offset} override delta",
        )
        == 1
        for offset, row in enumerate(primary_rows)
    )
    if (
        universe_values["manifest_episode_count"] != expected_episodes
        or universe_values["paired_primary_record_count"] != expected_count
        or universe_values["useful_prompt_count"]
        != universe_values["paired_primary_record_count"]
        + universe_values["out_of_primary_useful_prompt_count"]
        or universe_values["s2_override_prompt_count"]
        != universe_values["paired_primary_s2_override_prompt_count"]
        + universe_values["out_of_primary_s2_override_prompt_count"]
        or universe_values["out_of_primary_s2_override_prompt_count"]
        != universe_values["out_of_primary_s2_override_expert_equivalent_count"]
        + universe_values["out_of_primary_s2_override_disagreement_count"]
        or universe_values["out_of_primary_s2_override_disagreement_count"]
        != len(exploratory_rows)
        or universe_values["s2_exploratory_record_count"] != len(exploratory_rows)
        or universe_values["s2_exploratory_hard_ceiling"] != hard_ceiling
        or universe_values["paired_primary_s2_override_prompt_count"]
        != primary_override_prompt_count
        or universe_values["out_of_primary_s2_override_prompt_count"]
        > universe_values["out_of_primary_useful_prompt_count"]
    ):
        raise StageEvaluationError("Stage5 universe-count arithmetic mismatch")
    for offset, row in enumerate([*primary_rows, *exploratory_rows]):
        if (
            row.get("candidate_variant") != "s2"
            or row.get("candidate_s2_enabled") is not True
        ):
            raise StageEvaluationError(
                f"Stage5 candidate row {offset} lacks S2 mode proof"
            )
        trustworthy = row.get("s2_override_telemetry_trustworthy")
        if not isinstance(trustworthy, bool):
            raise StageEvaluationError(
                f"Stage5 candidate row {offset} has invalid S2 telemetry trust"
            )
        if not trustworthy and row.get("proposal_error") is None:
            raise StageEvaluationError(
                f"Stage5 candidate row {offset} has unexplained untrusted telemetry"
            )
        if row.get("proposal_error") is not None and trustworthy:
            raise StageEvaluationError(
                f"Stage5 candidate row {offset} trusts errored telemetry"
            )
        override_delta = _integer(
            row.get("s2_pre_attack_sequence_proof_overrides_delta"),
            field=f"Stage5 candidate row {offset} override delta",
        )
        if override_delta not in (0, 1):
            raise StageEvaluationError(
                f"Stage5 candidate row {offset} has invalid override delta"
            )
    for offset, row in enumerate(exploratory_rows):
        if (
            _integer(
                row.get("s2_pre_attack_sequence_proof_overrides_delta"),
                field=f"Stage5 exploratory row {offset} override delta",
            )
            != 1
            or _boolean(
                row.get("semantic_equivalent"),
                field=f"Stage5 exploratory row {offset} semantic_equivalent",
            )
            or row.get("proposal_error") is not None
        ):
            raise StageEvaluationError(
                f"Stage5 exploratory row {offset} is not a certified S2 disagreement"
            )

    primary_summary = _replay_aggregate_summary(
        primary.get("aggregate"),
        primary_rows,
        field="Stage5 S2 primary aggregate",
        require_quality_counts=True,
    )
    exploratory_summary = _replay_aggregate_summary(
        exploratory.get("aggregate"),
        exploratory_rows,
        field="Stage5 S2 exploratory aggregate",
        require_quality_counts=True,
    )
    if (
        primary_summary["decision_count"] != expected_count
        or primary_summary["episode_count"] != expected_episodes
    ):
        raise StageEvaluationError("Stage5 S2 primary coverage mismatch")
    transition_matrix = {
        before: {after: 0 for after in REPLAY_CLASSIFICATIONS}
        for before in REPLAY_CLASSIFICATIONS
    }
    for before, after in zip(baseline_rows, primary_rows):
        transition_matrix[str(before["classification"])][
            str(after["classification"])
        ] += 1
    transitions = {
        "ed_to_non_ed": sum(
            transition_matrix["EXPERT_DOMINATES"][label]
            for label in ("EQUIVALENT", "AGENT_DOMINATES")
        ),
        "non_ed_to_ed": sum(
            transition_matrix[label]["EXPERT_DOMINATES"]
            for label in REPLAY_CLASSIFICATIONS
            if label != "EXPERT_DOMINATES"
        ),
    }
    baseline_families = {
        family
        for row in baseline_rows
        if (family := _replay_failure_family(row)) is not None
    }
    candidate_families = {
        family
        for row in [*primary_rows, *exploratory_rows]
        if (family := _replay_failure_family(row)) is not None
    }
    new_families = sorted(candidate_families - baseline_families)
    contract = LATER_STAGE_DECISION_CONTRACT["stage5"]
    baseline_ed_count = baseline_summary["classification_counts"]["EXPERT_DOMINATES"]
    candidate_ed_count = primary_summary["classification_counts"]["EXPERT_DOMINATES"]
    baseline_ed_rate = baseline_summary["episode_rates"]["EXPERT_DOMINATES"]
    candidate_ed_rate = primary_summary["episode_rates"]["EXPERT_DOMINATES"]
    all_ed_exits = sum(
        transition_matrix["EXPERT_DOMINATES"][label]
        for label in REPLAY_CLASSIFICATIONS
        if label != "EXPERT_DOMINATES"
    )
    if baseline_ed_count - candidate_ed_count != (
        all_ed_exits - transitions["non_ed_to_ed"]
    ):
        raise StageEvaluationError("Stage5 paired ED transition invariant failed")
    baseline_failure_burden = sum(
        baseline_summary["classification_counts"][label]
        for label in ("INCOMPARABLE", "UNCERTIFIABLE")
    )
    candidate_failure_burden = sum(
        primary_summary["classification_counts"][label]
        for label in ("INCOMPARABLE", "UNCERTIFIABLE")
    )
    exploratory_ed = exploratory_summary["classification_counts"]["EXPERT_DOMINATES"]
    exploratory_incomparable = exploratory_summary["classification_counts"]["INCOMPARABLE"]
    candidate_policy_error_rows = sum(
        int(row.get("proposal_error") is not None) for row in primary_rows
    )
    gates = {
        "primary_expert_dominates_count_decreased": candidate_ed_count
        < baseline_ed_count,
        "primary_expert_dominates_episode_rate_decreased": candidate_ed_rate
        < baseline_ed_rate,
        "favorable_ed_exits_exceed_reverse_ed_entries": transitions["ed_to_non_ed"]
        > transitions["non_ed_to_ed"],
        "zero_certified_exploratory_expert_dominates": exploratory_ed
        <= int(contract["maximum_certified_exploratory_expert_dominates"]),
        "zero_certified_exploratory_incomparable": exploratory_incomparable
        <= int(contract["maximum_certified_exploratory_incomparable"]),
        "no_new_failure_family": not new_families,
        "zero_candidate_policy_errors": candidate_policy_error_rows == 0,
        "primary_incomparable_uncertifiable_burden_not_increased": (
            candidate_failure_burden <= baseline_failure_burden
        ),
    }
    passed = all(gates.values())
    return {
        "status": "EVALUATED",
        "baseline": {
            "source": {
                "path": _repo_relative_path(
                    baseline_path, field="stage5.baseline_result.path"
                ),
                "artifact_sha256": baseline_hash,
            },
            **baseline_summary,
        },
        "candidate": {
            "source": {
                "path": _repo_relative_path(
                    candidate_path, field="stage5.candidate_result.path"
                ),
                "artifact_sha256": candidate_hash,
            },
            **primary_summary,
        },
        "paired_record_ids": {
            "count": len(primary_ids),
            "sequence_sha256": _object_sha256(primary_ids),
            "exact_order_match": True,
        },
        "paired_transitions": {
            **transitions,
            "matrix": transition_matrix,
            "ed_count_identity_verified": True,
            "ed_to_non_ed_definition": "EXPERT_DOMINATES to EQUIVALENT or AGENT_DOMINATES only",
        },
        "exploratory_safety_veto": {
            **exploratory_summary,
            "efficacy_credit_permitted": False,
        },
        "failure_families": {
            "baseline": [
                {"classification": item[0], "decision_family": item[1], "reason": item[2]}
                for item in sorted(baseline_families)
            ],
            "candidate": [
                {"classification": item[0], "decision_family": item[1], "reason": item[2]}
                for item in sorted(candidate_families)
            ],
            "new": [
                {"classification": item[0], "decision_family": item[1], "reason": item[2]}
                for item in new_families
            ],
        },
        "statistical_contract": {
            "unit": "episode",
            "comparison": "paired_exact_record_id_transitions",
            "primary_set_only_for_efficacy": True,
            "exploratory_set_is_safety_veto_only": True,
            "combined_rate_permitted": False,
        },
        "decision": {
            "verdict": "PASS" if passed else "KILL",
            "passed": passed,
            "gates": gates,
            "observed": {
                "baseline_expert_dominates_count": baseline_ed_count,
                "candidate_expert_dominates_count": candidate_ed_count,
                "baseline_expert_dominates_episode_rate": baseline_ed_rate,
                "candidate_expert_dominates_episode_rate": candidate_ed_rate,
                "ed_to_non_ed": transitions["ed_to_non_ed"],
                "non_ed_to_ed": transitions["non_ed_to_ed"],
                "exploratory_expert_dominates": exploratory_ed,
                "exploratory_incomparable": exploratory_incomparable,
                "new_failure_families": [
                    {
                        "classification": item[0],
                        "decision_family": item[1],
                        "reason": item[2],
                    }
                    for item in new_families
                ],
                "candidate_policy_error_rows": candidate_policy_error_rows,
                "baseline_primary_incomparable_uncertifiable_count": baseline_failure_burden,
                "candidate_primary_incomparable_uncertifiable_count": candidate_failure_burden,
            },
            "thresholds": dict(contract),
        },
    }


def evaluate_spec(spec_path: Path) -> dict[str, Any]:
    spec_path = spec_path.resolve()
    report_spec_path = _repo_relative_path(spec_path, field="spec.path")
    spec_hash = sha256_file(spec_path)
    spec = _read_json(spec_path, field="spec")
    if spec.get("schema") != SPEC_SCHEMA:
        raise StageEvaluationError(f"spec.schema must be {SPEC_SCHEMA}")
    evidence_files = _validate_evidence_files(spec, spec_path=spec_path)
    baseline_identity = _mapping(spec.get("baseline"), field="baseline")
    candidate_identity = _mapping(spec.get("candidate"), field="candidate")
    evaluation_contract = _mapping(
        spec.get("evaluation_contract"), field="evaluation_contract"
    )
    allowed_fallbacks = set(
        _string(value, field="evaluation_contract.nonfatal_search_fallback_keys[]")
        for value in _sequence(
            evaluation_contract.get("nonfatal_search_fallback_keys"),
            field="evaluation_contract.nonfatal_search_fallback_keys",
        )
    )
    allowed_prefixes = tuple(
        _string(
            value, field="evaluation_contract.nonfatal_search_fallback_prefixes[]"
        )
        for value in _sequence(
            evaluation_contract.get("nonfatal_search_fallback_prefixes"),
            field="evaluation_contract.nonfatal_search_fallback_prefixes",
        )
    )
    if allowed_fallbacks != NONFATAL_SEARCH_FALLBACK_KEYS or set(
        allowed_prefixes
    ) != set(NONFATAL_SEARCH_FALLBACK_PREFIXES):
        raise StageEvaluationError(
            "evaluation_contract nonfatal search fallback policy mismatch"
        )
    later_contracts = _mapping(
        spec.get("later_stage_decision_contracts"),
        field="later_stage_decision_contracts",
    )
    if later_contracts.get("frozen_before_result_admission") is not True:
        raise StageEvaluationError("later-stage contracts are not marked frozen")
    declared_later = {
        key: later_contracts.get(key) for key in LATER_STAGE_DECISION_CONTRACT
    }
    if declared_later != LATER_STAGE_DECISION_CONTRACT:
        raise StageEvaluationError("later-stage decision contract mismatch")
    if spec.get("stage4_controls") != STAGE4_CONTROL_CONTRACT:
        raise StageEvaluationError("immutable Stage4 control contract mismatch")
    if (
        spec.get("stage4_control_evaluation_contract")
        != STAGE4_CONTROL_EVALUATION_CONTRACT
    ):
        raise StageEvaluationError("Stage4 control evaluation contract mismatch")
    if spec.get("stage5_baseline") != STAGE5_BASELINE_CONTRACT:
        raise StageEvaluationError("immutable Stage5 baseline contract mismatch")
    if spec.get("stage5_run_contract") != STAGE5_RUN_CONTRACT:
        raise StageEvaluationError("Stage5 replay run contract mismatch")
    opponent_contracts = _mapping(spec.get("opponents"), field="opponents")
    baseline_name = _string(baseline_identity.get("name"), field="baseline.name")
    candidate_name = _string(candidate_identity.get("name"), field="candidate.name")
    # Validate identities even before opening result artifacts.
    _hash(baseline_identity.get("tree_sha256"), field="baseline.tree_sha256")
    _hash(baseline_identity.get("archive_sha256"), field="baseline.archive_sha256")
    _hash(candidate_identity.get("tree_sha256"), field="candidate.tree_sha256")
    _hash(candidate_identity.get("archive_sha256"), field="candidate.archive_sha256")
    if _boolean(
        baseline_identity.get("expected_s2_enabled"),
        field="baseline.expected_s2_enabled",
    ):
        raise StageEvaluationError("baseline.expected_s2_enabled must be false")
    if not _boolean(
        candidate_identity.get("expected_s2_enabled"),
        field="candidate.expected_s2_enabled",
    ):
        raise StageEvaluationError("candidate.expected_s2_enabled must be true")
    baseline_manifest = _validate_package_manifest(
        baseline_identity, spec_path=spec_path, field="baseline"
    )
    candidate_manifest = _validate_package_manifest(
        candidate_identity, spec_path=spec_path, field="candidate"
    )

    stages = _mapping(spec.get("stages"), field="stages")
    if "stage1" not in stages:
        raise StageEvaluationError("stages.stage1 is required")
    top_baselines = baseline_identity.get("cells")
    stage1_value = stages["stage1"]
    if stage1_value is None:
        raise StageEvaluationError("stages.stage1 cannot be pending")
    stage1 = _stage_comparison(
        "stage1",
        _mapping(stage1_value, field="stages.stage1"),
        spec_path=spec_path,
        baseline_identity=baseline_identity,
        candidate_identity=candidate_identity,
        evaluation_contract=evaluation_contract,
        opponent_contracts=opponent_contracts,
        top_baselines=top_baselines,
    )
    stage1["decision"] = _stage1_decision(stage1, spec.get("stage1_decision"))
    output_stages: dict[str, Any] = {"stage1": stage1}
    unknown_stages = set(stages) - set(SEQUENTIAL_STAGES)
    if unknown_stages:
        raise StageEvaluationError(
            "unknown stage declarations: " + ", ".join(sorted(unknown_stages))
        )
    blocking_kind = (
        "KILL" if stage1["decision"]["verdict"] == "KILL" else None
    )
    blocking_stage = "stage1" if blocking_kind else None
    for name in SEQUENTIAL_STAGES[1:]:
        stage_value = stages.get(name)
        if blocking_kind is not None:
            output_stages[name] = {
                "status": f"INADMISSIBLE_PRECEDING_STAGE_{blocking_kind}",
                "blocked_by": blocking_stage,
                "decision": {"verdict": "NOT_EVALUATED", "gates": {}},
            }
            continue
        if stage_value is None:
            output_stages[name] = {"status": "PENDING"}
            blocking_kind = "PENDING"
            blocking_stage = name
            continue
        if name == "stage6":
            raise StageEvaluationError(
                "Stage6 sealed holdout is outside this evaluator and must remain pending"
            )
        stage = _mapping(stage_value, field=f"stages.{name}")
        expected_stage_keys = {
            "stage2": {"baseline_cells", "candidate_cells"},
            "stage3": {"baseline_cells", "candidate_cells"},
            "stage4": {"candidate_cells"},
            "stage5": {"candidate_result"},
        }[name]
        if set(stage) != expected_stage_keys:
            raise StageEvaluationError(
                f"stages.{name} keys must be exactly {sorted(expected_stage_keys)}"
            )
        if name in {"stage2", "stage3"}:
            evaluated = _stage_comparison(
                name,
                stage,
                spec_path=spec_path,
                baseline_identity=baseline_identity,
                candidate_identity=candidate_identity,
                evaluation_contract=evaluation_contract,
                opponent_contracts=opponent_contracts,
                top_baselines=None,
            )
            evaluated["decision"] = (
                _stage2_decision(evaluated)
                if name == "stage2"
                else _stage3_decision(evaluated)
            )
        elif name == "stage4":
            evaluated = _stage4_evaluation(
                stage,
                spec=spec,
                spec_path=spec_path,
                baseline_identity=baseline_identity,
                candidate_identity=candidate_identity,
                evaluation_contract=evaluation_contract,
                opponent_contracts=opponent_contracts,
            )
            evaluated["decision"] = _stage4_decision(evaluated)
        else:
            evaluated = _stage5_evaluation(
                stage, spec=spec, spec_path=spec_path
            )
        output_stages[name] = evaluated
        if evaluated["decision"]["verdict"] == "KILL":
            blocking_kind = "KILL"
            blocking_stage = name

    return {
        "schema": REPORT_SCHEMA,
        "spec": {"path": report_spec_path, "sha256": spec_hash},
        "evidence_files": evidence_files,
        "later_stage_decision_contracts": {
            "frozen_before_result_admission": True,
            **LATER_STAGE_DECISION_CONTRACT,
        },
        "baseline": {
            "name": baseline_name,
            "tree_sha256": str(baseline_identity["tree_sha256"]).lower(),
            "archive_sha256": str(baseline_identity["archive_sha256"]).lower(),
            "package_manifest": baseline_manifest,
        },
        "candidate": {
            "name": candidate_name,
            "tree_sha256": str(candidate_identity["tree_sha256"]).lower(),
            "archive_sha256": str(candidate_identity["archive_sha256"]).lower(),
            "package_manifest": candidate_manifest,
        },
        "stages": output_stages,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        output = args.output.resolve()
        spec_path = args.spec.resolve()
        if output == spec_path:
            raise StageEvaluationError("--output must not overwrite the spec")
        report = evaluate_spec(args.spec)
        evidence_paths = {
            _resolve_report_path(
                item["path"], field=f"report.evidence_files[{index}].path"
            )
            for index, item in enumerate(report["evidence_files"])
        }
        stage_paths = {
            _resolve_report_path(
                cell["source"]["path"],
                field=f"report.stages.{stage_name}.{arm_key}[{index}].source.path",
            )
            for stage_name, stage in report["stages"].items()
            if isinstance(stage, Mapping)
            for arm_key in ("baseline_cells", "candidate_cells")
            for index, cell in enumerate(stage.get(arm_key, []))
        }
        for stage_name, stage in report["stages"].items():
            if not isinstance(stage, Mapping):
                continue
            for source_key in ("baseline", "candidate"):
                source_value = stage.get(source_key)
                if isinstance(source_value, Mapping) and isinstance(
                    source_value.get("source"), Mapping
                ):
                    stage_paths.add(
                        _resolve_report_path(
                            source_value["source"]["path"],
                            field=(
                                f"report.stages.{stage_name}.{source_key}.source.path"
                            ),
                        )
                    )
        if output in evidence_paths | stage_paths:
            raise StageEvaluationError("--output must not overwrite evidence")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except (OSError, StageEvaluationError) as error:
        parser.error(str(error))
    verdicts = [
        stage.get("decision", {}).get("verdict")
        for stage in report["stages"].values()
        if isinstance(stage, Mapping)
    ]
    return 2 if "KILL" in verdicts else 0


if __name__ == "__main__":
    raise SystemExit(main())
