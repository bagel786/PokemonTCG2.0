#!/usr/bin/env python3
"""Forensic Decision Playback: Master v1 Blunders vs Pokémon TCG AI v2.

Replays exact decision states from live ladder mirror losses (#55283588)
and evaluates whether v2 (with 1-ply forward search and calibrated Value Head)
corrects the fatal passive blunders (e.g. energy hoarding, bench starvation, Marnie holding).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from cg.api import to_observation_class
from ptcg_ai.agent import CompetitionAgent
from ptcg_ai.model import NumpyPolicyModel
from ptcg_ai.search import OnePlySearchPolicy

REPLAY_DIR = ROOT / "data" / "replays" / "55283588"
V2_MODEL_PATH = ROOT / "artifacts" / "v2_model" / "policy_weights.npz"
V1_MODEL_PATH = ROOT / "artifacts" / "loss_buckets_model" / "master_loss_buckets_policy.npz"
if not V1_MODEL_PATH.exists():
    V1_MODEL_PATH = ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz"

GRIM_DECK = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"


def load_deck(path: Path) -> list[int]:
    return [int(line.strip()) for line in path.read_text().splitlines() if line.strip()]


def run_forensic_comparison():
    print("================================================================================")
    print("LIVE REPLAY FORENSIC PLAYBACK: MASTER V1 vs POKÉMON TCG AI V2")
    print("================================================================================")

    hero_deck = load_deck(GRIM_DECK)

    # 1. Initialize Master v1 agent (greedy policy, no search)
    v1_model = NumpyPolicyModel(V1_MODEL_PATH)
    
    # 2. Initialize v2 agent (calibrated model + 1-ply search enabled)
    v2_model = NumpyPolicyModel(V2_MODEL_PATH)
    v2_search = OnePlySearchPolicy(
        model=v2_model,
        hero_deck=hero_deck,
        ambiguity_margin=0.35,
        jaccard_threshold=0.35,
        timeout_ms=50.0,
    )

    # Mirror loss episodes to inspect
    target_episodes = [90303182, 90306144, 90326666, 90294956]
    
    total_evaluated = 0
    divergences = 0
    search_overrides = 0

    for ep_id in target_episodes:
        ep_file = REPLAY_DIR / f"episode-{ep_id}-replay.json"
        if not ep_file.exists():
            continue

        print(f"\n--- Analyzing Mirror Episode {ep_id} ---")
        ep_data = json.loads(ep_file.read_text())
        steps = ep_data.get("steps", [])

        for step_idx, step in enumerate(steps):
            # Check player 0 or 1 obs
            for p_idx in (0, 1):
                agent_data = step[p_idx]
                obs_dict = agent_data.get("observation", {})
                if not obs_dict or obs_dict.get("select") is None:
                    continue

                select_info = obs_dict.get("select")
                options = select_info.get("option", [])
                if len(options) <= 1:
                    continue

                obs = to_observation_class(obs_dict)
                if obs.current is None:
                    continue

                from ptcg_ai.features import encode_observation
                feat = encode_observation(obs, feature_version=2)
                logits_v1, c_v1, val_v1 = v1_model.predict(feat)
                v1_choice = [int(np.argmax(logits_v1))]

                # Run V2 prediction (with search evaluation)
                logits_v2, c_v2, val_v2 = v2_model.predict(feat)
                v2_base_choice = [int(np.argmax(logits_v2))]
                
                # Check if v2 search overrides base choice
                v2_choice = v2_base_choice
                overridden = False
                if v2_search.should_search(logits_v2, c_v2, obs.select):
                    sorted_opts = np.argsort(logits_v2)[::-1]
                    cands = [[int(opt)] for opt in sorted_opts[:3]]
                    search_res = v2_search.evaluate_candidates(obs, cands, hero_deck)
                    if search_res is not None and search_res != v2_base_choice:
                        v2_choice = search_res
                        overridden = True
                        search_overrides += 1

                total_evaluated += 1
                if v1_choice != v2_choice:
                    divergences += 1
                    opt_types = [opt.get("type", "UNKNOWN") for opt in options]
                    v1_type = opt_types[v1_choice[0]] if v1_choice[0] < len(opt_types) else "N/A"
                    v2_type = opt_types[v2_choice[0]] if v2_choice[0] < len(opt_types) else "N/A"
                    search_tag = " [SEARCH OVERRIDE]" if overridden else ""
                    print(
                        f"  Step {step_idx:3d} | V1: Opt {v1_choice[0]} ({v1_type}) "
                        f"--> V2: Opt {v2_choice[0]} ({v2_type}){search_tag} | Delta Val: {val_v2:.3f}"
                    )

    print("\n================================================================================")
    print(f"FORENSIC SUMMARY:")
    print(f"  Total Interactive Decisions Evaluated: {total_evaluated}")
    print(f"  Tactical Divergences (V1 vs V2):       {divergences} ({divergences/max(1, total_evaluated)*100:.1f}%)")
    print(f"  1-Ply Search Tactical Overrides:       {search_overrides}")
    print("================================================================================")


if __name__ == "__main__":
    run_forensic_comparison()
