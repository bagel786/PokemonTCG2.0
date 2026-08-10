#!/usr/bin/env python3
"""One-shot, fail-closed final proxy evaluation for the Grim d842 successor.

This is the only code path allowed to open the ``untouched_holdout`` shard.
It deliberately sits above the ordinary disagreement builder and correction
miner, both of which hard-refuse that split.  Before opening the shard it
requires a self-hashed candidate freeze, re-verifies the passing calibration
gate, binds the fixed legacy proposer packages, and writes an exclusive unseal
receipt.  The candidate is never used to propose labels.

The sealed run then:

* loads every whole-episode unit in the untouched shard and proves that no
  episode/grouping atom occurs in development or calibration;
* calls the existing replay disagreement miner with the frozen d842 baseline
  and the repository's fixed ``DEFAULT_CANDIDATES`` proposer set;
* performs two fresh-process complete-turn certification passes;
* calls the existing exact intersection implementation and validates that all
  emitted label rows contain public data only; and
* calls ``evaluate_grim_proxy_gate.run`` with the explicit
  ``expected_split='untouched_holdout'`` authorization.

There is intentionally no resume, overwrite, alternate-proposer, or candidate
proposal option.  A failed run consumes the seal and records an immutable
failure result.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import build_grim_policy_disagreements as disagreements
from scripts import evaluate_grim_proxy_gate as proxy_gate
from scripts import intersect_complete_turn_corrections as correction_intersection
from scripts import mine_complete_turn_disagreements as correction_miner
from training.complete_turn_corrections import CorrectionConfig


SCHEMA_VERSION = 1
FREEZE_KIND = "grim_d842_candidate_freeze"
RUN_KIND = "grim_d842_sealed_holdout_proxy"
UNSEAL_KIND = "grim_d842_untouched_holdout_unseal"
HOLDOUT_SPLIT = "untouched_holdout"
NON_HOLDOUT_SPLITS = ("development", "calibration")
ALL_SPLITS = (*NON_HOLDOUT_SPLITS, HOLDOUT_SPLIT)
CERTIFICATION_PASSES = 2
CERTIFICATION_WORLDS = 8
DEFAULT_BANK = ROOT / "artifacts" / "grim_5k_training_bank"
DEFAULT_REPLAY_ROOT = ROOT / "artifacts" / "grim_5k_history" / "replays"
DEFAULT_REFERENCE = ROOT / "grimmsnarl_5k_reference.tar.gz"
DEFAULT_MODEL = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"
DEFAULT_HERO_DECK = (
    ROOT / "artifacts" / "recovery_probes" / "extracted" / "control" / "deck.csv"
)
DEFAULT_OUTPUT = ROOT / "artifacts" / "grim_sealed_holdout"
FIXED_PROPOSER_NAMES = tuple(spec.name for spec in disagreements.DEFAULT_CANDIDATES)


class SealedHoldoutError(RuntimeError):
    """A final-proxy invariant failed; no retry with another candidate is valid."""


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def stable_json_id(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest().upper()


def sha256_file(path: str | Path) -> str:
    return correction_intersection.sha256_file(path)


def manifest_path_for(path: str | Path) -> Path:
    return correction_intersection.manifest_path_for(path)


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).resolve()
    value = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {target}")
    return value


def _self_hashed(value: Mapping[str, Any], *, field: str = "manifest_digest_sha256") -> bool:
    declared = str(value.get(field) or "").upper()
    payload = dict(value)
    payload.pop(field, None)
    return declared == stable_json_id(payload)


def with_manifest_digest(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    payload.pop("manifest_digest_sha256", None)
    payload["manifest_digest_sha256"] = stable_json_id(payload)
    return payload


def write_immutable_json(path: str | Path, value: Mapping[str, Any]) -> str:
    """Create a canonical JSON artifact exactly once (idempotent for same bytes)."""

    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    try:
        with target.open("xb") as handle:
            handle.write(payload)
    except FileExistsError:
        if target.read_bytes() != payload:
            raise SealedHoldoutError(f"refusing to overwrite immutable artifact: {target}")
    return hashlib.sha256(payload).hexdigest().upper()


def _artifact_reference(path: str | Path) -> dict[str, str]:
    target = Path(path).resolve()
    if not target.is_file():
        raise FileNotFoundError(target)
    return {"path": str(target), "sha256": sha256_file(target)}


def _verify_artifact_reference(value: Mapping[str, Any], *, label: str) -> Path:
    target = Path(str(value.get("path") or "")).resolve()
    expected = str(value.get("sha256") or "").upper()
    if not target.is_file() or len(expected) != 64 or sha256_file(target) != expected:
        raise ValueError(f"{label} artifact is missing or changed: {target}")
    return target


def _bank_id_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    splits = manifest.get("splits") or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "source_manifest_sha256": manifest.get("source_manifest_sha256"),
        "deck": manifest.get("expected_deck_canonical_sha256"),
        "seed": manifest.get("split_seed"),
        "allowlist": manifest.get("strict_lineage_allowlist"),
        "split_hashes": {
            split: (splits.get(split) or {}).get("shard_sha256") for split in ALL_SPLITS
        },
    }


def _bank_id(manifest: Mapping[str, Any]) -> str:
    # Keep byte compatibility with build_grim_5k_training_bank.py, whose bank
    # identity predates this module and intentionally uses json.dumps' default
    # separators for this one digest.
    encoded = json.dumps(_bank_id_payload(manifest), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


@dataclass(frozen=True)
class BankSeal:
    root: Path
    manifest_path: Path
    manifest_sha256: str
    manifest: dict[str, Any]
    split_artifacts: dict[str, dict[str, str]]

    def freeze_record(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "manifest": str(self.manifest_path),
            "manifest_sha256": self.manifest_sha256,
            "bank_id": str(self.manifest["bank_id"]).upper(),
            "splits": self.split_artifacts,
        }


def inspect_hash_bound_bank(bank_dir: str | Path) -> BankSeal:
    """Validate only bank manifests; the sealed shard is not opened here."""

    root = Path(bank_dir).resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = _read_json(manifest_path)
    splits = manifest.get("splits") or {}
    if (
        int(manifest.get("schema_version", 0)) != SCHEMA_VERSION
        or manifest.get("offline_only") is not True
        or manifest.get("public_only") is not True
        or manifest.get("split_unit") != "whole_episode_team"
        or str(manifest.get("frozen_model_sha256") or "").upper()
        != disagreements.FROZEN_MODEL_SHA256
        or str(manifest.get("expected_deck_canonical_sha256") or "").upper()
        != disagreements.FROZEN_DECK_CANONICAL_SHA256
        or set(splits) != set(ALL_SPLITS)
        or str(manifest.get("bank_id") or "").upper()
        != _bank_id(manifest)
    ):
        raise ValueError("Grim training-bank manifest failed frozen whole-episode checks")

    split_artifacts: dict[str, dict[str, str]] = {}
    for split in ALL_SPLITS:
        declared = splits[split]
        split_manifest_path = root / "manifests" / f"{split}.json"
        split_manifest = _read_json(split_manifest_path)
        untouched = split == HOLDOUT_SPLIT
        if (
            split_manifest != declared
            or int(declared.get("schema_version", 0)) != SCHEMA_VERSION
            or declared.get("split") != split
            or declared.get("untouched") is not untouched
            or declared.get("training_use")
            != ("forbidden_until_final_evaluation" if untouched else "allowed")
            or int(declared.get("units", -1)) <= 0
            or int(declared.get("episodes", -1)) <= 0
        ):
            raise ValueError(f"invalid {split} split manifest")
        shard_name = str(declared.get("shard") or "")
        if not shard_name or Path(shard_name).name != shard_name:
            raise ValueError(f"unsafe {split} shard name")
        shard_path = (root / shard_name).resolve()
        try:
            shard_path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"{split} shard escapes bank root") from exc
        declared_hash = str(declared.get("shard_sha256") or "").upper()
        if len(declared_hash) != 64:
            raise ValueError(f"invalid {split} shard hash")
        # Do not hash/open the shard here.  The main bank manifest is the seal;
        # bytes are checked only after the one-shot unseal receipt is written.
        split_artifacts[split] = {
            "shard": str(shard_path),
            "sha256": declared_hash,
            "manifest": str(split_manifest_path.resolve()),
            "manifest_sha256": sha256_file(split_manifest_path),
        }
    return BankSeal(
        root=root,
        manifest_path=manifest_path.resolve(),
        manifest_sha256=sha256_file(manifest_path),
        manifest=manifest,
        split_artifacts=split_artifacts,
    )


def fixed_proposer_metadata(
    specs: Sequence[disagreements.PackageSpec] = disagreements.DEFAULT_CANDIDATES,
) -> list[dict[str, Any]]:
    if tuple(spec.name for spec in specs) != FIXED_PROPOSER_NAMES:
        raise ValueError("sealed evaluation requires the exact fixed proposer list and order")
    return [disagreements.package_metadata(spec) for spec in specs]


def fixed_proposer_record(metadata: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = [dict(value) for value in metadata]
    names = [str(value.get("name")) for value in values]
    if tuple(names) != FIXED_PROPOSER_NAMES:
        raise ValueError("fixed proposer metadata has a changed name/order")
    if any(value.get("native_search_executed") is not False for value in values):
        raise ValueError("proposal packages must execute with native search disabled")
    return {
        "names": names,
        "metadata": values,
        "digest_sha256": stable_json_id(values),
        "candidate_generated_proposals": False,
    }


def create_candidate_freeze_manifest(
    *,
    candidate_path: str | Path,
    candidate_training_manifest: str | Path,
    training_labels: str | Path,
    anchor_path: str | Path,
    calibration_gate_manifest: str | Path,
    bank_dir: str | Path,
    output_path: str | Path,
    proposer_metadata: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verify and immutably bind everything before the holdout is unsealed."""

    candidate = Path(candidate_path).resolve()
    candidate_manifest = Path(candidate_training_manifest).resolve()
    anchor = Path(anchor_path).resolve()
    calibration = Path(calibration_gate_manifest).resolve()
    training_bank = proxy_gate.load_certified_bank(
        training_labels, expected_split=proxy_gate.TRAINING_SPLIT
    )
    candidate_provenance, training_anchor = proxy_gate.verify_candidate_manifest(
        candidate_manifest,
        candidate_path=candidate,
        training_bank=training_bank,
    )
    model_provenance = proxy_gate.verify_models(anchor, candidate, training_anchor)
    calibration_provenance = proxy_gate._verify_frozen_calibration(
        calibration,
        candidate_sha256=model_provenance["candidate_sha256"],
        candidate_manifest_sha256=candidate_provenance["sha256"],
        training_bank_sha256=training_bank.sha256,
    )
    bank = inspect_hash_bound_bank(bank_dir)
    proposer_values = list(proposer_metadata) if proposer_metadata is not None else fixed_proposer_metadata()
    payload = with_manifest_digest(
        {
            "schema_version": SCHEMA_VERSION,
            "kind": FREEZE_KIND,
            "status": "frozen",
            "immutable": True,
            "candidate": _artifact_reference(candidate),
            "candidate_training_manifest": _artifact_reference(candidate_manifest),
            "training_labels": {
                **_artifact_reference(training_bank.path),
                "manifest": str(training_bank.manifest_path),
                "manifest_sha256": training_bank.manifest_sha256,
            },
            "anchor": _artifact_reference(anchor),
            "calibration_gate": {
                **_artifact_reference(calibration),
                "manifest_digest_sha256": calibration_provenance[
                    "manifest_digest_sha256"
                ],
            },
            "grim_training_bank": bank.freeze_record(),
            "fixed_proposers": fixed_proposer_record(proposer_values),
            "authorization": {
                "evaluation_split": HOLDOUT_SPLIT,
                "certification_passes": CERTIFICATION_PASSES,
                "candidate_may_propose": False,
                "retry_with_alternate_candidate": False,
            },
        }
    )
    write_immutable_json(output_path, payload)
    return payload


