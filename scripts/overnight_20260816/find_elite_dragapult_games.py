#!/usr/bin/env python3
"""Find elite (heldout raw) episodes where opponent runs Dragapult and the
elite exact-Grim seat won. Summarize elite board/action patterns vs Dragapult."""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path('/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight/vendor')))
from cg.api import all_card_data  # noqa: E402

CT = {c.cardId: c for c in all_card_data()}
RAW = Path('/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight/artifacts/overnight_20260816/heldout_raw')
GRIM = tuple(sorted(int(x) for x in
    Path('/Users/safiullahbaig/Projects/pokemonTCG2.0/freshstart/decklists/grimmsnarl_marnie.deck.csv')
    .read_text().split() if x.strip()))


def name(pok):
    return CT.get(pok['id']).name if pok else 'none'


def main() -> None:
    found = 0
    for day in ('2026-08-13', '2026-08-14', '2026-08-15'):
        daydir = RAW / day
        if not daydir.exists():
            continue
        for f in sorted(daydir.glob('*.json')):
            try:
                d = json.load(open(f))
            except Exception:
                continue
            steps = d.get('steps') or []
            if len(steps) < 2 or len(steps[1]) < 2:
                continue
            decks = []
            for s in (0, 1):
                a = steps[1][s].get('action') or []
                decks.append(tuple(sorted(int(x) for x in a)))
            if decks[0] != GRIM and decks[1] != GRIM:
                continue
            grim_seat = 0 if decks[0] == GRIM else 1
            opp_seat = 1 - grim_seat
            opp_names = [CT[int(x)].name for x in decks[opp_seat]]
            if 'Dragapult' not in ' '.join(opp_names):
                continue
            won = None
            for step in reversed(steps):
                for si, row in enumerate(step[:2]):
                    cur = (row.get('observation') or {}).get('current') or {}
                    if cur.get('result') in (0, 1):
                        won = (cur['result'] == grim_seat)
            if won is None:
                continue
            found += 1
            turns = max((row.get('observation') or {}).get('current', {}).get('turn') or 0
                        for step in steps for row in step[:2]) or '?'
            info = d.get('info') or {}
            teams = info.get('TeamNames') or ['?', '?']
            print(f'{day} {f.stem} grim_seat={grim_seat} W={won} turns~{turns} teams={teams[grim_seat]} vs {teams[opp_seat]}')
    print('total elite grim-vs-dragapult episodes found:', found)


if __name__ == '__main__':
    main()
