#!/usr/bin/env python3
"""Mine elite exact-Grim vs Dragapult episodes (175) — v2 with proper
source-card resolution (hand/board), not option.cardId."""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path('/Users/safiullahbaig/Projects/PokemonTCG2.0-drag-surgical/vendor')))
from cg.api import all_card_data, AreaType  # noqa: E402

CT = {c.cardId: c for c in all_card_data()}
EPDIR = Path('/Users/safiullahbaig/Projects/PokemonTCG2.0-drag-surgical/artifacts/drag_surgical/elite_episodes')
HITS = json.load(open('/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight/artifacts/overnight_20260816/elite_dragapult_0815.json'))

ID = {'impidimp': 646, 'morgrem': 647, 'grim': 648, 'candy': 1079,
      'snorunt': {103, 860}, 'froslass': 104, 'munkidori': 112, 'denergy': 7}


def zone_of(obs, area, index, player_index):
    state = obs.get('current')
    if not state or area is None or index is None:
        return None
    players = state.get('players') or []
    if player_index is None:
        player_index = state.get('yourIndex')
    pl = players[player_index] if 0 <= player_index < len(players) else None
    if pl is None:
        return None
    zone = {
        AreaType.HAND: pl.get('hand'), AreaType.DISCARD: pl.get('discard'),
        AreaType.ACTIVE: pl.get('active'), AreaType.BENCH: pl.get('bench'),
        AreaType.PRIZE: pl.get('prize'),
    }.get(area, []) or []
    if 0 <= index < len(zone):
        return zone[index]
    return None


def source_card(obs, opt):
    """Resolve the card an option refers to (PLAY: hand fallback; else area)."""
    otype = int(opt.get('type', -1))
    if otype == 1 and opt.get('area') is None:
        return zone_of(obs, AreaType.HAND, opt.get('index'), obs['current']['yourIndex'])
    return zone_of(obs, opt.get('area'), opt.get('index'), opt.get('playerIndex'))


def name(c):
    if not c:
        return 'none'
    x = CT.get(c.get('id'))
    return x.name if x else '?'


def analyze(ep_file, grim_seat, won):
    d = json.load(open(EPDIR / ep_file))
    steps = d.get('steps') or []
    out = {'won': won, 'n_steps': len(steps)}
    first_grim_turn = None
    first_grim_ko_turn = None
    marnie_pieces_at_ko = None
    froslass_turn = None
    punk_pattern = None
    boss_events = []
    powered_mid = False
    turn_actions = {}  # turn -> list of source names played this turn
    grim_seen = False

    for si in range(len(steps) - 1):
        if grim_seat >= len(steps[si]):
            continue
        row = steps[si][grim_seat]
        if str(row.get('status', '')).upper() != 'ACTIVE':
            continue
        obs = row.get('observation') or {}
        cur = obs.get('current') or {}
        if not cur or not cur.get('players'):
            continue
        turn = cur.get('turn') or 0
        p = cur['players'][grim_seat]
        po = cur['players'][1 - grim_seat]
        act = (p.get('active') or [None])[0]
        act_name = name(act)
        bench = [b for b in (p.get('bench') or []) if b]
        bench_names = [name(b) for b in bench]
        sel = obs.get('select') or {}
        opts = sel.get('option') or []
        action = steps[si + 1][grim_seat].get('action') if (si + 1 < len(steps) and grim_seat < len(steps[si + 1])) else None
        if not isinstance(action, list):
            continue
        played_here = []
        for idx in action:
            if not (0 <= idx < len(opts)):
                continue
            o = opts[idx]
            src = source_card(obs, o)
            played_here.append(name(src))
        turn_actions.setdefault(turn, []).extend(played_here)

        if first_grim_turn is None and ("Marnie's Grimmsnarl ex" in bench_names or act_name == "Marnie's Grimmsnarl ex"):
            first_grim_turn = turn
        if act_name == "Marnie's Grimmsnarl ex":
            grim_seen = True
        if grim_seen and first_grim_ko_turn is None and act_name not in ("Marnie's Grimmsnarl ex", 'none') and "Marnie's Grimmsnarl ex" not in bench_names:
            first_grim_ko_turn = turn
            marnie_pieces_at_ko = sum(1 for n in bench_names + [act_name] if n in ("Marnie's Impidimp", "Marnie's Morgrem"))
        if froslass_turn is None and ('Froslass' in bench_names or act_name == 'Froslass'):
            froslass_turn = turn
        if not powered_mid and 6 <= turn <= 8:
            out['powered_munk_t6_8'] = sum(1 for b in [act] + bench if b and b.get('id') == 112 and (b.get('energies') or []))
            out['total_munk_t6_8'] = sum(1 for b in [act] + bench if b and b.get('id') == 112)
            powered_mid = True
        if "Boss" in played_here and si + 2 < len(steps) and grim_seat < len(steps[si + 2]):
            nxt = (steps[si + 2][grim_seat].get('observation') or {}).get('current') or {}
            if nxt.get('players'):
                prev_na = name((po.get('active') or [None])[0])
                new_na = name((nxt['players'][1 - grim_seat].get('active') or [None])[0])
                boss_events.append((turn, prev_na, new_na, won))

    # punk-bench-first: on the turn Grim first evolved, was an Impidimp played earlier that turn?
    if first_grim_turn is not None:
        acts = turn_actions.get(first_grim_turn, [])
        had_impidimp_play = "Marnie's Impidimp" in acts
        if had_impidimp_play:
            punk_pattern = 'bench_first'
        else:
            punk_pattern = 'evolve_first_or_noextra'
    out.update({'first_grim_turn': first_grim_turn, 'first_grim_ko_turn': first_grim_ko_turn,
                'marnie_pieces_at_ko': marnie_pieces_at_ko, 'froslass_turn': froslass_turn,
                'punk_pattern': punk_pattern, 'boss_events': boss_events})
    return out


