#!/usr/bin/env python3
"""Audit whether an actual-second opening Active choice was forced.

This is a setup-only diagnostic, not a strength evaluator.  It stops each
native deal at the hero's SETUP_ACTIVE prompt and records only aggregate Basic
candidate multisets plus the selected Basic.  It never advances into gameplay
and never serializes a hand, deck order, or Prize identity.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from cg import sim as cg_sim  # noqa: E402
from cg.api import OptionType, SelectContext, to_observation_class  # noqa: E402
from cg.game import battle_finish, battle_select, battle_start  # noqa: E402
from ptcg_ai.dipplin.cards import (  # noqa: E402
    BUG_SET,
    GRASS_ENERGY,
    GROOKEY,
    VOLBEAT,
)
from ptcg_ai.external import ExternalSubmissionAgent  # noqa: E402
from training.evaluation_schema import sha256_file, sha256_path  # noqa: E402


SCHEMA = "dipplin-setup-choice-audit-v1"


class SetupAuditError(RuntimeError):
    """A setup prompt or package invariant was not safely resolved."""


def _deck(path: Path) -> list[int]:
    try:
        cards = [int(line) for line in path.read_text().splitlines() if line.strip()]
    except (OSError, ValueError) as error:
        raise SetupAuditError(f"cannot read deck {path}: {error}") from error
    if len(cards) != 60:
        raise SetupAuditError(f"deck must contain exactly 60 rows: {path}")
    return cards


def _forced_first_action(select: Any, desired_first_player: int) -> list[int]:
    yes = [
        index
        for index, option in enumerate(select.option)
        if int(option.type) == int(OptionType.YES)
    ]
    no = [
        index
        for index, option in enumerate(select.option)
        if int(option.type) == int(OptionType.NO)
    ]
    # IS_FIRST belongs to physical seat zero in the audited engine contract.
    choices = yes if int(desired_first_player) == 0 else no
    if len(choices) != 1:
        raise SetupAuditError("IS_FIRST prompt lacks one semantic YES/NO choice")
    return [choices[0]]


def _reset_submission(agent: ExternalSubmissionAgent) -> None:
    internal = getattr(agent.module, "_AGENT", None)
    reset = getattr(internal, "reset", None)
    if not callable(reset):
        raise SetupAuditError("submission does not expose resettable _AGENT")
    reset()


def summarize_setup_choices(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    selected = Counter(int(row["selected_active_id"]) for row in rows)
    candidate_multisets = Counter(
        ",".join(map(str, row["candidate_basic_ids"])) for row in rows
    )
    grookey = [row for row in rows if int(row["selected_active_id"]) == GROOKEY]
    elective = [
        row
        for row in grookey
        if VOLBEAT in set(map(int, row["candidate_basic_ids"]))
    ]
    categories = Counter(
        (
            "with_volbeat" if VOLBEAT in set(map(int, row["candidate_basic_ids"])) else "no_volbeat",
            "known_energy_path" if bool(row["known_quick_sign_energy_path"]) else "no_known_energy_path",
        )
        for row in grookey
    )
    choice_scope: dict[str, Any] = {}
    for card_id in sorted(selected):
        card_rows = [
            row for row in rows if int(row["selected_active_id"]) == card_id
        ]
        only_candidate = sum(
            len(set(map(int, row["candidate_basic_ids"]))) == 1
            for row in card_rows
        )
        alternative_counts = Counter(
            alternative
            for row in card_rows
            for alternative in set(map(int, row["candidate_basic_ids"]))
            if alternative != card_id
        )
        choice_scope[str(card_id)] = {
            "selected": len(card_rows),
            "only_distinct_candidate": only_candidate,
            "with_any_alternative": len(card_rows) - only_candidate,
            "with_known_quick_sign_energy_path": sum(
                bool(row["known_quick_sign_energy_path"])
                for row in card_rows
            ),
            "alternative_basic_presence": {
                str(alternative): count
                for alternative, count in sorted(alternative_counts.items())
            },
        }
    games = len(rows)
    return {
        "games": games,
        "selected_active_counts": {
            str(card_id): count for card_id, count in sorted(selected.items())
        },
        "selected_choice_scope": choice_scope,
        "candidate_basic_multiset_counts": dict(sorted(candidate_multisets.items())),
        "grookey_selected": len(grookey),
        "grookey_with_selectable_volbeat": len(elective),
        "grookey_selection_categories": {
            f"{left}:{right}": count
            for (left, right), count in sorted(categories.items())
        },
        "grookey_with_selectable_volbeat_rate_all_openings": (
            len(elective) / games if games else None
        ),
        "grookey_with_selectable_volbeat_rate_within_grookey": (
            len(elective) / len(grookey) if grookey else None
        ),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    submission = args.submission.resolve()
    opponent_deck_path = args.opponent_deck.resolve()
    opponent_deck = _deck(opponent_deck_path)
    before = sha256_path(submission)
    hero = ExternalSubmissionAgent(submission, {})
    rows: list[dict[str, Any]] = []
    try:
        if list(hero.deck) != _deck(submission / "deck.csv"):
            raise SetupAuditError("submission adapter deck differs from deck.csv")
        for game_index in range(int(args.games)):
            hero_seat = game_index % 2
            desired_first = 1 - hero_seat  # the hero is always actual-second
            decks = [hero.deck, opponent_deck] if hero_seat == 0 else [opponent_deck, hero.deck]
            raw, started = battle_start(decks[0], decks[1])
            battle_active = raw is not None and int(started.errorType) == 0
            if not battle_active:
                raise SetupAuditError(
                    f"engine rejected setup game {game_index}: errorType={int(started.errorType)}"
                )
            try:
                found = False
                for _step in range(12):
                    obs = to_observation_class(raw)
                    current, select = obs.current, obs.select
                    if current is None or select is None:
                        raise SetupAuditError("setup observation is incomplete")
                    acting_seat = int(current.yourIndex)
                    if (
                        acting_seat == hero_seat
                        and int(select.context)
                        == int(SelectContext.SETUP_ACTIVE_POKEMON)
                    ):
                        hand = list(current.players[hero_seat].hand or ())
                        candidate_ids = tuple(
                            sorted(int(hand[int(option.index)].id) for option in select.option)
                        )
                        hand_ids = {int(card.id) for card in hand}
                        _reset_submission(hero)
                        action = list(map(int, hero(raw)))
                        if len(action) != 1 or not 0 <= action[0] < len(select.option):
                            raise SetupAuditError(
                                f"invalid setup action in game {game_index}: {action!r}"
                            )
                        selected_option = select.option[action[0]]
                        selected_id = int(hand[int(selected_option.index)].id)
                        rows.append(
                            {
                                "selected_active_id": selected_id,
                                "candidate_basic_ids": candidate_ids,
                                "known_quick_sign_energy_path": (
                                    GRASS_ENERGY in hand_ids or BUG_SET in hand_ids
                                ),
                            }
                        )
                        found = True
                        break
                    if int(select.context) == int(SelectContext.IS_FIRST):
                        action = _forced_first_action(select, desired_first)
                    else:
                        minimum = max(0, int(select.minCount))
                        if minimum > len(select.option):
                            raise SetupAuditError("mandatory setup count exceeds options")
                        action = list(range(minimum))
                    raw = battle_select(action)
                if not found:
                    raise SetupAuditError(
                        f"hero SETUP_ACTIVE prompt not reached in game {game_index}"
                    )
            finally:
                battle_finish()
    finally:
        hero.close()
    after = sha256_path(submission)
    if before != after:
        raise SetupAuditError("submission tree changed during setup audit")
    archive_sha = sha256_file(args.archive.resolve()) if args.archive else None
    return {
        "schema": SCHEMA,
        "scope": "aggregate setup-only diagnostic; not gameplay or strength evidence",
        "actual_order": "second",
        "physical_seat_split": {
            "seat_0": (int(args.games) + 1) // 2,
            "seat_1": int(args.games) // 2,
        },
        "summary": summarize_setup_choices(rows),
        "interpretation_contract": {
            "selectable_volbeat_is_causal_win_evidence": False,
            "maximum_direct_policy_scope": "grookey_with_selectable_volbeat_rate_all_openings",
            "known_quick_sign_energy_path": "Grass Energy or Bug Catching Set visible in the hero hand",
        },
        "information_contract": {
            "serialized_full_hands": False,
            "serialized_deck_order": False,
            "serialized_prize_identities": False,
            "aggregate_basic_candidate_multisets_only": True,
        },
        "rng_contract": {
            "engine": "independent_std_random_device",
            "seeded": False,
            "paired_deals": False,
        },
        "provenance": {
            "submission_path": str(submission),
            "submission_tree_sha256": before,
            "submission_unchanged": True,
            "archive_path": str(args.archive.resolve()) if args.archive else None,
            "archive_sha256": archive_sha,
            "opponent_deck_path": str(opponent_deck_path),
            "opponent_deck_sha256": sha256_file(opponent_deck_path),
            "engine_path": str(Path(cg_sim.lib_path).resolve()),
            "engine_sha256": sha256_file(Path(cg_sim.lib_path).resolve()),
            "evaluator_path": str(Path(__file__).resolve()),
            "evaluator_sha256": sha256_file(Path(__file__).resolve()),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submission", required=True, type=Path)
    parser.add_argument("--opponent-deck", required=True, type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--games", type=int, default=5000)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.games <= 0:
        raise SystemExit("--games must be positive")
    output = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps(output["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
