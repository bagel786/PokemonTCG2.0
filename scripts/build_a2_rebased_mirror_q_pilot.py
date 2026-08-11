#!/usr/bin/env python3
"""Build and score a narrow A2-native exact-Grim correction pilot.

The source candidates are the independently intersected complete-turn labels
that were originally certified against d842.  This script does not reuse that
baseline.  It joins each public label back to its hash-bound raw disagreement
row, keeps only the exact current Grim mirror, recomputes both bare and deployed
A2 actions, and terminal-rolls the remaining candidate against deployed A2.

Continuation policy is explicitly seat routed: deployed A2 controls the root
player and the byte-exact d842 control package controls the opponent.  A2 is
never used for both seats.  Every arm gets an independent search root with the
same explicit local-engine RNG seed; sibling states are not compared after one
arm has advanced their owning Game RNG.  Nonterminal truncation is not scored
as a draw and can never become a retained correction.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import ctypes
import gzip
import hashlib
import importlib
import json
import math
import os
import random
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

import numpy as np

from cg.api import ApiResult, to_observation_class
from cg.utils import json_to_dataclass
from scripts.build_grim_policy_disagreements import (
    LoadedPackagePolicy,
    PackageSpec,
    semantic_action,
    stable_id,
    validate_action,
)
from training.lucario_data import deterministic_gzip_text
from training.search_teacher import determinize_known_matchup


DEFAULT_CORRECTIONS = ROOT / "artifacts/grim_complete_turn_corrections/development_intersection.jsonl.gz"
DEFAULT_DISAGREEMENTS = ROOT / "artifacts/grim_policy_disagreements/disagreements.jsonl.gz"
DEFAULT_A2 = ROOT / "artifacts/recovery_probes/extracted/a2"
DEFAULT_CONTROL = ROOT / "artifacts/recovery_probes/extracted/control"
DEFAULT_ENGINE = ROOT / "artifacts/deterministic_q_engine/bin/cg.dll"
DEFAULT_PRODUCTION_ENGINE = ROOT / "vendor/cg/cg.dll"
DEFAULT_OUTPUT = ROOT / "artifacts/a2_rebased_mirror_q_pilot_seeded"

CORRECTIONS_SHA256 = "C9637C690DBE4EE5FA6DF6A96FE7FBD4DA44008666E866804C0C23D55ECF6F21"
DISAGREEMENTS_SHA256 = "C6E51038B5CA53AE3DEBC6C45F3DF4B4C3261BA5761BEFAA584877128B083558"
A2_MODEL_SHA256 = "B19871A9F1499C2460AE266E58194ACAB1D8C90B390FA5CF24ED94B9A2B6BDA8"
A2_SOURCE_TREE_SHA256 = "A25F9F0FEE304C6DE8811BB3E268D0A1BB7E5F60C961C3AAA005C590E51CEA12"
CONTROL_MODEL_SHA256 = "D842F85ABFC44AF9F41979F91795E22C92C179B62E04D5A0A2F9C734E70AF1C3"
CONTROL_SOURCE_TREE_SHA256 = "0AD83CC830ECDF618184F3D89DA0222EDB43434A43FDD41CFB0A915D320DCE19"
EXACT_GRIM_DECK_SHA256 = "C20A8A46F5C635773754F03103652F5C534B13DC622448ED2255A97234C103AF"
DETERMINISTIC_ENGINE_SHA256 = "5CBF19DBD5D75891DA50599548716A0C3530D6159C303CB2F49C8B11C706A6B7"
PRODUCTION_ENGINE_SHA256 = "EAE88634E26DC31D94150A4D8202FC9D32596B8C688EF67E14CB4088CD4D5771"

EXPECTED_COUNTS = {
    "exact_mirror_boundaries": 122,
    "pilot_candidate": 92,
    "already_adopted": 23,
    "shield_conflict_adopted": 6,
    "shield_conflict_nonadopted": 1,
}

PILOT_CANDIDATE = "pilot_candidate"
ALREADY_ADOPTED = "already_adopted"
SHIELD_CONFLICT_ADOPTED = "shield_conflict_adopted"
SHIELD_CONFLICT_NONADOPTED = "shield_conflict_nonadopted"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def read_jsonl_gz(path: str | Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl_gz(path: Path, rows: Iterable[Mapping]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with deterministic_gzip_text(path) as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def correction_key(row: Mapping) -> tuple[str, int, int, str]:
    return (
        str(row["episode_id"]),
        int(row["seat"]),
        int(row["step"]),
        str(row["candidate_semantic_id"]).upper(),
    )


def disagreement_key(row: Mapping) -> tuple[str, int, int, str]:
    return (
        str(row["episode_id"]),
        int(row["hero_seat"]),
        int(row["replay_step_t"]),
        str(row["candidate_semantic_id"]).upper(),
    )


def classify_semantics(bare: Mapping, deployed: Mapping, label: Mapping) -> str:
    bare_id, deployed_id, label_id = map(stable_id, (bare, deployed, label))
    if bare_id == deployed_id:
        return ALREADY_ADOPTED if deployed_id == label_id else PILOT_CANDIDATE
    return SHIELD_CONFLICT_ADOPTED if deployed_id == label_id else SHIELD_CONFLICT_NONADOPTED


def route_continuation(
    observation,
    root_player: int,
    hero_selector: Callable,
    opponent_selector: Callable,
):
    """Dispatch a search continuation by acting seat, never by candidate identity."""

    current = getattr(observation, "current", None)
    if current is None:
        raise ValueError("continuation observation has no current state")
    selector = hero_selector if int(current.yourIndex) == int(root_player) else opponent_selector
    return selector(observation)


def retention_decision(
    baseline_scores: Sequence[float | None],
    candidate_scores: Sequence[float | None],
    errors: Sequence[str],
    expected_worlds: int,
) -> dict:
    complete = (
        not errors
        and len(baseline_scores) == expected_worlds
        and len(candidate_scores) == expected_worlds
        and all(value is not None and math.isfinite(float(value)) for value in baseline_scores)
        and all(value is not None and math.isfinite(float(value)) for value in candidate_scores)
    )
    if not complete:
        return {
            "retained": False,
            "coverage_complete": False,
            "mean_advantage": None,
            "strict_better_worlds": 0,
            "all_worlds_nonnegative": False,
        }
    deltas = [float(candidate) - float(baseline) for baseline, candidate in zip(baseline_scores, candidate_scores)]
    strict = sum(delta > 0 for delta in deltas)
    mean = sum(deltas) / expected_worlds
    nonnegative = all(delta >= 0 for delta in deltas)
    retained = nonnegative and strict >= math.ceil(expected_worlds / 2) and mean >= 0.50
    return {
        "retained": retained,
        "coverage_complete": True,
        "mean_advantage": mean,
        "strict_better_worlds": strict,
        "all_worlds_nonnegative": nonnegative,
    }


def _package_metadata(name: str, root: Path, *, feature_provider: bool = False) -> tuple[LoadedPackagePolicy, dict]:
    policy = LoadedPackagePolicy(PackageSpec(name, root, {}), feature_provider=feature_provider)
    return policy, dict(policy.metadata)


def _verify_policy_metadata(metadata: Mapping, model_sha256: str, tree_sha256: str) -> None:
    if str(metadata.get("model_sha256", "")).upper() != model_sha256:
        raise ValueError(f"unexpected model for {metadata.get('name')}: {metadata.get('model_sha256')}")
    if str(metadata.get("source_tree_sha256", "")).upper() != tree_sha256:
        raise ValueError(f"unexpected source tree for {metadata.get('name')}: {metadata.get('source_tree_sha256')}")
    if str(metadata.get("deck_canonical_sha256", "")).upper() != EXACT_GRIM_DECK_SHA256:
        raise ValueError(f"unexpected deck for {metadata.get('name')}")


def bare_a2_action(policy: LoadedPackagePolicy, observation: Mapping) -> list[int]:
    """Execute the exact packaged A2 network before its tactical shield."""

    if policy._features_module is None or policy._api is None:  # pragma: no cover - startup invariant
        raise RuntimeError("A2 policy was not loaded as the feature provider")
    obs = policy._api.to_observation_class(dict(observation))
    model = policy._agent.policy.model
    features = policy._features_module.encode_observation(obs, model.feature_version)
    logits, count_logits, _ = model.predict(features)
    ranked = np.argsort(-np.asarray(logits), kind="stable").astype(int).tolist()
    minimum = int(obs.select.minCount)
    maximum = min(int(obs.select.maxCount), len(count_logits) - 1)
    desired = maximum if minimum == maximum else minimum + int(
        np.argmax(np.asarray(count_logits)[minimum : maximum + 1])
    )
    safety = importlib.import_module(f"{policy.alias}.safety")
    return safety.sanitize_selection(obs.select, ranked, desired)


def _input_rows(
    corrections_path: Path,
    disagreements_path: Path,
    a2_policy: LoadedPackagePolicy,
) -> tuple[list[dict], list[dict], list[dict], Counter]:
    corrections = read_jsonl_gz(corrections_path)
    wanted: dict[tuple[str, int, int, str], dict] = {}
    for row in corrections:
        key = correction_key(row)
        if key in wanted:
            raise ValueError(f"duplicate correction boundary: {key}")
        wanted[key] = row

    source: dict[tuple[str, int, int, str], dict] = {}
    with gzip.open(disagreements_path, "rt", encoding="utf-8") as handle:
        for line in handle:
            raw = json.loads(line)
            key = disagreement_key(raw)
            if key not in wanted:
                continue
            if key in source:
                raise ValueError(f"duplicate disagreement boundary: {key}")
            source[key] = raw
    missing = sorted(set(wanted) - set(source))
    if missing:
        raise ValueError(f"{len(missing)} correction boundaries did not join to raw disagreements")

    candidates: list[dict] = []
    adopted: list[dict] = []
    conflicts: list[dict] = []
    counts: Counter = Counter()
    for key in sorted(wanted):
        correction, raw = wanted[key], source[key]
        if str(raw.get("opponent_deck_canonical_sha256", "")).upper() != EXACT_GRIM_DECK_SHA256:
            continue
        if str(raw.get("opponent_matchup")) != "grimmsnarl_marnie":
            raise ValueError(f"exact Grim deck has unexpected matchup tag at {key}")
        observation = correction["observation"]
        candidate_action = validate_action(observation, correction["action"], policy_name="certified_candidate")
        bare_action = validate_action(observation, bare_a2_action(a2_policy, observation), policy_name="bare_a2")
        deployed_action = validate_action(observation, a2_policy.act(observation), policy_name="deployed_a2")
        bare_semantic = semantic_action(observation, bare_action)
        deployed_semantic = semantic_action(observation, deployed_action)
        label_semantic = semantic_action(observation, candidate_action)
        if stable_id(label_semantic) != str(correction["candidate_semantic_id"]).upper():
            raise ValueError(f"candidate semantic identity mismatch at {key}")
        category = classify_semantics(bare_semantic, deployed_semantic, label_semantic)
        counts["exact_mirror_boundaries"] += 1
        counts[category] += 1
        counts[f"{category}:{correction['actual_order']}"] += 1
        output = {
            "schema_version": 1,
            "record_type": "a2_rebased_exact_grim_terminal_q_pilot",
            "episode_id": correction["episode_id"],
            "seat": int(correction["seat"]),
            "step": int(correction["step"]),
            "actual_order": correction["actual_order"],
            "split": correction["split"],
            "features": correction["features"],
            "observation": observation,
            "observation_sha256": stable_id(observation),
            "bare_a2_action": bare_action,
            "deployed_a2_action": deployed_action,
            "candidate_action": candidate_action,
            "bare_a2_semantic_id": stable_id(bare_semantic),
            "deployed_a2_semantic_id": stable_id(deployed_semantic),
            "candidate_semantic_id": stable_id(label_semantic),
            "category": category,
            "opponent_matchup": "grimmsnarl_marnie",
            "opponent_deck": [int(value) for value in raw["opponent_deck"]],
            "opponent_deck_canonical_sha256": str(raw["opponent_deck_canonical_sha256"]).upper(),
            "proposers": sorted(map(str, correction.get("proposers") or [])),
            "source_correction_record_id": correction.get("correction_record_id"),
        }
        if category == PILOT_CANDIDATE:
            candidates.append(output)
        if category in {ALREADY_ADOPTED, SHIELD_CONFLICT_ADOPTED}:
            adopted.append(output)
        if category in {SHIELD_CONFLICT_ADOPTED, SHIELD_CONFLICT_NONADOPTED}:
            conflicts.append(output)
    return candidates, adopted, conflicts, counts


@dataclass(frozen=True)
class Rollout:
    score: float | None
    steps: int
    completed: bool
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class SeededSearchBackend:
    """Search adapter for the isolated engine's evaluation-only RNG reset."""

    def __init__(self, dll_path: str | Path):
        self.dll_path = Path(dll_path).resolve()
        self.lib = ctypes.CDLL(str(self.dll_path))
        self.lib.GameInitialize.argtypes = []
        self.lib.GameInitialize.restype = None
        self.lib.GameInitialize()
        self.lib.AgentStart.argtypes = []
        self.lib.AgentStart.restype = ctypes.c_void_p
        self.lib.SearchSetSeed.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.lib.SearchSetSeed.restype = ctypes.c_int
        self.lib.SearchBegin.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_int,
        ]
        self.lib.SearchBegin.restype = ctypes.c_char_p
        self.lib.SearchStep.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int64,
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_int,
        ]
        self.lib.SearchStep.restype = ctypes.c_char_p
        self.lib.SearchEnd.argtypes = [ctypes.c_void_p]
        self.lib.SearchEnd.restype = None
        self.lib.SearchRelease.argtypes = [ctypes.c_void_p, ctypes.c_int64]
        self.lib.SearchRelease.restype = None
        self.agent_ptr = self.lib.AgentStart()
        if not self.agent_ptr:
            raise RuntimeError("isolated seeded engine failed to create a search agent")

    @staticmethod
    def _array(values: Sequence[int]):
        normalized = [int(value) for value in values]
        return (ctypes.c_int * len(normalized))(*normalized)

    @staticmethod
    def _state(payload: bytes):
        result = json_to_dataclass(payload, ApiResult)
        if int(result.error):
            raise RuntimeError(f"seeded search engine error {int(result.error)}")
        if result.state is None:
            raise RuntimeError("seeded search engine returned no state")
        return result.state

    def reset_seed(self, seed: int) -> None:
        error = self.lib.SearchSetSeed(self.agent_ptr, ctypes.c_uint32(seed).value)
        if error:
            raise RuntimeError(f"seeded search reset failed with error {error}")

    def begin(self, observation, kwargs: Mapping[str, Sequence[int]], *, manual_coin: bool):
        serialized = observation.search_begin_input
        if serialized is None:
            raise ValueError("search observation is missing search_begin_input")
        values = {
            name: self._array(kwargs[name])
            for name in (
                "your_deck",
                "your_prize",
                "opponent_deck",
                "opponent_prize",
                "opponent_hand",
                "opponent_active",
            )
        }
        payload = self.lib.SearchBegin(
            self.agent_ptr,
            serialized.encode("ascii"),
            len(serialized),
            values["your_deck"],
            values["your_prize"],
            values["opponent_deck"],
            values["opponent_prize"],
            values["opponent_hand"],
            values["opponent_active"],
            int(manual_coin),
        )
        return self._state(payload)

    def step(self, search_id: int, selection: Sequence[int]):
        values = self._array(selection)
        payload = self.lib.SearchStep(self.agent_ptr, search_id, values, len(values))
        return self._state(payload)

    def end(self) -> None:
        self.lib.SearchEnd(self.agent_ptr)

    def release(self, search_id: int) -> None:
        self.lib.SearchRelease(self.agent_ptr, search_id)


