"""Generic information-set Monte Carlo search for training-only opponents.

The teacher deliberately contains no deck-specific tactical rules.  It knows the
two registered deck lists, samples hidden zones consistent with the public
observation, proposes legal actions from a neural policy, and scores candidates
by forward-simulated outcomes against frozen neural policies.
"""

from __future__ import annotations

import itertools
import math
import random
import sys
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from cg.api import all_card_data, search_begin, search_end, search_release, search_step, to_observation_class
from ptcg_ai.features import encode_observation
from ptcg_ai.model import NumpyPolicyModel
from ptcg_ai.safety import emergency_selection, sanitize_selection


class DeterminizationError(ValueError):
    """The public state could not be reconciled with a registered deck list."""


@dataclass(frozen=True)
class SearchConfig:
    determinizations: int = 2
    max_candidates: int = 8
    candidate_width: int = 8
    candidate_mode: str = "prior"
    rollout_steps: int = 320
    seed: int = 20260803


def load_deck(path: str | Path) -> list[int]:
    cards = [int(line) for line in Path(path).read_text().splitlines() if line.strip()]
    if len(cards) != 60:
        raise ValueError(f"deck must contain exactly 60 cards, got {len(cards)}: {path}")
    return cards


def _card_ids(cards) -> list[int]:
    return [int(card.id) for card in cards or [] if card is not None]


def _pokemon_card_ids(pokemon) -> list[int]:
    result: list[int] = []
    for card in pokemon or []:
        if card is None:
            continue
        result.append(int(card.id))
        result.extend(_card_ids(card.energyCards))
        result.extend(_card_ids(card.tools))
        result.extend(_card_ids(card.preEvolution))
    return result


def _card_serials(cards) -> set[int]:
    return {int(card.serial) for card in cards or [] if card is not None}


def visible_zone_serials(state, player_index: int) -> set[int]:
    player = state.players[player_index]
    result = _card_serials(player.hand) | _card_serials(player.discard) | _card_serials(player.prize)
    result |= {
        int(card.serial)
        for card in state.stadium or []
        if card is not None and int(card.playerIndex) == player_index
    }
    for pokemon_zone in (player.active, player.bench):
        for pokemon_card in pokemon_zone or []:
            if pokemon_card is None:
                continue
            result.add(int(pokemon_card.serial))
            result |= _card_serials(pokemon_card.energyCards)
            result |= _card_serials(pokemon_card.tools)
            result |= _card_serials(pokemon_card.preEvolution)
    return result


@lru_cache(maxsize=1)
def basic_card_ids() -> frozenset[int]:
    return frozenset(int(card.cardId) for card in all_card_data() if bool(card.basic))


def visible_zone_cards(state, player_index: int, include_hand: bool) -> list[int]:
    """Return cards publicly located outside hidden deck/prize/hand zones."""
    player = state.players[player_index]
    result = _pokemon_card_ids(player.active) + _pokemon_card_ids(player.bench)
    result.extend(_card_ids(player.discard))
    result.extend(
        int(card.id)
        for card in state.stadium or []
        if card is not None and int(card.playerIndex) == player_index
    )
    if include_hand:
        result.extend(_card_ids(player.hand))
    return result


def _subtract_known(full_deck: list[int], known: list[int], label: str) -> list[int]:
    pool = Counter(map(int, full_deck))
    for card_id in known:
        if pool[card_id] <= 0:
            raise DeterminizationError(f"{label}: visible card {card_id} exceeds deck multiplicity")
        pool[card_id] -= 1
    return list(pool.elements())


def _partition_hidden(
    full_deck: list[int],
    state,
    player_index: int,
    *,
    reveal_hand: bool,
    rng: random.Random,
    extra_known: list[int] | None = None,
) -> tuple[list[int], list[int], list[int], list[int]]:
    player = state.players[player_index]
    known_prizes = _card_ids(player.prize)
    known = (
        visible_zone_cards(state, player_index, include_hand=reveal_hand)
        + known_prizes
        + list(extra_known or [])
    )
    pool = _subtract_known(full_deck, known, f"player {player_index}")
    rng.shuffle(pool)

    hidden_active: list[int] = []
    active = player.active or []
    if active and active[0] is None:
        basic_index = next((index for index, card_id in enumerate(pool) if card_id in basic_card_ids()), None)
        if basic_index is None:
            raise DeterminizationError(f"player {player_index}: face-down active has no Basic candidate")
        hidden_active = [pool.pop(basic_index)]

    hand_count = 0 if reveal_hand else int(player.handCount)
    hidden_prize_count = len(player.prize) - len(known_prizes)
    expected = int(player.deckCount) + hand_count + hidden_prize_count
    if len(pool) != expected:
        raise DeterminizationError(
            f"player {player_index}: hidden pool has {len(pool)} cards, expected {expected} "
            f"(deck={player.deckCount}, hand={hand_count}, prize={hidden_prize_count})"
        )
    deck_end = int(player.deckCount)
    prize_end = deck_end + hidden_prize_count
    deck = pool[:deck_end]
    prizes = known_prizes + pool[deck_end:prize_end]
    hand = pool[prize_end:]
    return deck, prizes, hand, hidden_active


