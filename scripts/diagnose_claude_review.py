#!/usr/bin/env python3
"""Validate Claude's findings against live replays, master_v1, and v2.2 packages."""

import tarfile
import tempfile
import sys
import json
from pathlib import Path
from cg.api import to_observation_class

def test_package(tar_name):
    tar_path = Path('artifacts') / tar_name
    print(f"\n========================================================")
    print(f"TESTING PACKAGE: {tar_name}")
    print(f"========================================================")
    
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        with tarfile.open(tar_path, 'r:gz') as tar:
            tar.extractall(stage)
            
        sys.path.insert(0, str(stage))
        sys.path.insert(0, str(Path('vendor').resolve()))
        
        # Clean import
        for mod in list(sys.modules.keys()):
            if mod.startswith('ptcg_ai'):
                del sys.modules[mod]
                
        import ptcg_ai.agent as ag_mod
        agent = ag_mod.CompetitionAgent(stage / 'deck.csv', model_path=stage / 'policy_weights.npz')
        
        # Test all loss replays
        replays = sorted(Path('data/replays/55303334').glob('*.json'))
        total_end_choices = 0
        total_attacks_chosen = 0
        total_steps_audited = 0
        
        for rp in replays:
            data = json.loads(rp.read_text())
            hero_idx = 0 if data['steps'][1][0].get('action', [])[:5] == [7, 7, 7, 7, 7] else 1
            for s_idx, s in enumerate(data['steps']):
                raw_obs = s[hero_idx].get('observation')
                if not raw_obs or not raw_obs.get('select'):
                    continue
                ctx = raw_obs['select']['context']
                # Main context (0) where attacks / ends occur
                if ctx == 0:
                    total_steps_audited += 1
                    choice = agent(raw_obs)
                    # Check what option was chosen
                    opt_idx = choice[0] if choice else -1
                    if 0 <= opt_idx < len(raw_obs['select']['option']):
                        opt = raw_obs['select']['option'][opt_idx]
                        opt_type = opt.get('type')
                        # OptionType.ATTACK = 8 or OptionType.END = 9 (let's check type numbers)
                        # OptionType in cg.api: 8 = ATTACK, 9 = END
                        if opt_type == 9 or opt_type == 'END':
                            total_end_choices += 1
                            print(f"  [PASS/END] Replay {rp.stem} Step {s_idx:3d}: Agent chose END ({choice})")
                        elif opt_type == 8 or opt_type == 'ATTACK':
                            total_attacks_chosen += 1
                            
        print(f"Summary for {tar_name}:")
        print(f"  Main Turn Steps Audited: {total_steps_audited}")
        print(f"  END (Pass) Chosen: {total_end_choices}")
        print(f"  ATTACK Chosen: {total_attacks_chosen}")

test_package('submission_master_v1.tar.gz')
test_package('submission_v2_2.tar.gz')
