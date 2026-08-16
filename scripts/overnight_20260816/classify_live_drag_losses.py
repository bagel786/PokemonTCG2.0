#!/usr/bin/env python3
"""Classify EXP23's 4 live Dragapult games: find avoidable policy errors.

For each game, walk our seat chronologically. At each ACTIVE decision,
log what our recorded action was and what key alternatives existed:
- could we have evolved into Grimmsnarl ex this turn (candy/Morgrem ready)?
- did we play/bench disposable support (Snorunt/Froslass/extra Munkidori)
  late (turn>=6)?
- did we use Boss; what was the target?
- did we have a replacement Marnie line in play?
Output per-game summary + flagged decisions.
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path('/Users/safiullahbaig/Projects/PokemonTCG2.0-drag-surgical/vendor')))
from cg.api import all_card_data  # noqa: E402

CT = {c.cardId: c for c in all_card_data()}
OV = Path('/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight')
REPLAYS = OV / 'data' / 'replays' / '55556726'
META = json.load(open(REPLAYS / 'episodes_metadata.json'))
GAMES = (93671387, 93673237, 93679642, 93685951)

ID = {
    'impidimp': 646, 'morgrem': 647, 'grim': 648, 'candy': 1079,
    'snorunt': {103, 860}, 'froslass': 104, 'munkidori': 112,
    'boss': 0,  # resolved by name below
    'denergy': 7,
}
BOSS_IDS = {c.cardId for c in all_card_data() if "Boss's Orders" in (c.name or '')}
LILLIE = {c.cardId for c in all_card_data() if "Lillie's Determination" in (c.name or '')}


def zone_names(p, zone_key, ct):
    zone = p.get(zone_key) or []
    out = []
    for card in zone:
        if not card:
            continue
        c = ct.get(card.get('id'))
        out.append((c.name if c else '?', card.get('serial')))
    return out


def hand_counts(p, ct):
    hand = p.get('hand') or []
    return Counter(ct.get(c['id']).name if c and ct.get(c['id']) else '?' for c in hand)


def main() -> None:
    for eid in GAMES:
        d = json.load(open(REPLAYS / f'episode-{eid}-replay.json'))
        steps = d.get('steps') or []
        m = next(x for x in META if x['id'] == eid)
        our = next(i for i, a in enumerate(m['agents']) if a.get('submissionId') == 55556726)
        opp = 1 - our
        result = 'W' if next(a for a in m['agents'] if a.get('submissionId') == 55556726).get('reward') == 1 else 'L'
        print(f'\n========== ep{eid} {result} (we seat {our}) ==========')
        first_grim_turn = None
        grim_evolution_ready_turns = []
        flags = []
        boss_targets = []
        for si in range(len(steps) - 1):
            if our >= len(steps[si]):
                continue
            row = steps[si][our]
            if str(row.get('status', '')).upper() != 'ACTIVE':
                continue
            obs = row.get('observation') or {}
            cur = obs.get('current') or {}
            if not cur or not cur.get('players'):
                continue
            turn = cur.get('turn') or 0
            select = obs.get('select') or {}
            ctx = int(select.get('context', -1))
            options = select.get('option') or []
            action = steps[si + 1][our].get('action') if si + 1 < len(steps) and our < len(steps[si + 1]) else None
            if not isinstance(action, list):
                continue
            # what did we choose
            chosen = []
            for idx in action:
                if 0 <= idx < len(options):
                    o = options[idx]
                    chosen.append((int(o.get('type', -1)), o.get('cardId'), int(o.get('attackId') or 0)))
            p = cur['players'][our]
            p_opp = cur['players'][opp]
            # board state
            act = (p.get('active') or [None])[0]
            act_name = CT.get(act['id']).name if act else 'none'
            bench_names = [CT.get(b['id']).name for b in (p.get('bench') or []) if b]
            hand = hand_counts(p, CT)
            # first grim timing
            if first_grim_turn is None and (act_name == "Marnie's Grimmsnarl ex" or "Marnie's Grimmsnarl ex" in bench_names):
                first_grim_turn = turn
            # evolution readiness: morgrem in play + candy in hand  (or grim in hand + morgrem)
            has_morgrem = "Marnie's Morgrem" in [act_name] + bench_names
            has_candy = hand.get('Rare Candy', 0) > 0
            has_impidimp = "Marnie's Impidimp" in [act_name] + bench_names
            if has_morgrem and has_candy and (turn <= 6):
                grim_evolution_ready_turns.append(turn)
            # late disposable support plays (turn >= 6): playing snorunt/froslass/extra munkidori
            for (otype, cid, attk) in chosen:
                if turn >= 6 and cid in (ID['snorunt'] | {104, 112}):
                    flags.append((turn, si, 'LATE_SUPPORT_PLAY', CT.get(cid).name if CT.get(cid) else cid))
            # Boss usage
            for (otype, cid, attk) in chosen:
                if cid in BOSS_IDS:
                    opp_act = (p_opp.get('active') or [None])[0]
                    opp_act_name = CT.get(opp_act['id']).name if opp_act else 'none'
                    opp_bench = [CT.get(b['id']).name for b in (p_opp.get('bench') or []) if b]
                    boss_targets.append((turn, opp_act_name, opp_bench))
            # track our first grim KO: when our active changes from grim to something else (rough)
        print(f'  first Grim ex turn: {first_grim_turn}')
        print(f'  turns 1-6 with Morgrem+candy in hand (evolvable): {grim_evolution_ready_turns}')
        for t, si, kind, what in flags:
            print(f'  FLAG t{t} {kind}: {what}')
        for t, actn, bench in boss_targets:
            print(f'  BOSS at t{t}: opp active={actn}, opp bench={bench}')
        if not flags:
            print('  (no late support plays flagged)')


if __name__ == '__main__':
    main()
