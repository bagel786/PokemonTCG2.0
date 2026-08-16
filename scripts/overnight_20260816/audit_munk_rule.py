#!/usr/bin/env python3
"""Audit MUNK-RULE on EXP23's live bank: MAIN decisions where EXP23 plays a
basic/support card while an ABILITY (Adrena-Brain) option is also present.
Compare with C0's choice in the same states. If C0 takes the ability and
EXP23 plays support, the substitution is a cheap EXP23->C0-alignment fix."""
import json
import sys
from pathlib import Path

ROOT = Path('/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight')
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT / 'scripts' / 'overnight_20260816'))

from cg.api import all_card_data  # noqa: E402
from ptcg_ai.external import ExternalSubmissionAgent  # noqa: E402
from replay_disagreement import walk_episode  # noqa: E402

CT = {c.cardId: c for c in all_card_data()}
SUPPORT = {103, 104, 112, 860, 646, 647}
REPLAYS = ROOT / 'data' / 'replays' / '55556726'
META = json.load(open(REPLAYS / 'episodes_metadata.json'))
PKGS = {
    'c0': '/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/grim_damage_conversion/winner/extracted',
    'exp23': '/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/final_sprint/exp23_identity_trained',
}


def main() -> None:
    runs = {}
    for label, pkg in PKGS.items():
        agent = ExternalSubmissionAgent(pkg, {})
        runs[label] = {}
        for m in META:
            ours = [a for a in m['agents'] if a.get('submissionId') == 55556726]
            if len(ours) != 1 or ours[0].get('reward') is None:
                continue
            epf = REPLAYS / f"episode-{m['id']}-replay.json"
            try:
                ep = json.load(open(epf))
            except Exception:
                continue
            seat = next(i for i, a in enumerate(m['agents']) if a.get('submissionId') == 55556726)
            records, errs = walk_episode(ep, seat, agent)
            runs[label][m['id']] = {r['step']: r for r in records}
        agent.close()

    fires = 0
    c0_ability = 0
    c0_attack = 0
    c0_play_other = 0
    c0_end = 0
    by_outcome = {}
    for m in META:
        ours = [a for a in m['agents'] if a.get('submissionId') == 55556726]
        if len(ours) != 1 or ours[0].get('reward') is None:
            continue
        epf = REPLAYS / f"episode-{m['id']}-replay.json"
        ep = json.load(open(epf))
        seat = next(i for i, a in enumerate(m['agents']) if a.get('submissionId') == 55556726)
        steps = ep.get('steps') or []
        r_c0 = runs['c0'][m['id']]
        r_e23 = runs['exp23'][m['id']]
        outcome = 'W' if ours[0]['reward'] == 1 else 'L'
        by_outcome.setdefault(outcome, 0)
        for si, re23 in r_e23.items():
            rc0 = r_c0.get(si)
            if rc0 is None or rc0['package_action'] is None or re23['package_action'] is None:
                continue
            if re23['forced']:
                continue
            row = steps[si][seat]
            obs = row.get('observation') or {}
            sel = obs.get('select') or {}
            if int(sel.get('context', -1)) != 0:
                continue
            opts = sel.get('option') or []
            ability_idxs = [i for i, o in enumerate(opts) if int(o.get('type', -1)) == 10]
            if not ability_idxs:
                continue
            cur = obs.get('current') or {}
            p = cur['players'][cur.get('yourIndex', 0)]
            hand = [c for c in (p.get('hand') or []) if c]
            e23_plays_support = False
            for idx in re23['package_action']:
                if 0 <= idx < len(opts):
                    o = opts[idx]
                    if int(o.get('type', -1)) == 7 and o.get('area') is None and 0 <= idx < len(hand):
                        c = hand[idx]
                        if c and c.get('id') in SUPPORT:
                            e23_plays_support = True
            if not e23_plays_support:
                continue
            fires += 1
            by_outcome[outcome] += 1
            # C0's choice kind
            c0kinds = set()
            for idx in rc0['package_action']:
                if 0 <= idx < len(opts):
                    o = opts[idx]
                    t = int(o.get('type', -1))
                    if t == 10:
                        c0kinds.add('ability')
                    elif t == 13:
                        c0kinds.add('attack')
                    elif t == 14:
                        c0kinds.add('end')
                    elif t == 7 and o.get('area') is None and 0 <= idx < len(hand):
                        c = hand[idx]
                        if c and c.get('id') in SUPPORT:
                            c0kinds.add('support_play')
                        else:
                            c0kinds.add('other_play')
            if 'ability' in c0kinds:
                c0_ability += 1
            if 'attack' in c0kinds:
                c0_attack += 1
            if 'support_play' in c0kinds:
                c0_play_other += 1
            if 'end' in c0kinds:
                c0_end += 1
    print(f'fires (EXP23 plays support w/ ability available): {fires}')
    print(f'by outcome: {by_outcome}')
    print(f'C0 chose ability in same spot: {c0_ability} ({c0_ability/max(1,fires):.1%})')
    print(f'C0 chose attack: {c0_attack}, support_play: {c0_play_other}, end: {c0_end}')


if __name__ == '__main__':
    main()
