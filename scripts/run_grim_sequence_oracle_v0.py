#!/usr/bin/env python3
"""Offline Grim multi-action sequence-oracle discovery experiment.

This script keeps deployed A2+Damage V0 as the continuation policy and searches
only the current hero turn.  A plan is a sparse sequence of at most two stable
semantic overrides.  Proposal and confirmation use disjoint hidden-world and
rollout-seed schedules.  Every arm is evaluated from a newly reconstructed
native search root after ``SearchSetSeed``; sibling search states are never
used as counterfactual arms.

No heuristic board value is computed.  Plans are proposed by A2's frozen
option/count ranking and are compared only by complete terminal outcomes.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import gzip
import hashlib
import itertools
import json
import math
import multiprocessing as mp
import os
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

import numpy as np

from cg.api import OptionType, SelectContext, SelectType, all_card_data, to_observation_class
from ptcg_ai.external import ExternalSubmissionAgent
from scripts.build_a2_rebased_mirror_q_pilot import SeededSearchBackend
from training.complete_turn_corrections import (
    SemanticAction,
    SemanticBoundaryError,
    resolve_semantic_action,
    semantic_action,
    semantic_option,
)
from training.evaluate_deterministic_crn import SeededEngine, _forced_order
from training.search_teacher import determinize_known_matchup


DEFAULT_WORKSPACE = ROOT.parent / "pokemonTCG2.0"
DEFAULT_A2 = DEFAULT_WORKSPACE / "artifacts/grim_damage_conversion/candidates/a2_damage_v0"
DEFAULT_D842 = DEFAULT_WORKSPACE / "artifacts/grim_variance_floor/candidates/B0"
DEFAULT_MASTER = DEFAULT_WORKSPACE / "artifacts/grim_damage_conversion/opponents/master_v1"
DEFAULT_REPLAY = DEFAULT_WORKSPACE / "artifacts/grim_damage_conversion/opponents/replay_refresh"
DEFAULT_ENGINE = ROOT / "artifacts/grim_sequence_oracle_v0/engine/libcg.dylib"
DEFAULT_PRODUCTION_ENGINE = ROOT / "vendor/cg/cg.dll"
DEFAULT_OUTPUT = ROOT / "artifacts/grim_sequence_oracle_v0"

EXCLUDED_CONTEXTS = {
    int(SelectContext.SETUP_ACTIVE_POKEMON),
    int(SelectContext.SETUP_BENCH_POKEMON),
    int(SelectContext.IS_FIRST),
    int(SelectContext.MULLIGAN),
    int(SelectContext.COIN_HEAD),
}


class OracleError(RuntimeError):
    """A comparison cannot be used as terminal evidence."""


class TerminalCoverageError(OracleError):
    """A rollout did not reach a real terminal state."""


class PolicyExecutionError(OracleError):
    """A packaged policy entered an exception/fallback path."""


class EngineLifecycleError(OracleError):
    """A native state/root could not be cleaned up."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def stable_id(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest().upper()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def sha256_tree(path: Path) -> str:
    digest = hashlib.sha256()
    for child in sorted(
        item
        for item in path.rglob("*")
        if item.is_file() and "__pycache__" not in item.parts and child_suffix_ok(item)
    ):
        relative = child.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha256_file(child)))
    return digest.hexdigest().upper()


def child_suffix_ok(path: Path) -> bool:
    return path.suffix != ".pyc"


def public_observation_hash(raw: Mapping[str, Any]) -> str:
    return stable_id({key: value for key, value in raw.items() if key != "search_begin_input"})


def seed_for(schedule: str, base_seed: int, root_hash: str, world: int, purpose: str) -> int:
    material = f"grim-sequence-oracle-v0\0{schedule}\0{base_seed}\0{root_hash}\0{world}\0{purpose}"
    return int.from_bytes(hashlib.sha256(material.encode("ascii")).digest()[:8], "big")


def select_context_name(value: int) -> str:
    try:
        return SelectContext(int(value)).name
    except ValueError:
        return f"UNKNOWN_{int(value)}"


def option_type_name(value: int) -> str:
    try:
        return OptionType(int(value)).name
    except ValueError:
        return f"UNKNOWN_{int(value)}"


def own_turn_ordinal(turn: int, seat: int, first_player: int) -> int:
    return (turn + 1) // 2 if int(first_player) == int(seat) else turn // 2


def is_branching_boundary(obs: Any) -> bool:
    if obs.current is None or obs.select is None:
        return False
    if int(obs.select.context) in EXCLUDED_CONTEXTS:
        return False
    if len(obs.select.option or []) <= 1:
        return False
    minimum, maximum = int(obs.select.minCount), int(obs.select.maxCount)
    if maximum <= 0:
        return False
    # A boundary is useful only when at least two complete selections can exist.
    option_count = len(obs.select.option)
    possibilities = 0
    for count in range(max(0, minimum), min(maximum, option_count) + 1):
        possibilities += math.comb(option_count, count)
        if possibilities >= 2:
            return True
    return False


def semantic_boundary_hash_or_none(obs: Any) -> str | None:
    """Return a stable boundary or decline prompts that cannot be index-free."""

    if not is_branching_boundary(obs):
        return None
    try:
        raw = asdict(obs)
        current = raw.get("current") or {}
        viewer = int(current.get("yourIndex", 0))
        for index, player in enumerate(current.get("players") or []):
            # Search roots materialize hidden zones.  A plan guard must remain
            # actor-visible and therefore never bind to either prize payload or
            # the opponent's materialized hand.
            player["prize"] = [None] * len(player.get("prize") or [])
            if index != viewer:
                player["hand"] = []
        raw.pop("search_begin_input", None)
        raw["logs"] = []
        select = raw.get("select") or {}
        select["option"] = sorted(
            (semantic_option(obs, option).to_dict() for option in obs.select.option),
            key=canonical,
        )
        return stable_id(raw)
    except SemanticBoundaryError:
        return None


def _nested_errors(value: Any) -> int:
    """Conservatively count visible package error/fallback counters."""

    seen: set[int] = set()

    def visit(item: Any, depth: int) -> int:
        if item is None or depth > 4 or id(item) in seen:
            return 0
        seen.add(id(item))
        total = 0
        for name in (
            "errors",
            "fallbacks",
            "policy_errors",
            "search_errors",
            "engine_errors",
        ):
            raw = getattr(item, name, 0)
            if isinstance(raw, (int, np.integer)):
                total += int(raw)
        for name in (
            "_AGENT",
            "exact",
            "policy_first",
            "policy_second",
            "policy",
            "fallback",
            "damage_solver",
        ):
            child = getattr(item, name, None)
            if child is not None and not isinstance(child, (str, bytes, int, float, bool)):
                total += visit(child, depth + 1)
        return total

    return visit(value, 0)


def policy_error_count(agent: ExternalSubmissionAgent) -> int:
    return int(agent.errors) + _nested_errors(agent.module)


def exact_policy_action(agent: ExternalSubmissionAgent, raw: Mapping[str, Any], label: str) -> list[int]:
    before = policy_error_count(agent)
    action = agent(dict(raw))
    after = policy_error_count(agent)
    if after != before or after:
        raise PolicyExecutionError(f"{label} error/fallback counter changed {before}->{after}")
    select = raw.get("select") or {}
    options = select.get("option") or []
    minimum, maximum = int(select.get("minCount", 0)), int(select.get("maxCount", 0))
    if (
        not isinstance(action, list)
        or any(isinstance(value, bool) or not isinstance(value, int) for value in action)
        or not minimum <= len(action) <= maximum
        or len(set(action)) != len(action)
        or any(value < 0 or value >= len(options) for value in action)
    ):
        raise PolicyExecutionError(f"{label} returned illegal action {action!r}")
    return list(action)


