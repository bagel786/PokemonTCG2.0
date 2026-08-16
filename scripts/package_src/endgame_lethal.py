"""Fail-closed current-turn terminal-win search for the prize endgame.

Trigger: our remaining prizes <= 2. At any select prompt inside our own turn,
run a tiny DFS over the remainder of the CURRENT TURN using the native search
engine. Override the base action only when a continuation that provably ends
the game in OUR win exists. Otherwise return None (exact base behavior).

Hardening guarantees (V1.1):
- BASE-FIRST: if the base (EXP23) first action itself has a provable terminal
  continuation in ALL determinization worlds, abstain (no win-more overrides).
- HIDDEN-ZONE FAIL-CLOSED: any branch that reaches a prompt with
  ``select.deck`` set (deck selection / hidden allocation) or LOOK context is
  killed. Deck-order-dependent PLAY cards are also excluded from searched
  lines. Every surviving line touches only public zones.
- MULTI-WORLD: a claimed first action must produce a terminal hero win in ALL
  N=3 independent determinization worlds (same option index, same proof).
- EXACT ACTION: a candidate is only returned if selecting exactly [index]
  satisfies minCount/maxCount and sanitize_selection reproduces [index].
- DETERMINISTIC BUDGETS: node-count budgets only (no wall-clock cutoffs).
- Receding horizon: no option indices are stored across prompts; the search
  reruns from the current prompt every time it fires.
"""

from __future__ import annotations

import os
import random
import time

from cg.api import OptionType, SelectContext, to_observation_class

from .card_ids import (
    BUDDY_BUDDY_POFFIN,
    DAWN,
    LILLIES_DETERMINATION,
    POKEGEAR_30,
    POKE_PAD,
    TEAM_ROCKETS_PETREL,
    UNFAIR_STAMP,
)

MAX_PRIZES_TRIGGER = 2
MAX_DEPTH = 6
MAX_NODES = 150
WORLDS = 3
WORLD_SEEDS = (2026081601, 2026081602, 2026081603)

# Cards whose outcome depends on hidden deck order or hidden prize contents.
DECK_ORDER_DEPENDENT_PLAYS = frozenset(
    {
        POKEGEAR_30,
        POKE_PAD,
        BUDDY_BUDDY_POFFIN,
        LILLIES_DETERMINATION,
        UNFAIR_STAMP,
        TEAM_ROCKETS_PETREL,
        DAWN,
    }
)


def _play_card_id(state, option) -> int | None:
    if option.type != OptionType.PLAY:
        return None
    me = int(state.yourIndex)
    hand = state.players[me].hand or []
    if option.index is None or option.index >= len(hand):
        return None
    card = hand[option.index]
    if card is None or getattr(card, "id", None) is None:
        return None
    return int(card.id)


def _option_priority(option) -> int:
    priority = {
        OptionType.ATTACK: 0,
        OptionType.ABILITY: 1,
        OptionType.RETREAT: 2,
        OptionType.EVOLVE: 3,
        OptionType.PLAY: 4,
        OptionType.ATTACH: 5,
        OptionType.END: 6,
        OptionType.DISCARD: 7,
    }
    return priority.get(option.type, 8)