_HERO_POLICY: LoadedPackagePolicy | None = None
_OPPONENT_POLICY: LoadedPackagePolicy | None = None
_SEARCH_BACKEND: SeededSearchBackend | None = None
_ROLLOUT_STEPS = 0
_DETERMINIZATIONS = 0
_BASE_SEED = 0


def _init_worker(
    a2_root: str,
    control_root: str,
    engine_path: str,
    rollout_steps: int,
    determinizations: int,
    base_seed: int,
) -> None:
    global _HERO_POLICY, _OPPONENT_POLICY, _SEARCH_BACKEND, _ROLLOUT_STEPS, _DETERMINIZATIONS, _BASE_SEED
    _HERO_POLICY, hero_metadata = _package_metadata("a2_worker", Path(a2_root))
    _OPPONENT_POLICY, opponent_metadata = _package_metadata("control_worker", Path(control_root))
    _verify_policy_metadata(hero_metadata, A2_MODEL_SHA256, A2_SOURCE_TREE_SHA256)
    _verify_policy_metadata(opponent_metadata, CONTROL_MODEL_SHA256, CONTROL_SOURCE_TREE_SHA256)
    if hero_metadata["model_sha256"] == opponent_metadata["model_sha256"]:
        raise ValueError("hero and opponent continuation models must be distinct")
    _SEARCH_BACKEND = SeededSearchBackend(engine_path)
    _ROLLOUT_STEPS = int(rollout_steps)
    _DETERMINIZATIONS = int(determinizations)
    _BASE_SEED = int(base_seed)


