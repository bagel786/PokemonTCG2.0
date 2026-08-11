"""Strict schemas and aggregation helpers for promotion evaluations."""

from __future__ import annotations

import hashlib
import json
import math
import os
import socket
import subprocess
from pathlib import Path
from typing import Any, Mapping


BEHAVIOR_PTCG_ENV_KEYS = (
    "PTCG_DIRECTOR_ARM",
    "PTCG_DIRECTOR_HORIZON",
    "PTCG_DIRECTOR_SWAP_FALLBACK",
    "PTCG_DIRECTOR_TRIGGER",
    "PTCG_POLICY",
    "PTCG_SEARCH",
    "PTCG_TACTICAL_SHIELD",
    "PTCG_TEMP",
    "PTCG_WAVE1_RAIL",
)


class EvaluationSchemaError(ValueError):
    """Raised when an evaluation result is absent, malformed, or inconsistent."""


def sha256_file(path: str | Path) -> str:
    file_path = Path(path)
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_path(path: str | Path) -> str:
    target = Path(path)
    if target.is_file():
        return sha256_file(target)
    if not target.is_dir():
        raise FileNotFoundError(target)
    digest = hashlib.sha256()
    for child in sorted(
        item for item in target.rglob("*")
        if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc"
    ):
        relative = child.relative_to(target).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(child)))
    return digest.hexdigest()


def source_commit(root: Path) -> str:
    explicit = os.environ.get("PTCG_SOURCE_COMMIT", "").strip()
    if explicit:
        return explicit
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def model_schema(path: str | Path | None) -> int | None:
    if not path:
        return None
    import numpy as np

    with np.load(path, allow_pickle=False) as arrays:
        if "model_schema_version" not in arrays.files:
            return 1
        return int(np.asarray(arrays["model_schema_version"]).item())


def submission_schema(path: Path | None) -> int | str | None:
    if path is None:
        return None
    standard = path / "policy_weights.npz"
    if standard.exists():
        return model_schema(standard)
    named = sorted(item.name for item in path.rglob("*.npz") if "policy_v" in item.name)
    return "external:" + ",".join(named) if named else "external:nonstandard"


def runtime_environment(
    submission_env_a: Mapping[str, Any] | None = None,
    submission_env_b: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, str]]:
    """Capture process policy controls and exact per-submission overrides."""
    return {
        "process_ptcg": {
            key: os.environ[key]
            for key in BEHAVIOR_PTCG_ENV_KEYS
            if key in os.environ
        },
        "submission_a_overrides": {
            str(key): str(value) for key, value in sorted((submission_env_a or {}).items())
        },
        "submission_b_overrides": {
            str(key): str(value) for key, value in sorted((submission_env_b or {}).items())
        },
    }


