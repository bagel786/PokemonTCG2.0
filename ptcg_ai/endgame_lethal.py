"""Fail-closed current-turn terminal-win search for the prize endgame.

Trigger: our remaining prizes <= 2. At any select prompt inside our own turn,
run a tiny DFS over the remainder of the CURRENT TURN using the native search
engine. Override the base action only when a continuation that provably ends
the game in OUR win exists. Otherwise return None (exact base behavior).

Provability rules (public state only):
- The winning line must terminate before the opponent acts (result >= 0 with
  result == yourIndex while still inside our turn).
- Deck-order-dependent plays are NOT stepped into: Pokégear 3.0, Poké Pad,
  Buddy-Buddy Poffin, Lillie's Determination, Unfair Stamp. Excluding them
  makes the search invariant to hidden deck order for both players, because
  nothing else in the Grim deck touches a hidden zone.
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
MAX_NODES = 400
TIME_BUDGET_MS = 150.0

# Cards whose outcome depends on hidden deck order or hidden prize contents.
# Excluding them makes every searched line provable from public state alone:
# the Grim deck's remaining actions (Boss, Night Stretcher, Rare Candy, Dawn
# excluded, energy attach, evolve, retreat, abilities, attacks, stadiums)
# touch only fully known zones.
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


class EndgameLethal:
    """Terminal-win DFS overlay; always fails closed to the caller's action."""

    def __init__(self, hero_deck: list[int]) -> None:
        self.hero_deck = list(hero_deck)
        from .search import ArchetypeRegistry

        self.registry = ArchetypeRegistry()
        self.fires: list[dict] = []
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

    @staticmethod
    def _play_card_id(obs, option) -> int | None:
        if option.type != OptionType.PLAY:
            return None
        state = obs.current
        me = int(state.yourIndex)
        hand = state.players[me].hand or []
        if option.index is None or option.index >= len(hand):
            return None
        card = hand[option.index]
        if card is None or getattr(card, "id", None) is None:
            return None
        return int(card.id)

    @staticmethod
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

    def try_override(self, obs_dict: dict) -> list[int] | None:
        """Return a terminal-win action for the current prompt, or None."""
        if os.environ.get("PTCG_ENDGAME_LETHAL", "1").lower() in {"0", "false", "off", "no"}:
            return None
        try:
            obs = to_observation_class(obs_dict)
        except Exception:
            return None
        if obs.select is None or obs.select.context in (
            SelectContext.IS_FIRST,
            SelectContext.SETUP_ACTIVE_POKEMON,
            SelectContext.SETUP_BENCH_POKEMON,
        ):
            return None
        prizes = self._remaining_prizes(obs)
        if prizes is None or prizes > MAX_PRIZES_TRIGGER:
            return None
        if not obs.select.option:
            return None

        opponent_deck = self._opponent_deck(obs)
        root = None
        started = time.perf_counter()
        nodes = 0
        try:
            from .search import determinize_state, search_begin, search_end, search_release, search_step

            kwargs = determinize_state(
                obs,
                self.hero_deck,
                opponent_deck,
                random.Random(2026081601),
            )
            root = search_begin(obs, **kwargs)
            me = int(obs.current.yourIndex)
            root_turn = int(obs.current.turn)

            def expired() -> bool:
                return (time.perf_counter() - started) * 1000.0 >= TIME_BUDGET_MS

            def dfs(state, depth: int) -> bool:
                nonlocal nodes
                child_obs = state.observation
                current = child_obs.current
                if current is not None and int(current.result) >= 0:
                    return int(current.result) == me
                if child_obs.select is None:
                    return False
                if current is None:
                    return False
                if int(current.yourIndex) != me or int(current.turn) != root_turn:
                    return False
                if depth >= MAX_DEPTH:
                    return False
                ordered = sorted(
                    enumerate(child_obs.select.option),
                    key=lambda pair: (self._option_priority(pair[1]), pair[0]),
                )
                for index, option in ordered:
                    if expired() or nodes >= MAX_NODES:
                        return False
                    nodes += 1
                    if option.type == OptionType.PLAY and self._play_card_id(child_obs, option) in DECK_ORDER_DEPENDENT_PLAYS:
                        continue
                    child = None
                    try:
                        child = search_step(int(state.searchId), [index])
                    except Exception:
                        continue
                    try:
                        if dfs(child, depth + 1):
                            return True
                    finally:
                        try:
                            search_release(int(child.searchId))
                        except Exception:
                            pass
                return False

            winning_first: int | None = None
            ordered = sorted(
                enumerate(obs.select.option),
                key=lambda pair: (self._option_priority(pair[1]), pair[0]),
            )
            for index, option in ordered:
                if expired() or nodes >= MAX_NODES:
                    break
                nodes += 1
                if option.type == OptionType.PLAY and self._play_card_id(obs, option) in DECK_ORDER_DEPENDENT_PLAYS:
                    continue
                child = None
                try:
                    child = search_step(int(root.searchId), [index])
                except Exception:
                    continue
                try:
                    if dfs(child, 1):
                        winning_first = index
                        break
                finally:
                    try:
                        search_release(int(child.searchId))
                    except Exception:
                        pass
            if winning_first is not None:
                self._log(
                    {
                        "rule": "endgame_lethal",
                        "ctx": int(obs.select.context),
                        "nodes": nodes,
                        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
                        "prizes": prizes,
                        "action": [winning_first],
                    }
                )
                return [winning_first]
            return None
        except Exception:
            return None
        finally:
            if root is not None:
                try:
                    search_release(int(root.searchId))
                except Exception:
                    pass
            try:
                from .search import search_end

                search_end()
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
