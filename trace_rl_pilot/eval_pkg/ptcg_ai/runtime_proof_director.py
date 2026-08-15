"""Fail-closed runtime proof for immediate, deterministic game wins.

The frozen policy remains the decision maker.  This module receives its exact
already-sanitized action and only replaces it when a bounded native sibling
comparison proves one semantic alternative wins *at this prompt* in every
public-information determinization.  It deliberately does not score nonterminal
positions, continue through later prompts, inspect an opponent deck, or retain
option indices between calls.

Native search is process-global and synchronous.  Deadlines here are therefore
soft: an individual C call cannot be interrupted, but an over-budget result is
discarded and all states are still released before returning the baseline.
"""

from __future__ import annotations

import copy
import hashlib
import math
import random
import time
from collections import Counter
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Mapping, Protocol, Sequence

from cg.api import AreaType, LogType, OptionType, to_observation_class

from .prevention import attack_nullified
from .proof_search import (
    SemanticCandidate,
    public_state_digest,
    semantic_action_key,
    semantic_candidates,
)


_ALLOWED_REASONS = frozenset(
    {
        "attack_over_end",
        "lethal_attack",
        "attack_choice",
        "ko_target",
        "ready_promotion",
    }
)
_REASON_PRIORITY = {
    "attack_over_end": 0,
    "lethal_attack": 1,
    "attack_choice": 2,
    "ko_target": 3,
    "ready_promotion": 4,
}
_OPPONENT_FILLERS = (
    (7, 646),  # Darkness Energy, Marnie's Impidimp
    (3, 860),  # Water Energy, Snorunt
)
_RANDOM_LOG_TYPES = frozenset(
    {
        int(LogType.SHUFFLE),
        int(LogType.HAS_BASIC_POKEMON),
        int(LogType.DRAW),
        int(LogType.DRAW_REVERSE),
        int(LogType.COIN),
    }
)
_TURN_BOUNDARY_LOG_TYPES = frozenset({int(LogType.TURN_START), int(LogType.TURN_END)})
_MOVE_LOG_TYPES = frozenset({int(LogType.MOVE_CARD), int(LogType.MOVE_CARD_REVERSE)})


class RuntimeProofError(RuntimeError):
    """The runtime comparison could not be completed safely."""


class RuntimeProofTimeout(RuntimeProofError):
    """The soft per-decision runtime budget expired."""


class _CleanupError(RuntimeProofError):
    pass


class _InformationSetError(RuntimeProofError):
    pass


@dataclass(frozen=True)
class RuntimeProofConfig:
    """Limits for the terminal-only runtime proof.

    ``max_native_*`` and ``max_search_calls_per_game`` are reset by ``reset``.
    They are intentionally small because native calls are synchronous.
    """

    worlds: int = 2
    max_candidates: int = 3
    timeout_seconds: float = 0.05
    max_search_calls_per_game: int = 8
    max_native_roots_per_game: int = 32
    max_native_steps_per_game: int = 96
    max_cumulative_seconds_per_game: float = 1.0
    seed_salt: str = "grim-runtime-terminal-proof-v1"

    def __post_init__(self) -> None:
        if not 2 <= self.worlds <= 8:
            raise ValueError("worlds must be in [2, 8]")
        if not 2 <= self.max_candidates <= 8:
            raise ValueError("max_candidates must be in [2, 8]")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        if self.max_search_calls_per_game <= 0:
            raise ValueError("max_search_calls_per_game must be positive")
        if self.max_native_roots_per_game <= 0:
            raise ValueError("max_native_roots_per_game must be positive")
        if self.max_native_steps_per_game <= 0:
            raise ValueError("max_native_steps_per_game must be positive")
        if (
            not math.isfinite(self.max_cumulative_seconds_per_game)
            or self.max_cumulative_seconds_per_game <= 0
        ):
            raise ValueError("max_cumulative_seconds_per_game must be finite and positive")
        if not self.seed_salt:
            raise ValueError("seed_salt must not be empty")