def build_provenance(
    *,
    root: Path,
    deck_a: str | Path,
    model_a: str | Path | None,
    deck_b: str | Path,
    model_b: str | Path | None,
    submission_a: str | Path | None,
    submission_b: str | Path | None,
    engine_path: str | Path,
    seed: int,
    submission_env_a: Mapping[str, Any] | None = None,
    submission_env_b: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    submission_a_path = Path(submission_a) if submission_a else None
    submission_b_path = Path(submission_b) if submission_b else None
    return {
        "source_commit": source_commit(root),
        "source_bundle_sha256": os.environ.get("PTCG_SOURCE_BUNDLE_SHA256", "").strip(),
        "worker": socket.gethostname(),
        "seed": int(seed),
        "deck_a_sha256": sha256_file(deck_a),
        "model_a_sha256": sha256_file(model_a) if model_a else None,
        "model_a_schema": model_schema(model_a),
        "deck_b_sha256": sha256_file(deck_b),
        "model_b_sha256": sha256_file(model_b) if model_b else None,
        "model_b_schema": model_schema(model_b),
        "submission_a": str(submission_a_path.resolve()) if submission_a_path else None,
        "submission_a_sha256": sha256_path(submission_a_path) if submission_a_path else None,
        "submission_b": str(submission_b_path.resolve()) if submission_b_path else None,
        "submission_b_sha256": sha256_path(submission_b_path) if submission_b_path else None,
        "artifact_a_sha256": sha256_path(submission_a_path) if submission_a_path else sha256_file(model_a) if model_a else "heuristic",
        "artifact_b_sha256": sha256_path(submission_b_path) if submission_b_path else sha256_file(model_b) if model_b else "heuristic",
        "artifact_a_schema": submission_schema(submission_a_path) if submission_a_path else model_schema(model_a) if model_a else "heuristic",
        "artifact_b_schema": submission_schema(submission_b_path) if submission_b_path else model_schema(model_b) if model_b else "heuristic",
        "engine_binary": Path(engine_path).name,
        "engine_sha256": sha256_file(engine_path),
        "runtime_environment": runtime_environment(submission_env_a, submission_env_b),
    }


def _required(mapping: Mapping[str, Any], key: str, expected_type: type | tuple[type, ...]) -> Any:
    if key not in mapping:
        raise EvaluationSchemaError(f"missing required field: {key}")
    value = mapping[key]
    if not isinstance(value, expected_type) or isinstance(value, bool):
        raise EvaluationSchemaError(f"field {key!r} has invalid type: {type(value).__name__}")
    return value


def validate_evaluation_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Return a normalized result or raise; never synthesize missing metrics."""
    if not isinstance(result, Mapping):
        raise EvaluationSchemaError("evaluation result must be an object")
    games = int(_required(result, "games", int))
    wins = int(_required(result, "wins_a", int))
    win_rate = float(_required(result, "win_rate_a", (int, float)))
    if games <= 0 or not 0 <= wins <= games:
        raise EvaluationSchemaError(f"invalid record: {wins}/{games}")
    if not math.isclose(win_rate, wins / games, abs_tol=1e-12):
        raise EvaluationSchemaError("win_rate_a is inconsistent with wins_a/games")

    interval = _required(result, "wilson_95", list)
    if len(interval) != 2 or not all(isinstance(x, (int, float)) for x in interval):
        raise EvaluationSchemaError("wilson_95 must contain two numeric bounds")
    if not 0 <= float(interval[0]) <= win_rate <= float(interval[1]) <= 1:
        raise EvaluationSchemaError("wilson_95 does not contain win_rate_a")
    overall = _required(result, "overall", Mapping)
    if (
        _required(overall, "games", int) != games
        or _required(overall, "wins", int) != wins
        or not math.isclose(float(_required(overall, "win_rate", (int, float))), win_rate, abs_tol=1e-12)
        or list(_required(overall, "wilson_95", list)) != list(interval)
    ):
        raise EvaluationSchemaError("nested overall metrics are inconsistent")

    hero_errors = int(_required(result, "hero_policy_errors", int))
    opponent_errors = int(_required(result, "opponent_policy_errors", int))
    if hero_errors < 0 or opponent_errors < 0:
        raise EvaluationSchemaError("policy error counts cannot be negative")
    elapsed = float(_required(result, "elapsed_seconds", (int, float)))
    decisions = int(_required(result, "decisions", int))
    if elapsed <= 0 or decisions <= 0:
        raise EvaluationSchemaError("runtime and decision totals must be positive")

    seats = _required(result, "seat_results_a", Mapping)
    normalized_seats: dict[str, dict[str, Any]] = {}
    for seat in ("0", "1"):
        row = _required(seats, seat, Mapping)
        seat_games = int(_required(row, "games", int))
        seat_wins = int(_required(row, "wins", int))
        seat_rate = float(_required(row, "win_rate", (int, float)))
        if seat_games <= 0 or not 0 <= seat_wins <= seat_games:
            raise EvaluationSchemaError(f"invalid seat {seat} record")
        if not math.isclose(seat_rate, seat_wins / seat_games, abs_tol=1e-12):
            raise EvaluationSchemaError(f"seat {seat} win rate is inconsistent")
        normalized_seats[seat] = {"games": seat_games, "wins": seat_wins, "win_rate": seat_rate}
    if sum(row["games"] for row in normalized_seats.values()) != games:
        raise EvaluationSchemaError("seat game totals do not equal games")
    if sum(row["wins"] for row in normalized_seats.values()) != wins:
        raise EvaluationSchemaError("seat win totals do not equal wins_a")

    opponents = _required(result, "opponent_results_a", Mapping)
    if len(opponents) != 1:
        raise EvaluationSchemaError("a shard must contain exactly one named opponent metric")
    opponent_name, opponent = next(iter(opponents.items()))
    if not opponent_name or not isinstance(opponent, Mapping):
        raise EvaluationSchemaError("opponent metric has no stable name")
    if (
        _required(opponent, "games", int) != games
        or _required(opponent, "wins", int) != wins
        or not math.isclose(float(_required(opponent, "win_rate", (int, float))), win_rate, abs_tol=1e-12)
    ):
        raise EvaluationSchemaError("opponent metrics are inconsistent")

    rng = _required(result, "rng_provenance", Mapping)
    if rng.get("paired_deals") is not False or rng.get("engine") != "unpaired_std_random_device":
        raise EvaluationSchemaError("engine RNG must be explicitly recorded as independent/unpaired")
    provenance = _required(result, "artifact_provenance", Mapping)
    for key in (
        "source_commit",
        "source_bundle_sha256",
        "worker",
        "seed",
        "deck_a_sha256",
        "deck_b_sha256",
        "engine_binary",
        "engine_sha256",
        "runtime_environment",
        "artifact_a_sha256",
        "artifact_b_sha256",
        "artifact_a_schema",
        "artifact_b_schema",
    ):
        if key not in provenance or provenance[key] in (None, ""):
            raise EvaluationSchemaError(f"missing artifact provenance: {key}")
    if provenance["source_commit"] == "unknown":
        raise EvaluationSchemaError("source commit is unknown")
    runtime = _required(provenance, "runtime_environment", Mapping)
    for key in ("process_ptcg", "submission_a_overrides", "submission_b_overrides"):
        value = _required(runtime, key, Mapping)
        if not all(isinstance(name, str) and isinstance(setting, str) for name, setting in value.items()):
            raise EvaluationSchemaError(f"runtime environment {key!r} must contain string pairs")

    normalized = dict(result)
    normalized["games"] = games
    normalized["wins_a"] = wins
    normalized["win_rate_a"] = win_rate
    normalized["hero_policy_errors"] = hero_errors
    normalized["opponent_policy_errors"] = opponent_errors
    normalized["seat_results_a"] = normalized_seats
    return normalized


def load_evaluation(path: str | Path) -> dict[str, Any]:
    return validate_evaluation_result(json.loads(Path(path).read_text(encoding="utf-8")))
