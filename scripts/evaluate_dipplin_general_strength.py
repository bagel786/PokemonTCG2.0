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
import tempfile
from collections import defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping, Sequence
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "dipplin-general-strength-dashboard-v1"
SCHEMA_V2 = "dipplin-general-strength-dashboard-v2"
REPLAY_V2_SCHEMA = "dipplin-replay-regret-v2"
QUALIFICATION_SCHEMA = "dipplin-s2-holdout-qualification-v1"
SEALED_RECEIPT_SCHEMA = "dipplin-final-holdout-receipt-v2"
PINNED_S1_DASHBOARD_SPEC_SHA256 = (
    "bd8142f9b60077d82059c57e9e08a223b0d84701010c9c539537c7b7d58fed1e"
)
ORDERS = ("first", "second")
REPLAY_LABELS = (
    "EQUIVALENT",
    "AGENT_DOMINATES",
    "EXPERT_DOMINATES",
    "INCOMPARABLE",
    "UNCERTIFIABLE",
)
REPLAY_QUALITY_KEYS = (
    "proposal_error_rows",
    "candidate_policy_error_rows",
    "candidate_action_unstable_rows",
    "uncertifiable_rows",
    "incomparable_rows",
)
SEALED_FORBIDDEN_KEYS = {
    "decision_rows",
    "evaluation_sets",
    "by_actual_order",
    "by_opponent_archetype",
    "by_decision_family",
    "by_hero_deck_family",
    "by_game_phase",
    "opponent_archetypes",
    "opponent_archetype_episode_counts",
    "opponent_archetype_decision_counts",
    "per_episode",
    "episode_details",
    "decision_details",
}
SEALED_REPLAY_TOP_LEVEL_KEYS = {
    "schema",
    "sealed",
    "split",
    "manifest_payload_sha256",
    "method",
    "candidate_variant",
    "baseline_incumbent_s1",
    "evaluated_candidate",
    "aggregate",
}
SEALED_REPLAY_AGGREGATE_KEYS = {
    "episode_count",
    "decision_count",
    "classification_counts",
    "decision_rates",
    "episode_rates",
    "episode_bootstrap_95",
    "expert_dominates_rate",
    "agent_dominates_rate",
    "quality_counts",
    "manifest_episode_count",
    "evaluated_episode_count",
    "episode_coverage",
}
V2_ALLOWED_SPEC_KEYS = {
    "dashboard_schema",
    "candidate",
    "provenance",
        "strength_source",
        "rejected_s2_candidate",
    "replay_validation",
    "sealed_replay_holdout",
    "replay_manifests",
    "qualification",
    "sealed_holdout_receipt",
    "second_bucket_analysis",
    "mechanics",
    "weak_clones",
    "operational_provenance",
    "final_verdict",
}
FINAL_VERDICTS = {
    "KEEP_S1",
    "PROMOTE_S2",
    "PROMOTE_S2_NEEDS_LIVE_TEST",
    "S1_NEAR_ARCHITECTURE_CEILING",
    "REJECT_DIPPLIN",
}
WEAK_CLONE_NAMES = {
    "Mega Lucario",
    "Crustle / Kangaskhan",
    "Teal Mask Ogerpon",
    "Bellibolt",
    "Starmie / Froslass",
    "Dragapult",
    "Mega Lopunny",
}


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


