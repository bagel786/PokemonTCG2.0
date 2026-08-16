#!/usr/bin/env python3
"""Audit candidate Dragapult surgical rules on the 175 elite games (v2):
replay EXP23, join with elite decisions, score three narrow rules."""
import json
import sys
from collections import Counter, defaultdict
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
PKG = '/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/final_sprint/exp23_identity_trained'

DRAG_IDS = {119, 120, 121}
SUPPORT = {103, 104, 112, 860}
MARNIE = {646, 647, 648}


def name(c):
    if not c:
        return None
    return CT.get(c.get('id')).name if CT.get(c.get('id')) else None


def elite_index_for(ep, seat):
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


def opp_public_ids(obs):
    cur = obs.get('current') or {}
    players = cur.get('players') or []
    ids = set()
    for pl in players:
        for z in ('active', 'bench', 'discard'):
            for c in (pl.get(z) or []):
                if c and c.get('id') is not None:
                    ids.add(c['id'])
    return ids


def drag_confirmed(obs):
    return bool(opp_public_ids(obs) & DRAG_IDS)


def drag_ex_online(obs):
    cur = obs.get('current') or {}
    players = cur.get('players') or []
    yi = cur.get('yourIndex', 0)
    for pi, pl in enumerate(players):
        if pi == yi:
            continue
        for c in (pl.get('active') or []) + (pl.get('bench') or []):
            if c and c.get('id') == 121:
                return True
    return False


def main() -> None:
    agent = ExternalSubmissionAgent(PKG, {})
    stats = defaultdict(lambda: Counter())
    for h in HITS:
        if h['won'] is None:
            continue
        ep = json.load(open(EPDIR / (h['ep'] + '.json')))
        seat = h['grim_seat']
        outcome = 'W' if h['won'] else 'L'
        records, errs = walk_episode(ep, seat, agent)
        eidx = elite_index_for(ep, seat)
        by_step = {r['step']: r for r in records if r['package_action'] is not None}
        for si, erow in eidx.items():
            rec = by_step.get(si)
            if rec is None or rec['forced']:
                continue
            obs = erow['obs']
            if not drag_confirmed(obs):
                continue
            cur = obs.get('current') or {}
            turn = rec['turn']
            pkg_act = rec['package_action']
            elite_act = erow['action']
            sel = obs.get('select') or {}
            opts = sel.get('option') or []
            p = (cur.get('players') or [None])[cur.get('yourIndex', 0)]
            if not p:
                continue
            hand = [c for c in (p.get('hand') or []) if c]
            act = (p.get('active') or [None])[0]
            bench = [b for b in (p.get('bench') or []) if b]
            inplay_names = {name(c) for c in [act] + bench if c}
            hand_names = {name(c) for c in hand}
            for rule in ('A', 'B', 'C'):
                stats[rule]['drag_decisions'] += 1

            def srcs(action):
                out = set()
                for idx in action:
                    if 0 <= idx < len(opts):
                        o = opts[idx]
                        if int(o.get('type', -1)) == 1 and o.get('area') is None:
                            c = (hand[idx] if 0 <= idx < len(hand) else None)
                            out.add(name(c))
                return out

            # RULE A: no Marnie line in play, Marnie in hand, EXP23 plays support basic
            marnie_in_hand = bool(hand_names & {"Marnie's Impidimp", "Marnie's Morgrem"})
            marnie_in_play = bool(inplay_names & {"Marnie's Impidimp", "Marnie's Morgrem", "Marnie's Grimmsnarl ex"})
            if not marnie_in_play and marnie_in_hand:
                if srcs(pkg_act) & {'Snorunt', 'Froslass', 'Munkidori'}:
                    stats['A']['fires'] += 1
                    stats['A'][outcome] += 1
                    if srcs(elite_act) & {"Marnie's Impidimp", "Marnie's Morgrem"}:
                        stats['A']['elite_prefers_marnie'] += 1
            # RULE B: unpowered bench Munk + EXP23 attaches dark energy elsewhere (to attacker)
            benched_munk_unpowered = [b for b in bench if b and b.get('id') == 112 and not (b.get('energies') or [])]
            if benched_munk_unpowered:
                pkg_attach = set()
                for idx in pkg_act:
                    if 0 <= idx < len(opts):
                        o = opts[idx]
                        if int(o.get('type', -1)) == 2 and o.get('area') is None:
                            c = (hand[idx] if 0 <= idx < len(hand) else None)
                            pkg_attach.add(name(c))
                if 'Basic {D} Energy' in pkg_attach:
                    stats['B']['fires'] += 1
                    stats['B'][outcome] += 1
                    elite_attach = set()
                    for idx in elite_act:
                        if 0 <= idx < len(opts):
                            o = opts[idx]
                            if int(o.get('type', -1)) == 2 and o.get('area') is None:
                                c = (hand[idx] if 0 <= idx < len(hand) else None)
                                elite_attach.add(name(c))
                    if 'Basic {D} Energy' not in elite_attach:
                        stats['B']['elite_skipped_attach'] += 1
            # RULE C: turn>=6, Drag ex online, EXP23 plays new support body
            if turn >= 6 and drag_ex_online(obs):
                if srcs(pkg_act) & {'Snorunt', 'Froslass', 'Munkidori'}:
                    stats['C']['fires'] += 1
                    stats['C'][outcome] += 1
                    if not (srcs(elite_act) & {'Snorunt', 'Froslass', 'Munkidori'}):
                        stats['C']['elite_skipped_support'] += 1
    agent.close()
    print('rule audit on drag-confirmed decisions (elite 175 games):')
    for rule in ('A', 'B', 'C'):
        s = stats[rule]
        print(f' RULE {rule}: decisions={s["drag_decisions"]} fires={s["fires"]} (W={s["W"]} L={s["L"]})')
        for k in ('elite_prefers_marnie', 'elite_skipped_attach', 'elite_skipped_support'):
            if k in s:
                print(f'   {k}: {s[k]}')
    json.dump({k: dict(v) for k, v in stats.items()}, open(ROOT / 'artifacts/drag_surgical/rule_audit.json', 'w'), indent=1)


if __name__ == '__main__':
    main()
