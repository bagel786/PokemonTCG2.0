"""Kaggle replay parsing with correct observation/action alignment."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from cg.api import to_observation_class

from .features import encode_observation


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


def iter_decisions(
    episode: dict,
    allowed_teams: set[str] | None = None,
    feature_version: int = 2,
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

    for step_index in range(len(steps) - 1):
        current = steps[step_index]
        following = steps[step_index + 1]
        for seat in range(min(len(current), len(following), 2)):
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
            yield ReplayDecision(
                episode_id=episode_id,
                team=team,
                seat=seat,
                step=step_index,
                deck=decks[seat],
                action=[int(index) for index in action],
                reward=rewards[seat],
                features=encode_observation(obs, feature_version).to_json(),
            )


def write_decisions(records: Iterable[ReplayDecision], path: str | Path) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as handle:
        for record in records:
            handle.write(json.dumps(record.to_json(), separators=(",", ":")) + "\n")
            count += 1
    return count
