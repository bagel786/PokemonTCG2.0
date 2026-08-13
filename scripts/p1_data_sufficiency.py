#!/usr/bin/env python3
"""P1 data sufficiency gate: certified-state statistics and preference extraction."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

from ptcg_ai.view import card_table  # noqa: E402


def own_turn_ordinal(turn: int, seat: int, first_player: int) -> int:
    if first_player not in (0, 1) or turn <= 0:
        return 0
    return (turn + 1) // 2 if seat == first_player else turn // 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, default=ROOT / "artifacts/p1_causal_labels.jsonl")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/p1_data_sufficiency.json")
    args = parser.parse_args()

    table = card_table()
    states = [json.loads(line) for line in args.labels.read_text().splitlines()]

    clear_preferences = []
    ambiguous = []
    chosen_win_rates = []
    for state in states:
        chosen = state["chosen_card"]
        per_card = {int(card): value for card, value in state["per_card"].items()}
        cards = list(per_card)
        full_coverage = all(value["runs"] >= 3 for value in per_card.values())
        if not full_coverage:
            ambiguous.append(("coverage", state))
            continue
        if chosen is None:
            best = max(cards, key=lambda c: per_card[c]["wins"])
            second = max(cards, key=lambda c: per_card[c]["wins"] if c != best else -1)
            if per_card[best]["wins"] - per_card[second]["wins"] >= 2:
                clear_preferences.append({"state": state, "preferred": best, "base": second, "margin": per_card[best]["wins"] - per_card[second]["wins"]})
            else:
                ambiguous.append(("margin", state))
            continue
        for card in cards:
            if card == chosen:
                continue
            margin = per_card[card]["wins"] - per_card[chosen]["wins"]
            if margin >= 2:
                clear_preferences.append({"state": state, "preferred": card, "base": chosen, "margin": margin})
            else:
                ambiguous.append(("margin", state))
        chosen_win_rates.append(per_card[chosen]["wins"] / max(1, per_card[chosen]["runs"]))

    names = lambda card: table.get(int(card)).name if int(card) in table else str(card)
    report = {
        "states_total": len(states),
        "games": len({state["game_seed"] for state in states}),
        "opponents": Counter(state["opponent"] for state in states),
        "orders": Counter(state["order"] for state in states),
        "own_turn_ordinals": Counter(own_turn_ordinal(state["turn"], state["your_index"], state["first_player"]) for state in states),
        "turns": Counter(state["turn"] for state in states),
        "chosen_none_end_count": sum(1 for state in states if state["chosen_card"] is None),
        "cards_playable_counts": Counter(),
        "cards_chosen_counts": Counter(),
        "cards_preferred_counts": Counter(),
        "clear_preferences": len(clear_preferences),
        "ambiguous_discarded": len(ambiguous),
        "preference_episodes": len({p["state"]["game_seed"] for p in clear_preferences}),
        "preference_opponents": Counter(p["state"]["opponent"] for p in clear_preferences),
        "preference_margins": Counter(p["margin"] for p in clear_preferences),
        "mean_chosen_win_rate": sum(chosen_win_rates) / len(chosen_win_rates) if chosen_win_rates else 0.0,
    }
    for state in states:
        for card in state["playable"]:
            report["cards_playable_counts"][names(card)] += 1
        if state["chosen_card"] is not None:
            report["cards_chosen_counts"][names(state["chosen_card"])] += 1
    for preference in clear_preferences:
        report["cards_preferred_counts"][names(preference["preferred"])] += 1
    report["cards_playable_counts"] = dict(sorted(report["cards_playable_counts"].items()))
    report["cards_chosen_counts"] = dict(sorted(report["cards_chosen_counts"].items()))
    report["cards_preferred_counts"] = dict(sorted(report["cards_preferred_counts"].items()))
    report["clear_preference_examples"] = [
        {
            "game": preference["state"]["game_seed"],
            "order": preference["state"]["order"],
            "opponent": preference["state"]["opponent"],
            "turn": preference["state"]["turn"],
            "chosen": names(preference["state"]["chosen_card"]) if preference["state"]["chosen_card"] is not None else "END",
            "preferred": names(preference["preferred"]),
            "margin": preference["margin"],
            "per_card": {
                names(int(card)): value["wins"] for card, value in preference["state"]["per_card"].items()
            },
        }
        for preference in clear_preferences[:20]
    ]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in {"clear_preference_examples"}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