def _exact_package_action(policy: LoadedPackagePolicy, observation) -> list[int]:
    before = int(getattr(policy._agent, "errors", 0) or 0)
    action = policy.act(asdict(observation))
    after = int(getattr(policy._agent, "errors", 0) or 0)
    if after != before:
        raise RuntimeError(f"{policy.name} entered fail-closed fallback during search continuation")
    return action


def _rollout(state, root_player: int) -> Rollout:
    if _HERO_POLICY is None or _OPPONENT_POLICY is None or _SEARCH_BACKEND is None:
        raise RuntimeError("worker policies were not initialized")
    current_state = state
    steps = 0
    try:
        for steps in range(_ROLLOUT_STEPS + 1):
            current = current_state.observation.current
            if current is None:
                return Rollout(None, steps, False, "missing_current_state")
            result = int(current.result)
            if result >= 0:
                score = 0.0 if result == 2 else (1.0 if result == root_player else -1.0)
                return Rollout(score, steps, True)
            if steps >= _ROLLOUT_STEPS:
                return Rollout(None, steps, False, "nonterminal_truncation")
            if current_state.observation.select is None:
                return Rollout(None, steps, False, "missing_nonterminal_select")
            action = route_continuation(
                current_state.observation,
                root_player,
                lambda obs: _exact_package_action(_HERO_POLICY, obs),
                lambda obs: _exact_package_action(_OPPONENT_POLICY, obs),
            )
            next_state = _SEARCH_BACKEND.step(current_state.searchId, action)
            _SEARCH_BACKEND.release(current_state.searchId)
            current_state = next_state
        raise AssertionError("unreachable rollout loop exit")
    except Exception as exc:
        return Rollout(None, steps, False, f"{type(exc).__name__}: {exc}")
    finally:
        try:
            _SEARCH_BACKEND.release(current_state.searchId)
        except Exception:
            pass


