#!/usr/bin/env python3
"""Overnight held-out disagreement certification harness (2026-08-16).

Replays raw episodes through complete package runtimes (one fresh process per
(episode, package), full chronological walk, deck-select reset first) and
classifies C0 vs candidate vs recorded-elite decisions with a frozen semantic
identity.

Protocol: docs/sprints/final_overnight/OVERNIGHT_CERT_20260816.md
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import multiprocessing as mp
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np

from cg.api import AreaType, OptionType, SelectContext, all_card_data, to_observation_class


# ---------------------------------------------------------------- frozen bits

DECK_CSV = "/Users/safiullahbaig/Projects/pokemonTCG2.0/freshstart/decklists/grimmsnarl_marnie.deck.csv"
GRIM_SIGNATURE = tuple(
    sorted(int(x) for x in Path(DECK_CSV).read_text().split() if x.strip())
)

CERT_TEAMS = {"Dreamer", "GrimmsnaRL", "Mint120", "TMTA", "lollipop947"}
SEALED_TEAMS = {"matsurih"}

PACKAGES = {
    "c0": "/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/grim_damage_conversion/winner/extracted",
    "exp23": "/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/final_sprint/exp23_identity_trained",
    "exp20": "/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/final_sprint/exp20_punk_first_only",
    "d842": "/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/overnight_20260816/d842_runtime",
}

D842_SRC = "/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/grim_damage_conversion/winner/extracted"

PRIZE_CACHE: dict[int, int] = {}


def _card_table():
    return {card.cardId: card for card in all_card_data()}


_CARD_TABLE = None


def prize_value(pokemon) -> int:
    if pokemon is None:
        return 0
    global _CARD_TABLE
    if _CARD_TABLE is None:
        _CARD_TABLE = _card_table()
    data = _CARD_TABLE.get(pokemon.id)
    if data is None:
        return 1
    return 3 if data.megaEx else 2 if data.ex else 1


def resolve_area_card(obs, area, index, player_index=None):
    if obs.current is None or area is None or index is None:
        return None
    state = obs.current
    owner = state.yourIndex if player_index is None else player_index
    if area == AreaType.LOOKING:
        zone = state.looking or []
    elif area == AreaType.STADIUM:
        zone = state.stadium or []
    elif area == AreaType.DECK:
        zone = obs.select.deck or []
    else:
        player = state.players[owner]
        zone = {
            AreaType.HAND: player.hand or [],
            AreaType.DISCARD: player.discard or [],
            AreaType.ACTIVE: player.active or [],
            AreaType.BENCH: player.bench or [],
            AreaType.PRIZE: player.prize or [],
        }.get(area, [])
    if not 0 <= index < len(zone):
        return None
    return zone[index]


def semantic_key(obs_dict: dict, option_index: int) -> tuple:
    """Frozen semantic identity of a raw-option index (protocol section 5)."""
    obs = to_observation_class(obs_dict)
    option = obs.select.option[option_index]
    selected = None
    if option.type == OptionType.PLAY:
        if option.area is None:
            state = obs.current
            hand = state.players[state.yourIndex].hand or []
            i = option.index
            if i is not None and 0 <= i < len(hand) and hand[i] is not None:
                selected = hand[i]
        else:
            selected = resolve_area_card(obs, option.area, option.index, option.playerIndex)
    else:
        selected = resolve_area_card(obs, option.area, option.index, option.playerIndex)
    source_id = selected.id if selected is not None else int(option.cardId or 0)
    target = resolve_area_card(obs, option.inPlayArea, option.inPlayIndex, obs.current.yourIndex)
    target_id = target.id if target is not None else 0
    numeric = (
        round(float(option.number or 0) / 20.0, 6),
        round(float(option.count or 0) / 10.0, 6),
        round(float(getattr(target, "hp", 0) or 0) / 400.0, 6),
        round(float(getattr(target, "maxHp", 0) or 0) / 400.0, 6),
        round(float(len(getattr(target, "energies", []) or [])) / 10.0, 6),
        round(float(len(getattr(target, "tools", []) or [])) / 4.0, 6),
        round(float(prize_value(target)) / 3.0, 6),
        round(float(getattr(target, "appearThisTurn", False)), 6),
        round(float(1 if option.playerIndex == obs.current.yourIndex else 0), 6),
    )
    return (
        int(option.type),
        int(obs.select.context),
        int(source_id),
        int(target_id),
        int(option.attackId or 0),
        int(option.area or 0),
        int(option.inPlayArea or 0),
        numeric,
    )


def action_semantic(obs_dict: dict, action: list[int]) -> tuple:
    keys = [semantic_key(obs_dict, index) for index in action]
    if len(keys) == 1:
        return keys[0]
    return ("MULTI",) + tuple(sorted(keys))


# ---------------------------------------------------------------- mining bits

def load_episode(path: str | Path) -> dict:
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def episode_reward(episode: dict, seat: int):
    rewards = episode.get("rewards")
    if isinstance(rewards, list) and seat < len(rewards):
        reward = rewards[seat]
        if isinstance(reward, (int, float)) and not isinstance(reward, bool):
            return float(reward > 0)
    for step in reversed(episode.get("steps") or []):
        for row in step:
            current = (row.get("observation") or {}).get("current") or {}
            winner = current.get("result", -1)
            if winner in (0, 1):
                return float(winner == seat)
    return None


def canonical_deck(cards: list[int]) -> tuple[int, ...]:
    return tuple(sorted(int(card) for card in cards))


def episode_units(episode: dict, allowed_teams: set[str]):
    """(seat, team, exact_grim, won) for each allowed-team seat."""
    steps = episode.get("steps") or []
    if len(steps) < 2 or len(steps[1]) < 2:
        return []
    decks = [canonical_deck(steps[1][seat].get("action", [])) for seat in (0, 1)]
    if any(len(deck) != 60 for deck in decks):
        return []
    info = episode.get("info") or {}
    teams = info.get("TeamNames") or ["seat-0", "seat-1"]
    units = []
    for seat in (0, 1):
        team = teams[seat] if seat < len(teams) else f"seat-{seat}"
        if team not in allowed_teams:
            continue
        if decks[seat] != GRIM_SIGNATURE:
            continue
        won = episode_reward(episode, seat)
        if won == 1.0:
            units.append({"seat": seat, "team": team})
    return units


def is_forced(select: dict) -> bool:
    options = select.get("option") or []
    if len(options) <= 1:
        return True
    return select.get("minCount") == select.get("maxCount") == len(options)


def episode_order(episode: dict) -> tuple:
    steps = episode.get("steps") or []
    chooser = None
    choice = None
    first_player = None
    for step_index, step in enumerate(steps):
        for seat, row in enumerate(step[:2]):
            current = (row.get("observation") or {}).get("current") or {}
            observed_first = current.get("firstPlayer")
            if observed_first in (0, 1):
                first_player = int(observed_first)
            select = (row.get("observation") or {}).get("select") or {}
            if int(select.get("context", -1)) != 41 or step_index + 1 >= len(steps):
                continue
            chooser = seat
            following = steps[step_index + 1]
            action = following[seat].get("action") if seat < len(following) else None
            if isinstance(action, list) and len(action) == 1:
                options = select.get("option") or []
                selected = options[action[0]] if 0 <= action[0] < len(options) else {}
                if int(selected.get("type", -1)) == 1:
                    choice = "first"
                elif int(selected.get("type", -1)) == 2:
                    choice = "second"
    if chooser is not None and choice is None and first_player in (0, 1):
        choice = "first" if chooser == first_player else "second"
    return chooser, choice, first_player


def walk_episode(episode: dict, seat: int, package_agent):
    """Replay one episode for one seat through a loaded package. Returns records."""
    steps = episode.get("steps") or []
    _, _, first_player = episode_order(episode)
    hero_order = ("first" if seat == first_player else "second") if first_player in (0, 1) else None
    records = []
    errors = 0
    for step_index in range(len(steps) - 1):
        current = steps[step_index]
        if seat >= len(current):
            continue
        row = current[seat]
        if str(row.get("status", "")).upper() != "ACTIVE":
            continue
        obs_dict = row.get("observation") or {}
        if obs_dict.get("current") is None:
            continue
        if obs_dict.get("select") is None:
            try:
                package_agent(obs_dict)
            except Exception:
                errors += 1
            continue
        select = obs_dict["select"]
        options = select.get("option") or []
        if not options:
            continue
        if int(select.get("context", -1)) == SelectContext.IS_FIRST:
            try:
                package_agent(obs_dict)
            except Exception:
                errors += 1
            continue
        following = steps[step_index + 1]
        if seat >= len(following):
            continue
        elite_action = following[seat].get("action")
        if not isinstance(elite_action, list):
            continue
        if not (select["minCount"] <= len(elite_action) <= select["maxCount"]):
            continue
        if len(set(elite_action)) != len(elite_action) or any(
            i < 0 or i >= len(options) for i in elite_action
        ):
            continue
        before = int(getattr(package_agent, "errors", 0) or 0)
        try:
            package_action = list(package_agent(obs_dict))
            pkg_errors = int(getattr(package_agent, "errors", 0) or 0) - before
        except Exception:
            pkg_errors = int(getattr(package_agent, "errors", 0) or 0) - before + 1
            package_action = None
        if package_action is not None:
            if not (select["minCount"] <= len(package_action) <= select["maxCount"]):
                pkg_errors += 1
                package_action = None
            elif len(set(package_action)) != len(package_action) or any(
                i < 0 or i >= len(options) for i in package_action
            ):
                pkg_errors += 1
                package_action = None
        errors += pkg_errors
        records.append(
            {
                "step": step_index,
                "context": int(select.get("context", -1)),
                "n_options": len(options),
                "min_count": int(select.get("minCount", 0)),
                "max_count": int(select.get("maxCount", 0)),
                "forced": is_forced(select),
                "elite_action": [int(i) for i in elite_action],
                "package_action": package_action,
                "package_errors": int(pkg_errors),
                "turn": int((obs_dict.get("current") or {}).get("turn", -1)),
                "hero_order": hero_order,
            }
        )
    return records, errors


# ---------------------------------------------------------------- worker

def _run_worker(task: dict) -> dict:
    from ptcg_ai.external import ExternalSubmissionAgent

    package_dir = Path(task["package"])
    episode_path = Path(task["episode"])
    seat = int(task["seat"])
    package_agent = ExternalSubmissionAgent(package_dir, {})
    try:
        episode = load_episode(episode_path)
        records, errors = walk_episode(episode, seat, package_agent)
        return {
            "episode": episode_path.stem,
            "seat": seat,
            "team": task.get("team"),
            "records": records,
            "errors": errors,
        }
    except Exception as exc:
        return {
            "episode": episode_path.stem,
            "seat": seat,
            "team": task.get("team"),
            "records": [],
            "errors": -1,
            "fatal": f"{type(exc).__name__}: {exc}",
        }
    finally:
        package_agent.close()


def run_package_on_units(package_name: str, package_dir: str, units: list[dict], workers: int) -> list[dict]:
    tasks = [
        {"package": package_dir, "episode": unit["path"], "seat": unit["seat"], "team": unit.get("team")}
        for unit in units
    ]
    context = mp.get_context("spawn")
    results = []
    with context.Pool(min(workers, max(1, len(tasks)))) as pool:
        for result in pool.imap_unordered(_run_worker, tasks, chunksize=1):
            results.append(result)
    return results


# ---------------------------------------------------------------- metric

def classify(obs_dict: dict, elite: list[int], c0: list[int], cand: list[int]) -> str:
    k_e = action_semantic(obs_dict, elite)
    k_c0 = action_semantic(obs_dict, c0)
    k_cand = action_semantic(obs_dict, cand)
    if k_cand == k_c0:
        return "ignored"
    if k_e == k_cand:
        return "cand_approved"
    if k_e == k_c0:
        return "c0_approved"
    return "abstain"


def join_records(units: list[dict], elite_index: dict, runs: dict[str, list[dict]]):
    """Join per-package replays with the recorded elite actions by (episode, seat, step)."""
    elite_rows = {}
    for unit in units:
        for row in elite_index.get((unit["episode"], unit["seat"]), []):
            elite_rows[(unit["episode"], unit["seat"], row["step"])] = row
    joined = defaultdict(dict)
    for name, results in runs.items():
        for result in results:
            if result.get("fatal"):
                continue
            for record in result["records"]:
                key = (result["episode"], result["seat"], record["step"])
                joined[key][name] = record
                joined[key]["meta"] = {
                    "episode": result["episode"],
                    "seat": result["seat"],
                    "team": result.get("team"),
                    "step": record["step"],
                    "context": record["context"],
                    "forced": record["forced"],
                    "turn": record["turn"],
                    "hero_order": record.get("hero_order"),
                }
    return joined, elite_rows


def bootstrap_episode_ratio(rows: list[dict], n_iter: int = 20000, seed: int = 20260816):
    """Rows: one per decisive disagreement with 'episode' and 'cls'."""
    if not rows:
        return {"ratio": None, "ci_low": None, "ci_high": None, "n": 0}
    rng = np.random.default_rng(seed)
    by_episode = defaultdict(list)
    for row in rows:
        by_episode[row["episode"]].append(row["cls"])
    episodes = list(by_episode.keys())
    ratios = []
    for _ in range(n_iter):
        sample = rng.integers(0, len(episodes), size=len(episodes))
        approved = total = 0
        for idx in sample:
            classes = by_episode[episodes[idx]]
            approved += sum(1 for cls in classes if cls == "cand_approved")
            total += sum(1 for cls in classes if cls in ("cand_approved", "c0_approved"))
        ratios.append(approved / total if total else None)
    ratios = [r for r in ratios if r is not None]
    return {
        "ratio": sum(1 for row in rows if row["cls"] == "cand_approved")
        / max(1, sum(1 for row in rows if row["cls"] in ("cand_approved", "c0_approved"))),
        "ci_low": float(np.percentile(ratios, 2.5)),
        "ci_high": float(np.percentile(ratios, 97.5)),
        "n": len(rows),
        "n_episodes": len(episodes),
        "bootstrap_median": float(np.percentile(ratios, 50)),
    }


# ---------------------------------------------------------------- orchestration

def collect_units(raw_dirs: list[Path], allowed_teams: set[str]) -> list[dict]:
    units = []
    for raw_dir in raw_dirs:
        for path in sorted(raw_dir.glob("*.json")):
            try:
                episode = load_episode(path)
            except Exception:
                continue
            for unit in episode_units(episode, allowed_teams):
                units.append(
                    {
                        "episode": path.stem,
                        "path": str(path),
                        "seat": unit["seat"],
                        "team": unit["team"],
                    }
                )
    return units


def elite_index_for(units: list[dict]) -> dict:
    index = defaultdict(list)
    for unit in units:
        episode = load_episode(unit["path"])
        steps = episode.get("steps") or []
        for step_index in range(len(steps) - 1):
            current = steps[step_index]
            if unit["seat"] >= len(current):
                continue
            row = current[unit["seat"]]
            if str(row.get("status", "")).upper() != "ACTIVE":
                continue
            obs_dict = row.get("observation") or {}
            select = obs_dict.get("select") or {}
            options = select.get("option") or []
            if not options or int(select.get("context", -1)) == SelectContext.IS_FIRST:
                continue
            following = steps[step_index + 1]
            if unit["seat"] >= len(following):
                continue
            action = following[unit["seat"]].get("action")
            if not isinstance(action, list):
                continue
            if not (select["minCount"] <= len(action) <= select["maxCount"]):
                continue
            if len(set(action)) != len(action) or any(i < 0 or i >= len(options) for i in action):
                continue
            index[(unit["episode"], unit["seat"])].append(
                {
                    "step": step_index,
                    "obs": obs_dict,
                    "action": [int(i) for i in action],
                }
            )
    return index


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dirs", nargs="+", required=True)
    parser.add_argument("--teams", nargs="+", default=None, help="restrict to these teams")
    parser.add_argument("--candidate", required=True, choices=["exp23", "exp20", "d842"])
    parser.add_argument("--output", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--label", default=None)
    args = parser.parse_args()

    teams = set(args.teams) if args.teams else CERT_TEAMS
    raw_dirs = [Path(p) for p in args.raw_dirs]
    units = collect_units(raw_dirs, teams)
    print(f"units: {len(units)}", flush=True)
    if not units:
        print("no units", flush=True)
        return 1

    elite_index = elite_index_for(units)
    total_elite = sum(len(v) for v in elite_index.values())
    print(f"elite decisions indexed: {total_elite}", flush=True)

    results = {}
    for name in ("c0", args.candidate):
        package_dir = PACKAGES[name]
        if not Path(package_dir).exists():
            raise FileNotFoundError(f"package missing: {package_dir}")
        print(f"replaying {name} on {len(units)} units", flush=True)
        results[name] = run_package_on_units(name, package_dir, units, args.workers)
        ok = sum(1 for r in results[name] if not r.get("fatal"))
        errs = sum(int(r.get("errors", 0) or 0) for r in results[name])
        print(f"  {name}: {ok}/{len(units)} units ok, policy errors {errs}", flush=True)

    joined, elite_rows = join_records(units, elite_index, results)
    decisive = []
    meta_counter = Counter()
    decision_counter = Counter()
    excluded = Counter()
    for key, record in joined.items():
        meta = record["meta"]
        elite_row = elite_rows.get(key)
        if elite_row is None:
            continue
        if "c0" not in record or args.candidate not in record:
            continue
        c0_record = record["c0"]
        cand_record = record[args.candidate]
        if c0_record["package_action"] is None or cand_record["package_action"] is None:
            excluded["policy_error"] += 1
            continue
        if meta["forced"]:
            excluded["forced"] += 1
            continue
        cls = classify(elite_row["obs"], elite_row["action"], c0_record["package_action"], cand_record["package_action"])
        meta_counter["total"] += 1
        decision_counter[cls] += 1
        if cls == "ignored":
            excluded["agreement"] += 1
            continue
        decisive.append(
            {
                "episode": meta["episode"],
                "team": meta["team"],
                "seat": meta["seat"],
                "step": meta["step"],
                "context": meta["context"],
                "turn": meta["turn"],
                "hero_order": meta.get("hero_order"),
                "cls": cls,
                "elite": elite_row["action"],
                "c0": c0_record["package_action"],
                "cand": cand_record["package_action"],
                "obs": elite_row["obs"],
            }
        )

    bootstrap = bootstrap_episode_ratio(decisive)
    per_team = defaultdict(Counter)
    for row in decisive:
        per_team[row["team"]][row["cls"]] += 1
    team_ratios = {}
    for team, counter in sorted(per_team.items()):
        team_ratios[team] = (
            counter["cand_approved"] / max(1, counter["cand_approved"] + counter["c0_approved"]),
            counter["cand_approved"] + counter["c0_approved"],
        )

    output = {
        "label": args.label or f"{args.candidate}_vs_c0",
        "candidate": args.candidate,
        "teams": sorted(teams),
        "units": len(units),
        "total_scored_decisions": meta_counter["total"],
        "decision_classes": dict(decision_counter),
        "excluded": dict(excluded),
        "decisive_n": len(decisive),
        "bootstrap": bootstrap,
        "per_team": {k: {"ratio": v[0], "n": v[1]} for k, v in team_ratios.items()},
    }
    output["elite_approval_ratio"] = bootstrap["ratio"]
    output["episode_clustered_ci"] = [bootstrap["ci_low"], bootstrap["ci_high"]]

    by_turn = defaultdict(Counter)
    by_context = defaultdict(Counter)
    by_order = defaultdict(Counter)
    for row in decisive:
        band = "early" if row["turn"] <= 3 else ("mid" if row["turn"] <= 7 else "late")
        by_turn[band][row["cls"]] += 1
        by_context[row["context"]][row["cls"]] += 1
        by_order[str(row.get("hero_order"))][row["cls"]] += 1
    output["by_turn_band"] = {k: dict(v) for k, v in sorted(by_turn.items())}
    output["by_context"] = {str(k): dict(v) for k, v in sorted(by_context.items())}
    output["by_order"] = {str(k): dict(v) for k, v in sorted(by_order.items())}
    for key in list(by_order.keys()):
        counter = by_order[key]
        order_boot = bootstrap_episode_ratio(
            [r for r in decisive if str(r.get("hero_order")) == str(key)]
        )
        output[f"by_order_{key}_bootstrap"] = order_boot

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=1))
    rows_path = output_path.with_suffix(".rows.jsonl.gz")
    with gzip.open(rows_path, "wt", encoding="utf-8") as handle:
        for row in decisive:
            slim = {k: v for k, v in row.items() if k != "obs"}
            slim["obs_sha256"] = hashlib.sha256(
                json.dumps(row["obs"], sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            handle.write(json.dumps(slim, sort_keys=True) + "\n")
    print(json.dumps(output, indent=1)[:3000], flush=True)
    print(f"rows written: {rows_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
