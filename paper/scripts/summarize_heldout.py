#!/usr/bin/env python3
"""Sanitize and stratify the fresh 2026-08-13 held-out replay reanalysis."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))
HISTORICAL_EVALUATOR = ROOT / "scripts/overnight_20260816/replay_disagreement.py"
HISTORICAL_EVALUATOR_COMMIT = "9d974bb9ae7c57dad08d4742c8ad4503e1a681c0"
HISTORICAL_EVALUATOR_SHA256 = "6b9c1ec38773f5b4ef17e52189e97c482193884f84684941c071684d3c6c72d4"
EXPECTED_LABEL = "HELDOUT-0813-FRESH-REANALYSIS"
PRESPECIFIED_TEAMS = frozenset({"Dreamer", "GrimmsnaRL", "Mint120", "TMTA", "lollipop947"})
DECISIVE_CLASSES = frozenset({"cand_approved", "c0_approved", "abstain"})
OPTION_NAMES = {
    0: "number", 1: "yes", 2: "no", 3: "card", 4: "tool_card",
    5: "energy_card", 6: "energy", 7: "play", 8: "attach", 9: "evolve",
    10: "ability", 11: "discard", 12: "retreat", 13: "attack", 14: "end",
    15: "skill", 16: "special_condition",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_observation_hash(observation: dict) -> str:
    return hashlib.sha256(
        json.dumps(observation, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def require_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}, got {value!r}")
    return value


def validate_summary(summary: dict, evaluator_teams: set[str]) -> tuple[list[str], Counter]:
    if not isinstance(summary, dict):
        raise ValueError("historical summary must be a JSON object")
    if summary.get("candidate") != "exp23":
        raise ValueError(f"historical summary candidate must be exp23, got {summary.get('candidate')!r}")
    if summary.get("label") != EXPECTED_LABEL:
        raise ValueError(
            f"historical summary label must be {EXPECTED_LABEL!r}, got {summary.get('label')!r}"
        )

    teams = summary.get("teams")
    if not isinstance(teams, list) or any(not isinstance(team, str) for team in teams):
        raise ValueError("historical summary teams must be a list of strings")
    if len(teams) != len(set(teams)):
        raise ValueError("historical summary teams contains duplicates")
    if len(teams) != 5 or set(teams) != PRESPECIFIED_TEAMS:
        raise ValueError(
            "historical summary teams must be the exact five prespecified CERT-B teams"
        )
    if set(teams) != evaluator_teams:
        raise ValueError("historical summary teams differ from the frozen evaluator CERT_TEAMS")

    require_int(summary.get("units"), "historical summary units", minimum=1)
    decisive_n = require_int(summary.get("decisive_n"), "historical summary decisive_n")
    total_scored = require_int(
        summary.get("total_scored_decisions"),
        "historical summary total_scored_decisions",
    )
    decision_classes = summary.get("decision_classes")
    if not isinstance(decision_classes, dict):
        raise ValueError("historical summary decision_classes must be an object")
    class_counts = Counter()
    allowed_summary_classes = DECISIVE_CLASSES | {"ignored"}
    unknown = set(decision_classes) - allowed_summary_classes
    if unknown:
        raise ValueError(f"unknown historical decision classes: {sorted(unknown)}")
    for name in allowed_summary_classes:
        class_counts[name] = require_int(
            decision_classes.get(name, 0), f"historical decision_classes[{name!r}]"
        )
    if total_scored != sum(class_counts.values()):
        raise ValueError(
            "historical total_scored_decisions does not equal the decision-class total"
        )
    if decisive_n != sum(class_counts[name] for name in DECISIVE_CLASSES):
        raise ValueError(
            "historical decisive_n does not equal candidate-approved + control-approved + abstain"
        )

    excluded = summary.get("excluded")
    if not isinstance(excluded, dict):
        raise ValueError("historical summary excluded must be an object")
    for name, value in excluded.items():
        require_int(value, f"historical excluded[{name!r}]")
    if require_int(excluded.get("agreement", 0), "historical excluded['agreement']") != class_counts["ignored"]:
        raise ValueError("historical ignored and excluded-agreement counts do not reconcile")
    return sorted(teams), class_counts


def load_slim_rows(path: Path, expected_n: int, expected_classes: Counter) -> tuple[list[dict], dict]:
    rows = []
    rows_by_key = {}
    observed_classes = Counter()
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"blank line in disagreement rows at line {line_number}")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"row {line_number} must be a JSON object")
            required_fields = {
                "episode", "team", "seat", "step", "context", "turn", "hero_order",
                "cls", "elite", "c0", "cand", "obs_sha256",
            }
            missing = required_fields - set(row)
            if missing:
                raise ValueError(f"row {line_number} missing fields: {sorted(missing)}")
            if "obs" in row:
                raise ValueError(
                    f"row {line_number} unexpectedly embeds obs; expected hash-only portable rows"
                )
            extra = set(row) - required_fields
            if extra:
                raise ValueError(f"row {line_number} has unexpected fields: {sorted(extra)}")
            episode = str(row["episode"])
            if not episode:
                raise ValueError(f"row {line_number} has an empty episode identifier")
            seat = require_int(row["seat"], f"row {line_number} seat")
            if seat not in (0, 1):
                raise ValueError(f"row {line_number} seat must be 0 or 1")
            step = require_int(row["step"], f"row {line_number} step")
            key = (episode, seat, step)
            if key in rows_by_key:
                raise ValueError(f"duplicate disagreement key {key} at line {line_number}")
            cls = str(row["cls"])
            if cls not in DECISIVE_CLASSES:
                raise ValueError(f"row {line_number} has invalid retained class {cls!r}")
            obs_sha256 = row["obs_sha256"]
            if not isinstance(obs_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", obs_sha256) is None:
                raise ValueError(f"row {line_number} has an invalid obs_sha256")
            for action_name in ("elite", "c0", "cand"):
                action = row[action_name]
                if (
                    not isinstance(action, list)
                    or any(isinstance(index, bool) or not isinstance(index, int) or index < 0 for index in action)
                ):
                    raise ValueError(f"row {line_number} {action_name} must be nonnegative integer indices")
            row["episode"] = episode
            row["seat"] = seat
            row["step"] = step
            rows.append(row)
            rows_by_key[key] = row
            observed_classes[cls] += 1

    if len(rows) != expected_n:
        raise ValueError(
            f"row count {len(rows)} does not equal historical decisive_n {expected_n}"
        )
    expected_retained = Counter({name: expected_classes[name] for name in DECISIVE_CLASSES})
    if observed_classes != expected_retained:
        raise ValueError(
            f"row classes {dict(observed_classes)} do not reconcile with historical summary "
            f"{dict(expected_retained)}"
        )
    return rows, rows_by_key


def identity_state(obs_dict: dict) -> str:
    from scripts.overnight_20260816 import replay_disagreement as historical

    obs = historical.to_observation_class(obs_dict)
    source_cards = []
    for option in obs.select.option:
        if option.type != historical.OptionType.PLAY:
            continue
        selected = None
        if option.area is None:
            hand = obs.current.players[obs.current.yourIndex].hand or []
            index = option.index
            if index is not None and 0 <= index < len(hand) and hand[index] is not None:
                selected = hand[index]
        else:
            selected = historical.resolve_area_card(
                obs, option.area, option.index, option.playerIndex
            )
        source_cards.append(int(selected.id if selected is not None else option.cardId or 0))
    return "multi_play_identity" if len({value for value in source_cards if value > 0}) >= 2 else "other"


def action_family(obs_dict: dict, action: list[int]) -> str:
    from scripts.overnight_20260816 import replay_disagreement as historical

    obs = historical.to_observation_class(obs_dict)
    option_types = sorted({
        int(obs.select.option[index].type)
        for index in action
        if 0 <= int(index) < len(obs.select.option)
    })
    return "+".join(OPTION_NAMES.get(value, str(value)) for value in option_types) or "empty"


def bootstrap(rows: list[dict], iterations: int, seed: int) -> dict:
    counts = Counter(row["cls"] for row in rows)
    binary = counts["cand_approved"] + counts["c0_approved"]
    result = {
        "disagreements": len(rows),
        "candidate_approved": counts["cand_approved"],
        "control_approved": counts["c0_approved"],
        "abstain": counts["abstain"],
        "binary_decisive": binary,
        "approval": counts["cand_approved"] / binary if binary else None,
        "episodes": len({row["episode"] for row in rows}),
    }
    if not binary:
        result["episode_bootstrap_95_ci"] = [None, None]
        return result
    by_episode = defaultdict(list)
    for row in rows:
        by_episode[row["episode"]].append(row["cls"])
    episodes = sorted(by_episode)
    numerators = np.asarray([
        sum(value == "cand_approved" for value in by_episode[episode]) for episode in episodes
    ], dtype=np.int64)
    denominators = np.asarray([
        sum(value in {"cand_approved", "c0_approved"} for value in by_episode[episode])
        for episode in episodes
    ], dtype=np.int64)
    rng = np.random.default_rng(seed)
    samples = np.empty(iterations, dtype=np.float64)
    batch = 2_000
    for start in range(0, iterations, batch):
        stop = min(iterations, start + batch)
        picked = rng.integers(0, len(episodes), size=(stop - start, len(episodes)))
        denominator = denominators[picked].sum(axis=1)
        numerator = numerators[picked].sum(axis=1)
        samples[start:stop] = np.divide(
            numerator, denominator, out=np.full(stop - start, np.nan), where=denominator > 0
        )
    result["episode_bootstrap_95_ci"] = [
        float(np.nanpercentile(samples, 2.5)), float(np.nanpercentile(samples, 97.5))
    ]
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument(
        "--raw-dirs", nargs="+", type=Path, required=True,
        help="retained episode directories used by the unchanged evaluator",
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "paper/data/heldout_0813_summary.json",
    )
    parser.add_argument("--iterations", type=int, default=100_000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.iterations <= 0:
        raise ValueError("--iterations must be positive")
    evaluator_hash = sha256_file(HISTORICAL_EVALUATOR)
    if evaluator_hash != HISTORICAL_EVALUATOR_SHA256:
        raise ValueError(
            "historical evaluator bytes differ from the frozen audited version: "
            f"{evaluator_hash} != {HISTORICAL_EVALUATOR_SHA256}"
        )

    from scripts.overnight_20260816 import replay_disagreement as historical

    evaluator_teams = set(historical.CERT_TEAMS)
    historical_summary = json.loads(args.summary.read_text(encoding="utf-8"))
    prespecified_teams, class_counts = validate_summary(historical_summary, evaluator_teams)
    expected_n = require_int(historical_summary["decisive_n"], "historical decisive_n")
    slim_rows, rows_by_key = load_slim_rows(args.rows, expected_n, class_counts)

    # The unchanged historical evaluator deliberately strips observations from
    # its portable disagreement rows. Rejoin the required observations by the
    # evaluator's exact (episode, seat, step) key and verify its stored hash.
    # In the same pass, independently rerun the evaluator's winner/exact-deck
    # eligibility function over every retained raw episode.
    required_by_episode = defaultdict(list)
    for key in rows_by_key:
        required_by_episode[key[0]].append(key)

    raw_paths = {}
    for raw_dir in args.raw_dirs:
        if not raw_dir.is_dir():
            raise ValueError(f"raw episode directory does not exist: {raw_dir}")
        for path in sorted(raw_dir.glob("*.json")):
            episode_id = path.stem
            if episode_id in raw_paths:
                raise ValueError(
                    f"duplicate raw episode id {episode_id}: {raw_paths[episode_id]} and {path}"
                )
            raw_paths[episode_id] = path
    if not raw_paths:
        raise ValueError("no *.json raw episodes found")
    missing_episode_files = sorted(set(required_by_episode) - set(raw_paths))
    if missing_episode_files:
        raise ValueError(
            f"missing {len(missing_episode_files)} raw episode files; first={missing_episode_files[0]}"
        )

    observations = {}
    eligible_units = {}
    for episode_id, path in sorted(raw_paths.items()):
        episode = historical.load_episode(path)
        if not isinstance(episode, dict):
            raise ValueError(f"raw episode {episode_id} is not a JSON object")
        for unit in historical.episode_units(episode, set(prespecified_teams)):
            unit_key = (episode_id, require_int(unit["seat"], f"eligible unit {episode_id} seat"))
            if unit_key in eligible_units:
                raise ValueError(f"duplicate eligible unit {unit_key}")
            eligible_units[unit_key] = str(unit["team"])

        steps = episode.get("steps") or []
        _, _, first_player = historical.episode_order(episode)
        for key in required_by_episode.get(episode_id, []):
            _, seat, step = key
            if step >= len(steps) or seat >= len(steps[step]):
                raise ValueError(f"retained key is outside raw episode bounds: {key}")
            raw_row = steps[step][seat]
            if not isinstance(raw_row, dict):
                raise ValueError(f"raw episode row is not an object for {key}")
            obs = raw_row.get("observation")
            if not isinstance(obs, dict) or not obs:
                raise ValueError(f"raw observation is null or empty for retained key {key}")
            expected_hash = str(rows_by_key[key]["obs_sha256"])
            observed_hash = canonical_observation_hash(obs)
            if observed_hash != expected_hash:
                raise ValueError(f"observation hash mismatch for {key}")

            select = obs.get("select") or {}
            current = obs.get("current") or {}
            slim = rows_by_key[key]
            if int(select.get("context", -1)) != int(slim["context"]):
                raise ValueError(f"context mismatch between raw episode and portable row for {key}")
            if int(current.get("turn", -1)) != int(slim["turn"]):
                raise ValueError(f"turn mismatch between raw episode and portable row for {key}")
            expected_order = (
                "first" if seat == first_player else "second"
            ) if first_player in (0, 1) else None
            if slim["hero_order"] != expected_order:
                raise ValueError(f"actual-order mismatch between raw episode and portable row for {key}")
            if step + 1 >= len(steps) or seat >= len(steps[step + 1]):
                raise ValueError(f"recorded-action successor is missing for {key}")
            if steps[step + 1][seat].get("action") != slim["elite"]:
                raise ValueError(f"recorded action mismatch between raw episode and portable row for {key}")

            options = select.get("option") or []
            minimum = require_int(select.get("minCount"), f"raw select minCount for {key}")
            maximum = require_int(select.get("maxCount"), f"raw select maxCount for {key}")
            for action_name in ("elite", "c0", "cand"):
                action = slim[action_name]
                if (
                    not minimum <= len(action) <= maximum
                    or len(action) != len(set(action))
                    or any(index >= len(options) for index in action)
                ):
                    raise ValueError(f"invalid {action_name} action for retained key {key}")
            observations[key] = obs

    expected_units = require_int(historical_summary["units"], "historical summary units", minimum=1)
    if len(eligible_units) != expected_units:
        raise ValueError(
            f"re-derived eligible-unit count {len(eligible_units)} does not equal historical units {expected_units}"
        )
    for key, slim in rows_by_key.items():
        unit_key = (key[0], key[1])
        if unit_key not in eligible_units:
            raise ValueError(f"retained disagreement does not belong to an eligible unit: {key}")
        if str(slim["team"]) != eligible_units[unit_key]:
            raise ValueError(f"team mismatch between eligible unit and portable row for {key}")

    eligible_team_count = len(set(eligible_units.values()))
    eligible_episode_count = len({episode for episode, _ in eligible_units})

    missing = sorted(set(rows_by_key) - set(observations))
    if missing:
        raise ValueError(f"missing {len(missing)} retained observations; first={missing[0]}")

    rows = []
    for row in slim_rows:
        key = (str(row["episode"]), int(row["seat"]), int(row["step"]))
        obs = observations[key]
        rows.append({
            "episode": str(row["episode"]),
            "team": str(row["team"]),
            "hero_order": "unknown" if row["hero_order"] is None else str(row["hero_order"]),
            "turn": int(row["turn"]),
            "turn_band": "early" if int(row["turn"]) <= 3 else (
                "mid" if int(row["turn"]) <= 7 else "late"
            ),
            "context": str(row["context"]),
            "action_family": action_family(obs, row["elite"]),
            "cls": str(row["cls"]),
            "identity_state": identity_state(obs),
        })
    groups = defaultdict(list)
    for row in rows:
        groups[row["identity_state"]].append(row)
    # Use the prespecified summary population, including a team with zero
    # retained disagreements, rather than inferring the population post hoc.
    team_names = prespecified_teams
    team_results = {
        f"heldout_team_{index + 1}": bootstrap(
            [row for row in rows if row["team"] == team], args.iterations, 20260840 + index
        )
        for index, team in enumerate(team_names)
    }
    team_approvals = [value["approval"] for value in team_results.values() if value["approval"] is not None]
    sanitized = {
        "schema_version": 2,
        "label": "fresh_reanalysis_of_retained_2026_08_13_heldout_replays",
        "method": "historical semantic-action classifier; episode-clustered bootstrap",
        "important_estimand_note": (
            "Approval is conditional on candidate-control semantic disagreement and excludes abstentions; "
            "it is not a gameplay win rate or an estimate over all replay decisions."
        ),
        "eligibility": {
            "winner_only_units": True,
            "exact_target_deck_only": True,
            "prespecified_team_count": len(team_names),
            "teams_with_eligible_units": eligible_team_count,
            "eligibility_rederived_from_raw_episodes": True,
            "demonstrator_note": (
                "Recorded actions come only from winning units for five prespecified teams using the exact "
                "target deck. The retained daily/top-episode source and outcome selection are not a random "
                "sample, and independent demonstrator expertise was not established."
            ),
            "effective_team_note": (
                f"Only {eligible_team_count} of the five prespecified teams supplied a winning exact-deck "
                "unit in the retained raw episodes; zero-unit teams remain in by_team with null estimates."
            ),
            "inspection_note": (
                "The teams and historical certification materials had already been inspected. This fresh "
                "reanalysis is secondary refresh-heldout evidence, not an untouched external test."
            ),
        },
        "source": {
            "historical_evaluator": "scripts/overnight_20260816/replay_disagreement.py",
            "historical_evaluator_last_change_commit": HISTORICAL_EVALUATOR_COMMIT,
            "historical_evaluator_sha256": evaluator_hash,
            "raw_summary_sha256": sha256_file(args.summary),
            "raw_rows_sha256": sha256_file(args.rows),
            "raw_episode_file_count": len(raw_paths),
            "raw_episode_ids_sha256": hashlib.sha256(
                ("\n".join(sorted(raw_paths)) + "\n").encode()
            ).hexdigest(),
            "portable_rows_observation_storage": "omitted; obs_sha256 retained",
            "observation_rejoin": "raw episode keyed by (episode, seat, step), hash verified",
            "null_observation_note": (
                "The merged training-corpus rows carry observation=null and cannot support this analysis. "
                "This reanalysis instead uses non-null raw-episode observations rejoined to hash-only rows."
            ),
            "sanitizer": str(Path(__file__).resolve().relative_to(ROOT)),
            "sanitizer_sha256": sha256_file(Path(__file__).resolve()),
        },
        "coverage": {
            "units": expected_units,
            "units_rederived": len(eligible_units),
            "eligible_episodes": eligible_episode_count,
            "prespecified_team_count": len(team_names),
            "teams_with_eligible_units": eligible_team_count,
            "total_scored_decisions": historical_summary["total_scored_decisions"],
            "decision_classes": {
                name: class_counts[name]
                for name in ("cand_approved", "c0_approved", "abstain", "ignored")
            },
            "retained_disagreements": expected_n,
            "excluded": historical_summary["excluded"],
            "runtime_accounting_limitation": (
                "The historical summary serializes excluded policy-error decisions but not per-package "
                "fatal-unit counts; absent fatal-unit counts must not be interpreted as zero."
            ),
        },
        "overall": bootstrap(rows, args.iterations, 20260827),
        "by_identity_state": {
            name: bootstrap(group, args.iterations, 20260828 + index)
            for index, (name, group) in enumerate(sorted(groups.items()))
        },
        "by_actual_order": {
            name: bootstrap([row for row in rows if row["hero_order"] == name], args.iterations, 20260830 + index)
            for index, name in enumerate(sorted({row["hero_order"] for row in rows}))
        },
        "by_turn_band": {
            name: bootstrap([row for row in rows if row["turn_band"] == name], args.iterations, 20260850 + index)
            for index, name in enumerate(sorted({row["turn_band"] for row in rows}))
        },
        "by_context": {
            name: bootstrap([row for row in rows if row["context"] == name], args.iterations, 20260860 + index)
            for index, name in enumerate(sorted({row["context"] for row in rows}))
        },
        "by_action_family": {
            name: bootstrap([row for row in rows if row["action_family"] == name], args.iterations, 20260870 + index)
            for index, name in enumerate(sorted({row["action_family"] for row in rows}))
        },
        "by_team": team_results,
        "team_balanced_approval": float(np.mean(team_approvals)) if team_approvals else None,
        "team_balanced_nonnull_team_count": len(team_approvals),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sanitized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "disagreements": len(rows),
        "approval": sanitized["overall"]["approval"],
        "ci": sanitized["overall"]["episode_bootstrap_95_ci"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
