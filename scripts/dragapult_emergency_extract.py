#!/usr/bin/env python3
"""Extract teacher-seat schema-5 decisions from downloaded Dragapult replays.

For each teacher submission:
  - map episode_id -> hero seat(s) via cached ListEpisodes metadata
  - extract only the hero seat's decisions via ptcg_ai.replay.iter_decisions
  - write per-submission shards with teacher/source metadata and a temporal
    episode-level split (train / validation by episode createTime order)

Usage:
    python3 scripts/dragapult_emergency_extract.py --submission 55456110 --team 16380946 ...
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.replay import iter_decisions, load_episode  # noqa: E402

REPLAY_ROOT = ROOT / "data" / "dragapult_emergency" / "replays"
EP_DIR = ROOT / "data" / "dragapult_emergency" / "episodes"
OUT_ROOT = ROOT / "data" / "dragapult_emergency" / "shards"

DRAGAPULT_CARDS = {119, 120, 121}  # Dreepy, Drakloak, Dragapult ex
_GRIMSNARL_CARDS = {646, 647, 648}  # Marnie's Impidimp, Morgrem, Grimmsnarl ex


def _semantic_option(option: dict) -> tuple:
    numeric = list(option.get("numeric", []))
    stable_numeric = tuple(
        float(value) for index, value in enumerate(numeric) if index not in (9, 10, 11)
    )
    return (
        int(option.get("option_type", -1)),
        int(option.get("context", -1)),
        int(option.get("source_card", 0)),
        int(option.get("target_card", 0)),
        int(option.get("attack_id", 0)),
        int(option.get("area", 0)),
        int(option.get("in_play_area", 0)),
        int(option.get("source_serial", 0)),
        int(option.get("target_serial", 0)),
        stable_numeric,
    )


def action_equivalence_groups(features: dict, action: list[int]) -> list[list[int]]:
    options = features.get("options", [])
    semantics = [_semantic_option(option) for option in options]
    groups: list[list[int]] = []
    for raw_index in action:
        index = int(raw_index)
        if not 0 <= index < len(options):
            raise ValueError(f"invalid action index {index} for {len(options)} options")
        groups.append([candidate for candidate, value in enumerate(semantics)
                       if value == semantics[index]])
    return groups


def deck_sig(deck: list[int]) -> str:
    return hashlib.sha256(json.dumps(sorted(deck)).encode()).hexdigest()[:16]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", nargs="+", type=int, required=True)
    parser.add_argument("--team", nargs="+", type=int, required=True)
    parser.add_argument("--validation-share", type=float, default=0.15)
    parser.add_argument("--require-deck-hash", default="",
                        help="skip hero seats whose deck hash differs from this value")
    args = parser.parse_args()
    assert len(args.submission) == len(args.team)

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    manifest_rows = []
    global_episodes: dict[int, str] = {}
    global_decisions = 0

    for sid, tid in zip(args.submission, args.team):
        ep_blob = json.loads((EP_DIR / f"{sid}.json").read_text())
        episodes = ep_blob.get("result", {}).get("episodes", ep_blob.get("episodes", []))
        seat_by_ep: dict[int, list[int]] = {}
        create_by_ep: dict[int, str] = {}
        status_by_ep: dict[int, str] = {}
        for e in episodes:
            seats = [int(a.get("index", 0)) for a in e.get("agents", []) if a.get("teamId") == tid]
            if seats:
                seat_by_ep[e["id"]] = seats
                create_by_ep[e["id"]] = e.get("createTime", "")
                status_by_ep[e["id"]] = e.get("status", "")

        replay_dir = REPLAY_ROOT / str(sid)
        files = sorted(replay_dir.glob("*.json")) if replay_dir.exists() else []
        ordered = sorted(
            files, key=lambda p: create_by_ep.get(int(p.stem.split("-")[1]), ""))

        rows: list[dict] = []
        per_ep: dict[int, dict] = defaultdict(lambda: {"decisions": 0, "deck": None})
        parse_errors = 0
        for path in ordered:
            try:
                episode = load_episode(path)
            except Exception:
                parse_errors += 1
                continue
            ep_id = int(path.stem.split("-")[1])
            seats = seat_by_ep.get(ep_id, [])
            if not seats:
                continue
            info = episode.get("info") or {}
            names = info.get("TeamNames") or ["seat-0", "seat-1"]
            allowed = {names[s] for s in seats if s < len(names)}
            opponent_deck = None
            steps_1 = (episode.get("steps") or [None, None])[1]
            for seat in range(min(2, len(steps_1) if steps_1 else 0)):
                if seat in seats:
                    continue
                candidate = (steps_1[seat] or {}).get("action") or []
                if len(candidate) == 60:
                    opponent_deck = [int(c) for c in candidate]
            opponent_grimmsnarl = bool(
                opponent_deck and _GRIMSNARL_CARDS & set(opponent_deck))
            opponent_dragapult = bool(
                opponent_deck and DRAGAPULT_CARDS & set(opponent_deck))
            count = 0
            deck = None
            skip = False
            for decision in iter_decisions(episode, allowed, feature_version=5):
                if deck is None:
                    deck = decision.deck
                    if args.require_deck_hash and deck_sig(deck) != args.require_deck_hash:
                        skip = True
                        break
                row = decision.to_json()
                row["source_submission_id"] = sid
                row["teacher_team_id"] = tid
                row["episode_create_time"] = create_by_ep.get(ep_id, "")
                row["opponent_grimmsnarl"] = opponent_grimmsnarl
                row["opponent_dragapult"] = opponent_dragapult
                try:
                    row["action_groups"] = action_equivalence_groups(row["features"], row["action"])
                except ValueError:
                    row["action_groups"] = None
                rows.append(row)
                count += 1
            if skip:
                continue
            per_ep[ep_id]["decisions"] = count
            per_ep[ep_id]["deck"] = deck_sig(deck) if deck else None
            if deck and not (DRAGAPULT_CARDS & set(deck)):
                print(f"  WARN ep {ep_id} hero deck has no Dragapult line: {deck_sig(deck)}",
                      flush=True)

        n_episodes = len(per_ep)
        n_decisions = sum(v["decisions"] for v in per_ep.values())
        episode_ids = sorted(per_ep, key=lambda e: create_by_ep.get(e, ""))
        split_at = max(1, int(len(episode_ids) * (1 - args.validation_share)))
        split_by_ep = {e: ("train" if i < split_at else "validation")
                       for i, e in enumerate(episode_ids)}

        train = [r for r in rows if split_by_ep[r["episode_id"]] == "train"]
        validation = [r for r in rows if split_by_ep[r["episode_id"]] == "validation"]
        # Episode-level balance: every episode contributes equal aggregate
        # influence regardless of how many decisions it produced.
        for chunk in (train, validation):
            by_ep: dict[int, list[dict]] = defaultdict(list)
            for r in chunk:
                by_ep[r["episode_id"]].append(r)
            for ep_rows in by_ep.values():
                weight = 1.0 / len(ep_rows)
                for r in ep_rows:
                    r["sample_weight"] = weight
        out_dir = OUT_ROOT / str(sid)
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, chunk in (("train", train), ("validation", validation)):
            with gzip.open(out_dir / f"{name}.jsonl.gz", "wt", encoding="utf-8",
                           compresslevel=6) as handle:
                for row in sorted(chunk, key=lambda r: (r["episode_id"], r["seat"], r["step"])):
                    row["split"] = name
                    handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        # duplicate episode check across submissions
        dupes = [e for e in per_ep if e in global_episodes]
        for e in per_ep:
            global_episodes[e] = str(sid)

        wins = sum(1 for r in rows if r["reward"] == 1.0)
        losses = sum(1 for r in rows if r["reward"] == 0.0)
        first = sum(1 for r in rows if r.get("hero_order") == "first")
        second = sum(1 for r in rows if r.get("hero_order") == "second")
        main_sel = sum(1 for r in rows if len(r["action"]) > 1)
        deck_sigs = Counter(v["deck"] for v in per_ep.values())
        manifest_rows.append({
            "submission_id": sid, "team_id": tid,
            "episodes": n_episodes, "decisions": n_decisions,
            "train_episodes": len({r["episode_id"] for r in train}),
            "validation_episodes": len({r["episode_id"] for r in validation}),
            "train_decisions": len(train), "validation_decisions": len(validation),
            "wins": wins, "losses": losses, "first": first, "second": second,
            "multi_select_decisions": main_sel,
            "deck_hashes": {k: v for k, v in deck_sigs.items()},
            "duplicate_episodes": dupes,
            "parse_errors": parse_errors,
            "episode_range": [create_by_ep.get(episode_ids[0], "") if episode_ids else None,
                              create_by_ep.get(episode_ids[-1], "") if episode_ids else None],
        })
        global_decisions += n_decisions
        print(json.dumps(manifest_rows[-1], indent=1), flush=True)

    manifest = {
        "teachers": manifest_rows,
        "global_episodes": len(global_episodes),
        "global_decisions": global_decisions,
        "feature_version": 5,
        "split_unit": "whole_episode_temporal",
    }
    (OUT_ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    print("wrote", OUT_ROOT / "manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
