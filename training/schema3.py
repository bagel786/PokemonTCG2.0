"""Behavior-preserving schema-2 to schema-3 model migration."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ptcg_ai.features import OPTION_NUMERIC_SIZE, V3_OPTION_NUMERIC_SIZE


def pad_schema3(source: str | Path, destination: str | Path) -> Path:
    """Append a zero attack-nullification input row and set schema version 3."""
    source = Path(source)
    destination = Path(destination)
    with np.load(source, allow_pickle=False) as loaded:
        arrays = {name: np.array(loaded[name], copy=True) for name in loaded.files}
    version = int(np.asarray(arrays.get("model_schema_version", 1)).item())
    if version == 3:
        if arrays["numeric_w"].shape[0] != V3_OPTION_NUMERIC_SIZE:
            raise ValueError("schema-3 model has an inconsistent numeric input shape")
    elif version == 2:
        weights = arrays["numeric_w"]
        if weights.shape[0] != OPTION_NUMERIC_SIZE:
            raise ValueError(f"expected {OPTION_NUMERIC_SIZE} schema-2 numeric rows, got {weights.shape}")
        arrays["numeric_w"] = np.concatenate(
            [weights, np.zeros((1, weights.shape[1]), dtype=weights.dtype)], axis=0
        )
        arrays["model_schema_version"] = np.asarray(3, dtype=np.int16)
    else:
        raise ValueError(f"only schema 2 can be migrated, got schema {version}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(destination, **arrays)
    return destination