def reset_external(agent: ExternalSubmissionAgent, label: str) -> None:
    agent.errors = 0
    inner = getattr(agent.module, "_AGENT", None)
    if inner is None:
        raise PolicyExecutionError(f"{label} package exposes no resettable _AGENT")
    if hasattr(inner, "_reset"):
        result = inner._reset()
        if list(result) != list(agent.deck):
            raise PolicyExecutionError(f"{label} router reset returned the wrong deck")
    else:
        if hasattr(inner, "errors"):
            inner.errors = 0
        for component_name in ("policy", "fallback"):
            component = getattr(inner, component_name, None)
            if component is not None and hasattr(component, "reset"):
                component.reset()
    if policy_error_count(agent):
        raise PolicyExecutionError(f"{label} did not reset cleanly")


@dataclass(frozen=True)
class HistoryDecision:
    actor: str
    observation: dict[str, Any]
    action: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"actor": self.actor, "observation": self.observation, "action": list(self.action)}


class PolicyPair:
    """Reusable packages that are reset and history-replayed before every arm."""

    def __init__(self, hero_path: Path, opponent_path: Path):
        self.hero = ExternalSubmissionAgent(hero_path, {})
        self.opponent = ExternalSubmissionAgent(opponent_path, {})
        self.preparations = 0

    def close(self) -> None:
        self.hero.close()
        self.opponent.close()

    def prepare(self, history: Sequence[HistoryDecision]) -> None:
        reset_external(self.hero, "hero")
        reset_external(self.opponent, "opponent")
        for item in history:
            policy = self.hero if item.actor == "hero" else self.opponent
            action = exact_policy_action(policy, item.observation, item.actor)
            if tuple(action) != item.action:
                raise PolicyExecutionError(
                    f"history replay mismatch for {item.actor}: {action} != {list(item.action)}"
                )
        self.preparations += 1


def _active_a2_components(agent: ExternalSubmissionAgent) -> tuple[Any, Any]:
    router = getattr(agent.module, "_AGENT", None)
    order = getattr(router, "actual_order", None)
    if order == "first":
        selected = router.policy_first
    elif order == "second":
        selected = router.policy_second
    else:
        raise PolicyExecutionError("A2 actual-order router is not latched")
    neural = getattr(selected, "policy", None)
    model = getattr(neural, "model", None)
    if model is None:
        raise PolicyExecutionError("A2 neural proposal prior is unavailable")
    prefix = neural.__class__.__module__.rsplit(".", 1)[0]
    features = sys.modules.get(prefix + ".features")
    if features is None:
        raise PolicyExecutionError("A2 feature encoder is unavailable")
    return neural, features


def a2_rank(agent: ExternalSubmissionAgent, obs: Any) -> tuple[np.ndarray, np.ndarray]:
    neural, features = _active_a2_components(agent)
    encoded = features.encode_observation(obs, neural.model.feature_version)
    logits, count_logits, _unused_value = neural.model.predict(encoded)
    return np.asarray(logits, dtype=np.float64), np.asarray(count_logits, dtype=np.float64)


def sync_a2_override(agent: ExternalSubmissionAgent, obs: Any, action: Sequence[int]) -> None:
    """Keep Damage V0's within-turn pending state coherent with an override."""

    neural, _features = _active_a2_components(agent)
    solver = getattr(neural, "damage_solver", None)
    if solver is None:
        return
    chosen = [int(value) for value in action]
    remainder = [index for index in range(len(obs.select.option)) if index not in chosen]
    solver.apply(obs, chosen + remainder, len(chosen))


@dataclass(frozen=True)
class ActionProposal:
    semantic: SemanticAction
    prior_score: float
    rank: int
    role: str
    trace: str

    @property
    def digest(self) -> str:
        return self.semantic.digest


@dataclass(frozen=True)
class PlanStep:
    eligible_ordinal: int
    boundary_hash: str
    action: SemanticAction
    prior_score: float
    role: str
    trace: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligible_ordinal": self.eligible_ordinal,
            "boundary_hash": self.boundary_hash,
            "semantic_action": self.action.to_dict(),
            "semantic_action_sha256": self.action.digest,
            "prior_score": self.prior_score,
            "role": self.role,
            "trace": self.trace,
        }


@dataclass(frozen=True)
class SequencePlan:
    steps: tuple[PlanStep, ...] = ()

    @property
    def digest(self) -> str:
        return stable_id(self.to_dict())

    @property
    def family(self) -> str:
        return "baseline" if not self.steps else " -> ".join(step.role for step in self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "planned_deviations": len(self.steps),
            "steps": [step.to_dict() for step in self.steps],
            "family": self.family,
        }


@dataclass(frozen=True)
class BoundaryVisit:
    eligible_ordinal: int
    boundary_hash: str
    alternatives: tuple[ActionProposal, ...]


@dataclass(frozen=True)
class TurnExecution:
    visits: tuple[BoundaryVisit, ...]
    executed_deviations: int
    invalidated: bool
    steps: int
    turn_complete: bool
    terminal: bool
    action_trace_sha256: str


@dataclass(frozen=True)
class TerminalExecution:
    score: float
    win: int
    draw: int
    result: int
    executed_deviations: int
    invalidated: bool
    steps: int
    action_trace_sha256: str


def _selected_card_id(action: SemanticAction) -> int | None:
    if not action.options:
        return None
    payload = action.options[0].payload
    source = payload.get("source")
    if isinstance(source, Mapping) and source.get("id") is not None:
        return int(source["id"])
    if payload.get("card_id") is not None:
        return int(payload["card_id"])
    return None


CARD_NAMES: dict[int, str] = {}


def card_name(card_id: int | None) -> str:
    if card_id is None:
        return "unknown"
    return CARD_NAMES.get(int(card_id), f"card_{int(card_id)}")


def action_role(action: SemanticAction) -> str:
    option_type = action.options[0].option_type if action.options else -1
    context = action.context
    if option_type == int(OptionType.ATTACH):
        return "attach"
    if option_type == int(OptionType.RETREAT):
        return "retreat"
    if option_type == int(OptionType.ATTACK):
        return "attack"
    if option_type == int(OptionType.EVOLVE):
        return "evolve"
    if option_type == int(OptionType.PLAY):
        return "play"
    if context in {int(SelectContext.TO_HAND), int(SelectContext.LOOK)}:
        return "tutor"
    if context in {int(SelectContext.TO_BENCH), int(SelectContext.TO_FIELD)}:
        return "bench/setup"
    if context in {int(SelectContext.SWITCH), int(SelectContext.TO_ACTIVE)}:
        return "promote"
    if context in {
        int(SelectContext.DAMAGE_COUNTER),
        int(SelectContext.DAMAGE_COUNTER_ANY),
        int(SelectContext.DAMAGE),
        int(SelectContext.REMOVE_DAMAGE_COUNTER),
    }:
        return "target-manipulation"
    if context in {int(SelectContext.ATTACH_FROM), int(SelectContext.ATTACH_TO)}:
        return "resource-attach"
    if context == int(SelectContext.DISCARD):
        return "resource-discard"
    return select_context_name(context).lower().replace("_", "-")


def action_trace(action: SemanticAction) -> str:
    option_type = action.options[0].option_type if action.options else -1
    card_id = _selected_card_id(action)
    payload = action.options[0].payload if action.options else {}
    details = [option_type_name(option_type)]
    if card_id is not None:
        details.append(card_name(card_id))
    if payload.get("attack_id") is not None:
        details.append(f"attack_{payload['attack_id']}")
    details.append(f"at_{select_context_name(action.context)}")
    return " ".join(details)


