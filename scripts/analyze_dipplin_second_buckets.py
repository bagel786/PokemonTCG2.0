#!/usr/bin/env python3
"""Analyze retained actual-second Dipplin traces without running games.

Full causal buckets are built only from per-game rows carrying the exact
``dipplin-second-bucket-trace-v1`` payload.  Historical aggregate-only files
are retained as explicitly separate context; their totals are never treated
as per-game observations or crossed with outcomes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


ANALYSIS_SCHEMA = "dipplin-second-bucket-analysis-v1"
TRACE_SCHEMA = "dipplin-second-bucket-trace-v1"
REFERENCE_BUCKET = "volbeat_active_quick_sign_legal"
BUCKETS = (
    REFERENCE_BUCKET,
    "volbeat_active_quick_sign_unavailable",
    "applin_42_active",
    "applin_92_active",
    "grookey_active",
    "shaymin_active",
    "other_unusual",
)
OUTCOMES = ("win", "loss", "draw")
MECHANISM_FIELDS = (
    "productive_attacks",
    "festival_double_attacks",
    "first_hit_kos",
    "prizes_taken",
    "dead_turns",
    "trapped_active_turns",
)
PREREQUISITES = (
    "dipplin",
    "energy",
    "festival",
    "thwackey",
    "replacement",
    "retreat_promotion",
    "other",
)
EXCLUSION_KEYS = (
    "not_completed",
    "not_actual_second",
    "missing_trace",
    "wrong_trace_schema",
    "trace_incomplete",
    "trace_order_mismatch",
    "trace_outcome_mismatch",
    "unknown_opening_bucket",
    "duplicate",
)


class AnalysisError(ValueError):
    """Raised when inputs cannot form one auditable analytical cohort."""


@dataclass(frozen=True)
class TraceGame:
    source: str
    hero_hash: str | None
    row: Mapping[str, Any]
    trace: Mapping[str, Any]
    outcome: str
    bucket: str


def wilson(wins: int, games: int, z: float = 1.959963984540054) -> list[float]:
    """Return a two-sided 95% Wilson interval for a binary win indicator."""
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


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _safe_rate(numerator: int | float, denominator: int | float) -> float | None:
    return float(numerator) / float(denominator) if denominator else None


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _hero_hash(document: Mapping[str, Any]) -> str | None:
    provenance = document.get("artifact_provenance")
    if isinstance(provenance, Mapping):
        for key in ("submission_a_sha256", "artifact_a_sha256"):
            value = provenance.get(key)
            if isinstance(value, str) and value:
                return value
    value = document.get("hero_sha256")
    return value if isinstance(value, str) and value else None


def _row_outcome(row: Mapping[str, Any]) -> str:
    explicit = row.get("outcome")
    if explicit in OUTCOMES:
        return str(explicit)
    if bool(row.get("draw")):
        return "draw"
    return "win" if bool(row.get("win")) else "loss"


def _results(games: Sequence[TraceGame]) -> dict[str, Any]:
    outcomes = Counter(game.outcome for game in games)
    total = len(games)
    wins = outcomes["win"]
    draws = outcomes["draw"]
    losses = outcomes["loss"]
    return {
        "games": total,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": _safe_rate(wins, total),
        "wilson_95": wilson(wins, total),
    }


def _timing_summary(
    games: Sequence[TraceGame], field: str
) -> dict[str, Any]:
    observed: list[int] = []
    never = 0
    unknown = 0
    for game in games:
        trace = game.trace
        if field not in trace:
            unknown += 1
            continue
        value = trace.get(field)
        if value is None:
            never += 1
            continue
        numeric = _finite_number(value)
        if numeric is None or numeric <= 0 or not numeric.is_integer():
            unknown += 1
            continue
        observed.append(int(numeric))
    known = len(observed) + never
    histogram = Counter(observed)
    return {
        "eligible_games": len(games),
        "known_games": known,
        "coverage_rate": _safe_rate(known, len(games)),
        "observed_games": len(observed),
        "never_games": never,
        "unknown_games": unknown,
        "observed_rate_known": _safe_rate(len(observed), known),
        "never_rate_known": _safe_rate(never, known),
        "mean_observed": (
            sum(observed) / len(observed) if observed else None
        ),
        "minimum_observed": min(observed) if observed else None,
        "maximum_observed": max(observed) if observed else None,
        "histogram": {
            str(turn): histogram[turn] for turn in sorted(histogram)
        },
    }


def _numeric_summary(
    games: Sequence[TraceGame], getter: Callable[[Mapping[str, Any]], Any]
) -> dict[str, Any]:
    values: list[float] = []
    for game in games:
        value = _finite_number(getter(game.trace))
        if value is not None:
            values.append(value)
    return {
        "eligible_games": len(games),
        "observed_games": len(values),
        "missing_games": len(games) - len(values),
        "coverage_rate": _safe_rate(len(values), len(games)),
        "total": sum(values) if values else None,
        "mean": sum(values) / len(values) if values else None,
        "minimum": min(values) if values else None,
        "maximum": max(values) if values else None,
    }


def _boolean_summary(values: Iterable[Any], eligible: int) -> dict[str, Any]:
    observed = [value for value in values if isinstance(value, bool)]
    true_count = sum(observed)
    return {
        "eligible_games": eligible,
        "observed_games": len(observed),
        "missing_games": eligible - len(observed),
        "coverage_rate": _safe_rate(len(observed), eligible),
        "true_games": true_count,
        "false_games": len(observed) - true_count,
        "true_rate_observed": _safe_rate(true_count, len(observed)),
    }


def _board_summary(games: Sequence[TraceGame], field: str) -> dict[str, Any]:
    boards_by_game = [game.trace.get(field) for game in games]
    boards = [board for board in boards_by_game if isinstance(board, Mapping)]
    eligible = len(games)

    def board_numeric(key: str) -> dict[str, Any]:
        return _numeric_summary(
            games,
            lambda trace: (
                trace[field].get(key)
                if isinstance(trace.get(field), Mapping)
                else None
            ),
        )

    def energy_numeric(key: str) -> dict[str, Any]:
        return _numeric_summary(
            games,
            lambda trace: (
                trace[field]["energy_placement"].get(key)
                if isinstance(trace.get(field), Mapping)
                and isinstance(trace[field].get("energy_placement"), Mapping)
                else None
            ),
        )

    festival = _boolean_summary(
        (
            board.get("festival_active") if isinstance(board, Mapping) else None
            for board in boards_by_game
        ),
        eligible,
    )
    thwackey_values: list[bool | None] = []
    for board in boards_by_game:
        count = (
            _finite_number(board.get("thwackey_count"))
            if isinstance(board, Mapping)
            else None
        )
        thwackey_values.append(count > 0 if count is not None else None)
    thwackey = _boolean_summary(thwackey_values, eligible)
    states = Counter(
        str(board["replacement_state"])
        for board in boards
        if isinstance(board.get("replacement_state"), str)
    )
    state_total = sum(states.values())
    return {
        "eligible_games": eligible,
        "observed_games": len(boards),
        "missing_games": eligible - len(boards),
        "coverage_rate": _safe_rate(len(boards), eligible),
        "bench_count": board_numeric("bench_count"),
        "applin_lines": board_numeric("applin_lines"),
        "engine_lines": board_numeric("engine_lines"),
        "festival_active": festival,
        "thwackey_present": thwackey,
        "replacement_state": {
            "observed_games": state_total,
            "missing_games": eligible - state_total,
            "counts": dict(sorted(states.items())),
            "rates_observed": {
                state: states[state] / state_total
                for state in sorted(states)
            } if state_total else {},
        },
        "energy_placement": {
            key: energy_numeric(key)
            for key in (
                "total",
                "active",
                "applin_line",
                "engine_line",
                "other_support",
            )
        },
    }


def _prerequisite_summary(games: Sequence[TraceGame]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for category in PREREQUISITES:
        result[category] = _numeric_summary(
            games,
            lambda trace, category=category: (
                trace["missed_attack_prerequisites"].get(category, 0)
                if isinstance(trace.get("missed_attack_prerequisites"), Mapping)
                else None
            ),
        )
    return result


def _mechanisms(games: Sequence[TraceGame]) -> dict[str, Any]:
    return {
        "timing": {
            "first_productive_attack_own_turn": _timing_summary(
                games, "first_productive_attack_own_turn"
            ),
            "first_festival_double_attack_own_turn": _timing_summary(
                games, "first_festival_double_attack_own_turn"
            ),
        },
        "mechanism_means": {
            field: _numeric_summary(
                games, lambda trace, field=field: trace.get(field)
            )
            for field in MECHANISM_FIELDS
        },
        "turn_one_board": _board_summary(games, "turn_one_board"),
        "first_attack_board": _board_summary(games, "first_attack_board"),
        "missed_attack_prerequisites": _prerequisite_summary(games),
    }


def _coverage(games: Sequence[TraceGame], mechanisms: Mapping[str, Any]) -> dict[str, Any]:
    outcomes = Counter(game.outcome for game in games)
    timing = mechanisms["timing"]
    means = mechanisms["mechanism_means"]
    return {
        "eligible_games": len(games),
        "outcomes": {outcome: outcomes[outcome] for outcome in OUTCOMES},
        "timing_known_games": {
            name: int(summary["known_games"])
            for name, summary in timing.items()
        },
        "mechanism_observed_games": {
            name: int(summary["observed_games"])
            for name, summary in means.items()
        },
        "turn_one_board_observed_games": int(
            mechanisms["turn_one_board"]["observed_games"]
        ),
        "first_attack_board_observed_games": int(
            mechanisms["first_attack_board"]["observed_games"]
        ),
    }


def _cohort(games: Sequence[TraceGame]) -> dict[str, Any]:
    mechanisms = _mechanisms(games)
    return {
        "results": _results(games),
        "coverage": _coverage(games, mechanisms),
        "mechanisms": mechanisms,
    }


def _cohort_with_outcomes(games: Sequence[TraceGame]) -> dict[str, Any]:
    result = _cohort(games)
    result["by_outcome"] = {
        outcome: _cohort([game for game in games if game.outcome == outcome])
        for outcome in OUTCOMES
    }
    return result


def _mechanism_rate(
    games: Sequence[TraceGame], field: str, threshold: int | None = None
) -> dict[str, Any]:
    delayed = 0
    known = 0
    for game in games:
        trace = game.trace
        if field not in trace:
            continue
        value = trace.get(field)
        if threshold is not None:
            if value is None:
                known += 1
                delayed += 1
                continue
            numeric = _finite_number(value)
            if numeric is None or numeric <= 0:
                continue
            known += 1
            delayed += int(numeric > threshold)
        else:
            numeric = _finite_number(value)
            if numeric is None:
                continue
            known += 1
            delayed += int(numeric > 0)
    return {"rate": _safe_rate(delayed, known), "known_games": known}


def _opportunity_ranking(
    groups: Mapping[str, Sequence[TraceGame]], total_games: int
) -> dict[str, Any]:
    component_specs = {
        "delayed_first_attack": ("first_productive_attack_own_turn", 2),
        "delayed_first_double_attack": (
            "first_festival_double_attack_own_turn",
            3,
        ),
        "any_dead_turn": ("dead_turns", None),
        "any_trapped_active_turn": ("trapped_active_turns", None),
    }

    def rates(games: Sequence[TraceGame]) -> dict[str, dict[str, Any]]:
        return {
            name: _mechanism_rate(games, field, threshold)
            for name, (field, threshold) in component_specs.items()
        }

    reference_games = list(groups.get(REFERENCE_BUCKET, ()))
    reference_rates = rates(reference_games)
    reference_available = bool(reference_games)
    entries: list[dict[str, Any]] = []
    for bucket in BUCKETS:
        bucket_games = list(groups.get(bucket, ()))
        if not bucket_games:
            continue
        bucket_rates = rates(bucket_games)
        gaps: dict[str, float | None] = {}
        available_gaps: list[float] = []
        for component in component_specs:
            bucket_rate = bucket_rates[component]["rate"]
            reference_rate = reference_rates[component]["rate"]
            if bucket_rate is None:
                gaps[component] = None
                continue
            baseline = (
                float(reference_rate)
                if reference_available and reference_rate is not None
                else 0.0
            )
            gap = max(0.0, float(bucket_rate) - baseline)
            gaps[component] = gap
            available_gaps.append(gap)
        deficit = (
            sum(available_gaps) / len(available_gaps)
            if available_gaps
            else 0.0
        )
        frequency = len(bucket_games) / total_games if total_games else 0.0
        entries.append(
            {
                "bucket": bucket,
                "games": len(bucket_games),
                "bucket_frequency": frequency,
                "mechanism_rates": bucket_rates,
                "positive_gaps_vs_reference": gaps,
                "avoidable_deficit": deficit,
                "opportunity": frequency * deficit,
            }
        )
    bucket_order = {bucket: index for index, bucket in enumerate(BUCKETS)}
    entries.sort(
        key=lambda entry: (
            -float(entry["opportunity"]),
            -int(entry["games"]),
            bucket_order[str(entry["bucket"])],
        )
    )
    for rank, entry in enumerate(entries, 1):
        entry["rank"] = rank
    return {
        "method": {
            "name": "outcome-independent-visible-tempo-gap-v1",
            "uses_outcomes_or_win_rate": False,
            "reference_bucket": REFERENCE_BUCKET,
            "reference_available": reference_available,
            "fallback_when_reference_missing": "ideal zero mechanism-failure rate",
            "component_definitions": {
                "delayed_first_attack": "P(first productive attack after own turn 2, or never)",
                "delayed_first_double_attack": "P(first Festival double attack after own turn 3, or never)",
                "any_dead_turn": "P(dead_turns > 0)",
                "any_trapped_active_turn": "P(trapped_active_turns > 0)",
            },
            "formula": (
                "opportunity = bucket_frequency * mean(nonnegative bucket-minus-"
                "reference mechanism-rate gaps with coverage)"
            ),
            "interpretation": (
                "observational mechanism-triage heuristic, not a causal strength estimate"
            ),
        },
        "reference_mechanism_rates": reference_rates,
        "buckets": entries,
    }


def _aggregate_source(
    source: str, document: Mapping[str, Any]
) -> dict[str, Any]:
    games_value = document.get("games", document.get("scheduled_games", 0))
    wins_value = document.get("wins", document.get("wins_a", 0))
    draws_value = document.get("draws", 0)
    games = int(_finite_number(games_value) or 0)
    wins = int(_finite_number(wins_value) or 0)
    draws = int(_finite_number(draws_value) or 0)
    losses = max(0, games - wins - draws)
    telemetry = document.get("hero_telemetry")
    numeric_telemetry = {
        str(key): value
        for key, value in (telemetry.items() if isinstance(telemetry, Mapping) else ())
        if _finite_number(value) is not None
    }
    return {
        "source": source,
        "hero_hash": _hero_hash(document),
        "opponent_hash": document.get("opponent_sha256"),
        "actual_order": document.get(
            "actual_order", document.get("forced_actual_order")
        ),
        "games": games,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": _safe_rate(wins, games),
        "wilson_95": wilson(wins, games),
        "hero_policy_errors": int(
            _finite_number(document.get("hero_policy_errors")) or 0
        ),
        "opponent_policy_errors": int(
            _finite_number(document.get("opponent_policy_errors")) or 0
        ),
        "hero_telemetry": numeric_telemetry,
        "bucket_analysis_available": False,
    }


def _aggregate_context(
    documents: Sequence[tuple[str, Mapping[str, Any]]]
) -> dict[str, Any]:
    sources = [_aggregate_source(source, document) for source, document in documents]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for source in sources:
        grouped[
            (
                str(source["hero_hash"] or "unknown"),
                str(source["actual_order"] or "unknown"),
            )
        ].append(source)
    groups: list[dict[str, Any]] = []
    for (hero_hash, actual_order), members in sorted(grouped.items()):
        games = sum(int(member["games"]) for member in members)
        wins = sum(int(member["wins"]) for member in members)
        draws = sum(int(member["draws"]) for member in members)
        telemetry: Counter[str] = Counter()
        for member in members:
            telemetry.update(member["hero_telemetry"])
        groups.append(
            {
                "hero_hash": None if hero_hash == "unknown" else hero_hash,
                "actual_order": actual_order,
                "source_count": len(members),
                "games": games,
                "wins": wins,
                "losses": max(0, games - wins - draws),
                "draws": draws,
                "win_rate": _safe_rate(wins, games),
                "wilson_95": wilson(wins, games),
                "hero_telemetry": dict(sorted(telemetry.items())),
                "bucket_analysis_available": False,
            }
        )
    return {
        "note": (
            "Aggregate-only sources are context only. They are never used for "
            "bucket-by-outcome, board, timing, or opportunity calculations."
        ),
        "sources": sources,
        "groups": groups,
    }


def analyze_documents(
    documents: Sequence[tuple[str | Path, Mapping[str, Any]]],
    *,
    allow_mixed_hero_hashes: bool = False,
) -> dict[str, Any]:
    """Analyze already-loaded evaluation documents."""
    normalized = [(str(source), document) for source, document in documents]
    row_documents: list[tuple[str, Mapping[str, Any]]] = []
    aggregate_documents: list[tuple[str, Mapping[str, Any]]] = []
    for source, document in normalized:
        if not isinstance(document, Mapping):
            raise AnalysisError(f"{source}: top-level JSON must be an object")
        if "game_rows" in document:
            if not isinstance(document.get("game_rows"), list):
                raise AnalysisError(f"{source}: game_rows must be an array")
            row_documents.append((source, document))
        else:
            aggregate_documents.append((source, document))

    exclusions = Counter({key: 0 for key in EXCLUSION_KEYS})
    rows_seen = 0
    candidates: list[TraceGame] = []
    seen_rows: set[str] = set()
    row_source_summaries: list[dict[str, Any]] = []
    for source, document in row_documents:
        hero_hash = _hero_hash(document)
        source_rows = document["game_rows"]
        row_source_summaries.append(
            {
                "source": source,
                "hero_hash": hero_hash,
                "rows": len(source_rows),
            }
        )
        for row in source_rows:
            rows_seen += 1
            if not isinstance(row, Mapping) or not bool(row.get("completed")):
                exclusions["not_completed"] += 1
                continue
            if row.get("actual_order") != "second":
                exclusions["not_actual_second"] += 1
                continue
            trace = row.get("second_bucket_trace")
            if not isinstance(trace, Mapping):
                exclusions["missing_trace"] += 1
                continue
            if trace.get("schema") != TRACE_SCHEMA:
                exclusions["wrong_trace_schema"] += 1
                continue
            if (
                not bool(trace.get("completed"))
                or trace.get("collection_complete") is not True
                or bool(trace.get("trace_errors"))
            ):
                exclusions["trace_incomplete"] += 1
                continue
            if trace.get("actual_order") != "second":
                exclusions["trace_order_mismatch"] += 1
                continue
            outcome = _row_outcome(row)
            trace_win = trace.get("win")
            if isinstance(trace_win, bool) and trace_win != (outcome == "win"):
                exclusions["trace_outcome_mismatch"] += 1
                continue
            bucket = trace.get("opening_bucket")
            if bucket not in BUCKETS:
                exclusions["unknown_opening_bucket"] += 1
                continue
            fingerprint = _canonical_digest(
                {"hero_hash": hero_hash, "row": row}
            )
            if fingerprint in seen_rows:
                exclusions["duplicate"] += 1
                continue
            seen_rows.add(fingerprint)
            candidates.append(
                TraceGame(
                    source=source,
                    hero_hash=hero_hash,
                    row=row,
                    trace=trace,
                    outcome=outcome,
                    bucket=str(bucket),
                )
            )

    known_hashes = sorted(
        {game.hero_hash for game in candidates if game.hero_hash is not None}
    )
    if len(known_hashes) > 1 and not allow_mixed_hero_hashes:
        raise AnalysisError(
            "mixed hero submission hashes in traced cohort: "
            + ", ".join(known_hashes)
        )

    groups = {
        bucket: [game for game in candidates if game.bucket == bucket]
        for bucket in BUCKETS
    }
    quality = {
        field: sum(int(game.row.get(field, 0) or 0) for game in candidates)
        for field in (
            "hero_policy_errors",
            "opponent_policy_errors",
            "hero_illegal_actions",
            "opponent_illegal_actions",
        )
    }
    overall = _cohort_with_outcomes(candidates)
    return {
        "schema": ANALYSIS_SCHEMA,
        "trace_schema": TRACE_SCHEMA,
        "source_files": [source for source, _ in normalized],
        "hero_hashes": known_hashes,
        "mixed_hero_hashes_allowed": bool(allow_mixed_hero_hashes),
        "input_coverage": {
            "row_sources": row_source_summaries,
            "aggregate_only_sources": len(aggregate_documents),
            "rows_seen": rows_seen,
            "eligible_traced_games": len(candidates),
            "excluded_rows": {
                key: exclusions[key] for key in EXCLUSION_KEYS
            },
            "quality_counters": quality,
        },
        "overall": overall,
        "buckets": {
            bucket: _cohort_with_outcomes(groups[bucket]) for bucket in BUCKETS
        },
        "opportunity_ranking": _opportunity_ranking(groups, len(candidates)),
        "aggregate_context": _aggregate_context(aggregate_documents),
    }


def analyze_paths(
    paths: Sequence[Path], *, allow_mixed_hero_hashes: bool = False
) -> dict[str, Any]:
    documents: list[tuple[Path, Mapping[str, Any]]] = []
    for path in paths:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise AnalysisError(f"cannot read {path}: {error}") from error
        if not isinstance(document, Mapping):
            raise AnalysisError(f"{path}: top-level JSON must be an object")
        documents.append((path, document))
    return analyze_documents(
        documents, allow_mixed_hero_hashes=allow_mixed_hero_hashes
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--markdown-output",
        type=Path,
        help="optional compact human-readable bucket report",
    )
    parser.add_argument(
        "--allow-mixed-hero-hashes",
        action="store_true",
        help="retain mixed traced hero builds (disabled by default)",
    )
    return parser


def _percent(value: Any) -> str:
    numeric = _finite_number(value)
    return "n/a" if numeric is None else f"{100.0 * numeric:.1f}%"


def render_markdown(result: Mapping[str, Any]) -> str:
    """Render a compact evidence table without concealing coverage gaps."""
    lines = [
        "# Dipplin actual-second causal buckets",
        "",
        (
            f"Eligible traced games: {result['input_coverage']['eligible_traced_games']}; "
            f"aggregate-only context sources: "
            f"{result['input_coverage']['aggregate_only_sources']}."
        ),
        "",
        "| Bucket | Games | Win rate | First attack mean | Never attacked | "
        "First double mean | Dead turns/game | Trapped/game | Opportunity |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    opportunities = {
        str(row["bucket"]): row
        for row in result["opportunity_ranking"]["buckets"]
    }
    for bucket in BUCKETS:
        cell = result["buckets"][bucket]
        games = int(cell["results"]["games"])
        timing = cell["mechanisms"]["timing"]
        attack = timing["first_productive_attack_own_turn"]
        double = timing["first_festival_double_attack_own_turn"]
        means = cell["mechanisms"]["mechanism_means"]
        opportunity = opportunities.get(bucket, {}).get("opportunity")
        lines.append(
            "| " + " | ".join(
                (
                    bucket,
                    str(games),
                    _percent(cell["results"]["win_rate"]),
                    "n/a" if attack["mean_observed"] is None else f"{attack['mean_observed']:.2f}",
                    _percent(attack["never_rate_known"]),
                    "n/a" if double["mean_observed"] is None else f"{double['mean_observed']:.2f}",
                    "n/a" if means["dead_turns"]["mean"] is None else f"{means['dead_turns']['mean']:.3f}",
                    "n/a" if means["trapped_active_turns"]["mean"] is None else f"{means['trapped_active_turns']['mean']:.3f}",
                    "n/a" if opportunity is None else f"{opportunity:.4f}",
                )
            ) + " |"
        )
    lines.extend(
        [
            "",
            "Opportunity is an outcome-independent mechanism-triage heuristic, "
            "not a causal strength estimate. Historical aggregate-only files are "
            "kept separate and cannot support bucket-by-outcome analysis.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = analyze_paths(
            args.inputs,
            allow_mixed_hero_hashes=args.allow_mixed_hero_hashes,
        )
    except AnalysisError as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(result), encoding="utf-8")
    concise = {
        "output": str(args.output.resolve()),
        "eligible_traced_games": result["input_coverage"]["eligible_traced_games"],
        "aggregate_only_sources": result["input_coverage"]["aggregate_only_sources"],
        "hero_hashes": result["hero_hashes"],
    }
    print(json.dumps(concise, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
