#!/usr/bin/env python3
"""R1 live-loss gate: EXP23 vs R1 chronological replay with public Dragapult detector."""
from __future__ import annotations

import json
import multiprocessing as mp
import sys
from pathlib import Path

ROOT = Path("/Users/safiullahbaig/Projects/pokemonTCG2.0")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(Path("/Users/safiullahbaig/Projects/pokemonTCG2.0-overnight/scripts/overnight_20260816")))

from cg.api import AreaType, OptionType, SelectContext, to_observation_class  # noqa: E402
from ptcg_ai.external import ExternalSubmissionAgent  # noqa: E402

E23 = str(ROOT / "artifacts" / "final_sprint" / "exp23_identity_trained")
R1 = str(ROOT / "artifacts" / "final_r1_drag_gate_20260816" / "r1_tree")
OUT = ROOT / "artifacts" / "final_r1_drag_gate_20260816"
OUT.mkdir(parents=True, exist_ok=True)

DRAG_IDS = {119, 120, 121}
REPLAY_ROOTS = [
    Path("/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight/data/replays/55556726"),
    Path("/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight/data/replays/55562629"),
]

TARGETS = {
    "93730597": ("loss", "normal", 55556726),
    "93673237": ("loss", "normal", 55556726),
    "93671387": ("loss", "normal", 55556726),
    "93745631": ("loss", "normal", 55562629),
    "93755661": ("loss", "normal", 55562629),
    "93699067": ("loss", "structural", 55556726),
    "93685951": ("loss", "structural", 55556726),
    "93679642": ("win", "normal", 55556726),
}


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


_CARD_TABLE = None


def _card_table():
    global _CARD_TABLE
    if _CARD_TABLE is None:
        from cg.api import all_card_data
        _CARD_TABLE = {c.cardId: c for c in all_card_data()}
    return _CARD_TABLE


def prize_value(pokemon) -> int:
    if pokemon is None:
        return 0
    data = _card_table().get(pokemon.id)
    if data is None:
        return 1
    return 3 if data.megaEx else 2 if data.ex else 1


def semantic_key(obs, option_index: int) -> tuple:
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


def action_key(obs, action):
    keys = [semantic_key(obs, i) for i in action if 0 <= i < len(obs.select.option)]
    if len(keys) == 1:
        return keys[0]
    return ("MULTI",) + tuple(sorted(keys))


def zone_list(zone):
    return [c for c in (zone or []) if c is not None]


def opponent_dragapult_evidence(obs) -> bool:
    state = obs.current
    if state is None:
        return False
    players = state.players or []
    if len(players) < 2:
        return False
    opp = players[1 - state.yourIndex]
    for zone_name in ("active", "bench", "discard"):
        for card in zone_list(getattr(opp, zone_name, None)):
            if int(card.id) in DRAG_IDS:
                return True
            for pre in zone_list(getattr(card, "preEvolution", None)):
                if int(pre.id) in DRAG_IDS:
                    return True
    return False


def walk_one(task):
    ep_id, label, tempo, sub = task["episode"], task["label"], task["tempo"], task["sub"]
    path = None
    for root in REPLAY_ROOTS:
        if str(root).endswith(str(sub)):
            cand = root / f"episode-{ep_id}-replay.json"
            if cand.exists():
                path = cand
    if path is None:
        return {"episode": ep_id, "fatal": "replay missing"}
    meta_root = path.parent
    meta = json.loads((meta_root / "episodes_metadata.json").read_text())
    seat = next(i for m in meta if str(m["id"]) == str(ep_id)
                for i, a in enumerate(m["agents"]) if str(a.get("submissionId")) == str(sub))
    e23 = ExternalSubmissionAgent(E23, {})
    r1 = ExternalSubmissionAgent(R1, {})
    episode = json.loads(path.read_text())
    detected = False
    locked = False
    lock_step = None
    divergences = []
    decisions = 0
    errors = 0
    steps = episode.get("steps") or []
    try:
        for step_index in range(len(steps) - 1):
            row = steps[step_index]
            entry = row[seat] if row and seat < len(row) else None
            obs_raw = (entry or {}).get("observation") or {}
            if not obs_raw.get("select") or not obs_raw.get("current"):
                continue
            obs = to_observation_class(obs_raw)
            if obs.select.option is None or len(obs.select.option) == 0:
                continue
            decisions += 1
            if opponent_dragapult_evidence(obs):
                detected = True
            try:
                act_e23 = e23(obs_raw)
                act_r1 = r1(obs_raw)
            except Exception as exc:
                errors += 1
                continue
            key_e = action_key(obs, act_e23)
            key_r = action_key(obs, act_r1)
            ctx = int(obs.select.context)
            if not locked and detected and ctx == int(SelectContext.MAIN):
                locked = True
                lock_step = step_index
            if locked and key_e != key_r:
                cur = obs.current
                opp = cur.players[1 - cur.yourIndex]
                ours = cur.players[cur.yourIndex]
                our_active = (zone_list(ours.active) or [None])[0]
                opp_active = (zone_list(opp.active) or [None])[0]
                board = {
                    "turn": int(cur.turn),
                    "our_active": int(our_active.id) if our_active is not None else None,
                    "our_active_hp": int(our_active.hp) if our_active is not None else None,
                    "opp_active": int(opp_active.id) if opp_active is not None else None,
                    "opp_active_hp": int(opp_active.hp) if opp_active is not None else None,
                    "our_prizes": len(zone_list(ours.prize)),
                    "opp_prizes": len(zone_list(opp.prize)),
                }
                divergences.append({
                    "step": step_index,
                    "turn": int(cur.turn),
                    "context": ctx,
                    "order": "first" if int(cur.firstPlayer) == seat else "second",
                    "board": board,
                    "exp23_action": key_e,
                    "r1_action": key_r,
                    "exp23_indices": [int(i) for i in act_e23],
                    "r1_indices": [int(i) for i in act_r1],
                })
        return {
            "episode": ep_id, "label": label, "tempo": tempo, "seat": seat,
            "decisions": decisions, "detected": detected, "lock_step": lock_step,
            "locked": locked, "divergences": divergences, "errors": errors,
        }
    except Exception as exc:
        return {"episode": ep_id, "fatal": f"{type(exc).__name__}: {exc}", "errors": errors}
    finally:
        try:
            e23.close()
            r1.close()
        except Exception:
            pass


def main():
    tasks = [{"episode": e, "label": v[0], "tempo": v[1], "sub": v[2]} for e, v in TARGETS.items()]
    results = []
    with mp.Pool(8, maxtasksperchild=1) as pool:
        for res in pool.map(walk_one, tasks):
            results.append(res)
    results.sort(key=lambda r: r["episode"])
    (OUT / "live_divergences.json").write_text(json.dumps(results, indent=1))
    for r in results:
        print(r["episode"], r["label"], r["tempo"], "locked", r.get("locked"), "at step", r.get("lock_step"),
              "dec", r.get("decisions"), "div", len(r.get("divergences", [])), "err", r.get("errors"), r.get("fatal", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
