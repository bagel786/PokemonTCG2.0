#!/usr/bin/env python3
"""Final target residual screen: census + split manifest + row mining."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import sys
import zlib
from collections import Counter
from pathlib import Path

ROOT = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import ptcg_ai.features as _features  # noqa: E402

_features.PLAY_IDENTITY_ENABLED = True

from ptcg_ai.replay import episode_reward, iter_decisions  # noqa: E402
from training.lucario_data import canonical_deck, load_deck  # noqa: E402

OUT = ROOT / "artifacts" / "final_target_residual_20260816"
OUT.mkdir(parents=True, exist_ok=True)

GRIM = load_deck(ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv")
GRIM_SIG = tuple(sorted(GRIM))
GRIM_HASH = hashlib.sha256(json.dumps(list(GRIM_SIG)).encode()).hexdigest()
DRAGAPULT_FAMILY = {119, 120, 121}      # Dreepy, Drakloak, Dragapult ex
CRUSTLE_FAMILY = {344, 345, 756}        # Dwebble, Crustle, Mega Kangaskhan ex

EPISODES_DIR = Path("/Users/safiullahbaig/Projects/PokemonTCG2.0-drag-surgical/artifacts/drag_surgical/elite_episodes")
MANIFEST = json.load(open("/Users/safiullahbaig/Projects/PokemonTCG2.0-drag-surgical/artifacts/drag_surgical/elite_dragapult_0815.json"))

HELDOUT_RAW = Path("/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight/artifacts/overnight_20260816/heldout_raw")


def family_of(deck: list[int]) -> str | None:
    s = set(deck)
    if DRAGAPULT_FAMILY & s and 121 in s:
        return "dragapult_family"
    if CRUSTLE_FAMILY & s and 345 in s:
        return "crustle_kangaskhan_family"
    return None


def scan_heldout_raw() -> list[dict]:
    rows = []
    for day in ("2026-08-13", "2026-08-14", "2026-08-15"):
        d = HELDOUT_RAW / day
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.json")):
            try:
                head = path.open("rb").read(500_000)
                import re
                m = re.search(rb'"action":\s*\[\[([^\]]*)\],\s*\[([^\]]*)\]', head)
                if not m:
                    continue
                a = tuple(sorted(int(x) for x in m.group(1).split(b",") if x.strip()))
                b = tuple(sorted(int(x) for x in m.group(2).split(b",") if x.strip()))
                if len(a) != 60 or len(b) != 60:
                    continue
                decks = [a, b]
                for seat in (0, 1):
                    if decks[seat] == GRIM_SIG:
                        fam = family_of(decks[1 - seat])
                        if fam:
                            ep = json.loads(path.read_text())
                            info = ep.get("info") or {}
                            rows.append({
                                "episode_id": str(info.get("EpisodeId", path.stem)),
                                "date": day,
                                "grim_seat": seat,
                                "target_family": fam,
                                "won": episode_reward(ep, seat) == 1.0,
                                "grim_team": (info.get("TeamNames") or ["s0", "s1"])[seat],
                                "opp_team": (info.get("TeamNames") or ["s0", "s1"])[1 - seat],
                                "source": "heldout_raw",
                            })
            except Exception:
                continue
    return rows


def mine_one(x: dict, dev_ids: set):
    import gzip as _gz
    path = Path(x["path"])
    try:
        ep = json.loads(path.read_text())
    except Exception as e:
        return x["episode_id"], "parse_fail", str(e)
    rows = []
    try:
        for rec in iter_decisions(ep, {x["grim_team"]}, feature_version=2):
            row = rec.to_json()
            if int(row.get("seat", -1)) != x["grim_seat"]:
                continue
            row["target_family"] = x["target_family"]
            row["opp_team"] = x["opp_team"]
            row["grim_team"] = x["grim_team"]
            row["result"] = "grim_win" if x["won"] else "grim_loss"
            row["source_date"] = x["date"]
            row["split"] = "dev" if x["episode_id"] in dev_ids else "holdout"
            rows.append(row)
    except Exception as e:
        return x["episode_id"], "iter_fail", str(e)
    return x["episode_id"], rows, None


def main() -> int:
    census = {"grim_deck_hash": GRIM_HASH, "dates": {}, "heldout_raw_scan": {}}
    units = []
    for row in MANIFEST:
        eid = row["ep"]
        path = EPISODES_DIR / f"{eid}.json"
        units.append({
            "episode_id": eid,
            "path": str(path),
            "grim_seat": row["grim_seat"],
            "grim_team": row["grim_team"],
            "opp_team": row["opp_team"],
            "won": bool(row["won"]),
            "date": "2026-08-15",
            "target_family": "dragapult_family",
        })
    extra = scan_heldout_raw()
    census["heldout_raw_scan"]["games"] = len(extra)
    census["heldout_raw_scan"]["dragapult"] = sum(1 for x in extra if x["target_family"] == "dragapult_family")
    census["heldout_raw_scan"]["crustle"] = sum(1 for x in extra if x["target_family"] == "crustle_kangaskhan_family")
    census["heldout_raw_scan"]["by_date"] = dict(Counter(x["date"] for x in extra))
    census["heldout_raw_scan"]["dragapult_wins"] = sum(1 for x in extra if x["target_family"] == "dragapult_family" and x["won"])

    dates = Counter(x["date"] for x in units)
    wins = [x for x in units if x["won"]]
    losses = [x for x in units if not x["won"]]
    census["dates"]["2026-08-15"] = {
        "episodes": len(units), "wins": len(wins), "losses": len(losses),
        "grim_teams": len({x["grim_team"] for x in units}),
        "opp_teams": len({x["opp_team"] for x in units}),
        "win_grim_teams": len({x["grim_team"] for x in wins}),
        "win_opp_teams": len({x["opp_team"] for x in wins}),
    }

    # Phase B: stable hash split grouped by (grim_team, opp_team)
    dev, hold = [], []
    for x in units:
        h = zlib.crc32(f"{x['grim_team']}||{x['opp_team']}".encode()) % 100
        (dev if h < 70 else hold).append(x)
    split = {
        "rule": "crc32(grim_team||opp_team)%100 < 70 -> dev; else sealed holdout",
        "dev_episodes": len(dev), "holdout_episodes": len(hold),
        "dev_wins": sum(1 for x in dev if x["won"]), "holdout_wins": sum(1 for x in hold if x["won"]),
        "dev_losses": sum(1 for x in dev if not x["won"]), "holdout_losses": sum(1 for x in hold if not x["won"]),
        "dev_grim_teams": len({x["grim_team"] for x in dev}),
        "holdout_grim_teams": len({x["grim_team"] for x in hold}),
        "dev_opp_teams": len({x["opp_team"] for x in dev}),
        "holdout_opp_teams": len({x["opp_team"] for x in hold}),
        "team_pairs_disjoint": ({(x["grim_team"], x["opp_team"]) for x in dev} & {(x["grim_team"], x["opp_team"]) for x in hold}) == set(),
        "dev_episodes": [x["episode_id"] for x in sorted(dev, key=lambda r: r["episode_id"])],
        "holdout_episodes": [x["episode_id"] for x in sorted(hold, key=lambda r: r["episode_id"])],
    }
    (OUT / "census.json").write_text(json.dumps(census, indent=1, sort_keys=True))
    (OUT / "split_manifest.json").write_text(json.dumps(split, indent=1, sort_keys=True))
    print("CENSUS", json.dumps(census, sort_keys=True))
    print("SPLIT", {k: v for k, v in split.items() if not isinstance(v, list)})

    # Phase C input: mine rows for all 175 episodes
    import multiprocessing as mp
    dev_ids = set(split["dev_episodes"])
    from functools import partial
    worker = partial(mine_one, dev_ids=dev_ids)
    all_rows = {"dev_wins": [], "hold_wins": [], "losses": []}
    n_done = 0
    with mp.Pool(8, maxtasksperchild=1) as pool:
        for eid, rows, err in pool.map(worker, units, chunksize=2):
            n_done += 1
            if err:
                print("ERR", eid, err, file=sys.stderr)
                continue
            if not rows:
                continue
            key = "losses" if rows[0]["result"] == "grim_loss" else ("dev_wins" if rows[0]["split"] == "dev" else "hold_wins")
            all_rows[key].extend(rows)
    def write_rows(name, rows):
        path = OUT / name
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        return len(rows)
    counts = {}
    counts["target_wins_dev"] = write_rows("target_wins_dev.jsonl.gz", all_rows["dev_wins"])
    counts["target_wins_holdout"] = write_rows("target_wins_holdout.jsonl.gz", all_rows["hold_wins"])
    counts["target_losses_audit"] = write_rows("target_losses_audit.jsonl.gz", all_rows["losses"])
    print("ROWS", counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