def _world_seed(observation_sha256: str, world_index: int) -> int:
    material = f"a2-rebased-mirror-q-v2-seeded\0{_BASE_SEED}\0{observation_sha256.upper()}\0{world_index}"
    return int.from_bytes(hashlib.sha256(material.encode("ascii")).digest()[:8], "big")


def _score_branch(observation, kwargs: Mapping[str, Sequence[int]], action: Sequence[int], root_player: int, seed: int) -> Rollout:
    if _SEARCH_BACKEND is None:
        raise RuntimeError("worker search backend was not initialized")
    root = None
    try:
        # A fresh root is required for each arm.  Search states share the
        # owning AgentStart Game RNG, so sibling traversal is not matched CRN.
        _SEARCH_BACKEND.reset_seed(seed)
        root = _SEARCH_BACKEND.begin(observation, kwargs, manual_coin=False)
        child = _SEARCH_BACKEND.step(root.searchId, action)
        return _rollout(child, root_player)
    finally:
        if root is not None:
            try:
                _SEARCH_BACKEND.release(root.searchId)
            except Exception:
                pass
        _SEARCH_BACKEND.end()


def score_candidate(row: dict) -> dict:
    if _HERO_POLICY is None or _OPPONENT_POLICY is None or _SEARCH_BACKEND is None:
        raise RuntimeError("worker policies were not initialized")
    obs = to_observation_class(row["observation"])
    hero_deck = [int(line) for line in (_HERO_POLICY.root / "deck.csv").read_text().splitlines() if line.strip()]
    opponent_deck = [int(value) for value in row["opponent_deck"]]
    baseline_scores: list[float | None] = []
    candidate_scores: list[float | None] = []
    errors: list[str] = []
    worlds: list[dict] = []
    for world_index in range(_DETERMINIZATIONS):
        seed = _world_seed(row["observation_sha256"], world_index)
        rollout_seed = seed & 0xFFFFFFFF
        baseline = candidate = Rollout(None, 0, False, "not_evaluated")
        try:
            kwargs = determinize_known_matchup(obs, hero_deck, opponent_deck, random.Random(seed))
            root_player = int(obs.current.yourIndex)
            baseline = _score_branch(
                obs, kwargs, row["deployed_a2_action"], root_player, rollout_seed
            )
            candidate = _score_branch(
                obs, kwargs, row["candidate_action"], root_player, rollout_seed
            )
        except Exception as exc:
            errors.append(f"world_{world_index}:{type(exc).__name__}: {exc}")
        if baseline.error and baseline.error != "not_evaluated":
            errors.append(f"world_{world_index}:baseline:{baseline.error}")
        if candidate.error and candidate.error != "not_evaluated":
            errors.append(f"world_{world_index}:candidate:{candidate.error}")
        baseline_scores.append(baseline.score)
        candidate_scores.append(candidate.score)
        worlds.append({
            "world_index": world_index,
            "determinization_seed": seed,
            "rollout_seed_uint32": rollout_seed,
            "baseline": baseline.to_dict(),
            "candidate": candidate.to_dict(),
            "delta": (
                float(candidate.score) - float(baseline.score)
                if baseline.score is not None and candidate.score is not None
                else None
            ),
        })
    decision = retention_decision(baseline_scores, candidate_scores, errors, _DETERMINIZATIONS)
    scored = dict(row)
    scored["q_evaluation"] = {
        "teacher": "paired_terminal_q_exact_grim_v2_seeded",
        "baseline": "deployed_a2_shielded",
        "hero_continuation": "deployed_a2_shielded",
        "opponent_continuation": "byte_exact_d842_control",
        "candidate_never_controls_opponent": True,
        "determinizations": _DETERMINIZATIONS,
        "rollout_steps": _ROLLOUT_STEPS,
        "manual_coin": False,
        "independent_roots_per_arm": True,
        "matched_hidden_determinization": True,
        "matched_rollout_seed": True,
        "shared_mutable_rng_between_arms": False,
        "worlds": worlds,
        "errors": errors,
        **decision,
    }
    return scored