@dataclass(frozen=True)
class FrozenCandidate:
    manifest_path: Path
    manifest_sha256: str
    manifest_digest_sha256: str
    candidate_path: Path
    candidate_training_manifest: Path
    training_labels: Path
    anchor_path: Path
    calibration_gate_manifest: Path
    bank: BankSeal
    proposer_metadata: tuple[dict[str, Any], ...]


def verify_candidate_freeze_manifest(
    path: str | Path,
    *,
    proposer_metadata: Sequence[Mapping[str, Any]] | None = None,
) -> FrozenCandidate:
    target = Path(path).resolve()
    manifest = _read_json(target)
    authorization = manifest.get("authorization") or {}
    if (
        int(manifest.get("schema_version", 0)) != SCHEMA_VERSION
        or manifest.get("kind") != FREEZE_KIND
        or manifest.get("status") != "frozen"
        or manifest.get("immutable") is not True
        or not _self_hashed(manifest)
        or authorization.get("evaluation_split") != HOLDOUT_SPLIT
        or int(authorization.get("certification_passes", 0)) != CERTIFICATION_PASSES
        or authorization.get("candidate_may_propose") is not False
        or authorization.get("retry_with_alternate_candidate") is not False
    ):
        raise ValueError("candidate-freeze manifest is not a valid immutable final authorization")

    candidate = _verify_artifact_reference(manifest.get("candidate") or {}, label="candidate")
    candidate_manifest = _verify_artifact_reference(
        manifest.get("candidate_training_manifest") or {}, label="candidate training manifest"
    )
    training_value = manifest.get("training_labels") or {}
    training_labels = _verify_artifact_reference(training_value, label="training labels")
    anchor = _verify_artifact_reference(manifest.get("anchor") or {}, label="frozen anchor")
    calibration_value = manifest.get("calibration_gate") or {}
    calibration = _verify_artifact_reference(calibration_value, label="calibration gate")

    training_bank = proxy_gate.load_certified_bank(
        training_labels, expected_split=proxy_gate.TRAINING_SPLIT
    )
    if (
        Path(str(training_value.get("manifest") or "")).resolve()
        != training_bank.manifest_path
        or str(training_value.get("manifest_sha256") or "").upper()
        != training_bank.manifest_sha256
    ):
        raise ValueError("candidate freeze no longer matches the training-label manifest")
    candidate_provenance, training_anchor = proxy_gate.verify_candidate_manifest(
        candidate_manifest,
        candidate_path=candidate,
        training_bank=training_bank,
    )
    model_provenance = proxy_gate.verify_models(anchor, candidate, training_anchor)
    calibration_provenance = proxy_gate._verify_frozen_calibration(
        calibration,
        candidate_sha256=model_provenance["candidate_sha256"],
        candidate_manifest_sha256=candidate_provenance["sha256"],
        training_bank_sha256=training_bank.sha256,
    )
    if (
        str(calibration_value.get("manifest_digest_sha256") or "").upper()
        != calibration_provenance["manifest_digest_sha256"]
    ):
        raise ValueError("candidate freeze calibration digest mismatch")

    bank_value = manifest.get("grim_training_bank") or {}
    bank = inspect_hash_bound_bank(bank_value.get("root") or "")
    if bank.freeze_record() != bank_value:
        raise ValueError("candidate freeze no longer matches the hash-bound Grim bank")

    proposer_values = list(proposer_metadata) if proposer_metadata is not None else fixed_proposer_metadata()
    proposer_record = fixed_proposer_record(proposer_values)
    if proposer_record != manifest.get("fixed_proposers"):
        raise ValueError("candidate freeze no longer matches the fixed proposer packages")
    return FrozenCandidate(
        manifest_path=target,
        manifest_sha256=sha256_file(target),
        manifest_digest_sha256=str(manifest["manifest_digest_sha256"]).upper(),
        candidate_path=candidate,
        candidate_training_manifest=candidate_manifest,
        training_labels=training_labels,
        anchor_path=anchor,
        calibration_gate_manifest=calibration,
        bank=bank,
        proposer_metadata=tuple(dict(value) for value in proposer_values),
    )


