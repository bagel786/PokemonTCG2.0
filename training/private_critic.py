"""Training-only encoding of full simulator state for the centralized critic."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np


PRIVATE_CRITIC_SIZE = 256


def _bucket(path: str) -> tuple[int, float]:
    digest = hashlib.sha256(path.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % PRIVATE_CRITIC_SIZE, (1.0 if digest[4] & 1 else -1.0)


def encode_private_visualize(payload: str | list | dict) -> list[float]:
    """Hash full visualizer state into a fixed critic vector.

    The returned vector is intentionally unsuitable for the actor: it includes
    both hidden hands, decks, and prize identities.  Rollout validation rejects
    it if nested under the public actor feature object.
    """
    value = json.loads(payload) if isinstance(payload, str) else payload
    if isinstance(value, list):
        if not value:
            raise ValueError("visualize_data returned no frames")
        value = value[-1]
    vector = np.zeros(PRIVATE_CRITIC_SIZE, dtype=np.float32)

    def visit(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key in sorted(node):
                visit(node[key], f"{path}.{key}")
        elif isinstance(node, list):
            # Card-order information is intentionally retained for a stronger
            # training critic; it can never be exported to runtime.
            for index, item in enumerate(node):
                visit(item, f"{path}[{index}]")
        elif isinstance(node, bool):
            index, sign = _bucket(path)
            vector[index] += sign * float(node)
        elif isinstance(node, (int, float)) and math.isfinite(float(node)):
            index, sign = _bucket(path)
            scale = 0.01 if abs(float(node)) > 20 else 0.1
            vector[index] += sign * math.tanh(float(node) * scale)
        elif isinstance(node, str) and path.endswith((".type", ".context")):
            index, sign = _bucket(f"{path}={node}")
            vector[index] += sign

    visit(value, "root")
    norm = float(np.linalg.norm(vector))
    if norm > 20:
        vector *= 20 / norm
    return vector.tolist()
