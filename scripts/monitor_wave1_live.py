#!/usr/bin/env python3
"""Continuously preserve and score wave-one Kaggle ladder evidence.

This watcher is deliberately read-only with respect to Kaggle and Azure.  It
downloads completed rated replays, records frozen opponent ratings from the
episode service, and emits evidence for the live shipping policy.  It never
uploads a submission or changes VM power state.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import math
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.crawl_grim_daily import classify, load_archetype_catalog

COMPETITION = "pokemon-tcg-ai-battle"
EPISODE_URL = "https://www.kaggle.com/api/i/competitions.EpisodeService/ShowEpisode"
AZURE = shutil.which("az.cmd") or shutil.which("az.bat") or shutil.which("az") or "az"
AZURE_WORKERS = (
    ("ptcg-train-south-rg", "ptcg-train"),
    ("ptcg-recovery-centralus-rg", "grim-centralus"),
    ("ptcg-recovery-eastus2-rg", "grim-eastus2"),
    ("ptcg-recovery-northcentralus-rg", "grim-northcentralus"),
    ("ptcg-recovery-westus2-rg", "grim-westus2"),
)


def atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def enum_text(value: object) -> str:
    return str(value).split(".")[-1]


def show_episode(api, episode_id: int) -> dict:
    username = api.config_values.get("username", "")
    key = api.config_values.get("key", "")
    auth = base64.b64encode(f"{username}:{key}".encode()).decode()
    request = urllib.request.Request(
        EPISODE_URL,
        data=json.dumps({"id": int(episode_id)}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Basic {auth}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def rated_games(api, submission_id: int, cached: dict[int, dict]) -> tuple[list[dict], int]:
    games: list[dict] = []
    excluded = 0
    for episode in api.competition_list_episodes(submission_id):
        matching = [agent for agent in episode.agents if int(agent.submission_id) == submission_id]
        if len(matching) == 2:
            excluded += 1
            continue
        if len(matching) != 1:
            continue
        hero = matching[0]
        opponents = [agent for agent in episode.agents if int(agent.submission_id) != submission_id]
        if len(opponents) != 1:
            continue
        opponent = opponents[0]
        episode_id = int(episode.id)
        detail = cached.get(episode_id)
        if detail is None:
            # The list endpoint commonly exposes a just-finished episode several
            # minutes before ShowEpisode does.  Preserve the result now and fill
            # frozen rating metadata on a later poll instead of losing the whole
            # monitoring snapshot to that transient 404.
            try:
                detail = show_episode(api, episode_id)
                cached[episode_id] = detail
            except Exception:
                detail = {}
        agents = detail.get("agents") or []
        hero_detail = next(
            (row for row in agents if int(row.get("submissionId", -1)) == submission_id), {}
        )
        opponent_detail = next(
            (row for row in agents if int(row.get("submissionId", -1)) != submission_id), {}
        )
        created = episode.create_time
        if created.tzinfo is None:
            created = created.replace(tzinfo=dt.timezone.utc)
        state = enum_text(hero.state)
        games.append({
            "episode_id": episode_id,
            "created_unix": created.timestamp(),
            "created_utc": created.isoformat(),
            "seat": int(hero.index),
            "outcome": float(hero.reward),
            "agent_state": state,
            "crash": "ERROR" in state or "INVALID" in state,
            "our_initial_rating": hero_detail.get("initialScore"),
            "our_updated_rating": hero_detail.get("updatedScore"),
            "opponent_initial_rating": opponent_detail.get("initialScore"),
            "opponent_updated_rating": opponent_detail.get("updatedScore"),
            "opponent_submission_id": int(opponent.submission_id),
            "opponent_team_id": int(opponent.team_id),
            "opponent_team_name": str(opponent.team_name),
        })
    games.sort(key=lambda row: (row["created_unix"], row["episode_id"]))
    return games, excluded


def replay_facts(replay: dict, hero_seat: int, catalog: dict[str, tuple[int, ...]]) -> dict:
    steps = replay.get("steps") or []
    opponent_deck: tuple[int, ...] = ()
    if len(steps) > 1 and len(steps[1]) == 2:
        action = steps[1][1 - hero_seat].get("action")
        if isinstance(action, list) and len(action) == 60:
            opponent_deck = tuple(sorted(int(card) for card in action))
    first_player = None
    last = None
    for step in steps:
        for agent in step:
            current = (agent.get("observation") or {}).get("current")
            if not isinstance(current, dict):
                continue
            observed = current.get("firstPlayer")
            if first_player is None and observed in (0, 1):
                first_player = int(observed)
            if len(current.get("players") or []) == 2:
                last = current
    facts = {
        "actual_order": (
            "first" if first_player == hero_seat else "second"
        ) if first_player in (0, 1) else None,
        "opponent_archetype": classify(opponent_deck, catalog),
        "opponent_deck": list(opponent_deck),
    }
    if last is not None:
        hero = last["players"][hero_seat]
        opponent = last["players"][1 - hero_seat]
        facts.update({
            "terminal_turn": int(last.get("turn", 0)),
            "hero_prizes_taken": 6 - len(hero.get("prize") or []),
            "opponent_prizes_taken": 6 - len(opponent.get("prize") or []),
        })
    return facts


def enrich_replays(api, submission_id: int, games: list[dict], output: Path,
                   catalog: dict[str, tuple[int, ...]]) -> None:
    replay_dir = output / "replays" / str(submission_id)
    replay_dir.mkdir(parents=True, exist_ok=True)
    for game in games:
        target = replay_dir / f"episode-{game['episode_id']}-replay.json"
        try:
            if not target.exists() or target.stat().st_size == 0:
                api.competition_episode_replay(game["episode_id"], path=str(replay_dir), quiet=True)
            replay = json.loads(target.read_text(encoding="utf-8"))
            game.update(replay_facts(replay, game["seat"], catalog))
            game["replay_path"] = str(target.resolve())
        except Exception as exc:
            game["replay_pending"] = str(exc)


def beta_rate(rows: list[dict]) -> float:
    wins = sum(float(row["outcome"]) > 0 for row in rows)
    return (wins + 2) / (len(rows) + 4)


def bucket(rows: list[dict]) -> dict:
    wins = sum(float(row["outcome"]) > 0 for row in rows)
    return {
        "games": len(rows),
        "wins": wins,
        "losses": len(rows) - wins,
        "win_rate": wins / len(rows) if rows else None,
        "beta_smoothed_rate": beta_rate(rows),
    }


def assessment(games: list[dict], rating: float | None) -> dict:
    by_order = {name: [g for g in games if g.get("actual_order") == name]
                for name in ("first", "second")}
    mirror = [g for g in games if "grim" in str(g.get("opponent_archetype", "")).lower()]
    mirror_order = {name: [g for g in mirror if g.get("actual_order") == name]
                    for name in ("first", "second")}
    high900 = [g for g in games if float(g.get("opponent_initial_rating") or -math.inf) >= 900]
    high950 = [g for g in games if float(g.get("opponent_initial_rating") or -math.inf) >= 950]
    q_order = 0.5 * beta_rate(by_order["first"]) + 0.5 * beta_rate(by_order["second"])
    q_grim = 0.5 * beta_rate(mirror_order["first"]) + 0.5 * beta_rate(mirror_order["second"])
    lcs = 100 * (0.45 * q_order + 0.25 * q_grim + 0.20 * beta_rate(high900)
                 + 0.10 * beta_rate(high950))
    crashes = sum(bool(g.get("crash")) for g in games)
    recent = games[-10:]
    catastrophic = len(games) >= 20 and sum(g["outcome"] > 0 for g in games) <= 5
    order_catastrophe = any(
        len(rows) >= 8 and not any(g["outcome"] > 0 for g in rows)
        for rows in by_order.values()
    )
    healthy = crashes == 0 and not catastrophic and not order_catastrophe and (
        len(recent) < 10 or sum(g["outcome"] > 0 for g in recent) >= 3
    )
    lock = "none"
    if healthy and rating is not None and rating >= 950:
        lock = "hard"
    elif healthy and rating is not None and rating >= 900:
        lock = "soft"
    return {
        "overall": bucket(games),
        "recent_10": bucket(recent),
        "by_order": {key: bucket(rows) for key, rows in by_order.items()},
        "mirror": bucket(mirror),
        "mirror_by_order": {key: bucket(rows) for key, rows in mirror_order.items()},
        "opponent_900_plus": bucket(high900),
        "opponent_950_plus": bucket(high950),
        "by_archetype": {
            name: bucket([g for g in games if g.get("opponent_archetype") == name])
            for name in sorted({str(g.get("opponent_archetype", "unknown")) for g in games})
        },
        "lcs": lcs,
        "crashes": crashes,
        "healthy": healthy,
        "lock": lock,
        "hard_stop": crashes > 0 or catastrophic or order_catastrophe,
    }


def azure_snapshot(_resource_group: str) -> dict:
    workers = []
    for group, name in AZURE_WORKERS:
        try:
            result = subprocess.run(
                [AZURE, "vm", "get-instance-view", "-g", group, "-n", name,
                 "--query", "instanceView.statuses[?starts_with(code, 'PowerState/')].displayStatus | [0]",
                 "--output", "tsv"],
                capture_output=True, text=True, timeout=45, check=False,
            )
            workers.append({"resource_group": group, "name": name,
                            "power_state": result.stdout.strip() if result.returncode == 0 else None,
                            "error": result.stderr.strip() if result.returncode else None})
        except Exception as exc:
            workers.append({"resource_group": group, "name": name, "error": str(exc)})
    return {"workers": workers}


def observe(args: argparse.Namespace, api, catalog: dict[str, tuple[int, ...]]) -> dict:
    ledger = json.loads((ROOT / args.ledger).read_text(encoding="utf-8"))
    output = ROOT / args.output_dir
    cache_path = output / "episode_metadata.json"
    cached_list = json.loads(cache_path.read_text()) if cache_path.exists() else []
    cached = {int(row["id"]): row["detail"] for row in cached_list}
    remote = {str(row.ref): row for row in api.competition_submissions(COMPETITION, page_size=100)}
    reports = {}
    now = time.time()
    for entry in ledger["submissions"]:
        sid = int(entry["submission_id"])
        row = remote.get(str(sid))
        games, excluded = rated_games(api, sid, cached)
        enrich_replays(api, sid, games, output, catalog)
        rating = None if row is None or row.public_score in (None, "") else float(row.public_score)
        report = {
            "submission_id": sid,
            "mode": entry["mode"],
            "description": entry["description"],
            "rating": rating,
            "kaggle_status": None if row is None else enum_text(row.status),
            "excluded_self_play": excluded,
            "assessment": assessment(games, rating),
            "games": games,
        }
        reports[str(sid)] = report
        atomic_json(output / "games" / f"{sid}.json", games)
    atomic_json(cache_path, [{"id": key, "detail": value} for key, value in sorted(cached.items())])
    snapshot = {
        "observed_unix": now,
        "observed_utc": dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(),
        "reports": reports,
        "azure": azure_snapshot(args.resource_group),
    }
    atomic_json(output / "latest.json", snapshot)
    history = output / "history.jsonl"
    history.parent.mkdir(parents=True, exist_ok=True)
    with history.open("a", encoding="utf-8") as handle:
        compact = {
            "observed_unix": now,
            "azure": snapshot["azure"],
            "reports": {sid: {"rating": report["rating"],
                "assessment": report["assessment"]} for sid, report in reports.items()},
        }
        handle.write(json.dumps(compact, sort_keys=True) + "\n")
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default="artifacts/wave1_push/submission_ledger.json")
    parser.add_argument("--output-dir", default="artifacts/wave1_push/live")
    parser.add_argument("--resource-group", default="ptcg-train-south-rg")
    parser.add_argument("--interval-seconds", type=int, default=240)
    parser.add_argument("--duration-hours", type=float, default=24)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()
    catalog = load_archetype_catalog(ROOT / "freshstart" / "decklists")
    deadline = time.time() + args.duration_hours * 3600
    while True:
        try:
            snapshot = observe(args, api, catalog)
            compact = {sid: {"rating": row["rating"],
                "games": row["assessment"]["overall"]["games"],
                "wins": row["assessment"]["overall"]["wins"],
                "lcs": round(row["assessment"]["lcs"], 2),
                "lock": row["assessment"]["lock"]} for sid, row in snapshot["reports"].items()}
            print(json.dumps({"observed_utc": snapshot["observed_utc"], "reports": compact,
                              "azure": snapshot["azure"]}), flush=True)
        except Exception as exc:
            print(json.dumps({"observed_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                              "error": repr(exc)}), file=sys.stderr, flush=True)
        if args.once or time.time() >= deadline:
            break
        time.sleep(max(30, args.interval_seconds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
