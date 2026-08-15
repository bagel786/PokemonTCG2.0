"""Deterministic replay-derived fallback for neural policy failures."""

from __future__ import annotations

import json
from pathlib import Path

from .features import encode_option
from .safety import sanitize_selection


def option_keys(context: int, option) -> tuple[str, str, str]:
    number = int(round(option.numeric[0] * 20.0))
    return (
        f"{context}|{option.option_type}|{option.source_card}|{option.target_card}|{option.attack_id}|{option.area}|{number}",
        f"{context}|{option.option_type}|{option.source_card}|{option.attack_id}",
        f"{context}|{option.option_type}",
    )


class ElitePriorHeuristic:
    """Use smoothed elite selection rates, backing off to the hand-written policy."""

    def __init__(self, path: str | Path, base):
        payload = json.loads(Path(path).read_text())
        self.exact = payload.get("exact", {})
        self.middle = payload.get("middle", {})
        self.coarse = payload.get("coarse", {})
        self.counts = payload.get("counts", {})
        self.base = base

    def choose(self, obs) -> list[int]:
        context = int(obs.select.context)
        scored = []
        for index, raw in enumerate(obs.select.option):
            option = encode_option(obs, raw)
            exact, middle, coarse = option_keys(context, option)
            probability = self.exact.get(exact, self.middle.get(middle, self.coarse.get(coarse)))
            if probability is None:
                score = self.base.score(obs, raw, index)
            else:
                score = float(probability) * 1_000_000.0 + self.base.score(obs, raw, index) * 1e-4
            scored.append((score, index))
        scored.sort(key=lambda pair: (pair[0], -pair[1]), reverse=True)
        ranked = [index for _, index in scored]
        select = obs.select
        if select.minCount == select.maxCount:
            desired = select.maxCount
        else:
            key = f"{context}|{len(select.option)}|{select.minCount}|{select.maxCount}"
            desired = int(self.counts.get(key, select.minCount))
        return sanitize_selection(select, ranked, desired)
