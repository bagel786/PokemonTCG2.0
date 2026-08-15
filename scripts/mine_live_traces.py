#!/usr/bin/env python3
"""Mine live replay decision traces for causal loss analysis (v2).

Decodes our semantic decisions from live replay JSONs and produces per-game
traces plus board-state timelines, calibrated against the real option format
seen in data/replays.

Usage: .venv/bin/python scripts/mine_live_traces.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from loss_buckets_live import archetype, card_names, pokemon_seen  # noqa: E402

SUBS = (55513649, 55513642, 55491471, 55491464)
REPLAYS = ROOT / "data" / "replays"
OUT = ROOT / "artifacts" / "final_sprint"
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "traces").mkdir(exist_ok=True)

GRIM_LINE = {646, 647, 648}


def safe_pokemon_seen(cur, idx, names, ismon):
    import copy
    c = copy.deepcopy(cur)
    pl = c["players"][idx]
    pl["active"] = [s for s in (pl.get("active") or []) if s]
    pl["bench"] = [s for s in (pl.get("bench") or []) if s]
    pl["discard"] = [s for s in (pl.get("discard") or []) if s]
    return pokemon_seen(c, idx, names, ismon)


def zone(obs, player, area, index):
    cur = obs.get("current") or {}
    players = cur.get("players") or []
    if area is None or index is None:
        return None
    if player is None:
        player = cur.get("yourIndex")
    if player is None or player >= len(players):
        return None
    z = {
        1: obs.get("select", {}).get("deck") or [],
        2: (players[player].get("hand") or []),
        3: (players[player].get("discard") or []),
        4: (players[player].get("active") or []),
        5: (players[player].get("bench") or []),
        6: (players[player].get("prize") or []),
    }.get(area, [])
    if 0 <= index < len(z) and z[index]:
        return int(z[index].get("id") or 0)
    return 0


def board_of(obs, player):
    cur = obs.get("current") or {}
    players = cur.get("players") or []
    if player is None or player >= len(players):
        return None
    pl = players[player]
    cards = [(int(c["id"]), len(c.get("energies") or [])) for c in (pl.get("active") or []) if c]
    bench = [(int(c["id"]), len(c.get("energies") or [])) for c in (pl.get("bench") or []) if c]
    return cards, bench


def target_id(obs, opt):
    cur = obs.get("current") or {}
    you = cur.get("yourIndex")
    if opt.get("inPlayArea") in (4, 5):
        return zone(obs, you, opt.get("inPlayArea"), opt.get("inPlayIndex"))
    return 0


def walk(replay: dict, seat: int) -> list[dict]:
    rows = []
    for step in replay.get("steps", []):
        for row in step:
            obs = row.get("observation") or {}
            cur = obs.get("current")
            if cur is None or cur.get("yourIndex") != seat:
                continue
            if obs.get("select") is None:
                continue
            action = row.get("action") or []
            if not action:
                continue
            rows.append({"obs": obs, "action": action})
    return rows


def game_trace(episode_id, replay, seat, win, opp_arch, sub):
    rows = walk(replay, seat)
    first = None
    setup = []
    play_log, attach_log, evolve_log, attack_log = [], [], [], []
    retreat_log, ability_log, boss_log, punk_log = [], [], [], []
    search_log = []
    first_grim = first_opp_grim = first_attack = None
    first_our_prize = first_opp_prize = None
    our_timeline = {}
    opp_timeline = {}
    last_prizes = None
    for r in rows:
        obs, action = r["obs"], r["action"]
        cur = obs.get("current") or {}
        turn = int(cur.get("turn") or 0)
        fp = cur.get("firstPlayer")
        fp = int(fp) if fp is not None else -1
        if first is None and fp in (0, 1):
            first = fp == seat
        ordinal = (turn + 1) // 2 if seat == fp else turn // 2
        sel = obs.get("select") or {}
        ctx = int(sel.get("context") or 0)
        options = sel.get("option") or []
        eff = sel.get("effect") or sel.get("contextCard") or {}
        eff_id = int(eff.get("id") or 0)
        if turn == 0 and ctx in (1, 2):
            for i in action:
                if isinstance(i, int) and 0 <= i < len(options):
                    cid = zone(obs, seat, options[i].get("area"), options[i].get("index"))
                    setup.append(cid or int(options[i].get("cardId") or 0))
        if ordinal <= 0:
            continue
        for i in action:
            if not isinstance(i, int) or not 0 <= i < len(options):
                continue
            opt = options[i]
            t = int(opt.get("type") or -1)
            if t == 7:  # PLAY: no area in raw option; source is hand[option.index]
                src = int(opt.get("cardId") or 0)
                if not src and opt.get("index") is not None:
                    cur2 = obs.get("current") or {}
                    pls = cur2.get("players") or []
                    if seat is not None and seat < len(pls):
                        hand = pls[seat].get("hand") or []
                        idx = opt.get("index")
                        if 0 <= idx < len(hand) and hand[idx]:
                            src = int(hand[idx].get("id") or 0)
                play_log.append((ordinal, src))
                if src == 1182:
                    boss_log.append(ordinal)
            elif t == 8:  # ATTACH
                tgt = target_id(obs, opt)
                attach_log.append((ordinal, tgt or eff_id or 0))
            elif t == 9:  # EVOLVE
                src = zone(obs, seat, opt.get("area"), opt.get("index")) or int(opt.get("cardId") or 0)
                tgt = target_id(obs, opt)
                evolve_log.append((ordinal, src, tgt))
            elif t == 13:  # ATTACK
                attack_log.append((ordinal, int(opt.get("attackId") or 0)))
                if first_attack is None:
                    first_attack = ordinal
            elif t == 12:
                retreat_log.append(ordinal)
            elif t == 10:
                ability_log.append((ordinal, eff_id))
            # punk prompts
            if eff_id == 648 and ctx == 43:
                punk_log.append((ordinal, "activate"))
            elif eff_id == 648 and ctx == 22:
                punk_log.append((ordinal, "count", action))
            elif eff_id == 648 and ctx == 21:
                tgt = zone(obs, seat, opt.get("inPlayArea"), opt.get("inPlayIndex")) if opt.get("inPlayArea") in (4, 5) else 0
                punk_log.append((ordinal, "target", tgt))
            # search prompts (deck reveals)
            if ctx == 7 and eff_id in (1259, 1152, 1219, 1227):
                cid = zone(obs, seat, 1, opt.get("index"))
                search_log.append((ordinal, eff_id, cid or int(opt.get("cardId") or 0)))
        ob = board_of(obs, seat)
        bb = board_of(obs, 1 - seat)
        if ob is not None:
            our_timeline[ordinal] = ob
            ids = [c for c, _ in ob[0]] + [c for c, _ in ob[1]]
            if first_grim is None and 648 in ids:
                first_grim = ordinal
        if bb is not None:
            opp_timeline[ordinal] = bb
            ids = [c for c, _ in bb[0]] + [c for c, _ in bb[1]]
            if first_opp_grim is None and 648 in ids:
                first_opp_grim = ordinal
        prizes = []
        for p in (cur.get("players") or []):
            if isinstance(p, dict) and isinstance(p.get("prize"), list):
                prizes.append(6 - len(p["prize"]))
        if prizes:
            last_prizes = prizes
            if first_our_prize is None and prizes[seat] > 0:
                first_our_prize = ordinal
            if first_opp_prize is None and prizes[1 - seat] > 0:
                first_opp_prize = ordinal

    def tl_bits(tl, key):
        out = {}
        for k, board in sorted(tl.items()):
            ids = [c for c, _ in board[0]] + [c for c, _ in board[1]]
            e = sum(cc for _, cc in board[0]) + sum(cc for _, cc in board[1])
            if key == "ids":
                out[k] = ids
            elif key == "energy":
                out[k] = e
            elif key == "bench":
                out[k] = len(board[1])
            elif key == "grim":
                out[k] = int(648 in ids)
        return out

    return {
        "episode": episode_id, "sub": sub, "seat": 0 if first else 1, "win": win,
        "arch": opp_arch, "setup": setup,
        "setup_active": setup[0] if setup else 0, "setup_width": len(setup),
        "first_grim": first_grim, "first_opp_grim": first_opp_grim,
        "first_attack": first_attack,
        "first_our_prize": first_our_prize, "first_opp_prize": first_opp_prize,
        "play_log": play_log, "attach_log": attach_log, "evolve_log": evolve_log,
        "attack_log": attack_log, "retreats": retreat_log, "abilities": ability_log,
        "boss": boss_log, "punk": punk_log, "search": search_log,
        "our_ids": tl_bits(our_timeline, "ids"), "our_energy": tl_bits(our_timeline, "energy"),
        "our_bench": tl_bits(our_timeline, "bench"), "opp_grim": tl_bits(opp_timeline, "grim"),
        "opp_energy": tl_bits(opp_timeline, "energy"),
        "last_prizes": last_prizes,
    }


def load_games(sub):
    meta = json.loads((REPLAYS / str(sub) / "episodes_metadata.json").read_text())
    for ep in meta:
        if ep.get("state") != "COMPLETED" or ep.get("type") != "EPISODE_TYPE_PUBLIC":
            continue
        me = next((a for a in ep["agents"] if a.get("submissionId") == sub), None)
        opp = next((a for a in ep["agents"] if a.get("submissionId") != sub), None)
        if me is None or opp is None or me.get("reward") is None:
            continue
        rp = REPLAYS / str(sub) / f"episode-{ep['id']}-replay.json"
        if not rp.exists():
            continue
        seat = me.get("index")
        if seat is None:
            seat = 0
        yield ep["id"], seat, me["reward"], rp


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--sub", type=int, default=0)
    args = ap.parse_args()
    subs = (args.sub,) if args.sub else SUBS
    all_traces = []
    for sub in subs:
        for ep_id, seat, reward, rp in load_games(sub):
            replay = json.loads(rp.read_text())
            names, ismon = card_names()
            best, best_key = None, (-1, -1)
            for step in replay.get("steps", []):
                for row in step:
                    c = (row.get("observation") or {}).get("current")
                    if c and c.get("turn") is not None:
                        key = (int(c.get("turn") or 0), int(c.get("turnActionCount") or 0))
                        if key >= best_key:
                            best_key, best = key, c
            arch = archetype(safe_pokemon_seen(best, 1 - seat, names, ismon)) if best else "unknown"
            t = game_trace(ep_id, replay, seat, reward > 0, arch, sub)
            all_traces.append(t)
            (OUT / "traces" / f"{sub}_{ep_id}.json").write_text(json.dumps(t))
    (OUT / "all_traces.json").write_text(json.dumps(all_traces, indent=1, sort_keys=True))
    print(f"mined {len(all_traces)} games")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
