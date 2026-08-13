#!/usr/bin/env python3
"""Build one auditable Dipplin general-strength dashboard from frozen results.

The input is a small JSON specification whose paths are resolved relative to
the specification file.  The dashboard keeps anchor, same-deck, replay,
mechanics, and weak-clone evidence separate; it deliberately does not invent a
single scalar score.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence


SCHEMA = "dipplin-general-strength-dashboard-v1"
ORDERS = ("first", "second")
REPLAY_LABELS = (
    "EQUIVALENT",
    "AGENT_DOMINATES",
    "EXPERT_DOMINATES",
    "INCOMPARABLE",
    "UNCERTIFIABLE",
)


class DashboardError(ValueError):
    """A frozen evidence input is missing, inconsistent, or malformed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_object(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _declared_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise DashboardError(f"{field} must be a SHA-256 string")
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise DashboardError(f"{field} must be a 64-character hexadecimal SHA-256")
    return normalized


def _verify_file_sha256(path: Path, declared: Any, field: str = "artifact_sha256") -> str:
    actual = sha256_file(path)
    if declared is not None:
        expected = _declared_sha256(declared, field)
        if actual != expected:
            raise DashboardError(
                f"{path}: {field} mismatch: declared {expected}, actual {actual}"
            )
    return actual


def _required_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DashboardError(f"{field} must be an integer")
    if not math.isfinite(float(value)):
        raise DashboardError(f"{field} must be a finite integer")
    result = int(value)
    if float(value) != result:
        raise DashboardError(f"{field} must be an integer")
    return result


def _optional_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise DashboardError(f"{field} must be an object when present")
    return value


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


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _integer(value: Any, default: int = 0) -> int:
    number = _number(value)
    return int(number) if number is not None else default


def _load(path: Path) -> Mapping[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DashboardError(f"cannot read {path}: {error}") from error
    if not isinstance(document, Mapping):
        raise DashboardError(f"{path}: top-level JSON must be an object")
    return document


def _resolve(base: Path, raw: Any) -> Path:
    if not isinstance(raw, str) or not raw:
        raise DashboardError("evidence path must be a non-empty string")
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _normalize_eval(document: Mapping[str, Any], path: Path) -> dict[str, Any]:
    overall = document.get("overall")
    overall = overall if isinstance(overall, Mapping) else {}
    games = _integer(document.get("games"), _integer(overall.get("games")))
    wins = _integer(
        document.get("wins_a"),
        _integer(document.get("wins"), _integer(overall.get("wins"))),
    )
    draws = _integer(document.get("draws"), _integer(overall.get("draws")))
    failed = _integer(
        document.get("failed_games"), _integer(overall.get("failed_games"))
    )
    if games < 0 or wins < 0 or draws < 0 or wins + draws > games:
        raise DashboardError(f"{path}: invalid game outcome counts")
    rate = wins / games if games else None
    order = document.get("forced_actual_order", document.get("actual_order"))
    latency = document.get("latency_ms")
    latency = latency.get("hero") if isinstance(latency, Mapping) else None
    if not isinstance(latency, Mapping):
        latency = {}
    provenance = document.get("artifact_provenance")
    provenance = provenance if isinstance(provenance, Mapping) else {}
    tree_hash = provenance.get("submission_a_sha256", document.get("hero_sha256"))
    telemetry = document.get("hero_telemetry")
    telemetry = telemetry if isinstance(telemetry, Mapping) else {}
    unknown = sum(
        float(value)
        for key, value in telemetry.items()
        if _number(value) is not None
        and ("unknown" in str(key).lower() or "unhandled" in str(key).lower())
    )
    return {
        "source": str(path),
        "source_sha256": sha256_file(path),
        "evaluated_tree_sha256": tree_hash,
        "actual_order": order,
        "games": games,
        "wins": wins,
        "losses": games - wins - draws,
        "draws": draws,
        "win_rate": rate,
        "wilson_95": wilson(wins, games),
        "failed_games": failed,
        "hero_policy_errors": _integer(
            document.get("hero_policy_errors"),
            _integer(overall.get("hero_policy_errors")),
        ),
        "opponent_policy_errors": _integer(
            document.get("opponent_policy_errors"),
            _integer(overall.get("opponent_policy_errors")),
        ),
        "hero_illegal_actions": _integer(
            document.get("hero_illegal_actions"),
            _integer(overall.get("hero_illegal_actions")),
        ),
        "opponent_illegal_actions": _integer(
            document.get("opponent_illegal_actions"),
            _integer(overall.get("opponent_illegal_actions")),
        ),
        "unknown_contexts": unknown,
        "latency_ms": {
            key: _number(latency.get(key))
            for key in ("count", "mean", "p95", "p99", "max")
        },
        "artifacts_unchanged": provenance.get(
            "submission_artifacts_unchanged_during_evaluation"
        ),
    }


def _verify_eval_declaration(
    declaration: Mapping[str, Any],
    cell: Mapping[str, Any],
    path: Path,
    *,
    expected_order: str | None = None,
) -> None:
    _verify_file_sha256(path, declaration.get("artifact_sha256"))
    if _integer(cell.get("games")) <= 0:
        raise DashboardError(f"{path}: evaluation must contain at least one game")
    for declared_key, actual_key in (
        ("expected_games", "games"),
        ("expected_wins", "wins"),
    ):
        if declared_key not in declaration:
            continue
        expected = _required_integer(declaration[declared_key], declared_key)
        actual = _required_integer(cell.get(actual_key), actual_key)
        if actual != expected:
            raise DashboardError(
                f"{path}: {declared_key} mismatch: declared {expected}, actual {actual}"
            )
    explicit_order = declaration.get("expected_order")
    if (
        expected_order is not None
        and explicit_order is not None
        and explicit_order != expected_order
    ):
        raise DashboardError(
            f"{path}: expected_order {explicit_order!r} conflicts with evidence slot "
            f"{expected_order!r}"
        )
    declared_order = expected_order if expected_order is not None else explicit_order
    if declared_order is not None:
        if declared_order not in ORDERS:
            raise DashboardError(f"{path}: expected_order must be first or second")
        if cell.get("actual_order") != declared_order:
            raise DashboardError(
                f"{path}: expected order mismatch: declared {declared_order}, "
                f"actual {cell.get('actual_order')!r}"
            )
    declared_tree = declaration.get(
        "expected_evaluated_tree_sha256",
        declaration.get("evaluated_tree_sha256"),
    )
    if declared_tree is not None:
        expected_tree = _declared_sha256(
            declared_tree, "expected_evaluated_tree_sha256"
        )
        actual_tree_raw = cell.get("evaluated_tree_sha256")
        if actual_tree_raw is None:
            raise DashboardError(f"{path}: evaluated tree hash is missing")
        actual_tree = _declared_sha256(
            actual_tree_raw, f"{path} evaluated_tree_sha256"
        )
        if actual_tree != expected_tree:
            raise DashboardError(
                f"{path}: evaluated-tree mismatch: declared {expected_tree}, "
                f"actual {actual_tree}"
            )


def _combine(cells: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    games = sum(_integer(cell.get("games")) for cell in cells)
    wins = sum(_integer(cell.get("wins")) for cell in cells)
    draws = sum(_integer(cell.get("draws")) for cell in cells)
    tree_hashes = sorted(
        {
            str(cell["evaluated_tree_sha256"])
            for cell in cells
            if cell.get("evaluated_tree_sha256")
        }
    )
    return {
        "games": games,
        "wins": wins,
        "losses": games - wins - draws,
        "draws": draws,
        "win_rate": wins / games if games else None,
        "wilson_95": wilson(wins, games),
        "evaluated_tree_sha256": tree_hashes,
        "failed_games": sum(_integer(cell.get("failed_games")) for cell in cells),
        "hero_policy_errors": sum(
            _integer(cell.get("hero_policy_errors")) for cell in cells
        ),
        "opponent_policy_errors": sum(
            _integer(cell.get("opponent_policy_errors")) for cell in cells
        ),
        "hero_illegal_actions": sum(
            _integer(cell.get("hero_illegal_actions")) for cell in cells
        ),
        "opponent_illegal_actions": sum(
            _integer(cell.get("opponent_illegal_actions")) for cell in cells
        ),
        "unknown_contexts": sum(
            float(cell.get("unknown_contexts") or 0.0) for cell in cells
        ),
        "sources": [cell.get("source") for cell in cells],
    }


def _anchor_dashboard(
    base: Path, records: Any
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(records, list) or not records:
        raise DashboardError("strong_anchors must be a non-empty array")
    by_opponent: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    normalized: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise DashboardError("each strong anchor record must be an object")
        opponent = str(record.get("opponent") or "").strip()
        order = str(record.get("actual_order") or "").strip()
        if not opponent or order not in ORDERS:
            raise DashboardError("anchor records require opponent and first/second order")
        path = _resolve(base, record.get("path"))
        cell = _normalize_eval(_load(path), path)
        try:
            _verify_eval_declaration(record, cell, path, expected_order=order)
        except DashboardError as error:
            if "expected order mismatch" in str(error):
                raise DashboardError(f"{path}: declared order conflicts with result") from error
            raise
        cell.update({"opponent": opponent, "actual_order": order})
        by_opponent[opponent][order].append(cell)
        normalized.append(cell)
    opponents: dict[str, Any] = {}
    order_rates: dict[str, list[float]] = {order: [] for order in ORDERS}
    opponent_order_balanced_rates: list[float] = []
    all_cells: list[dict[str, Any]] = []
    for opponent in sorted(by_opponent):
        order_cells = {
            order: _combine(by_opponent[opponent].get(order, ()))
            for order in ORDERS
        }
        for order in ORDERS:
            rate = order_cells[order]["win_rate"]
            if rate is not None:
                order_rates[order].append(float(rate))
        opponent_cells = [
            cell
            for order in ORDERS
            for cell in by_opponent[opponent].get(order, ())
        ]
        all_cells.extend(opponent_cells)
        combined = _combine(opponent_cells)
        available_order_rates = [
            float(order_cells[order]["win_rate"])
            for order in ORDERS
            if order_cells[order]["win_rate"] is not None
        ]
        order_balanced = (
            fmean(available_order_rates) if available_order_rates else None
        )
        if order_balanced is not None:
            opponent_order_balanced_rates.append(order_balanced)
        opponents[opponent] = {
            "actual_order": order_cells,
            "overall": {
                **combined,
                "sample_weighted_win_rate": combined["win_rate"],
                "order_balanced_win_rate": order_balanced,
            },
        }
    first = fmean(order_rates["first"]) if order_rates["first"] else None
    second = fmean(order_rates["second"]) if order_rates["second"] else None
    # Each opponent and actual order is one strength cell. Unequal historical
    # replication (100 first versus 300 second games) must not silently give
    # actual-second triple weight in the headline macro.
    macro = (
        fmean(opponent_order_balanced_rates)
        if opponent_order_balanced_rates
        else None
    )
    sample_weighted = _combine(all_cells)
    return (
        {
            "opponents": opponents,
            "anchor_macro": macro,
            "anchor_sample_weighted": sample_weighted["win_rate"],
            "anchor_actual_first": first,
            "anchor_actual_second": second,
            "robust_anchor": min(first, second) if first is not None and second is not None else None,
            "macro_definition": (
                "unweighted mean of opponent order-balanced win rates; each "
                "opponent x actual-order cell has equal weight"
            ),
            "sample_weighted_definition": (
                "pooled wins/games across admitted shards; retained only as a "
                "sampling diagnostic"
            ),
            "robust_anchor_definition": "min(anchor_actual_first, anchor_actual_second)",
        },
        normalized,
    )


def _optional_eval(
    base: Path, raw: Any, *, expected_order: str | None = None
) -> dict[str, Any] | None:
    if raw in (None, ""):
        return None
    declaration = raw if isinstance(raw, Mapping) else {"path": raw}
    path = _resolve(base, declaration.get("path"))
    cell = _normalize_eval(_load(path), path)
    _verify_eval_declaration(
        declaration, cell, path, expected_order=expected_order
    )
    return cell


def _same_deck(base: Path, spec: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    spec = spec if isinstance(spec, Mapping) else {}
    result: dict[str, Any] = {}
    cells: list[dict[str, Any]] = []
    for label in (
        "s1_vs_s1_first",
        "s1_vs_s1_second",
        "candidate_vs_s1_first",
        "candidate_vs_s1_second",
    ):
        expected_order = "first" if label.endswith("_first") else "second"
        cell = _optional_eval(
            base, spec.get(label), expected_order=expected_order
        )
        result[label] = cell
        if cell is not None:
            cells.append(cell)
    return result, cells


def _candidate_dashboard(
    base: Path, candidate: Mapping[str, Any]
) -> dict[str, Any]:
    package_path = _resolve(base, candidate.get("package"))
    if not package_path.is_file():
        raise DashboardError(f"candidate package does not exist: {package_path}")
    package_sha256 = _verify_file_sha256(
        package_path,
        candidate.get("package_sha256"),
        "candidate.package_sha256",
    )
    declared_tree_raw = candidate.get("tree_sha256")
    declared_tree = (
        _declared_sha256(declared_tree_raw, "candidate.tree_sha256")
        if declared_tree_raw is not None
        else None
    )
    manifest_path: Path | None = None
    manifest_sha256: str | None = None
    manifest_tree: str | None = None
    manifest_raw = candidate.get("manifest")
    if manifest_raw not in (None, ""):
        manifest_path = _resolve(base, manifest_raw)
        manifest_sha256 = _verify_file_sha256(
            manifest_path,
            candidate.get("manifest_sha256"),
            "candidate.manifest_sha256",
        )
        manifest = _load(manifest_path)
        output = manifest.get("output")
        output = output if isinstance(output, Mapping) else {}
        manifest_archive_raw = output.get(
            "archive_sha256", manifest.get("package_sha256")
        )
        if manifest_archive_raw is not None:
            manifest_archive = _declared_sha256(
                manifest_archive_raw, "candidate manifest archive_sha256"
            )
            if manifest_archive != package_sha256:
                raise DashboardError(
                    f"{manifest_path}: archive SHA-256 does not match candidate package"
                )
        manifest_tree_raw = output.get(
            "extracted_tree_sha256", manifest.get("tree_sha256")
        )
        if manifest_tree_raw is not None:
            manifest_tree = _declared_sha256(
                manifest_tree_raw, "candidate manifest tree_sha256"
            )
    elif declared_tree is not None:
        raise DashboardError(
            "candidate.tree_sha256 requires candidate.manifest for independent verification"
        )
    if declared_tree is not None:
        if manifest_tree is None:
            raise DashboardError("candidate manifest does not declare an extracted tree hash")
        if manifest_tree != declared_tree:
            raise DashboardError(
                "candidate.tree_sha256 mismatch: "
                f"declared {declared_tree}, manifest {manifest_tree}"
            )
    return {
        "name": candidate.get("name"),
        "source_sha": candidate.get("source_sha"),
        "tree_sha256": declared_tree,
        "verified_tree_sha256": manifest_tree,
        "package": str(package_path),
        "package_sha256": package_sha256,
        "manifest": str(manifest_path) if manifest_path is not None else None,
        "manifest_sha256": manifest_sha256,
    }


def _replay_summary(base: Path, raw: Any, split: str) -> dict[str, Any]:
    if raw in (None, ""):
        return {
            "available": False,
            "split": split,
            "episodes": 0,
            "status": "NOT_RUN",
        }
    declaration = raw if isinstance(raw, Mapping) else {"path": raw}
    path = _resolve(base, declaration.get("path"))
    document = _load(path)
    source_sha256 = _verify_file_sha256(
        path, declaration.get("artifact_sha256")
    )
    for declaration_key, document_key in (
        ("expected_schema", "schema"),
        ("expected_trace_schema", "trace_schema"),
    ):
        if declaration_key in declaration and declaration[declaration_key] != document.get(document_key):
            raise DashboardError(
                f"{path}: {declaration_key} mismatch: declared "
                f"{declaration[declaration_key]!r}, actual {document.get(document_key)!r}"
            )
    document_split = document.get("split")
    if document_split is not None and document_split != split:
        raise DashboardError(
            f"{path}: replay split mismatch: expected {split}, actual {document_split}"
        )
    aggregate = document.get("aggregate")
    regret_layout = isinstance(aggregate, Mapping)
    if regret_layout:
        overall = aggregate
        counts_raw = overall.get("classification_counts")
        rates_raw = overall.get("episode_rates")
        bootstrap = overall.get("episode_bootstrap_95")
        episodes_raw = overall.get("episode_count")
        decisions_raw = overall.get("decision_count")
        if not isinstance(rates_raw, Mapping):
            raise DashboardError(
                f"{path}: regret aggregate requires explicit episode_rates"
            )
        rate_basis = "episode_mean"
    else:
        summary = document.get("summary")
        summary = summary if isinstance(summary, Mapping) else document
        overall_raw = summary.get("overall")
        overall = overall_raw if isinstance(overall_raw, Mapping) else summary
        counts_raw = overall.get("classifications")
        if not isinstance(counts_raw, Mapping):
            counts_raw = overall.get("counts")
        rates_raw = None
        bootstrap = overall.get("bootstrap_95", summary.get("bootstrap_95"))
        episodes_raw = summary.get("episodes", document.get("episodes"))
        decisions_raw = None
        rate_basis = "classification_count"
    if not isinstance(counts_raw, Mapping):
        raise DashboardError(f"{path}: replay result has no classification counts")
    normalized_counts: dict[str, int] = {}
    for label in REPLAY_LABELS:
        if label not in counts_raw:
            continue
        count = _required_integer(counts_raw[label], f"{path} {label} count")
        if count < 0:
            raise DashboardError(f"{path}: replay classification counts cannot be negative")
        normalized_counts[label] = count
    if not normalized_counts:
        raise DashboardError(f"{path}: replay result has no recognized classifications")
    decision_count = sum(normalized_counts.values())
    if decisions_raw is not None:
        declared_decisions = _required_integer(
            decisions_raw, f"{path} decision_count"
        )
        if declared_decisions != decision_count:
            raise DashboardError(
                f"{path}: decision_count does not match classification counts"
            )
    if regret_layout:
        rates: dict[str, float] = {}
        assert isinstance(rates_raw, Mapping)
        for label in REPLAY_LABELS:
            if label not in rates_raw:
                continue
            rate = _number(rates_raw[label])
            if rate is None or not 0.0 <= rate <= 1.0:
                raise DashboardError(f"{path}: invalid episode rate for {label}")
            rates[label] = rate
        if set(rates) != set(normalized_counts):
            raise DashboardError(
                f"{path}: episode_rates and classification_counts cover different labels"
            )
    else:
        rates = {
            label: count / decision_count
            for label, count in normalized_counts.items()
        }
    episodes = _required_integer(episodes_raw, f"{path} episode_count")
    if episodes <= 0:
        raise DashboardError(f"{path}: episode_count must be positive")
    archetypes = overall.get(
        "opponent_archetypes",
        document.get("opponent_archetypes", {}),
    )
    return {
        "available": True,
        "split": split,
        "status": "COMPLETE",
        "source": str(path),
        "source_sha256": source_sha256,
        "episodes": episodes,
        "decisions": decision_count,
        "opponent_archetype_coverage": archetypes if archetypes is not None else {},
        "classifications": normalized_counts,
        "rates": rates,
        "rate_basis": rate_basis,
        "bootstrap_95": bootstrap,
        "sealed_aggregate_only": bool(
            document.get("sealed", document.get("sealed_aggregate_only", False))
        ),
    }


def _integer_counts(raw: Any, field: str) -> dict[str, int]:
    if not isinstance(raw, Mapping):
        raise DashboardError(f"{field} must be an object")
    result: dict[str, int] = {}
    for key, value in raw.items():
        count = _required_integer(value, f"{field}.{key}")
        if count < 0:
            raise DashboardError(f"{field}.{key} cannot be negative")
        result[str(key)] = count
    return result


def _game_results(raw: Any, field: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise DashboardError(f"{field} must be an object")
    games = _required_integer(raw.get("games"), f"{field}.games")
    wins = _required_integer(raw.get("wins"), f"{field}.wins")
    draws = _required_integer(raw.get("draws", 0), f"{field}.draws")
    losses = _required_integer(
        raw.get("losses", games - wins - draws), f"{field}.losses"
    )
    if min(games, wins, draws, losses) < 0 or wins + draws + losses != games:
        raise DashboardError(f"{field} contains inconsistent outcome counts")
    expected_rate = wins / games if games else None
    declared_rate = raw.get("win_rate")
    if declared_rate is not None:
        rate = _number(declared_rate)
        if rate is None or expected_rate is None or not math.isclose(
            rate, expected_rate, rel_tol=0.0, abs_tol=1e-12
        ):
            raise DashboardError(f"{field}.win_rate does not match wins/games")
    return {
        "games": games,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": expected_rate,
        "wilson_95": raw.get("wilson_95", wilson(wins, games)),
    }


def _second_bucket_analysis(base: Path, raw: Any) -> dict[str, Any]:
    if raw in (None, ""):
        return {"available": False, "status": "NOT_RUN"}
    declaration = raw if isinstance(raw, Mapping) else {"path": raw}
    path = _resolve(base, declaration.get("path"))
    document = _load(path)
    source_sha256 = _verify_file_sha256(
        path, declaration.get("artifact_sha256")
    )
    for declaration_key, document_key in (
        ("expected_schema", "schema"),
        ("expected_trace_schema", "trace_schema"),
    ):
        if (
            declaration_key in declaration
            and declaration[declaration_key] != document.get(document_key)
        ):
            raise DashboardError(
                f"{path}: {declaration_key} mismatch: declared "
                f"{declaration[declaration_key]!r}, "
                f"actual {document.get(document_key)!r}"
            )
    coverage = document.get("input_coverage")
    if not isinstance(coverage, Mapping):
        raise DashboardError(f"{path}: bucket analysis requires input_coverage")
    eligible_games = _required_integer(
        coverage.get("eligible_traced_games"),
        f"{path} input_coverage.eligible_traced_games",
    )
    if eligible_games <= 0:
        raise DashboardError(f"{path}: eligible_traced_games must be positive")
    if "expected_eligible_games" in declaration:
        expected_games = _required_integer(
            declaration["expected_eligible_games"], "expected_eligible_games"
        )
        if eligible_games != expected_games:
            raise DashboardError(
                f"{path}: expected_eligible_games mismatch: declared "
                f"{expected_games}, actual {eligible_games}"
            )
    hero_hashes_raw = document.get("hero_hashes")
    if not isinstance(hero_hashes_raw, list) or not hero_hashes_raw:
        raise DashboardError(f"{path}: bucket analysis requires hero_hashes")
    hero_hashes = [
        _declared_sha256(value, f"{path} hero_hashes")
        for value in hero_hashes_raw
    ]
    declared_tree = declaration.get(
        "expected_evaluated_tree_sha256",
        declaration.get("evaluated_tree_sha256"),
    )
    if declared_tree is not None:
        expected_tree = _declared_sha256(
            declared_tree, "expected_evaluated_tree_sha256"
        )
        if sorted(set(hero_hashes)) != [expected_tree]:
            raise DashboardError(
                f"{path}: evaluated-tree mismatch in bucket hero_hashes"
            )
    overall = document.get("overall")
    if not isinstance(overall, Mapping):
        raise DashboardError(f"{path}: bucket analysis requires overall")
    overall_results = _game_results(
        overall.get("results"), f"{path} overall.results"
    )
    if overall_results["games"] != eligible_games:
        raise DashboardError(
            f"{path}: overall results do not match eligible traced games"
        )
    overall_coverage = overall.get("coverage")
    if isinstance(overall_coverage, Mapping):
        covered = _required_integer(
            overall_coverage.get("eligible_games"),
            f"{path} overall.coverage.eligible_games",
        )
        if covered != eligible_games:
            raise DashboardError(
                f"{path}: overall coverage does not match eligible traced games"
            )
    declared_results = declaration.get("expected_results")
    if declared_results is not None:
        if not isinstance(declared_results, Mapping):
            raise DashboardError("expected_results must be an object")
        for key in ("games", "wins", "losses", "draws"):
            if key not in declared_results:
                continue
            expected = _required_integer(
                declared_results[key], f"expected_results.{key}"
            )
            if overall_results[key] != expected:
                raise DashboardError(
                    f"{path}: expected_results.{key} mismatch: declared "
                    f"{expected}, actual {overall_results[key]}"
                )
    rows_seen = _required_integer(
        coverage.get("rows_seen"), f"{path} input_coverage.rows_seen"
    )
    row_sources_raw = coverage.get("row_sources")
    if not isinstance(row_sources_raw, list):
        raise DashboardError(f"{path}: input_coverage.row_sources must be an array")
    row_sources: list[dict[str, Any]] = []
    row_total = 0
    for index, row in enumerate(row_sources_raw):
        if not isinstance(row, Mapping):
            raise DashboardError(f"{path}: row source {index} must be an object")
        rows = _required_integer(row.get("rows"), f"{path} row_sources[{index}].rows")
        if rows < 0:
            raise DashboardError(f"{path}: row source rows cannot be negative")
        row_hero_hash = _declared_sha256(
            row.get("hero_hash"), f"{path} row_sources[{index}].hero_hash"
        )
        if row_hero_hash not in hero_hashes:
            raise DashboardError(
                f"{path}: row source {index} hero hash is not in hero_hashes"
            )
        row_total += rows
        row_sources.append(
            {
                "source": row.get("source"),
                "rows": rows,
                "hero_hash": row_hero_hash,
            }
        )
    if rows_seen != eligible_games or row_total != eligible_games:
        raise DashboardError(
            f"{path}: traced row counts do not match eligible traced games"
        )
    buckets_raw = document.get("buckets")
    if not isinstance(buckets_raw, Mapping):
        raise DashboardError(f"{path}: buckets must be an object")
    bucket_results: dict[str, Any] = {}
    for name, bucket in buckets_raw.items():
        if not isinstance(bucket, Mapping):
            raise DashboardError(f"{path}: bucket {name} must be an object")
        bucket_results[str(name)] = _game_results(
            bucket.get("results"), f"{path} buckets.{name}.results"
        )
    if sum(item["games"] for item in bucket_results.values()) != eligible_games:
        raise DashboardError(f"{path}: bucket game counts do not partition traced games")
    ranking = document.get("opportunity_ranking")
    if not isinstance(ranking, Mapping):
        raise DashboardError(f"{path}: opportunity_ranking must be an object")
    ranking_rows_raw = ranking.get("buckets")
    if not isinstance(ranking_rows_raw, list):
        raise DashboardError(f"{path}: opportunity_ranking.buckets must be an array")
    ranking_rows: list[dict[str, Any]] = []
    for index, row in enumerate(ranking_rows_raw):
        if not isinstance(row, Mapping):
            raise DashboardError(f"{path}: ranking row {index} must be an object")
        bucket_name = str(row.get("bucket") or "").strip()
        if bucket_name not in bucket_results:
            raise DashboardError(
                f"{path}: ranking row {index} names an unknown bucket"
            )
        rank = _required_integer(row.get("rank"), f"{path} ranking[{index}].rank")
        games = _required_integer(
            row.get("games"), f"{path} ranking[{index}].games"
        )
        if games != bucket_results[bucket_name]["games"]:
            raise DashboardError(
                f"{path}: ranking row {index} game count does not match bucket"
            )
        frequency = _number(row.get("bucket_frequency"))
        opportunity = _number(row.get("opportunity"))
        if (
            frequency is None
            or opportunity is None
            or not 0.0 <= frequency <= 1.0
            or opportunity < 0.0
        ):
            raise DashboardError(f"{path}: ranking row {index} has invalid rates")
        ranking_rows.append(
            {
                "rank": rank,
                "bucket": bucket_name,
                "games": games,
                "bucket_frequency": frequency,
                "opportunity": opportunity,
                "avoidable_deficit": _number(row.get("avoidable_deficit")),
                "mechanism_rates": row.get("mechanism_rates"),
            }
        )
    ranks = [row.get("rank") for row in ranking_rows]
    if ranks != list(range(1, len(ranking_rows) + 1)):
        raise DashboardError(f"{path}: opportunity ranks must be unique and ordered")
    ranked_names = {str(row["bucket"]) for row in ranking_rows}
    nonempty_names = {
        name for name, result in bucket_results.items() if result["games"] > 0
    }
    if ranked_names != nonempty_names:
        raise DashboardError(f"{path}: opportunity ranking does not cover all nonempty buckets")
    method = ranking.get("method")
    method = method if isinstance(method, Mapping) else {}
    if method.get("uses_outcomes_or_win_rate") is not False:
        raise DashboardError(
            f"{path}: opportunity ranking must be outcome-independent"
        )
    aggregate_only_sources = _required_integer(
        coverage.get("aggregate_only_sources", 0),
        f"{path} input_coverage.aggregate_only_sources",
    )
    aggregate_context = document.get("aggregate_context")
    aggregate_context = (
        aggregate_context if isinstance(aggregate_context, Mapping) else {}
    )
    aggregate_sources = aggregate_context.get("sources")
    if isinstance(aggregate_sources, list) and len(aggregate_sources) != aggregate_only_sources:
        raise DashboardError(
            f"{path}: aggregate-only source count does not match aggregate context"
        )
    if "expected_aggregate_only_sources" in declaration:
        expected_aggregate_sources = _required_integer(
            declaration["expected_aggregate_only_sources"],
            "expected_aggregate_only_sources",
        )
        if expected_aggregate_sources != aggregate_only_sources:
            raise DashboardError(
                f"{path}: expected_aggregate_only_sources mismatch"
            )
    excluded_rows = _integer_counts(
        coverage.get("excluded_rows", {}), f"{path} excluded_rows"
    )
    quality_counters = _integer_counts(
        coverage.get("quality_counters", {}), f"{path} quality_counters"
    )
    for declaration_key, actual_counts in (
        ("expected_excluded_rows", excluded_rows),
        ("expected_quality_counters", quality_counters),
    ):
        expected_raw = declaration.get(declaration_key)
        if expected_raw is None:
            continue
        expected_counts = _integer_counts(expected_raw, declaration_key)
        if expected_counts != actual_counts:
            raise DashboardError(f"{path}: {declaration_key} mismatch")
    return {
        "available": True,
        "status": "COMPLETE",
        "source": str(path),
        "source_sha256": source_sha256,
        "schema": document.get("schema"),
        "trace_schema": document.get("trace_schema"),
        "hero_hashes": sorted(set(hero_hashes)),
        "mixed_hero_hashes_allowed": bool(
            document.get("mixed_hero_hashes_allowed", False)
        ),
        "eligible_traced_games": eligible_games,
        "rows_seen": rows_seen,
        "row_sources": row_sources,
        "aggregate_only_sources": aggregate_only_sources,
        "aggregate_context": {
            "source_count": aggregate_only_sources,
            "note": aggregate_context.get("note"),
            "merged_as_per_game": False,
        },
        "excluded_rows": excluded_rows,
        "quality_counters": quality_counters,
        "results": overall_results,
        "bucket_results": bucket_results,
        "opportunity_ranking": {
            "method": dict(method),
            "reference_mechanism_rates": ranking.get("reference_mechanism_rates"),
            "buckets": ranking_rows,
        },
    }


def _mechanics_dashboard(base: Path, raw: Any) -> dict[str, Any]:
    if raw is None:
        return {"status": "NOT_RECORDED", "passed": 0, "failed": 0}
    if not isinstance(raw, Mapping):
        raise DashboardError("mechanics must be an object")
    result = dict(raw)
    suite_raw = raw.get("suite")
    if suite_raw not in (None, ""):
        suite_path = _resolve(base, suite_raw)
        result["suite"] = str(suite_path)
        result["suite_sha256"] = _verify_file_sha256(
            suite_path,
            raw.get("suite_sha256"),
            "mechanics.suite_sha256",
        )
    return result


def _replay_manifest_provenance(base: Path, raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise DashboardError("replay_manifests must be an object")
    result: dict[str, Any] = {}
    for label, declaration_raw in raw.items():
        if not isinstance(declaration_raw, Mapping):
            raise DashboardError(f"replay_manifests.{label} must be an object")
        declaration = declaration_raw
        path = _resolve(base, declaration.get("path"))
        document = _load(path)
        source_sha256 = _verify_file_sha256(
            path, declaration.get("artifact_sha256")
        )
        payload_digest = document.get("manifest_payload_sha256")
        unsigned = {
            key: value
            for key, value in document.items()
            if key != "manifest_payload_sha256"
        }
        actual_payload_digest = sha256_object(unsigned)
        if not isinstance(payload_digest, str) or payload_digest != actual_payload_digest:
            raise DashboardError(f"{path}: frozen manifest payload digest mismatch")
        episodes_raw = document.get("episodes")
        if not isinstance(episodes_raw, list):
            raise DashboardError(f"{path}: frozen manifest episodes must be an array")
        episode_count = _required_integer(
            document.get("episode_count"), f"{path} episode_count"
        )
        if episode_count != len(episodes_raw):
            raise DashboardError(f"{path}: frozen manifest episode_count mismatch")
        expected_fields = {
            "expected_split": document.get("split"),
            "expected_episode_count": episode_count,
            "expected_sealed": document.get("sealed"),
            "expected_payload_sha256": payload_digest,
        }
        for field, actual in expected_fields.items():
            if field not in declaration:
                continue
            expected = declaration[field]
            if field == "expected_payload_sha256":
                expected = _declared_sha256(expected, field)
            if expected != actual:
                raise DashboardError(
                    f"{path}: {field} mismatch: declared {expected!r}, actual {actual!r}"
                )
        order_counts: dict[str, int] = defaultdict(int)
        outcome_counts: dict[str, int] = defaultdict(int)
        verified_selections = 0
        for index, episode in enumerate(episodes_raw):
            if not isinstance(episode, Mapping):
                raise DashboardError(f"{path}: episode {index} must be an object")
            hero = episode.get("hero")
            hero = hero if isinstance(hero, Mapping) else {}
            order = hero.get("actual_order")
            if order not in ORDERS:
                raise DashboardError(f"{path}: episode {index} has invalid actual order")
            order_counts[str(order)] += 1
            outcome = episode.get("expert_result")
            if outcome not in {"win", "loss", "draw"}:
                raise DashboardError(f"{path}: episode {index} has invalid expert result")
            outcome_counts[str(outcome)] += 1
            if episode.get("selection_contract_verified") is True:
                verified_selections += 1
        inspection = document.get("inspection_policy")
        inspection = inspection if isinstance(inspection, Mapping) else {}
        selection = document.get("selection_provenance")
        selection = selection if isinstance(selection, Mapping) else {}
        for field, actual_counts in (
            ("expected_actual_order_counts", dict(order_counts)),
            ("expected_expert_result_counts", dict(outcome_counts)),
        ):
            if field not in declaration:
                continue
            expected_counts = _integer_counts(declaration[field], field)
            if expected_counts != actual_counts:
                raise DashboardError(f"{path}: {field} mismatch")
        if "expected_selection_contract_verified_count" in declaration:
            expected_verified = _required_integer(
                declaration["expected_selection_contract_verified_count"],
                "expected_selection_contract_verified_count",
            )
            if expected_verified != verified_selections:
                raise DashboardError(
                    f"{path}: expected_selection_contract_verified_count mismatch"
                )
        if declaration.get("require_pristine") is True and (
            selection.get("selection_used_outcome") is not False
            or inspection.get("metadata_only") is not True
            or inspection.get("action_level_inspected") is not False
            or inspection.get("replay_regret_executed") is not False
        ):
            raise DashboardError(f"{path}: frozen replay inspection contract is not pristine")
        result[str(label)] = {
            "status": "FROZEN_INPUT",
            "source": str(path),
            "source_sha256": source_sha256,
            "manifest_payload_sha256": payload_digest,
            "split": document.get("split"),
            "sealed": document.get("sealed"),
            "episode_count": episode_count,
            "actual_order_counts": dict(sorted(order_counts.items())),
            "expert_result_counts": dict(sorted(outcome_counts.items())),
            "selection_contract_verified_count": verified_selections,
            "selection_used_outcome": selection.get("selection_used_outcome"),
            "inspection_contract_at_freeze": {
                "metadata_only": inspection.get("metadata_only"),
                "action_level_inspected": inspection.get("action_level_inspected"),
                "replay_regret_executed": inspection.get("replay_regret_executed"),
            },
        }
    return result


def _operational_provenance(base: Path, raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise DashboardError("operational_provenance must be an object")
    result: dict[str, Any] = {}
    for label, declaration_raw in raw.items():
        if not isinstance(declaration_raw, Mapping) or "path" not in declaration_raw:
            result[str(label)] = declaration_raw
            continue
        declaration = declaration_raw
        path = _resolve(base, declaration.get("path"))
        document = _load(path)
        source_sha256 = _verify_file_sha256(
            path, declaration.get("artifact_sha256")
        )
        cell = _normalize_eval(document, path)
        provenance = document.get("artifact_provenance")
        provenance = provenance if isinstance(provenance, Mapping) else {}
        archive_raw = provenance.get("archive_a_sha256")
        archive_sha256 = (
            _declared_sha256(archive_raw, f"{path} archive_a_sha256")
            if archive_raw is not None
            else None
        )
        tree_raw = provenance.get(
            "submission_a_sha256", provenance.get("artifact_a_sha256")
        )
        tree_sha256 = (
            _declared_sha256(tree_raw, f"{path} submission_a_sha256")
            if tree_raw is not None
            else None
        )
        engine_raw = provenance.get("engine_sha256")
        engine_sha256 = (
            _declared_sha256(engine_raw, f"{path} engine_sha256")
            if engine_raw is not None
            else None
        )
        for key, actual in (
            ("archive_sha256", archive_sha256),
            ("evaluated_tree_sha256", tree_sha256),
            ("engine_sha256", engine_sha256),
        ):
            if key not in declaration:
                continue
            expected = _declared_sha256(declaration[key], key)
            if expected != actual:
                raise DashboardError(
                    f"{path}: {key} mismatch: declared {expected}, actual {actual}"
                )
        cells = document.get("cells")
        cells = cells if isinstance(cells, Mapping) else {}
        actual_order = cells.get("actual_order")
        actual_order = actual_order if isinstance(actual_order, Mapping) else {}
        first = actual_order.get("first")
        first = first if isinstance(first, Mapping) else {}
        second = actual_order.get("second")
        second = second if isinstance(second, Mapping) else {}
        games = _integer(cell.get("games"))
        first_games = _integer(first.get("games"))
        second_games = _integer(second.get("games"))
        failed_games = _integer(cell.get("failed_games"))
        policy_errors = _integer(cell.get("hero_policy_errors")) + _integer(
            cell.get("opponent_policy_errors")
        )
        illegal_actions = _integer(cell.get("hero_illegal_actions")) + _integer(
            cell.get("opponent_illegal_actions")
        )
        unchanged = provenance.get(
            "submission_artifacts_unchanged_during_evaluation"
        )
        actual_declarations = {
            "games": games,
            "actual_first_games": first_games,
            "actual_second_games": second_games,
            "completed_games": games - failed_games,
            "policy_errors": policy_errors,
            "illegal_actions": illegal_actions,
            "artifact_mutations": 0 if unchanged is True else 1,
        }
        for key, actual in actual_declarations.items():
            if key not in declaration:
                continue
            expected = _required_integer(declaration[key], key)
            if expected != actual:
                raise DashboardError(
                    f"{path}: {key} mismatch: declared {expected}, actual {actual}"
                )
        derived_status = (
            "PASS"
            if games > 0
            and failed_games == 0
            and policy_errors == 0
            and illegal_actions == 0
            and unchanged is True
            else "FAIL"
        )
        if declaration.get("status") not in (None, derived_status):
            raise DashboardError(
                f"{path}: operational status mismatch: declared "
                f"{declaration.get('status')}, actual {derived_status}"
            )
        result[str(label)] = {
            "status": derived_status,
            "source": str(path),
            "source_sha256": source_sha256,
            "schema": document.get("schema"),
            "platform": provenance.get("platform"),
            "machine": provenance.get("machine"),
            "engine_binary": provenance.get("engine_binary"),
            "engine_sha256": engine_sha256,
            "archive_sha256": archive_sha256,
            "evaluated_tree_sha256": tree_sha256,
            "games": games,
            "actual_order_games": {"first": first_games, "second": second_games},
            "completed_games": games - failed_games,
            "failed_games": failed_games,
            "policy_errors": policy_errors,
            "illegal_actions": illegal_actions,
            "artifacts_unchanged": unchanged,
        }
    return result


def _operational(cells: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    selected = list(cells)
    latency = [cell.get("latency_ms") for cell in selected]
    latency = [item for item in latency if isinstance(item, Mapping)]
    counts = [
        float(item["count"])
        for item in latency
        if _number(item.get("count")) is not None and float(item["count"]) > 0
    ]
    weighted_mean_numerator = sum(
        float(item["mean"]) * float(item["count"])
        for item in latency
        if _number(item.get("mean")) is not None
        and _number(item.get("count")) is not None
    )
    return {
        "failed_games": sum(_integer(cell.get("failed_games")) for cell in selected),
        "policy_errors": sum(_integer(cell.get("hero_policy_errors")) for cell in selected),
        "illegal_actions": sum(_integer(cell.get("hero_illegal_actions")) for cell in selected),
        "unknown_contexts": sum(float(cell.get("unknown_contexts") or 0.0) for cell in selected),
        "latency_ms": {
            "count": int(sum(counts)),
            "mean": weighted_mean_numerator / sum(counts) if counts else None,
            # Without raw samples, extrema of shard quantiles are a transparent
            # conservative summary rather than a fabricated pooled quantile.
            "p95_max_across_inputs": max(
                (float(item["p95"]) for item in latency if _number(item.get("p95")) is not None),
                default=None,
            ),
            "p99_max_across_inputs": max(
                (float(item["p99"]) for item in latency if _number(item.get("p99")) is not None),
                default=None,
            ),
            "max": max(
                (float(item["max"]) for item in latency if _number(item.get("max")) is not None),
                default=None,
            ),
            "quantile_note": "max of input p95/p99 summaries; not a pooled quantile",
        },
    }


def build_dashboard(spec_path: Path) -> dict[str, Any]:
    spec_path = spec_path.resolve()
    spec = _load(spec_path)
    base = spec_path.parent
    candidate = spec.get("candidate")
    if not isinstance(candidate, Mapping):
        raise DashboardError("spec requires candidate object")
    candidate_dashboard = _candidate_dashboard(base, candidate)
    anchors, anchor_cells = _anchor_dashboard(base, spec.get("strong_anchors"))
    same_deck, mirror_cells = _same_deck(base, spec.get("same_deck"))
    mechanics = _mechanics_dashboard(base, spec.get("mechanics"))
    provenance = _optional_mapping(spec.get("provenance"), "provenance")
    same_deck_provenance = _optional_mapping(
        spec.get("same_deck_provenance"), "same_deck_provenance"
    )
    weak_clones = spec.get("weak_clones")
    weak_clones = weak_clones if isinstance(weak_clones, list) else []
    clone_rows = []
    for row in weak_clones:
        if not isinstance(row, Mapping):
            raise DashboardError("weak clone entries must be objects")
        clone_rows.append(
            {
                **dict(row),
                "strength_status": "CEILINGED — EXCLUDED FROM STRENGTH",
                "win_rate_is_strength_metric": False,
            }
        )
    return {
        "schema": SCHEMA,
        "spec_path": str(spec_path),
        "spec_sha256": sha256_file(spec_path),
        "candidate": candidate_dashboard,
        "provenance": dict(provenance),
        "strong_anchors": anchors,
        "same_deck": same_deck,
        "same_deck_provenance": dict(same_deck_provenance),
        "replay_validation": _replay_summary(
            base, spec.get("replay_validation"), "VALIDATION"
        ),
        "sealed_replay_holdout": _replay_summary(
            base, spec.get("sealed_replay_holdout"), "FINAL_HOLDOUT"
        ),
        "replay_manifests": _replay_manifest_provenance(
            base, spec.get("replay_manifests")
        ),
        "second_bucket_analysis": _second_bucket_analysis(
            base, spec.get("second_bucket_analysis")
        ),
        "mechanics": mechanics,
        "weak_clones": clone_rows,
        "operational_provenance": _operational_provenance(
            base, spec.get("operational_provenance")
        ),
        "operational": _operational([*anchor_cells, *mirror_cells]),
        "score_contract": {
            "single_magic_score": False,
            "anchor_macro": anchors["anchor_macro"],
            "anchor_sample_weighted": anchors["anchor_sample_weighted"],
            "anchor_actual_first": anchors["anchor_actual_first"],
            "anchor_actual_second": anchors["anchor_actual_second"],
            "robust_anchor": anchors["robust_anchor"],
        },
    }


def _percent(value: Any) -> str:
    number = _number(value)
    return "n/a" if number is None else f"{100.0 * number:.2f}%"


def render_markdown(dashboard: Mapping[str, Any]) -> str:
    candidate = dashboard["candidate"]
    anchors = dashboard["strong_anchors"]
    lines = [
        "# Dipplin general-strength dashboard",
        "",
        f"Candidate: {candidate.get('name')}  ",
        f"Source: `{candidate.get('source_sha')}`  ",
        f"Package SHA-256: `{candidate.get('package_sha256')}`  ",
        f"Verified tree SHA-256: `{candidate.get('verified_tree_sha256')}`",
        "",
        "## Strong anchors",
        "",
        "| Opponent | First | Second | Overall |",
        "|---|---:|---:|---:|",
    ]
    for name, cell in anchors["opponents"].items():
        lines.append(
            f"| {name} | {_percent(cell['actual_order']['first']['win_rate'])} | "
            f"{_percent(cell['actual_order']['second']['win_rate'])} | "
            f"{_percent(cell['overall']['order_balanced_win_rate'])} |"
        )
    lines.extend(
        [
            "",
            f"Anchor macro: {_percent(anchors['anchor_macro'])}; "
            f"first: {_percent(anchors['anchor_actual_first'])}; "
            f"second: {_percent(anchors['anchor_actual_second'])}; "
            f"robust min: {_percent(anchors['robust_anchor'])}.",
            "",
            "## Same-deck and replay evidence",
            "",
        ]
    )
    for label, cell in dashboard["same_deck"].items():
        lines.append(
            f"- {label}: " + ("not run" if cell is None else _percent(cell["win_rate"]))
        )
    for key in ("replay_validation", "sealed_replay_holdout"):
        replay = dashboard[key]
        lines.append(
            f"- {key}: {replay.get('episodes', 0)} episodes; "
            f"expert dominates {_percent((replay.get('rates') or {}).get('EXPERT_DOMINATES'))}; "
            f"agent dominates {_percent((replay.get('rates') or {}).get('AGENT_DOMINATES'))}."
        )
    for label, manifest in dashboard.get("replay_manifests", {}).items():
        lines.append(
            f"- frozen {label} manifest: {manifest.get('episode_count')} episodes; "
            f"input status {manifest.get('status')}."
        )
    bucket = dashboard.get("second_bucket_analysis")
    bucket = bucket if isinstance(bucket, Mapping) else {}
    lines.extend(["", "## Actual-second traced buckets", ""])
    if not bucket.get("available"):
        lines.append("Not run.")
    else:
        results = bucket.get("results")
        results = results if isinstance(results, Mapping) else {}
        ranking = bucket.get("opportunity_ranking")
        ranking = ranking if isinstance(ranking, Mapping) else {}
        ranking_rows = ranking.get("buckets")
        ranking_rows = ranking_rows if isinstance(ranking_rows, list) else []
        leader = ranking_rows[0].get("bucket") if ranking_rows else "n/a"
        lines.extend(
            [
                f"Eligible traced games: {bucket.get('eligible_traced_games')}; "
                f"wins: {results.get('wins')}; win rate: "
                f"{_percent(results.get('win_rate'))}.",
                f"Top outcome-independent opportunity bucket: {leader}. "
                f"Aggregate-only context sources: {bucket.get('aggregate_only_sources')}; "
                "not merged as per-game evidence.",
            ]
        )
    operational = dashboard["operational"]
    latency = operational["latency_ms"]
    lines.extend(
        [
            "",
            "## Safety and operations",
            "",
            f"Failures: {operational['failed_games']}; policy errors: "
            f"{operational['policy_errors']}; illegal actions: "
            f"{operational['illegal_actions']}; unknown contexts: "
            f"{operational['unknown_contexts']:.0f}.",
            f"Latency mean: {latency['mean'] if latency['mean'] is not None else 'n/a'} ms; "
            f"p95 ceiling: {latency['p95_max_across_inputs'] if latency['p95_max_across_inputs'] is not None else 'n/a'} ms; "
            f"p99 ceiling: {latency['p99_max_across_inputs'] if latency['p99_max_across_inputs'] is not None else 'n/a'} ms; "
            f"max: {latency['max'] if latency['max'] is not None else 'n/a'} ms.",
            f"Mechanics: {dashboard.get('mechanics', {}).get('status', 'NOT_RECORDED')} "
            f"({dashboard.get('mechanics', {}).get('passed', 0)} passed, "
            f"{dashboard.get('mechanics', {}).get('failed', 0)} failed).",
            "",
            "## Frozen provenance",
            "",
        ]
    )
    historical = dashboard.get("provenance", {}).get("historical_anchor_identity")
    if isinstance(historical, Mapping):
        lines.append(
            f"Historical anchor identity: {historical.get('status')}. "
            f"{historical.get('note', '')}"
        )
    operational_provenance = dashboard.get("operational_provenance")
    if isinstance(operational_provenance, Mapping):
        for label, certification in operational_provenance.items():
            if not isinstance(certification, Mapping):
                continue
            lines.append(
                f"- {label}: {certification.get('status')}; "
                f"{certification.get('completed_games')} complete games; "
                f"tree `{certification.get('evaluated_tree_sha256')}`."
            )
    lines.extend(
        [
            "",
            "No composite magic score is computed. Weak-clone win rates are "
            "ceilinged and excluded from strength evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--markdown-output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        dashboard = build_dashboard(args.spec)
    except DashboardError as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(dashboard, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(dashboard), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                **dashboard["score_contract"],
                "illegal_actions": dashboard["operational"]["illegal_actions"],
                "policy_errors": dashboard["operational"]["policy_errors"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
