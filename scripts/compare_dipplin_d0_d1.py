#!/usr/bin/env python3
"""Strict, unpaired qualification comparison for frozen FESTIVAL-D0/D1.

The native engine seeds deals from ``std::random_device``.  Reports are matched
by opponent identity while their Python/NumPy schedule blocks remain separate;
even equal schedule labels do *not* create paired games.  This tool only reports
independent-arm estimates and refuses inputs labelled otherwise.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "dipplin-d0-d1-comparison-v1"
EVALUATION_SCHEMA = "dipplin-authentic-evaluation-v1"
VERDICT_D1 = "D1_QUALIFIED"
VERDICT_D0 = "D0_PREFERRED"

D1_ALIASES = {
    "attempts": ("d1_attempts", "search_attempts", "searches_started"),
    "abstentions": ("d1_abstentions", "search_abstentions", "abstentions"),
    "overrides": (
        "d1_overrides",
        "search_interventions",
        "search_overrides",
        "interventions",
    ),
    "disagreements": ("d0_d1_disagreements", "search_disagreements"),
}
CONTEXT_PREFIXES = (
    "d1_override_context_",
    "search_intervention_context_",
    "d1_context_",
)


class ComparisonError(ValueError):
    """An input cannot support an auditable D0/D1 comparison."""


@dataclass(frozen=True)
class QualificationThresholds:
    """Predeclared conservative gates; all values are serialized in output."""

    min_opponents: int = 4
    min_independent_blocks: int = 2
    min_games_per_opponent_block: int = 20
    min_intervention_games: int = 20
    material_matchup_drop: float = 0.05
    material_order_drop: float = 0.05
    high_frequency_context_game_rate: float = 0.10
    negative_context_margin: float = 0.0
    max_d1_p99_ms: float = 2000.0
    max_d1_max_ms: float = 2500.0

    def validate(self) -> None:
        integer_fields = (
            self.min_opponents,
            self.min_independent_blocks,
            self.min_games_per_opponent_block,
            self.min_intervention_games,
        )
        if any(value <= 0 for value in integer_fields):
            raise ComparisonError("minimum sample thresholds must be positive")
        rates = (
            self.material_matchup_drop,
            self.material_order_drop,
            self.high_frequency_context_game_rate,
            self.negative_context_margin,
        )
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in rates):
            raise ComparisonError("rate thresholds must be finite values in [0, 1]")
        if self.max_d1_p99_ms <= 0 or self.max_d1_max_ms <= 0:
            raise ComparisonError("latency thresholds must be positive")


def _number(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ComparisonError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ComparisonError(f"{field} must be finite")
    return result


def _integer(value: object, *, field: str, minimum: int = 0) -> int:
    number = _number(value, field=field)
    if not number.is_integer() or number < minimum:
        raise ComparisonError(f"{field} must be an integer >= {minimum}")
    return int(number)


def _mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ComparisonError(f"{field} must be an object")
    return value


def _hash(value: object, *, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ComparisonError(f"{field} must be a SHA-256 digest")
    try:
        bytes.fromhex(value)
    except ValueError as error:
        raise ComparisonError(f"{field} must be a SHA-256 digest") from error
    return value.lower()


def wilson(wins: int, games: int, z: float = 1.959963984540054) -> list[float]:
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


def _cell(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    selected = list(rows)
    completed = [row for row in selected if bool(row["completed"])]
    wins = sum(int(row["win"]) for row in completed)
    draws = sum(int(row.get("draw", 0)) for row in completed)
    games = len(completed)
    return {
        "scheduled_games": len(selected),
        "games": games,
        "failed_games": len(selected) - games,
        "wins": wins,
        "draws": draws,
        "losses": games - wins - draws,
        "win_rate": wins / games if games else 0.0,
        "wilson_95": wilson(wins, games),
        "hero_policy_errors": sum(int(row["hero_policy_errors"]) for row in selected),
        "opponent_policy_errors": sum(
            int(row["opponent_policy_errors"]) for row in selected
        ),
        "hero_illegal_actions": sum(int(row["hero_illegal_actions"]) for row in selected),
        "opponent_illegal_actions": sum(
            int(row["opponent_illegal_actions"]) for row in selected
        ),
    }


def _arm_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    opponents = sorted({str(row["_opponent_name"]) for row in rows})
    blocks = sorted(
        {
            (str(row["_opponent_name"]), int(row["_schedule_seed"]))
            for row in rows
        }
    )
    return {
        "overall": _cell(rows),
        "opponent": {
            name: _cell(row for row in rows if row["_opponent_name"] == name)
            for name in opponents
        },
        "actual_order": {
            order: _cell(row for row in rows if row["actual_order"] == order)
            for order in ("first", "second")
        },
        "seat": {
            str(seat): _cell(row for row in rows if int(row["hero_seat"]) == seat)
            for seat in (0, 1)
        },
        "schedule_block": {
            f"{opponent}@{seed}": _cell(
                row
                for row in rows
                if row["_opponent_name"] == opponent
                and row["_schedule_seed"] == seed
            )
            for opponent, seed in blocks
        },
    }


def independent_difference(d1: Mapping[str, Any], d0: Mapping[str, Any]) -> dict[str, Any]:
    """Newcombe hybrid-score interval for two independent binomial arms."""

    n1, w1 = int(d1["games"]), int(d1["wins"])
    n0, w0 = int(d0["games"]), int(d0["wins"])
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


def _difference_summary(d1: Mapping[str, Any], d0: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "overall": independent_difference(d1["overall"], d0["overall"]),
        "opponent": {
            key: independent_difference(d1["opponent"][key], d0["opponent"][key])
            for key in sorted(d0["opponent"])
        },
        "actual_order": {
            key: independent_difference(d1["actual_order"][key], d0["actual_order"][key])
            for key in ("first", "second")
        },
        "seat": {
            key: independent_difference(d1["seat"][key], d0["seat"][key])
            for key in ("0", "1")
        },
    }


def _telemetry_value(telemetry: Mapping[str, Any], aliases: Sequence[str]) -> float:
    # Packages can export a canonical key and a compatibility alias for the
    # same event.  Prefer the first present key instead of double counting it.
    for key in aliases:
        if key in telemetry:
            value = _number(telemetry[key], field=f"hero_telemetry.{key}")
            if value < 0:
                raise ComparisonError(f"hero_telemetry.{key} cannot be negative")
            return value
    return 0.0


def _canonical_d1(row: Mapping[str, Any]) -> dict[str, float]:
    telemetry = _mapping(row.get("hero_telemetry", {}), field="game_rows.hero_telemetry")
    return {
        name: _telemetry_value(telemetry, aliases)
        for name, aliases in D1_ALIASES.items()
    }


def _contexts(row: Mapping[str, Any]) -> dict[str, float]:
    telemetry = _mapping(row.get("hero_telemetry", {}), field="game_rows.hero_telemetry")
    # Prefix ordering is intentional.  For duplicate compatibility aliases,
    # retain the highest-priority counter and never add the same event twice.
    found: dict[str, tuple[int, float, str]] = {}
    for key, raw in telemetry.items():
        for priority, prefix in enumerate(CONTEXT_PREFIXES):
            if not str(key).startswith(prefix):
                continue
            name = str(key)[len(prefix) :] or "unknown"
            value = _number(raw, field=f"hero_telemetry.{key}")
            if value < 0:
                raise ComparisonError(f"hero_telemetry.{key} cannot be negative")
            current = found.get(name)
            if current is None or priority < current[0]:
                found[name] = (priority, value, prefix.rstrip("_"))
            break
    return {name: value[1] for name, value in found.items() if value[1] > 0}


def _validate_rng(report: Mapping[str, Any], *, label: str) -> None:
    rng = _mapping(report.get("rng_provenance"), field=f"{label}.rng_provenance")
    expected = {
        "engine": "unpaired_std_random_device",
        "paired_deals": False,
        "common_random_numbers": False,
    }
    for key, value in expected.items():
        if rng.get(key) != value:
            raise ComparisonError(
                f"{label} must explicitly label native games independent/unpaired; "
                f"rng_provenance.{key}={rng.get(key)!r}"
            )


def _validate_provenance(report: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    provenance = _mapping(report.get("artifact_provenance"), field=f"{label}.artifact_provenance")
    identity = {
        "hero_artifact": _hash(provenance.get("artifact_a_sha256"), field=f"{label}.artifact_a_sha256"),
        "hero_submission": _hash(provenance.get("submission_a_sha256"), field=f"{label}.submission_a_sha256"),
        "hero_deck": _hash(provenance.get("deck_a_sha256"), field=f"{label}.deck_a_sha256"),
        "opponent_artifact": _hash(provenance.get("artifact_b_sha256"), field=f"{label}.artifact_b_sha256"),
        "opponent_submission": _hash(provenance.get("submission_b_sha256"), field=f"{label}.submission_b_sha256"),
        "opponent_deck": _hash(provenance.get("deck_b_sha256"), field=f"{label}.deck_b_sha256"),
        "engine": _hash(provenance.get("engine_sha256"), field=f"{label}.engine_sha256"),
        "evaluator": _hash(provenance.get("evaluator_sha256"), field=f"{label}.evaluator_sha256"),
        "adapter": _hash(provenance.get("external_adapter_sha256"), field=f"{label}.external_adapter_sha256"),
        "evaluation_schema": _hash(provenance.get("evaluation_schema_sha256"), field=f"{label}.evaluation_schema_sha256"),
    }
    if identity["hero_artifact"] != identity["hero_submission"]:
        raise ComparisonError(f"{label} hero artifact/submission hashes disagree")
    if identity["opponent_artifact"] != identity["opponent_submission"]:
        raise ComparisonError(f"{label} opponent artifact/submission hashes disagree")
    if provenance.get("submission_artifacts_unchanged_during_evaluation") is not True:
        raise ComparisonError(f"{label} does not prove artifacts remained unchanged")
    if _hash(
        provenance.get("post_evaluation_submission_a_sha256"),
        field=f"{label}.post_evaluation_submission_a_sha256",
    ) != identity["hero_artifact"]:
        raise ComparisonError(f"{label} hero artifact changed during evaluation")
    if _hash(
        provenance.get("post_evaluation_submission_b_sha256"),
        field=f"{label}.post_evaluation_submission_b_sha256",
    ) != identity["opponent_artifact"]:
        raise ComparisonError(f"{label} opponent artifact changed during evaluation")

    rng = _mapping(provenance.get("rng_contract"), field=f"{label}.artifact_provenance.rng_contract")
    if (
        rng.get("engine") != "independent_std_random_device"
        or rng.get("paired_deals") is not False
        or rng.get("common_random_numbers") is not False
    ):
        raise ComparisonError(f"{label} provenance RNG contract is not independent/unpaired")
    blinding = _mapping(
        provenance.get("runtime_blinding_contract"),
        field=f"{label}.artifact_provenance.runtime_blinding_contract",
    )
    required_blinding = {
        "hero_receives_opponent_label": False,
        "hero_receives_opponent_package_identity": False,
        "agent_call_payload": "engine_observation_only",
        "labels_added_in_parent_after_game": True,
    }
    if any(blinding.get(key) != value for key, value in required_blinding.items()):
        raise ComparisonError(f"{label} does not prove opponent-identity blinding")
    schedule_seed = _integer(provenance.get("seed"), field=f"{label}.seed")
    top_rng = _mapping(report["rng_provenance"], field=f"{label}.rng_provenance")
    if _integer(
        top_rng.get("python_numpy_seed_schedule"),
        field=f"{label}.python_numpy_seed_schedule",
    ) != schedule_seed:
        raise ComparisonError(f"{label} schedule seeds disagree")
    identity["schedule_seed"] = schedule_seed
    identity["opponent_environment"] = _mapping(
        provenance.get("runtime_environment"), field=f"{label}.runtime_environment"
    ).get("submission_b_overrides", {})
    identity["hero_environment"] = _mapping(
        provenance.get("runtime_environment"), field=f"{label}.runtime_environment"
    ).get("submission_a_overrides", {})
    identity["archive_a_sha256"] = provenance.get("archive_a_sha256")
    identity["archive_b_sha256"] = provenance.get("archive_b_sha256")
    for key in ("archive_a_sha256", "archive_b_sha256"):
        if identity[key] is not None:
            identity[key] = _hash(identity[key], field=f"{label}.{key}")
    return identity


def _validate_report(report: Mapping[str, Any], *, arm: str, source: str) -> dict[str, Any]:
    label = f"{arm}:{source}"
    if report.get("schema") != EVALUATION_SCHEMA:
        raise ComparisonError(f"{label} has unsupported schema {report.get('schema')!r}")
    opponent = report.get("opponent_name")
    if not isinstance(opponent, str) or not opponent.strip():
        raise ComparisonError(f"{label}.opponent_name must be a non-empty string")
    opponent = opponent.strip()
    _validate_rng(report, label=label)
    identity = _validate_provenance(report, label=label)
    rows_raw = report.get("game_rows")
    if not isinstance(rows_raw, list) or not rows_raw:
        raise ComparisonError(f"{label}.game_rows must be a non-empty list")
    scheduled = _integer(report.get("scheduled_games"), field=f"{label}.scheduled_games", minimum=1)
    if len(rows_raw) != scheduled:
        raise ComparisonError(f"{label} game_rows length differs from scheduled_games")

    rows: list[dict[str, Any]] = []
    indices: set[int] = set()
    for position, raw in enumerate(rows_raw):
        row = dict(_mapping(raw, field=f"{label}.game_rows[{position}]"))
        index = _integer(row.get("game_index"), field=f"{label}.game_rows[{position}].game_index")
        if index in indices:
            raise ComparisonError(f"{label} has duplicate game_index {index}")
        indices.add(index)
        if row.get("opponent_name") != opponent:
            raise ComparisonError(f"{label} row opponent label does not match report")
        row["hero_seat"] = _integer(row.get("hero_seat"), field=f"{label}.hero_seat")
        if row["hero_seat"] not in (0, 1):
            raise ComparisonError(f"{label}.hero_seat must be 0 or 1")
        if not isinstance(row.get("completed"), bool):
            raise ComparisonError(f"{label}.completed must be boolean")
        row["win"] = _integer(row.get("win"), field=f"{label}.win")
        row["draw"] = _integer(row.get("draw", 0), field=f"{label}.draw")
        if row["win"] not in (0, 1) or row["draw"] not in (0, 1):
            raise ComparisonError(f"{label} win/draw indicators must be binary")
        if row["completed"] and row.get("actual_order") not in ("first", "second"):
            raise ComparisonError(f"{label} completed row has invalid actual_order")
        row["hero_policy_errors"] = _integer(
            row.get("hero_policy_errors"), field=f"{label}.hero_policy_errors"
        )
        row["opponent_policy_errors"] = _integer(
            row.get("opponent_policy_errors"), field=f"{label}.opponent_policy_errors"
        )
        row["hero_illegal_actions"] = _integer(
            row.get("hero_illegal_actions"), field=f"{label}.hero_illegal_actions"
        )
        row["opponent_illegal_actions"] = _integer(
            row.get("opponent_illegal_actions"), field=f"{label}.opponent_illegal_actions"
        )
        row["hero_telemetry"] = dict(
            _mapping(row.get("hero_telemetry", {}), field=f"{label}.hero_telemetry")
        )
        canonical = _canonical_d1(row)
        expected_intervened = canonical["overrides"] > 0 or canonical["disagreements"] > 0
        if bool(row.get("d1_intervened", False)) != expected_intervened:
            raise ComparisonError(f"{label} row d1_intervened disagrees with telemetry")
        row["_canonical_d1"] = canonical
        row["_contexts"] = _contexts(row)
        row["_opponent_name"] = opponent
        row["_schedule_seed"] = identity["schedule_seed"]
        row["_source"] = source
        rows.append(row)

    recomputed = _cell(rows)
    expected = {
        "games": _integer(report.get("games"), field=f"{label}.games"),
        "wins": _integer(report.get("wins_a"), field=f"{label}.wins_a"),
        "failed_games": _integer(report.get("failed_games"), field=f"{label}.failed_games"),
        "hero_policy_errors": _integer(
            report.get("hero_policy_errors"), field=f"{label}.hero_policy_errors"
        ),
        "opponent_policy_errors": _integer(
            report.get("opponent_policy_errors"), field=f"{label}.opponent_policy_errors"
        ),
        "hero_illegal_actions": _integer(
            report.get("hero_illegal_actions"), field=f"{label}.hero_illegal_actions"
        ),
        "opponent_illegal_actions": _integer(
            report.get("opponent_illegal_actions"), field=f"{label}.opponent_illegal_actions"
        ),
    }
    for key, value in expected.items():
        if recomputed[key] != value:
            raise ComparisonError(f"{label} top-level {key} disagrees with game_rows")
    rate = _number(report.get("win_rate_a"), field=f"{label}.win_rate_a")
    if not math.isclose(rate, recomputed["win_rate"], abs_tol=1e-12):
        raise ComparisonError(f"{label} top-level win_rate_a disagrees with game_rows")

    counts = {
        name: sum(row["_canonical_d1"][name] for row in rows)
        for name in D1_ALIASES
    }
    evaluator_analysis = _mapping(
        report.get("d1_intervention_analysis"),
        field=f"{label}.d1_intervention_analysis",
    )
    evaluator_counts = _mapping(
        evaluator_analysis.get("canonical_counts"),
        field=f"{label}.d1_intervention_analysis.canonical_counts",
    )
    evaluator_names = {
        "attempts": "attempts",
        "abstentions": "abstentions",
        "overrides": "overrides",
        "disagreements": "d0_d1_disagreements",
    }
    for name, evaluator_name in evaluator_names.items():
        reported = _number(
            evaluator_counts.get(evaluator_name),
            field=f"{label}.d1_intervention_analysis.canonical_counts.{evaluator_name}",
        )
        if not math.isclose(reported, counts[name], abs_tol=1e-9):
            raise ComparisonError(
                f"{label} canonical D1 count {evaluator_name} disagrees with game_rows"
            )
    if arm == "d0" and any(value != 0 for value in counts.values()):
        raise ComparisonError(f"{label} is not search-off D0; D1 counters are nonzero")
    if counts["attempts"] + 1e-9 < counts["overrides"] + counts["abstentions"]:
        raise ComparisonError(f"{label} D1 attempts are below overrides + abstentions")
    if counts["disagreements"] + 1e-9 < counts["overrides"]:
        raise ComparisonError(f"{label} D1 overrides exceed D0/D1 disagreements")

    latency = _mapping(report.get("latency_ms"), field=f"{label}.latency_ms")
    hero_latency = dict(_mapping(latency.get("hero"), field=f"{label}.latency_ms.hero"))
    for key in ("count", "mean", "p50", "p95", "p99", "max"):
        value = _number(hero_latency.get(key), field=f"{label}.latency_ms.hero.{key}")
        if value < 0:
            raise ComparisonError(f"{label}.latency_ms.hero.{key} cannot be negative")
        hero_latency[key] = value
    return {
        "arm": arm,
        "source": source,
        "opponent": opponent,
        "schedule_seed": identity["schedule_seed"],
        "identity": identity,
        "rows": rows,
        "counts": counts,
        "latency": hero_latency,
        "scheduled_games": scheduled,
    }


def _load(path: Path, arm: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ComparisonError(f"cannot read {arm} evaluation {path}: {error}") from error
    return _validate_report(
        _mapping(payload, field=f"{arm}:{path}"), arm=arm, source=str(path.resolve())
    )


def _frozen_identity(reports: Sequence[Mapping[str, Any]], arm: str) -> dict[str, Any]:
    identities = [report["identity"] for report in reports]
    hero_keys = (
        "hero_artifact",
        "hero_deck",
        "evaluator",
        "adapter",
        "evaluation_schema",
        "engine",
        "hero_environment",
        "archive_a_sha256",
    )
    frozen: dict[str, Any] = {}
    for key in hero_keys:
        values = {json.dumps(identity[key], sort_keys=True) for identity in identities}
        if len(values) != 1:
            raise ComparisonError(f"{arm} is not frozen across shards: {key} differs")
        frozen[key] = identities[0][key]
    return frozen


def _match_reports(
    d0: Sequence[Mapping[str, Any]], d1: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, list[Mapping[str, Any]]], dict[str, list[Mapping[str, Any]]]]:
    def grouped(
        reports: Sequence[Mapping[str, Any]], arm: str
    ) -> dict[str, list[Mapping[str, Any]]]:
        result: dict[str, list[Mapping[str, Any]]] = {}
        seen: set[tuple[str, int]] = set()
        for report in reports:
            key = (str(report["opponent"]), int(report["schedule_seed"]))
            if key in seen:
                raise ComparisonError(f"duplicate {arm} opponent/schedule block: {key}")
            seen.add(key)
            result.setdefault(key[0], []).append(report)
        for values in result.values():
            values.sort(key=lambda report: int(report["schedule_seed"]))
        return result

    left, right = grouped(d0, "d0"), grouped(d1, "d1")
    if set(left) != set(right):
        missing_d1 = sorted(set(left) - set(right))
        missing_d0 = sorted(set(right) - set(left))
        raise ComparisonError(
            f"D0/D1 opponent populations differ; missing_d1={missing_d1}, missing_d0={missing_d0}"
        )
    for opponent in sorted(left):
        reference = left[opponent][0]["identity"]
        all_reports = [*left[opponent], *right[opponent]]
        for identity_key in (
            "opponent_artifact",
            "opponent_deck",
            "opponent_environment",
            "archive_b_sha256",
            "engine",
            "evaluator",
            "adapter",
            "evaluation_schema",
        ):
            if any(
                report["identity"][identity_key] != reference[identity_key]
                for report in all_reports
            ):
                raise ComparisonError(
                    f"D0/D1 opponent provenance differs for {opponent}: {identity_key}"
                )
    return left, right


def _latency_summary(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    count = sum(float(report["latency"]["count"]) for report in reports)
    weighted_mean = (
        sum(
            float(report["latency"]["mean"]) * float(report["latency"]["count"])
            for report in reports
        )
        / count
        if count
        else 0.0
    )
    return {
        "count": int(count),
        "weighted_mean": weighted_mean,
        "worst_reported_p50": max(float(report["latency"]["p50"]) for report in reports),
        "worst_reported_p95": max(float(report["latency"]["p95"]) for report in reports),
        "worst_reported_p99": max(float(report["latency"]["p99"]) for report in reports),
        "max": max(float(report["latency"]["max"]) for report in reports),
        "quantile_aggregation": "maximum of exact per-shard quantiles; raw samples unavailable",
        "per_shard": {
            f"{report['opponent']}@{report['schedule_seed']}": report["latency"]
            for report in reports
        },
    }


def _search_error_telemetry(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for row in rows:
        telemetry = row["hero_telemetry"]
        for key, raw in telemetry.items():
            lowered = str(key).lower()
            scoped = lowered.startswith(("d1_", "search_"))
            failure = "error" in lowered or "release_failure" in lowered or "cleanup_failure" in lowered
            if not scoped or not failure:
                continue
            value = _number(raw, field=f"hero_telemetry.{key}")
            if value < 0:
                raise ComparisonError(f"hero_telemetry.{key} cannot be negative")
            result[str(key)] = result.get(str(key), 0.0) + value
    return dict(sorted(result.items()))


def _d1_analysis(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts = {
        name: sum(row["_canonical_d1"][name] for row in rows)
        for name in D1_ALIASES
    }
    intervention = [
        row
        for row in rows
        if row["_canonical_d1"]["overrides"] > 0
        or row["_canonical_d1"]["disagreements"] > 0
    ]
    abstention_only = [
        row
        for row in rows
        if row["_canonical_d1"]["attempts"] > 0
        and row["_canonical_d1"]["overrides"] == 0
        and row["_canonical_d1"]["disagreements"] == 0
    ]
    no_attempt = [row for row in rows if row["_canonical_d1"]["attempts"] == 0]
    returned_d0 = [
        row
        for row in rows
        if row["_canonical_d1"]["overrides"] == 0
        and row["_canonical_d1"]["disagreements"] == 0
    ]
    contexts: dict[str, dict[str, Any]] = {}
    context_names = sorted({name for row in intervention for name in row["_contexts"]})
    intervention_completed = max(1, _cell(intervention)["games"])
    total_events = sum(
        sum(row["_contexts"].values()) for row in intervention if row["completed"]
    )
    for name in context_names:
        selected = [row for row in intervention if row["_contexts"].get(name, 0) > 0]
        cell = _cell(selected)
        events = sum(float(row["_contexts"].get(name, 0)) for row in selected)
        contexts[name] = {
            "events": events,
            "outcome": cell,
            "intervention_game_rate": cell["games"] / intervention_completed,
            "event_rate": events / total_events if total_events else 0.0,
        }
    attempts = counts["attempts"]
    intervention_cell = _cell(intervention)
    abstention_cell = _cell(abstention_only)
    no_attempt_cell = _cell(no_attempt)
    returned_d0_cell = _cell(returned_d0)
    completed_games = max(1, _cell(rows)["games"])
    return {
        "canonical_counts": counts,
        "event_rates": {
            "abstention_per_attempt": counts["abstentions"] / attempts if attempts else 0.0,
            "override_per_attempt": counts["overrides"] / attempts if attempts else 0.0,
            "disagreement_per_attempt": counts["disagreements"] / attempts if attempts else 0.0,
        },
        "games": {
            "intervention": intervention_cell,
            "abstention_only": abstention_cell,
            "no_attempt": no_attempt_cell,
            "returned_d0": returned_d0_cell,
        },
        "game_rates": {
            "intervention": intervention_cell["games"] / completed_games,
            "abstention_only": abstention_cell["games"] / completed_games,
            "no_attempt": no_attempt_cell["games"] / completed_games,
            "returned_d0": returned_d0_cell["games"] / completed_games,
        },
        "route_splits": {
            "intervention": _arm_summary(intervention),
            "abstention_only": _arm_summary(abstention_only),
            "no_attempt": _arm_summary(no_attempt),
        },
        "context_outcomes": contexts,
        "error_telemetry": _search_error_telemetry(rows),
    }


def compare_reports(
    d0_reports: Sequence[Mapping[str, Any]],
    d1_reports: Sequence[Mapping[str, Any]],
    *,
    thresholds: QualificationThresholds | None = None,
) -> dict[str, Any]:
    """Validate, aggregate, and qualify already-loaded evaluator reports."""

    limits = thresholds or QualificationThresholds()
    limits.validate()
    if not d0_reports or not d1_reports:
        raise ComparisonError("at least one D0 and one D1 report are required")
    d0 = [
        _validate_report(report, arm="d0", source=f"memory:d0:{index}")
        for index, report in enumerate(d0_reports)
    ]
    d1 = [
        _validate_report(report, arm="d1", source=f"memory:d1:{index}")
        for index, report in enumerate(d1_reports)
    ]
    return _compare_validated(d0, d1, limits)


def compare_paths(
    d0_paths: Sequence[Path],
    d1_paths: Sequence[Path],
    *,
    thresholds: QualificationThresholds | None = None,
) -> dict[str, Any]:
    limits = thresholds or QualificationThresholds()
    limits.validate()
    if not d0_paths or not d1_paths:
        raise ComparisonError("at least one D0 and one D1 report are required")
    return _compare_validated(
        [_load(path, "d0") for path in d0_paths],
        [_load(path, "d1") for path in d1_paths],
        limits,
    )


def _compare_validated(
    d0: Sequence[Mapping[str, Any]],
    d1: Sequence[Mapping[str, Any]],
    limits: QualificationThresholds,
) -> dict[str, Any]:
    d0_frozen = _frozen_identity(d0, "d0")
    d1_frozen = _frozen_identity(d1, "d1")
    if d0_frozen["hero_deck"] != d1_frozen["hero_deck"]:
        raise ComparisonError("D1 was not evaluated with the frozen D0 deck")
    if d0_frozen["hero_artifact"] == d1_frozen["hero_artifact"]:
        raise ComparisonError("D0 and D1 hero artifacts are identical")
    matched_d0, matched_d1 = _match_reports(d0, d1)
    opponents = sorted(matched_d0)
    schedule_seeds = {
        arm: {
            opponent: [int(report["schedule_seed"]) for report in groups[opponent]]
            for opponent in opponents
        }
        for arm, groups in (("d0", matched_d0), ("d1", matched_d1))
    }

    d0_rows = [row for report in d0 for row in report["rows"]]
    d1_rows = [row for report in d1 for row in report["rows"]]
    summary_d0 = _arm_summary(d0_rows)
    summary_d1 = _arm_summary(d1_rows)
    differences = _difference_summary(summary_d1, summary_d0)
    search = _d1_analysis(d1_rows)
    latency_d0 = _latency_summary(d0)
    latency_d1 = _latency_summary(d1)

    matchup_collapses = {
        name: difference
        for name, difference in differences["opponent"].items()
        if difference["estimate"] < -limits.material_matchup_drop
    }
    order_collapses = {
        name: difference
        for name, difference in differences["actual_order"].items()
        if difference["estimate"] < -limits.material_order_drop
    }
    intervention = search["games"]["intervention"]
    abstention = search["games"]["abstention_only"]
    intervention_delta = independent_difference(intervention, abstention)
    negative_contexts: dict[str, Any] = {}
    for name, context in search["context_outcomes"].items():
        frequency = float(context["intervention_game_rate"])
        rate = float(context["outcome"]["win_rate"])
        benchmark = float(abstention["win_rate"])
        if (
            frequency >= limits.high_frequency_context_game_rate
            and rate + limits.negative_context_margin < benchmark
        ):
            negative_contexts[name] = {
                **context,
                "abstention_only_win_rate": benchmark,
                "difference": rate - benchmark,
            }

    # A fresh D1 shard is compared with the aggregate frozen-D0 estimate for
    # the same opponent.  These are still independent samples; no D0 row is
    # paired to a D1 row or schedule seed.
    d1_block_comparisons = {
        opponent: {
            str(report["schedule_seed"]): independent_difference(
                _cell(report["rows"]), summary_d0["opponent"][opponent]
            )
            for report in matched_d1[opponent]
        }
        for opponent in opponents
    }
    all_blocks_positive = all(
        difference["estimate"] > 0
        for comparisons in d1_block_comparisons.values()
        for difference in comparisons.values()
    )
    per_block_sample_ok = all(
        report["scheduled_games"] >= limits.min_games_per_opponent_block
        for report in (*d0, *d1)
    )
    independent_blocks = min(
        min(len(matched_d0[opponent]), len(matched_d1[opponent]))
        for opponent in opponents
    )
    d0_clean = (
        summary_d0["overall"]["failed_games"] == 0
        and summary_d0["overall"]["hero_policy_errors"] == 0
        and summary_d0["overall"]["opponent_policy_errors"] == 0
        and summary_d0["overall"]["hero_illegal_actions"] == 0
        and summary_d0["overall"]["opponent_illegal_actions"] == 0
    )
    d1_clean = (
        summary_d1["overall"]["failed_games"] == 0
        and summary_d1["overall"]["hero_policy_errors"] == 0
        and summary_d1["overall"]["opponent_policy_errors"] == 0
        and summary_d1["overall"]["hero_illegal_actions"] == 0
        and summary_d1["overall"]["opponent_illegal_actions"] == 0
        and not any(value > 0 for value in search["error_telemetry"].values())
    )
    checks = {
        "minimum_primary_population": len(opponents) >= limits.min_opponents,
        "independent_fresh_schedule_blocks": independent_blocks >= limits.min_independent_blocks,
        "minimum_games_each_opponent_block": per_block_sample_ok,
        "frozen_d0_is_error_free": d0_clean,
        "d1_search_is_error_free": d1_clean,
        "d1_search_was_exercised": search["canonical_counts"]["attempts"] > 0,
        "d1_overrode_d0": search["canonical_counts"]["overrides"] > 0,
        "minimum_intervention_games": intervention["games"] >= limits.min_intervention_games,
        "abstention_comparator_available": abstention["games"] > 0,
        "overall_independent_95ci_excludes_zero": differences["overall"]["confidence_95"][0] > 0,
        "every_independent_block_improves": all_blocks_positive,
        "no_material_matchup_collapse": not matchup_collapses,
        "no_material_actual_order_collapse": not order_collapses,
        "intervention_games_outperform_abstention_games": (
            intervention["games"] > 0
            and abstention["games"] > 0
            and intervention_delta["estimate"] > 0
        ),
        "intervention_context_telemetry_present": bool(search["context_outcomes"]),
        "no_negative_high_frequency_intervention_context": not negative_contexts,
        "d1_p99_latency_within_budget": latency_d1["worst_reported_p99"] <= limits.max_d1_p99_ms,
        "d1_max_latency_within_budget": latency_d1["max"] <= limits.max_d1_max_ms,
    }
    failed = [name for name, passed in checks.items() if not passed]
    verdict = VERDICT_D1 if not failed else VERDICT_D0
    return {
        "schema": SCHEMA,
        "verdict": verdict,
        "comparison_design": {
            "native_engine_games": "independent_unpaired",
            "paired": False,
            "common_random_numbers": False,
            "report_matching": "opponent_name only",
            "warning": (
                "Reports are matched only by opponent identity; schedule seeds are "
                "independent arm labels and do not pair native deals. All deltas and "
                "intervals are independent-arm estimates. Intervention/abstention "
                "outcomes are selection-conditioned descriptions, not causal uplift."
            ),
        },
        "inputs": {
            "d0": [report["source"] for report in d0],
            "d1": [report["source"] for report in d1],
        },
        "provenance": {
            "d0_frozen": d0_frozen,
            "d1_frozen": d1_frozen,
            "opponents": {
                opponent: {
                    "artifact_sha256": matched_d0[opponent][0]["identity"]["opponent_artifact"],
                    "deck_sha256": matched_d0[opponent][0]["identity"]["opponent_deck"],
                    "archive_sha256": matched_d0[opponent][0]["identity"]["archive_b_sha256"],
                    "runtime_environment": matched_d0[opponent][0]["identity"]["opponent_environment"],
                }
                for opponent in opponents
            },
            "schedule_seeds_by_arm_and_opponent": schedule_seeds,
            "artifact_validation": "passed",
        },
        "sample": {
            "opponents": opponents,
            "opponent_count": len(opponents),
            "minimum_independent_schedule_blocks_per_opponent_per_arm": independent_blocks,
            "native_games_are_unpaired": True,
        },
        "performance": {
            "d0": summary_d0,
            "d1": summary_d1,
            "d1_minus_d0_independent": differences,
            "d1_block_minus_same_opponent_frozen_d0_independent": d1_block_comparisons,
        },
        "d1_search": {
            **search,
            "intervention_minus_abstention_independent": intervention_delta,
            "outcome_interpretation": "selection-conditioned, independent game groups",
        },
        "latency_ms": {"d0": latency_d0, "d1": latency_d1},
        "flags": {
            "material_matchup_collapses": matchup_collapses,
            "material_actual_order_collapses": order_collapses,
            "negative_high_frequency_intervention_contexts": negative_contexts,
        },
        "qualification": {
            "thresholds": asdict(limits),
            "checks": checks,
            "failed_checks": failed,
            "verdict": verdict,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--d0", type=Path, nargs="+", action="append", required=True,
        help="one or more frozen D0 evaluator JSON files; flag may be repeated",
    )
    parser.add_argument(
        "--d1", type=Path, nargs="+", action="append", required=True,
        help="one or more frozen D1 evaluator JSON files; flag may be repeated",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-opponents", type=int, default=4)
    parser.add_argument("--min-independent-blocks", type=int, default=2)
    parser.add_argument("--min-games-per-opponent-block", type=int, default=20)
    parser.add_argument("--min-intervention-games", type=int, default=20)
    parser.add_argument("--material-matchup-drop", type=float, default=0.05)
    parser.add_argument("--material-order-drop", type=float, default=0.05)
    parser.add_argument("--high-frequency-context-game-rate", type=float, default=0.10)
    parser.add_argument("--negative-context-margin", type=float, default=0.0)
    parser.add_argument("--max-d1-p99-ms", type=float, default=2000.0)
    parser.add_argument("--max-d1-max-ms", type=float, default=2500.0)
    return parser


def _flatten(paths: Sequence[Sequence[Path]]) -> list[Path]:
    return [path for group in paths for path in group]


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    thresholds = QualificationThresholds(
        min_opponents=args.min_opponents,
        min_independent_blocks=args.min_independent_blocks,
        min_games_per_opponent_block=args.min_games_per_opponent_block,
        min_intervention_games=args.min_intervention_games,
        material_matchup_drop=args.material_matchup_drop,
        material_order_drop=args.material_order_drop,
        high_frequency_context_game_rate=args.high_frequency_context_game_rate,
        negative_context_margin=args.negative_context_margin,
        max_d1_p99_ms=args.max_d1_p99_ms,
        max_d1_max_ms=args.max_d1_max_ms,
    )
    try:
        result = compare_paths(
            _flatten(args.d0), _flatten(args.d1), thresholds=thresholds
        )
    except ComparisonError as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "verdict": result["verdict"],
                "failed_checks": result["qualification"]["failed_checks"],
                "native_games_are_unpaired": True,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
