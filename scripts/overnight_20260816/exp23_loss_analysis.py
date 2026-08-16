#!/usr/bin/env python3
"""Loss analysis for submission 55556726 (EXP23 live).

For every game: opponent archetype, our order, first Grim turn, game length,
prize race, final board. Classify each loss:
  STRUCTURAL / TEMPO / ATTACKER_EXHAUSTION / CLUTTER / TARGETING / UNKNOWN
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path('/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight/vendor')))
from cg.api import all_card_data  # noqa: E402

CT = {c.cardId: c for c in all_card_data()}
REPLAYS = Path('/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight/data/replays/55556726')
META = json.load(open(REPLAYS / 'episodes_metadata.json'))
GRIM = tuple(sorted(int(x) for x in
    Path('/Users/safiullahbaig/Projects/pokemonTCG2.0/freshstart/decklists/grimmsnarl_marnie.deck.csv')
    .read_text().split() if x.strip()))


def name(c):
    if not c:
        return 'none'
    x = CT.get(c.get('id'))
    return x.name if x else '?'


def archetype(deck_names):
    j = ' '.join(deck_names)
    if 'Dragapult' in j:
        return 'Dragapult'
    if 'Grimmsnarl' in j:
        return 'Grim-mirror'
    if 'Alakazam' in j:
        return 'Alakazam'
    if 'Dipplin' in j or 'Rillaboom' in j:
        return 'Dipplin'
    if 'Crustle' in j:
        return 'Crustle'
    if 'Kangaskhan' in j:
        return 'Kangaskhan'
    if 'Lopunny' in j:
        return 'Lopunny'
    if 'Starmie' in j:
        return 'Starmie'
    return 'other'


def main() -> None:
    games = []
    for m in META:
        ours = [a for a in m['agents'] if a.get('submissionId') == 55556726]
        if len(ours) != 1:
            continue
        opp = next((a for a in m['agents'] if a.get('submissionId') != 55556726), None)
        reward = ours[0].get('reward')
        if reward is None:
            continue
        epf = REPLAYS / f"episode-{m['id']}-replay.json"
        try:
            d = json.load(open(epf))
        except Exception:
            continue
        steps = d.get('steps') or []
        info = d.get('info') or {}
        teams = info.get('TeamNames') or ['?', '?']
        our_seat = next((i for i, a in enumerate(m['agents']) if a.get('submissionId') == 55556726), 0)
        opp_seat = 1 - our_seat
        if len(steps) < 2:
            continue
        opp_deck = [CT[int(x)].name if CT.get(int(x)) else '?' for x in steps[1][opp_seat].get('action') or []]
        arch = archetype(opp_deck)
        first_grim = None
        max_bench = 0
        munks_t8 = 0
        prizes = None
        first_player = None
        prev_prizes = None
        prize_events = []
        last_turn = 0
        for step in steps:
            if our_seat >= len(step):
                continue
            row = step[our_seat]
            cur = (row.get('observation') or {}).get('current') or {}
            if not cur or not cur.get('players'):
                continue
            t = cur.get('turn') or 0
            last_turn = max(last_turn, t)
            if cur.get('firstPlayer') in (0, 1):
                first_player = cur['firstPlayer']
            p = cur['players'][our_seat]
            po = cur['players'][opp_seat]
            act = (p.get('active') or [None])[0]
            bench = [b for b in (p.get('bench') or []) if b]
            max_bench = max(max_bench, len(bench))
            if t == 8:
                munks_t8 = sum(1 for b in [act] + bench if b and b.get('id') == 112)
            if first_grim is None and (name(act) == "Marnie's Grimmsnarl ex" or any(name(b) == "Marnie's Grimmsnarl ex" for b in bench)):
                first_grim = t
            pr = (len(p.get('prize') or []), len(po.get('prize') or []))
            if prev_prizes and pr[0] < prev_prizes[0]:
                prize_events.append((t, 'we'))
            if prev_prizes and pr[1] < prev_prizes[1]:
                prize_events.append((t, 'opp'))
            prev_prizes = pr
            prizes = pr
        order = 'first' if first_player == our_seat else ('second' if first_player is not None else '?')
        games.append({
            'ep': m['id'], 'result': 'W' if reward == 1 else 'L', 'arch': arch,
            'opp_team': teams[opp_seat] if opp_seat < len(teams) else '?',
            'opp_sub': opp.get('submissionId') if opp else '?',
            'order': order, 'first_grim': first_grim, 'turns': last_turn,
            'final_prizes_we_left': prizes[0] if prizes else None,
            'final_prizes_opp_left': prizes[1] if prizes else None,
            'max_bench': max_bench, 'munks_t8': munks_t8,
            'n_prize_events_us': sum(1 for t, who in prize_events if who == 'we'),
            'n_prize_events_opp': sum(1 for t, who in prize_events if who == 'opp'),
        })
    games.sort(key=lambda g: g['ep'])
    wl = Counter(g['result'] for g in games)
    print(f'total rated games: {len(games)}  {dict(wl)}')
    print()
    print('=== ALL GAMES ===')
    for g in games:
        print(f"ep{g['ep']} {g['result']} vs {g['arch']:12s} order={g['order']} first_grim=t{g['first_grim']} turns={g['turns']} prizes_left(w/o)={g['final_prizes_we_left']}/{g['final_prizes_opp_left']} max_bench={g['max_bench']} munks_t8={g['munks_t8']}")
    print()
    print('=== LOSS CLASSIFICATION ===')
    for g in games:
        if g['result'] != 'L':
            continue
        causes = []
        if g['first_grim'] is None or (g['first_grim'] or 99) >= 8:
            causes.append('TEMPO(first_grim>=t8)')
        if g['final_prizes_opp_left'] is not None and g['final_prizes_opp_left'] <= 2 and g['final_prizes_we_left'] and g['final_prizes_we_left'] >= 3:
            causes.append('PRIZE_RACE_LOST')
        if g['final_prizes_we_left'] is not None and g['final_prizes_we_left'] <= 2 and g['result'] == 'L':
            causes.append('CLOSE_RACE')
        if g['munks_t8'] >= 2:
            causes.append(f"MUNK_SPAM_t8({g['munks_t8']})")
        if not causes:
            causes.append('STRUCTURAL/UNKNOWN')
        print(f"ep{g['ep']} vs {g['arch']:12s} {g['opp_team'][:24]:24s} -> {' + '.join(causes)}")
    print()
    print('=== W/L BY ARCHETYPE ===')
    per = Counter()
    for g in games:
        per[(g['arch'], g['result'])] += 1
    for a in sorted(set(g['arch'] for g in games)):
        w = per[(a, 'W')]
        l = per[(a, 'L')]
        print(f'  {a:12s} {w}W-{l}L ({w/max(1,w+l):.0%})')
    json.dump(games, open('artifacts/overnight_20260816/exp23_live_loss_analysis.json', 'w'), indent=1)


if __name__ == '__main__':
    main()