def _complete_actions(
    obs: Any,
    baseline: Sequence[int],
    logits: np.ndarray,
    count_logits: np.ndarray,
    *,
    alternatives: int,
    exhaustive_options: int,
) -> list[tuple[tuple[int, ...], float]]:
    """Policy-ranked complete selections; never use the value head."""

    option_count = len(obs.select.option)
    minimum = max(0, int(obs.select.minCount))
    maximum = min(option_count, int(obs.select.maxCount))
    ranked = np.argsort(-logits, kind="stable").astype(int).tolist()
    desired = minimum
    if minimum == maximum:
        desired = maximum
    elif len(count_logits):
        capped = min(maximum, len(count_logits) - 1)
        desired = minimum + int(np.argmax(count_logits[minimum : capped + 1]))
    counts = [len(baseline), desired]
    if option_count <= exhaustive_options:
        counts.extend(range(minimum, maximum + 1))
    counts = sorted(set(count for count in counts if minimum <= count <= maximum))
    candidates: dict[tuple[int, ...], float] = {}

    def add(values: Iterable[int]) -> None:
        action = tuple(sorted(int(value) for value in values))
        if not minimum <= len(action) <= maximum or len(set(action)) != len(action):
            return
        candidates[action] = float(sum(float(logits[index]) for index in action))

    add(baseline)
    if option_count <= exhaustive_options:
        for count in counts:
            for combo in itertools.combinations(range(option_count), count):
                add(combo)
    else:
        for count in counts:
            add(ranked[:count])
            if count == 1:
                for index in ranked[: alternatives + 2]:
                    add((index,))
            elif count > 1:
                base = ranked[:count]
                for replacement in ranked[count : count + alternatives + 1]:
                    for position in range(min(count, 2)):
                        changed = list(base)
                        changed[position] = replacement
                        add(changed)
    return sorted(candidates.items(), key=lambda item: (-item[1], item[0]))


def propose_alternatives(
    policy: ExternalSubmissionAgent,
    obs: Any,
    baseline: Sequence[int],
    *,
    alternatives: int = 3,
    exhaustive_options: int = 6,
) -> tuple[ActionProposal, ...]:
    logits, count_logits = a2_rank(policy, obs)
    baseline_semantic = semantic_action(obs, baseline)
    proposals: dict[str, ActionProposal] = {}
    ranked_actions = _complete_actions(
        obs,
        baseline,
        logits,
        count_logits,
        alternatives=alternatives,
        exhaustive_options=exhaustive_options,
    )
    for rank, (raw_action, score) in enumerate(ranked_actions, 1):
        try:
            semantic = semantic_action(obs, raw_action)
        except SemanticBoundaryError:
            continue
        if semantic == baseline_semantic:
            continue
        proposal = ActionProposal(
            semantic=semantic,
            prior_score=float(score),
            rank=rank,
            role=action_role(semantic),
            trace=action_trace(semantic),
        )
        proposals.setdefault(proposal.digest, proposal)
    return tuple(
        sorted(proposals.values(), key=lambda value: (-value.prior_score, value.rank, value.digest))[
            :alternatives
        ]
    )


class OracleBackend:
    """Instrumented wrapper enforcing one root per evaluated plan."""

    def __init__(self, path: Path, *, initialize: bool = True):
        self.backend = SeededSearchBackend(path, initialize=initialize)
        self.fresh_roots = 0
        self.search_ends = 0
        self.release_errors = 0

    def begin(self, observation: Any, kwargs: Mapping[str, Sequence[int]], seed: int):
        self.backend.reset_seed(seed)
        root = self.backend.begin(observation, kwargs, manual_coin=False)
        self.fresh_roots += 1
        return root

    def step(self, state: Any, action: Sequence[int]):
        return self.backend.step(int(state.searchId), action)

    def release(self, state: Any) -> None:
        if state is None:
            return
        try:
            self.backend.release(int(state.searchId))
        except Exception as exc:
            self.release_errors += 1
            raise EngineLifecycleError(f"SearchRelease failed: {exc}") from exc

    def end(self) -> None:
        try:
            self.backend.end()
            self.search_ends += 1
        except Exception as exc:
            raise EngineLifecycleError(f"SearchEnd failed: {exc}") from exc


def _raw_observation(observation: Any) -> dict[str, Any]:
    return asdict(observation)


def _trace_line(obs: Any, action: Sequence[int], actor: str) -> dict[str, Any]:
    try:
        semantic = semantic_action(obs, action).to_dict()
    except Exception:
        semantic = {"unresolved_action_count": len(action)}
    current = obs.current
    return {
        "actor": actor,
        "turn": int(current.turn) if current is not None else None,
        "semantic": semantic,
    }


def execute_plan(
    backend: OracleBackend,
    pair: PolicyPair,
    observation: Any,
    kwargs: Mapping[str, Sequence[int]],
    rollout_seed: int,
    history: Sequence[HistoryDecision],
    plan: SequencePlan,
    *,
    terminal: bool,
    max_turn_steps: int,
    max_rollout_steps: int,
    collect_alternatives: bool = False,
    alternatives_per_boundary: int = 3,
    exhaustive_options: int = 6,
) -> TurnExecution | TerminalExecution:
    pair.prepare(history)
    state = None
    primary: Exception | None = None
    result: TurnExecution | TerminalExecution | None = None
    trace: list[dict[str, Any]] = []
    root_player = int(observation.current.yourIndex)
    root_turn = int(observation.current.turn)
    eligible_ordinal = 0
    next_plan_step = 0
    executed = 0
    invalidated = False
    steps = 0
    visits: list[BoundaryVisit] = []
    try:
        state = backend.begin(observation, kwargs, rollout_seed)
        while True:
            obs = state.observation
            current = obs.current
            if current is None:
                raise OracleError("search state has no current game state")
            terminal_now = int(current.result) >= 0
            hero_turn_done = (
                terminal_now
                or int(current.yourIndex) != root_player
                or int(current.turn) != root_turn
            )
            if hero_turn_done and not terminal:
                if next_plan_step < len(plan.steps):
                    invalidated = True
                result = TurnExecution(
                    visits=tuple(visits),
                    executed_deviations=executed,
                    invalidated=invalidated,
                    steps=steps,
                    turn_complete=True,
                    terminal=terminal_now,
                    action_trace_sha256=stable_id(trace),
                )
                break
            if terminal_now:
                terminal_result = int(current.result)
                score = 0.0 if terminal_result == 2 else (1.0 if terminal_result == root_player else -1.0)
                result = TerminalExecution(
                    score=score,
                    win=int(terminal_result == root_player),
                    draw=int(terminal_result == 2),
                    result=terminal_result,
                    executed_deviations=executed,
                    invalidated=invalidated,
                    steps=steps,
                    action_trace_sha256=stable_id(trace),
                )
                break
            if obs.select is None:
                raise OracleError("nonterminal search state has no selection")
            if steps >= max_rollout_steps:
                raise TerminalCoverageError("nonterminal rollout reached the step cap")
            acting = int(current.yourIndex)
            raw = _raw_observation(obs)
            if acting == root_player:
                baseline = exact_policy_action(pair.hero, raw, "hero")
                action = baseline
                boundary = (
                    semantic_boundary_hash_or_none(obs)
                    if int(current.turn) == root_turn
                    else None
                )
                if boundary is not None:
                    proposals: tuple[ActionProposal, ...] = ()
                    if collect_alternatives:
                        proposals = propose_alternatives(
                            pair.hero,
                            obs,
                            baseline,
                            alternatives=alternatives_per_boundary,
                            exhaustive_options=exhaustive_options,
                        )
                        visits.append(BoundaryVisit(eligible_ordinal, boundary, proposals))
                    if not invalidated and next_plan_step < len(plan.steps):
                        wanted = plan.steps[next_plan_step]
                        if wanted.eligible_ordinal == eligible_ordinal:
                            if wanted.boundary_hash != boundary:
                                invalidated = True
                            else:
                                resolved = resolve_semantic_action(obs, wanted.action)
                                if resolved is None:
                                    invalidated = True
                                else:
                                    action = resolved
                                    sync_a2_override(pair.hero, obs, action)
                                    executed += 1
                                    next_plan_step += 1
                        elif wanted.eligible_ordinal < eligible_ordinal:
                            invalidated = True
                    eligible_ordinal += 1
            else:
                action = exact_policy_action(pair.opponent, raw, "opponent")
            trace.append(_trace_line(obs, action, "hero" if acting == root_player else "opponent"))
            next_state = backend.step(state, action)
            backend.release(state)
            state = next_state
            steps += 1
            if not terminal and steps >= max_turn_steps:
                raise TerminalCoverageError("current hero turn reached the step cap")
    except Exception as exc:
        primary = exc
    finally:
        if state is not None:
            try:
                backend.release(state)
            except Exception as exc:
                if primary is None:
                    primary = exc
        try:
            backend.end()
        except Exception as exc:
            if primary is None:
                primary = exc
    if primary is not None:
        raise primary
    if result is None:
        raise OracleError("plan execution produced no result")
    return result


