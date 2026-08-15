"""Kaggle replay parsing with correct observation/action alignment."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from cg.api import to_observation_class

from .features import EVENT_NUMERIC_SIZE, encode_observation, public_state_delta


@dataclass
class ReplayDecision:
    episode_id: int | str
    team: str
    seat: int
    step: int
    deck: list[int]
    action: list[int]
    reward: float
    features: dict
    legal_options: list[dict]
    chooser_seat: int | None = None
    hero_is_chooser: bool | None = None
    choice: str | None = None
    first_player: int | None = None
    hero_order: str | None = None
    turn: int = 0
    own_turn_ordinal: int = 0
    observation: dict | None = None

    def to_json(self) -> dict:
        return {
            "episode_id": self.episode_id,
            "team": self.team,
            "seat": self.seat,
            "step": self.step,
            "deck": self.deck,
            "action": self.action,
            "reward": self.reward,
            "features": self.features,
            "legal_options": self.legal_options,
            "chooser_seat": self.chooser_seat,
            "hero_is_chooser": self.hero_is_chooser,
            "choice": self.choice,
            "first_player": self.first_player,
            "hero_order": self.hero_order,
            "turn": self.turn,
            "own_turn_ordinal": self.own_turn_ordinal,
            "observation": self.observation,
        }


def load_episode(path: str | Path) -> dict:
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def episode_reward(episode: dict, seat: int) -> float | None:
    """Return a binary game outcome for ``seat``, or None for unfinished games.

    Public Kaggle episodes occasionally contain a rewards list whose entries are null.
    Finished Pokemon TCG observations still record the winning seat in
    ``current.result``, so use that authoritative engine value as a fallback.  Do not
    turn an unresolved outcome into a loss: doing so would poison the value target.
    """
    rewards = episode.get("rewards")
    if isinstance(rewards, list) and seat < len(rewards):
        reward = rewards[seat]
        if isinstance(reward, (int, float)) and not isinstance(reward, bool):
            return float(reward > 0)

    for step in reversed(episode.get("steps") or []):
        for row in step:
            current = (row.get("observation") or {}).get("current") or {}
            winner = current.get("result", -1)
            if winner in (0, 1):
                return float(winner == seat)
    return None


def episode_order(episode: dict) -> tuple[int | None, str | None, int | None]:
    """Return ``(chooser_seat, choice, first_player)`` from raw replay actions.

    Kaggle stores the answer to the observation at row ``t`` in row ``t+1``.
    The current engine assigns the IS_FIRST question to seat 0, but this parser
    derives that fact instead of baking it into downstream analysis.
    """
    steps = episode.get("steps") or []
    chooser = None
    choice = None
    first_player = None
    for step_index, step in enumerate(steps):
        for seat, row in enumerate(step[:2]):
            current = (row.get("observation") or {}).get("current") or {}
            observed_first = current.get("firstPlayer")
            if observed_first in (0, 1):
                first_player = int(observed_first)
            select = (row.get("observation") or {}).get("select") or {}
            if int(select.get("context", -1)) != 41 or step_index + 1 >= len(steps):
                continue
            chooser = seat
            following = steps[step_index + 1]
            action = following[seat].get("action") if seat < len(following) else None
            if isinstance(action, list) and len(action) == 1:
                options = select.get("option") or []
                selected = options[action[0]] if 0 <= action[0] < len(options) else {}
                option_type = int(selected.get("type", -1))
                if option_type == 1:
                    choice = "first"
                elif option_type == 2:
                    choice = "second"
    if chooser is not None and choice is None and first_player in (0, 1):
        choice = "first" if chooser == first_player else "second"
    return chooser, choice, first_player


def own_turn_ordinal(turn: int, seat: int, first_player: int | None) -> int:
    if first_player not in (0, 1) or turn <= 0:
        return 0
    return (turn + 1) // 2 if seat == first_player else turn // 2


def iter_decisions(
    episode: dict,
    allowed_teams: set[str] | None = None,
    feature_version: int = 2,
    include_observation: bool | None = None,
) -> Iterator[ReplayDecision]:
    """Yield decisions, pairing observation at step t with action at t+1.

    Kaggle replay rows store the action that produced the row's observation. Pairing fields
    within one row silently teaches the wrong labels; this one-step alignment is required.
    """
    steps = episode.get("steps") or []
    if len(steps) < 2:
        return
    info = episode.get("info") or {}
    teams = info.get("TeamNames") or ["seat-0", "seat-1"]
    rewards = [episode_reward(episode, seat) for seat in range(2)]
    episode_id = info.get("EpisodeId", episode.get("id", "unknown"))
    decks: list[list[int]] = [[], []]
    if len(steps) > 1:
        for seat in range(min(2, len(steps[1]))):
            candidate = steps[1][seat].get("action") or []
            if len(candidate) == 60:
                decks[seat] = [int(card) for card in candidate]
    chooser_seat, choice, first_player = episode_order(episode)
    action_history: list[list[dict]] = [[], []]
    history_turn = [-1, -1]

    for step_index in range(len(steps) - 1):
        current = steps[step_index]
        following = steps[step_index + 1]
        for seat in range(min(len(current), len(following), 2)):
            # Kaggle retains a row for both agents at every environment step.
            # INACTIVE rows can contain a stale, still-valid-looking select
            # payload, but their following action is not a decision made from
            # that payload.  Admitting them creates duplicate/misaligned labels
            # (notably empty setup-bench selections), so require replay truth.
            if str(current[seat].get("status", "")).upper() != "ACTIVE":
                continue
            team = teams[seat] if seat < len(teams) else f"seat-{seat}"
            if allowed_teams is not None and team not in allowed_teams:
                continue
            if rewards[seat] is None:
                continue
            obs_dict = current[seat].get("observation") or {}
            if obs_dict.get("select") is None or obs_dict.get("current") is None:
                continue
            action = following[seat].get("action")
            if not isinstance(action, list):
                continue
            select = obs_dict["select"]
            if not select.get("option"):
                continue
            if not (select["minCount"] <= len(action) <= select["maxCount"]):
                continue
            if len(set(action)) != len(action) or any(i < 0 or i >= len(select["option"]) for i in action):
                continue
            obs = to_observation_class(obs_dict)
            turn = int(obs.current.turn or 0)
            if history_turn[seat] != turn:
                history_turn[seat] = turn
                action_history[seat] = []
            encoded = encode_observation(
                obs,
                feature_version,
                action_history=action_history[seat] if feature_version >= 4 else None,
            )
            result_delta = [0.0] * EVENT_NUMERIC_SIZE
            if feature_version >= 5:
                try:
                    next_obs_dict = following[seat].get("observation") or {}
                    if next_obs_dict.get("current") is not None:
                        next_obs = to_observation_class(next_obs_dict)
                        if int(next_obs.current.yourIndex) == int(obs.current.yourIndex):
                            result_delta = public_state_delta(obs, next_obs)
                except Exception:
                    result_delta = [0.0] * EVENT_NUMERIC_SIZE
            yield ReplayDecision(
                episode_id=episode_id,
                team=team,
                seat=seat,
                step=step_index,
                deck=decks[seat],
                action=[int(index) for index in action],
                reward=rewards[seat],
                features=encoded.to_json(),
                legal_options=select["option"],
                chooser_seat=chooser_seat,
                hero_is_chooser=(seat == chooser_seat) if chooser_seat is not None else None,
                choice=choice,
                first_player=first_player,
                hero_order=("first" if seat == first_player else "second")
                if first_player in (0, 1) else None,
                turn=turn,
                own_turn_ordinal=own_turn_ordinal(turn, seat, first_player),
                observation=obs_dict
                if (feature_version >= 4 and include_observation is not False) else None,
            )
            for action_position, selected_index in enumerate(action):
                if 0 <= selected_index < len(encoded.options):
                    option = encoded.options[selected_index]
                    action_history[seat].append({
                        "context": option.context,
                        "option_type": option.option_type,
                        "source_card": option.source_card,
                        "source_serial": option.source_serial,
                        "target_card": option.target_card,
                        "target_serial": option.target_serial,
                        "attack_id": option.attack_id,
                        "numeric": result_delta
                        if action_position == len(action) - 1 else [0.0] * EVENT_NUMERIC_SIZE,
                    })


def write_decisions(records: Iterable[ReplayDecision], path: str | Path) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as handle:
        for record in records:
            handle.write(json.dumps(record.to_json(), separators=(",", ":")) + "\n")
            count += 1
    return count