@dataclass(frozen=True)
class BranchEvidence:
    """Public, order-comparable evidence from one native child."""

    result: int
    same_turn: bool
    tainted: bool
    public_digest: str


class RuntimeSearchBackend(Protocol):
    """Injectable boundary around the native process-global search API."""

    def begin(self, obs: Any, determinization: Mapping[str, Sequence[int]]) -> Any: ...

    def step(self, search_id: int, action: Sequence[int]) -> Any: ...

    def release(self, search_id: int) -> None: ...

    def end(self) -> None: ...


class _CgRuntimeSearchBackend:
    def begin(self, obs: Any, determinization: Mapping[str, Sequence[int]]) -> Any:
        from cg.api import search_begin

        return search_begin(obs, manual_coin=False, **dict(determinization))

    def step(self, search_id: int, action: Sequence[int]) -> Any:
        from cg.api import search_step

        return search_step(int(search_id), list(map(int, action)))

    def release(self, search_id: int) -> None:
        from cg.api import search_release

        search_release(int(search_id))

    def end(self) -> None:
        from cg.api import search_end

        search_end()


def _integer(value: Any, default: int = -1) -> int:
    try:
        if isinstance(value, IntEnum):
            return int(value.value)
        return int(value)
    except (TypeError, ValueError):
        return default


def _validate_action(select: Any, action: Sequence[int]) -> tuple[int, ...]:
    normalized = tuple(int(index) for index in action)
    options = list(getattr(select, "option", None) or [])
    if len(set(normalized)) != len(normalized):
        raise ValueError("duplicate option index")
    if any(index < 0 or index >= len(options) for index in normalized):
        raise ValueError("option index out of range")
    minimum = _integer(getattr(select, "minCount", None), 0)
    maximum = _integer(getattr(select, "maxCount", None), 0)
    if not minimum <= len(normalized) <= maximum:
        raise ValueError("illegal selection count")
    return normalized


def runtime_world_seeds(obs: Any, config: RuntimeProofConfig) -> tuple[int, ...]:
    """Derive deterministic seeds solely from the public-state digest."""

    digest = public_state_digest(obs)
    seeds: list[int] = []
    for world_index in range(config.worlds):
        material = f"{config.seed_salt}:{digest}:{world_index}".encode("ascii")
        seeds.append(int.from_bytes(hashlib.sha256(material).digest()[:8], "big"))
    return tuple(seeds)


def _card_id(card: Any) -> int:
    card_id = _integer(getattr(card, "id", None))
    if card_id < 0:
        raise _InformationSetError("visible card has no valid ID")
    return card_id


def _identified_prize_present(obs: Any) -> bool:
    current = getattr(obs, "current", None)
    return any(
        card is not None
        for player in (getattr(current, "players", None) or [])
        for card in (getattr(player, "prize", None) or [])
    )


def _candidate_public_view(obs: Any) -> Any:
    """Redact private identities before semantic candidate generation.

    Candidate semantics may inspect board, discard, stadium, public counts, and
    option shapes.  The hero hand is intentionally absent here; its identities
    are used only later by ``_public_determinization`` to construct an internally
    valid exact-hero information set for the native engine.
    """

    view = copy.copy(obs)
    current = copy.copy(obs.current)
    players = [copy.copy(player) for player in (getattr(current, "players", None) or [])]
    me = _integer(getattr(current, "yourIndex", None))
    for index, player in enumerate(players):
        player.prize = [None] * len(getattr(player, "prize", None) or [])
        player.hand = [] if index == me else None
    current.players = players
    current.looking = None
    view.current = current
    select = copy.copy(obs.select)
    select.deck = None
    select.contextCard = None
    select.effect = None
    view.select = select
    return view


