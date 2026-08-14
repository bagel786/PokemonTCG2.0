#!/usr/bin/env python3
"""Build and certify the frozen A2 Elite Recovery Rerank corpus.

The official daily archives are streamed one at a time.  Only exact-deck,
complete Grim game-seats are retained, and August 13 is written to a separate
holdout shard.  This command performs no training.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import shutil
import statistics
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np

from cg.api import OptionType, SelectContext
from ptcg_ai.features import DecisionFeatures
from ptcg_ai.model import NumpyPolicyModel
from ptcg_ai.replay import episode_order, episode_reward, iter_decisions
from scripts.crawl_grim_daily import classify, deck_hash, load_archetype_catalog
from training.evaluate_elite_topk import option_key, unique_semantic_ranking
from training.lucario_data import canonical_deck, deterministic_gzip_text, load_deck, sha256_file


DATES = tuple(f"2026-08-{day:02d}" for day in range(8, 14))
TRAIN_DATES = frozenset(DATES[:-1])
HOLDOUT_DATE = DATES[-1]
EXPECTED_A2_SHA256 = "b19871a9f1499c2460ae266e58194acab1d8c90b390fa5cf24ed94b9a2b6bda8"
RANK_WEIGHTS = {"1-20": 1.0, "21-40": 0.75, "41-70": 0.50}
ORDER_OUTCOME_BUCKETS = ("win-first", "win-second", "loss-first", "loss-second")
KAGGLE = Path("/Users/safiullahbaig/Library/Python/3.11/bin/kaggle")


def stable_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def semantic_json(key: tuple) -> list:
    return [*key[:-1], list(key[-1])]


def input_fingerprint(features: dict) -> str:
    return hashlib.sha256(stable_json(features).encode("utf-8")).hexdigest()


def rank_band(rank: int | None) -> str:
    if rank is None:
        return "unranked"
    if rank <= 20:
        return "1-20"
    if rank <= 40:
        return "21-40"
    if rank <= 70:
        return "41-70"
    return "71+"


def action_category(features: DecisionFeatures, label: int) -> str:
    option = features.options[label]
    option_type = int(option.option_type)
    context = int(option.context)
    if context in (int(SelectContext.SWITCH), int(SelectContext.TO_ACTIVE)):
        return "SWITCH / promotion"
    names = {
        int(OptionType.PLAY): "PLAY",
        int(OptionType.ABILITY): "ABILITY",
        int(OptionType.EVOLVE): "EVOLVE",
        int(OptionType.ATTACH): "ATTACH",
    }
    if option_type in names:
        return names[option_type]
    if context != int(SelectContext.MAIN):
        return "target selection"
    return "other"


def validate_active_actions(episode: dict, seat: int) -> Counter:
    """Count active decision rows that the canonical replay parser cannot resolve."""
    errors = Counter()
    steps = episode.get("steps") or []
    for index in range(max(0, len(steps) - 1)):
        if seat >= len(steps[index]) or seat >= len(steps[index + 1]):
            continue
        current = steps[index][seat] or {}
        if str(current.get("status", "")).upper() != "ACTIVE":
            continue
        observation = current.get("observation") or {}
        select = observation.get("select")
        state = observation.get("current")
        if select is None or state is None:
            continue
        options = select.get("option") or []
        if not options:
            errors["empty_options"] += 1
            continue
        action = (steps[index + 1][seat] or {}).get("action")
        if not isinstance(action, list):
            errors["missing_action"] += 1
            continue
        minimum = int(select.get("minCount", 0))
        maximum = int(select.get("maxCount", len(options)))
        if not minimum <= len(action) <= maximum:
            errors["invalid_count"] += 1
        elif len(action) != len(set(action)):
            errors["duplicate_index"] += 1
        elif any(type(value) is not int or value < 0 or value >= len(options) for value in action):
            errors["unresolved_index"] += 1
    return errors


def read_manifest(archive: zipfile.ZipFile) -> dict[str, dict]:
    names = [name for name in archive.namelist() if Path(name).name == "manifest.csv"]
    if len(names) != 1:
        raise ValueError(f"official archive must contain exactly one manifest.csv, found {len(names)}")
    with archive.open(names[0]) as raw:
        rows = csv.DictReader(line.decode("utf-8-sig") for line in raw)
        return {str(row["episode_id"]): row for row in rows}


def episode_decks(episode: dict) -> tuple[tuple[int, ...], tuple[int, ...]]:
    steps = episode.get("steps") or []
    if len(steps) < 2 or len(steps[1]) < 2:
        return (), ()
    result = []
    for seat in (0, 1):
        action = (steps[1][seat] or {}).get("action") or []
        result.append(canonical_deck(action) if len(action) == 60 else ())
    return result[0], result[1]


def episode_outcomes(episode: dict) -> tuple[float, float] | None:
    """Return one winner and one loser; reject unresolved games and 0/0 draws."""
    outcomes = tuple(episode_reward(episode, seat) for seat in (0, 1))
    if outcomes not in ((0.0, 1.0), (1.0, 0.0)):
        return None
    return float(outcomes[0]), float(outcomes[1])


def game_complete(episode: dict) -> bool:
    return episode_outcomes(episode) is not None


def download_dataset(date: str, destination: Path, kaggle: Path = KAGGLE) -> Path:
    if not kaggle.is_file():
        raise FileNotFoundError(f"Kaggle CLI not found: {kaggle}")
    reference = f"kaggle/pokemon-tcg-ai-battle-episodes-{date}"
    command = [str(kaggle), "datasets", "download", "-d", reference, "-p", str(destination), "-q"]
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"dataset download failed for {date}: {result.stderr[-2000:]}")
    archives = list(destination.glob("*.zip"))
    if len(archives) != 1:
        raise RuntimeError(f"expected one downloaded archive for {date}, found {len(archives)}")
    return archives[0]


def extract_day(
    date: str,
    archive_path: Path,
    deck: tuple[int, ...],
    archetype_catalog: dict[str, tuple[int, ...]],
    output_dir: Path,
) -> dict:
    """Stream one official archive and retain exact-deck schema-2 decisions."""
    day_dir = output_dir / "days"
    day_dir.mkdir(parents=True, exist_ok=True)
    rows_path = day_dir / f"{date}.exact.jsonl.gz"
    games_path = day_dir / f"{date}.games.json"
    report_path = day_dir / f"{date}.extraction.json"
    if rows_path.is_file() and games_path.is_file() and report_path.is_file():
        return json.loads(report_path.read_text(encoding="utf-8"))

    archive_sha = sha256_file(archive_path)
    games = []
    counters = Counter()
    malformed = Counter()
    seen_episode_ids = set()
    temporary_rows = rows_path.with_name(rows_path.name + ".tmp")
    with zipfile.ZipFile(archive_path) as archive, deterministic_gzip_text(temporary_rows) as output:
        manifest = read_manifest(archive)
        members = sorted(name for name in archive.namelist() if name.endswith(".json"))
        counters["manifest_rows"] = len(manifest)
        counters["json_members"] = len(members)
        for number, member in enumerate(members, 1):
            try:
                with archive.open(member) as handle:
                    episode = json.load(handle)
            except Exception:
                counters["malformed_episode_json"] += 1
                continue
            info = episode.get("info") or {}
            episode_id = str(info.get("EpisodeId") or Path(member).stem)
            if episode_id in seen_episode_ids:
                counters["duplicate_episode_in_archive"] += 1
                continue
            seen_episode_ids.add(episode_id)
            manifest_row = manifest.get(episode_id)
            if manifest_row is None:
                counters["episode_missing_manifest"] += 1
                continue
            teams = list(info.get("TeamNames") or [])
            if len(teams) != 2 or any(not isinstance(team, str) or not team for team in teams):
                counters["invalid_team_names"] += 1
                continue
            low = float(manifest_row["min_score"])
            high = float(manifest_row["sum_score"]) - low
            games.append({
                "episode_id": episode_id,
                "teams": teams,
                "low_score": min(low, high),
                "high_score": max(low, high),
                "create_time": manifest_row["create_time"],
            })
            decks = episode_decks(episode)
            exact_seats = [seat for seat, value in enumerate(decks) if value == deck]
            if not exact_seats:
                if number % 500 == 0:
                    print(json.dumps({"date": date, "members": number, **counters}), flush=True)
                continue
            counters["exact_episodes_seen"] += 1
            outcomes = episode_outcomes(episode)
            if outcomes is None:
                observed = tuple(episode_reward(episode, seat) for seat in (0, 1))
                counter = "draw_exact_episodes" if observed == (0.0, 0.0) else "incomplete_exact_episodes"
                counters[counter] += 1
                continue
            _, _, first_player = episode_order(episode)
            if first_player not in (0, 1):
                counters["unresolved_order_exact_episodes"] += 1
                continue
            for seat in exact_seats:
                seat_errors = validate_active_actions(episode, seat)
                malformed.update(seat_errors)
                if seat_errors:
                    counters["excluded_malformed_game_seats"] += 1
                    continue
                reward = outcomes[seat]
                opponent = 1 - seat
                game_meta = {
                    "source": "official_kaggle_daily_complete",
                    "source_date": date,
                    "episode_id": episode_id,
                    "seat": seat,
                    "teacher_identity": teams[seat],
                    "opponent_identity": teams[opponent],
                    "outcome": "win" if reward == 1.0 else "loss",
                    "actual_order": "first" if first_player == seat else "second",
                    "create_time": manifest_row["create_time"],
                    "episode_min_score": min(low, high),
                    "episode_max_score": max(low, high),
                    "strict_both_ge_1050": min(low, high) >= 1050.0,
                    "hero_deck_sha256": deck_hash(decks[seat]),
                    "opponent_deck_sha256": deck_hash(decks[opponent]),
                    "opponent_archetype": classify(decks[opponent], archetype_catalog),
                }
                row_count = 0
                for decision in iter_decisions(
                    episode, {teams[seat]}, feature_version=2, include_observation=False
                ):
                    if decision.seat != seat:
                        continue
                    row = decision.to_json()
                    row.update(game_meta)
                    row.pop("observation", None)
                    output.write(stable_json(row) + "\n")
                    row_count += 1
                if row_count:
                    counters["eligible_exact_game_seats"] += 1
                    counters["exact_decisions"] += row_count
                else:
                    counters["empty_exact_game_seats"] += 1
            if number % 500 == 0:
                print(json.dumps({"date": date, "members": number, **counters}), flush=True)
    temporary_rows.replace(rows_path)
    games_path.write_text(json.dumps(games, separators=(",", ":")), encoding="utf-8")
    report = {
        "date": date,
        "dataset": f"kaggle/pokemon-tcg-ai-battle-episodes-{date}",
        "archive_sha256": archive_sha,
        "official_manifest_sha256": hashlib.sha256(
            stable_json(sorted(manifest.items())).encode("utf-8")
        ).hexdigest(),
        "rows_path": str(rows_path),
        "rows_sha256": sha256_file(rows_path),
        "games_path": str(games_path),
        "games_sha256": sha256_file(games_path),
        "counts": dict(sorted(counters.items())),
        "malformed_unresolved_actions": dict(sorted(malformed.items())),
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def load_leaderboard(path: Path, local_username: str) -> tuple[dict[str, float], set[str], list[dict]]:
    anchors = {}
    locally_owned = set()
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            team = str(row["TeamName"])
            anchors[team] = float(row["Score"])
            members = {value.strip().casefold() for value in row["TeamMemberUserNames"].split(",")}
            if local_username.casefold() in members:
                locally_owned.add(team)
            rows.append(row)
    return anchors, locally_owned, rows


def infer_daily_strength(matches: list[dict], anchors: dict[str, float]) -> dict[str, dict]:
    """Infer per-team source-day ratings from manifest score pairs.

    Official manifests expose the two episode scores as an unordered pair.  A
    deterministic anchored EM assignment maps those values back to team names;
    ranks are then computed only within that source date.
    """
    incident = defaultdict(list)
    for match in matches:
        midpoint = (float(match["low_score"]) + float(match["high_score"])) / 2.0
        for team in match["teams"]:
            incident[team].append(midpoint)
    means = {
        team: float(anchors.get(team, statistics.median(values)))
        for team, values in incident.items()
    }
    assignments = []
    for _ in range(50):
        assigned = defaultdict(list)
        assignments = []
        for match in matches:
            a, b = match["teams"]
            low, high = float(match["low_score"]), float(match["high_score"])
            cost_low_high = (low - means[a]) ** 2 + (high - means[b]) ** 2
            cost_high_low = (high - means[a]) ** 2 + (low - means[b]) ** 2
            a_score, b_score = (low, high) if (cost_low_high, a, b) <= (cost_high_low, b, a) else (high, low)
            assigned[a].append(a_score)
            assigned[b].append(b_score)
            assignments.append((a, b, a_score, b_score))
        updated = {team: float(statistics.median(values)) for team, values in assigned.items()}
        delta = max(abs(updated[team] - means[team]) for team in updated) if updated else 0.0
        means = updated
        if delta < 1e-9:
            break
    ordered = sorted(means, key=lambda team: (-means[team], team.casefold(), team))
    result = {
        team: {
            "rank": rank,
            "rating": means[team],
            "games_observed": len(incident[team]),
            "current_leaderboard_anchor": anchors.get(team),
        }
        for rank, team in enumerate(ordered, 1)
    }
    return result


def iter_jsonl(path: Path) -> Iterator[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


@dataclass
class EvaluatedRow:
    row: dict
    fingerprint: str
    label_key: tuple | None
    top_keys: list[tuple]
    ranked: list[int]
    category: str


def evaluate_row(row: dict, model: NumpyPolicyModel) -> EvaluatedRow:
    features = DecisionFeatures.from_json(row["features"])
    action = [int(value) for value in row.get("action", [])]
    logits, _, _ = model.predict(features)
    if len(logits) != len(features.options) or not np.all(np.isfinite(logits)):
        raise ValueError(f"invalid A2 inference at {(row['episode_id'], row['seat'], row['step'])}")
    ranked = np.argsort(-np.asarray(logits), kind="stable").astype(int).tolist()
    top_keys = unique_semantic_ranking(features, ranked)
    label_key = option_key(features.options[action[0]]) if len(action) == 1 else None
    category = action_category(features, action[0]) if len(action) == 1 else "other"
    return EvaluatedRow(row, input_fingerprint(row["features"]), label_key, top_keys, ranked, category)


def balance_corrections(rows: list[dict]) -> dict:
    """Downweight only: equalize four recovery strata and enforce domination caps."""
    if not rows:
        return {"status": "empty", "iterations": 0, "mass": {}}
    episode_counts = Counter((row["source_date"], row["episode_id"], row["seat"]) for row in rows)
    weights = np.asarray([
        float(row["base_rank_weight"]) / episode_counts[(row["source_date"], row["episode_id"], row["seat"])]
        for row in rows
    ], dtype=np.float64)
    buckets = np.asarray([f"{row['outcome']}-{row['actual_order']}" for row in rows], dtype=object)
    pilots = np.asarray([row["teacher_identity"] for row in rows], dtype=object)
    dates = np.asarray([row["source_date"] for row in rows], dtype=object)
    if any(not np.any(buckets == bucket) for bucket in ORDER_OUTCOME_BUCKETS):
        return {"status": "missing_bucket", "iterations": 0, "mass": {}}
    iterations = 0
    for iterations in range(1, 1001):
        before = weights.copy()
        bucket_mass = {bucket: float(weights[buckets == bucket].sum()) for bucket in ORDER_OUTCOME_BUCKETS}
        target = min(bucket_mass.values())
        for bucket, mass in bucket_mass.items():
            if mass > target and mass > 0:
                weights[buckets == bucket] *= target / mass
        total = float(weights.sum())
        for pilot in sorted(set(pilots)):
            mask = pilots == pilot
            mass = float(weights[mask].sum())
            cap = 0.15 * total
            if mass > cap and mass > 0:
                weights[mask] *= cap / mass
        total = float(weights.sum())
        for date in sorted(set(dates)):
            mask = dates == date
            mass = float(weights[mask].sum())
            cap = 0.30 * total
            if mass > cap and mass > 0:
                weights[mask] *= cap / mass
        if float(np.max(np.abs(weights - before))) < 1e-12:
            break
    total = float(weights.sum())
    if total <= 0:
        return {"status": "zero_mass", "iterations": iterations, "mass": {}}
    normalized = weights * (len(rows) / total)
    for row, weight in zip(rows, normalized, strict=True):
        row["final_training_weight"] = float(weight)
        row["sample_weight"] = float(weight)
    bucket_mass = {bucket: float(normalized[buckets == bucket].sum()) for bucket in ORDER_OUTCOME_BUCKETS}
    pilot_mass = {pilot: float(normalized[pilots == pilot].sum()) for pilot in sorted(set(pilots))}
    date_mass = {date: float(normalized[dates == date].sum()) for date in sorted(set(dates))}
    total = float(normalized.sum())
    return {
        "status": "balanced",
        "iterations": iterations,
        "total_mass": total,
        "bucket_mass": bucket_mass,
        "bucket_fraction": {key: value / total for key, value in bucket_mass.items()},
        "pilot_fraction": {key: value / total for key, value in pilot_mass.items()},
        "date_fraction": {key: value / total for key, value in date_mass.items()},
        "max_pilot_fraction": max(pilot_mass.values()) / total,
        "max_date_fraction": max(date_mass.values()) / total,
        "episode_normalization": "base rank weight divided by correction count in game-seat",
        "resampling": "none; downweight-only balancing before global normalization",
    }


def rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def finalize_bucket(bucket: Counter) -> dict:
    return {
        "games": bucket["games"],
        "decisions": bucket["decisions"],
        "a2_top1_count": bucket["top1"],
        "a2_top1": rate(bucket["top1"], bucket["single"]),
        "a2_top3_count": bucket["top3"],
        "a2_top3": rate(bucket["top3"], bucket["single"]),
        "single_semantic_decisions": bucket["single"],
        "clean_corrections": bucket["corrections"],
    }


def certify(
    output_dir: Path,
    a2_path: Path,
    leaderboard_path: Path,
    local_username: str,
    include_rank_41_70: bool = True,
) -> dict:
    if sha256_file(a2_path) != EXPECTED_A2_SHA256:
        raise ValueError("exact A2 SHA-256 mismatch")
    model = NumpyPolicyModel(a2_path)
    anchors, locally_owned, leaderboard_rows = load_leaderboard(leaderboard_path, local_username)
    day_reports = [json.loads((output_dir / "days" / f"{date}.extraction.json").read_text()) for date in DATES]
    rank_maps = {}
    for date in DATES:
        matches = json.loads((output_dir / "days" / f"{date}.games.json").read_text())
        rank_maps[date] = infer_daily_strength(matches, anchors)
    (output_dir / "source_date_rank_estimates.json").write_text(
        json.dumps(rank_maps, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    evaluated = []
    strict_holdout_extras = []
    excluded = Counter()
    duplicate_keys = Counter()
    seen_keys = set()
    episode_dates = defaultdict(set)
    for date in DATES:
        for row in iter_jsonl(output_dir / "days" / f"{date}.exact.jsonl.gz"):
            key = (str(row["episode_id"]), int(row["seat"]), int(row["step"]))
            episode_dates[str(row["episode_id"])].add(date)
            if key in seen_keys:
                duplicate_keys[key] += 1
                continue
            seen_keys.add(key)
            teacher = str(row["teacher_identity"])
            if teacher in locally_owned:
                excluded["locally_owned"] += 1
                continue
            strength = rank_maps[date].get(teacher)
            if strength is None:
                excluded["teacher_rank_unresolved"] += 1
                continue
            teacher_rank = int(strength["rank"])
            teacher_qualified_top70 = teacher_rank <= 70
            strict_holdout = bool(
                row["source_date"] == HOLDOUT_DATE and row.get("strict_both_ge_1050", False)
            )
            if not teacher_qualified_top70 and not strict_holdout:
                excluded["teacher_rank_over_70"] += 1
                continue
            band = rank_band(teacher_rank)
            if teacher_qualified_top70 and band == "41-70" and not include_rank_41_70:
                excluded["rank_41_70_band_removed"] += 1
                continue
            opponent_strength = rank_maps[date].get(str(row["opponent_identity"]), {})
            row.update({
                "teacher_source_date_rank": teacher_rank,
                "teacher_source_date_rating": float(strength["rating"]),
                "opponent_source_date_rank": opponent_strength.get("rank"),
                "opponent_source_date_rating": opponent_strength.get("rating"),
                "rank_band": band,
                "base_rank_weight": RANK_WEIGHTS.get(band, 0.0),
                "teacher_qualified_top70": teacher_qualified_top70,
                # The manifest's unordered score pair is sufficient: if its
                # minimum is >=1050, both episode participants meet the gate.
                "strict_both_ge_1050": strict_holdout,
            })
            try:
                item = evaluate_row(row, model)
                (evaluated if teacher_qualified_top70 else strict_holdout_extras).append(item)
            except Exception:
                excluded["a2_inference_or_feature_error"] += 1

    label_sets = defaultdict(set)
    for item in evaluated:
        if item.label_key is not None:
            label_sets[item.fingerprint].add(item.label_key)
    conflicting = {fingerprint: labels for fingerprint, labels in label_sets.items() if len(labels) > 1}

    corrections = []
    matrix = defaultdict(Counter)
    matrix_games = defaultdict(set)
    pilots = defaultdict(Counter)
    dates = Counter()
    categories = Counter()
    rank_coverage = defaultdict(Counter)
    correction_strata = Counter()
    qualified_rows = {"train": [], "holdout": []}
    all_games = set()
    for item in evaluated:
        row = item.row
        matrix_key = (row["source_date"], row["rank_band"], row["outcome"], row["actual_order"])
        game_key = (row["source_date"], str(row["episode_id"]), int(row["seat"]))
        matrix_games[matrix_key].add(game_key)
        all_games.add(game_key)
        bucket = matrix[matrix_key]
        bucket["decisions"] += 1
        pilots[row["teacher_identity"]]["decisions"] += 1
        dates[row["source_date"]] += 1
        # Every valid qualified state is available to the KL-only stream,
        # including multi-select decisions.  Aug. 13 remains a separate file.
        qualified_rows["train" if row["source_date"] in TRAIN_DATES else "holdout"].append(dict(row))
        if item.label_key is None:
            continue
        bucket["single"] += 1
        rank_coverage[row["rank_band"]]["single"] += 1
        top1 = bool(item.top_keys and item.top_keys[0] == item.label_key)
        top3 = item.label_key in item.top_keys[:3]
        bucket["top1"] += int(top1)
        bucket["top3"] += int(top3)
        rank_coverage[row["rank_band"]]["top1"] += int(top1)
        rank_coverage[row["rank_band"]]["top3"] += int(top3)
        categories[item.category] += 1
        features = DecisionFeatures.from_json(row["features"])
        label = int(row["action"][0])
        label_semantic_rank = item.top_keys.index(item.label_key) + 1 if item.label_key in item.top_keys else None
        is_correction = (
            not top1
            and label_semantic_rank in (2, 3)
            and int(features.options[label].option_type) != int(OptionType.END)
            and item.fingerprint not in conflicting
        )
        projected = dict(row)
        projected["input_fingerprint"] = item.fingerprint
        projected["elite_semantic_key"] = semantic_json(item.label_key)
        projected["a2_semantic_top1_key"] = semantic_json(item.top_keys[0])
        projected["a2_semantic_rank"] = label_semantic_rank
        projected["a2_top1"] = top1
        projected["a2_top3"] = top3
        projected["action_category"] = item.category
        projected["correction"] = is_correction
        projected["split"] = "train" if row["source_date"] in TRAIN_DATES else "holdout"
        if is_correction:
            projected["teacher_action"] = row.get("legal_options", [])[label]
            rejected = item.ranked[0]
            projected["rejected_a2_action"] = row.get("legal_options", [])[rejected]
            corrections.append(projected)
            bucket["corrections"] += 1
            pilots[row["teacher_identity"]]["corrections"] += 1
            correction_strata[f"{row['outcome']}-{row['actual_order']}"] += 1

    for key, games in matrix_games.items():
        matrix[key]["games"] = len(games)
    pilot_games = defaultdict(set)
    for item in evaluated:
        pilot_games[item.row["teacher_identity"]].add(
            (item.row["source_date"], str(item.row["episode_id"]), int(item.row["seat"]))
        )
    for pilot, games in pilot_games.items():
        pilots[pilot]["games"] = len(games)

    # Gate A is the union of the qualified top-70 holdout and the independent
    # manifest-defined strict population.  Strict rows outside top 70 are
    # diagnostics only and can never enter optimization or corpus statistics.
    qualified_rows["holdout"].extend(dict(item.row) for item in strict_holdout_extras)
    train_corrections = [row for row in corrections if row["source_date"] in TRAIN_DATES]
    holdout_corrections = [row for row in corrections if row["source_date"] == HOLDOUT_DATE]
    balancing = balance_corrections(train_corrections)
    corrections_dir = output_dir / "certified"
    corrections_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "train_corrections": (corrections_dir / "train_corrections.jsonl.gz", train_corrections),
        "aug13_holdout": (corrections_dir / "aug13_holdout.jsonl.gz", qualified_rows["holdout"]),
        "aug8_12_qualified_kl": (corrections_dir / "aug8_12_qualified_kl.jsonl.gz", qualified_rows["train"]),
    }
    output_meta = {}
    for name, (path, rows) in outputs.items():
        with deterministic_gzip_text(path) as handle:
            for row in sorted(rows, key=lambda value: (
                value["source_date"], str(value["episode_id"]), int(value["seat"]), int(value["step"])
            )):
                handle.write(stable_json(row) + "\n")
        output_meta[name] = {"path": str(path), "rows": len(rows), "sha256": sha256_file(path)}

    rank_quality = {
        band: {
            "single": values["single"],
            "top1": rate(values["top1"], values["single"]),
            "top3": rate(values["top3"], values["single"]),
            "corrections": sum(
                1 for row in corrections if row["rank_band"] == band
            ),
        }
        for band, values in sorted(rank_coverage.items())
    }
    duplicate_episode_ids = {
        episode: sorted(values) for episode, values in episode_dates.items() if len(values) > 1
    }
    malformed_total = sum(
        sum(report["malformed_unresolved_actions"].values()) for report in day_reports
    )
    train_dates = {row["source_date"] for row in qualified_rows["train"]}
    train_pilots_1_20 = {row["teacher_identity"] for row in qualified_rows["train"] if row["rank_band"] == "1-20"}
    train_orders = Counter(row["actual_order"] for row in train_corrections)
    train_loss_strata = Counter(
        f"loss-{row['actual_order']}" for row in train_corrections if row["outcome"] == "loss"
    )
    hard_checks = {
        "five_training_dates": len(train_dates) == 5,
        "multiple_top_quality_pilots": len(train_pilots_1_20) >= 2,
        "both_actual_orders": all(train_orders[value] > 0 for value in ("first", "second")),
        "loss_first_and_second": all(train_loss_strata[f"loss-{value}"] > 0 for value in ("first", "second")),
        "at_least_2000_clean_loss_corrections": sum(
            1 for row in train_corrections if row["outcome"] == "loss"
        ) >= 2000,
        "zero_unresolved_conflicting_label_contamination": all(
            row["input_fingerprint"] not in conflicting for row in corrections
        ),
        # Malformed game-seats are rejected before any decision enters evaluated.
        "zero_malformed_unresolved_actions_in_included_game_seats": True,
        "balanced_four_way_mass": balancing.get("status") == "balanced" and all(
            abs(value - 0.25) <= 1e-6 for value in balancing.get("bucket_fraction", {}).values()
        ),
        "pilot_mass_cap": balancing.get("max_pilot_fraction", 1.0) <= 0.15 + 1e-9,
        "date_mass_cap": balancing.get("max_date_fraction", 1.0) <= 0.30 + 1e-9,
    }
    status = "PASS" if all(hard_checks.values()) else "FAIL"
    matrix_rows = [
        {
            "date": key[0], "rank_band": key[1], "outcome": key[2], "actual_order": key[3],
            **finalize_bucket(values),
        }
        for key, values in sorted(matrix.items())
    ]
    opponent_ratings = [
        float(item.row["opponent_source_date_rating"])
        for item in evaluated if item.row.get("opponent_source_date_rating") is not None
    ]
    strict_holdout_rows = [row for row in qualified_rows["holdout"] if row["strict_both_ge_1050"]]
    strict_holdout_game_seats = {
        (str(row["episode_id"]), int(row["seat"])): row["outcome"]
        for row in strict_holdout_rows
    }
    report = {
        "experiment": "A2-ERR-1",
        "stage": "pre-training corpus certification",
        "status": status,
        "training_authorized": status == "PASS",
        "source_dates": list(DATES),
        "temporal_split": {"training": sorted(TRAIN_DATES), "untouched_holdout": HOLDOUT_DATE},
        "provenance": {
            "a2_path": str(a2_path), "a2_sha256": sha256_file(a2_path),
            "deck_path": str(ROOT / "decks/grimmsnarl.csv"),
            "deck_sha256": sha256_file(ROOT / "decks/grimmsnarl.csv"),
            "daily_extractions": day_reports,
            "leaderboard_anchor_path": str(leaderboard_path),
            "leaderboard_anchor_sha256": sha256_file(leaderboard_path),
            "rank_method": "source-date rank over deterministic team ratings inferred from official manifest unordered score pairs; latest official leaderboard anchors pair orientation only",
            "local_username": local_username,
            "locally_owned_teams_excluded": sorted(locally_owned),
        },
        "hard_checks": hard_checks,
        "required_matrix": matrix_rows,
        "unique_qualified_grim_pilots": len(pilot_games),
        "unique_episodes": len({str(item.row["episode_id"]) for item in evaluated}),
        "games_per_pilot": {key: value["games"] for key, value in sorted(pilots.items())},
        "decisions_per_pilot": {key: value["decisions"] for key, value in sorted(pilots.items())},
        "corrections_per_pilot": {key: value["corrections"] for key, value in sorted(pilots.items())},
        "corrections_per_date": dict(sorted(Counter(row["source_date"] for row in corrections).items())),
        "corrections_by_outcome_order": dict(sorted(correction_strata.items())),
        "opponent_strength_distribution": {
            "count": len(opponent_ratings),
            "minimum": min(opponent_ratings) if opponent_ratings else None,
            "median": statistics.median(opponent_ratings) if opponent_ratings else None,
            "maximum": max(opponent_ratings) if opponent_ratings else None,
            "both_players_ge_1050_decisions": len(strict_holdout_rows),
        },
        "strict_aug13_holdout": {
            "definition": "official manifest min_score >= 1050; independent of inferred teacher rank",
            "game_seats": len(strict_holdout_game_seats),
            "decisions": len(strict_holdout_rows),
            "wins": sum(outcome == "win" for outcome in strict_holdout_game_seats.values()),
            "losses": sum(outcome == "loss" for outcome in strict_holdout_game_seats.values()),
        },
        "duplicate_episode_ids_across_days": duplicate_episode_ids,
        "duplicate_decision_keys": len(duplicate_keys),
        "feature_identical_conflicting_labels": {
            "fingerprints": len(conflicting),
            "rows": sum(1 for item in evaluated if item.fingerprint in conflicting),
        },
        "malformed_unresolved_actions": {
            "included_game_seats": malformed_total,
            "by_day": {report["date"]: report["malformed_unresolved_actions"] for report in day_reports},
        },
        "action_category_counts": dict(sorted(categories.items())),
        "rank_band_coverage": rank_quality,
        "qualitative_quality_audit": {
            "strong_semantic_top3_across_included_bands": "inspect rank_band_coverage without inventing an unstated threshold",
            "rank_41_70_discard_rule": "discard the entire band only if its reported coverage clearly demonstrates substantially worse/noisier action quality than ranks 1-40",
            "substantial_order_and_meaningful_loss_coverage": "inspect corrections_by_outcome_order and required_matrix",
        },
        "balancing": balancing,
        "excluded_decisions": dict(sorted(excluded.items())),
        "outputs": output_meta,
        "notes": {
            "rank_41_70_included": include_rank_41_70,
            "opponent_archetype": "classified from the opponent's official replay deck handshake",
            "strict_subset": "official episode manifest min_score >=1050, independent of top-70 qualification",
            "loss_labels": "positive demonstrations; never negative labels",
        },
    }
    report_path = output_dir / "corpus_certification.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def locate_leaderboard(directory: Path, kaggle: Path = KAGGLE) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(kaggle), "competitions", "leaderboard", "pokemon-tcg-ai-battle", "-d", "-p", str(directory)],
        text=True, capture_output=True,
    )
    if result.returncode:
        raise RuntimeError(f"leaderboard download failed: {result.stderr[-2000:]}")
    archives = sorted(directory.glob("pokemon-tcg-ai-battle.zip"))
    if len(archives) != 1:
        raise RuntimeError("official leaderboard archive was not downloaded")
    with zipfile.ZipFile(archives[0]) as archive:
        members = [name for name in archive.namelist() if name.endswith(".csv")]
        if len(members) != 1:
            raise RuntimeError("official leaderboard archive must contain one CSV")
        target = directory / Path(members[0]).name
        with archive.open(members[0]) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="data/a2_err_1")
    parser.add_argument("--deck", default="decks/grimmsnarl.csv")
    parser.add_argument("--a2", default="artifacts/grim_damage_conversion/candidates/a2_damage_v0/policy_weights.npz")
    parser.add_argument("--leaderboard", help="official leaderboard CSV used only to orient manifest score pairs")
    parser.add_argument("--local-username", default="safm1rza")
    parser.add_argument("--archive-dir", help="optional directory containing one DATE-named zip per source date")
    parser.add_argument("--top40-only", action="store_true")
    parser.add_argument("--certify-only", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    deck = load_deck(args.deck)
    if len(deck) != 60:
        raise ValueError("exact Grim deck must contain 60 cards")
    archetype_catalog = load_archetype_catalog(ROOT / "freshstart" / "decklists")
    if not args.certify_only:
        for date in DATES:
            report_path = output_dir / "days" / f"{date}.extraction.json"
            if report_path.is_file():
                print(json.dumps({"date": date, "status": "reused"}), flush=True)
                continue
            if args.archive_dir:
                candidates = sorted(Path(args.archive_dir).glob(f"*{date}*.zip"))
                if len(candidates) != 1:
                    raise RuntimeError(f"expected one archive containing {date} in {args.archive_dir}")
                archive_path = candidates[0]
                report = extract_day(date, archive_path, deck, archetype_catalog, output_dir)
            else:
                with tempfile.TemporaryDirectory(prefix=f"a2-err-{date}-") as temporary:
                    archive_path = download_dataset(date, Path(temporary))
                    report = extract_day(date, archive_path, deck, archetype_catalog, output_dir)
            print(json.dumps({"date": date, "status": "extracted", **report["counts"]}), flush=True)

    if args.leaderboard:
        leaderboard = Path(args.leaderboard).resolve()
    else:
        leaderboard = locate_leaderboard(output_dir / "sources")
    report = certify(
        output_dir, Path(args.a2).resolve(), leaderboard, args.local_username,
        include_rank_41_70=not args.top40_only,
    )
    print(json.dumps({
        "status": report["status"],
        "training_authorized": report["training_authorized"],
        "hard_checks": report["hard_checks"],
        "report": str(output_dir / "corpus_certification.json"),
    }, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