def determinize_known_matchup(
    obs,
    acting_deck: list[int],
    opponent_deck: list[int],
    rng: random.Random,
) -> dict:
    """Build ``search_begin`` inputs using only public state and registered decks."""
    state = obs.current
    if state is None or obs.select is None:
        raise DeterminizationError("search requires a live selection observation")
    me = int(state.yourIndex)
    opponent = 1 - me
    looking = getattr(state, "looking", None)
    known_serials = visible_zone_serials(state, me) | _card_serials(looking)
    transient = []
    for card in (getattr(obs.select, "contextCard", None), getattr(obs.select, "effect", None)):
        if (
            card is not None
            and int(card.playerIndex) == me
            and int(card.serial) not in known_serials
        ):
            transient.append(int(card.id))
            known_serials.add(int(card.serial))
    your_deck, your_prize, _, _your_hidden_active = _partition_hidden(
        acting_deck,
        state,
        me,
        reveal_hand=True,
        rng=rng,
        # Looking cards are temporarily outside hand/deck counts and are visible
        # only to the player currently resolving the effect.
        extra_known=_card_ids(looking) + transient,
    )
    opponent_hidden_deck, opponent_prize, opponent_hand, opponent_active = _partition_hidden(
        opponent_deck, state, opponent, reveal_hand=False, rng=rng
    )

    # When selecting from a revealed deck, the engine owns the exact deck view.
    if obs.select.deck is not None:
        your_deck = []

    return {
        "your_deck": your_deck,
        "your_prize": your_prize,
        "opponent_deck": opponent_hidden_deck,
        "opponent_prize": opponent_prize,
        "opponent_hand": opponent_hand,
        "opponent_active": opponent_active,
    }


def _softmax(values: np.ndarray) -> np.ndarray:
    shifted = np.asarray(values, dtype=np.float64) - float(np.max(values))
    probabilities = np.exp(shifted)
    return probabilities / probabilities.sum()


def candidate_actions(model: NumpyPolicyModel, obs, config: SearchConfig) -> list[tuple[list[int], float]]:
    """Return bounded legal action candidates and neural log-prior scores.

    ``prior`` preserves the original inexpensive policy-guided proposal.  In
    ``exhaustive`` mode every legal option participates before the final hard
    candidate cap is applied.  This matters when the seed policy is weak: a
    top-k option filter otherwise makes a strong but low-prior move impossible
    for forward search to discover.  The implementation remains deck-agnostic;
    the neural policy is used only to order multi-selections and break rollout
    ties.
    """
    if config.candidate_mode not in {"prior", "exhaustive"}:
        raise ValueError(f"unsupported candidate mode: {config.candidate_mode!r}")
    if config.max_candidates <= 0:
        raise ValueError("max_candidates must be positive")
    features = encode_observation(obs, model.feature_version)
    logits, count_logits, _ = model.predict(features)
    select = obs.select
    minimum, maximum = int(select.minCount), int(select.maxCount)
    if not len(select.option):
        return [([], 0.0)]

    if minimum == maximum:
        counts = [minimum]
    else:
        valid = list(range(minimum, maximum + 1))
        ranked_counts = sorted(valid, key=lambda count: float(count_logits[count]), reverse=True)
        counts = list(dict.fromkeys(ranked_counts[:3] + [minimum, maximum]))

    option_order = np.argsort(-np.asarray(logits)).astype(int).tolist()
    if config.candidate_mode == "exhaustive":
        pool = option_order
    else:
        width = min(len(option_order), max(config.candidate_width, max(counts, default=0)))
        pool = option_order[:width]
    results: list[tuple[list[int], float]] = []
    count_probs = _softmax(np.asarray(count_logits)[minimum : maximum + 1]) if minimum != maximum else None

    for count in counts:
        if count == 0:
            combinations = [tuple()]
        elif count <= len(pool):
            combinations = itertools.combinations(pool, count)
        else:
            continue
        for combination in combinations:
            action = sorted(combination, key=lambda index: float(logits[index]), reverse=True)
            action = sanitize_selection(select, action, count)
            available = list(range(len(logits)))
            log_prior = 0.0
            if count_probs is not None:
                log_prior += math.log(max(1e-12, float(count_probs[count - minimum])))
            for index in action:
                probabilities = _softmax(np.asarray(logits)[available])
                local = available.index(index)
                log_prior += math.log(max(1e-12, float(probabilities[local])))
                available.pop(local)
            results.append((action, log_prior))

    # Keep the highest-prior unique selections.  No tactical option types are privileged.
    unique: dict[tuple[int, ...], float] = {}
    for action, log_prior in results:
        key = tuple(action)
        unique[key] = max(log_prior, unique.get(key, -math.inf))
    ranked = sorted(unique.items(), key=lambda item: item[1], reverse=True)[: config.max_candidates]
    return [(list(action), prior) for action, prior in ranked] or [(emergency_selection(select), 0.0)]