def q_evaluation_signature(row: Mapping) -> str:
    return stable_id(row["q_evaluation"])


def rejected_nondeterministic_evaluation(
    determinizations: int,
    rollout_steps: int,
    repeats: int,
) -> dict:
    """Return a fixed payload; never persist unstable native rollout values."""

    return {
        "teacher": "paired_terminal_q_exact_grim_v1",
        "status": "rejected_nondeterministic_repeats",
        "reason": "identical root worlds produced different terminal outcomes",
        "baseline": "deployed_a2_shielded",
        "hero_continuation": "deployed_a2_shielded",
        "opponent_continuation": "byte_exact_d842_control",
        "candidate_never_controls_opponent": True,
        "determinizations": int(determinizations),
        "rollout_steps": int(rollout_steps),
        "manual_coin": True,
        "determinism_repeats": int(repeats),
        "repeat_stable": False,
        "raw_rollout_values_persisted": False,
        "coverage_complete": False,
        "retained": False,
        "mean_advantage": None,
        "strict_better_worlds": 0,
        "all_worlds_nonnegative": False,
        "worlds": [],
        "errors": [],
    }


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _policy_manifest(metadata: Mapping) -> dict:
    return {
        key: metadata[key]
        for key in (
            "name",
            "model_sha256",
            "deck_sha256",
            "deck_canonical_sha256",
            "main_sha256",
            "source_tree_sha256",
        )
    }


