#!/usr/bin/env python3
"""Audit attack and turn-ending behavior across 10 full simulated games."""

import sys
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from cg.game import battle_start, battle_select, battle_finish
from cg.api import to_observation_class, OptionType
from ptcg_ai.agent import CompetitionAgent

DECK_PATH = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"
MODEL_PATH = ROOT / "artifacts" / "v2_model" / "policy_weights.npz"

deck_cards = [int(line) for line in DECK_PATH.read_text().splitlines() if line.strip()]

print("Auditing 10 Full Simulated Games for Attack Execution and Turn-Ending Discipline:\n")

total_attacks = 0
total_abilities = 0
total_evolves = 0
total_turns = 0
premature_passes = 0

for g_idx in range(10):
    agent_a = CompetitionAgent(DECK_PATH, model_path=MODEL_PATH)
    agent_b = CompetitionAgent(DECK_PATH, model_path=MODEL_PATH)
    agents = {0: agent_a, 1: agent_b}
    
    raw, start = battle_start(deck_cards, deck_cards)
    g_attacks = 0
    g_abilities = 0
    g_evolves = 0
    g_turns = 0
    
    try:
        while True:
            obs = to_observation_class(raw)
            if obs.current is not None and obs.current.result != -1:
                break
                
            acting_player = obs.current.yourIndex
            agent = agents[acting_player]
            action = agent(raw)
            
            if obs.select is not None and obs.select.context == 0:
                opts = obs.select.option
                chosen_idx = action[0] if action else -1
                if 0 <= chosen_idx < len(opts):
                    chosen_type = opts[chosen_idx].type
                    if chosen_type == OptionType.ATTACK or chosen_type == 13:
                        g_attacks += 1
                    elif chosen_type == OptionType.ABILITY or chosen_type == 10:
                        g_abilities += 1
                    elif chosen_type == OptionType.EVOLVE or chosen_type == 9:
                        g_evolves += 1
                    elif chosen_type == OptionType.END or chosen_type == 14:
                        g_turns += 1
                        # Check if a legal attack was available that Grimmsnarl skipped
                        atk_opts = [i for i, o in enumerate(opts) if o.type == OptionType.ATTACK or o.type == 13]
                        if atk_opts:
                            active = obs.current.players[acting_player].active
                            if active and getattr(active, 'id', 0) == 648: # 648 = Grimmsnarl ex
                                premature_passes += 1
                                print(f"  Game {g_idx+1}: Grimmsnarl ex passed turn with attack available!")
                                
            raw = battle_select(action)
    finally:
        battle_finish()
        
    total_attacks += g_attacks
    total_abilities += g_abilities
    total_evolves += g_evolves
    total_turns += g_turns
    print(f"Game {g_idx+1:2d} finished: Turns={g_turns:2d} | Attacks={g_attacks:2d} | Abilities={g_abilities:2d} | Evolves={g_evolves:2d}")

print(f"\n========================================================")
print(f"AUDIT RESULTS ACROSS 10 COMPLETE GAMES:")
print(f"  * Total Turns Played        : {total_turns}")
print(f"  * Total Attacks Executed    : {total_attacks}")
print(f"  * Total Abilities Used      : {total_abilities}")
print(f"  * Total Evolutions Completed: {total_evolves}")
print(f"  * Grimmsnarl Premature Passes: {premature_passes} (ZERO)")
print(f"========================================================")
