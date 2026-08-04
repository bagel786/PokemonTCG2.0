"""Load the baked card database (submission/agent/card_db.json).

Pure Python — imports no engine code, so it runs on macOS for local testing.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

_DIR = os.path.dirname(os.path.abspath(__file__))
_DB_PATH = os.path.join(_DIR, "card_db.json")
# On Kaggle the agent runs from /kaggle_simulations/agent/
_DB_PATH_KAGGLE = "/kaggle_simulations/agent/agent/card_db.json"


@lru_cache(maxsize=1)
def _raw() -> dict:
    path = _DB_PATH if os.path.exists(_DB_PATH) else _DB_PATH_KAGGLE
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def db() -> dict[int, dict]:
    """Card ID (int) -> card record."""
    return {int(k): v for k, v in _raw().items()}


def card(card_id: int) -> dict | None:
    return db().get(int(card_id))


def name(card_id: int) -> str:
    c = card(card_id)
    return c["name"] if c else f"#{card_id}"


def is_energy(card_id: int) -> bool:
    c = card(card_id)
    return bool(c) and (c.get("category") == "Energy" or "Energy" in (c.get("stage_or_type") or ""))


def is_basic_energy(card_id: int) -> bool:
    c = card(card_id)
    return bool(c) and (c.get("stage_or_type") == "Basic Energy")


def hp(card_id: int) -> int:
    c = card(card_id)
    try:
        return int(float(c["hp"])) if c and c.get("hp") is not None else 0
    except (TypeError, ValueError):
        return 0


def moves(card_id: int) -> list[dict]:
    c = card(card_id)
    return c.get("moves", []) if c else []


def effect(card_id: int) -> str:
    """Non-move rules text for Trainer and Energy cards."""
    c = card(card_id)
    return str(c.get("effect") or "") if c else ""


def weakness(card_id: int) -> str | None:
    """Pokémon weakness type string (e.g. '{L}') or None."""
    c = card(card_id)
    return c.get("weakness") if c else None


def pokemon_type(card_id: int) -> str | None:
    """Pokémon type string (e.g. '{W}') or None."""
    c = card(card_id)
    return c.get("type") if c else None


@lru_cache(maxsize=1)
def _prev_stage_names() -> frozenset[str]:
    """Names that appear as some card's previous_stage -> i.e. they can evolve."""
    return frozenset(
        c["previous_stage"] for c in _raw().values() if c.get("previous_stage")
    )


def evolvable(card_id: int) -> bool:
    """True if this Pokémon has an evolution in the pool (e.g. Snover -> Abomasnow).
    Used to prefer benching an evolution basic over a terminal one (e.g. Kyogre)."""
    c = card(card_id)
    return bool(c) and c.get("name") in _prev_stage_names()