def score_diagnostics(rows: Sequence[Mapping]) -> dict:
    totals: Counter = Counter()
    by_order: dict[str, Counter] = {}
    for row in rows:
        deltas = [world["delta"] for world in row["q_evaluation"]["worlds"]]
        finite = [float(value) for value in deltas if value is not None]
        complete = len(finite) == len(deltas)
        positive = sum(value > 0 for value in finite)
        negative = sum(value < 0 for value in finite)
        mean = sum(finite) / len(finite) if finite else math.nan
        metrics = {
            "rows": 1,
            "all_worlds_equal": int(complete and not positive and not negative),
            "any_positive_world": int(positive > 0),
            "any_negative_world": int(negative > 0),
            "all_nonnegative_with_positive": int(complete and negative == 0 and positive > 0),
            "strict_better_in_at_least_half": int(complete and positive >= math.ceil(len(deltas) / 2)),
            "mean_advantage_at_least_half": int(complete and mean >= 0.50),
        }
        totals.update(metrics)
        order = str(row["actual_order"])
        by_order.setdefault(order, Counter()).update(metrics)
    return {
        "overall": dict(sorted(totals.items())),
        "by_actual_order": {
            order: dict(sorted(values.items())) for order, values in sorted(by_order.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corrections", type=Path, default=DEFAULT_CORRECTIONS)
    parser.add_argument("--disagreements", type=Path, default=DEFAULT_DISAGREEMENTS)
    parser.add_argument("--a2-package", type=Path, default=DEFAULT_A2)
    parser.add_argument("--control-package", type=Path, default=DEFAULT_CONTROL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--production-engine", type=Path, default=DEFAULT_PRODUCTION_ENGINE)
    parser.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 1)))
    parser.add_argument("--determinizations", type=int, default=8)
    parser.add_argument("--rollout-steps", type=int, default=320)
    parser.add_argument("--seed", type=int, default=20260811)
    parser.add_argument("--max-records", type=int, default=0)
    parser.add_argument("--determinism-repeats", type=int, default=3)
    args = parser.parse_args()
    if (
        args.workers <= 0
        or args.determinizations <= 0
        or args.rollout_steps <= 0
        or args.determinism_repeats < 2
    ):
        raise ValueError(
            "workers, determinizations, and rollout-steps must be positive; "
            "determinism-repeats must be at least two"
        )
    if args.max_records < 0:
        raise ValueError("max-records cannot be negative")
    if sha256_file(args.corrections) != CORRECTIONS_SHA256:
        raise ValueError("complete-turn intersection input hash mismatch")
    if sha256_file(args.disagreements) != DISAGREEMENTS_SHA256:
        raise ValueError("raw disagreement input hash mismatch")
    if sha256_file(args.engine) != DETERMINISTIC_ENGINE_SHA256:
        raise ValueError("isolated deterministic Q engine hash mismatch")
    production_before = sha256_file(args.production_engine)
    if production_before != PRODUCTION_ENGINE_SHA256:
        raise ValueError("production engine hash mismatch before isolated Q evaluation")

    a2_policy, a2_metadata = _package_metadata("a2", args.a2_package.resolve(), feature_provider=True)
    control_policy, control_metadata = _package_metadata("control", args.control_package.resolve())
    _verify_policy_metadata(a2_metadata, A2_MODEL_SHA256, A2_SOURCE_TREE_SHA256)
    _verify_policy_metadata(control_metadata, CONTROL_MODEL_SHA256, CONTROL_SOURCE_TREE_SHA256)
    if a2_metadata["model_sha256"] == control_metadata["model_sha256"]:
        raise ValueError("candidate and opponent continuation models are unexpectedly identical")

    candidates, adopted, conflicts, counts = _input_rows(
        args.corrections.resolve(), args.disagreements.resolve(), a2_policy
    )
    for name, expected in EXPECTED_COUNTS.items():
        if int(counts[name]) != expected:
            raise ValueError(f"{name} count changed: {counts[name]}; expected {expected}")
    selected = candidates[: args.max_records] if args.max_records else candidates

    # Long native rollouts include future shuffles/random effects that are not
    # controlled by root determinization or manual coin prompts.  Audit one
    # fixed boundary repeatedly in one fresh worker before trusting any score.
    audit_rows: list[dict] = []
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=1,
        initializer=_init_worker,
        initargs=(
            str(args.a2_package.resolve()),
            str(args.control_package.resolve()),
            str(args.engine.resolve()),
            args.rollout_steps,
            args.determinizations,
            args.seed,
        ),
    ) as pool:
        for _repeat in range(args.determinism_repeats):
            audit_rows.append(pool.submit(score_candidate, selected[0]).result())
    audit_stable = len({q_evaluation_signature(row) for row in audit_rows}) == 1
    if audit_stable:
        scored = []
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=args.workers,
            initializer=_init_worker,
            initargs=(
                str(args.a2_package.resolve()),
                str(args.control_package.resolve()),
                str(args.engine.resolve()),
                args.rollout_steps,
                args.determinizations,
                args.seed,
            ),
        ) as pool:
            futures = {pool.submit(score_candidate, row): row for row in selected}
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                scored.append(future.result())
                if index % 10 == 0 or index == len(selected):
                    print(json.dumps({
                        "completed": index,
                        "selected": len(selected),
                        "retained": sum(bool(row["q_evaluation"]["retained"]) for row in scored),
                        "complete": sum(bool(row["q_evaluation"]["coverage_complete"]) for row in scored),
                    }), flush=True)
    else:
        rejected = rejected_nondeterministic_evaluation(
            args.determinizations, args.rollout_steps, args.determinism_repeats
        )
        scored = [{**row, "q_evaluation": rejected} for row in selected]
        print(json.dumps({
            "selected": len(selected),
            "terminal_q_audit": "rejected_nondeterministic_repeats",
            "certified_corrections": 0,
        }), flush=True)
    scored.sort(key=lambda row: (str(row["episode_id"]), int(row["seat"]), int(row["step"]), str(row["candidate_semantic_id"])))
    retained = [
        row for row in scored
        if audit_stable and row["q_evaluation"]["retained"]
    ]
    adopted.sort(key=lambda row: (str(row["episode_id"]), int(row["seat"]), int(row["step"]), str(row["candidate_semantic_id"])))
    conflicts.sort(key=lambda row: (str(row["episode_id"]), int(row["seat"]), int(row["step"]), str(row["candidate_semantic_id"])))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "pilot_candidates": args.output_dir / "pilot_candidates.jsonl.gz",
        "retained_corrections": args.output_dir / "retained_corrections.jsonl.gz",
        "already_adopted": args.output_dir / "already_adopted.jsonl.gz",
        "shield_conflicts": args.output_dir / "shield_conflicts.jsonl.gz",
    }
    write_jsonl_gz(outputs["pilot_candidates"], scored)
    write_jsonl_gz(outputs["retained_corrections"], retained)
    write_jsonl_gz(outputs["already_adopted"], adopted)
    write_jsonl_gz(outputs["shield_conflicts"], conflicts)
    error_counts = Counter(
        error.split(":", 2)[-1]
        for row in scored
        for error in row["q_evaluation"]["errors"]
    )
    production_after = sha256_file(args.production_engine)
    if production_after != production_before:
        raise RuntimeError("production engine changed during isolated Q evaluation")
    manifest = {
        "schema_version": 1,
        "status": (
            "complete"
            if audit_stable and not error_counts
            else "blocked_nondeterministic_terminal_q"
            if not audit_stable
            else "completed_with_rejected_errors"
        ),
        "inputs": {
            "corrections": _relative(args.corrections),
            "corrections_sha256": sha256_file(args.corrections),
            "disagreements": _relative(args.disagreements),
            "disagreements_sha256": sha256_file(args.disagreements),
        },
        "hero_policy": _policy_manifest(a2_metadata),
        "opponent_policy": _policy_manifest(control_metadata),
        "routing": {
            "root_player": "deployed_a2_shielded",
            "other_player": "byte_exact_d842_control",
            "candidate_controls_opponent": False,
        },
        "engine": {
            "path": _relative(args.engine),
            "sha256": sha256_file(args.engine),
            "entrypoint": "SearchSetSeed",
            "production_path": _relative(args.production_engine),
            "production_sha256_before": production_before,
            "production_sha256_after": production_after,
            "production_preserved": production_before == production_after,
        },
        "filter": {
            "split": "development",
            "matchup": "grimmsnarl_marnie",
            "exact_deck_canonical_sha256": EXACT_GRIM_DECK_SHA256,
            "requires_bare_and_deployed_a2_same_nonlabel_baseline": True,
        },
        "counts": {
            **dict(sorted(counts.items())),
            "scored_pilot_candidates": len(scored),
            "terminal_coverage_complete": (
                sum(bool(row["q_evaluation"]["coverage_complete"]) for row in scored)
                if audit_stable else 0
            ),
            "retained_corrections": len(retained),
            "scoring_errors": sum(len(row["q_evaluation"]["errors"]) for row in scored),
        },
        "settings": {
            "workers": args.workers,
            "determinizations": args.determinizations,
            "rollout_steps": args.rollout_steps,
            "manual_coin": False,
            "independent_roots_per_arm": True,
            "matched_hidden_determinization": True,
            "matched_rollout_seed": True,
            "seed": args.seed,
            "max_records": args.max_records,
            "determinism_repeats": args.determinism_repeats,
            "retention": "complete terminal coverage in all worlds; all deltas nonnegative; at least half positive; mean advantage >= 0.50; zero errors",
            "truncation_value": None,
        },
        "errors": dict(sorted(error_counts.items())),
        "terminal_q_audit": {
            "passed": audit_stable,
            "status": "repeat_stable" if audit_stable else "rejected_nondeterministic_repeats",
            "fixed_boundary_repeats": args.determinism_repeats,
            "identical_world_seeds": True,
            "manual_coin": False,
            "independent_roots_per_arm": True,
            "matched_rollout_seed": True,
            "raw_unstable_values_persisted": False,
            "certified_corrections": len(retained) if audit_stable else 0,
        },
        "score_diagnostics": score_diagnostics(scored) if audit_stable else None,
        "outputs": {
            name: {
                "path": _relative(path),
                "sha256": sha256_file(path),
            }
            for name, path in sorted(outputs.items())
        },
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if not error_counts else 1


if __name__ == "__main__":
    raise SystemExit(main())
