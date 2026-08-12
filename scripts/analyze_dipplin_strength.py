#!/usr/bin/env python3
"""Baseline mechanism audit for Festival Dipplin.

Consumes existing evaluation JSON and produces machine-readable JSON plus
a short Markdown report. Does NOT run new games.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from scripts.evaluate_dipplin import seat_order_cells, wilson


@dataclass
class MechanismAudit:
    overall_win_rate: float
    actual_first_win_rate: float
    actual_second_win_rate: float
    physical_seat_0_win_rate: float
    physical_seat_1_win_rate: float
    per_opponent: dict[str, dict[str, float]]
    first_productive_attack_turn: dict[str, float]
    first_festival_double_attack_turn: dict[str, float]
    bench_size_at_first_attack: dict[str, float]
    thwackey_present_at_first_attack: dict[str, float]
    festival_active_at_first_attack: dict[str, float]
    replacement_ready_after_first_attack: dict[str, float]
    card_frequencies: dict[str, dict[str, float]]
    late_turn_no_productive_attack: dict[str, float]
    support_trapped_active: dict[str, float]
    festival_attack_offered_taken: dict[str, float]
    replacement_unavailable_after_ko: dict[str, float]
    unknown_resolver_rate: dict[str, float]
    policy_fallback_rate: dict[str, float]
    policy_error_rate: dict[str, float]
    illegal_action_rate: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_win_rate": self.overall_win_rate,
            "actual_first_win_rate": self.actual_first_win_rate,
            "actual_second_win_rate": self.actual_second_win_rate,
            "physical_seat_0_win_rate": self.physical_seat_0_win_rate,
            "physical_seat_1_win_rate": self.physical_seat_1_win_rate,
            "per_opponent": self.per_opponent,
            "first_productive_attack_turn": self.first_productive_attack_turn,
            "first_festival_double_attack_turn": self.first_festival_double_attack_turn,
            "bench_size_at_first_attack": self.bench_size_at_first_attack,
            "thwackey_present_at_first_attack": self.thwackey_present_at_first_attack,
            "festival_active_at_first_attack": self.festival_active_at_first_attack,
            "replacement_ready_after_first_attack": self.replacement_ready_after_first_attack,
            "card_frequencies": self.card_frequencies,
            "late_turn_no_productive_attack": self.late_turn_no_productive_attack,
            "support_trapped_active": self.support_trapped_active,
            "festival_attack_offered_taken": self.festival_attack_offered_taken,
            "replacement_unavailable_after_ko": self.replacement_unavailable_after_ko,
            "unknown_resolver_rate": self.unknown_resolver_rate,
            "policy_fallback_rate": self.policy_fallback_rate,
            "policy_error_rate": self.policy_error_rate,
            "illegal_action_rate": self.illegal_action_rate,
        }


CARD_NAMES = {
    107: "Quick Sign",
    1225: "Hilda",
    1227: "Lillie",
    114: "Boom Boom Groove",
    1086: "Poffin",
    1094: "Bug Catching Set",
    1152: "Poké Pad",
    1182: "Boss",
    1175: "Bangle",
    1211: "Black Belt",
    1080: "Unfair Stamp",
}


def _rate(numer: int, denom: int) -> float:
    return numer / denom if denom else 0.0


def _mean(values: Iterable[float]) -> float:
    vals = [v for v in values if math.isfinite(v)]
    return sum(vals) / len(vals) if vals else 0.0


def load_evaluation(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def extract_mechanism_rates(rows: list[dict[str, Any]]) -> MechanismAudit:
    completed = [r for r in rows if r.get("completed")]
    games = len(completed)
    if games == 0:
        empty = MechanismAudit(
            overall_win_rate=0.0,
            actual_first_win_rate=0.0,
            actual_second_win_rate=0.0,
            physical_seat_0_win_rate=0.0,
            physical_seat_1_win_rate=0.0,
            per_opponent={},
            first_productive_attack_turn={},
            first_festival_double_attack_turn={},
            bench_size_at_first_attack={},
            thwackey_present_at_first_attack={},
            festival_active_at_first_attack={},
            replacement_ready_after_first_attack={},
            card_frequencies={},
            late_turn_no_productive_attack={},
            support_trapped_active={},
            festival_attack_offered_taken={},
            replacement_unavailable_after_ko={},
            unknown_resolver_rate={},
            policy_fallback_rate={},
            policy_error_rate={},
            illegal_action_rate={},
        )
        return empty

    wins = sum(r["win"] for r in completed)

    # Split by actual order
    first_rows = [r for r in completed if r.get("actual_order") == "first"]
    second_rows = [r for r in completed if r.get("actual_order") == "second"]
    seat_0_rows = [r for r in completed if r.get("hero_seat") == 0]
    seat_1_rows = [r for r in completed if r.get("hero_seat") == 1]

    first_wins = sum(r["win"] for r in first_rows)
    second_wins = sum(r["win"] for r in second_rows)
    seat_0_wins = sum(r["win"] for r in seat_0_rows)
    seat_1_wins = sum(r["win"] for r in seat_1_rows)

    # Per opponent
    opponents = sorted({r.get("opponent_name", "unknown") for r in completed})
    per_opponent = {}
    for opp in opponents:
        opp_rows = [r for r in completed if r.get("opponent_name") == opp]
        opp_games = len(opp_rows)
        opp_wins = sum(r["win"] for r in opp_rows)
        opp_first = [r for r in opp_rows if r.get("actual_order") == "first"]
        opp_second = [r for r in opp_rows if r.get("actual_order") == "second"]
        per_opponent[opp] = {
            "overall": _rate(opp_wins, opp_games),
            "first": _rate(sum(r["win"] for r in opp_first), len(opp_first)),
            "second": _rate(sum(r["win"] for r in opp_second), len(opp_second)),
        }

    # Mechanism rates from telemetry
    def telemetry_sum(rows: list[dict[str, Any]], key: str) -> float:
        return sum(r.get("hero_telemetry", {}).get(key, 0) for r in rows)

    def telemetry_rate(rows: list[dict[str, Any]], key: str) -> float:
        return _rate(int(telemetry_sum(rows, key)), len(rows))

    def telemetry_split_rate(rows: list[dict[str, Any]], key: str) -> dict[str, float]:
        split = {}
        for label, subset in (
            ("win", [r for r in rows if r["win"]]),
            ("loss", [r for r in rows if not r["win"]]),
            ("first", [r for r in rows if r.get("actual_order") == "first"]),
            ("second", [r for r in rows if r.get("actual_order") == "second"]),
        ):
            if subset:
                split[label] = _rate(int(telemetry_sum(subset, key)), len(subset))
            else:
                split[label] = 0.0
        return split

    # First productive attack turn
    first_atk_sum = telemetry_sum(completed, "first_productive_attack_turn_sum")
    first_atk_count = telemetry_sum(completed, "first_productive_attack_turn_count")
    first_atk_max = telemetry_sum(completed, "first_productive_attack_turn_max")

    # First Festival double attack turn
    # Not directly tracked; use festival_attack_windows and second_attacks_taken
    festival_windows = telemetry_sum(completed, "festival_attack_windows")
    second_taken = telemetry_sum(completed, "second_attacks_taken")

    # Bench size at first attack - not directly tracked, use bench counts at attack time
    # This would need per-game telemetry; approximate from available data

    # Card frequencies
    card_frequencies = {}
    for card_id, name in CARD_NAMES.items():
        freq = telemetry_rate(completed, f"setup_active_{card_id}") if card_id in (88, 89, 92, 343) else 0
        # For cards played as supporters/items, use different keys
        if name == "Hilda":
            freq = telemetry_rate(completed, "hilda_uses") if telemetry_sum(completed, "hilda_uses") else 0
        elif name == "Lillie":
            freq = telemetry_rate(completed, "lillie_uses") if telemetry_sum(completed, "lillie_uses") else 0
        elif name == "Poffin":
            freq = telemetry_rate(completed, "poffin_plays") if telemetry_sum(completed, "poffin_plays") else 0
        elif name == "Boss":
            freq = telemetry_rate(completed, "boss_uses")
        elif name == "Bangle":
            freq = telemetry_rate(completed, "brave_bangle_attachments")
        elif name == "Black Belt":
            freq = telemetry_rate(completed, "black_belt_uses")
        elif name == "Unfair Stamp":
            freq = telemetry_rate(completed, "unfair_stamp_plays") if telemetry_sum(completed, "unfair_stamp_plays") else 0
        elif name == "Bug Catching Set":
            freq = telemetry_rate(completed, "bug_set_plays") if telemetry_sum(completed, "bug_set_plays") else 0
        elif name == "Poké Pad":
            freq = telemetry_rate(completed, "poke_pad_plays") if telemetry_sum(completed, "poke_pad_plays") else 0
        elif name == "Boom Boom Groove":
            freq = telemetry_rate(completed, "thwackey_ability_uses") if telemetry_sum(completed, "thwackey_ability_uses") else 0
        elif name == "Quick Sign":
            freq = telemetry_rate(completed, "quick_sign_taken")
        # Split frequencies
        split_freq: dict[str, float] = {}
        for label, subset in (
            ("win", [r for r in completed if r["win"]]),
            ("loss", [r for r in completed if not r["win"]]),
            ("first", [r for r in completed if r.get("actual_order") == "first"]),
            ("second", [r for r in completed if r.get("actual_order") == "second"]),
        ):
            if subset:
                split_freq[label] = telemetry_rate(subset, f"{name.lower()}_uses") if name.lower() in ("hilda", "lillie", "poffin", "boss", "bangle", "black belt", "unfair stamp", "bug catching set", "poké pad", "boom boom groove", "quick sign") else 0.0
            else:
                split_freq[label] = 0.0
        card_frequencies[name] = {"overall": freq, **split_freq}

    # Late turn no productive attack
    late_no_atk = telemetry_rate(completed, "late_turns_no_productive_attack")

    # Support trapped active
    trapped = telemetry_rate(completed, "trapped_active_turns") if telemetry_sum(completed, "trapped_active_turns") else 0

    # Festival attack offered/taken
    offered = telemetry_rate(completed, "second_attacks_offered")
    taken = telemetry_rate(completed, "second_attacks_taken")
    missed = telemetry_rate(completed, "second_attacks_missed")

    # Replacement unavailable after KO
    repl_ready_end = telemetry_rate(completed, "replacement_attacker_ready_end_turn")

    # Unknown resolver
    unknown_ctx = telemetry_rate(completed, "unknown_contexts")

    # Policy fallback
    fallback = telemetry_rate(completed, "legal_fallbacks")

    # Policy errors
    errors = telemetry_rate(completed, "policy_errors")

    # Illegal actions
    illegal = _rate(sum(r.get("hero_illegal_actions", 0) for r in rows), len(rows))

    return MechanismAudit(
        overall_win_rate=_rate(wins, games),
        actual_first_win_rate=_rate(first_wins, len(first_rows)),
        actual_second_win_rate=_rate(second_wins, len(second_rows)),
        physical_seat_0_win_rate=_rate(seat_0_wins, len(seat_0_rows)),
        physical_seat_1_win_rate=_rate(seat_1_wins, len(seat_1_rows)),
        per_opponent=per_opponent,
        first_productive_attack_turn={
            "mean": first_atk_sum / first_atk_count if first_atk_count else 0,
            "max": first_atk_max,
            "count": first_atk_count,
        },
        first_festival_double_attack_turn={
            "festival_windows": festival_windows,
            "second_taken": second_taken,
            "rate": _rate(second_taken, festival_windows),
        },
        bench_size_at_first_attack={"note": "requires per-game bench_at_attack telemetry"},
        thwackey_present_at_first_attack={"note": "requires per-game thwackey_at_attack telemetry"},
        festival_active_at_first_attack={"note": "requires per-game festival_at_attack telemetry"},
        replacement_ready_after_first_attack={
            "replacement_ready_end_turn": repl_ready_end,
        },
        card_frequencies=card_frequencies,
        late_turn_no_productive_attack={"rate": late_no_atk},
        support_trapped_active={"rate": trapped},
        festival_attack_offered_taken={
            "offered": offered,
            "taken": taken,
            "missed": missed,
        },
        replacement_unavailable_after_ko={"rate": 1 - repl_ready_end},
        unknown_resolver_rate={"rate": unknown_ctx},
        policy_fallback_rate={"rate": fallback},
        policy_error_rate={"rate": errors},
        illegal_action_rate={"rate": illegal},
    )


def generate_markdown(audit: MechanismAudit, label: str = "D0") -> str:
    lines = [
        f"# {label} Mechanism Audit",
        "",
        "## Win Rates",
        f"- Overall: {audit.overall_win_rate:.1%}",
        f"- Actual First: {audit.actual_first_win_rate:.1%}",
        f"- Actual Second: {audit.actual_second_win_rate:.1%}",
        f"- Physical Seat 0: {audit.physical_seat_0_win_rate:.1%}",
        f"- Physical Seat 1: {audit.physical_seat_1_win_rate:.1%}",
        "",
        "## Per Opponent",
        "| Opponent | Overall | First | Second |",
        "|----------|---------|-------|--------|",
    ]
    for opp, rates in audit.per_opponent.items():
        lines.append(f"| {opp} | {rates['overall']:.1%} | {rates['first']:.1%} | {rates['second']:.1%} |")

    lines.extend([
        "",
        "## First Productive Attack",
        f"- Mean turn: {audit.first_productive_attack_turn.get('mean', 0):.2f}",
        f"- Max turn: {audit.first_productive_attack_turn.get('max', 0)}",
        f"- Games with attack: {audit.first_productive_attack_turn.get('count', 0)}",
        "",
        "## Festival Double Attack",
        f"- Windows: {audit.first_festival_double_attack_turn.get('festival_windows', 0)}",
        f"- Taken: {audit.first_festival_double_attack_turn.get('second_taken', 0)}",
        f"- Rate: {audit.first_festival_double_attack_turn.get('rate', 0):.1%}",
        "",
        "## Card Frequencies (per game)",
        "| Card | Overall | D0 Win | D0 Loss | First | Second |",
        "|------|---------|--------|---------|-------|--------|",
    ])
    for name, freq in audit.card_frequencies.items():
        if isinstance(freq, dict) and "overall" in freq:
            win_val = freq.get('win', 0)
            loss_val = freq.get('loss', 0)
            first_val = freq.get('first', 0)
            second_val = freq.get('second', 0)
            lines.append(
                f"| {name} | {freq.get('overall', 0):.2f} | "
                f"{win_val:.2f} | {loss_val:.2f} | "
                f"{first_val:.2f} | {second_val:.2f} |"
            )

    lines.extend([
        "",
        "## Late Turn No Productive Attack",
        f"- Rate: {audit.late_turn_no_productive_attack.get('rate', 0):.2f}",
        "",
        "## Support Trapped Active",
        f"- Rate: {audit.support_trapped_active.get('rate', 0):.2f}",
        "",
        "## Festival Attack Offered/Taken",
        f"- Offered: {audit.festival_attack_offered_taken.get('offered', 0):.2f}",
        f"- Taken: {audit.festival_attack_offered_taken.get('taken', 0):.2f}",
        f"- Missed: {audit.festival_attack_offered_taken.get('missed', 0):.2f}",
        "",
        "## Replacement Ready After KO",
        f"- Ready: {audit.replacement_ready_after_first_attack.get('replacement_ready_end_turn', 0):.2f}",
        f"- Unavailable: {audit.replacement_unavailable_after_ko.get('rate', 0):.2f}",
        "",
        "## Error Rates",
        f"- Unknown Resolver: {audit.unknown_resolver_rate.get('rate', 0):.2f}",
        f"- Policy Fallback: {audit.policy_fallback_rate.get('rate', 0):.2f}",
        f"- Policy Error: {audit.policy_error_rate.get('rate', 0):.2f}",
        f"- Illegal Action: {audit.illegal_action_rate.get('rate', 0):.2f}",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Baseline mechanism audit for Festival Dipplin")
    parser.add_argument("--input", type=Path, nargs="+", required=True, help="Evaluation JSON files")
    parser.add_argument("--output-json", type=Path, help="Output JSON audit")
    parser.add_argument("--output-md", type=Path, help="Output Markdown report")
    parser.add_argument("--label", default="D0", help="Label for report")
    args = parser.parse_args(argv)

    all_rows: list[dict[str, Any]] = []
    for path in args.input:
        data = load_evaluation(path)
        all_rows.extend(data.get("game_rows", []))

    if not all_rows:
        print("No game rows found in input files", file=sys.stderr)
        return 1

    audit = extract_mechanism_rates(all_rows)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(audit.to_dict(), indent=2, sort_keys=True))

    if args.output_md:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(generate_markdown(audit, args.label))

    print(generate_markdown(audit, args.label))
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main())