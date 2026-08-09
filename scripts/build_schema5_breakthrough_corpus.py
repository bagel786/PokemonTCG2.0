#!/usr/bin/env python3
"""Build leak-resistant schema-5 streams for M0 teachers and policy clones."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from training.lucario_data import deterministic_gzip_text, sha256_file

FEATURE_VERSION = 5
AR_SEKKAT = 55327371
CAPPA = 55325981
AJAY = 55308008
NISHIMATSU = 55312662
WATER_JOE = 55321109
TREECKO = 55316998
POLICY_IDENTITY_HOLDOUTS = {AJAY, TREECKO}
CLONE_SOURCES = {AJAY, TREECKO, WATER_JOE, CAPPA}
DAILY_TEACHERS = (
    "matsurih",
    "Sixth Sense",
    "Yaroslav",
    "less",
    "Oshbocker",
    "@kdcyberdude",
)
PRIMARY_DAILY_TEACHER = "matsurih"


def read_rows(path: Path):
    if not path.exists():
        raise FileNotFoundError(path)
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if int(row.get("features", {}).get("feature_version", -1)) != FEATURE_VERSION:
                raise ValueError(
                    f"non-schema-5 row in {path}: {row.get('features', {}).get('feature_version')}"
                )
            yield row


def episode_key(row: dict) -> str:
    return str(row["episode_id"])


def chronological_split(rows: list[dict], holdout_fraction: float = 0.20) -> tuple[list[dict], list[dict]]:
    episodes = sorted({episode_key(row) for row in rows}, key=lambda value: int(value) if value.isdigit() else value)
    if len(episodes) < 2:
        raise ValueError("a policy source needs at least two episodes for an untouched split")
    count = max(1, round(len(episodes) * holdout_fraction))
    holdout = set(episodes[-count:])
    return ([row for row in rows if episode_key(row) not in holdout],
            [row for row in rows if episode_key(row) in holdout])


def episode_balance(rows: list[dict]) -> list[dict]:
    counts = Counter(episode_key(row) for row in rows)
    episode_count = len(counts)
    if not episode_count:
        return []
    # Mean row weight stays one, but each complete episode has equal total influence.
    scale = len(rows) / episode_count
    result = []
    for original in rows:
        row = dict(original)
        row["sample_weight"] = scale / counts[episode_key(row)]
        result.append(row)
    return result


def actual_order(row: dict) -> str:
    value = row.get("actual_order")
    if value in {"first", "second"}:
        return value
    first_player = row.get("first_player")
    if first_player is None:
        # Fail closed: order-conditioned teachers may never infer order from physical seat.
        return "unknown"
    return "first" if int(first_player) == int(row["seat"]) else "second"


def write_stream(path: Path, rows: list[dict], split: str, family: str) -> dict:
    seen = set()
    ordered = []
    for original in sorted(rows, key=lambda row: (episode_key(row), int(row["seat"]), int(row["step"]))):
        key = (episode_key(original), int(original["seat"]), int(original["step"]))
        if key in seen:
            raise RuntimeError(f"duplicate decision in {family}/{split}: {key}")
        seen.add(key)
        row = dict(original)
        row["split"] = split
        row["candidate_family"] = family
        ordered.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    with deterministic_gzip_text(path) as handle:
        for row in ordered:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    return {
        "path": str(path.resolve()),
        "rows": len(ordered),
        "episodes": len({episode_key(row) for row in ordered}),
        "wins": sum(float(row.get("reward", 0)) > 0 for row in ordered),
        "losses": sum(float(row.get("reward", 0)) <= 0 for row in ordered),
        "actual_order": dict(Counter(actual_order(row) for row in ordered)),
        "sha256": sha256_file(path),
    }


def source_name(row: dict) -> str:
    return str(row.get("source_team") or row.get("team") or "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily", default="data/grim_daily_v5_causal/shards/2026-08-06.jsonl.gz")
    parser.add_argument("--live-root", default="artifacts/live_grim_corpus_v5_causal")
    parser.add_argument("--flg-variant", default="artifacts/flg_grim_corpus_v5_causal/submission_55290684.jsonl.gz")
    parser.add_argument("--output-root", default="data/grim_breakthrough_v5")
    args = parser.parse_args()
    output = ROOT / args.output_root
    live_root = ROOT / args.live_root

    teacher_lookup = {teacher.casefold(): teacher for teacher in DAILY_TEACHERS}
    daily_by_teacher = {teacher: [] for teacher in DAILY_TEACHERS}
    flg_rows = []
    for row in read_rows(ROOT / args.daily):
        normalized = source_name(row).strip().casefold()
        teacher = teacher_lookup.get(normalized)
        if teacher is not None:
            daily_by_teacher[teacher].append(row)
        if normalized == "flg":
            flg_rows.append(row)
    missing_daily = [name for name, rows in daily_by_teacher.items() if not rows]
    if missing_daily:
        raise RuntimeError(f"August 6 schema-5 shard is missing current teacher sources: {missing_daily}")

    live: dict[int, list[dict]] = {}
    for submission_id in (AR_SEKKAT, CAPPA, AJAY, NISHIMATSU, WATER_JOE, TREECKO):
        rows = list(read_rows(live_root / f"submission_{submission_id}.jsonl.gz"))
        if not rows or {int(row.get("source_submission_id", -1)) for row in rows} != {submission_id}:
            raise RuntimeError(f"source identity mismatch for submission {submission_id}")
        live[submission_id] = rows
    flg_variant_path = ROOT / args.flg_variant
    flg_variant = list(read_rows(flg_variant_path)) if flg_variant_path.exists() else []

    train, holdout = {}, {}
    source_rows = {
        **daily_by_teacher,
        **{str(key): value for key, value in live.items()},
        **({"flg_variant_55290684": flg_variant} if flg_variant else {}),
    }
    for name, rows in source_rows.items():
        train[name], holdout[name] = chronological_split(rows)

    # Candidate identity holdouts are never referenced by a candidate-family train stream.
    candidate_sources = {*DAILY_TEACHERS, str(AR_SEKKAT), str(NISHIMATSU), "flg_variant_55290684"}
    if candidate_sources & {str(value) for value in POLICY_IDENTITY_HOLDOUTS}:
        raise AssertionError("policy-identity holdout leaked into candidate source set")

    families = {
        **{f"{teacher.lower().replace(' ', '_').replace('@', 'at_')}_only": train[teacher] for teacher in DAILY_TEACHERS},
        "ar_sekkat_only": train[str(AR_SEKKAT)],
        "primary_first_nishimatsu_second": [
            row for row in train[PRIMARY_DAILY_TEACHER] if actual_order(row) == "first"
        ] + [row for row in train[str(NISHIMATSU)] if actual_order(row) == "second"],
        "source_balanced_mix": [],
    }
    if flg_variant:
        families["flg_variant_only"] = train["flg_variant_55290684"]
    for name, share in ((PRIMARY_DAILY_TEACHER, .60), (str(AR_SEKKAT), .25), (str(NISHIMATSU), .15)):
        balanced = episode_balance(train[name])
        for original in balanced:
            row = dict(original)
            row["sample_weight"] *= share
            families["source_balanced_mix"].append(row)

    manifest = {
        "status": "complete",
        "feature_version": FEATURE_VERSION,
        "split_unit": "whole_episode",
        "qualification_policy": "newest_20_percent_per_source_untouched",
        "planned_flg_source": {
            "status": "variant_submission_recovered" if flg_variant else "unavailable_in_august_6_exact_deck_shard",
            "observed_rows": len(flg_rows),
            "variant_submission_id": 55290684 if flg_variant else None,
            "variant_rows": len(flg_variant),
            "variant_training_policy": "isolated_auxiliary_family_not_exact_deck_primary",
            "substitution": list(DAILY_TEACHERS),
        },
        "candidate_policy_identity_holdouts": sorted(POLICY_IDENTITY_HOLDOUTS),
        "clone_sources": sorted(CLONE_SOURCES),
        "families": {},
        "clones": {},
    }
    for family, rows in families.items():
        weighted = rows if family == "source_balanced_mix" else episode_balance(rows)
        validation = []
        teacher_name = next((
            teacher for teacher in DAILY_TEACHERS
            if family == f"{teacher.lower().replace(' ', '_').replace('@', 'at_')}_only"
        ), None)
        if teacher_name is not None:
            validation = holdout[teacher_name]
        elif family == "ar_sekkat_only":
            validation = holdout[str(AR_SEKKAT)]
        elif family == "primary_first_nishimatsu_second":
            validation = [row for row in holdout[PRIMARY_DAILY_TEACHER] if actual_order(row) == "first"] + [
                row for row in holdout[str(NISHIMATSU)] if actual_order(row) == "second"
            ]
        elif family == "flg_variant_only":
            validation = holdout["flg_variant_55290684"]
        else:
            validation = holdout[PRIMARY_DAILY_TEACHER] + holdout[str(AR_SEKKAT)] + holdout[str(NISHIMATSU)]
        manifest["families"][family] = {
            "train": write_stream(output / "families" / family / "train.jsonl.gz", weighted, "train", family),
            "validation": write_stream(
                output / "families" / family / "validation.jsonl.gz", validation, "validation", family
            ),
        }

    for submission_id in sorted(CLONE_SOURCES):
        family = f"clone_{submission_id}"
        manifest["clones"][str(submission_id)] = {
            "train": write_stream(
                output / "clones" / str(submission_id) / "train.jsonl.gz",
                episode_balance(train[str(submission_id)]), "train", family,
            ),
            "qualification": write_stream(
                output / "clones" / str(submission_id) / "qualification.jsonl.gz",
                holdout[str(submission_id)], "policy_holdout", family,
            ),
        }

    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "flg_episodes": len({episode_key(row) for row in flg_rows}),
        "daily_teacher_episodes": {
            name: len({episode_key(row) for row in rows}) for name, rows in daily_by_teacher.items()
        },
        "families": {key: value["train"]["rows"] for key, value in manifest["families"].items()},
        "clone_sources": sorted(CLONE_SOURCES),
        "manifest": str(manifest_path),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