def deterministic_model_action(model: NumpyPolicyModel, obs) -> list[int]:
    features = encode_observation(obs, model.feature_version)
    logits, count_logits, _ = model.predict(features)
    select = obs.select
    if int(select.minCount) == int(select.maxCount):
        count = int(select.minCount)
    else:
        low, high = int(select.minCount), int(select.maxCount)
        count = low + int(np.argmax(np.asarray(count_logits)[low : high + 1]))
    ranked = np.argsort(-np.asarray(logits)).astype(int).tolist()
    return sanitize_selection(select, ranked, count)


def rollout_to_outcome(
    state,
    root_player: int,
    actor_model: NumpyPolicyModel,
    opponent_model: NumpyPolicyModel,
    rollout_steps: int,
) -> float:
    """Roll out frozen neural policies; return an exact outcome or neutral truncation."""
    for _ in range(rollout_steps):
        current = state.observation.current
        if current is None:
            return 0.0
        if int(current.result) >= 0:
            if int(current.result) == 2:
                return 0.0
            return 1.0 if int(current.result) == root_player else -1.0
        if state.observation.select is None:
            return 0.0
        model = actor_model if int(current.yourIndex) == root_player else opponent_model
        try:
            action = deterministic_model_action(model, state.observation)
        except Exception:
            action = emergency_selection(state.observation.select)
        state = search_step(state.searchId, action)
    return 0.0


class SearchTeacherAgent:
    """Training-only callable that improves a frozen neural policy with search."""

    def __init__(
        self,
        deck_path: str | Path,
        model_path: str | Path,
        opponent_deck_path: str | Path,
        opponent_model_path: str | Path,
        config: SearchConfig | None = None,
    ):
        self.deck = load_deck(deck_path)
        self.opponent_deck = load_deck(opponent_deck_path)
        self.model = NumpyPolicyModel(model_path)
        self.opponent_model = NumpyPolicyModel(opponent_model_path)
        self.config = config or SearchConfig()
        self.calls = 0
        self.search_errors = 0
        self.rollouts = 0
        self.error_counts: Counter[str] = Counter()
        self.last_error = ""

    def __call__(self, obs_dict: dict) -> list[int]:
        if obs_dict.get("select") is None:
            return list(self.deck)
        obs = to_observation_class(obs_dict)
        candidates = candidate_actions(self.model, obs, self.config)
        if len(candidates) == 1:
            return candidates[0][0]

        self.calls += 1
        scores = [0.0] * len(candidates)
        completed = [0] * len(candidates)
        for world_index in range(self.config.determinizations):
            root = None
            try:
                rng = random.Random(
                    self.config.seed + self.calls * 1_000_003 + world_index * 10_007
                )
                kwargs = determinize_known_matchup(obs, self.deck, self.opponent_deck, rng)
                root = search_begin(obs, **kwargs)
                for index, (action, _prior) in enumerate(candidates):
                    child = None
                    try:
                        child = search_step(root.searchId, action)
                        scores[index] += rollout_to_outcome(
                            child,
                            int(obs.current.yourIndex),
                            self.model,
                            self.opponent_model,
                            self.config.rollout_steps,
                        )
                        completed[index] += 1
                        self.rollouts += 1
                    finally:
                        if child is not None:
                            search_release(child.searchId)
            except Exception as exc:
                self.search_errors += 1
                key = f"{type(exc).__name__}: {exc}"
                self.error_counts[key] += 1
                self.last_error = key
            finally:
                if root is not None:
                    try:
                        search_release(root.searchId)
                    except Exception:
                        pass
                try:
                    search_end()
                except Exception:
                    pass

        def rank(index: int) -> tuple[float, float]:
            mean = scores[index] / completed[index] if completed[index] else -math.inf
            return mean, candidates[index][1]

        best = max(range(len(candidates)), key=rank)
        if not completed[best]:
            return candidates[0][0]
        return candidates[best][0]

    def telemetry(self) -> dict:
        return {
            "search_calls": self.calls,
            "search_errors": self.search_errors,
            "search_rollouts": self.rollouts,
            "search_error_counts": dict(self.error_counts),
            "last_search_error": self.last_error,
        }