def _load_split_rows_after_unseal(bank: BankSeal, split: str) -> list[dict[str, Any]]:
    if split not in ALL_SPLITS:
        raise ValueError(f"unknown bank split: {split}")
    reference = bank.split_artifacts[split]
    path = Path(reference["shard"])
    if not path.is_file() or sha256_file(path) != reference["sha256"]:
        raise ValueError(f"{split} shard is missing or changed after candidate freeze")
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected an object")
            if (
                row.get("schema_version") != SCHEMA_VERSION
                or row.get("unit_type") != "whole_episode_team"
                or row.get("split") != split
                or row.get("required_labels_complete") is not True
                or str(row.get("frozen_model_sha256") or "").upper()
                != disagreements.FROZEN_MODEL_SHA256
                or str(row.get("hero_deck_canonical_sha256") or "").upper()
                != disagreements.FROZEN_DECK_CANONICAL_SHA256
                or not str(row.get("episode_id") or "").strip()
                or row.get("grouping_key") is None
                or not isinstance(row.get("grouping_atoms"), list)
            ):
                raise ValueError(f"{path}:{line_number}: invalid whole-episode bank row")
            rows.append(row)
    declared = bank.manifest["splits"][split]
    identities = {
        (str(row["episode_id"]), int(row["submission_id"]), int(row["hero_seat"]))
        for row in rows
    }
    if (
        len(identities) != len(rows)
        or len(rows) != int(declared["units"])
        or len({str(row["episode_id"]) for row in rows}) != int(declared["episodes"])
        or len({str(row["grouping_key"]) for row in rows}) != int(declared["grouping_keys"])
    ):
        raise ValueError(f"{split} shard violates declared whole-episode coverage")
    return sorted(
        rows,
        key=lambda row: (str(row["episode_id"]), int(row["submission_id"]), int(row["hero_seat"])),
    )