def main() -> None:
    results = []
    for h in HITS:
        if h['won'] is None:
            continue
        try:
            r = analyze(h['ep'] + '.json', h['grim_seat'], h['won'])
            r['ep'] = h['ep']
            r['opp'] = h['opp_team']
            results.append(r)
        except Exception as e:
            print('ERR', h['ep'], repr(e)[:100])
    n = len(results)
    print(f'analyzed {n}')

    def wr(rows):
        if not rows:
            return 'n/a'
        return f'{sum(1 for r in rows if r["won"])}/{len(rows)} = {sum(1 for r in rows if r["won"])/len(rows):.1%}'

    print('\n--- PUNK-BENCH pattern on first-Grim turn ---')
    for pat in ('bench_first', 'evolve_first_or_noextra'):
        rows = [r for r in results if r['punk_pattern'] == pat]
        print(f'  {pat:24s}: n={len(rows):3d}  WR={wr(rows)}')
    print('\n--- REPLACEMENT pieces at first Grim KO ---')
    for k in (0, 1, 2, 3):
        rows = [r for r in results if r['marnie_pieces_at_ko'] == k]
        if rows:
            print(f'  pieces={k}: n={len(rows):3d}  WR={wr(rows)}')
    print('\n--- first Grim turn ---')
    for t in range(3, 14):
        rows = [r for r in results if r['first_grim_turn'] == t]
        if rows:
            print(f'  t{t:2d}: n={len(rows):3d}  WR={wr(rows)}')
    print(f'  never: n={len([r for r in results if r["first_grim_turn"] is None])}  WR={wr([r for r in results if r["first_grim_turn"] is None])}')
    print('\n--- Froslass entry vs first Grim ---')
    for label, rows in (
        ('BEFORE grim', [r for r in results if r['froslass_turn'] is not None and r['first_grim_turn'] is not None and r['froslass_turn'] < r['first_grim_turn']]),
        ('AFTER grim', [r for r in results if r['froslass_turn'] is not None and r['first_grim_turn'] is not None and r['froslass_turn'] >= r['first_grim_turn']]),
        ('none', [r for r in results if r['froslass_turn'] is None])):
        print(f'  {label:12s}: n={len(rows):3d}  WR={wr(rows)}')
    print('\n--- powered Munkidori t6-8 ---')
    for k in (0, 1, 2, 3):
        rows = [r for r in results if r.get('powered_munk_t6_8') == k]
        if rows:
            print(f'  powered={k}: n={len(rows):3d}  WR={wr(rows)}')
    print('\n--- Boss targets (from -> to) ---')
    tab = Counter()
    for r in results:
        for (t, frm, to, w) in r['boss_events']:
            tab[(frm, to, w)] += 1
    for (frm, to, w), c in sorted(tab.items(), key=lambda kv: -kv[1]):
        print(f'  {frm:14s} -> {to:14s} {"W" if w else "L"} x{c}')
    json.dump(results, open('/Users/safiullahbaig/Projects/PokemonTCG2.0-drag-surgical/artifacts/drag_surgical/elite_patterns.json', 'w'), indent=1)


if __name__ == '__main__':
    main()