def evaluate_disagreement_record(
    record: dict,
    config: SearchConfig,
    hero_deck: list[int],
    opp_deck: list[int],
    model: NumpyPolicyModel | None = None,
    opponent_model: NumpyPolicyModel | None = None,
) -> dict:
    """Evaluate paired counterfactual advantage between elite action and d842 action on common random numbers."""
    elite_action = record.get("elite_action") or record.get("action", [])
    d842_action = record.get("d842_action", [])
    obs_raw = record.get("observation") or record.get("obs_dict")
    
    if obs_raw is None:
        # If raw observation dict is not directly attached, return neutral
        return {
            "record": record,
            "advantage": 0.0,
            "informative_worlds": 0,
            "retained": False,
            "error": "missing raw observation dict for determinization",
        }

    obs = to_observation_class(obs_raw) if not hasattr(obs_raw, "current") else obs_raw
    if obs.current is None or obs.select is None:
        return {
            "record": record,
            "advantage": 0.0,
            "informative_worlds": 0,
            "retained": False,
            "error": "inactive select observation",
        }

    hero_seat = int(obs.current.yourIndex)
    if model is None:
        model = NumpyPolicyModel(ROOT / "artifacts" / "overnight_grim_20260730" / "grim_selected.npz")
    if opponent_model is None:
        opponent_model = model

    scores_elite = []
    scores_d842 = []
    informative_worlds = 0
    errors = 0

    for world_idx in range(config.determinizations):
        root = None
        try:
            rng = random.Random(config.seed + world_idx * 10_007 + int(record.get("step", 0)) * 31)
            kwargs = determinize_known_matchup(obs, hero_deck, opp_deck, rng)
            root = search_begin(obs, **kwargs)

            # 1. Roll out elite action
            child_e = None
            try:
                child_e = search_step(root.searchId, elite_action)
                s_e = rollout_to_outcome(child_e, hero_seat, model, opponent_model, config.rollout_steps)
            finally:
                if child_e is not None:
                    try:
                        search_release(child_e.searchId)
                    except Exception:
                        pass

            # 2. Roll out d842 action
            child_d = None
            try:
                child_d = search_step(root.searchId, d842_action)
                s_d = rollout_to_outcome(child_d, hero_seat, model, opponent_model, config.rollout_steps)
            finally:
                if child_d is not None:
                    try:
                        search_release(child_d.searchId)
                    except Exception:
                        pass

            scores_elite.append(s_e)
            scores_d842.append(s_d)
            if s_e != s_d:
                informative_worlds += 1

        except Exception as exc:
            errors += 1
        finally:
            if root is not None:
                try:
                    search_release(root.searchId)
                except Exception:
                    pass
            try:
                search_end()
            except Exception:
                pass

    n = len(scores_elite)
    if n == 0 or errors > 0:
        return {
            "record": record,
            "advantage": 0.0,
            "informative_worlds": informative_worlds,
            "retained": False,
            "errors": errors,
        }

    mean_advantage = (sum(scores_elite) - sum(scores_d842)) / n
    retained = (mean_advantage >= 0.50 and informative_worlds >= max(1, config.determinizations // 2) and errors == 0)

    return {
        "record": record,
        "advantage": mean_advantage,
        "informative_worlds": informative_worlds,
        "retained": retained,
        "elite_scores": scores_elite,
        "d842_scores": scores_d842,
        "errors": errors,
    }