def load_and_verify_whole_episode_splits(bank: BankSeal) -> dict[str, list[dict[str, Any]]]:
    rows = {split: _load_split_rows_after_unseal(bank, split) for split in ALL_SPLITS}
    episode_sets = {
        split: {str(row["episode_id"]) for row in values} for split, values in rows.items()
    }
    grouping_sets = {
        split: {str(row["grouping_key"]) for row in values} for split, values in rows.items()
    }
    atom_sets = {
        split: {
            str(atom)
            for row in values
            for atom in row.get("grouping_atoms") or []
        }
        for split, values in rows.items()
    }
    for index, left in enumerate(ALL_SPLITS):
        for right in ALL_SPLITS[index + 1 :]:
            overlap = episode_sets[left] & episode_sets[right]
            if overlap:
                raise ValueError(f"episode leakage between {left} and {right}: {sorted(overlap)[:10]}")
            grouping_overlap = grouping_sets[left] & grouping_sets[right]
            if grouping_overlap:
                raise ValueError(
                    f"grouping-key leakage between {left} and {right}: {sorted(grouping_overlap)[:10]}"
                )
            atom_overlap = atom_sets[left] & atom_sets[right]
            if atom_overlap:
                raise ValueError(
                    f"grouping-atom leakage between {left} and {right}: {sorted(atom_overlap)[:10]}"
                )
    return rows


def build_sealed_disagreements(
    *,
    episode_rows: Sequence[Mapping[str, Any]],
    replay_root: Path,
    output_path: Path,
    baseline: disagreements.Policy,
    candidates: Sequence[disagreements.Policy],
) -> dict[str, Any]:
    """Use the existing episode miner while retaining explicit sealed provenance."""

    if tuple(policy.name for policy in candidates) != FIXED_PROPOSER_NAMES:
        raise ValueError("sealed disagreements require exactly the fixed proposer packages")
    if not episode_rows or any(row.get("split") != HOLDOUT_SPLIT for row in episode_rows):
        raise ValueError("sealed disagreement input must contain only untouched-holdout units")
    all_rows: list[dict[str, Any]] = []
    totals: Counter[str] = Counter()
    episode_counts: dict[str, dict[str, int]] = {}
    for episode in sorted(
        episode_rows,
        key=lambda row: (str(row["episode_id"]), int(row["submission_id"]), int(row["hero_seat"])),
    ):
        replay_path = disagreements._row_replay_path(episode, replay_root)
        replay = disagreements.load_json(replay_path)
        mined, metrics = disagreements.mine_episode(episode, replay, baseline, candidates)
        if any(row.get("split") != HOLDOUT_SPLIT for row in mined):
            raise ValueError("disagreement builder changed the sealed split")
        all_rows.extend(mined)
        totals.update(metrics)
        episode_counts[str(episode["episode_id"])] = metrics
    decisions = totals["decisions"]
    if totals["historical_semantic_agreement"] != decisions:
        raise ValueError(
            "sealed replay failed frozen-d842 semantic verification: "
            f"{totals['historical_semantic_agreement']}/{decisions}"
        )
    all_rows.sort(
        key=lambda row: (
            str(row["episode_id"]),
            int(row["replay_step_t"]),
            str(row["candidate_semantic_id"]),
        )
    )
    output_sha = disagreements.deterministic_gzip_jsonl(output_path, all_rows)
    proposer_counts = Counter(name for row in all_rows for name in row["proposers"])
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "allowed_input_splits": [HOLDOUT_SPLIT],
        "holdout_read": True,
        "sealed_holdout_used": True,
        "alignment": "observation_t_to_same_seat_action_t_plus_1",
        "semantic_deduplication": "observation_sha256_plus_candidate_semantic_id",
        "native_search_executed": False,
        "candidate_generated_proposals": False,
        "episodes": len({str(row["episode_id"]) for row in episode_rows}),
        "units": len(episode_rows),
        "decisions": decisions,
        "disagreement_rows": len(all_rows),
        "rows_by_split": {HOLDOUT_SPLIT: len(all_rows)},
        "rows_by_proposer": dict(sorted(proposer_counts.items())),
        "historical_exact_agreement": totals["historical_exact_agreement"],
        "historical_semantic_agreement": totals["historical_semantic_agreement"],
        "strict_historical": True,
        "strict_historical_criterion": "semantic_action_identity_not_temporary_option_index",
        "baseline": dict(baseline.metadata),
        "candidates": [dict(policy.metadata) for policy in candidates],
        "fixed_proposer_names": list(FIXED_PROPOSER_NAMES),
        "output": str(output_path.resolve()),
        "output_file": output_path.name,
        "output_sha256": output_sha,
        "episode_metrics_digest": stable_json_id(dict(sorted(episode_counts.items()))),
    }
    write_immutable_json(output_path.with_name("manifest.json"), manifest)
    return {**manifest, "rows": all_rows}