def _public_determinization(
    obs: Any,
    hero_deck: Sequence[int],
    *,
    seed: int,
    world_index: int,
) -> dict[str, list[int]]:
    """Build a runtime information set without an opponent-deck oracle.

    The exact registered hero list, public hero zones, and the hero's legally
    observed hand are used to partition its unknown deck/prizes.  Hand identities
    are used only here, never by candidate semantics.  Any identified prize card
    fails closed.  Opponent hidden zones are filled from two deliberately
    different sentinels using only public zone counts.  Search results that touch
    those opaque zones are marked tainted and cannot prove an override.
    """

    current = getattr(obs, "current", None)
    select = getattr(obs, "select", None)
    if current is None or select is None:
        raise _InformationSetError("missing current/select")
    if getattr(select, "deck", None) is not None:
        raise _InformationSetError("deck-selection prompt is outside the runtime slice")
    if getattr(current, "looking", None) is not None:
        raise _InformationSetError("looking state is outside the runtime slice")
    if _identified_prize_present(obs):
        raise _InformationSetError("identified prize card is outside the runtime slice")

    players = list(getattr(current, "players", None) or [])
    me = _integer(getattr(current, "yourIndex", None))
    if len(players) != 2 or me not in (0, 1):
        raise _InformationSetError("invalid player state")
    mine = players[me]
    opponent = players[1 - me]

    remaining = Counter(map(int, hero_deck))
    seen_serials: set[int] = set()

    def consume(card: Any, *, expected_owner: int | None = me) -> None:
        if card is None:
            return
        owner = getattr(card, "playerIndex", None)
        if expected_owner is not None and owner is not None and _integer(owner) != expected_owner:
            raise _InformationSetError("visible card owner mismatch")
        serial = _integer(getattr(card, "serial", None))
        if serial >= 0:
            if serial in seen_serials:
                return
            seen_serials.add(serial)
        card_id = _card_id(card)
        if remaining[card_id] <= 0:
            raise _InformationSetError("visible card exceeds registered deck multiplicity")
        remaining[card_id] -= 1

    def consume_pokemon(pokemon: Any) -> None:
        consume(pokemon)
        for name in ("energyCards", "tools", "preEvolution"):
            for attached in getattr(pokemon, name, None) or []:
                consume(attached)

    for pokemon in (getattr(mine, "active", None) or []):
        consume_pokemon(pokemon)
    for pokemon in (getattr(mine, "bench", None) or []):
        consume_pokemon(pokemon)
    for card in (getattr(mine, "discard", None) or []):
        consume(card)

    hand = getattr(mine, "hand", None)
    hand_count = _integer(getattr(mine, "handCount", None), 0)
    if hand is None:
        if hand_count:
            raise _InformationSetError("hero hand identities unavailable")
    else:
        visible_hand = [card for card in hand if card is not None]
        if len(visible_hand) != hand_count:
            raise _InformationSetError("hero hand count mismatch")
        for card in visible_hand:
            consume(card)

    own_prizes = list(getattr(mine, "prize", None) or [])

    for stadium in (getattr(current, "stadium", None) or []):
        if _integer(getattr(stadium, "playerIndex", None)) == me:
            consume(stadium)

    # An effect/context card can be transiently absent from its ordinary zone.
    # Serial de-duplication prevents counting the common in-zone representation
    # twice while still accounting for a genuinely transient hero card.
    for transient in (getattr(select, "contextCard", None), getattr(select, "effect", None)):
        if transient is not None and _integer(getattr(transient, "playerIndex", me)) == me:
            consume(transient)

    pool = [card_id for card_id in sorted(remaining) for _ in range(remaining[card_id])]
    deck_count = _integer(getattr(mine, "deckCount", None), -1)
    unknown_prize_count = sum(card is None for card in own_prizes)
    if deck_count < 0 or len(pool) != deck_count + unknown_prize_count:
        raise _InformationSetError("registered deck does not match visible hero zones")
    random.Random(int(seed)).shuffle(pool)
    your_deck = pool[:deck_count]
    unknown_prizes = iter(pool[deck_count:])
    your_prize = [int(next(unknown_prizes)) for _card in own_prizes]

    energy_filler, basic_filler = _OPPONENT_FILLERS[world_index % len(_OPPONENT_FILLERS)]
    opponent_deck_count = _integer(getattr(opponent, "deckCount", None), -1)
    opponent_hand_count = _integer(getattr(opponent, "handCount", None), -1)
    if opponent_deck_count < 0 or opponent_hand_count < 0:
        raise _InformationSetError("invalid opponent hidden-zone count")
    opponent_deck = [energy_filler] * opponent_deck_count
    # Keep setup-compatible sentinels without pretending they are a real deck.
    if opponent_deck:
        opponent_deck[0] = basic_filler
    opponent_prize = [energy_filler] * len(getattr(opponent, "prize", None) or [])
    opponent_hand = [energy_filler] * opponent_hand_count
    active = list(getattr(opponent, "active", None) or [])
    opponent_active = [basic_filler] if active == [None] else []

    return {
        "your_deck": your_deck,
        "your_prize": your_prize,
        "opponent_deck": opponent_deck,
        "opponent_prize": opponent_prize,
        "opponent_hand": opponent_hand,
        "opponent_active": opponent_active,
    }


