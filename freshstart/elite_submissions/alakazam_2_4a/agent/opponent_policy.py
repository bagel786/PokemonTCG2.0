"""Shared conditional policy used only for imagined opponent rollout turns."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np

from . import policy_v2

MODEL_PATHS = (
    Path(__file__).with_name("opponent_policy_v26.npz"),
    Path("/kaggle_simulations/agent/agent/opponent_policy_v26.npz"),
)
_MODEL = None
_ATTEMPTED = False
STATS = {"loads": 0, "load_failures": 0, "inference_calls": 0,
         "inference_failures": 0, "illegal_mask_fallbacks": 0,
         "inference_s_total": 0.0}


def reset_for_tests() -> None:
    global _MODEL, _ATTEMPTED
    _MODEL = None
    _ATTEMPTED = False


def load_model():
    global _MODEL, _ATTEMPTED
    if _ATTEMPTED:
        return _MODEL
    _ATTEMPTED = True
    override = os.environ.get("OPPONENT_POLICY_PATH")
    paths = (Path(override),) if override else MODEL_PATHS
    for path in paths:
        if not path.exists():
            continue
        try:
            data = np.load(path, allow_pickle=False)
            _MODEL = {key: data[key] for key in data.files}
            _MODEL["archetype_index"] = {
                str(name): index for index, name in enumerate(_MODEL["archetype_names"].tolist())}
            STATS["loads"] += 1
            break
        except Exception:  # runtime fallback is intentional and observable
            STATS["load_failures"] += 1
    return _MODEL


def available() -> bool:
    return load_model() is not None


def _lookup(table: np.ndarray, index: int) -> np.ndarray:
    return table[index] if 0 <= index < len(table) else np.zeros(table.shape[1], dtype=np.float32)


def scores(state: dict, options: list[dict], archetype: str,
           behavior: list[float] | np.ndarray) -> list[float]:
    started = time.monotonic()
    try:
        model = load_model()
        if model is None:
            raise RuntimeError("opponent policy artifact is unavailable")
        dimension = model["card_embeddings"].shape[1]
        token_vectors = []
        for cid, zone, owner, visible, evolved, attached in policy_v2.state_tokens(state):
            token_vectors.append(
                _lookup(model["card_embeddings"], cid)
                + _lookup(model["zone_embeddings"], zone)
                + _lookup(model["owner_embeddings"], owner)
                + model["context_projection"] @ np.asarray(
                    [visible, evolved, attached], dtype=np.float32))
        state_vector = (np.mean(token_vectors, axis=0) if token_vectors
                        else np.zeros(dimension, dtype=np.float32))
        fallback = model["archetype_index"].get("mixed", 0)
        archetype_index = model["archetype_index"].get(archetype, fallback)
        state_vector = state_vector + model["archetype_embeddings"][archetype_index]
        behavior_vector = np.asarray(behavior, dtype=np.float32)
        expected = model["behavior_projection"].shape[0]
        if len(behavior_vector) != expected:
            behavior_vector = np.zeros(expected, dtype=np.float32)
        state_vector = state_vector + behavior_vector @ model["behavior_projection"]
        output = []
        for option in options:
            action = policy_v2.action_struct(state, option)
            vector = (
                _lookup(model["card_embeddings"], action["source_card"])
                + _lookup(model["card_embeddings"], action["target_card"])
                + _lookup(model["attack_embeddings"], action["attack"])
                + _lookup(model["type_embeddings"], action["action_type"])
                + _lookup(model["area_embeddings"], action["target_area"])
                + _lookup(model["target_owner_embeddings"], action["target_owner"])
            )
            output.append(float(state_vector @ vector
                                + model["action_bias"][action["action_type"]]))
        STATS["inference_calls"] += 1
        return output
    except Exception:
        STATS["inference_failures"] += 1
        raise
    finally:
        STATS["inference_s_total"] += time.monotonic() - started


def choose(state: dict, select: dict, archetype: str,
           behavior: list[float] | np.ndarray) -> list[int]:
    """Return a legal argmax selection; multi-select uses the top legal k."""
    options = select.get("option") or []
    minimum = max(int(select.get("minCount", 1)), 0)
    maximum = min(int(select.get("maxCount", minimum)), len(options))
    if not options or minimum > maximum:
        STATS["illegal_mask_fallbacks"] += 1
        raise ValueError("selection has no legal masked action")
    values = scores(state, options, archetype, behavior)
    count = minimum if minimum else min(1, maximum)
    return sorted(range(len(options)), key=lambda index: -values[index])[:count]


def metadata() -> dict:
    model = load_model()
    if model is None:
        return {"available": False}
    raw = model.get("metadata_json")
    return {"available": True, **(json.loads(str(raw.item())) if raw is not None else {})}