class EndgameLethal:
    """Terminal-win DFS overlay; always fails closed to the caller's action."""

    def __init__(self, hero_deck: list[int]) -> None:
        self.hero_deck = list(hero_deck)
        from .search import ArchetypeRegistry

        self.registry = ArchetypeRegistry()
        self.fires: list[dict] = []
        self.last_abstain: str | None = None
        self.telemetry_path = os.environ.get("PTCG_ENDGAME_TELEMETRY", "") or None

    def reset(self) -> None:
        self.fires = []

    @staticmethod
    def _remaining_prizes(obs) -> int | None:
        state = obs.current
        if state is None:
            return None
        me = int(state.yourIndex)
        if me < 0 or me >= len(state.players or []):
            return None
        return len(state.players[me].prize or [])

    def _log(self, row: dict) -> None:
        self.fires.append(row)
        if not self.telemetry_path:
            return
        try:
            import json

            with open(self.telemetry_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
        except Exception:
            pass

    def _opponent_deck(self, obs) -> list[int]:
        from .search import visible_zone_cards

        state = obs.current
        opponent = 1 - int(state.yourIndex)
        visible = set(visible_zone_cards(state, opponent, include_hand=False))
        _, deck, _ = self.registry.match(visible)
        if deck is None:
            deck = self.hero_deck
        return list(deck)

    def action_wins(self, obs, action: list[int], seed: int, trace: list | None = None) -> bool:
        """True if taking exactly `action` from the current prompt reaches a
        terminal hero win within the current turn, in the given determinization
        world, without touching any hidden-zone selection. If `trace` is a
        list, the first winning continuation is appended as (context, action)
        pairs in execution order."""
        from .search import determinize_state, search_begin, search_end, search_release, search_step

        opponent_deck = self._opponent_deck(obs)
        root = None
        nodes = 0
        local_trace: list = []
        try:
            kwargs = determinize_state(obs, self.hero_deck, opponent_deck, random.Random(seed))
            root = search_begin(obs, **kwargs)
            me = int(obs.current.yourIndex)
            root_turn = int(obs.current.turn)
            if not action:
                return False
            child = None
            try:
                child = search_step(int(root.searchId), action)
            except Exception:
                return False

            def dfs(state, depth: int) -> bool:
                nonlocal nodes
                child_obs = state.observation
                current = child_obs.current
                if current is not None and int(current.result) >= 0:
                    return int(current.result) == me
                if child_obs.select is None or current is None:
                    return False
                if child_obs.select.deck is not None:
                    return False
                if int(child_obs.select.context) == SelectContext.LOOK:
                    return False
                if int(current.yourIndex) != me or int(current.turn) != root_turn:
                    return False
                if depth >= MAX_DEPTH:
                    return False
                ordered = sorted(
                    enumerate(child_obs.select.option),
                    key=lambda pair: (_option_priority(pair[1]), pair[0]),
                )
                for index, option in ordered:
                    if nodes >= MAX_NODES:
                        return False
                    nodes += 1
                    if option.type == OptionType.PLAY and _play_card_id(current, option) in DECK_ORDER_DEPENDENT_PLAYS:
                        continue
                    grandchild = None
                    try:
                        grandchild = search_step(int(state.searchId), [index])
                    except Exception:
                        continue
                    try:
                        if dfs(grandchild, depth + 1):
                            local_trace.append((int(child_obs.select.context), [index]))
                            return True
                    finally:
                        try:
                            search_release(int(grandchild.searchId))
                        except Exception:
                            pass
                return False

            try:
                won = dfs(child, 1)
                if won:
                    local_trace.append((int(obs.select.context), list(action)))
                return won
            finally:
                try:
                    search_release(int(child.searchId))
                except Exception:
                    pass
        except Exception:
            return False
        finally:
            if root is not None:
                try:
                    search_release(int(root.searchId))
                except Exception:
                    pass
            try:
                search_end()
            except Exception:
                pass
            if trace is not None and local_trace:
                trace.extend(reversed(local_trace))

    def try_override(self, obs_dict: dict, base_action: list[int] | None = None) -> list[int] | None:
        """Return a terminal-win action for the current prompt, or None.

        BASE-FIRST: if `base_action` provably wins in every world, return None.
        """
        self.last_abstain = None
        if os.environ.get("PTCG_ENDGAME_LETHAL", "1").lower() in {"0", "false", "off", "no"}:
            self.last_abstain = "disabled"
            return None
        started = time.perf_counter()
        try:
            obs = to_observation_class(obs_dict)
        except Exception:
            self.last_abstain = "parse_error"
            return None
        if obs.select is None or obs.select.context in (
            SelectContext.IS_FIRST,
            SelectContext.SETUP_ACTIVE_POKEMON,
            SelectContext.SETUP_BENCH_POKEMON,
        ):
            self.last_abstain = "context"
            return None
        if obs.select.deck is not None:
            self.last_abstain = "hidden_zone_prompt"
            return None
        if int(obs.select.context) == SelectContext.LOOK:
            self.last_abstain = "look_context"
            return None
        prizes = self._remaining_prizes(obs)
        if prizes is None or prizes > MAX_PRIZES_TRIGGER:
            self.last_abstain = "prize_gate"
            return None
        if not obs.select.option:
            self.last_abstain = "no_options"
            return None

        if base_action:
            base_outcomes = [self.action_wins(obs, base_action, seed) for seed in WORLD_SEEDS]
            if any(base_outcomes):
                # Base already has a proven continuation (in >=1 world). Never
                # override: either it surely wins (all worlds) or we cannot
                # disprove it; overriding risks disturbing a winning line.
                self.last_abstain = "base_already_lethal"
                return None

        from .safety import sanitize_selection

        for index, option in sorted(
            enumerate(obs.select.option),
            key=lambda pair: (_option_priority(pair[1]), pair[0]),
        ):
            if option.type == OptionType.PLAY and _play_card_id(obs.current, option) in DECK_ORDER_DEPENDENT_PLAYS:
                continue
            if not (int(obs.select.minCount) <= 1 <= int(obs.select.maxCount)):
                continue
            try:
                if sanitize_selection(obs.select, [index], 1) != [index]:
                    continue
            except Exception:
                continue
            if all(self.action_wins(obs, [index], seed) for seed in WORLD_SEEDS):
                self._log(
                    {
                        "rule": "endgame_lethal",
                        "ctx": int(obs.select.context),
                        "prizes": prizes,
                        "action": [index],
                        "worlds": WORLDS,
                        "base_won": False,
                        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
                    }
                )
                return [index]
        self.last_abstain = "no_proof"
        return None
