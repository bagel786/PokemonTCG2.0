#!/usr/bin/env python3
"""Dragapult matchup loss/win reports for EXP23 live games."""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path('/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight/vendor')))
from cg.api import all_card_data  # noqa: E402

CT = {c.cardId: c for c in all_card_data()}
REPLAYS = Path('/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight/data/replays/55556726')
META = json.load(open(REPLAYS / 'episodes_metadata.json'))
GAMES = (93671387, 93673237, 93679642, 93685951)


def name(pok):
    return CT.get(pok['id']).name if pok and pok.get('id') is not None else 'none'


def board(p):
    act = (p.get('active') or [None])[0]
    b = [x for x in (p.get('bench') or []) if x]
    return act, b


def main() -> None:
    for eid in GAMES:
        d = json.load(open(REPLAYS / f'episode-{eid}-replay.json'))
        steps = d.get('steps') or []
        m = next(x for x in META if x['id'] == eid)
        our_seat = next(i for i, a in enumerate(m['agents']) if a.get('submissionId') == 55556726)
        opp_seat = 1 - our_seat
        info = d.get('info') or {}
        teams = info.get('TeamNames') or ['?', '?']
        result = 'W' if next(a for a in m['agents'] if a.get('submissionId') == 55556726).get('reward') == 1 else 'L'
        print(f'\n================ ep{eid} {result} vs {teams[opp_seat]} (we seat {our_seat}) ================')
        first_player = None
        events = []
        prev_prizes = None
        last_hp = {}
        for si, step in enumerate(steps):
            if our_seat >= len(step):
                continue
            row = step[our_seat]
            cur = (row.get('observation') or {}).get('current') or {}
            if not cur or not cur.get('players'):
                continue
            turn = cur.get('turn')
            if cur.get('firstPlayer') in (0, 1) and first_player is None:
                first_player = cur['firstPlayer']
            p_us, p_opp = cur['players'][our_seat], cur['players'][opp_seat]
            prizes = (len(p_us.get('prize') or []), len(p_opp.get('prize') or []))
            if prev_prizes is not None and prizes[1] < prev_prizes[1]:
                events.append(f't{prev_turn}->{turn}: OPP took prize ({prev_prizes[1]}->{prizes[1]})')
            if prev_prizes is not None and prizes[0] < prev_prizes[0]:
                events.append(f't{prev_turn}->{turn}: WE took prize ({prev_prizes[0]}->{prizes[0]})')
            prev_prizes = prizes
            prev_turn = turn
            # track our active pokemon changes
            act_us, bench_us = board(p_us)
            act_opp, bench_opp = board(p_opp)
            key = (name(act_us), name(act_opp), len(bench_us), len(bench_opp))
            if key != last_hp.get('key'):
                last_hp = {'key': key, 'turn': turn}
        print(f'  firstPlayer: {first_player} (we {"first" if first_player == our_seat else "second"})')
        print(f'  total turns ~{prev_turn}, final prizes: we={prev_prizes[0]} opp={prev_prizes[1]}')
        print('  events:')
        for e in events:
            print('   ', e)
        # final boards
        act_us, bench_us = board(p_us)
        act_opp, bench_opp = board(p_opp)
        print(f'  final OUR: active={name(act_us)} bench={[name(x) for x in bench_us]}')
        print(f'  final OPP: active={name(act_opp)} bench={[name(x) for x in bench_opp]}')


if __name__ == '__main__':
    main()
