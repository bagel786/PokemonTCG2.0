#!/usr/bin/env python3
"""Turn-by-turn narrative of EXP23's 4 live Dragapult games."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path('/Users/safiullahbaig/Projects/PokemonTCG2.0-drag-surgical/vendor')))
from cg.api import all_card_data  # noqa: E402

CT = {c.cardId: c for c in all_card_data()}
OV = Path('/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight')
REPLAYS = OV / 'data' / 'replays' / '55556726'
META = json.load(open(REPLAYS / 'episodes_metadata.json'))
GAMES = (93671387, 93673237, 93685951, 93679642)

OPTYPE = {0: 'MAIN', 1: 'PLAY', 2: 'ATTACH', 3: 'EVOLVE', 4: 'ABILITY', 5: 'DISCARD',
          6: 'RETREAT', 7: 'ATTACK', 8: 'END'}


def card_name(c):
    if not c:
        return 'none'
    x = CT.get(c.get('id'))
    return x.name if x else '?'


def short_hand(p):
    hand = p.get('hand') or []
    out = []
    for c in hand:
        if c and CT.get(c.get('id')):
            n = CT[c['id']].name
            out.append(n.replace("Marnie's ", '').replace(' ex', '').replace('Basic {D} Energy', 'D')
                       .replace("Buddy-Buddy Poffin", 'Poffin').replace("Lillie's Determination", 'Lillie')
                       .replace("Boss's Orders", 'Boss').replace("Boss’s Orders", 'Boss')
                       .replace('Rare Candy', 'Candy').replace('Night Stretcher', 'Stretcher')
                       .replace('Spikemuth Gym', 'Spikemuth').replace('Unfair Stamp', 'Stamp')
                       .replace('Dawn', 'Dawn').replace('Team Rocket', 'Petrel')[:14])
    return out


def main() -> None:
    for eid in GAMES:
        d = json.load(open(REPLAYS / f'episode-{eid}-replay.json'))
        steps = d.get('steps') or []
        m = next(x for x in META if x['id'] == eid)
        our = next(i for i, a in enumerate(m['agents']) if a.get('submissionId') == 55556726)
        opp = 1 - our
        result = 'W' if next(a for a in m['agents'] if a.get('submissionId') == 55556726).get('reward') == 1 else 'L'
        print(f'\n================ ep{eid} {result} (we seat {our}) ================')
        last_turn = None
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
            if turn == last_turn:
                continue
            last_turn = turn
            p = cur['players'][our]
            po = cur['players'][opp]
            act = (p.get('active') or [None])[0]
            bench = [b for b in (p.get('bench') or []) if b]
            act_n = card_name(act)
            bench_n = [card_name(b) for b in bench]
            opp_act = (po.get('active') or [None])[0]
            opp_bench = [b for b in (po.get('bench') or []) if b]
            hand = short_hand(p)
            # energies on our active
            en = act.get('energies') or [] if act else []
            print(f't{turn:2d} OUR act={act_n}({len(en)}en) bench={bench_n} | OPP act={card_name(opp_act)} bench={[card_name(b) for b in opp_bench]}')
            print(f'      hand({len(p.get("hand") or [])}): {hand}')


if __name__ == '__main__':
    main()
