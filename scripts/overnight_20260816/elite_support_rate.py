#!/usr/bin/env python3
"""Elite late-support-play rate over ALL late drag-online decisions."""
import json
import sys
from pathlib import Path

ROOT = Path('/Users/safiullahbaig/Projects/PokemonTCG2.0-drag-surgical')
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT / 'scripts' / 'overnight_20260816'))

from cg.api import all_card_data  # noqa: E402
from ptcg_ai.external import ExternalSubmissionAgent  # noqa: E402
from replay_disagreement import walk_episode  # noqa: E402

CT = {c.cardId: c for c in all_card_data()}
EPDIR = ROOT / 'artifacts' / 'drag_surgical' / 'elite_episodes'
HITS = json.load(open('/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight/artifacts/overnight_20260816/elite_dragapult_0815.json'))
SUPPORT = {103, 104, 112, 860}
PKG = '/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/grim_damage_conversion/winner/extracted'


def drag_ex_online(obs):
    cur = obs.get('current') or {}
    yi = cur.get('yourIndex', 0)
    for pi, pl in enumerate(cur.get('players') or []):
        if pi == yi:
            continue
        for c in (pl.get('active') or []) + (pl.get('bench') or []):
            if c and c.get('id') == 121:
                return True
    return False


def main() -> None:
    agent = ExternalSubmissionAgent(PKG, {})
    total = 0
    elite_fires = 0
    wins_fire = 0
    losses_fire = 0
    for h in HITS:
        if h['won'] is None:
            continue
        ep = json.load(open(EPDIR / (h['ep'] + '.json')))
        seat = h['grim_seat']
        outcome = 'W' if h['won'] else 'L'
        records, errs = walk_episode(ep, seat, agent)
        steps = ep.get('steps') or []
        for r in records:
            si = r['step']
            if si + 1 >= len(steps) or seat >= len(steps[si]):
                continue
            if r['turn'] < 6:
                continue
            row = steps[si][seat]
            obs = row.get('observation') or {}
            cur = obs.get('current') or {}
            if not cur or not cur.get('players'):
                continue
            if not drag_ex_online(obs):
                continue
            sel = obs.get('select') or {}
            opts = sel.get('option') or []
            p = cur['players'][cur.get('yourIndex', 0)]
            hand = [c for c in (p.get('hand') or []) if c]
            total += 1
            fired = False
            for idx in (r['elite_action'] or []):
                if 0 <= idx < len(opts):
                    o = opts[idx]
                    if int(o.get('type', -1)) == 7 and o.get('area') is None and 0 <= idx < len(hand):
                        c = hand[idx]
                        if c and c.get('id') in SUPPORT:
                            fired = True
                            break
            if fired:
                elite_fires += 1
                if outcome == 'W':
                    wins_fire += 1
                else:
                    losses_fire += 1
    agent.close()
    print(f'elite: total={total} support-plays={elite_fires} ({elite_fires/total:.2%})  W={wins_fire} L={losses_fire}')


if __name__ == '__main__':
    main()