def _git_blob_sha1(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(
        b"blob " + str(len(data)).encode("ascii") + b"\0" + data
    ).hexdigest()


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


def _required_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DashboardError(f"{field} must be an object")
    return value


def _required_sequence(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise DashboardError(f"{field} must be an array")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    actual = set(map(str, value))
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise DashboardError(
            f"{field} keys mismatch (missing={missing}, extra={extra})"
        )


def _git_sha(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise DashboardError(f"{field} must be a Git SHA")
    normalized = value.strip().lower()
    if len(normalized) != 40 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise DashboardError(f"{field} must be a 40-character hexadecimal Git SHA")
    return normalized


def _contains_forbidden_key(value: Any, forbidden: set[str]) -> str | None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key) in forbidden:
                return str(key)
            found = _contains_forbidden_key(nested, forbidden)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _contains_forbidden_key(nested, forbidden)
            if found is not None:
                return found
    return None


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
        normalized.append(cell)
    return _anchors_from_normalized(normalized), normalized


def _anchors_from_normalized(
    normalized: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not normalized:
        raise DashboardError("strong anchor evidence is empty")
    by_opponent: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for raw_cell in normalized:
        cell = dict(raw_cell)
        opponent = str(cell.get("opponent") or "").strip()
        order = str(cell.get("actual_order") or "").strip()
        if not opponent or order not in ORDERS:
            raise DashboardError("normalized anchors require opponent and order")
        by_opponent[opponent][order].append(cell)
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
    return {
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
    }


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
    base: Path, candidate: Mapping[str, Any], *, strict: bool = False
) -> dict[str, Any]:
    source_sha_raw = candidate.get("source_sha")
    source_sha = (
        _git_sha(source_sha_raw, "candidate.source_sha")
        if strict
        else source_sha_raw
    )
    if strict:
        required = {
            "name",
            "variant",
            "source_sha",
            "tree_sha256",
            "runtime_tree_sha256",
            "package",
            "package_sha256",
            "manifest",
            "manifest_sha256",
        }
        _exact_keys(candidate, required, "candidate")
        if not str(candidate.get("name") or "").strip():
            raise DashboardError("candidate.name must be a non-empty string")
        if candidate.get("variant") not in {"s1", "s2"}:
            raise DashboardError("candidate.variant must be s1 or s2")
        _declared_sha256(
            candidate.get("package_sha256"), "candidate.package_sha256"
        )
        _declared_sha256(
            candidate.get("manifest_sha256"), "candidate.manifest_sha256"
        )
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
    if strict and declared_tree is None:
        raise DashboardError("candidate.tree_sha256 is required")
    manifest_path: Path | None = None
    manifest_sha256: str | None = None
    manifest_tree: str | None = None
    manifest_runtime_tree: str | None = None
    manifest_variant: str | None = None
    manifest_raw = candidate.get("manifest")
    if manifest_raw not in (None, ""):
        manifest_path = _resolve(base, manifest_raw)
        manifest_sha256 = _verify_file_sha256(
            manifest_path,
            candidate.get("manifest_sha256"),
            "candidate.manifest_sha256",
        )
        manifest = _load(manifest_path)
        manifest_variant_raw = manifest.get("variant")
        manifest_variant = (
            str(manifest_variant_raw) if manifest_variant_raw is not None else None
        )
        declared_variant = candidate.get("variant")
        if declared_variant is not None and manifest_variant != declared_variant:
            raise DashboardError(
                f"{manifest_path}: variant does not match candidate.variant"
            )
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
        runtime = manifest.get("runtime")
        runtime = runtime if isinstance(runtime, Mapping) else {}
        runtime_tree_raw = runtime.get("runtime_source_tree_sha256")
        if runtime_tree_raw is not None:
            manifest_runtime_tree = _declared_sha256(
                runtime_tree_raw, "candidate manifest runtime_source_tree_sha256"
            )
        if strict:
            try:
                from scripts.package_dipplin import (
                    PackageError,
                    package_file_manifest,
                    package_tree_sha256,
                    runtime_source_tree_sha256,
                    safe_extract,
                )

                with tempfile.TemporaryDirectory(
                    prefix="dipplin-dashboard-package-"
                ) as directory:
                    extracted = Path(directory) / "extracted"
                    safe_extract(package_path, extracted)
                    archive_tree = package_tree_sha256(extracted).lower()
                    archive_runtime_tree, _ = runtime_source_tree_sha256(extracted)
                    archive_runtime_tree = archive_runtime_tree.lower()
                    manifest_files = output.get("file_manifest")
                    if not isinstance(manifest_files, Mapping):
                        raise DashboardError(
                            "candidate manifest does not declare output.file_manifest"
                        )
                    actual_files = package_file_manifest(extracted)
                    normalized_manifest_files = {
                        str(name): {
                            "bytes": _required_integer(
                                _required_mapping(
                                    details,
                                    f"candidate manifest file_manifest.{name}",
                                ).get("bytes"),
                                f"candidate manifest file_manifest.{name}.bytes",
                            ),
                            "sha256": _declared_sha256(
                                details.get("sha256"),
                                f"candidate manifest file_manifest.{name}.sha256",
                            ),
                        }
                        for name, details in manifest_files.items()
                    }
                    normalized_actual_files = {
                        name: {
                            "bytes": int(details["bytes"]),
                            "sha256": str(details["sha256"]).lower(),
                        }
                        for name, details in actual_files.items()
                    }
                    if normalized_manifest_files != normalized_actual_files:
                        raise DashboardError(
                            "candidate archive files differ from its manifest"
                        )
            except (OSError, PackageError) as error:
                raise DashboardError(
                    f"cannot verify candidate archive contents: {error}"
                ) from error
            if manifest_tree is not None and archive_tree != manifest_tree:
                raise DashboardError(
                    "candidate archive extracted tree differs from manifest"
                )
            if (
                manifest_runtime_tree is not None
                and archive_runtime_tree != manifest_runtime_tree
            ):
                raise DashboardError(
                    "candidate archive runtime tree differs from manifest"
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
    declared_runtime_raw = candidate.get("runtime_tree_sha256")
    declared_runtime_tree = (
        _declared_sha256(
            declared_runtime_raw, "candidate.runtime_tree_sha256"
        )
        if declared_runtime_raw is not None
        else None
    )
    if strict and declared_runtime_tree is None:
        raise DashboardError("candidate.runtime_tree_sha256 is required")
    if declared_runtime_tree is not None:
        if manifest_runtime_tree is None:
            raise DashboardError(
                "candidate manifest does not declare a runtime source tree hash"
            )
        if manifest_runtime_tree != declared_runtime_tree:
            raise DashboardError(
                "candidate.runtime_tree_sha256 mismatch: "
                f"declared {declared_runtime_tree}, manifest {manifest_runtime_tree}"
            )
    return {
        "name": candidate.get("name"),
        "variant": candidate.get("variant", manifest_variant),
        "source_sha": source_sha,
        "tree_sha256": declared_tree,
        "verified_tree_sha256": manifest_tree,
        "runtime_tree_sha256": declared_runtime_tree,
        "verified_runtime_tree_sha256": manifest_runtime_tree,
        "package": str(package_path),
        "package_sha256": package_sha256,
        "manifest": str(manifest_path) if manifest_path is not None else None,
        "manifest_sha256": manifest_sha256,
    }


def _stage_cell_to_eval(
    base: Path,
    raw: Any,
    *,
    expected_order: str,
    expected_tree: str,
    field: str,
) -> dict[str, Any]:
    cell = _required_mapping(raw, field)
    if cell.get("actual_order") != expected_order:
        raise DashboardError(f"{field}.actual_order mismatch")
    matchup = str(cell.get("matchup") or "").strip()
    if not matchup:
        raise DashboardError(f"{field}.matchup is required")
    source = _required_mapping(cell.get("source"), f"{field}.source")
    path = _resolve(base, source.get("path"))
    source_sha256 = _verify_file_sha256(
        path, source.get("artifact_sha256"), f"{field}.source.artifact_sha256"
    )
    source_tree = _declared_sha256(
        source.get("tree_sha256"), f"{field}.source.tree_sha256"
    )
    if source_tree != expected_tree:
        raise DashboardError(f"{field} evaluated tree does not match its arm")
    normalized = _normalize_eval(_load(path), path)
    normalized_tree_raw = normalized.get("evaluated_tree_sha256")
    if normalized_tree_raw is None or _declared_sha256(
        normalized_tree_raw, f"{field}.evaluated_tree_sha256"
    ) != expected_tree:
        raise DashboardError(f"{field} source result tree mismatch")
    comparisons = {
        "games": "games",
        "wins": "wins",
        "draws": "draws",
        "failed_games": "failed_games",
        "hero_policy_errors": "hero_policy_errors",
        "opponent_policy_errors": "opponent_policy_errors",
        "hero_illegal_actions": "hero_illegal_actions",
        "opponent_illegal_actions": "opponent_illegal_actions",
    }
    for report_key, normalized_key in comparisons.items():
        expected = _required_integer(cell.get(report_key), f"{field}.{report_key}")
        actual = _required_integer(
            normalized.get(normalized_key), f"{field}.source.{normalized_key}"
        )
        if actual != expected:
            raise DashboardError(
                f"{field}.{report_key} disagrees with its source result"
            )
    if normalized.get("actual_order") != expected_order:
        raise DashboardError(f"{field} source result order mismatch")
    if source_sha256 != normalized["source_sha256"]:
        raise DashboardError(f"{field} source hash changed while reading")
    normalized.update(
        {
            "id": cell.get("id"),
            "opponent": matchup,
            "opponent_name": cell.get("opponent_name"),
            "actual_order": expected_order,
            "stage_source": dict(source),
            "operational_telemetry": cell.get("operational_telemetry", {}),
            "s2_proof": cell.get("s2_proof", {}),
        }
    )
    return normalized


def _identity_pins(identity: Mapping[str, Any], field: str) -> dict[str, str]:
    package_manifest = _required_mapping(
        identity.get("package_manifest"), f"{field}.package_manifest"
    )
    return {
        "archive_sha256": _declared_sha256(
            identity.get("archive_sha256"), f"{field}.archive_sha256"
        ),
        "tree_sha256": _declared_sha256(
            identity.get("tree_sha256"), f"{field}.tree_sha256"
        ),
        "manifest_sha256": _declared_sha256(
            package_manifest.get("sha256"), f"{field}.package_manifest.sha256"
        ),
    }


def _verify_rejected_s2_candidate(
    base: Path,
    raw: Any,
    *,
    stage_candidate: Mapping[str, Any],
) -> dict[str, Any]:
    declaration = _required_mapping(raw, "rejected_s2_candidate")
    _exact_keys(
        declaration,
        {
            "source_sha",
            "package",
            "package_sha256",
            "manifest",
            "manifest_sha256",
            "tree_sha256",
            "runtime_tree_sha256",
        },
        "rejected_s2_candidate",
    )
    source_sha = _git_sha(
        declaration.get("source_sha"), "rejected_s2_candidate.source_sha"
    )
    package_path = _resolve(base, declaration.get("package"))
    archive_sha256 = _verify_file_sha256(
        package_path,
        declaration.get("package_sha256"),
        "rejected_s2_candidate.package_sha256",
    )
    manifest_path = _resolve(base, declaration.get("manifest"))
    manifest_sha256 = _verify_file_sha256(
        manifest_path,
        declaration.get("manifest_sha256"),
        "rejected_s2_candidate.manifest_sha256",
    )
    manifest = _load(manifest_path)
    if manifest.get("variant") != "s2":
        raise DashboardError("rejected S2 manifest variant mismatch")
    output = _required_mapping(
        manifest.get("output"), "rejected S2 manifest.output"
    )
    runtime = _required_mapping(
        manifest.get("runtime"), "rejected S2 manifest.runtime"
    )
    tree_sha256 = _declared_sha256(
        declaration.get("tree_sha256"), "rejected_s2_candidate.tree_sha256"
    )
    runtime_tree_sha256 = _declared_sha256(
        declaration.get("runtime_tree_sha256"),
        "rejected_s2_candidate.runtime_tree_sha256",
    )
    if (
        _declared_sha256(
            output.get("archive_sha256"), "rejected S2 manifest archive_sha256"
        )
        != archive_sha256
        or _declared_sha256(
            output.get("extracted_tree_sha256"),
            "rejected S2 manifest extracted_tree_sha256",
        )
        != tree_sha256
        or _declared_sha256(
            runtime.get("runtime_source_tree_sha256"),
            "rejected S2 manifest runtime_source_tree_sha256",
        )
        != runtime_tree_sha256
    ):
        raise DashboardError("rejected S2 package/manifest identity mismatch")
    try:
        from scripts.evaluate_dipplin_replay_regret import (
            PINNED_S2_ARCHIVE_SHA256,
            PINNED_S2_EXTRACTED_TREE_SHA256,
            PINNED_S2_MANIFEST_SHA256,
            PINNED_S2_RUNTIME_TREE_SHA256,
        )
    except ImportError as error:
        raise DashboardError(f"cannot import frozen S2 pins: {error}") from error
    if {
        "archive_sha256": archive_sha256,
        "tree_sha256": tree_sha256,
        "manifest_sha256": manifest_sha256,
        "runtime_tree_sha256": runtime_tree_sha256,
    } != {
        "archive_sha256": PINNED_S2_ARCHIVE_SHA256.lower(),
        "tree_sha256": PINNED_S2_EXTRACTED_TREE_SHA256.lower(),
        "manifest_sha256": PINNED_S2_MANIFEST_SHA256.lower(),
        "runtime_tree_sha256": PINNED_S2_RUNTIME_TREE_SHA256.lower(),
    }:
        raise DashboardError("rejected S2 is not the frozen candidate package")
    expected = _identity_pins(stage_candidate, "stage_report.candidate")
    if expected != {
        "archive_sha256": archive_sha256,
        "tree_sha256": tree_sha256,
        "manifest_sha256": manifest_sha256,
    }:
        raise DashboardError("rejected S2 does not match staged candidate")
    return {
        "status": "REJECTED_STAGE2_KILL",
        "source_sha": source_sha,
        "package": str(package_path),
        "package_sha256": archive_sha256,
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_sha256,
        "tree_sha256": tree_sha256,
        "runtime_tree_sha256": runtime_tree_sha256,
    }


def _stage_comparison_view(stage: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: stage.get(key)
        for key in (
            "status",
            "pooled",
            "macro",
            "per_matchup",
            "per_order",
            "decision",
            "statistical_contract",
            "candidate_s2_proof",
            "candidate_latency_ms",
        )
        if key in stage
    }


def _strength_source_dashboard(
    base: Path,
    raw: Any,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    declaration = _required_mapping(raw, "strength_source")
    expected_keys = {
        "stage_spec",
        "stage_spec_sha256",
        "stage_report",
        "stage_report_sha256",
        "anchor_stage_by_order",
        "same_deck_stage",
        "required_verdicts",
    }
    _exact_keys(declaration, expected_keys, "strength_source")
    spec_path = _resolve(base, declaration.get("stage_spec"))
    report_path = _resolve(base, declaration.get("stage_report"))
    spec_sha256 = _verify_file_sha256(
        spec_path,
        declaration.get("stage_spec_sha256"),
        "strength_source.stage_spec_sha256",
    )
    report_sha256 = _verify_file_sha256(
        report_path,
        declaration.get("stage_report_sha256"),
        "strength_source.stage_report_sha256",
    )
    stage_spec = _load(spec_path)
    stage_provenance = _required_mapping(
        stage_spec.get("provenance"), "stage_spec.provenance"
    )
    if _git_sha(
        stage_provenance.get("source_head"), "stage_spec.provenance.source_head"
    ) != candidate.get("source_sha"):
        raise DashboardError("stage spec source_head does not match candidate.source_sha")
    report = _load(report_path)
    if report.get("schema") != "dipplin-s2-stage-evaluation-v1":
        raise DashboardError("strength_source stage report schema mismatch")
    try:
        from scripts.evaluate_dipplin_s2_stages import (
            StageEvaluationError,
            evaluate_spec,
        )

        regenerated = evaluate_spec(spec_path)
    except (OSError, StageEvaluationError) as error:
        raise DashboardError(f"cannot recompute staged evaluation: {error}") from error
    if regenerated != report:
        raise DashboardError(
            "stored staged evaluation differs from exact evaluator recomputation"
        )
    report_spec = _required_mapping(report.get("spec"), "stage_report.spec")
    if (
        Path(str(report_spec.get("path"))).resolve() != spec_path
        or str(report_spec.get("sha256") or "").lower() != spec_sha256
    ):
        raise DashboardError("stage report does not bind the declared stage spec")

    candidate_identity = _required_mapping(
        report.get("candidate"), "stage_report.candidate"
    )
    expected_candidate = {
        "tree_sha256": candidate.get("verified_tree_sha256"),
        "archive_sha256": candidate.get("package_sha256"),
    }
    for key, expected in expected_candidate.items():
        actual = _declared_sha256(
            candidate_identity.get(key), f"stage_report.candidate.{key}"
        )
        if actual != expected:
            raise DashboardError(f"stage report candidate {key} mismatch")
    package_manifest = _required_mapping(
        candidate_identity.get("package_manifest"),
        "stage_report.candidate.package_manifest",
    )
    if _declared_sha256(
        package_manifest.get("sha256"),
        "stage_report.candidate.package_manifest.sha256",
    ) != candidate.get("manifest_sha256"):
        raise DashboardError("stage report candidate manifest mismatch")

    stages = _required_mapping(report.get("stages"), "stage_report.stages")
    required_verdicts = _required_mapping(
        declaration.get("required_verdicts"),
        "strength_source.required_verdicts",
    )
    if set(required_verdicts) != {f"stage{index}" for index in range(1, 6)}:
        raise DashboardError("strength_source must freeze verdicts for Stage1-5")
    for name in sorted(required_verdicts):
        stage = _required_mapping(stages.get(name), f"stage_report.stages.{name}")
        if stage.get("status") != "EVALUATED":
            raise DashboardError(f"{name} is not evaluated")
        decision = _required_mapping(stage.get("decision"), f"{name}.decision")
        allowed = _required_sequence(
            required_verdicts[name], f"required_verdicts.{name}"
        )
        if not allowed or decision.get("verdict") not in allowed:
            raise DashboardError(f"{name} verdict is not admitted")
        gates = _required_mapping(decision.get("gates"), f"{name}.decision.gates")
        if not gates or any(value is not True for value in gates.values()):
            raise DashboardError(f"{name} has a failed or malformed gate")

    stage_by_order = _required_mapping(
        declaration.get("anchor_stage_by_order"),
        "strength_source.anchor_stage_by_order",
    )
    if dict(stage_by_order) != {"first": "stage3", "second": "stage2"}:
        raise DashboardError(
            "S2 headline anchors must use Stage3 first and Stage2 second"
        )
    baseline_identity = _required_mapping(
        report.get("baseline"), "stage_report.baseline"
    )
    baseline_tree = _declared_sha256(
        baseline_identity.get("tree_sha256"), "stage_report.baseline.tree_sha256"
    )
    candidate_tree = _declared_sha256(
        candidate_identity.get("tree_sha256"), "stage_report.candidate.tree_sha256"
    )
    anchor_cells: list[dict[str, Any]] = []
    baseline_anchor_cells: list[dict[str, Any]] = []
    comparisons: dict[str, Any] = {}
    for order in ORDERS:
        stage_name = str(stage_by_order[order])
        stage = _required_mapping(stages.get(stage_name), f"stages.{stage_name}")
        candidate_cells = _required_sequence(
            stage.get("candidate_cells"), f"stages.{stage_name}.candidate_cells"
        )
        baseline_cells = _required_sequence(
            stage.get("baseline_cells"), f"stages.{stage_name}.baseline_cells"
        )
        if not candidate_cells or not baseline_cells:
            raise DashboardError(f"{stage_name} strength cells are empty")
        anchor_cells.extend(
            _stage_cell_to_eval(
                base,
                cell,
                expected_order=order,
                expected_tree=candidate_tree,
                field=f"{stage_name}.candidate[{index}]",
            )
            for index, cell in enumerate(candidate_cells)
        )
        baseline_anchor_cells.extend(
            _stage_cell_to_eval(
                base,
                cell,
                expected_order=order,
                expected_tree=baseline_tree,
                field=f"{stage_name}.baseline[{index}]",
            )
            for index, cell in enumerate(baseline_cells)
        )
        comparisons[f"actual_{order}"] = {
            "stage": stage_name,
            **_stage_comparison_view(stage),
        }

    same_deck_stage = declaration.get("same_deck_stage")
    if same_deck_stage != "stage4":
        raise DashboardError("same_deck_stage must be stage4")
    stage4 = _required_mapping(stages.get("stage4"), "stages.stage4")
    stage4_baseline = _required_sequence(
        stage4.get("baseline_cells"), "stages.stage4.baseline_cells"
    )
    stage4_candidate = _required_sequence(
        stage4.get("candidate_cells"), "stages.stage4.candidate_cells"
    )
    if len(stage4_baseline) != 2 or len(stage4_candidate) != 2:
        raise DashboardError("Stage4 must contain exactly two cells per arm")
    same_deck: dict[str, Any] = {}
    candidate_mirror_cells: list[dict[str, Any]] = []
    for order in ORDERS:
        controls = [cell for cell in stage4_baseline if cell.get("actual_order") == order]
        candidates = [cell for cell in stage4_candidate if cell.get("actual_order") == order]
        if len(controls) != 1 or len(candidates) != 1:
            raise DashboardError(f"Stage4 {order} cell accounting mismatch")
        control = _stage_cell_to_eval(
            base,
            controls[0],
            expected_order=order,
            expected_tree=baseline_tree,
            field=f"stage4.baseline.{order}",
        )
        candidate_cell = _stage_cell_to_eval(
            base,
            candidates[0],
            expected_order=order,
            expected_tree=candidate_tree,
            field=f"stage4.candidate.{order}",
        )
        same_deck[f"s1_vs_s1_{order}"] = control
        same_deck[f"candidate_vs_s1_{order}"] = candidate_cell
        candidate_mirror_cells.append(candidate_cell)

    return {
        "source": {
            "stage_spec": str(spec_path),
            "stage_spec_sha256": spec_sha256,
            "stage_report": str(report_path),
            "stage_report_sha256": report_sha256,
            "exact_recomputation_match": True,
        },
        "anchors": _anchors_from_normalized(anchor_cells),
        "anchor_cells": anchor_cells,
        "baseline_anchor_cells": baseline_anchor_cells,
        "candidate_vs_s1": comparisons,
        "same_deck": same_deck,
        "same_deck_provenance": {
            "baseline": dict(baseline_identity),
            "candidate": dict(candidate_identity),
            "stage4": _stage_comparison_view(stage4),
        },
        "operational_cells": [*anchor_cells, *candidate_mirror_cells],
        "stage_verdicts": {
            name: stages[name]["decision"]["verdict"]
            for name in sorted(required_verdicts)
        },
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


def _s1_replay_validation_summary(
    base: Path,
    raw: Any,
    *,
    candidate: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    declaration = _required_mapping(raw, "replay_validation")
    required = {
        "path",
        "artifact_sha256",
        "expected_schema",
        "expected_split",
        "expected_sealed",
        "expected_episode_count",
        "expected_manifest_file_sha256",
        "expected_manifest_payload_sha256",
    }
    _exact_keys(declaration, required, "replay_validation")
    if (
        declaration.get("expected_schema") != "dipplin-replay-regret-v1"
        or declaration.get("expected_split") != "VALIDATION"
        or declaration.get("expected_sealed") is not False
    ):
        raise DashboardError("S1 replay validation declaration mismatch")
    path = _resolve(base, declaration.get("path"))
    document = _load(path)
    expected_episodes = _required_integer(
        declaration.get("expected_episode_count"),
        "replay_validation.expected_episode_count",
    )
    if (
        document.get("schema") != "dipplin-replay-regret-v1"
        or document.get("split") != "VALIDATION"
        or document.get("sealed") is not False
        or expected_episodes != manifest.get("episode_count")
        or _declared_sha256(
            declaration.get("expected_manifest_file_sha256"),
            "replay_validation.expected_manifest_file_sha256",
        )
        != manifest.get("source_sha256")
        or _declared_sha256(
            declaration.get("expected_manifest_payload_sha256"),
            "replay_validation.expected_manifest_payload_sha256",
        )
        != manifest.get("manifest_payload_sha256")
        or str(document.get("manifest_payload_sha256") or "").lower()
        != manifest.get("manifest_payload_sha256")
    ):
        raise DashboardError("S1 replay validation split/manifest contract mismatch")
    incumbent = _required_mapping(document.get("incumbent"), "S1 replay incumbent")
    if (
        _declared_sha256(
            incumbent.get("archive_sha256"), "S1 replay incumbent archive_sha256"
        )
        != candidate.get("package_sha256")
        or _declared_sha256(
            incumbent.get("manifest_sha256"), "S1 replay incumbent manifest_sha256"
        )
        != candidate.get("manifest_sha256")
    ):
        raise DashboardError("S1 replay validation incumbent package mismatch")
    aggregate = _required_mapping(document.get("aggregate"), "S1 replay aggregate")
    if (
        _required_integer(aggregate.get("episode_count"), "S1 replay episode_count")
        != expected_episodes
        or _required_integer(
            aggregate.get("manifest_episode_count"),
            "S1 replay manifest_episode_count",
        )
        != expected_episodes
        or _required_integer(
            aggregate.get("evaluated_episode_count"),
            "S1 replay evaluated_episode_count",
        )
        != expected_episodes
        or not math.isclose(
            float(aggregate.get("episode_coverage", -1.0)),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ):
        raise DashboardError("S1 replay validation does not cover its full manifest")
    result = _replay_summary(base, declaration, "VALIDATION")
    if not result.get("available") or result.get("episodes") != expected_episodes:
        raise DashboardError("S1 replay validation summary mismatch")
    # The legacy aggregate's opponent_archetypes alias counts decisions. For
    # the dashboard, episode coverage comes only from frozen manifest metadata.
    result["opponent_archetype_coverage"] = manifest.get(
        "opponent_archetype_episode_counts", {}
    )
    result["coverage_source"] = "frozen_metadata_only_manifest"
    return result


def _replay_quality_counts(aggregate: Mapping[str, Any], path: Path) -> dict[str, int]:
    raw = _required_mapping(
        aggregate.get("quality_counts"), f"{path} aggregate.quality_counts"
    )
    _exact_keys(raw, set(REPLAY_QUALITY_KEYS), f"{path} aggregate.quality_counts")
    counts = {
        key: _required_integer(raw.get(key), f"{path} quality_counts.{key}")
        for key in REPLAY_QUALITY_KEYS
    }
    if any(value < 0 for value in counts.values()):
        raise DashboardError(f"{path}: replay quality counts cannot be negative")
    if counts["proposal_error_rows"] != (
        counts["candidate_policy_error_rows"]
        + counts["candidate_action_unstable_rows"]
    ):
        raise DashboardError(f"{path}: replay proposal-error partition mismatch")
    if counts["proposal_error_rows"] > counts["uncertifiable_rows"]:
        raise DashboardError(f"{path}: proposal errors exceed uncertifiable rows")
    classifications = _required_mapping(
        aggregate.get("classification_counts"),
        f"{path} aggregate.classification_counts",
    )
    if (
        counts["uncertifiable_rows"]
        != _required_integer(
            classifications.get("UNCERTIFIABLE"), f"{path} UNCERTIFIABLE"
        )
        or counts["incomparable_rows"]
        != _required_integer(
            classifications.get("INCOMPARABLE"), f"{path} INCOMPARABLE"
        )
    ):
        raise DashboardError(f"{path}: replay quality aliases do not match labels")
    return counts


def _replay_aggregate_v2(
    aggregate: Any,
    *,
    path: Path,
    expected_episodes: int,
    sealed: bool,
    require_full_manifest_coverage: bool = True,
) -> dict[str, Any]:
    value = _required_mapping(aggregate, f"{path} aggregate")
    counts_raw = _required_mapping(
        value.get("classification_counts"), f"{path} classification_counts"
    )
    rates_raw = _required_mapping(value.get("episode_rates"), f"{path} episode_rates")
    intervals_raw = _required_mapping(
        value.get("episode_bootstrap_95"), f"{path} episode_bootstrap_95"
    )
    if (
        set(counts_raw) != set(REPLAY_LABELS)
        or set(rates_raw) != set(REPLAY_LABELS)
        or set(intervals_raw) != set(REPLAY_LABELS)
    ):
        raise DashboardError(f"{path}: replay aggregate must contain all five labels")
    counts = {
        label: _required_integer(counts_raw[label], f"{path} {label} count")
        for label in REPLAY_LABELS
    }
    if any(value < 0 for value in counts.values()):
        raise DashboardError(f"{path}: replay classification count is negative")
    decision_count = _required_integer(
        value.get("decision_count"), f"{path} decision_count"
    )
    if decision_count != sum(counts.values()):
        raise DashboardError(f"{path}: decision_count does not match labels")
    episode_count = _required_integer(
        value.get("episode_count"), f"{path} episode_count"
    )
    if episode_count != expected_episodes:
        raise DashboardError(f"{path}: replay episode_count mismatch")
    if episode_count < 0 or decision_count < 0:
        raise DashboardError(f"{path}: replay counts cannot be negative")
    if require_full_manifest_coverage and episode_count > 0 and decision_count == 0:
        raise DashboardError(f"{path}: full-manifest replay has no decisions")
    if require_full_manifest_coverage:
        manifest_count = _required_integer(
            value.get("manifest_episode_count"), f"{path} manifest_episode_count"
        )
        evaluated_count = _required_integer(
            value.get("evaluated_episode_count"), f"{path} evaluated_episode_count"
        )
        if manifest_count != expected_episodes or evaluated_count != expected_episodes:
            raise DashboardError(f"{path}: replay does not cover its full manifest")
        coverage = _number(value.get("episode_coverage"))
        if coverage is None or not math.isclose(coverage, 1.0, abs_tol=1e-12):
            raise DashboardError(f"{path}: replay episode coverage is not complete")
    else:
        selected_episodes = _required_integer(
            value.get("episodes_with_selected_prompts"),
            f"{path} episodes_with_selected_prompts",
        )
        if selected_episodes != episode_count:
            raise DashboardError(f"{path}: exploratory selected-episode count mismatch")
    rates: dict[str, float] = {}
    intervals: dict[str, list[float]] = {}
    for label in REPLAY_LABELS:
        rate = _number(rates_raw[label])
        if rate is None or not 0.0 <= rate <= 1.0:
            raise DashboardError(f"{path}: invalid episode rate for {label}")
        rates[label] = rate
        interval = intervals_raw.get(label)
        if not isinstance(interval, list) or len(interval) != 2:
            raise DashboardError(f"{path}: invalid bootstrap interval for {label}")
        lower, upper = (_number(interval[0]), _number(interval[1]))
        if (
            lower is None
            or upper is None
            or lower < 0.0
            or upper > 1.0
            or lower > upper
        ):
            raise DashboardError(f"{path}: invalid bootstrap interval for {label}")
        intervals[label] = [lower, upper]
    expected_rate_sum = 1.0 if episode_count else 0.0
    if not math.isclose(
        sum(rates.values()), expected_rate_sum, rel_tol=0.0, abs_tol=1e-12
    ):
        raise DashboardError(f"{path}: replay episode rates do not form a partition")
    quality = _replay_quality_counts(value, path)
    result = {
        "episode_count": episode_count,
        "decision_count": decision_count,
        "classification_counts": counts,
        "episode_rates": rates,
        "episode_bootstrap_95": intervals,
        "quality_counts": quality,
    }
    if not sealed:
        episode_archetypes = _integer_counts(
            value.get("opponent_archetype_episode_counts"),
            f"{path} opponent_archetype_episode_counts",
        )
        decision_archetypes = _integer_counts(
            value.get("opponent_archetype_decision_counts"),
            f"{path} opponent_archetype_decision_counts",
        )
        alias = _integer_counts(
            value.get("opponent_archetypes"), f"{path} opponent_archetypes"
        )
        if (
            value.get("opponent_archetypes_basis") != "unique_episode_id"
            or alias != episode_archetypes
            or sum(episode_archetypes.values()) != episode_count
            or sum(decision_archetypes.values()) != decision_count
        ):
            raise DashboardError(f"{path}: replay archetype coverage mismatch")
        result.update(
            {
                "opponent_archetype_episode_counts": episode_archetypes,
                "opponent_archetype_decision_counts": decision_archetypes,
                "opponent_archetypes_basis": "unique_episode_id",
            }
        )
    return result


def _verify_replay_candidate_pins(
    document: Mapping[str, Any],
    candidate: Mapping[str, Any],
    path: Path,
) -> None:
    if document.get("candidate_variant") != "s2":
        raise DashboardError(f"{path}: replay candidate_variant must be s2")
    evaluated = _required_mapping(
        document.get("evaluated_candidate"), f"{path} evaluated_candidate"
    )
    expected = {
        "archive_sha256": candidate.get("package_sha256"),
        "manifest_sha256": candidate.get("manifest_sha256"),
        "extracted_tree_sha256": candidate.get("verified_tree_sha256"),
        "runtime_source_tree_sha256": candidate.get("verified_runtime_tree_sha256"),
    }
    for key, expected_value in expected.items():
        actual = _declared_sha256(evaluated.get(key), f"{path} candidate {key}")
        if actual != expected_value:
            raise DashboardError(f"{path}: replay candidate {key} mismatch")


def _verify_replay_baseline_pins(
    document: Mapping[str, Any], path: Path
) -> None:
    try:
        from scripts.evaluate_dipplin_replay_regret import (
            PINNED_S1_ARCHIVE_SHA256,
            PINNED_S1_EXTRACTED_TREE_SHA256,
            PINNED_S1_MANIFEST_SHA256,
            PINNED_S1_PRIMARY_RECORD_COUNT,
            PINNED_S1_RUNTIME_TREE_SHA256,
            PINNED_S1_VALIDATION_OUTPUT_SHA256,
        )
    except ImportError as error:
        raise DashboardError(f"cannot import frozen S1 pins: {error}") from error
    baseline = _required_mapping(
        document.get("baseline_incumbent_s1"), f"{path} baseline_incumbent_s1"
    )
    expected_keys = {
        "variant",
        "archive_sha256",
        "manifest_sha256",
        "extracted_tree_sha256",
        "runtime_source_tree_sha256",
        "validation_result_sha256",
        "paired_record_count",
        "paired_record_id_sequence_sha256",
    }
    _exact_keys(baseline, expected_keys, f"{path} baseline_incumbent_s1")
    expected_hashes = {
        "archive_sha256": PINNED_S1_ARCHIVE_SHA256.lower(),
        "manifest_sha256": PINNED_S1_MANIFEST_SHA256.lower(),
        "extracted_tree_sha256": PINNED_S1_EXTRACTED_TREE_SHA256.lower(),
        "runtime_source_tree_sha256": PINNED_S1_RUNTIME_TREE_SHA256.lower(),
        "validation_result_sha256": PINNED_S1_VALIDATION_OUTPUT_SHA256.lower(),
    }
    if baseline.get("variant") != "s1":
        raise DashboardError(f"{path}: replay baseline variant mismatch")
    for key, expected in expected_hashes.items():
        if _declared_sha256(baseline.get(key), f"{path} baseline {key}") != expected:
            raise DashboardError(f"{path}: replay baseline {key} mismatch")
    if _required_integer(
        baseline.get("paired_record_count"), f"{path} paired_record_count"
    ) != PINNED_S1_PRIMARY_RECORD_COUNT:
        raise DashboardError(f"{path}: replay baseline paired-record count mismatch")
    _declared_sha256(
        baseline.get("paired_record_id_sequence_sha256"),
        f"{path} paired_record_id_sequence_sha256",
    )


def _replay_v2_summary(
    base: Path,
    raw: Any,
    *,
    split: str,
    candidate: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    declaration = _required_mapping(raw, f"{split} replay declaration")
    required = {
        "path",
        "artifact_sha256",
        "expected_schema",
        "expected_split",
        "expected_sealed",
        "expected_episode_count",
        "expected_manifest_file_sha256",
        "expected_manifest_payload_sha256",
    }
    _exact_keys(declaration, required, f"{split} replay declaration")
    path = _resolve(base, declaration.get("path"))
    source_sha256 = _verify_file_sha256(path, declaration.get("artifact_sha256"))
    document = _load(path)
    expected_sealed = split == "FINAL_HOLDOUT"
    expected_episodes = _required_integer(
        declaration.get("expected_episode_count"), "expected_episode_count"
    )
    if (
        declaration.get("expected_schema") != REPLAY_V2_SCHEMA
        or declaration.get("expected_split") != split
        or declaration.get("expected_sealed") is not expected_sealed
        or document.get("schema") != REPLAY_V2_SCHEMA
        or document.get("split") != split
        or document.get("sealed") is not expected_sealed
    ):
        raise DashboardError(f"{path}: replay schema/split/sealed contract mismatch")
    if expected_episodes != _required_integer(
        manifest.get("episode_count"), "manifest episode_count"
    ):
        raise DashboardError(f"{path}: replay/manifest episode-count mismatch")
    if _declared_sha256(
        declaration.get("expected_manifest_file_sha256"),
        "expected_manifest_file_sha256",
    ) != manifest.get("source_sha256"):
        raise DashboardError(f"{path}: replay manifest file pin mismatch")
    expected_payload = _declared_sha256(
        declaration.get("expected_manifest_payload_sha256"),
        "expected_manifest_payload_sha256",
    )
    if (
        expected_payload != manifest.get("manifest_payload_sha256")
        or str(document.get("manifest_payload_sha256") or "").lower()
        != expected_payload
    ):
        raise DashboardError(f"{path}: replay manifest payload pin mismatch")
    _verify_replay_candidate_pins(document, candidate, path)
    _verify_replay_baseline_pins(document, path)

    if expected_sealed:
        _exact_keys(document, SEALED_REPLAY_TOP_LEVEL_KEYS, f"{path} sealed replay")
        found = _contains_forbidden_key(document, SEALED_FORBIDDEN_KEYS)
        if found is not None:
            raise DashboardError(
                f"{path}: sealed aggregate contains forbidden detail key {found}"
            )
        sealed_aggregate = _required_mapping(
            document.get("aggregate"), f"{path} sealed aggregate"
        )
        _exact_keys(
            sealed_aggregate,
            SEALED_REPLAY_AGGREGATE_KEYS,
            f"{path} sealed aggregate",
        )
        aggregate = _replay_aggregate_v2(
            sealed_aggregate,
            path=path,
            expected_episodes=expected_episodes,
            sealed=True,
        )
        return {
            "available": True,
            "status": "COMPLETE",
            "split": split,
            "sealed_aggregate_only": True,
            "source": str(path),
            "source_sha256": source_sha256,
            "opponent_archetype_coverage": manifest.get(
                "opponent_archetype_episode_counts", {}
            ),
            "coverage_source": "frozen_metadata_only_manifest",
            **aggregate,
            "episodes": aggregate["episode_count"],
            "decisions": aggregate["decision_count"],
            "classifications": aggregate["classification_counts"],
            "rates": aggregate["episode_rates"],
            "bootstrap_95": aggregate["episode_bootstrap_95"],
            "rate_basis": "episode_mean",
        }

    if (
        document.get("headline_set") != "paired_primary"
        or document.get("aggregate_alias")
        != "evaluation_sets.paired_primary.aggregate"
        or document.get("combined_rate_permitted") is not False
        or "decision_rows" in document
    ):
        raise DashboardError(f"{path}: validation dual-set contract mismatch")
    sets = _required_mapping(document.get("evaluation_sets"), f"{path} evaluation_sets")
    _exact_keys(sets, {"paired_primary", "s2_exploratory"}, f"{path} evaluation_sets")
    primary = _required_mapping(sets.get("paired_primary"), f"{path} paired_primary")
    exploratory = _required_mapping(sets.get("s2_exploratory"), f"{path} s2_exploratory")
    if (
        primary.get("role") != "qualification_primary"
        or exploratory.get("role") != "exploratory_safety_veto_only"
        or exploratory.get("safety_veto_only") is not True
        or exploratory.get("eligible_for_efficacy_rate") is not False
        or document.get("aggregate") != primary.get("aggregate")
    ):
        raise DashboardError(f"{path}: validation primary/exploratory roles mismatch")
    primary_selection = _required_mapping(
        primary.get("selection"), f"{path} paired_primary.selection"
    )
    if (
        primary_selection.get("mode") != "exact_frozen_s1_record_ids"
        or primary_selection.get("order_preserved") is not True
        or _required_integer(
            primary_selection.get("record_count"), f"{path} primary record_count"
        )
        <= 0
    ):
        raise DashboardError(f"{path}: validation primary selection mismatch")
    primary_rows = _required_sequence(
        primary.get("decision_rows"), f"{path} paired_primary.decision_rows"
    )
    exploratory_rows = _required_sequence(
        exploratory.get("decision_rows"), f"{path} s2_exploratory.decision_rows"
    )
    primary_ids = [str(_required_mapping(row, "primary row").get("record_id") or "") for row in primary_rows]
    exploratory_ids = [str(_required_mapping(row, "exploratory row").get("record_id") or "") for row in exploratory_rows]
    if (
        not all(primary_ids)
        or not all(exploratory_ids)
        or len(primary_ids) != len(set(primary_ids))
        or len(exploratory_ids) != len(set(exploratory_ids))
        or set(primary_ids) & set(exploratory_ids)
        or len(primary_ids) != int(primary_selection["record_count"])
    ):
        raise DashboardError(f"{path}: validation record sets overlap or are malformed")
    primary_aggregate = _replay_aggregate_v2(
        primary.get("aggregate"),
        path=path,
        expected_episodes=expected_episodes,
        sealed=False,
    )
    exploratory_aggregate = _replay_aggregate_v2(
        exploratory.get("aggregate"),
        path=path,
        expected_episodes=_required_integer(
            _required_mapping(
                exploratory.get("aggregate"), f"{path} exploratory aggregate"
            ).get("episode_count"),
            f"{path} exploratory episode_count",
        ),
        sealed=False,
        require_full_manifest_coverage=False,
    )
    if primary_aggregate["decision_count"] != len(primary_rows) or exploratory_aggregate[
        "decision_count"
    ] != len(exploratory_rows):
        raise DashboardError(f"{path}: validation decision-row counts mismatch")
    if primary_aggregate["opponent_archetype_episode_counts"] != manifest.get(
        "opponent_archetype_episode_counts"
    ):
        raise DashboardError(f"{path}: validation archetype coverage differs from manifest")
    return {
        "available": True,
        "status": "COMPLETE",
        "split": split,
        "sealed_aggregate_only": False,
        "source": str(path),
        "source_sha256": source_sha256,
        "headline_set": "paired_primary",
        "combined_rate_permitted": False,
        "episodes": primary_aggregate["episode_count"],
        "decisions": primary_aggregate["decision_count"],
        "classifications": primary_aggregate["classification_counts"],
        "rates": primary_aggregate["episode_rates"],
        "bootstrap_95": primary_aggregate["episode_bootstrap_95"],
        "quality_counts": primary_aggregate["quality_counts"],
        "opponent_archetype_coverage": primary_aggregate[
            "opponent_archetype_episode_counts"
        ],
        "opponent_archetype_decision_counts": primary_aggregate[
            "opponent_archetype_decision_counts"
        ],
        "rate_basis": "episode_mean",
        "paired_primary": primary_aggregate,
        "s2_exploratory_safety_veto": exploratory_aggregate,
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


def _mechanics_dashboard(
    base: Path, raw: Any, *, strict: bool = False
) -> dict[str, Any]:
    if raw is None:
        return {"status": "NOT_RECORDED", "passed": 0, "failed": 0}
    if not isinstance(raw, Mapping):
        raise DashboardError("mechanics must be an object")
    if strict:
        required = {
            "status",
            "junit_xml",
            "junit_xml_sha256",
            "expected_tests",
            "command",
            "run_date",
            "test_files",
            "scope",
            "caveat",
        }
        _exact_keys(raw, required, "mechanics")
        if raw.get("status") != "PASS":
            raise DashboardError("mechanics.status must be PASS")
        xml_path = _resolve(base, raw.get("junit_xml"))
        xml_sha256 = _verify_file_sha256(
            xml_path, raw.get("junit_xml_sha256"), "mechanics.junit_xml_sha256"
        )
        try:
            root = ElementTree.parse(xml_path).getroot()
        except (OSError, ElementTree.ParseError) as error:
            raise DashboardError(f"invalid mechanics JUnit XML: {error}") from error
        suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
        if not suites:
            raise DashboardError("mechanics JUnit XML has no testsuite")
        totals = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
        for suite in suites:
            for key in totals:
                totals[key] += _required_integer(
                    int(suite.attrib.get(key, "0")), f"mechanics junit {key}"
                )
        expected_tests = _required_integer(
            raw.get("expected_tests"), "mechanics.expected_tests"
        )
        if (
            totals["tests"] != expected_tests
            or totals["failures"]
            or totals["errors"]
            or totals["skipped"]
        ):
            raise DashboardError("mechanics JUnit result is incomplete or failing")
        test_files_raw = _required_sequence(raw.get("test_files"), "mechanics.test_files")
        verified_files: list[dict[str, str]] = []
        for index, declaration_raw in enumerate(test_files_raw):
            declaration = _required_mapping(
                declaration_raw, f"mechanics.test_files[{index}]"
            )
            _exact_keys(
                declaration,
                {"path", "sha256"},
                f"mechanics.test_files[{index}]",
            )
            path = _resolve(base, declaration.get("path"))
            verified_files.append(
                {
                    "path": str(path),
                    "sha256": _verify_file_sha256(
                        path,
                        declaration.get("sha256"),
                        f"mechanics.test_files[{index}].sha256",
                    ),
                }
            )
        return {
            "status": "PASS",
            "junit_xml": str(xml_path),
            "junit_xml_sha256": xml_sha256,
            "tests": totals["tests"],
            "passed": totals["tests"],
            "failed": totals["failures"],
            "errors": totals["errors"],
            "skipped": totals["skipped"],
            "command": raw.get("command"),
            "run_date": raw.get("run_date"),
            "test_files": verified_files,
            "scope": raw.get("scope"),
            "caveat": raw.get("caveat"),
        }
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
        archetype_counts: dict[str, int] = defaultdict(int)
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
            opponent = episode.get("opponent")
            opponent = opponent if isinstance(opponent, Mapping) else {}
            archetype = str(opponent.get("archetype") or "unknown")
            archetype_counts[archetype] += 1
            if episode.get("selection_contract_verified") is True:
                verified_selections += 1
        inspection = document.get("inspection_policy")
        inspection = inspection if isinstance(inspection, Mapping) else {}
        selection = document.get("selection_provenance")
        selection = selection if isinstance(selection, Mapping) else {}
        for field, actual_counts in (
            ("expected_actual_order_counts", dict(order_counts)),
            ("expected_expert_result_counts", dict(outcome_counts)),
            ("expected_opponent_archetype_episode_counts", dict(archetype_counts)),
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
            "opponent_archetype_episode_counts": dict(
                sorted(archetype_counts.items())
            ),
            "selection_contract_verified_count": verified_selections,
            "selection_used_outcome": selection.get("selection_used_outcome"),
            "inspection_contract_at_freeze": {
                "metadata_only": inspection.get("metadata_only"),
                "action_level_inspected": inspection.get("action_level_inspected"),
                "replay_regret_executed": inspection.get("replay_regret_executed"),
            },
        }
    return result


def _v2_replay_manifest_provenance(base: Path, raw: Any) -> dict[str, Any]:
    declarations = _required_mapping(raw, "replay_manifests")
    _exact_keys(
        declarations,
        {"validation", "final_holdout"},
        "replay_manifests",
    )
    required_keys = {
        "path",
        "artifact_sha256",
        "expected_split",
        "expected_episode_count",
        "expected_sealed",
        "expected_payload_sha256",
        "expected_actual_order_counts",
        "expected_expert_result_counts",
        "expected_selection_contract_verified_count",
        "require_pristine",
    }
    optional_keys = {"expected_opponent_archetype_episode_counts"}
    for label, raw_declaration in declarations.items():
        declaration = _required_mapping(
            raw_declaration, f"replay_manifests.{label}"
        )
        actual_keys = set(declaration)
        missing = required_keys - actual_keys
        extra = actual_keys - required_keys - optional_keys
        if missing or extra:
            raise DashboardError(
                f"replay_manifests.{label} keys mismatch "
                f"(missing={sorted(missing)}, extra={sorted(extra)})"
            )
        if declaration.get("require_pristine") is not True:
            raise DashboardError(
                f"replay_manifests.{label}.require_pristine must be true"
            )
    try:
        from scripts.evaluate_dipplin_replay_regret import PINNED_MANIFESTS
    except ImportError as error:
        raise DashboardError(
            f"cannot import canonical replay-manifest pins: {error}"
        ) from error
    for label, split in (
        ("validation", "VALIDATION"),
        ("final_holdout", "FINAL_HOLDOUT"),
    ):
        declaration = _required_mapping(
            declarations[label], f"replay_manifests.{label}"
        )
        pinned = _required_mapping(
            PINNED_MANIFESTS.get(split), f"PINNED_MANIFESTS.{split}"
        )
        path = _resolve(base, declaration.get("path"))
        if (
            path != Path(str(pinned.get("path"))).resolve()
            or _declared_sha256(
                declaration.get("artifact_sha256"),
                f"replay_manifests.{label}.artifact_sha256",
            )
            != str(pinned.get("file_sha256") or "").lower()
            or _declared_sha256(
                declaration.get("expected_payload_sha256"),
                f"replay_manifests.{label}.expected_payload_sha256",
            )
            != str(pinned.get("payload_sha256") or "").lower()
        ):
            raise DashboardError(
                f"replay_manifests.{label} is not the canonical pinned manifest"
            )
    result = _replay_manifest_provenance(base, declarations)
    expected_contracts = {
        "validation": ("VALIDATION", False),
        "final_holdout": ("FINAL_HOLDOUT", True),
    }
    for label, (split, sealed) in expected_contracts.items():
        manifest = _required_mapping(result.get(label), f"replay_manifests.{label}")
        if (
            manifest.get("split") != split
            or manifest.get("sealed") is not sealed
            or manifest.get("episode_count", 0) <= 0
            or manifest.get("selection_contract_verified_count")
            != manifest.get("episode_count")
            or manifest.get("selection_used_outcome") is not False
            or manifest.get("inspection_contract_at_freeze")
            != {
                "metadata_only": True,
                "action_level_inspected": False,
                "replay_regret_executed": False,
            }
        ):
            raise DashboardError(
                f"replay_manifests.{label} frozen split/privacy contract mismatch"
            )
    return result


def _weak_clones_dashboard(raw: Any, *, strict: bool) -> list[dict[str, Any]]:
    rows = raw if isinstance(raw, list) else []
    if strict and not isinstance(raw, list):
        raise DashboardError("weak_clones must be an array")
    forbidden = {
        "wins",
        "losses",
        "draws",
        "win_rate",
        "score",
        "reward",
        "win_rate_a",
    }
    allowed = {
        "name",
        "availability",
        "coverage",
        "runnable_status",
        "evaluated_contexts",
        "failed_games",
        "policy_errors",
        "illegal_actions",
        "unknown_contexts",
        "note",
    }
    result: list[dict[str, Any]] = []
    for index, raw_row in enumerate(rows):
        row = _required_mapping(raw_row, f"weak_clones[{index}]")
        if not strict:
            output = dict(row)
            output.update(
                {
                    "strength_status": "CEILINGED — EXCLUDED FROM STRENGTH",
                    "win_rate_is_strength_metric": False,
                }
            )
            result.append(output)
            continue
        if forbidden & set(row):
            raise DashboardError(
                f"weak_clones[{index}] contains prohibited strength outcome fields"
            )
        if strict and set(row) - allowed:
            raise DashboardError(
                f"weak_clones[{index}] contains unsupported fields: "
                + ", ".join(sorted(set(row) - allowed))
            )
        name = str(row.get("name") or "").strip()
        if not name:
            raise DashboardError(f"weak_clones[{index}].name is required")
        runnable = str(row.get("runnable_status") or "").strip()
        output = {
            key: row.get(key)
            for key in allowed
            if key in row
        }
        output.update(
            {
                "name": name,
                "strength_status": "CEILINGED — EXCLUDED FROM STRENGTH",
                "win_rate_is_strength_metric": False,
            }
        )
        if strict and runnable in {"NOT_RUN_NONRUNNABLE", "WEIGHTS_ONLY"}:
            for key in (
                "failed_games",
                "policy_errors",
                "illegal_actions",
                "unknown_contexts",
            ):
                if row.get(key) not in (None, "NOT_MEASURABLE"):
                    raise DashboardError(
                        f"weak_clones[{index}].{key} must be NOT_MEASURABLE"
                    )
        result.append(output)
    return result


def _qualification_dashboard(
    base: Path,
    raw: Any,
    *,
    validation: Mapping[str, Any],
) -> dict[str, Any]:
    declaration = _required_mapping(raw, "qualification")
    _exact_keys(
        declaration,
        {
            "path",
            "artifact_sha256",
            "payload_sha256",
            "candidate_validation_sha256",
        },
        "qualification",
    )
    path = _resolve(base, declaration.get("path"))
    file_sha256 = _verify_file_sha256(
        path, declaration.get("artifact_sha256"), "qualification.artifact_sha256"
    )
    payload = _load(path)
    if payload.get("schema") != QUALIFICATION_SCHEMA or payload.get("status") != "QUALIFIED":
        raise DashboardError("qualification is not a QUALIFIED S2 artifact")
    claimed_payload = _declared_sha256(
        declaration.get("payload_sha256"), "qualification.payload_sha256"
    )
    embedded_payload = _declared_sha256(
        payload.get("qualification_payload_sha256"),
        "qualification qualification_payload_sha256",
    )
    unsigned = dict(payload)
    unsigned.pop("qualification_payload_sha256", None)
    canonical_payload = json.dumps(
        unsigned,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    calculated_payload = hashlib.sha256(canonical_payload).hexdigest()
    if claimed_payload != embedded_payload or claimed_payload != calculated_payload:
        raise DashboardError("qualification payload digest mismatch")
    expected_validation = _declared_sha256(
        declaration.get("candidate_validation_sha256"),
        "qualification.candidate_validation_sha256",
    )
    if expected_validation != validation.get("source_sha256"):
        raise DashboardError("qualification candidate-validation pin mismatch")
    candidate_validation = _required_mapping(
        payload.get("candidate_validation"), "qualification.candidate_validation"
    )
    if _declared_sha256(
        candidate_validation.get("sha256"),
        "qualification.candidate_validation.sha256",
    ) != expected_validation:
        raise DashboardError("qualification payload candidate-validation mismatch")
    try:
        from scripts.create_dipplin_s2_qualification import (
            QualificationError,
            verify_canonical_qualification,
        )

        verified = verify_canonical_qualification(path)
    except (OSError, QualificationError) as error:
        raise DashboardError(f"qualification verification failed: {error}") from error
    if (
        verified.get("schema") != QUALIFICATION_SCHEMA
        or verified.get("status") != "QUALIFIED"
        or str(verified.get("file_sha256") or "").lower() != file_sha256
        or str(verified.get("payload_sha256") or "").lower() != claimed_payload
        or str(verified.get("candidate_validation_sha256") or "").lower()
        != expected_validation
    ):
        raise DashboardError("qualification verifier result does not match declaration")
    return {
        "status": "QUALIFIED",
        "source": str(path),
        "file_sha256": file_sha256,
        "payload_sha256": claimed_payload,
        "candidate_validation_sha256": expected_validation,
        "rule_version": verified.get("rule_version"),
    }


def _receipt_dashboard(
    base: Path,
    raw: Any,
    *,
    holdout: Mapping[str, Any],
    holdout_manifest: Mapping[str, Any],
    qualification: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    declaration = _required_mapping(raw, "sealed_holdout_receipt")
    _exact_keys(
        declaration,
        {"path", "artifact_sha256", "expected_parameters", "evaluator"},
        "sealed_holdout_receipt",
    )
    path = _resolve(base, declaration.get("path"))
    file_sha256 = _verify_file_sha256(path, declaration.get("artifact_sha256"))
    receipt = _load(path)
    if receipt.get("schema") != SEALED_RECEIPT_SCHEMA or receipt.get("status") != "COMPLETE":
        raise DashboardError("sealed holdout receipt is not COMPLETE")
    try:
        from scripts.evaluate_dipplin_replay_regret import (
            PINNED_S1_ARCHIVE_SHA256,
            PINNED_S1_VALIDATION_OUTPUT_SHA256,
        )
    except ImportError as error:
        raise DashboardError(f"cannot import frozen S1 receipt pins: {error}") from error
    pins = {
        "baseline_s1_archive_sha256": PINNED_S1_ARCHIVE_SHA256.lower(),
        "baseline_s1_validation_sha256": PINNED_S1_VALIDATION_OUTPUT_SHA256.lower(),
        "manifest_file_sha256": holdout_manifest.get("source_sha256"),
        "manifest_payload_sha256": holdout_manifest.get("manifest_payload_sha256"),
        "candidate_archive_sha256": candidate.get("package_sha256"),
        "candidate_manifest_sha256": candidate.get("manifest_sha256"),
        "candidate_extracted_tree_sha256": candidate.get("verified_tree_sha256"),
        "candidate_runtime_tree_sha256": candidate.get("verified_runtime_tree_sha256"),
        "qualification_file_sha256": qualification.get("file_sha256"),
        "qualification_payload_sha256": qualification.get("payload_sha256"),
        "candidate_validation_sha256": qualification.get(
            "candidate_validation_sha256"
        ),
        "aggregate_output_sha256": holdout.get("source_sha256"),
    }
    for key, expected in pins.items():
        actual = _declared_sha256(receipt.get(key), f"receipt.{key}")
        if actual != expected:
            raise DashboardError(f"sealed holdout receipt {key} mismatch")
    if receipt.get("candidate") != "s2":
        raise DashboardError("sealed holdout receipt candidate mismatch")
    expected_parameters = _required_mapping(
        declaration.get("expected_parameters"),
        "sealed_holdout_receipt.expected_parameters",
    )
    try:
        from scripts.evaluate_dipplin_replay_regret import (
            FROZEN_SEALED_PARAMETERS,
        )
    except ImportError as error:
        raise DashboardError(
            f"cannot import frozen sealed parameters: {error}"
        ) from error
    if (
        dict(expected_parameters) != FROZEN_SEALED_PARAMETERS
        or receipt.get("parameters") != FROZEN_SEALED_PARAMETERS
    ):
        raise DashboardError("sealed holdout receipt parameters mismatch")
    evaluator = _required_mapping(
        declaration.get("evaluator"), "sealed_holdout_receipt.evaluator"
    )
    _exact_keys(evaluator, {"path", "sha256", "git_blob_sha1"}, "receipt evaluator")
    evaluator_path = _resolve(ROOT, evaluator.get("path"))
    evaluator_sha256 = _verify_file_sha256(
        evaluator_path, evaluator.get("sha256"), "receipt evaluator.sha256"
    )
    evaluator_blob = _git_blob_sha1(evaluator_path)
    declared_evaluator_blob = str(evaluator.get("git_blob_sha1") or "").lower()
    if (
        len(declared_evaluator_blob) != 40
        or any(
            character not in "0123456789abcdef"
            for character in declared_evaluator_blob
        )
        or evaluator_blob != declared_evaluator_blob
    ):
        raise DashboardError("sealed holdout receipt evaluator git_blob_sha1 mismatch")
    actual_evaluator = {
        "path": str(evaluator_path.relative_to(ROOT)),
        "sha256": evaluator_sha256,
        "git_blob_sha1": evaluator_blob,
    }
    receipt_evaluator = {
        "path": receipt.get("evaluator_path"),
        "sha256": str(receipt.get("evaluator_sha256") or "").lower(),
        "git_blob_sha1": str(receipt.get("evaluator_git_blob_sha1") or "").lower(),
    }
    if receipt_evaluator != actual_evaluator:
        raise DashboardError("sealed holdout receipt evaluator provenance mismatch")
    aggregate_output = Path(str(receipt.get("aggregate_output") or "")).resolve()
    if aggregate_output != Path(str(holdout.get("source"))).resolve():
        raise DashboardError("sealed receipt aggregate output path mismatch")
    return {
        "status": "COMPLETE",
        "source": str(path),
        "source_sha256": file_sha256,
        "parameters": dict(expected_parameters),
        "evaluator": actual_evaluator,
    }


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
        expected_platform = declaration.get("expected_platform")
        expected_machine = declaration.get("expected_machine")
        actual_platform = str(provenance.get("platform") or "")
        if expected_platform is not None:
            platform_matches = (
                actual_platform.startswith("Linux")
                if expected_platform == "Linux"
                else actual_platform == expected_platform
            )
            if not platform_matches:
                raise DashboardError(f"{path}: platform mismatch")
        if expected_machine is not None and provenance.get("machine") != expected_machine:
            raise DashboardError(f"{path}: machine mismatch")
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
        expected_s2_enabled = declaration.get("expected_s2_enabled")
        if expected_s2_enabled is not None:
            telemetry = document.get("hero_telemetry")
            telemetry = telemetry if isinstance(telemetry, Mapping) else {}
            s2_enabled_games = _integer(telemetry.get("s2_enabled"))
            expected_s2_total = games if expected_s2_enabled is True else 0
            if s2_enabled_games != expected_s2_total:
                raise DashboardError(f"{path}: S2-enabled telemetry mismatch")
            actual_declarations["s2_enabled_games"] = s2_enabled_games
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
            "s2_enabled_games": actual_declarations.get("s2_enabled_games"),
        }
    return result


def _v2_operational_provenance(base: Path, raw: Any) -> dict[str, Any]:
    declarations = _required_mapping(raw, "operational_provenance")
    for label, raw_declaration in declarations.items():
        declaration = _required_mapping(
            raw_declaration, f"operational_provenance.{label}"
        )
        if "path" not in declaration:
            raise DashboardError(
                f"operational_provenance.{label} must be a hashed artifact declaration"
            )
    return _operational_provenance(base, declarations)


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
    nonfatal: dict[str, int] = defaultdict(int)
    fatal: dict[str, int] = defaultdict(int)
    for cell in selected:
        telemetry = cell.get("operational_telemetry")
        telemetry = telemetry if isinstance(telemetry, Mapping) else {}
        for key, value in _optional_mapping(
            telemetry.get("nonfatal_search_fallback_counts"),
            "nonfatal_search_fallback_counts",
        ).items():
            nonfatal[str(key)] += _integer(value)
        for key, value in _optional_mapping(
            telemetry.get("fatal_counts"), "fatal_counts"
        ).items():
            fatal[str(key)] += _integer(value)
    hero_policy = sum(_integer(cell.get("hero_policy_errors")) for cell in selected)
    opponent_policy = sum(
        _integer(cell.get("opponent_policy_errors")) for cell in selected
    )
    hero_illegal = sum(_integer(cell.get("hero_illegal_actions")) for cell in selected)
    opponent_illegal = sum(
        _integer(cell.get("opponent_illegal_actions")) for cell in selected
    )
    return {
        "failed_games": sum(_integer(cell.get("failed_games")) for cell in selected),
        "hero_policy_errors": hero_policy,
        "opponent_policy_errors": opponent_policy,
        "policy_errors": hero_policy + opponent_policy,
        "hero_illegal_actions": hero_illegal,
        "opponent_illegal_actions": opponent_illegal,
        "illegal_actions": hero_illegal + opponent_illegal,
        "unknown_contexts": sum(float(cell.get("unknown_contexts") or 0.0) for cell in selected),
        "fatal_operational_telemetry": {
            "counts": dict(sorted(fatal.items())),
            "count": sum(fatal.values()),
        },
        "nonfatal_search_fallback_counts": dict(sorted(nonfatal.items())),
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


def _build_dashboard_v2(
    spec_path: Path, spec: Mapping[str, Any]
) -> dict[str, Any]:
    unknown = set(spec) - V2_ALLOWED_SPEC_KEYS
    if unknown:
        raise DashboardError(
            "unsupported v2 spec fields: " + ", ".join(sorted(unknown))
        )
    base = spec_path.parent
    candidate_raw = _required_mapping(spec.get("candidate"), "candidate")
    candidate = _candidate_dashboard(base, candidate_raw, strict=True)
    final_verdict = spec.get("final_verdict")
    if final_verdict not in FINAL_VERDICTS:
        raise DashboardError("final_verdict is missing or invalid")
    variant = candidate.get("variant")
    strength_raw = spec.get("strength_source")

    # A rejected S2 is represented by a KEEP_S1 dashboard whose candidate is
    # the immutable S1 archive. It deliberately does not fabricate promotion
    # qualification, sealed holdout, or S2 Linux certification.
    rejected_s2 = variant == "s1" and final_verdict in {
        "KEEP_S1",
        "S1_NEAR_ARCHITECTURE_CEILING",
        "REJECT_DIPPLIN",
    }
    if rejected_s2:
        if not isinstance(strength_raw, Mapping):
            raise DashboardError("KEEP_S1 v2 dashboard requires strength_source")
        rejection = _required_mapping(strength_raw, "strength_source")
        required = {
            "stage_spec",
            "stage_spec_sha256",
            "stage_report",
            "stage_report_sha256",
            "incumbent_dashboard_spec",
            "incumbent_dashboard_spec_sha256",
            "required_stage1_verdicts",
            "required_stage2_verdict",
            "incumbent_strong_anchors",
            "incumbent_same_deck",
        }
        _exact_keys(rejection, required, "strength_source")
        stage_spec = _resolve(base, rejection.get("stage_spec"))
        stage_report = _resolve(base, rejection.get("stage_report"))
        spec_sha = _verify_file_sha256(
            stage_spec,
            rejection.get("stage_spec_sha256"),
            "strength_source.stage_spec_sha256",
        )
        report_sha = _verify_file_sha256(
            stage_report,
            rejection.get("stage_report_sha256"),
            "strength_source.stage_report_sha256",
        )
        incumbent_dashboard_spec = _resolve(
            base, rejection.get("incumbent_dashboard_spec")
        )
        incumbent_dashboard_spec_sha = _verify_file_sha256(
            incumbent_dashboard_spec,
            rejection.get("incumbent_dashboard_spec_sha256"),
            "strength_source.incumbent_dashboard_spec_sha256",
        )
        canonical_incumbent_spec = (
            ROOT / "data/dipplin_general_strength/s1_dashboard_spec.json"
        ).resolve()
        if incumbent_dashboard_spec != canonical_incumbent_spec:
            raise DashboardError("KEEP_S1 requires the canonical S1 dashboard spec")
        if incumbent_dashboard_spec_sha != PINNED_S1_DASHBOARD_SPEC_SHA256:
            raise DashboardError("canonical S1 dashboard spec hash mismatch")
        canonical_incumbent = _load(incumbent_dashboard_spec)
        canonical_candidate = _required_mapping(
            canonical_incumbent.get("candidate"), "canonical S1 candidate"
        )
        candidate_fields = {
            "name",
            "source_sha",
            "tree_sha256",
            "package_sha256",
            "manifest_sha256",
        }
        if (
            any(
                canonical_candidate.get(key) != candidate_raw.get(key)
                for key in candidate_fields
            )
            or _resolve(incumbent_dashboard_spec.parent, canonical_candidate.get("package"))
            != _resolve(base, candidate_raw.get("package"))
            or _resolve(incumbent_dashboard_spec.parent, canonical_candidate.get("manifest"))
            != _resolve(base, candidate_raw.get("manifest"))
            or canonical_incumbent.get("strong_anchors")
            != rejection.get("incumbent_strong_anchors")
            or canonical_incumbent.get("same_deck")
            != rejection.get("incumbent_same_deck")
            or canonical_incumbent.get("second_bucket_analysis")
            != spec.get("second_bucket_analysis")
        ):
            raise DashboardError(
                "KEEP_S1 candidate/anchor/mirror declarations differ from canonical S1"
            )
        stage_spec_document = _load(stage_spec)
        stage_provenance = _required_mapping(
            stage_spec_document.get("provenance"), "stage_spec.provenance"
        )
        _git_sha(
            stage_provenance.get("source_head"),
            "stage_spec.provenance.source_head",
        )
        report = _load(stage_report)
        try:
            from scripts.evaluate_dipplin_s2_stages import (
                StageEvaluationError,
                evaluate_spec,
            )

            regenerated = evaluate_spec(stage_spec)
        except (OSError, StageEvaluationError) as error:
            raise DashboardError(f"cannot recompute rejected S2 report: {error}") from error
        if regenerated != report:
            raise DashboardError("rejected S2 stage report fails exact recomputation")
        if report.get("schema") != "dipplin-s2-stage-evaluation-v1":
            raise DashboardError("rejected S2 stage report schema mismatch")
        report_spec = _required_mapping(report.get("spec"), "stage_report.spec")
        if (
            Path(str(report_spec.get("path"))).resolve() != stage_spec
            or str(report_spec.get("sha256") or "").lower() != spec_sha
        ):
            raise DashboardError("rejected S2 report does not bind its stage spec")
        baseline_identity = _required_mapping(
            report.get("baseline"), "stage_report.baseline"
        )
        if (
            _declared_sha256(
                baseline_identity.get("tree_sha256"),
                "stage_report.baseline.tree_sha256",
            )
            != candidate.get("verified_tree_sha256")
            or _declared_sha256(
                baseline_identity.get("archive_sha256"),
                "stage_report.baseline.archive_sha256",
            )
            != candidate.get("package_sha256")
            or _declared_sha256(
                _required_mapping(
                    baseline_identity.get("package_manifest"),
                    "stage_report.baseline.package_manifest",
                ).get("sha256"),
                "stage_report.baseline.package_manifest.sha256",
            )
            != candidate.get("manifest_sha256")
        ):
            raise DashboardError("KEEP_S1 candidate is not the staged S1 baseline")
        rejected_candidate = _verify_rejected_s2_candidate(
            base,
            spec.get("rejected_s2_candidate"),
            stage_candidate=_required_mapping(
                report.get("candidate"), "stage_report.candidate"
            ),
        )
        if rejected_candidate.get("source_sha") != str(
            stage_provenance.get("source_head")
        ).lower():
            raise DashboardError(
                "rejected S2 source SHA does not match stage-spec source_head"
            )
        stages = _required_mapping(report.get("stages"), "stage_report.stages")
        stage1 = _required_mapping(stages.get("stage1"), "stage1")
        stage2 = _required_mapping(stages.get("stage2"), "stage2")
        allowed_stage1 = _required_sequence(
            rejection.get("required_stage1_verdicts"),
            "required_stage1_verdicts",
        )
        stage1_decision = _required_mapping(
            stage1.get("decision"), "stage1.decision"
        )
        stage2_decision = _required_mapping(
            stage2.get("decision"), "stage2.decision"
        )
        stage1_gates = _required_mapping(
            stage1_decision.get("gates"), "stage1.decision.gates"
        )
        stage2_gates = _required_mapping(
            stage2_decision.get("gates"), "stage2.decision.gates"
        )
        if (
            stage1.get("status") != "EVALUATED"
            or stage1_decision.get("verdict") not in allowed_stage1
            or not stage1_gates
            or any(value is not True for value in stage1_gates.values())
            or stage2.get("status") != "EVALUATED"
            or stage2_decision.get("verdict")
            != rejection.get("required_stage2_verdict")
            or not stage2_gates
            or not any(value is False for value in stage2_gates.values())
            or rejection.get("required_stage2_verdict") != "KILL"
        ):
            raise DashboardError("KEEP_S1 rejection-stage contract mismatch")
        for name in ("stage3", "stage4", "stage5", "stage6"):
            status = str(_required_mapping(stages.get(name), name).get("status") or "")
            if not (
                status.startswith("INADMISSIBLE_PRECEDING_STAGE_KILL")
                or status == "PENDING"
            ):
                raise DashboardError(f"{name} should not be evaluated after Stage2 KILL")
        anchors, anchor_cells = _anchor_dashboard(
            incumbent_dashboard_spec.parent,
            rejection.get("incumbent_strong_anchors"),
        )
        same_deck, mirror_cells = _same_deck(
            incumbent_dashboard_spec.parent,
            rejection.get("incumbent_same_deck"),
        )
        canonical_anchor_rows = _required_sequence(
            canonical_incumbent.get("strong_anchors"),
            "canonical S1 strong_anchors",
        )
        expected_anchor_pairs = {
            (
                str(_required_mapping(row, "canonical S1 anchor").get("opponent")),
                _required_mapping(row, "canonical S1 anchor").get("actual_order"),
            )
            for row in canonical_anchor_rows
        }
        anchor_pairs = {
            (str(cell.get("opponent") or ""), cell.get("actual_order"))
            for cell in anchor_cells
        }
        if (
            len(anchor_cells) != 8
            or len(expected_anchor_pairs) != 8
            or anchor_pairs != expected_anchor_pairs
        ):
            raise DashboardError(
                "KEEP_S1 requires one exact current anchor for every opponent/order"
            )
        for cell in anchor_cells:
            if cell.get("evaluated_tree_sha256") != candidate.get(
                "verified_tree_sha256"
            ):
                raise DashboardError("KEEP_S1 anchor uses a non-incumbent tree")
        if set(same_deck) != {
            "s1_vs_s1_first",
            "s1_vs_s1_second",
            "candidate_vs_s1_first",
            "candidate_vs_s1_second",
        }:
            raise DashboardError("KEEP_S1 same-deck control shape mismatch")
        if (
            same_deck.get("s1_vs_s1_first") is None
            or same_deck.get("s1_vs_s1_second") is None
            or same_deck.get("candidate_vs_s1_first") is not None
            or same_deck.get("candidate_vs_s1_second") is not None
        ):
            raise DashboardError("KEEP_S1 requires exact S1 mirror controls only")
        for cell in mirror_cells:
            if cell.get("evaluated_tree_sha256") != candidate.get(
                "verified_tree_sha256"
            ):
                raise DashboardError("KEEP_S1 mirror uses a non-incumbent tree")
        strength = {
            "source": {
                "stage_spec": str(stage_spec),
                "stage_spec_sha256": spec_sha,
                "stage_report": str(stage_report),
                "stage_report_sha256": report_sha,
                "incumbent_dashboard_spec": str(incumbent_dashboard_spec),
                "incumbent_dashboard_spec_sha256": incumbent_dashboard_spec_sha,
                "exact_recomputation_match": True,
            },
            "candidate_vs_s1": {
                "rejected_candidate": rejected_candidate,
                "stage1": _stage_comparison_view(stage1),
                "stage2": _stage_comparison_view(stage2),
            },
            "stage_verdicts": {
                "stage1": stage1["decision"]["verdict"],
                "stage2": "KILL",
            },
            "anchors": anchors,
            "anchor_cells": anchor_cells,
            "same_deck": same_deck,
            "same_deck_provenance": {"status": "IMMUTABLE_S1_CONTROLS"},
            "operational_cells": [*anchor_cells, *mirror_cells],
        }
    else:
        if variant != "s2" or final_verdict not in {
            "PROMOTE_S2",
            "PROMOTE_S2_NEEDS_LIVE_TEST",
        }:
            raise DashboardError("v2 candidate/verdict combination is inconsistent")
        strength = _strength_source_dashboard(base, strength_raw, candidate)

    manifests = _v2_replay_manifest_provenance(
        base, spec.get("replay_manifests")
    )
    validation_manifest = manifests.get("validation")
    holdout_manifest = manifests.get("final_holdout")
    if not isinstance(validation_manifest, Mapping) or not isinstance(
        holdout_manifest, Mapping
    ):
        raise DashboardError("v2 dashboard requires both frozen replay manifests")

    if rejected_s2:
        replay_validation = _s1_replay_validation_summary(
            base,
            spec.get("replay_validation"),
            candidate=candidate,
            manifest=validation_manifest,
        )
        sealed_holdout = {
            "available": False,
            "split": "FINAL_HOLDOUT",
            "episodes": 0,
            "status": "NOT_RUN_NOT_APPLICABLE_AFTER_S2_REJECTION",
        }
        if spec.get("sealed_replay_holdout") not in (None, ""):
            raise DashboardError("rejected S2 dashboard cannot admit a sealed holdout")
        if spec.get("qualification") not in (None, "") or spec.get(
            "sealed_holdout_receipt"
        ) not in (None, ""):
            raise DashboardError("rejected S2 dashboard cannot claim qualification/receipt")
        qualification = {"status": "NOT_APPLICABLE_AFTER_S2_REJECTION"}
        receipt = {"status": "NOT_RUN_NOT_APPLICABLE_AFTER_S2_REJECTION"}
    else:
        replay_validation = _replay_v2_summary(
            base,
            spec.get("replay_validation"),
            split="VALIDATION",
            candidate=candidate,
            manifest=validation_manifest,
        )
        qualification = _qualification_dashboard(
            base, spec.get("qualification"), validation=replay_validation
        )
        if spec.get("sealed_replay_holdout") in (None, ""):
            if final_verdict != "PROMOTE_S2_NEEDS_LIVE_TEST":
                raise DashboardError("PROMOTE_S2 requires the sealed holdout")
            sealed_holdout = {
                "available": False,
                "split": "FINAL_HOLDOUT",
                "episodes": 0,
                "status": "NOT_RUN",
            }
            if spec.get("sealed_holdout_receipt") not in (None, ""):
                raise DashboardError("sealed receipt exists without a holdout result")
            receipt = {"status": "NOT_RUN"}
        else:
            sealed_holdout = _replay_v2_summary(
                base,
                spec.get("sealed_replay_holdout"),
                split="FINAL_HOLDOUT",
                candidate=candidate,
                manifest=holdout_manifest,
            )
            receipt = _receipt_dashboard(
                base,
                spec.get("sealed_holdout_receipt"),
                holdout=sealed_holdout,
                holdout_manifest=holdout_manifest,
                qualification=qualification,
                candidate=candidate,
            )

    bucket_analysis = _second_bucket_analysis(
        incumbent_dashboard_spec.parent if rejected_s2 else base,
        spec.get("second_bucket_analysis"),
    )
    if rejected_s2:
        if (
            not bucket_analysis.get("available")
            or bucket_analysis.get("status") != "COMPLETE"
            or bucket_analysis.get("hero_hashes")
            != [candidate.get("verified_tree_sha256")]
        ):
            raise DashboardError(
                "KEEP_S1 requires the exact-current completed second-bucket analysis"
            )
    mechanics = _mechanics_dashboard(base, spec.get("mechanics"), strict=True)
    operational_provenance = _v2_operational_provenance(
        base, spec.get("operational_provenance")
    )
    if not rejected_s2:
        linux_rows = [
            row
            for key, row in operational_provenance.items()
            if "linux" in str(key).lower() and isinstance(row, Mapping)
        ]
        if not linux_rows:
            if final_verdict != "PROMOTE_S2_NEEDS_LIVE_TEST":
                raise DashboardError("PROMOTE_S2 requires S2 Linux/x86_64 certification")
            operational_provenance["s2_linux_x86_64"] = {"status": "NOT_RUN"}
        else:
            for linux in linux_rows:
                if (
                    linux.get("status") != "PASS"
                    or not str(linux.get("platform") or "").startswith("Linux")
                    or linux.get("machine") != "x86_64"
                    or linux.get("archive_sha256") != candidate.get("package_sha256")
                    or linux.get("evaluated_tree_sha256")
                    != candidate.get("verified_tree_sha256")
                    or _integer(linux.get("s2_enabled_games"))
                    != _integer(linux.get("games"))
                    or min(
                        _integer((linux.get("actual_order_games") or {}).get(order))
                        for order in ORDERS
                    )
                    < 1
                ):
                    raise DashboardError("S2 Linux/x86_64 certification is invalid")
    elif any(
        "s2" in str(key).lower() and "linux" in str(key).lower()
        for key in operational_provenance
    ):
        raise DashboardError("rejected S2 dashboard cannot claim S2 Linux certification")
    elif rejected_s2:
        operational_provenance["s2_linux_x86_64"] = {
            "status": "NOT_APPLICABLE_AFTER_S2_REJECTION"
        }

    weak_clones = _weak_clones_dashboard(spec.get("weak_clones"), strict=True)
    clone_names = [str(row.get("name")) for row in weak_clones]
    if (
        len(clone_names) != len(set(clone_names))
        or set(clone_names) != WEAK_CLONE_NAMES
    ):
        raise DashboardError(
            "weak_clones must cover each known weak clone exactly once"
        )
    operational = _operational(strength["operational_cells"])
    return {
        "schema": SCHEMA_V2,
        "spec_path": str(spec_path),
        "spec_sha256": sha256_file(spec_path),
        "candidate": candidate,
        "provenance": dict(_optional_mapping(spec.get("provenance"), "provenance")),
        "strength_source": strength["source"],
        "stage_verdicts": strength["stage_verdicts"],
        "candidate_vs_s1": strength["candidate_vs_s1"],
        "strong_anchors": strength["anchors"],
        "same_deck": strength["same_deck"],
        "same_deck_provenance": strength["same_deck_provenance"],
        "replay_validation": replay_validation,
        "sealed_replay_holdout": sealed_holdout,
        "replay_manifests": manifests,
        "qualification": qualification,
        "sealed_holdout_receipt": receipt,
        "second_bucket_analysis": bucket_analysis,
        "mechanics": mechanics,
        "weak_clones": weak_clones,
        "operational_provenance": operational_provenance,
        "operational": operational,
        "final_verdict": final_verdict,
        "score_contract": {
            "single_magic_score": False,
            "anchor_macro": strength["anchors"]["anchor_macro"],
            "anchor_sample_weighted": strength["anchors"]["anchor_sample_weighted"],
            "anchor_actual_first": strength["anchors"]["anchor_actual_first"],
            "anchor_actual_second": strength["anchors"]["anchor_actual_second"],
            "robust_anchor": strength["anchors"]["robust_anchor"],
        },
    }


def build_dashboard(spec_path: Path) -> dict[str, Any]:
    spec_path = spec_path.resolve()
    spec = _load(spec_path)
    schema = spec.get("dashboard_schema", SCHEMA)
    if schema == SCHEMA_V2:
        return _build_dashboard_v2(spec_path, spec)
    if schema != SCHEMA:
        raise DashboardError(f"unsupported dashboard_schema {schema!r}")
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
    clone_rows = _weak_clones_dashboard(spec.get("weak_clones"), strict=False)
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
        *(
            [f"Runtime tree SHA-256: `{candidate.get('verified_runtime_tree_sha256')}`"]
            if candidate.get("verified_runtime_tree_sha256")
            else []
        ),
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
    stage_verdicts = dashboard.get("stage_verdicts")
    if isinstance(stage_verdicts, Mapping):
        lines.append(
            "- Stages: "
            + ", ".join(
                f"{name}={verdict}" for name, verdict in stage_verdicts.items()
            )
            + "."
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
        if replay.get("available"):
            for label in REPLAY_LABELS:
                lines.append(
                    f"  - {label}: {_percent((replay.get('rates') or {}).get(label))}"
                )
            exploratory = replay.get("s2_exploratory_safety_veto")
            if isinstance(exploratory, Mapping):
                lines.append(
                    "  - S2 exploratory set: safety veto only; no efficacy credit; "
                    f"{exploratory.get('decision_count', 0)} decisions."
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
    if dashboard.get("schema") == SCHEMA_V2:
        lines.extend(
            [
                f"Qualification: {dashboard.get('qualification', {}).get('status')}; "
                f"sealed receipt: {dashboard.get('sealed_holdout_receipt', {}).get('status')}.",
                "Weak clones: "
                + ", ".join(
                    f"{row.get('name')} ({row.get('runnable_status', row.get('availability', 'unknown'))})"
                    for row in dashboard.get("weak_clones", [])
                )
                + ".",
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
            *(
                ["", f"Final verdict: **{dashboard.get('final_verdict')}**."]
                if dashboard.get("final_verdict")
                else []
            ),
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