def _copy_determinization(value: Mapping[str, Sequence[int]]) -> dict[str, list[int]]:
    return {name: list(map(int, cards)) for name, cards in value.items()}


def _candidate_set(
    obs: Any,
    baseline: tuple[int, ...],
    config: RuntimeProofConfig,
) -> tuple[SemanticCandidate, ...]:
    """Resolve a fresh, bounded semantic set for this exact prompt."""

    semantic_obs = _candidate_public_view(obs)
    baseline_key = semantic_action_key(semantic_obs, baseline)
    baseline_candidate = SemanticCandidate(
        action=baseline,
        key=baseline_key,
        reason="d842_baseline",
        is_baseline=True,
    )
    # Ask for more than the shipped cap so unrelated proof_search tactics cannot
    # crowd out the narrow allowed family before filtering.  The request remains
    # statically bounded and the final set is capped by config.max_candidates.
    raw = semantic_candidates(semantic_obs, baseline, max_candidates=32)
    alternatives: dict[str, SemanticCandidate] = {}
    options = list(getattr(obs.select, "option", None) or [])
    for candidate in raw:
        if candidate.is_baseline or candidate.reason not in _ALLOWED_REASONS:
            continue
        action = _validate_action(semantic_obs.select, candidate.action)
        key = semantic_action_key(semantic_obs, action)
        if key != candidate.key:
            raise RuntimeProofError("semantic candidate did not resolve on the current prompt")
        if candidate.reason in {"attack_over_end", "lethal_attack", "attack_choice"}:
            if len(action) != 1:
                continue
            option = options[action[0]]
            if _integer(getattr(option, "type", None)) != int(OptionType.ATTACK):
                continue
            if attack_nullified(semantic_obs, option):
                continue
        else:
            if len(action) != 1:
                continue
            option = options[action[0]]
            if _integer(getattr(option, "type", None)) != int(OptionType.CARD):
                continue
            if _integer(getattr(option, "area", None)) not in {
                int(AreaType.ACTIVE),
                int(AreaType.BENCH),
            }:
                continue
        alternatives[key] = SemanticCandidate(action, key, candidate.reason, False)

    ordered = sorted(
        alternatives.values(),
        key=lambda item: (_REASON_PRIORITY[item.reason], item.key),
    )
    return tuple([baseline_candidate, *ordered[: config.max_candidates - 1]])


def _prize_counts(obs: Any) -> tuple[int, int] | None:
    current = getattr(obs, "current", None)
    players = list(getattr(current, "players", None) or [])
    if len(players) != 2:
        return None
    return (
        len(getattr(players[0], "prize", None) or []),
        len(getattr(players[1], "prize", None) or []),
    )


