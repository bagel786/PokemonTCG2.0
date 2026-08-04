#!/usr/bin/env python3
import sys
import scripts.generate_loss_report as glr

def main():
    card_map = glr.load_cards()
    losses_5k = [89476888, 89476983, 89478632, 89479194]
    print("#####################################################################################")
    print("# LOSSES FOR SUBMISSION 55180261 (Grimmsnarl 5k Reference)")
    print("#####################################################################################")
    for ep_id in losses_5k:
        r = glr.analyze_episode(ep_id, 55180261, "Grimmsnarl 5k Reference", card_map)
        print(f"\n{'='*85}")
        print(f"EPISODE {r['ep_id']} | {r['label']} vs {r['opp_name']} (Opp ELO: {r['opp_init']})")
        print(f"{'='*85}")
        print(f"ELO Impact: {r['our_init']} -> {r['our_upd']} ({r['delta']}) | {r['first_turn']} | Total Turns: {r['total_turns']} (Steps: {r['total_steps']})")
        print(f"Opponent Archetype: {r['opp_arch']}")
        print(f"Opponent Key Cards: {', '.join(r['opp_key'])}")
        print(f"Loss Mode: {r['loss_mode']}")
        for f in r['findings']:
            print(f"  * {f}")
        print("Final Boards:")
        print(f"  * Our Final Board: {', '.join(filter(None, r['final_us_board']))}")
        print(f"  * Opp Final Board: {', '.join(filter(None, r['final_opp_board']))}")
        print("Turn Progression Highlights:")
        for t in r['turns_sample']:
            print(f"  Turn {t.get('turn', 0):2d}: Us Active={t.get('us_active')} (Prizes: {t.get('us_prizes')}/6 left) vs Opp Active={t.get('opp_active')} (Prizes: {t.get('opp_prizes')}/6 left)")

if __name__ == "__main__":
    main()
