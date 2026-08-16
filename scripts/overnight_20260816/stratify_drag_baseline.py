#!/usr/bin/env python3
"""Stratify the 175-game elite Grim-vs-Dragapult baseline by opponent strength."""
import json
from collections import Counter, defaultdict
from pathlib import Path

OV = Path('/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight')
HITS = json.load(open(OV / 'artifacts/overnight_20260816/elite_dragapult_0815.json'))
TOP = json.load(open(OV / 'data/meta/top_team_archetypes_147.json'))

name_to_strength = {}
for tid, v in TOP.items():
    name_to_strength[v.get('name')] = {'rank': v.get('rank'), 'score': v.get('score'),
                                       'team_id': tid}


def strength_of(team_name):
    s = name_to_strength.get(team_name)
    if not s:
        return 'unranked'
    rank = s['rank']
    if rank <= 50:
        return 'high'
    if rank <= 147:
        return 'medium'
    return 'unranked'


def main() -> None:
    bins = defaultdict(list)
    opp_teams = Counter()
    for h in HITS:
        if h['won'] is None:
            continue
        b = strength_of(h['opp_team'])
        opp_teams[h['opp_team']] += 1
        bins[b].append(h)
    print(f'total games with known outcome: {sum(len(v) for v in bins.values())}')
    print()
    for b in ('high', 'medium', 'unranked'):
        rows = bins[b]
        if not rows:
            continue
        wins = sum(1 for r in rows if r['won'])
        wr = wins / len(rows)
        steps = [r['n_steps'] for r in rows]
        import statistics as st
        print(f'{b.upper():9s}: n={len(rows):3d}  grim WR={wr:.1%}  '
              f'mean_steps={st.mean(steps):.0f} median={st.median(steps):.0f}')
        # wins vs losses step counts
        w_steps = [r['n_steps'] for r in rows if r['won']]
        l_steps = [r['n_steps'] for r in rows if not r['won']]
        print(f'           wins steps mean={st.mean(w_steps):.0f}  losses steps mean={st.mean(l_steps):.0f}')
        # top opp teams in bin
        top_opps = Counter(r['opp_team'] for r in rows).most_common(5)
        print('           opp teams:', ', '.join(f'{t}×{c}' for t, c in top_opps))
    print()
    print('unranked bin — how many distinct opp teams:', len(set(r['opp_team'] for r in bins['unranked'])))
    # how many of the unranked teams are actually IN top_147 by other name spellings?
    missing = sorted(set(r['opp_team'] for r in bins['unranked']))
    print('unranked opp team names (first 15):', missing[:15])


if __name__ == '__main__':
    main()
