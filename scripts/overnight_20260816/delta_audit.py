#!/usr/bin/env python3
"""Delta audit: on decisions where EXP23 plays late support vs online Dragapult
AND C0 does NOT, what does elite do? Elite agreement with C0's exact action
would support a narrow C0-fallback rule."""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path('/Users/safiullahbaig/Projects/PokemonTCG2.0-drag-surgical')
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT / 'scripts' / 'overnight_20260816'))

from cg.api import all_card_data, to_observation_class  # noqa: E402
from ptcg_ai.external import ExternalSubmissionAgent  # noqa: E402
from replay_disagreement import walk_episode  # noqa: E402

CT = {c.cardId: c for c in all_card_data()}
EPDIR = ROOT / 'artifacts' / 'drag_surgical' / 'elite_episodes'
HITS = json.load(open('/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight/artifacts/overnight_20260816/elite_dragapult_0815.json'))
SUPPORT = {103, 104, 112, 860}
PKGS = {
    'c0': '/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/grim_damage_conversion/winner/extracted',
    'exp23': '/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/final_sprint/exp23_identity_trained',
}


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


def elite_index(ep, seat):
    steps = ep.get('steps') or []
    index = {}
    for si in range(len(steps) - 1):
        if seat >= len(steps[si]):
            continue
        row = steps[si][seat]
        if str(row.get('status', '')).upper() != 'ACTIVE':
            continue
        obs = row.get('observation') or {}
        sel = obs.get('select') or {}
        opts = sel.get('option') or []
        if not opts or int(sel.get('context', -1)) == 41:
            continue
        following = steps[si + 1]
        if seat >= len(following):
            continue
        act = following[seat].get('action')
        if not isinstance(act, list):
            continue
        if not (sel['minCount'] <= len(act) <= sel['maxCount']):
            continue
        if len(set(act)) != len(act) or any(i < 0 or i >= len(opts) for i in act):
            continue
        index[si] = {'obs': obs, 'action': [int(i) for i in act]}
    return index


def play_support(obs, action):
    cur = obs.get('current') or {}
    p = (cur.get('players') or [None])[cur.get('yourIndex', 0)]
    hand = [c for c in (p.get('hand') or []) if c] if p else []
    sel = obs.get('select') or {}
    opts = sel.get('option') or []
    for idx in action:
        if 0 <= idx < len(opts):
            o = opts[idx]
            if int(o.get('type', -1)) == 7 and o.get('area') is None and 0 <= idx < len(hand):
                c = hand[idx]
                if c and c.get('id') in SUPPORT:
                    return True
    return False


def main() -> None:
    runs = {}
    for label, pkg in PKGS.items():
        agent = ExternalSubmissionAgent(pkg, {})
        runs[label] = {}
        for h in HITS:
            if h['won'] is None:
                continue
            ep = json.load(open(EPDIR / (h['ep'] + '.json')))
            records, errs = walk_episode(ep, h['grim_seat'], agent)
            runs[label][h['ep']] = {r['step']: r for r in records}
        agent.close()

    n_delta = 0
    elite_matches_c0 = 0
    elite_plays_support = 0
    outcomes = Counter()
    agree_by_outcome = Counter()
    support_by_outcome = Counter()
    for h in HITS:
        if h['won'] is None:
            continue
        ep = json.load(open(EPDIR / (h['ep'] + '.json')))
        eidx = elite_index(ep, h['grim_seat'])
        r_c0 = runs['c0'][h['ep']]
        r_e23 = runs['exp23'][h['ep']]
        for si, erow in eidx.items():
            rc0 = r_c0.get(si)
            re23 = r_e23.get(si)
            if rc0 is None or re23 is None:
                continue
            if rc0['package_action'] is None or re23['package_action'] is None:
                continue
            if re23['turn'] < 6:
                continue
            obs = erow['obs']
            if not drag_ex_online(obs):
                continue
            if re23['forced']:
                continue
            if not play_support(obs, re23['package_action']):
                continue
            if play_support(obs, rc0['package_action']):
                continue
            n_delta += 1
            oc = 'W' if h['won'] else 'L'
            outcomes[oc] += 1
            if rc0['package_action'] == erow['action']:
                elite_matches_c0 += 1
                agree_by_outcome[oc] += 1
            if play_support(obs, erow['action']):
                elite_plays_support += 1
                support_by_outcome[oc] += 1
    print(f'delta decisions (EXP23 support, C0 not): {n_delta}')
    print(f'outcomes: {dict(outcomes)}')
    print(f'elite exact-matches C0 action: {elite_matches_c0} ({elite_matches_c0/max(1,n_delta):.1%})')
    print(f'agreement by outcome: {dict(agree_by_outcome)} / fires {dict(outcomes)}')
    print(f'elite plays support: {elite_plays_support} ({elite_plays_support/max(1,n_delta):.1%}) by outcome {dict(support_by_outcome)}')


if __name__ == '__main__':
    main()