def _validate_sealed_disagreement_row(row: Mapping[str, Any]) -> None:
    if row.get("split") != HOLDOUT_SPLIT:
        raise ValueError("certification received a non-holdout disagreement")
    # Reuse the ordinary miner's complete row validation under a harmless
    # calibration alias, then independently prove the original holdout ID.
    shadow = json.loads(canonical_json(row))
    shadow["split"] = "calibration"
    shadow["record_id"] = correction_miner._stable_json_id(
        {
            "split": "calibration",
            "episode_id": str(shadow["episode_id"]),
            "hero_seat": int(shadow["hero_seat"]),
            "replay_step_t": int(shadow["replay_step_t"]),
            "semantic_pair_id": str(shadow["semantic_pair_id"]),
        }
    )
    correction_miner.validate_input_row(shadow)
    expected = correction_miner._stable_json_id(
        {
            "split": HOLDOUT_SPLIT,
            "episode_id": str(row["episode_id"]),
            "hero_seat": int(row["hero_seat"]),
            "replay_step_t": int(row["replay_step_t"]),
            "semantic_pair_id": str(row["semantic_pair_id"]),
        }
    )
    if str(row.get("record_id") or "").upper() != expected:
        raise ValueError("sealed disagreement record identity mismatch")


def _evaluate_records_fresh_processes(
    rows: Sequence[dict[str, Any]],
    *,
    model_path: Path,
    hero_deck: Sequence[int],
    config_values: Mapping[str, Any],
    repeats: int,
    workers: int,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    results: list[tuple[dict[str, Any], dict[str, Any]]] = []
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=workers,
        initializer=correction_miner._init_worker,
        initargs=(str(model_path), list(hero_deck), dict(config_values), repeats),
    ) as pool:
        futures = {pool.submit(correction_miner.evaluate_row, row): row for row in rows}
        for future in concurrent.futures.as_completed(futures):
            results.append((futures[future], future.result()))
    return results


EvaluationRunner = Callable[
    [Sequence[dict[str, Any]], Path, Sequence[int], Mapping[str, Any], int, int],
    list[tuple[dict[str, Any], dict[str, Any]]],
]


def run_certification_pass(
    *,
    rows: Sequence[dict[str, Any]],
    disagreement_path: Path,
    model_path: Path,
    hero_deck_path: Path,
    output_path: Path,
    config: CorrectionConfig,
    certification_repeats: int,
    workers: int,
    pass_ordinal: int,
    evaluation_runner: EvaluationRunner | None = None,
) -> dict[str, Any]:
    if certification_repeats < 3:
        raise ValueError("sealed certification requires at least three identical repeats")
    if config.worlds != CERTIFICATION_WORLDS:
        raise ValueError("sealed certification requires exactly eight worlds")
    if workers <= 0:
        raise ValueError("workers must be positive")
    if pass_ordinal not in (1, 2):
        raise ValueError("sealed evaluation requires pass ordinal 1 or 2")
    for row in rows:
        _validate_sealed_disagreement_row(row)
    model_hash = sha256_file(model_path)
    if model_hash != correction_miner.FROZEN_D842_MODEL_SHA256:
        raise ValueError("certification model is not exact frozen d842")
    model_behavior_hash = correction_miner.model_behavior_digest(model_path)
    hero_deck = correction_miner.load_frozen_hero_deck(hero_deck_path)
    config_values = {
        "worlds": config.worlds,
        "max_turn_steps": config.max_turn_steps,
        "timeout_seconds": config.timeout_seconds,
        "seed": config.seed,
        "manual_coin": config.manual_coin,
        "certification_repeats": certification_repeats,
    }
    if evaluation_runner is None:
        results = _evaluate_records_fresh_processes(
            rows,
            model_path=model_path,
            hero_deck=hero_deck,
            config_values={key: value for key, value in config_values.items() if key != "certification_repeats"},
            repeats=certification_repeats,
            workers=workers,
        )
    else:
        results = evaluation_runner(
            rows,
            model_path,
            hero_deck,
            config_values,
            certification_repeats,
            workers,
        )
    expected_sources = {
        correction_miner.stable_key(row): canonical_json(row) for row in rows
    }
    if len(expected_sources) != len(rows):
        raise ValueError("sealed disagreement input contains duplicate record identities")
    returned_sources: dict[str, str] = {}
    for source, result in results:
        key = correction_miner.stable_key(source)
        if key in returned_sources:
            raise ValueError(f"certification returned duplicate result for {key}")
        returned_sources[key] = canonical_json(source)
        if str(result.get("key") or "") != key:
            raise ValueError(f"certification result/source identity mismatch for {key}")
    if returned_sources != expected_sources:
        raise ValueError("certification did not return exact one-to-one input coverage")
    results.sort(key=lambda item: correction_miner.stable_key(item[0]))
    selected, ambiguous = correction_miner.select_unique_corrections(results)
    admitted = [
        correction_miner.correction_output_row(row, result, model_hash, model_behavior_hash)
        for row, result in selected
    ]
    reason_counts = Counter(str(result.get("reason")) for _row, result in results)
    worker_errors = [result for _row, result in results if result.get("worker_error")]
    input_decisions = {correction_miner.decision_key(row) for row in rows}
    admitted_signatures = {
        str(row["correction_record_id"]).upper(): str(
            row["correction"]["certification_signature"]
        ).upper()
        for row in admitted
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "input": str(disagreement_path.resolve()),
        "input_sha256": sha256_file(disagreement_path),
        "output": str(output_path.resolve()),
        "model": str(model_path.resolve()),
        "model_sha256": model_hash,
        "model_behavior_sha256": model_behavior_hash,
        "hero_deck": str(hero_deck_path.resolve()),
        "hero_deck_canonical_sha256": correction_miner.FROZEN_GRIM_DECK_CANONICAL_SHA256,
        "splits": [HOLDOUT_SPLIT],
        "sealed_holdout_used": True,
        "shard_index": 0,
        "shard_count": 1,
        "selected_records": len(rows),
        "decision_boundaries_evaluated": len(input_decisions),
        "certification_repeats": certification_repeats,
        "admitted_corrections": len(admitted),
        "decision_boundaries_with_multiple_admitted_candidates": ambiguous,
        "admitted_certification_signatures": dict(sorted(admitted_signatures.items())),
        "worker_exceptions": len(worker_errors),
        "integrity_failures": len(worker_errors)
        + reason_counts.get("baseline_replay_mismatch", 0),
        "reasons": dict(sorted(reason_counts.items())),
        "independent_pass_ordinal": pass_ordinal,
        "process_isolation": "fresh_process_pool",
        "config": config_values,
    }
    manifest["passed"] = (
        manifest["worker_exceptions"] == 0 and manifest["integrity_failures"] == 0
    )
    for row in admitted:
        proxy_gate._walk_forbidden_metadata(row)
        proxy_gate._validate_certified_row(row, manifest, HOLDOUT_SPLIT)
    if not manifest["passed"]:
        raise SealedHoldoutError(
            f"certification pass {pass_ordinal} failed integrity checks: {manifest['reasons']}"
        )
    disagreements.deterministic_gzip_jsonl(output_path, admitted)
    manifest["output_sha256"] = sha256_file(output_path)
    write_immutable_json(manifest_path_for(output_path), manifest)
    return {**manifest, "rows": admitted}


