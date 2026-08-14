#!/usr/bin/env python3
"""Build the Dragapult teacher manifest from downloaded replays + shards.

Writes artifacts/dragapult_emergency/teacher_manifest.json with per-teacher:
deck hash, episodes, decisions, win/loss/draw, order split, opponent
archetypes, date range, dupes, failures.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REPLAY_ROOT = ROOT / "data" / "dragapult_emergency" / "replays"
EP_DIR = ROOT / "data" / "dragapult_emergency" / "episodes"
OUT = ROOT / "artifacts" / "dragapult_emergency"
CARD_CSV = ROOT / "freshstart" / "data" / "EN_Card_Data.csv"

_name: dict[int, str] = {}
_stage: dict[int, str] = {}
_prev: dict[int, str] = {}
if CARD_CSV.exists():
    for row in csv.DictReader(CARD_CSV.read_text(encoding="utf-8-sig").splitlines()):
        cid = int(row["Card ID"])
        _name[cid] = row["Card Name"]
        _stage[cid] = row["Stage (Pokémon)/Type (Energy and Trainer)"]
        _prev[cid] = row["Previous stage"]


def family_root(cid: int, depth: int = 0) -> str:
    p = _prev.get(cid, "n/a")
    if p in ("n/a", "", None) or depth > 3 or p not in _name:
        return _name.get(cid, str(cid))
    return family_root(int(p), depth + 1)


def archetype(deck: list[int]) -> str:
    counts = Counter(deck)
    fam: dict[str, list] = defaultdict(lambda: [0, None, 0])
    for cid, n in counts.items():
        if _stage.get(cid) not in {"Basic Pokémon", "Stage 1 Pokémon", "Stage 2 Pokémon"}:
            continue
        f = fam[family_root(cid)]
        f[0] += n
        f[1] = _name.get(cid)
        f[2] = {"Basic Pokémon": 0, "Stage 1 Pokémon": 1, "Stage 2 Pokémon": 2}[_stage[cid]]
    if not fam:
        return "unknown"
    order = sorted(fam.values(), key=lambda v: (-v[0], -v[2]))
    return " / ".join(v[1] for v in order[:2])


def deck_sig(deck: list[int]) -> str:
    return hashlib.sha256(json.dumps(sorted(deck)).encode()).hexdigest()[:16]


def main() -> int:
    shards = json.loads((ROOT / "data/dragapult_emergency/shards/manifest.json").read_text())
    teachers = shards["teachers"]
    for teacher in teachers:
        sid = teacher["submission_id"]
        tid = teacher["team_id"]
        ep_blob = json.loads((EP_DIR / f"{sid}.json").read_text())
        episodes = ep_blob.get("result", {}).get("episodes", ep_blob.get("episodes", []))
        by_id = {e["id"]: e for e in episodes}
        opponents: Counter[str] = Counter()
        hero_seat_stats = {"seat0": 0, "seat1": 0}
        reward_stats = Counter()
        replay_dir = REPLAY_ROOT / str(sid)
        scanned = 0
        for path in sorted(replay_dir.glob("*.json")) if replay_dir.exists() else []:
            try:
                replay = json.loads(path.read_text())
            except Exception:
                continue
            scanned += 1
            ep_id = replay.get("info", {}).get("EpisodeId")
            ep = by_id.get(ep_id, {})
            seats = [int(a.get("index", 0)) for a in ep.get("agents", [])
                     if a.get("teamId") == tid]
            steps = replay.get("steps") or []
            if len(steps) < 2:
                continue
            for seat in range(min(2, len(steps[1]))):
                action = (steps[1][seat] or {}).get("action") or []
                if len(action) != 60:
                    continue
                deck = [int(c) for c in action]
                if seat in seats:
                    hero_seat_stats[f"seat{seat}"] += 1
                else:
                    opponents[archetype(deck)] += 1
            for agent in ep.get("agents", []):
                if agent.get("teamId") == tid and agent.get("reward") is not None:
                    reward_stats[int(agent["reward"])] += 1
        teacher["opponent_archetypes"] = dict(opponents.most_common())
        teacher["hero_seat_split"] = hero_seat_stats
        teacher["hero_episode_rewards"] = {str(k): v for k, v in reward_stats.items()}
        teacher["replays_scanned"] = scanned
        teacher["deck_hash"] = (list(teacher["deck_hashes"].keys()) or [None])[0]
        del teacher["deck_hashes"]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "teacher_manifest.json").write_text(
        json.dumps(teachers, indent=1, sort_keys=True))
    print(json.dumps(teachers, indent=1)[:3000])
    print("wrote", OUT / "teacher_manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