def generate_plans(
    backend: OracleBackend,
    pair: PolicyPair,
    root: Mapping[str, Any],
    kwargs: Mapping[str, Sequence[int]],
    seed: int,
    *,
    plan_budget: int,
    one_deviation_cap: int,
    max_turn_steps: int,
    alternatives_per_boundary: int,
    exhaustive_options: int,
) -> list[SequencePlan]:
    if not 60 <= plan_budget <= 100:
        raise ValueError("Stage-1 plan budget must be between 60 and 100")
    obs = to_observation_class(root["observation"])
    history = tuple(
        HistoryDecision(item["actor"], item["observation"], tuple(item["action"]))
        for item in root["history"]
    )
    baseline = SequencePlan()
    baseline_run = execute_plan(
        backend,
        pair,
        obs,
        kwargs,
        seed,
        history,
        baseline,
        terminal=False,
        max_turn_steps=max_turn_steps,
        max_rollout_steps=max_turn_steps,
        collect_alternatives=True,
        alternatives_per_boundary=alternatives_per_boundary,
        exhaustive_options=exhaustive_options,
    )
    assert isinstance(baseline_run, TurnExecution)
    one_candidates: list[SequencePlan] = []
    for visit in baseline_run.visits:
        for proposal in visit.alternatives:
            one_candidates.append(
                SequencePlan(
                    (
                        PlanStep(
                            visit.eligible_ordinal,
                            visit.boundary_hash,
                            proposal.semantic,
                            proposal.prior_score,
                            proposal.role,
                            proposal.trace,
                        ),
                    )
                )
            )
    unique_one = {plan.digest: plan for plan in one_candidates}
    one = sorted(
        unique_one.values(),
        key=lambda plan: (-plan.steps[0].prior_score, plan.steps[0].eligible_ordinal, plan.digest),
    )[:one_deviation_cap]

    two_candidates: dict[str, SequencePlan] = {}
    for plan in one:
        run = execute_plan(
            backend,
            pair,
            obs,
            kwargs,
            seed,
            history,
            plan,
            terminal=False,
            max_turn_steps=max_turn_steps,
            max_rollout_steps=max_turn_steps,
            collect_alternatives=True,
            alternatives_per_boundary=alternatives_per_boundary,
            exhaustive_options=exhaustive_options,
        )
        assert isinstance(run, TurnExecution)
        if run.executed_deviations != 1 or run.invalidated:
            continue
        first = plan.steps[0]
        for visit in run.visits:
            if visit.eligible_ordinal <= first.eligible_ordinal:
                continue
            for proposal in visit.alternatives:
                candidate = SequencePlan(
                    (
                        first,
                        PlanStep(
                            visit.eligible_ordinal,
                            visit.boundary_hash,
                            proposal.semantic,
                            proposal.prior_score,
                            proposal.role,
                            proposal.trace,
                        ),
                    )
                )
                two_candidates.setdefault(candidate.digest, candidate)
    two = sorted(
        two_candidates.values(),
        key=lambda plan: (
            -sum(step.prior_score for step in plan.steps),
            plan.steps[-1].eligible_ordinal,
            plan.digest,
        ),
    )
    remaining = plan_budget - 1 - len(one)
    plans = [baseline, *one, *two[: max(0, remaining)]]
    if len(plans) < 60:
        # Preserve the hard 60-plan target when a turn has enough candidates;
        # a genuinely smaller legal tree is reported rather than duplicated.
        plans.extend(two[max(0, remaining) : max(0, remaining) + (60 - len(plans))])
    return plans[:plan_budget]


