#!/usr/bin/env python3
"""Live self-parity: replay EXP23's live episodes through the local EXP23
runtime and compare local decisions against the recorded (live) actions.

A high match rate = live mechanism matches the locally-validated package.
"""
import json
import sys
from pathlib import Path

ROOT = Path('/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight')
sys.path.insert(0, str(ROOT / 'scripts' / 'overnight_20260816'))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'vendor'))

from replay_disagreement import walk_episode, is_forced, SelectContext  # noqa: E402
from ptcg_ai.external import ExternalSubmissionAgent  # noqa: E402

PKG = '/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/final_sprint/exp23_identity_trained'
REPLAYS = ROOT / 'data' / 'replays' / '55556726'


def main() -> None:
    agent = ExternalSubmissionAgent(PKG, {})
    meta_list = json.load(open(REPLAYS / 'episodes_metadata.json'))
    meta_by_id = {m['id']: m for m in meta_list}
    total = 0
    mismatches = 0
    errors = 0
    for f in sorted(REPLAYS.glob('episode-*.json')):
        ep = json.load(open(f))
        steps = ep.get('steps') or []
        info = ep.get('info') or {}
        teams = info.get('TeamNames') or []
        episode_id = int(f.stem.split('-')[1])
        meta = meta_by_id.get(episode_id)
        our_seat = None
        if meta:
            for a in meta.get('agents') or []:
                if a.get('submissionId') == 55556726:
                    our_seat = a.get('index')
                    break
        if our_seat is None:
            grim = tuple(sorted(int(x) for x in
                Path('/Users/safiullahbaig/Projects/pokemonTCG2.0/freshstart/decklists/grimmsnarl_marnie.deck.csv')
                .read_text().split() if x.strip()))
            if len(steps) > 1:
                for s in (0, 1):
                    a = steps[1][s].get('action') or []
                    if tuple(sorted(int(x) for x in a)) == grim:
                        our_seat = s
                        break
        if our_seat is None:
            print(f'{f.name}: seat unknown')
            continue
        records, errs = walk_episode(ep, our_seat, agent)
        errors += errs
        n_scored = 0
        n_mismatch = 0
        for r in records:
            if r['forced']:
                continue
            if r['package_action'] is None:
                n_mismatch += 1
                continue
            if r['context'] == int(SelectContext.IS_FIRST):
                continue
            n_scored += 1
            if r['package_action'] != r['elite_action']:
                n_mismatch += 1
        total += n_scored
        mismatches += n_mismatch
        winner = '?'
        if meta:
            for a in meta.get('agents') or []:
                if a.get('submissionId') == 55556726 and a.get('reward') is not None:
                    winner = 'W' if a['reward'] == 1 else 'L'
        print(f'{f.name[:22]} seat={our_seat} teams={teams} {winner} scored={n_scored} mismatch={n_mismatch} errs={errs}')
    agent.close()
    print(f'TOTAL scored={total} mismatches={mismatches} ({mismatches/max(1,total):.2%}) errors={errors}')


if __name__ == '__main__':
    main()