def _is_hidden_tainted(
    root_obs: Any,
    child_obs: Any,
    *,
    root_player: int,
    terminal_win: bool,
) -> bool:
    select = getattr(child_obs, "select", None)
    current = getattr(child_obs, "current", None)
    root_prizes = _prize_counts(root_obs)
    child_prizes = _prize_counts(child_obs)
    if root_prizes is None or child_prizes is None:
        return True
    opponent = 1 - root_player
    final_prize_take = (
        terminal_win
        and root_prizes[root_player] > 0
        and child_prizes[root_player] == 0
        and child_prizes[opponent] == root_prizes[opponent]
    )
    if child_prizes != root_prizes and not final_prize_take:
        return True
    if select is not None and getattr(select, "deck", None) is not None:
        return True
    if current is not None and getattr(current, "looking", None) is not None:
        return True

    for log in (getattr(child_obs, "logs", None) or []):
        log_type = _integer(getattr(log, "type", None))
        if log_type in _RANDOM_LOG_TYPES:
            return True
        if log_type not in _MOVE_LOG_TYPES:
            continue
        source = _integer(getattr(log, "fromArea", None))
        target = _integer(getattr(log, "toArea", None))
        owner = _integer(getattr(log, "playerIndex", None))
        areas = {source, target}
        if int(AreaType.DECK) in areas or int(AreaType.LOOKING) in areas:
            return True
        if int(AreaType.PRIZE) in areas:
            # Taking the last known-count prize after a KO exposes an identity but
            # cannot change the already-terminal result.  All other prize motion
            # remains outside this proof slice.
            ordinary_terminal_take = (
                final_prize_take
                and owner == root_player
                and source == int(AreaType.PRIZE)
                and target == int(AreaType.HAND)
            )
            if not ordinary_terminal_take:
                return True
        if int(AreaType.HAND) in areas and owner != root_player:
            return True
    return False


def _branch_evidence(root_obs: Any, child_obs: Any, root_player: int) -> BranchEvidence:
    current = getattr(child_obs, "current", None)
    if current is None:
        raise RuntimeProofError("native child has no current state")
    result = _integer(getattr(current, "result", None), -1)
    terminal_win = result == root_player
    root_turn = _integer(getattr(root_obs.current, "turn", None), -1)
    child_turn = _integer(getattr(current, "turn", None), -2)
    crossed_turn_boundary = any(
        _integer(getattr(log, "type", None)) in _TURN_BOUNDARY_LOG_TYPES
        for log in (getattr(child_obs, "logs", None) or [])
    )
    same_turn = terminal_win and child_turn == root_turn and not crossed_turn_boundary
    return BranchEvidence(
        result=result,
        same_turn=same_turn,
        tainted=_is_hidden_tainted(
            root_obs,
            child_obs,
            root_player=root_player,
            terminal_win=terminal_win,
        ),
        public_digest=public_state_digest(child_obs),
    )


