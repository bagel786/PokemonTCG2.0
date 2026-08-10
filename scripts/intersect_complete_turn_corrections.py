#!/usr/bin/env python3
"""Intersect independently mined complete-turn correction passes.

The native engine is not fully repeatable across processes.  This utility is
therefore intentionally stricter than the miner's in-process repeat gate: a
training label survives only when every independent pass emitted the exact
same label and complete certification payload.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.lucario_data import deterministic_gzip_text


FROZEN_D842_MODEL_SHA256 = "D842F85ABFC44AF9F41979F91795E22C92C179B62E04D5A0A2F9C734E70AF1C3"
FROZEN_GRIM_DECK_CANONICAL_SHA256 = "C20A8A46F5C635773754F03103652F5C534B13DC622448ED2255A97234C103AF"
CERTIFICATION_WORLDS = 8
ALLOWED_SPLITS = frozenset({"development", "calibration"})

# These are replay/search facts that the miner deliberately excludes from a
# trainable correction.  Search seeds and public observations are permitted;
# opponent identity, rating, and deck knowledge are not.
FORBIDDEN_METADATA_KEYS = frozenset(
    {
        "determinizations",
        "hiddendeck",
        "hiddenhand",
        "hiddenprizes",
        "hiddenstate",
        "opponentarchetype",
        "opponentdeck",
        "opponentdeckcanonicalsha256",
        "opponenthand",
        "opponenthandcards",
        "opponentmatchup",
        "opponentrating",
        "opponentratingbucket",
        "opponentsubmissionid",
        "opponentteam",
        "privatecards",
        "privatestate",
        "submissionid",
    }
)


def canonical_json(value) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def stable_json_id(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest().upper()


def _is_sha256(value) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdefABCDEF" for character in text)


def _refuse_holdout_path(path: str | Path, *, label: str) -> None:
    if "holdout" in str(Path(path)).casefold() or "sealed" in str(Path(path)).casefold():
        raise ValueError(f"refusing sealed/holdout {label}: {path}")


def manifest_path_for(path: str | Path) -> Path:
    return Path(path).with_suffix(".manifest.json")


def decision_coordinate(row: Mapping) -> tuple[str, int, int]:
    episode = row.get("episode_id")
    if episode is None or not str(episode).strip():
        raise ValueError("correction row is missing episode_id")
    if row.get("seat") is None or row.get("step") is None:
        raise ValueError(f"correction row {episode!r} is missing seat or step")
    return str(episode), int(row["seat"]), int(row["step"])


def expected_decision_id(row: Mapping) -> str:
    episode, seat, step = decision_coordinate(row)
    return stable_json_id({"episode": episode, "seat": seat, "step": step})


def expected_record_id(row: Mapping) -> str:
    episode, seat, step = decision_coordinate(row)
    return stable_json_id(
        {
            "split": str(row.get("split")),
            "episode_id": episode,
            "hero_seat": seat,
            "replay_step_t": step,
            "semantic_pair_id": str(row.get("semantic_pair_id") or ""),
        }
    )


def _walk_forbidden_metadata(value, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = "".join(character for character in str(raw_key).casefold() if character.isalnum())
            if key in FORBIDDEN_METADATA_KEYS:
                location = ".".join((*path, str(raw_key)))
                raise ValueError(f"hidden or identity metadata is forbidden in correction row: {location}")
            _walk_forbidden_metadata(child, (*path, str(raw_key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_forbidden_metadata(child, (*path, str(index)))


def _comparison(world: Mapping) -> int:
    try:
        baseline = tuple(float(value) for value in world["baseline"])
        candidate = tuple(float(value) for value in world["candidate"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid public certification vector") from exc
    if not baseline or len(baseline) != len(candidate):
        raise ValueError("baseline/candidate certification vectors have unequal coverage")
    if not all(math.isfinite(value) for value in (*baseline, *candidate)):
        raise ValueError("certification vectors contain non-finite values")
    return (candidate > baseline) - (candidate < baseline)


def validate_row(row: dict, manifest: Mapping) -> None:
    required = (
        "action",
        "baseline_semantic_id",
        "candidate_semantic_id",
        "correction",
        "correction_record_id",
        "decision_id",
        "episode_id",
        "features",
        "observation",
        "proposers",
        "semantic_action_pair_id",
        "semantic_pair_id",
        "source",
        "split",
        "seat",
        "step",
    )
    missing = [name for name in required if row.get(name) is None]
    if missing:
        raise ValueError(f"correction row is missing required fields: {','.join(missing)}")
    _walk_forbidden_metadata(row)
    if row["source"] != "complete_turn_multi_policy_correction":
        raise ValueError(f"unknown correction source: {row['source']!r}")
    if str(row["split"]) not in ALLOWED_SPLITS:
        raise ValueError(f"refusing sealed or unknown correction split: {row['split']!r}")
    if str(row.get("actual_order")) not in {"first", "second"}:
        raise ValueError("correction row has missing or unknown actual_order")

    decision_id = str(row["decision_id"]).upper()
    record_id = str(row["correction_record_id"]).upper()
    if decision_id != expected_decision_id(row):
        raise ValueError(f"decision identity mismatch for correction {record_id}")
    if record_id != expected_record_id(row):
        raise ValueError(f"record identity mismatch for correction {record_id}")

    observation_sha256 = stable_json_id(row["observation"])
    expected_pair = stable_json_id(
        {
            "observation_sha256": observation_sha256,
            "baseline_semantic_id": str(row["baseline_semantic_id"]),
            "candidate_semantic_id": str(row["candidate_semantic_id"]),
        }
    )
    if str(row["semantic_pair_id"]).upper() != expected_pair:
        raise ValueError(f"observation-bound semantic identity mismatch for {record_id}")
    for name in (
        "baseline_semantic_id",
        "candidate_semantic_id",
        "semantic_pair_id",
        "semantic_action_pair_id",
    ):
        if not _is_sha256(row[name]):
            raise ValueError(f"invalid {name} for correction {record_id}")

    proposers = list(map(str, row["proposers"]))
    if not proposers or proposers != sorted(set(proposers)):
        raise ValueError(f"non-canonical proposer provenance for correction {record_id}")
    try:
        action = [int(index) for index in row["action"]]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid correction action for {record_id}") from exc
    if any(index < 0 for index in action) or action != row["action"]:
        raise ValueError(f"invalid correction action for {record_id}")

    correction = row["correction"]
    if not isinstance(correction, dict):
        raise ValueError(f"invalid certification payload for {record_id}")
    config = manifest["config"]
    expected_worlds = int(config["worlds"])
    expected_repeats = int(manifest["certification_repeats"])
    decision = correction.get("decision") or {}
    coverage = correction.get("coverage") or {}
    worlds = correction.get("worlds") or []
    comparisons = correction.get("per_world_comparisons") or []
    repeated_vectors = correction.get("per_world_vectors") or []
    actual_comparisons = [_comparison(world) for world in worlds]
    if (
        correction.get("teacher") != "equal_coverage_complete_current_turn_v1"
        or correction.get("baseline") != "frozen_d842"
        or str(correction.get("baseline_model_sha256") or "").upper()
        != str(manifest["model_sha256"]).upper()
        or str(correction.get("anchor_sha256") or "").upper()
        != str(manifest["model_sha256"]).upper()
        or str(correction.get("anchor_behavior_sha256") or "").upper()
        != str(manifest["model_behavior_sha256"]).upper()
        or int(correction.get("certification_repeat_count", 0)) != expected_repeats
        or correction.get("coverage_complete") is not True
        or correction.get("all_worlds_nonnegative") is not True
        or correction.get("errors") != []
        or decision.get("admitted") is not True
        or decision.get("reason") != "admitted"
        or int(decision.get("expected_worlds", 0)) != expected_worlds
        or int(decision.get("covered_worlds", 0)) != expected_worlds
        or int(decision.get("noninferior_worlds", 0)) != expected_worlds
        or int(decision.get("required_strict_worlds", 0)) != math.ceil(expected_worlds / 2)
        or int(coverage.get("baseline", 0)) != expected_worlds
        or int(coverage.get("candidate", 0)) != expected_worlds
        or len(worlds) != expected_worlds
        or [int(value) for value in comparisons] != actual_comparisons
        or repeated_vectors != worlds
        or [int(world.get("lexicographic_comparison", 99)) for world in worlds]
        != actual_comparisons
        or any(value < 0 for value in actual_comparisons)
        or sum(value > 0 for value in actual_comparisons) < math.ceil(expected_worlds / 2)
        or int(correction.get("strict_better_worlds", -1))
        != sum(value > 0 for value in actual_comparisons)
        or int(decision.get("strict_better_worlds", -1))
        != sum(value > 0 for value in actual_comparisons)
    ):
        raise ValueError(f"incomplete or inconsistent certification payload for {record_id}")
    world_indices = [int(world.get("world_index", -1)) for world in worlds]
    if world_indices != list(range(expected_worlds)):
        raise ValueError(f"non-canonical certification world coverage for {record_id}")
    signature = str(correction.get("certification_signature") or "").upper()
    boundary_hash = str(correction.get("public_boundary_hash") or "")
    if not _is_sha256(signature) or not _is_sha256(boundary_hash):
        raise ValueError(f"invalid certification signature/boundary hash for {record_id}")


@dataclass(frozen=True)
class CorrectionPass:
    path: Path
    sha256: str
    manifest_path: Path
    manifest_sha256: str
    manifest: dict
    rows: dict[str, dict]
    decisions: dict[tuple[str, int, int], str]


def load_pass(path: str | Path) -> CorrectionPass:
    path = Path(path).resolve()
    _refuse_holdout_path(path, label="correction input")
    if not path.is_file():
        raise FileNotFoundError(path)
    manifest_path = manifest_path_for(path)
    _refuse_holdout_path(manifest_path, label="correction manifest")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"missing correction manifest: {manifest_path}")
    file_hash = sha256_file(path)
    manifest_hash = sha256_file(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    manifest_output = Path(str(manifest.get("output") or "")).resolve()
    splits = manifest.get("splits")
    config = manifest.get("config")
    if (
        manifest.get("passed") is not True
        or manifest.get("sealed_holdout_used") is not False
        or int(manifest.get("integrity_failures", -1)) != 0
        or int(manifest.get("worker_exceptions", -1)) != 0
        or manifest_output != path
        or str(manifest.get("output_sha256") or "").upper() != file_hash
        or not isinstance(splits, list)
        or not splits
        or not set(map(str, splits)) <= ALLOWED_SPLITS
        or not isinstance(config, dict)
        or int(config.get("worlds", 0)) != CERTIFICATION_WORLDS
        or int(manifest.get("certification_repeats", 0)) < 3
        or int(manifest.get("certification_repeats", 0))
        != int(config.get("certification_repeats", manifest.get("certification_repeats", 0)))
        or str(manifest.get("model_sha256") or "").upper() != FROZEN_D842_MODEL_SHA256
        or str(manifest.get("hero_deck_canonical_sha256") or "").upper()
        != FROZEN_GRIM_DECK_CANONICAL_SHA256
        or not _is_sha256(manifest.get("model_behavior_sha256"))
        or not _is_sha256(manifest.get("input_sha256"))
    ):
        raise ValueError(f"correction manifest failed integrity checks: {manifest_path}")
    for protected_path in (manifest.get("input"), manifest.get("model"), manifest.get("hero_deck")):
        if protected_path:
            _refuse_holdout_path(protected_path, label="manifest provenance path")

    rows: dict[str, dict] = {}
    decisions: dict[tuple[str, int, int], str] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            validate_row(row, manifest)
            record_id = str(row["correction_record_id"]).upper()
            coordinate = decision_coordinate(row)
            if record_id in rows:
                raise ValueError(f"duplicate correction_record_id in {path}:{line_number}: {record_id}")
            if coordinate in decisions:
                raise ValueError(
                    "multiple labels for episode-seat-step in "
                    f"{path}:{line_number}: {coordinate}"
                )
            rows[record_id] = row
            decisions[coordinate] = record_id

    if len(rows) != int(manifest.get("admitted_corrections", -1)):
        raise ValueError(f"manifest row count mismatch: {path}")
    declared_signatures = manifest.get("admitted_certification_signatures")
    actual_signatures = {
        record_id: str(row["correction"]["certification_signature"]).upper()
        for record_id, row in sorted(rows.items())
    }
    if not isinstance(declared_signatures, dict) or {
        str(key).upper(): str(value).upper() for key, value in declared_signatures.items()
    } != actual_signatures:
        raise ValueError(f"manifest certification signature map mismatch: {path}")
    return CorrectionPass(
        path=path,
        sha256=file_hash,
        manifest_path=manifest_path,
        manifest_sha256=manifest_hash,
        manifest=manifest,
        rows=rows,
        decisions=decisions,
    )


def _provenance(pass_: CorrectionPass) -> dict:
    manifest = pass_.manifest
    # Outcome-dependent fields (admission counts, reasons, and repeat digest)
    # are intentionally absent.  Everything governing which work was run and
    # how it was certified must match exactly.
    return {
        "source_input_sha256": str(manifest["input_sha256"]).upper(),
        "model_sha256": str(manifest["model_sha256"]).upper(),
        "model_behavior_sha256": str(manifest["model_behavior_sha256"]).upper(),
        "hero_deck_canonical_sha256": str(manifest["hero_deck_canonical_sha256"]).upper(),
        "splits": sorted(map(str, manifest["splits"])),
        "shard_index": int(manifest.get("shard_index", 0)),
        "shard_count": int(manifest.get("shard_count", 1)),
        "selected_records": int(manifest.get("selected_records", -1)),
        "decision_boundaries_evaluated": int(manifest.get("decision_boundaries_evaluated", -1)),
        "certification_repeats": int(manifest["certification_repeats"]),
        "config": manifest["config"],
    }


def _semantic_provenance(row: Mapping) -> dict:
    """All label/state provenance outside the stochastic certification payload."""
    return {key: value for key, value in row.items() if key != "correction"}


def _family_values(row: Mapping) -> list[str]:
    values: list[str] = []
    for key in ("family", "rule_family", "intervention_family", "reason_family"):
        value = row.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            values.extend(map(str, value))
        else:
            values.append(str(value))
    return sorted(set(value for value in values if value))


def intersect_passes(passes: Sequence[CorrectionPass]) -> tuple[list[dict], dict]:
    if len(passes) < 2:
        raise ValueError("at least two independent correction passes are required")
    reference_provenance = _provenance(passes[0])
    reference_provenance_json = canonical_json(reference_provenance)
    for pass_ in passes[1:]:
        if canonical_json(_provenance(pass_)) != reference_provenance_json:
            raise ValueError(
                "correction pass source/model/deck/world/repeat/config provenance mismatch: "
                f"{pass_.path}"
            )

    all_record_ids = sorted(set().union(*(pass_.rows for pass_ in passes)))
    retained: list[dict] = []
    drop_reasons: Counter[str] = Counter()
    for record_id in all_record_ids:
        present = [pass_.rows.get(record_id) for pass_ in passes]
        if any(row is None for row in present):
            coordinates = {
                decision_coordinate(row) for row in present if row is not None
            }
            if len(coordinates) != 1:
                raise ValueError(f"record {record_id} maps to conflicting decision identities")
            coordinate = next(iter(coordinates))
            if all(coordinate in pass_.decisions for pass_ in passes):
                drop_reasons["decision_label_mismatch"] += 1
            else:
                drop_reasons["not_present_in_every_pass"] += 1
            continue

        rows = [row for row in present if row is not None]
        semantic_payloads = {canonical_json(_semantic_provenance(row)) for row in rows}
        if len(semantic_payloads) != 1:
            raise ValueError(f"semantic provenance mismatch for correction {record_id}")
        certification_payloads = {canonical_json(row["correction"]) for row in rows}
        if len(certification_payloads) != 1:
            drop_reasons["certification_payload_or_signature_mismatch"] += 1
            continue
        complete_rows = {canonical_json(row) for row in rows}
        if len(complete_rows) != 1:
            # Defensive: semantic + correction equality should imply this.
            raise ValueError(f"complete label mismatch for correction {record_id}")
        retained.append(rows[0])

    retained.sort(key=lambda row: str(row["correction_record_id"]).upper())
    coordinates: dict[tuple[str, int, int], str] = {}
    for row in retained:
        coordinate = decision_coordinate(row)
        record_id = str(row["correction_record_id"]).upper()
        if coordinate in coordinates:
            raise ValueError(f"intersected output has multiple labels for {coordinate}")
        coordinates[coordinate] = record_id

    order = Counter(str(row["actual_order"]) for row in retained)
    proposers = Counter(
        proposer
        for row in retained
        for proposer in sorted(set(map(str, row.get("proposers") or [])))
    )
    families = Counter(family for row in retained for family in _family_values(row))
    coverage = {
        "episodes": len({str(row["episode_id"]) for row in retained}),
        "decision_boundaries": len(retained),
        "by_actual_order": dict(sorted(order.items())),
        "by_proposer": dict(sorted(proposers.items())),
    }
    if families:
        coverage["by_family"] = dict(sorted(families.items()))
    counts = {
        "input_passes": len(passes),
        "union_correction_records": len(all_record_ids),
        "retained_corrections": len(retained),
        "dropped_correction_records": sum(drop_reasons.values()),
        "input_rows": [len(pass_.rows) for pass_ in passes],
    }
    if counts["retained_corrections"] + counts["dropped_correction_records"] != counts[
        "union_correction_records"
    ]:
        raise AssertionError("intersection accounting is inconsistent")
    return retained, {
        "provenance": reference_provenance,
        "counts": counts,
        "drop_reasons": dict(sorted(drop_reasons.items())),
        "coverage": coverage,
    }


def run(inputs: Iterable[str | Path], output: str | Path) -> dict:
    output = Path(output).resolve()
    _refuse_holdout_path(output, label="correction output")
    input_paths = sorted({Path(path).resolve() for path in inputs}, key=lambda path: str(path).casefold())
    if len(input_paths) < 2:
        raise ValueError("at least two distinct correction pass paths are required")
    if output in input_paths:
        raise ValueError("output must not overwrite an input correction pass")
    passes = [load_pass(path) for path in input_paths]
    retained, report = intersect_passes(passes)

    output.parent.mkdir(parents=True, exist_ok=True)
    with deterministic_gzip_text(output) as handle:
        for row in retained:
            handle.write(canonical_json(row) + "\n")
    manifest = {
        "schema_version": 1,
        "status": "complete",
        "passed": True,
        "source": "exact_multi_pass_complete_turn_intersection",
        "sealed_holdout_used": False,
        "inputs": [
            {
                "file": str(pass_.path),
                "sha256": pass_.sha256,
                "manifest": str(pass_.manifest_path),
                "manifest_sha256": pass_.manifest_sha256,
                "rows": len(pass_.rows),
            }
            for pass_ in passes
        ],
        **report,
        "output": str(output),
        "output_sha256": sha256_file(output),
    }
    manifest_path = manifest_path_for(output)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = run(args.inputs, args.output)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
