#!/usr/bin/env python3
"""Final Pre-Submission Integrity and Hostile Environment Verification."""

import hashlib
import json
import os
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from scripts.package_v2_agent import package_v2

GRIM_DECK = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"
MODEL_V2 = ROOT / "artifacts" / "v2_model" / "policy_weights.npz"
OUT_TAR = ROOT / "artifacts" / "submission_v2_2.tar.gz"

print("=" * 80)
print("=== FINAL PRE-SUBMISSION INTEGRITY & SECURITY AUDIT ===")
print("=" * 80)

# 1. Fresh Package
package_v2(model_path=MODEL_V2, deck_path=GRIM_DECK, output_tar=OUT_TAR)
tar_bytes = OUT_TAR.read_bytes()
tar_hash = hashlib.sha256(tar_bytes).hexdigest()
tar_size_mb = len(tar_bytes) / 1024 / 1024
print(f"\n[Audit 1/5] Package Integrity:")
print(f"  * File Path : {OUT_TAR}")
print(f"  * File Size : {tar_size_mb:.2f} MB")
print(f"  * SHA256    : {tar_hash}")

# 2. Extract into sterile environment
with tempfile.TemporaryDirectory(prefix="final_sterile_audit_", ignore_cleanup_errors=True) as tmp_dir:
    stage = Path(tmp_dir)
    with tarfile.open(OUT_TAR, "r:gz") as tar:
        tar.extractall(stage)
        
    members = list(stage.rglob("*"))
    file_count = sum(1 for p in members if p.is_file())
    print(f"\n[Audit 2/5] Sterile Extraction:")
    print(f"  * Extracted Files Count: {file_count}")
    print(f"  * main.py exists       : {(stage / 'main.py').exists()}")
    print(f"  * deck.csv exists      : {(stage / 'deck.csv').exists()}")
    print(f"  * policy_weights.npz   : {(stage / 'policy_weights.npz').exists()}")

    # 3. Hostile Environment Test (Inject PTCG_TEMP=2 into env)
    os.environ["PTCG_TEMP"] = "2.0"
    
    sys.path.insert(0, str(stage))
    for mod in list(sys.modules.keys()):
        if mod.startswith("ptcg_ai") or mod == "main":
            del sys.modules[mod]
            
    import main as sub_main
    
    print(f"\n[Audit 3/5] Hostile Environment Lock Test:")
    print(f"  * Environment PTCG_TEMP was set to: 2.0")
    print(f"  * Effective os.environ['PTCG_TEMP']: {os.environ.get('PTCG_TEMP')}")
    print(f"  * Effective Policy temp           : {sub_main._AGENT.policy.temp}")
    assert sub_main._AGENT.policy.temp == 0.0, "FAIL: Policy temperature is not locked to 0.0!"
    print(f"  * RESULT: GREEDY LOCK HOLDS 100% (Strictly 0.0)")

    # 4. Step-0 Deck Initialization
    step0_obs = {"deck": [0] * 60, "step": 0}
    returned_deck = sub_main.agent(step0_obs)
    print(f"\n[Audit 4/5] Step-0 Kaggle Deck Handshake:")
    print(f"  * Returned Deck Length : {len(returned_deck)}")
    deck_hash = hashlib.sha256(Path(stage / "deck.csv").read_bytes()).hexdigest()
    print(f"  * Deck Hash SHA256     : {deck_hash}")
    assert len(returned_deck) == 60, "FAIL: Deck length is not 60!"
    print(f"  * RESULT: STEP-0 HANDSHAKE PERFECT")

    # 5. Historical Pass-Blunder Invariant Verification across all 7 loss replays
    from cg.api import to_observation_class, OptionType
    replays = sorted(Path("data/replays/55303334").glob("*.json"))
    total_decisions = 0
    passes_with_attack = 0
    
    for rp in replays:
        data = json.loads(rp.read_text())
        hero_idx = 0 if data["steps"][1][0].get("action", [])[:5] == [7, 7, 7, 7, 7] else 1
        for s in data["steps"]:
            raw_obs = s[hero_idx].get("observation")
            if not raw_obs or not raw_obs.get("select"):
                continue
            total_decisions += 1
            action = sub_main.agent(raw_obs)
            if raw_obs.get("select", {}).get("context") == 0:
                opts = raw_obs["select"].get("option", [])
                chosen_idx = action[0] if action else -1
                if 0 <= chosen_idx < len(opts):
                    chosen_type = opts[chosen_idx].get("type")
                    if chosen_type == OptionType.END or chosen_type == 14:
                        atk_opts = [i for i, o in enumerate(opts) if o.get("type") == OptionType.ATTACK or o.get("type") == 13]
                        if atk_opts:
                            passes_with_attack += 1

    print(f"\n[Audit 5/5] Pass-Blunder Historical Defense:")
    print(f"  * Total Replay Decisions Tested: {total_decisions}")
    print(f"  * Unprovoked Passes With Attack: {passes_with_attack}")
    assert passes_with_attack == 0, f"FAIL: detected {passes_with_attack} pass blunders"
    print(f"  * RESULT: ZERO PASS BLUNDERS DETECTED")

print("\n" + "=" * 80)
print("=== FINAL VERDICT: 100% READY FOR SUBMISSION ===")
print("=" * 80)