def create_sealed_intersection(
    pass_results: Sequence[Mapping[str, Any]],
    output_path: str | Path,
) -> dict[str, Any]:
    if len(pass_results) != CERTIFICATION_PASSES:
        raise ValueError("exactly two certification passes are required")
    loaded: list[correction_intersection.CorrectionPass] = []
    for result in pass_results:
        path = Path(str(result["output"])).resolve()
        pass_manifest_path = manifest_path_for(path).resolve()
        manifest = {key: value for key, value in result.items() if key != "rows"}
        rows = list(result.get("rows") or [])
        for row in rows:
            proxy_gate._walk_forbidden_metadata(row)
            proxy_gate._validate_certified_row(row, manifest, HOLDOUT_SPLIT)
        row_map = {str(row["correction_record_id"]).upper(): row for row in rows}
        decisions = {
            correction_intersection.decision_coordinate(row): record_id
            for record_id, row in row_map.items()
        }
        if (
            manifest.get("sealed_holdout_used") is not True
            or manifest.get("splits") != [HOLDOUT_SPLIT]
            or len(row_map) != len(rows)
            or len(decisions) != len(rows)
            or sha256_file(path) != str(manifest.get("output_sha256") or "").upper()
        ):
            raise ValueError("sealed certification pass cannot be intersected")
        loaded.append(
            correction_intersection.CorrectionPass(
                path=path,
                sha256=sha256_file(path),
                manifest_path=pass_manifest_path,
                manifest_sha256=sha256_file(pass_manifest_path),
                manifest=manifest,
                rows=row_map,
                decisions=decisions,
            )
        )
    if len({item.manifest_sha256 for item in loaded}) != CERTIFICATION_PASSES:
        raise ValueError("certification passes are not independent/distinct")
    retained, report = correction_intersection.intersect_passes(loaded)
    if not retained:
        raise SealedHoldoutError("independent certification intersection is empty")
    for row in retained:
        proxy_gate._walk_forbidden_metadata(row)
    output = Path(output_path).resolve()
    disagreements.deterministic_gzip_jsonl(output, retained)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "passed": True,
        "source": "exact_multi_pass_complete_turn_intersection",
        "sealed_holdout_used": True,
        "inputs": [
            {
                "file": str(item.path),
                "sha256": item.sha256,
                "manifest": str(item.manifest_path),
                "manifest_sha256": item.manifest_sha256,
                "rows": len(item.rows),
            }
            for item in loaded
        ],
        **report,
        "output": str(output),
        "output_sha256": sha256_file(output),
    }
    for row in retained:
        proxy_gate._validate_certified_row(row, loaded[0].manifest, HOLDOUT_SPLIT)
    write_immutable_json(manifest_path_for(output), manifest)
    return {**manifest, "rows": retained}


def _exclusive_unseal_receipt(
    *,
    path: Path,
    frozen: FrozenCandidate,
    output_dir: Path,
) -> dict[str, Any]:
    holdout = frozen.bank.split_artifacts[HOLDOUT_SPLIT]
    receipt = with_manifest_digest(
        {
            "schema_version": SCHEMA_VERSION,
            "kind": UNSEAL_KIND,
            "status": "consumed",
            "immutable": True,
            "candidate_freeze_manifest": str(frozen.manifest_path),
            "candidate_freeze_sha256": frozen.manifest_sha256,
            "candidate_freeze_digest_sha256": frozen.manifest_digest_sha256,
            "bank_id": str(frozen.bank.manifest["bank_id"]).upper(),
            "bank_manifest_sha256": frozen.bank.manifest_sha256,
            "holdout_shard_sha256": holdout["sha256"],
            "output_directory": str(output_dir.resolve()),
            "retry_authorized": False,
        }
    )
    if path.exists():
        raise SealedHoldoutError(
            f"untouched holdout seal was already consumed; retries are forbidden: {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
        "utf-8"
    )
    try:
        # Unlike ordinary immutable manifests, equal bytes are not idempotent
        # here: exactly one process may consume the holdout authorization.
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise SealedHoldoutError(
            f"untouched holdout seal was already consumed; retries are forbidden: {path}"
        ) from exc
    return receipt