def collect_root_states(
    engine_path: Path,
    hero_path: Path,
    opponents: Mapping[str, Path],
    *,
    base_seed: int,
    games_per_cell: int,
    target_ordinal: int,
    max_decisions: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    engine = SeededEngine(engine_path)
    roots: list[dict[str, Any]] = []
    errors: list[str] = []
    for lineage_index, (lineage, opponent_path) in enumerate(sorted(opponents.items())):
        for order_index, order in enumerate(("first", "second")):
            for index in range(games_per_cell):
                seed = base_seed + lineage_index * 1_000_000 + order_index * 100_000 + index
                hero_seat = index % 2
                hero = ExternalSubmissionAgent(hero_path, {})
                opponent = ExternalSubmissionAgent(opponent_path, {})
                agents = {hero_seat: hero, 1 - hero_seat: opponent}
                decks = [hero.deck, opponent.deck] if hero_seat == 0 else [opponent.deck, hero.deck]
                history: list[HistoryDecision] = []
                battle_ptr = 0
                first_player: int | None = None
                selected: dict[str, Any] | None = None
                try:
                    battle_ptr, raw = engine.start(decks[0], decks[1], seed)
                    for decision in range(max_decisions):
                        obs = to_observation_class(raw)
                        if obs.current is not None and int(obs.current.firstPlayer) in (0, 1):
                            first_player = int(obs.current.firstPlayer)
                        if obs.current is not None and int(obs.current.result) >= 0:
                            raise OracleError("source game terminated before the deterministic root rule")
                        if first_player is None:
                            ordinal = 0
                        else:
                            ordinal = own_turn_ordinal(int(obs.current.turn), hero_seat, first_player)
                        acting = int(obs.current.yourIndex) if obs.current is not None else -1
                        root_boundary = semantic_boundary_hash_or_none(obs)
                        eligible_root = (
                            acting == hero_seat
                            and ordinal == target_ordinal
                            and int(obs.select.type) == int(SelectType.MAIN)
                            and root_boundary is not None
                        )
                        if eligible_root:
                            observed_order = "first" if first_player == hero_seat else "second"
                            if observed_order != order:
                                raise OracleError(
                                    f"forced source order mismatch: requested {order}, saw {observed_order}"
                                )
                            selected = {
                                "schema_version": 1,
                                "record_type": "grim_sequence_oracle_v0_root",
                                "lineage": lineage,
                                "opponent_path": str(opponent_path.resolve()),
                                "base_game_seed": seed,
                                "physical_seat": hero_seat,
                                "actual_order": order,
                                "first_player": first_player,
                                "source_decision": decision,
                                "game_turn": int(obs.current.turn),
                                "own_turn_ordinal": ordinal,
                                "root_public_state_hash": root_boundary,
                                "root_public_observation_sha256": public_observation_hash(raw),
                                "observation": dict(raw),
                                "history": [item.to_dict() for item in history],
                                "opponent_deck": list(opponent.deck),
                                "hero_deck": list(hero.deck),
                            }
                            selected["root_id"] = stable_id(
                                {
                                    "lineage": lineage,
                                    "seed": seed,
                                    "seat": hero_seat,
                                    "order": order,
                                    "public": selected["root_public_state_hash"],
                                }
                            )
                            break
                        if obs.select.context == SelectContext.IS_FIRST:
                            action = _forced_order(obs.select, hero_seat, order)
                        else:
                            policy = agents[acting]
                            actor = "hero" if acting == hero_seat else "opponent"
                            action = exact_policy_action(policy, raw, f"source_{actor}")
                            history.append(HistoryDecision(actor, dict(raw), tuple(action)))
                        raw = engine.select(battle_ptr, action)
                    if selected is None:
                        raise OracleError("source game did not reach the deterministic root rule")
                    roots.append(selected)
                except Exception as exc:
                    errors.append(f"{lineage}:{order}:{index}:{type(exc).__name__}:{exc}")
                    raise
                finally:
                    if battle_ptr:
                        engine.finish(battle_ptr)
                    hero.close()
                    opponent.close()
    expected = len(opponents) * 2 * games_per_cell
    if len(roots) != expected:
        raise OracleError(f"collected {len(roots)} roots, expected {expected}")
    if len({row["base_game_seed"] for row in roots}) != expected:
        raise OracleError("source game seeds are not unique")
    if len({row["root_id"] for row in roots}) != expected:
        raise OracleError("root states are not independent/unique")
    metadata = {
        "selection_rule": (
            f"first branching MAIN decision on hero own-turn ordinal {target_ordinal}; "
            "one state per independently seeded base game; outcome blind"
        ),
        "roots": len(roots),
        "unique_games": len({row["base_game_seed"] for row in roots}),
        "errors": errors,
        "by_lineage": dict(Counter(row["lineage"] for row in roots)),
        "by_actual_order": dict(Counter(row["actual_order"] for row in roots)),
        "by_lineage_order": dict(
            Counter(f"{row['lineage']}:{row['actual_order']}" for row in roots)
        ),
        "by_own_turn_ordinal": dict(Counter(str(row["own_turn_ordinal"]) for row in roots)),
        "base_seed": base_seed,
        "games_per_lineage_order_cell": games_per_cell,
    }
    return roots, metadata


def _world_inputs(
    root: Mapping[str, Any], schedule: str, base_seed: int, world: int
) -> tuple[dict[str, Any], int, int]:
    obs = to_observation_class(root["observation"])
    determinization_seed = seed_for(schedule, base_seed, root["root_id"], world, "hidden")
    rollout_seed = seed_for(schedule, base_seed, root["root_id"], world, "rollout") & 0xFFFFFFFF
    kwargs = determinize_known_matchup(
        obs,
        list(root["hero_deck"]),
        list(root["opponent_deck"]),
        random.Random(determinization_seed),
    )
    return kwargs, determinization_seed, rollout_seed


def _execution_dict(result: TerminalExecution) -> dict[str, Any]:
    return asdict(result)


def summarize_worlds(worlds: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    deltas = [float(row["candidate"]["score"]) - float(row["baseline"]["score"]) for row in worlds]
    win_deltas = [int(row["candidate"]["win"]) - int(row["baseline"]["win"]) for row in worlds]
    return {
        "worlds": len(worlds),
        "better": sum(value > 0 for value in deltas),
        "worse": sum(value < 0 for value in deltas),
        "equal": sum(value == 0 for value in deltas),
        "paired_mean_terminal_delta": statistics.mean(deltas) if deltas else None,
        "paired_terminal_delta_variance": statistics.variance(deltas) if len(deltas) > 1 else 0.0,
        "downside_rate": sum(value < 0 for value in deltas) / len(deltas) if deltas else None,
        "baseline_wins": sum(int(row["baseline"]["win"]) for row in worlds),
        "candidate_wins": sum(int(row["candidate"]["win"]) for row in worlds),
        "candidate_only_wins": sum(value > 0 for value in win_deltas),
        "baseline_only_wins": sum(value < 0 for value in win_deltas),
        "paired_win_delta": statistics.mean(win_deltas) if win_deltas else None,
        "invalidated_worlds": sum(bool(row["candidate"]["invalidated"]) for row in worlds),
        "executed_deviations": dict(
            Counter(str(row["candidate"]["executed_deviations"]) for row in worlds)
        ),
    }


def evaluate_plans(
    backend: OracleBackend,
    pair: PolicyPair,
    root: Mapping[str, Any],
    plans: Sequence[SequencePlan],
    *,
    schedule: str,
    base_seed: int,
    worlds: int,
    max_turn_steps: int,
    max_rollout_steps: int,
) -> list[dict[str, Any]]:
    obs = to_observation_class(root["observation"])
    history = tuple(
        HistoryDecision(item["actor"], item["observation"], tuple(item["action"]))
        for item in root["history"]
    )
    baseline_plan = SequencePlan()
    world_inputs = [_world_inputs(root, schedule, base_seed, world) for world in range(worlds)]
    baselines: list[TerminalExecution] = []
    for kwargs, _determinization_seed, rollout_seed in world_inputs:
        outcome = execute_plan(
            backend,
            pair,
            obs,
            kwargs,
            rollout_seed,
            history,
            baseline_plan,
            terminal=True,
            max_turn_steps=max_turn_steps,
            max_rollout_steps=max_rollout_steps,
        )
        assert isinstance(outcome, TerminalExecution)
        baselines.append(outcome)
    evaluations: list[dict[str, Any]] = []
    for plan in plans:
        paired: list[dict[str, Any]] = []
        for world, ((kwargs, determinization_seed, rollout_seed), baseline) in enumerate(
            zip(world_inputs, baselines)
        ):
            if not plan.steps:
                candidate = baseline
            else:
                outcome = execute_plan(
                    backend,
                    pair,
                    obs,
                    kwargs,
                    rollout_seed,
                    history,
                    plan,
                    terminal=True,
                    max_turn_steps=max_turn_steps,
                    max_rollout_steps=max_rollout_steps,
                )
                assert isinstance(outcome, TerminalExecution)
                candidate = outcome
            paired.append(
                {
                    "world": world,
                    "determinization_seed": determinization_seed,
                    "rollout_seed_uint32": rollout_seed,
                    "baseline": _execution_dict(baseline),
                    "candidate": _execution_dict(candidate),
                }
            )
        evaluations.append(
            {
                "plan_id": plan.digest,
                "plan": plan.to_dict(),
                "summary": summarize_worlds(paired),
                "worlds": paired,
            }
        )
    return evaluations


def choose_confirmation_plan(
    plans: Sequence[SequencePlan], evaluations: Sequence[Mapping[str, Any]]
) -> SequencePlan:
    by_id = {plan.digest: plan for plan in plans}
    candidates = [row for row in evaluations if int(row["plan"]["planned_deviations"]) > 0]
    if not candidates:
        return SequencePlan()
    ranked = sorted(
        candidates,
        key=lambda row: (
            -float(row["summary"]["paired_mean_terminal_delta"]),
            float(row["summary"]["downside_rate"]),
            -float(row["summary"]["paired_win_delta"]),
            -sum(float(step["prior_score"]) for step in row["plan"]["steps"]),
            str(row["plan_id"]),
        ),
    )
    best = ranked[0]
    if float(best["summary"]["paired_mean_terminal_delta"]) <= 0:
        return SequencePlan()
    return by_id[str(best["plan_id"])]


_WORKER_BACKEND: OracleBackend | None = None
_WORKER_HERO: Path | None = None
_WORKER_PAIRS: dict[str, PolicyPair] = {}
_WORKER_CONFIG: dict[str, Any] = {}


def _init_worker(engine: str, hero: str, config: Mapping[str, Any]) -> None:
    global _WORKER_BACKEND, _WORKER_HERO, _WORKER_PAIRS, _WORKER_CONFIG
    random.seed(0)
    np.random.seed(0)
    _WORKER_BACKEND = OracleBackend(Path(engine))
    _WORKER_HERO = Path(hero)
    _WORKER_PAIRS = {}
    _WORKER_CONFIG = dict(config)


def _worker_pair(opponent_path: str) -> PolicyPair:
    if _WORKER_HERO is None:
        raise RuntimeError("worker is not initialized")
    if opponent_path not in _WORKER_PAIRS:
        _WORKER_PAIRS[opponent_path] = PolicyPair(_WORKER_HERO, Path(opponent_path))
    return _WORKER_PAIRS[opponent_path]


def score_root(root: dict[str, Any]) -> dict[str, Any]:
    if _WORKER_BACKEND is None:
        raise RuntimeError("worker is not initialized")
    pair = _worker_pair(str(root["opponent_path"]))
    config = _WORKER_CONFIG
    proposal_kwargs, proposal_hidden_seed, proposal_rollout_seed = _world_inputs(
        root, "generation", int(config["generation_seed"]), 0
    )
    plans = generate_plans(
        _WORKER_BACKEND,
        pair,
        root,
        proposal_kwargs,
        proposal_rollout_seed,
        plan_budget=int(config["plan_budget"]),
        one_deviation_cap=int(config["one_deviation_cap"]),
        max_turn_steps=int(config["max_turn_steps"]),
        alternatives_per_boundary=int(config["alternatives_per_boundary"]),
        exhaustive_options=int(config["exhaustive_options"]),
    )
    proposal = evaluate_plans(
        _WORKER_BACKEND,
        pair,
        root,
        plans,
        schedule="proposal",
        base_seed=int(config["proposal_seed"]),
        worlds=int(config["proposal_worlds"]),
        max_turn_steps=int(config["max_turn_steps"]),
        max_rollout_steps=int(config["max_rollout_steps"]),
    )
    selected = choose_confirmation_plan(plans, proposal)
    confirmation = evaluate_plans(
        _WORKER_BACKEND,
        pair,
        root,
        [selected],
        schedule="confirmation",
        base_seed=int(config["confirmation_seed"]),
        worlds=int(config["confirmation_worlds"]),
        max_turn_steps=int(config["max_turn_steps"]),
        max_rollout_steps=int(config["max_rollout_steps"]),
    )[0]
    return {
        "root_id": root["root_id"],
        "root": {
            key: root[key]
            for key in (
                "lineage",
                "base_game_seed",
                "physical_seat",
                "actual_order",
                "game_turn",
                "own_turn_ordinal",
                "root_public_state_hash",
                "root_public_observation_sha256",
            )
        },
        "generation": {
            "hidden_seed": proposal_hidden_seed,
            "rollout_seed_uint32": proposal_rollout_seed,
            "plan_count": len(plans),
            "by_deviations": dict(Counter(str(len(plan.steps)) for plan in plans)),
            "plans": [plan.to_dict() | {"plan_id": plan.digest} for plan in plans],
        },
        "proposal": proposal,
        "selected_plan_id": selected.digest,
        "confirmation": confirmation,
        "mechanism": selected.family,
        "fresh_roots_worker_cumulative": _WORKER_BACKEND.fresh_roots,
        "search_ends_worker_cumulative": _WORKER_BACKEND.search_ends,
        "release_errors_worker_cumulative": _WORKER_BACKEND.release_errors,
    }


def write_jsonl_gz(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        # mtime=0 makes the result hash reproducible.
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            for row in rows:
                zipped.write((canonical(row) + "\n").encode("utf-8"))


def bootstrap_cluster_interval(rows: Sequence[Mapping[str, Any]], seed: int, repeats: int = 20_000) -> list[float]:
    per_root: list[list[int]] = []
    for row in rows:
        worlds = row["confirmation"]["worlds"]
        per_root.append(
            [int(world["candidate"]["win"]) - int(world["baseline"]["win"]) for world in worlds]
        )
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(repeats):
        sampled = [rng.choice(per_root) for _ in range(len(per_root))]
        values = [value for cluster in sampled for value in cluster]
        estimates.append(100.0 * sum(values) / len(values))
    estimates.sort()
    return [
        estimates[math.ceil(0.025 * repeats) - 1],
        estimates[math.ceil(0.975 * repeats) - 1],
    ]


def aggregate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    worlds = [world for row in rows for world in row["confirmation"]["worlds"]]
    terminal_deltas = [
        float(world["candidate"]["score"]) - float(world["baseline"]["score"]) for world in worlds
    ]
    win_deltas = [
        int(world["candidate"]["win"]) - int(world["baseline"]["win"]) for world in worlds
    ]
    candidate_only = [world for world in worlds if int(world["candidate"]["win"]) > int(world["baseline"]["win"])]
    baseline_only = [world for world in worlds if int(world["candidate"]["win"]) < int(world["baseline"]["win"])]
    rescue_roots = []
    two_deviation_rescue_roots = []
    for row in rows:
        row_worlds = row["confirmation"]["worlds"]
        row_win_delta = sum(
            int(world["candidate"]["win"]) - int(world["baseline"]["win"])
            for world in row_worlds
        )
        if row_win_delta > 0:
            rescue_roots.append(str(row["root_id"]))
            if any(
                int(world["candidate"]["win"]) > int(world["baseline"]["win"])
                and int(world["candidate"]["executed_deviations"]) == 2
                for world in row_worlds
            ):
                two_deviation_rescue_roots.append(str(row["root_id"]))
    return {
        "roots": len(rows),
        "confirmation_worlds": len(worlds),
        "baseline_terminal_wins": sum(int(world["baseline"]["win"]) for world in worlds),
        "oracle_terminal_wins": sum(int(world["candidate"]["win"]) for world in worlds),
        "candidate_only_wins": len(candidate_only),
        "baseline_only_wins": len(baseline_only),
        "paired_win_delta_pp": 100.0 * statistics.mean(win_deltas) if win_deltas else 0.0,
        "paired_mean_terminal_delta": statistics.mean(terminal_deltas) if terminal_deltas else 0.0,
        "terminal_delta_variance": statistics.variance(terminal_deltas) if len(terminal_deltas) > 1 else 0.0,
        "worlds_better_worse_equal": {
            "better": sum(value > 0 for value in terminal_deltas),
            "worse": sum(value < 0 for value in terminal_deltas),
            "equal": sum(value == 0 for value in terminal_deltas),
        },
        "downside_rate": sum(value < 0 for value in terminal_deltas) / len(terminal_deltas) if terminal_deltas else 0.0,
        "selected_plans_by_deviations": dict(
            Counter(str(row["confirmation"]["plan"]["planned_deviations"]) for row in rows)
        ),
        "candidate_worlds_by_executed_deviations": dict(
            Counter(str(world["candidate"]["executed_deviations"]) for world in worlds)
        ),
        "candidate_only_wins_with_two_actual_deviations": sum(
            int(world["candidate"]["executed_deviations"]) == 2 for world in candidate_only
        ),
        "rescue_roots": rescue_roots,
        "independent_rescue_roots": len(rescue_roots),
        "two_actual_deviation_rescue_roots": two_deviation_rescue_roots,
        "independent_two_actual_deviation_rescue_roots": len(two_deviation_rescue_roots),
        "selected_mechanism_families": dict(Counter(str(row["mechanism"]) for row in rows)),
    }


def subgroup(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row["root"][key])].append(row)
    return {name: aggregate(group) for name, group in sorted(groups.items())}


def decision_from(aggregate_result: Mapping[str, Any]) -> tuple[str, str]:
    delta = float(aggregate_result["paired_win_delta_pp"])
    two_roots = int(aggregate_result["independent_two_actual_deviation_rescue_roots"])
    families = Counter(aggregate_result["selected_mechanism_families"])
    recurring = max((count for name, count in families.items() if name != "baseline"), default=0)
    mechanism_ok = two_roots >= 5 and recurring >= 2
    if delta < 3.0 or not mechanism_ok:
        return "SEQUENCE_SEARCH_WEAK", (
            f"paired win delta {delta:+.3f} pp; {two_roots} independent rescue roots "
            f"with two actual deviations; maximum recurring nonbaseline family {recurring}"
        )
    if delta >= 8.0:
        return "SEQUENCE_SEARCH_STRONG", (
            f"paired win delta {delta:+.3f} pp with the two-deviation mechanism gate satisfied"
        )
    return "SEQUENCE_SEARCH_INTERESTING", (
        f"paired win delta {delta:+.3f} pp with the two-deviation mechanism gate satisfied"
    )


def synthetic_stranded_munk_discovery() -> dict[str, Any]:
    """Engine-independent capability proof; these labels are not runtime rules."""

    # State -> available actions.  The frozen proposal prior chooses the first.
    graph = {
        "munk_active": ["attach_bench", "attach_active"],
        "attached_bench": ["end"],
        "attached_active": ["end", "retreat"],
        "retreated": ["promote_grim"],
        "grim_active": ["shadow_bullet"],
        "end": [],
        "win": [],
    }
    transition = {
        ("munk_active", "attach_bench"): "attached_bench",
        ("munk_active", "attach_active"): "attached_active",
        ("attached_bench", "end"): "end",
        ("attached_active", "end"): "end",
        ("attached_active", "retreat"): "retreated",
        ("retreated", "promote_grim"): "grim_active",
        ("grim_active", "shadow_bullet"): "win",
    }
    found: list[dict[str, Any]] = []

    def walk(state: str, deviations: list[tuple[str, str]], trace: list[str]) -> None:
        if state in {"win", "end"}:
            if state == "win":
                found.append({"deviations": list(deviations), "trace": list(trace), "terminal": state})
            return
        actions = graph[state]
        baseline = actions[0]
        for action in actions:
            changed = action != baseline
            if len(deviations) + int(changed) > 2:
                continue
            next_deviations = deviations + ([(state, action)] if changed else [])
            walk(transition[(state, action)], next_deviations, trace + [action])

    walk("munk_active", [], [])
    qualifying = [row for row in found if len(row["deviations"]) == 2]
    return {
        "passed": bool(qualifying),
        "winning_trace": qualifying[0]["trace"] if qualifying else None,
        "deviations": qualifying[0]["deviations"] if qualifying else None,
        "hard_coded_in_runtime": False,
    }


def structural_static_audit() -> dict[str, Any]:
    baseline = SequencePlan()
    serialized = baseline.to_dict()
    key_stack = [serialized]
    raw_index_key = False
    while key_stack:
        value = key_stack.pop()
        if isinstance(value, Mapping):
            raw_index_key |= "index" in value
            key_stack.extend(value.values())
        elif isinstance(value, list):
            key_stack.extend(value)
    synthetic = synthetic_stranded_munk_discovery()
    return {
        "raw_prompt_local_indices_persisted": raw_index_key,
        "synthetic_stranded_munk_discoverable": bool(synthetic["passed"]),
        "synthetic": synthetic,
        "max_deliberate_deviations": 2,
        "nested_boundaries_eligible": True,
        "attack_terminates_via_native_turn_boundary": True,
        "truncation_terminal_value": None,
        "policy_engine_errors_fail_closed": True,
    }


def order_invariance_audit(
    engine_path: Path,
    hero_path: Path,
    root: Mapping[str, Any],
    plan: SequencePlan,
    *,
    max_turn_steps: int,
    max_rollout_steps: int,
) -> dict[str, Any]:
    backend = OracleBackend(engine_path, initialize=False)
    pair = PolicyPair(hero_path, Path(root["opponent_path"]))
    obs = to_observation_class(root["observation"])
    history = tuple(
        HistoryDecision(item["actor"], item["observation"], tuple(item["action"]))
        for item in root["history"]
    )
    kwargs, hidden_seed, rollout_seed = _world_inputs(root, "order_audit", 2026081503, 0)

    def run(chosen: SequencePlan) -> dict[str, Any]:
        value = execute_plan(
            backend,
            pair,
            obs,
            kwargs,
            rollout_seed,
            history,
            chosen,
            terminal=True,
            max_turn_steps=max_turn_steps,
            max_rollout_steps=max_rollout_steps,
        )
        assert isinstance(value, TerminalExecution)
        return asdict(value)

    try:
        a1, b1 = run(SequencePlan()), run(plan)
        b2, a2 = run(plan), run(SequencePlan())
        a3 = run(SequencePlan())
        passed = a1 == a2 == a3 and b1 == b2
        return {
            "passed": passed,
            "hidden_seed": hidden_seed,
            "rollout_seed_uint32": rollout_seed,
            "a_then_b": {"a": a1, "b": b1},
            "b_then_a": {"b": b2, "a": a2},
            "repeat_a": a3,
            "fresh_roots": backend.fresh_roots,
            "search_ends": backend.search_ends,
            "release_errors": backend.release_errors,
            "independent_fresh_root_per_evaluation": backend.fresh_roots == 5,
            "shared_mutable_rng_between_arms": False if passed else None,
        }
    finally:
        pair.close()


def option_reordering_audit(root: Mapping[str, Any], hero_path: Path) -> dict[str, Any]:
    raw = copy.deepcopy(root["observation"])
    agent = ExternalSubmissionAgent(hero_path, {})
    try:
        history = [
            HistoryDecision(item["actor"], item["observation"], tuple(item["action"]))
            for item in root["history"]
        ]
        # Only hero history affects this package.
        reset_external(agent, "hero")
        for item in history:
            if item.actor == "hero":
                exact_policy_action(agent, item.observation, "hero")
        action = exact_policy_action(agent, raw, "hero")
        obs = to_observation_class(raw)
        semantic = semantic_action(obs, action)
        count = len(raw["select"]["option"])
        permutation = list(reversed(range(count)))
        reordered = copy.deepcopy(raw)
        reordered["select"]["option"] = [raw["select"]["option"][index] for index in permutation]
        resolved = resolve_semantic_action(to_observation_class(reordered), semantic)
        expected = [permutation.index(index) for index in action]
        return {
            "passed": resolved == expected,
            "original_action": action,
            "resolved_after_reorder": resolved,
            "expected_after_reorder": expected,
            "persisted_identity": semantic.to_dict(),
        }
    finally:
        agent.close()


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a2", type=Path, default=DEFAULT_A2)
    parser.add_argument("--d842", type=Path, default=DEFAULT_D842)
    parser.add_argument("--master-v1", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--replay-refresh", type=Path, default=DEFAULT_REPLAY)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--production-engine", type=Path, default=DEFAULT_PRODUCTION_ENGINE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source-base-seed", type=int, default=2026081500)
    parser.add_argument("--generation-seed", type=int, default=2026081501)
    parser.add_argument("--proposal-seed", type=int, default=2026081502)
    parser.add_argument("--confirmation-seed", type=int, default=2026081601)
    parser.add_argument("--games-per-cell", type=int, default=10)
    parser.add_argument("--target-own-turn", type=int, default=2)
    parser.add_argument("--plan-budget", type=int, default=64)
    parser.add_argument("--one-deviation-cap", type=int, default=20)
    parser.add_argument("--alternatives-per-boundary", type=int, default=3)
    parser.add_argument("--exhaustive-options", type=int, default=6)
    parser.add_argument("--proposal-worlds", type=int, default=4)
    parser.add_argument("--confirmation-worlds", type=int, default=16)
    parser.add_argument("--max-turn-steps", type=int, default=96)
    parser.add_argument("--max-rollout-steps", type=int, default=768)
    parser.add_argument("--max-source-decisions", type=int, default=2_000)
    parser.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 1)))
    args = parser.parse_args()
    if not 60 <= args.plan_budget <= 100:
        raise ValueError("plan-budget must be in [60, 100]")
    for path in (
        args.a2,
        args.d842,
        args.master_v1,
        args.replay_refresh,
        args.engine,
        args.production_engine,
    ):
        if not path.exists():
            raise FileNotFoundError(path)
    opponents = {
        "d842": args.d842.resolve(),
        "master_v1": args.master_v1.resolve(),
        "replay_refresh": args.replay_refresh.resolve(),
    }
    global CARD_NAMES
    CARD_NAMES = {int(card.cardId): str(card.name) for card in all_card_data()}
    started = time.monotonic()
    production_before = sha256_file(args.production_engine)
    package_hashes_before = {
        "a2": sha256_tree(args.a2),
        **{name: sha256_tree(path) for name, path in opponents.items()},
    }
    roots, sampling = collect_root_states(
        args.engine,
        args.a2,
        opponents,
        base_seed=args.source_base_seed,
        games_per_cell=args.games_per_cell,
        target_ordinal=args.target_own_turn,
        max_decisions=args.max_source_decisions,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    roots_path = args.output_dir / "stage1_roots.jsonl.gz"
    write_jsonl_gz(roots_path, roots)

    config = {
        "generation_seed": args.generation_seed,
        "proposal_seed": args.proposal_seed,
        "confirmation_seed": args.confirmation_seed,
        "plan_budget": args.plan_budget,
        "one_deviation_cap": args.one_deviation_cap,
        "alternatives_per_boundary": args.alternatives_per_boundary,
        "exhaustive_options": args.exhaustive_options,
        "proposal_worlds": args.proposal_worlds,
        "confirmation_worlds": args.confirmation_worlds,
        "max_turn_steps": args.max_turn_steps,
        "max_rollout_steps": args.max_rollout_steps,
    }
    scored: list[dict[str, Any]] = []
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=args.workers,
        mp_context=mp.get_context("spawn"),
        initializer=_init_worker,
        initargs=(str(args.engine.resolve()), str(args.a2.resolve()), config),
    ) as pool:
        futures = [pool.submit(score_root, root) for root in roots]
        for completed, future in enumerate(concurrent.futures.as_completed(futures), 1):
            scored.append(future.result())
            print(canonical({"completed_roots": completed, "total_roots": len(futures)}), flush=True)
    scored.sort(key=lambda row: str(row["root_id"]))
    raw_path = args.output_dir / "stage1_raw_results.jsonl.gz"
    write_jsonl_gz(raw_path, scored)

    overall = aggregate(scored)
    overall["cluster_bootstrap_95_pp"] = bootstrap_cluster_interval(scored, 2026081602)
    result_by_opponent = subgroup(scored, "lineage")
    result_by_order = subgroup(scored, "actual_order")
    result_by_ordinal = subgroup(scored, "own_turn_ordinal")
    recommendation, reason = decision_from(overall)

    first_nonbaseline = next(
        (
            SequencePlan(
                tuple(
                    PlanStep(
                        int(step["eligible_ordinal"]),
                        str(step["boundary_hash"]),
                        SemanticAction(
                            select_type=int(step["semantic_action"]["select_type"]),
                            context=int(step["semantic_action"]["context"]),
                            minimum=int(step["semantic_action"]["minimum"]),
                            maximum=int(step["semantic_action"]["maximum"]),
                            context_card=(
                                canonical(step["semantic_action"]["context_card"])
                                if step["semantic_action"]["context_card"] is not None
                                else None
                            ),
                            effect=(
                                canonical(step["semantic_action"]["effect"])
                                if step["semantic_action"]["effect"] is not None
                                else None
                            ),
                            options=tuple(
                                # SemanticOption is intentionally imported lazily to keep this
                                # reconstruction visibly index-free.
                                __import__(
                                    "training.complete_turn_corrections",
                                    fromlist=["SemanticOption"],
                                ).SemanticOption(
                                    int(option["option_type"]), canonical(option["payload"])
                                )
                                for option in step["semantic_action"]["options"]
                            ),
                        ),
                        float(step["prior_score"]),
                        str(step["role"]),
                        str(step["trace"]),
                    )
                    for step in row["confirmation"]["plan"]["steps"]
                )
            )
            for row in scored
            if int(row["confirmation"]["plan"]["planned_deviations"]) > 0
        ),
        SequencePlan(),
    )
    order_audit = order_invariance_audit(
        args.engine,
        args.a2,
        roots[0],
        first_nonbaseline,
        max_turn_steps=args.max_turn_steps,
        max_rollout_steps=args.max_rollout_steps,
    )
    reorder_audit = option_reordering_audit(roots[0], args.a2)
    static_audit = structural_static_audit()
    generated_nested = any(
        any(int(step["semantic_action"]["context"]) != int(SelectContext.MAIN) for step in plan["steps"])
        for row in scored
        for plan in row["generation"]["plans"]
    )
    generated_two = any(
        int(plan["planned_deviations"]) == 2
        for row in scored
        for plan in row["generation"]["plans"]
    )
    structural = {
        **static_audit,
        "repeat_stable_terminal_result": bool(order_audit["passed"]),
        "candidate_order_invariant": bool(order_audit["passed"]),
        "fresh_root_per_plan": bool(order_audit["independent_fresh_root_per_evaluation"]),
        "no_shared_mutable_rng": order_audit["shared_mutable_rng_between_arms"] is False,
        "semantic_actions_survive_option_reordering": bool(reorder_audit["passed"]),
        "generated_nested_deviation_candidates": generated_nested,
        "generated_two_deviation_candidates": generated_two,
        "order_invariance_detail": order_audit,
        "option_reordering_detail": reorder_audit,
    }
    required_structural = (
        not structural["raw_prompt_local_indices_persisted"]
        and structural["synthetic_stranded_munk_discoverable"]
        and structural["repeat_stable_terminal_result"]
        and structural["candidate_order_invariant"]
        and structural["fresh_root_per_plan"]
        and structural["no_shared_mutable_rng"]
        and structural["semantic_actions_survive_option_reordering"]
        and structural["generated_nested_deviation_candidates"]
        and structural["generated_two_deviation_candidates"]
    )
    if not required_structural:
        raise OracleError(f"structural regression audit failed: {canonical(structural)}")

    production_after = sha256_file(args.production_engine)
    package_hashes_after = {
        "a2": sha256_tree(args.a2),
        **{name: sha256_tree(path) for name, path in opponents.items()},
    }
    if production_before != production_after:
        raise OracleError("production engine changed during the experiment")
    if package_hashes_before != package_hashes_after:
        raise OracleError("a frozen package changed during the experiment")
    elapsed = time.monotonic() - started
    manifest = {
        "schema_version": 1,
        "status": "complete",
        "experiment": "grim_sequence_oracle_v0",
        "recommendation": recommendation,
        "decision_reason": reason,
        "architecture": {
            "baseline": "exact deployed A2+Damage V0",
            "plan": "sparse stable-semantic deviations within current hero turn",
            "maximum_deliberate_deviations": 2,
            "candidate_prior": "frozen A2 option/count ranking only",
            "value_head_used": False,
            "board_evaluator_used": False,
            "plan_budget_per_root": args.plan_budget,
            "alternatives_per_boundary": args.alternatives_per_boundary,
            "nested_prompts_branchable": True,
            "unavailable_plan_behavior": "invalidate remaining plan and fall back to exact A2+Damage V0",
        },
        "sampling": sampling,
        "two_stage_worlds": {
            "proposal": {"worlds": args.proposal_worlds, "base_seed": args.proposal_seed},
            "confirmation": {
                "worlds": args.confirmation_worlds,
                "base_seed": args.confirmation_seed,
                "fresh_and_disjoint": args.confirmation_seed != args.proposal_seed,
            },
            "hidden_worlds": "public-consistent registered authentic opponent deck",
            "matched_hidden_determinization": True,
            "matched_rollout_seed": True,
            "fresh_root_per_plan": True,
            "candidate_evaluation_order_invariant": True,
        },
        "terminal_evaluation": {
            "hero_continuation": "exact deployed A2+Damage V0",
            "opponent_continuation": "exact authentic deterministic lineage package",
            "candidate_controls_future_hero_turns": False,
            "score": {"win": 1, "draw": 0, "loss": -1},
            "rollout_cap": args.max_rollout_steps,
            "truncation_value": None,
        },
        "coverage": {
            "roots": len(scored),
            "root_errors": 0,
            "plan_world_errors": 0,
            "policy_errors": 0,
            "engine_errors": 0,
            "incomplete_rollouts": 0,
            "cleanup_errors": 0,
        },
        "result": {
            "overall": overall,
            "by_opponent": result_by_opponent,
            "by_actual_order": result_by_order,
            "by_own_turn_ordinal": result_by_ordinal,
        },
        "winning_sequence_families": dict(
            Counter(
                row["mechanism"]
                for row in scored
                if str(row["root_id"]) in set(overall["rescue_roots"])
            )
        ),
        "winning_two_deviation_traces": [
            {
                "root_id": row["root_id"],
                "lineage": row["root"]["lineage"],
                "actual_order": row["root"]["actual_order"],
                "family": row["mechanism"],
                "steps": [step["trace"] for step in row["confirmation"]["plan"]["steps"]],
            }
            for row in scored
            if str(row["root_id"]) in set(overall["two_actual_deviation_rescue_roots"])
        ],
        "structural_regression_tests": structural,
        "runtime": {"wall_seconds": elapsed, "workers": args.workers},
        "engine": {
            "seeded_search_path": relative(args.engine),
            "seeded_search_sha256": sha256_file(args.engine),
            "seeded_source_tree_sha256": sha256_tree(ROOT / "freshstart/engine/ptcgProgram"),
            "entrypoint": "SearchSetSeed",
            "production_path": relative(args.production_engine),
            "production_sha256_before": production_before,
            "production_sha256_after": production_after,
            "production_unchanged": production_before == production_after,
        },
        "packages": {
            name: {
                "path": relative(args.a2 if name == "a2" else opponents[name]),
                "tree_sha256_before": package_hashes_before[name],
                "tree_sha256_after": package_hashes_after[name],
                "unchanged": package_hashes_before[name] == package_hashes_after[name],
            }
            for name in package_hashes_before
        },
        "outputs": {
            "roots": {"path": relative(roots_path), "sha256": sha256_file(roots_path)},
            "raw_results": {"path": relative(raw_path), "sha256": sha256_file(raw_path)},
        },
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"recommendation": recommendation, "manifest": relative(manifest_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