class RuntimeProofDirector:
    """Terminal-only proof wrapper around an externally supplied baseline action."""

    def __init__(
        self,
        hero_deck: Sequence[int],
        *,
        config: RuntimeProofConfig | None = None,
        backend: RuntimeSearchBackend | None = None,
    ) -> None:
        self.hero_deck = tuple(map(int, hero_deck))
        if len(self.hero_deck) != 60:
            raise ValueError("runtime proof requires the exact 60-card hero deck")
        self.config = config or RuntimeProofConfig()
        self.backend = backend or _CgRuntimeSearchBackend()
        self.reset()

    def reset(self) -> None:
        """Reset per-game budgets and ephemeral in-memory telemetry."""

        self._calls = 0
        self._triggers = 0
        self._overrides = 0
        self._search_calls = 0
        self._native_roots = 0
        self._native_steps = 0
        self._cumulative_search_seconds = 0.0
        self._status_counts: Counter[str] = Counter()
        self._reason_counts: Counter[str] = Counter()
        self._last: dict[str, Any] = {
            "phase": "terminal_proof",
            "status": "reset",
            "reason": "reset",
            "public_digest": "",
            "candidate_count": 0,
            "coverage": 0,
            "latency_ms": 0.0,
            "error_type": None,
        }

    @property
    def telemetry(self) -> dict[str, Any]:
        """Return a copy containing counters and names, never observations/actions."""

        return {
            "phase": "terminal_proof",
            "calls": self._calls,
            "triggers": self._triggers,
            "overrides": self._overrides,
            "budget": {
                "search_calls_used": self._search_calls,
                "search_calls_limit": self.config.max_search_calls_per_game,
                "native_roots_used": self._native_roots,
                "native_roots_limit": self.config.max_native_roots_per_game,
                "native_steps_used": self._native_steps,
                "native_steps_limit": self.config.max_native_steps_per_game,
                "cumulative_search_ms": round(self._cumulative_search_seconds * 1000.0, 3),
                "cumulative_search_ms_limit": round(
                    self.config.max_cumulative_seconds_per_game * 1000.0, 3
                ),
            },
            "statuses": dict(sorted(self._status_counts.items())),
            "reasons": dict(sorted(self._reason_counts.items())),
            "last": dict(self._last),
        }

    def _record(
        self,
        action: list[Any],
        *,
        status: str,
        reason: str,
        started: float,
        digest: str = "",
        candidate_count: int = 0,
        coverage: int = 0,
        error: Exception | None = None,
    ) -> list[Any]:
        self._status_counts[status] += 1
        self._reason_counts[reason] += 1
        self._last = {
            "phase": "terminal_proof",
            "status": status,
            "reason": reason,
            "public_digest": digest,
            "candidate_count": int(candidate_count),
            "coverage": int(coverage),
            "latency_ms": round((time.monotonic() - started) * 1000.0, 3),
            "error_type": None if error is None else type(error).__name__,
        }
        return action

    def _budget_allows(self, candidate_count: int) -> bool:
        planned_roots = self.config.worlds * 2
        planned_steps = planned_roots * candidate_count
        return (
            self._search_calls < self.config.max_search_calls_per_game
            and self._native_roots + planned_roots <= self.config.max_native_roots_per_game
            and self._native_steps + planned_steps <= self.config.max_native_steps_per_game
            and self._cumulative_search_seconds < self.config.max_cumulative_seconds_per_game
        )

    @staticmethod
    def _check_deadline(deadline: float, label: str) -> None:
        if time.monotonic() >= deadline:
            raise RuntimeProofTimeout(f"deadline {label}")

    def _evaluate_root(
        self,
        obs: Any,
        ordered: Sequence[SemanticCandidate],
        determinization: Mapping[str, Sequence[int]],
        deadline: float,
    ) -> dict[str, BranchEvidence]:
        root = None
        begin_attempted = False
        attempted_releases: set[int] = set()
        cleanup_errors: list[str] = []
        primary_error: Exception | None = None
        evidence: dict[str, BranchEvidence] = {}

        def state_id(state: Any) -> int:
            search_id = getattr(state, "searchId", None)
            if search_id is None:
                raise RuntimeProofError("native state has no searchId")
            return int(search_id)

        def release(state: Any, label: str) -> None:
            try:
                search_id = state_id(state)
                if search_id in attempted_releases:
                    raise RuntimeProofError("native state ID was returned more than once")
                attempted_releases.add(search_id)
                self.backend.release(search_id)
            except Exception as exc:  # every cleanup defect invalidates the proof
                cleanup_errors.append(f"{label}:{type(exc).__name__}")

        try:
            self._check_deadline(deadline, "before search_begin")
            native_input = _copy_determinization(determinization)
            self._native_roots += 1
            begin_attempted = True
            root = self.backend.begin(obs, native_input)
            root_id = state_id(root)
            self._check_deadline(deadline, "after search_begin")
            root_player = int(obs.current.yourIndex)
            for candidate in ordered:
                child = None
                try:
                    self._check_deadline(deadline, "before search_step")
                    self._native_steps += 1
                    child = self.backend.step(root_id, candidate.action)
                    state_id(child)
                    self._check_deadline(deadline, "after search_step")
                    evidence[candidate.key] = _branch_evidence(
                        obs,
                        child.observation,
                        root_player,
                    )
                finally:
                    if child is not None:
                        release(child, "child_release")
        except Exception as exc:
            primary_error = exc
        finally:
            if root is not None:
                release(root, "root_release")
            if begin_attempted:
                try:
                    # search_end is required once for every begin attempt,
                    # including an attempt whose search_begin raised.
                    self.backend.end()
                except Exception as exc:
                    cleanup_errors.append(f"search_end:{type(exc).__name__}")

        if cleanup_errors:
            raise _CleanupError(";".join(cleanup_errors))
        if primary_error is not None:
            if isinstance(primary_error, RuntimeProofTimeout):
                raise primary_error
            raise RuntimeProofError(type(primary_error).__name__) from primary_error
        self._check_deadline(deadline, "after cleanup")
        return evidence

    def _prove(
        self,
        obs: Any,
        candidates: tuple[SemanticCandidate, ...],
        deadline: float,
    ) -> tuple[SemanticCandidate | None, str, int]:
        keys = {candidate.key for candidate in candidates}
        if len(keys) != len(candidates):
            return None, "duplicate_semantic_candidate", 0
        baseline = next((candidate for candidate in candidates if candidate.is_baseline), None)
        if baseline is None or sum(candidate.is_baseline for candidate in candidates) != 1:
            return None, "invalid_baseline_candidate", 0

        worlds: dict[str, list[BranchEvidence]] = {candidate.key: [] for candidate in candidates}
        coverage = 0
        for world_index, seed in enumerate(runtime_world_seeds(obs, self.config)):
            determinization = _public_determinization(
                obs,
                self.hero_deck,
                seed=seed,
                world_index=world_index,
            )
            forward = self._evaluate_root(obs, candidates, determinization, deadline)
            reverse = self._evaluate_root(
                obs,
                tuple(reversed(candidates)),
                determinization,
                deadline,
            )
            if set(forward) != keys or set(reverse) != keys:
                return None, "incomplete_coverage", coverage
            for candidate in candidates:
                first = forward[candidate.key]
                second = reverse[candidate.key]
                coverage += 2
                if first != second:
                    return None, "order_inconsistent", coverage
                worlds[candidate.key].append(first)

        baseline_evidence = worlds[baseline.key]
        if baseline_evidence and all(
            branch.result == int(obs.current.yourIndex) and branch.same_turn
            for branch in baseline_evidence
        ):
            return None, "baseline_already_terminal_win", coverage

        qualified: list[SemanticCandidate] = []
        saw_terminal = False
        saw_tainted_terminal = False
        for candidate in candidates:
            if candidate.is_baseline:
                continue
            branches = worlds[candidate.key]
            terminal_everywhere = bool(branches) and all(
                branch.result == int(obs.current.yourIndex) and branch.same_turn
                for branch in branches
            )
            saw_terminal = saw_terminal or terminal_everywhere
            if not terminal_everywhere:
                continue
            if any(branch.tainted for branch in branches):
                saw_tainted_terminal = True
                continue
            qualified.append(candidate)

        if len(qualified) > 1:
            return None, "ambiguous_terminal_winner", coverage
        if len(qualified) == 1:
            return qualified[0], "proved_same_turn_terminal_win", coverage
        if saw_tainted_terminal:
            return None, "terminal_winner_tainted", coverage
        if saw_terminal:
            return None, "terminal_winner_rejected", coverage
        return None, "no_same_turn_terminal_win", coverage

    def choose(self, obs_or_dict: Any, baseline_action: Sequence[int]) -> list[int]:
        """Return a proved terminal action or the exact supplied baseline values."""

        started = time.monotonic()
        self._calls += 1
        try:
            # This unnormalized copy is the only value used on every fallthrough.
            fallback = list(baseline_action)
        except Exception as exc:
            # The public contract is list[int]; a non-sequence cannot be returned
            # byte-for-byte, so use an empty safe value and expose only the type.
            return self._record(
                [],
                status="abstained",
                reason="unreadable_baseline",
                started=started,
                error=exc,
            )

        digest = ""
        try:
            obs = (
                to_observation_class(obs_or_dict)
                if isinstance(obs_or_dict, dict)
                else obs_or_dict
            )
            current = getattr(obs, "current", None)
            select = getattr(obs, "select", None)
            if current is None or select is None:
                return self._record(
                    fallback,
                    status="baseline",
                    reason="missing_current_or_select",
                    started=started,
                )
            if getattr(obs, "search_begin_input", None) is None:
                return self._record(
                    fallback,
                    status="baseline",
                    reason="missing_search_payload",
                    started=started,
                )
            if _integer(getattr(current, "result", None), -1) >= 0:
                return self._record(
                    fallback,
                    status="baseline",
                    reason="battle_already_terminal",
                    started=started,
                )
            if (
                getattr(select, "deck", None) is not None
                or getattr(current, "looking", None) is not None
                or _identified_prize_present(obs)
            ):
                raise _InformationSetError("observation is outside the public runtime slice")
            digest = public_state_digest(obs)
            baseline = _validate_action(select, fallback)
            candidates = _candidate_set(obs, baseline, self.config)
            if len(candidates) <= 1:
                return self._record(
                    fallback,
                    status="baseline",
                    reason="no_semantic_alternative",
                    started=started,
                    digest=digest,
                    candidate_count=len(candidates),
                )
            self._triggers += 1
            if not self._budget_allows(len(candidates)):
                return self._record(
                    fallback,
                    status="abstained",
                    reason="budget_exhausted",
                    started=started,
                    digest=digest,
                    candidate_count=len(candidates),
                )

            self._search_calls += 1
            search_started = time.monotonic()
            remaining_game_seconds = max(
                0.0,
                self.config.max_cumulative_seconds_per_game
                - self._cumulative_search_seconds,
            )
            deadline = search_started + min(
                self.config.timeout_seconds,
                remaining_game_seconds,
            )
            deadline = min(deadline, started + self.config.timeout_seconds)
            try:
                candidate, reason, coverage = self._prove(
                    obs,
                    candidates,
                    deadline,
                )
                self._check_deadline(deadline, "after proof")
            finally:
                self._cumulative_search_seconds += time.monotonic() - search_started
            if candidate is None:
                return self._record(
                    fallback,
                    status="abstained",
                    reason=reason,
                    started=started,
                    digest=digest,
                    candidate_count=len(candidates),
                    coverage=coverage,
                )
            self._overrides += 1
            return self._record(
                list(candidate.action),
                status="proved",
                reason=reason,
                started=started,
                digest=digest,
                candidate_count=len(candidates),
                coverage=coverage,
            )
        except RuntimeProofTimeout as exc:
            return self._record(
                fallback,
                status="abstained",
                reason="timeout",
                started=started,
                digest=digest,
                error=exc,
            )
        except _CleanupError as exc:
            return self._record(
                fallback,
                status="abstained",
                reason="cleanup_error",
                started=started,
                digest=digest,
                error=exc,
            )
        except _InformationSetError as exc:
            return self._record(
                fallback,
                status="abstained",
                reason="information_set_error",
                started=started,
                digest=digest,
                error=exc,
            )
        except ValueError as exc:
            return self._record(
                fallback,
                status="abstained",
                reason="invalid_input",
                started=started,
                digest=digest,
                error=exc,
            )
        except Exception as exc:
            return self._record(
                fallback,
                status="abstained",
                reason="runtime_error",
                started=started,
                digest=digest,
                error=exc,
            )


__all__ = [
    "BranchEvidence",
    "RuntimeProofConfig",
    "RuntimeProofDirector",
    "RuntimeProofError",
    "RuntimeProofTimeout",
    "RuntimeSearchBackend",
    "runtime_world_seeds",
]