def run_sealed_holdout(
    *,
    candidate_freeze_manifest: str | Path,
    replay_root: str | Path,
    reference_archive: str | Path,
    search_model: str | Path,
    hero_deck: str | Path,
    output_dir: str | Path,
    unseal_receipt: str | Path | None = None,
    workers: int = max(1, min(8, os.cpu_count() or 1)),
    certification_repeats: int = 3,
    max_turn_steps: int = 64,
    timeout_seconds: float = 30.0,
    seed: int = 20260810,
    bootstrap_samples: int = proxy_gate.BOOTSTRAP_SAMPLES,
    proposer_specs: Sequence[disagreements.PackageSpec] = disagreements.DEFAULT_CANDIDATES,
    evaluation_runner: EvaluationRunner | None = None,
    proxy_runner: Callable[..., dict[str, Any]] = proxy_gate.run,
) -> dict[str, Any]:
    if tuple(spec.name for spec in proposer_specs) != FIXED_PROPOSER_NAMES:
        raise ValueError("sealed run cannot replace or reorder fixed proposers")
    proposer_values = fixed_proposer_metadata(proposer_specs)
    frozen = verify_candidate_freeze_manifest(
        candidate_freeze_manifest, proposer_metadata=proposer_values
    )
    output = Path(output_dir).resolve()
    if output.exists():
        raise SealedHoldoutError(f"sealed output directory already exists: {output}")
    output.mkdir(parents=True)
    receipt_path = (
        Path(unseal_receipt).resolve()
        if unseal_receipt is not None
        else frozen.bank.root / "manifests" / "untouched_holdout.unseal.json"
    )
    receipt = _exclusive_unseal_receipt(
        path=receipt_path,
        frozen=frozen,
        output_dir=output,
    )
    result_path = output / "sealed_holdout_manifest.json"
    try:
        split_rows = load_and_verify_whole_episode_splits(frozen.bank)
        holdout_rows = split_rows[HOLDOUT_SPLIT]
        holdout_episodes = {str(row["episode_id"]) for row in holdout_rows}
        non_holdout_episodes = {
            str(row["episode_id"])
            for split in NON_HOLDOUT_SPLITS
            for row in split_rows[split]
        }
        if holdout_episodes & non_holdout_episodes:
            raise ValueError("whole-episode split overlap survived bank validation")

        disagreement_path = output / "disagreements.jsonl.gz"
        with disagreements.frozen_baseline(Path(reference_archive).resolve()) as baseline:
            policies = [disagreements.LoadedPackagePolicy(spec) for spec in proposer_specs]
            runtime_proposer_values = [dict(policy.metadata) for policy in policies]
            if fixed_proposer_record(runtime_proposer_values) != fixed_proposer_record(
                frozen.proposer_metadata
            ):
                raise ValueError("loaded fixed proposer bytes differ from candidate freeze")
            disagreement_result = build_sealed_disagreements(
                episode_rows=holdout_rows,
                replay_root=Path(replay_root).resolve(),
                output_path=disagreement_path,
                baseline=baseline,
                candidates=policies,
            )
        disagreement_rows = list(disagreement_result.pop("rows"))
        if {str(row["episode_id"]) for row in disagreement_rows} - holdout_episodes:
            raise ValueError("disagreement output contains a non-holdout episode")

        config = CorrectionConfig(
            worlds=CERTIFICATION_WORLDS,
            max_turn_steps=max_turn_steps,
            timeout_seconds=timeout_seconds,
            seed=seed,
        )
        passes = []
        for ordinal in range(1, CERTIFICATION_PASSES + 1):
            passes.append(
                run_certification_pass(
                    rows=disagreement_rows,
                    disagreement_path=disagreement_path,
                    model_path=Path(search_model).resolve(),
                    hero_deck_path=Path(hero_deck).resolve(),
                    output_path=output / f"certification_pass_{ordinal}.jsonl.gz",
                    config=config,
                    certification_repeats=certification_repeats,
                    workers=workers,
                    pass_ordinal=ordinal,
                    evaluation_runner=evaluation_runner,
                )
            )
        intersection_result = create_sealed_intersection(
            passes, output / "certified_intersection.jsonl.gz"
        )
        intersection_rows = list(intersection_result.pop("rows"))
        label_episodes = {str(row["episode_id"]) for row in intersection_rows}
        if label_episodes - holdout_episodes or label_episodes & non_holdout_episodes:
            raise ValueError("certified labels violate whole-episode split isolation")

        proxy_path = output / "proxy_gate.json"
        proxy_result = proxy_runner(
            labels_path=intersection_result["output"],
            training_labels_path=frozen.training_labels,
            anchor_path=frozen.anchor_path,
            candidate_path=frozen.candidate_path,
            candidate_manifest_path=frozen.candidate_training_manifest,
            expected_split=HOLDOUT_SPLIT,
            output_path=proxy_path,
            calibration_gate_manifest=frozen.calibration_gate_manifest,
            bootstrap_samples=bootstrap_samples,
        )
        result = with_manifest_digest(
            {
                "schema_version": SCHEMA_VERSION,
                "kind": RUN_KIND,
                "status": "complete",
                "passed": proxy_result.get("passed") is True,
                "sealed_holdout_used": True,
                "candidate_freeze": {
                    "path": str(frozen.manifest_path),
                    "sha256": frozen.manifest_sha256,
                    "manifest_digest_sha256": frozen.manifest_digest_sha256,
                },
                "unseal_receipt": {
                    "path": str(receipt_path),
                    "sha256": sha256_file(receipt_path),
                    "manifest_digest_sha256": receipt["manifest_digest_sha256"],
                },
                "whole_episode_isolation": {
                    "verified": True,
                    "holdout_units": len(holdout_rows),
                    "holdout_episodes": len(holdout_episodes),
                    "development_calibration_episode_overlap": 0,
                    "development_calibration_grouping_key_overlap": 0,
                    "development_calibration_grouping_atom_overlap": 0,
                },
                "proposals": {
                    "candidate_generated": False,
                    "fixed_names": list(FIXED_PROPOSER_NAMES),
                    "fixed_metadata_digest_sha256": stable_json_id(runtime_proposer_values),
                    "disagreement_file": disagreement_result["output"],
                    "disagreement_sha256": disagreement_result["output_sha256"],
                    "rows": disagreement_result["disagreement_rows"],
                },
                "certification": {
                    "independent_passes": CERTIFICATION_PASSES,
                    "pass_manifest_sha256": [
                        sha256_file(manifest_path_for(item["output"])) for item in passes
                    ],
                    "intersection": intersection_result["output"],
                    "intersection_sha256": intersection_result["output_sha256"],
                    "retained_labels": len(intersection_rows),
                    "hidden_metadata_in_label_rows": 0,
                },
                "proxy_gate": {
                    "path": str(proxy_path),
                    "sha256": sha256_file(proxy_path),
                    "expected_split": HOLDOUT_SPLIT,
                    "passed": proxy_result.get("passed") is True,
                    "manifest_digest_sha256": proxy_result.get("manifest_digest_sha256"),
                },
            }
        )
        write_immutable_json(result_path, result)
        return result
    except Exception as exc:
        failure = with_manifest_digest(
            {
                "schema_version": SCHEMA_VERSION,
                "kind": RUN_KIND,
                "status": "failed",
                "passed": False,
                "sealed_holdout_used": True,
                "candidate_freeze": {
                    "path": str(frozen.manifest_path),
                    "sha256": frozen.manifest_sha256,
                    "manifest_digest_sha256": frozen.manifest_digest_sha256,
                },
                "unseal_receipt": {
                    "path": str(receipt_path),
                    "sha256": sha256_file(receipt_path),
                    "manifest_digest_sha256": receipt["manifest_digest_sha256"],
                },
                "failure": {"type": type(exc).__name__, "message": str(exc)},
            }
        )
        write_immutable_json(result_path, failure)
        raise


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    freeze = subparsers.add_parser("freeze", help="freeze a calibrated candidate before unsealing")
    freeze.add_argument("--candidate", type=Path, required=True)
    freeze.add_argument("--candidate-training-manifest", type=Path, required=True)
    freeze.add_argument("--training-labels", type=Path, required=True)
    freeze.add_argument("--anchor", type=Path, required=True)
    freeze.add_argument("--calibration-gate-manifest", type=Path, required=True)
    freeze.add_argument("--bank-dir", type=Path, default=DEFAULT_BANK)
    freeze.add_argument("--output", type=Path, required=True)

    evaluate = subparsers.add_parser("evaluate", help="consume the seal and run the final proxy once")
    evaluate.add_argument("--candidate-freeze-manifest", type=Path, required=True)
    evaluate.add_argument("--replay-root", type=Path, default=DEFAULT_REPLAY_ROOT)
    evaluate.add_argument("--reference-archive", type=Path, default=DEFAULT_REFERENCE)
    evaluate.add_argument("--search-model", type=Path, default=DEFAULT_MODEL)
    evaluate.add_argument("--hero-deck", type=Path, default=DEFAULT_HERO_DECK)
    evaluate.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    evaluate.add_argument("--unseal-receipt", type=Path)
    evaluate.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 1)))
    evaluate.add_argument("--certification-repeats", type=int, default=3)
    evaluate.add_argument("--max-turn-steps", type=int, default=64)
    evaluate.add_argument("--timeout-seconds", type=float, default=30.0)
    evaluate.add_argument("--seed", type=int, default=20260810)
    evaluate.add_argument("--bootstrap-samples", type=int, default=proxy_gate.BOOTSTRAP_SAMPLES)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "freeze":
        result = create_candidate_freeze_manifest(
            candidate_path=args.candidate,
            candidate_training_manifest=args.candidate_training_manifest,
            training_labels=args.training_labels,
            anchor_path=args.anchor,
            calibration_gate_manifest=args.calibration_gate_manifest,
            bank_dir=args.bank_dir,
            output_path=args.output,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    try:
        result = run_sealed_holdout(
            candidate_freeze_manifest=args.candidate_freeze_manifest,
            replay_root=args.replay_root,
            reference_archive=args.reference_archive,
            search_model=args.search_model,
            hero_deck=args.hero_deck,
            output_dir=args.output_dir,
            unseal_receipt=args.unseal_receipt,
            workers=args.workers,
            certification_repeats=args.certification_repeats,
            max_turn_steps=args.max_turn_steps,
            timeout_seconds=args.timeout_seconds,
            seed=args.seed,
            bootstrap_samples=args.bootstrap_samples,
        )
    except Exception as exc:
        print(json.dumps({"status": "failed", "type": type(exc).__name__, "message": str(exc)}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
