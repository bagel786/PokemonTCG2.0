#!/usr/bin/env python3
"""Late-game divergence diagnostic: for CERT-B episodes, find decisive late
disagreements and dump human-readable option summaries for elite/C0/EXP23."""
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path('/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight')
sys.path.insert(0, str(ROOT / 'scripts' / 'overnight_20260816'))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'vendor'))

from replay_disagreement import (  # noqa: E402
    PACKAGES, CERT_TEAMS, collect_units, elite_index_for, run_package_on_units,
    join_records, classify, SelectContext, OptionType, resolve_area_card,
)
from cg.api import to_observation_class  # noqa: E402

RAW_DIR = ROOT / 'artifacts' / 'overnight_20260816' / 'heldout_raw'
OUT = ROOT / 'artifacts' / 'overnight_20260816' / 'late_divergence_diagnostic.jsonl.gz'

CTX_NAMES = {v: k for k, v in SelectContext.__members__.items()}
OT_NAMES = {v: k for k, v in OptionType.__members__.items()}


def opt_summary(obs_dict, idxs, card_table):
    obs = to_observation_class(obs_dict)
    out = []
    for i in idxs:
        opt = obs.select.option[i]
        name = OT_NAMES.get(int(opt.type), str(opt.type))
        if opt.type == OptionType.PLAY and opt.area is None:
            state = obs.current
            hand = state.players[state.yourIndex].hand or []
            card = hand[i] if i is not None and 0 <= i < len(hand) else None
        else:
            card = resolve_area_card(obs, opt.area, opt.index, opt.playerIndex)
        cid = card.id if card is not None else int(opt.cardId or 0)
        cdata = card_table.get(cid)
        cname = (cdata.name if cdata else f'id{cid}')
        out.append(f'{name}:{cname}.attk{int(opt.attackId or 0)}')
    return out


def main() -> None:
    from cg.api import all_card_data
    card_table = {c.cardId: c for c in all_card_data()}
    raw_dirs = [RAW_DIR / '2026-08-14', RAW_DIR / '2026-08-15']
    units = collect_units(raw_dirs, CERT_TEAMS)
    elite_index = elite_index_for(units)
    results = {}
    for name in ('c0', 'exp23'):
        results[name] = run_package_on_units(name, PACKAGES[name], units, 6)
    joined, elite_rows = join_records(units, elite_index, results)
    fam = Counter()
    n = 0
    with gzip.open(OUT, 'wt') as out:
        for key, record in joined.items():
            meta = record['meta']
            if meta['turn'] <= 7:
                continue
            elite_row = elite_rows.get(key)
            if elite_row is None or 'c0' not in record or 'exp23' not in record:
                continue
            c0r, e23r = record['c0'], record['exp23']
            if c0r['package_action'] is None or e23r['package_action'] is None:
                continue
            if meta['forced']:
                continue
            cls = classify(elite_row['obs'], elite_row['action'], c0r['package_action'], e23r['package_action'])
            if cls == 'ignored':
                continue
            n += 1
            fam[(meta['context'], cls)] += 1
            row = {
                'episode': meta['episode'], 'team': meta['team'], 'step': meta['step'],
                'turn': meta['turn'], 'order': meta.get('hero_order'),
                'context': meta['context'], 'context_name': CTX_NAMES.get(meta['context'], '?'),
                'cls': cls,
                'elite': opt_summary(elite_row['obs'], elite_row['action'], card_table),
                'c0': opt_summary(elite_row['obs'], c0r['package_action'], card_table),
                'e23': opt_summary(elite_row['obs'], e23r['package_action'], card_table),
            }
            out.write(json.dumps(row) + '\n')
    print('late decisive rows dumped:', n)
    print('by (context, cls):')
    for k, v in sorted(fam.items(), key=lambda kv: -kv[1]):
        print(f'  ctx={CTX_NAMES.get(k[0],"?"):22s} {k[1]:14s} {v}')


if __name__ == '__main__':
    main()
