#!/usr/bin/env python3
"""Fresh A2-reached exact-Grim terminal-Q feasibility screen.

This intentionally stays small.  It plays seeded A2-vs-d842 Grim mirrors,
collects consequential one-choice prompts reached by deployed A2, proposes one
semantic alternative per state from d842, the best temporal continuation, the
A2 network ranking, and small exhaustive legal sets, then uses independent
matched terminal rollouts in three successive-halving stages.

The source-game seed schedule and all rollout schedules are fixed before any
outcomes are observed.  Negative individual worlds are allowed; decisions use
paired expected terminal-outcome differences and fresh confirmation worlds.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import NormalDist
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

import numpy as np

from cg.api import SelectContext, to_observation_class
from scripts import build_a2_rebased_mirror_q_pilot as q_pilot
from scripts.build_grim_policy_disagreements import (
    LoadedPackagePolicy,
    PackageSpec,
    semantic_action,
    stable_id,
    validate_action,
)
from training.evaluate_deterministic_crn import SeededEngine, _forced_order


DEFAULT_TEMPORAL = (
    ROOT
    / "artifacts"
    / "elite_policy_candidates"
    / "temporal_continue_lr25"
    / "package"
    / "extracted"
)
DEFAULT_OUTPUT = ROOT / "artifacts" / "fresh_a2_onpolicy_q_screen"

# Setup, order selection, mulligan, and manual coin choices are not policy
# corrections.  The remaining priorities favor game-changing target, attack,
# switch, and main-phase choices over mechanical bookkeeping.
EXCLUDED_CONTEXTS = {
    int(SelectContext.SETUP_ACTIVE_POKEMON),
    int(SelectContext.SETUP_BENCH_POKEMON),
    int(SelectContext.IS_FIRST),
    int(SelectContext.MULLIGAN),
    int(SelectContext.COIN_HEAD),
    # ATTACH_FROM is a mid-effect prompt whose context card has already left a
    # counted zone.  The public-state determinizer is short by exactly that one
    # card and cannot construct a valid matched hidden pool from this boundary.
    int(SelectContext.ATTACH_FROM),
}
CONTEXT_PRIORITY = defaultdict(
    lambda: 6,
    {
        int(SelectContext.DAMAGE_COUNTER): 16,
        int(SelectContext.DAMAGE_COUNTER_ANY): 16,
        int(SelectContext.ATTACK): 15,
        int(SelectContext.SWITCH): 14,
        int(SelectContext.TO_ACTIVE): 14,
        int(SelectContext.DAMAGE): 14,
        int(SelectContext.REMOVE_DAMAGE_COUNTER): 13,
        int(SelectContext.HEAL): 13,
        int(SelectContext.DISCARD_ENERGY): 12,
        int(SelectContext.EVOLVE): 11,
        int(SelectContext.ATTACH_FROM): 10,
        int(SelectContext.ATTACH_TO): 10,
        int(SelectContext.TO_HAND): 9,
        int(SelectContext.DISCARD): 9,
        int(SelectContext.ACTIVATE): 8,
        int(SelectContext.MAIN): 12,
    },
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def public_observation_sha256(observation: Mapping[str, Any]) -> str:
    public = {key: value for key, value in observation.items() if key != "search_begin_input"}
    return stable_id(public)


def context_name(value: int) -> str:
    try:
        return SelectContext(int(value)).name
    except ValueError:
        return f"UNKNOWN_{int(value)}"


def _policy(name: str, root: Path, *, features: bool = False) -> LoadedPackagePolicy:
    return LoadedPackagePolicy(PackageSpec(name, root.resolve(), {}), feature_provider=features)


def _a2_logits(policy: LoadedPackagePolicy, raw: Mapping[str, Any]) -> np.ndarray:
    if policy._features_module is None or policy._api is None:
        raise RuntimeError("A2 feature provider is unavailable")
    obs = policy._api.to_observation_class(dict(raw))
    model = policy._agent.policy.model
    features = policy._features_module.encode_observation(obs, model.feature_version)
    logits, _, _ = model.predict(features)
    return np.asarray(logits, dtype=np.float64)


def _candidate_for_state(
    raw: dict[str, Any],
    deployed_action: list[int],
    control_action: list[int],
    temporal_action: list[int],
    logits: np.ndarray,
    *,
    exhaustive_max_options: int,
) -> dict[str, Any] | None:
    """Choose one non-A2 semantic alternate without looking at outcomes."""

    options = raw["select"]["option"]
    deployed_semantic = semantic_action(raw, deployed_action)
    deployed_semantic_id = stable_id(deployed_semantic)
    deployed_index = int(deployed_action[0])
    proposed: dict[str, dict[str, Any]] = {}

    def add(action: Sequence[int], proposer: str) -> None:
        try:
            checked = validate_action(raw, list(action), policy_name=proposer)
        except ValueError:
            return
        if len(checked) != 1:
            return
        semantic = semantic_action(raw, checked)
        semantic_id = stable_id(semantic)
        if semantic_id == deployed_semantic_id:
            return
        item = proposed.setdefault(
            semantic_id,
            {
                "action": checked,
                "semantic": semantic,
                "semantic_id": semantic_id,
                "proposers": [],
            },
        )
        item["proposers"].append(proposer)

    add(control_action, "d842_policy")
    add(temporal_action, "temporal_continue_lr25")
    ranked = np.argsort(-logits, kind="stable").astype(int).tolist()
    for rank, index in enumerate(ranked[: min(4, len(ranked))], 1):
        add([index], f"a2_network_rank_{rank}")
    if len(options) <= exhaustive_max_options:
        for index in range(len(options)):
            add([index], "small_legal_exhaustion")
    if not proposed:
        return None

    for item in proposed.values():
        index = int(item["action"][0])
        external_votes = sum(
            proposer in {"d842_policy", "temporal_continue_lr25"}
            for proposer in item["proposers"]
        )
        item["external_policy_votes"] = external_votes
        item["candidate_logit"] = float(logits[index])
        item["deployed_logit"] = float(logits[deployed_index])
        item["deployed_minus_candidate_logit"] = float(logits[deployed_index] - logits[index])
        item["proposers"] = sorted(set(item["proposers"]))

    # Existing-policy agreement is the primary prior; network ambiguity is the
    # tiebreaker.  Exhaustion only supplies coverage when policies agree.
    return max(
        proposed.values(),
        key=lambda item: (
            int(item["external_policy_votes"]),
            "temporal_continue_lr25" in item["proposers"],
            float(item["candidate_logit"]),
            -int(item["action"][0]),
        ),
    )


def collect_source_pool(
    *,
    games: int,
    base_seed: int,
    states: int,
    exhaustive_max_options: int,
    max_decisions: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    a2 = _policy("fresh_source_a2", q_pilot.DEFAULT_A2, features=True)
    opponent = _policy("fresh_source_d842", q_pilot.DEFAULT_CONTROL)
    control_proposer = _policy("fresh_proposer_d842", q_pilot.DEFAULT_CONTROL)
    temporal_proposer = _policy("fresh_proposer_temporal", DEFAULT_TEMPORAL)
    q_pilot._verify_policy_metadata(a2.metadata, q_pilot.A2_MODEL_SHA256, q_pilot.A2_SOURCE_TREE_SHA256)
    q_pilot._verify_policy_metadata(
        opponent.metadata, q_pilot.CONTROL_MODEL_SHA256, q_pilot.CONTROL_SOURCE_TREE_SHA256
    )
    engine = SeededEngine(q_pilot.DEFAULT_ENGINE)
    all_rows: list[dict[str, Any]] = []
    game_results: list[dict[str, Any]] = []
    source_errors = 0

    for game_index in range(games):
        hero_seat = game_index % 2
        actual_order = "first" if (game_index // 2) % 2 == 0 else "second"
        seed = base_seed + game_index
        decks = (
            [list(a2._agent.deck), list(opponent._agent.deck)]
            if hero_seat == 0
            else [list(opponent._agent.deck), list(a2._agent.deck)]
        )
        battle_ptr = 0
        first_player: int | None = None
        hero_boundaries = 0
        try:
            battle_ptr, raw = engine.start(decks[0], decks[1], seed)
            for decision in range(max_decisions):
                obs = to_observation_class(raw)
                if obs.current is not None and int(obs.current.firstPlayer) in (0, 1):
                    first_player = int(obs.current.firstPlayer)
                if obs.current is not None and int(obs.current.result) >= 0:
                    observed_order = "first" if first_player == hero_seat else "second"
                    if observed_order != actual_order:
                        raise RuntimeError(
                            f"source order mismatch: requested {actual_order}, observed {observed_order}"
                        )
                    game_results.append(
                        {
                            "game_index": game_index,
                            "seed": seed,
                            "hero_seat": hero_seat,
                            "actual_order": actual_order,
                            "result": int(obs.current.result),
                            "hero_win": int(int(obs.current.result) == hero_seat),
                            "decisions": decision,
                            "candidate_boundaries": hero_boundaries,
                        }
                    )
                    break
                if obs.select.context == SelectContext.IS_FIRST:
                    action = _forced_order(obs.select, hero_seat, actual_order)
                else:
                    acting_seat = int(obs.current.yourIndex)
                    if acting_seat != hero_seat:
                        action = opponent.act(raw)
                    else:
                        logits = _a2_logits(a2, raw)
                        deployed_action = a2.act(raw)
                        control_action = control_proposer.act(raw)
                        temporal_action = temporal_proposer.act(raw)
                        select = raw.get("select") or {}
                        context = int(select.get("context", -1))
                        minimum = int(select.get("minCount", 0))
                        maximum = int(select.get("maxCount", 0))
                        option_count = len(select.get("option") or [])
                        if (
                            context not in EXCLUDED_CONTEXTS
                            and minimum == maximum == 1
                            and option_count >= 2
                            and len(deployed_action) == 1
                        ):
                            alternative = _candidate_for_state(
                                raw,
                                deployed_action,
                                control_action,
                                temporal_action,
                                logits,
                                exhaustive_max_options=exhaustive_max_options,
                            )
                            if alternative is not None:
                                game_id = f"fresh-a2-{seed}-{hero_seat}-{actual_order}"
                                public_sha = public_observation_sha256(raw)
                                root_sha = stable_id(
                                    {
                                        "game_id": game_id,
                                        "decision": decision,
                                        "public_observation_sha256": public_sha,
                                    }
                                )
                                all_rows.append(
                                    {
                                        "schema_version": 1,
                                        "record_type": "fresh_a2_onpolicy_exact_grim_q_boundary",
                                        "source_game_id": game_id,
                                        "source_game_index": game_index,
                                        "source_game_seed": seed,
                                        "hero_seat": hero_seat,
                                        "actual_order": actual_order,
                                        "source_decision": decision,
                                        "observation": dict(raw),
                                        "public_observation_sha256": public_sha,
                                        "observation_sha256": root_sha,
                                        "deployed_a2_action": deployed_action,
                                        "deployed_a2_semantic": semantic_action(raw, deployed_action),
                                        "deployed_a2_semantic_id": stable_id(
                                            semantic_action(raw, deployed_action)
                                        ),
                                        "candidate_action": alternative["action"],
                                        "candidate_semantic": alternative["semantic"],
                                        "candidate_semantic_id": alternative["semantic_id"],
                                        "candidate_proposers": alternative["proposers"],
                                        "external_policy_votes": alternative["external_policy_votes"],
                                        "candidate_logit": alternative["candidate_logit"],
                                        "deployed_logit": alternative["deployed_logit"],
                                        "deployed_minus_candidate_logit": alternative[
                                            "deployed_minus_candidate_logit"
                                        ],
                                        "select_type": int(select.get("type", -1)),
                                        "select_context": context,
                                        "select_context_name": context_name(context),
                                        "option_count": option_count,
                                        "opponent_matchup": "exact_grim_d842",
                                        "opponent_deck": list(opponent._agent.deck),
                                        "opponent_deck_canonical_sha256": q_pilot.EXACT_GRIM_DECK_SHA256,
                                    }
                                )
                                hero_boundaries += 1
                        action = deployed_action
                raw = engine.select(battle_ptr, action)
            else:
                raise RuntimeError(f"source game {game_index} exceeded decision cap")
        except Exception:
            source_errors += 1
            raise
        finally:
            if battle_ptr:
                engine.finish(battle_ptr)

    # One candidate per distinct state was already chosen.  This deterministic
    # stratified pass prevents MAIN and any single long game from monopolizing
    # the screen while retaining the strongest policy/uncertainty priors.
    ranked = sorted(
        all_rows,
        key=lambda row: (
            -int(row["external_policy_votes"]),
            -int(CONTEXT_PRIORITY[int(row["select_context"])]),
            abs(float(row["deployed_minus_candidate_logit"])),
            int(row["option_count"]),
            int(row["source_game_index"]),
            int(row["source_decision"]),
        ),
    )
    selected: list[dict[str, Any]] = []
    by_context: Counter[int] = Counter()
    by_game: Counter[int] = Counter()
    for row in ranked:
        context = int(row["select_context"])
        game_index = int(row["source_game_index"])
        context_cap = 16 if context == int(SelectContext.MAIN) else 8
        game_cap = max(4, math.ceil(states / games) + 2)
        if by_context[context] >= context_cap or by_game[game_index] >= game_cap:
            continue
        selected.append(row)
        by_context[context] += 1
        by_game[game_index] += 1
        if len(selected) == states:
            break
    if len(selected) < states:
        selected_ids = {row["observation_sha256"] for row in selected}
        for row in ranked:
            if row["observation_sha256"] in selected_ids:
                continue
            selected.append(row)
            selected_ids.add(row["observation_sha256"])
            if len(selected) == states:
                break
    if len(selected) < states:
        raise RuntimeError(f"only {len(selected)} eligible fresh states were collected; requested {states}")

    metadata = {
        "source_games": games,
        "source_base_seed": base_seed,
        "source_errors": source_errors,
        "source_game_results": game_results,
        "eligible_boundaries": len(all_rows),
        "selected_boundaries": len(selected),
        "selected_unique_games": len({row["source_game_id"] for row in selected}),
        "selected_by_context": dict(Counter(row["select_context_name"] for row in selected)),
        "selected_by_proposer": dict(
            Counter(proposer for row in selected for proposer in row["candidate_proposers"])
        ),
        "a2": q_pilot._policy_manifest(a2.metadata),
        "source_opponent": q_pilot._policy_manifest(opponent.metadata),
        "temporal_proposer": q_pilot._policy_manifest(temporal_proposer.metadata),
    }
    return selected, metadata


def _score_rows(
    rows: Sequence[dict[str, Any]],
    *,
    worlds: int,
    base_seed: int,
    workers: int,
    rollout_steps: int,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    initargs = (
        str(q_pilot.DEFAULT_A2.resolve()),
        str(q_pilot.DEFAULT_CONTROL.resolve()),
        str(q_pilot.DEFAULT_ENGINE.resolve()),
        rollout_steps,
        worlds,
        base_seed,
    )
    scored: list[dict[str, Any]] = []
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=workers, initializer=q_pilot._init_worker, initargs=initargs
    ) as pool:
        futures = [pool.submit(q_pilot.score_candidate, dict(row)) for row in rows]
        for completed, future in enumerate(concurrent.futures.as_completed(futures), 1):
            scored.append(future.result())
            if completed % 8 == 0 or completed == len(futures):
                print(json.dumps({"completed": completed, "stage_rows": len(futures)}), flush=True)
    scored.sort(key=lambda row: str(row["observation_sha256"]))
    errors = [row for row in scored if row["q_evaluation"]["errors"]]
    if errors:
        diagnostic = [
            {
                "observation_sha256": row["observation_sha256"],
                "context": row["select_context_name"],
                "errors": row["q_evaluation"]["errors"][:4],
            }
            for row in errors[:10]
        ]
        raise RuntimeError(
            f"terminal-Q stage had {len(errors)} rows with rollout errors: "
            f"{json.dumps(diagnostic, sort_keys=True)}"
        )
    return scored


def deltas(row: Mapping[str, Any]) -> list[float]:
    values = [world["delta"] for world in row["q_evaluation"]["worlds"]]
    if any(value is None for value in values):
        raise ValueError("incomplete terminal-Q row")
    return [float(value) for value in values]


def mean_delta(row: Mapping[str, Any]) -> float:
    values = deltas(row)
    return statistics.mean(values)


def exact_positive_sign_p(values: Sequence[float]) -> float:
    positive = sum(value > 0 for value in values)
    negative = sum(value < 0 for value in values)
    decisive = positive + negative
    if decisive == 0 or positive <= decisive / 2:
        return 1.0
    return sum(math.comb(decisive, k) for k in range(positive, decisive + 1)) / (2**decisive)


def distribution_summary(values: Sequence[float]) -> dict[str, Any]:
    estimate = statistics.mean(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    se = sd / math.sqrt(len(values)) if values else math.inf
    if se:
        z = estimate / se
        one_sided_p = 1.0 - NormalDist().cdf(z)
        lower_one_sided = estimate - 1.6448536269514722 * se
        two_sided = [
            estimate - 1.959963984540054 * se,
            estimate + 1.959963984540054 * se,
        ]
    else:
        one_sided_p = 0.0 if estimate > 0 else 1.0
        lower_one_sided = estimate
        two_sided = [estimate, estimate]
    return {
        "n": len(values),
        "mean_advantage": estimate,
        "sample_sd": sd,
        "standard_error": se,
        "normal_one_sided_p": one_sided_p,
        "normal_one_sided_95_lower": lower_one_sided,
        "normal_two_sided_95": two_sided,
        "strict_better_worlds": sum(value > 0 for value in values),
        "strict_worse_worlds": sum(value < 0 for value in values),
        "equal_worlds": sum(value == 0 for value in values),
        "sign_test_one_sided_p": exact_positive_sign_p(values),
    }


def bootstrap_interval(values: Sequence[float], seed_material: str, repeats: int = 10_000) -> list[float]:
    rng = random.Random(int.from_bytes(hashlib.sha256(seed_material.encode("ascii")).digest()[:8], "big"))
    estimates = sorted(
        sum(rng.choice(values) for _ in range(len(values))) / len(values) for _ in range(repeats)
    )
    return [estimates[math.ceil(0.025 * repeats) - 1], estimates[math.ceil(0.975 * repeats) - 1]]


def bh_adjust(p_values: Sequence[float]) -> list[float]:
    count = len(p_values)
    order = sorted(range(count), key=lambda index: p_values[index])
    adjusted = [1.0] * count
    running = 1.0
    for reverse_rank, index in enumerate(reversed(order), 1):
        rank = count - reverse_rank + 1
        running = min(running, p_values[index] * count / rank)
        adjusted[index] = min(1.0, running)
    return adjusted


def _by_id(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result = {str(row["observation_sha256"]): row for row in rows}
    if len(result) != len(rows):
        raise ValueError("duplicate source boundary IDs")
    return result


def choose_phase2(rows: Sequence[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    ranked = sorted(
        rows,
        key=lambda row: (
            -mean_delta(row),
            -sum(value > 0 for value in deltas(row)),
            sum(value < 0 for value in deltas(row)),
            -int(row["external_policy_votes"]),
            abs(float(row["deployed_minus_candidate_logit"])),
            str(row["observation_sha256"]),
        ),
    )
    positive = [row for row in ranked if mean_delta(row) > 0]
    promoted = positive[:limit]
    # Four terminal worlds can easily all tie.  If signal is sparse, preserve a
    # small predeclared ambiguity tranche, but never expand a negative screen.
    minimum_ambiguous = min(limit, 12)
    if len(promoted) < minimum_ambiguous:
        used = {row["observation_sha256"] for row in promoted}
        for row in ranked:
            if row["observation_sha256"] in used or mean_delta(row) != 0:
                continue
            promoted.append(row)
            used.add(row["observation_sha256"])
            if len(promoted) == minimum_ambiguous:
                break
    return promoted


def choose_phase3(rows: Sequence[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    positive = [row for row in rows if mean_delta(row) > 0]
    return sorted(
        positive,
        key=lambda row: (
            -mean_delta(row),
            -sum(value > 0 for value in deltas(row)),
            sum(value < 0 for value in deltas(row)),
            str(row["observation_sha256"]),
        ),
    )[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source-games", type=int, default=16)
    parser.add_argument("--source-base-seed", type=int, default=2026091100)
    parser.add_argument("--states", type=int, default=48)
    parser.add_argument("--exhaustive-max-options", type=int, default=6)
    parser.add_argument("--phase1-worlds", type=int, default=4)
    parser.add_argument("--phase2-worlds", type=int, default=12)
    parser.add_argument("--phase3-worlds", type=int, default=32)
    parser.add_argument("--phase2-limit", type=int, default=24)
    parser.add_argument("--phase3-limit", type=int, default=24)
    parser.add_argument("--phase1-seed", type=int, default=2026091201)
    parser.add_argument("--phase2-seed", type=int, default=2026091202)
    parser.add_argument("--phase3-seed", type=int, default=2026091203)
    parser.add_argument("--rollout-steps", type=int, default=512)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--max-decisions", type=int, default=2_000)
    args = parser.parse_args()
    positive_args = (
        args.source_games,
        args.states,
        args.exhaustive_max_options,
        args.phase1_worlds,
        args.phase2_worlds,
        args.phase3_worlds,
        args.phase2_limit,
        args.phase3_limit,
        args.rollout_steps,
        args.workers,
        args.max_decisions,
    )
    if any(value <= 0 for value in positive_args):
        raise ValueError("all count, world, worker, and cap arguments must be positive")
    if sha256_file(q_pilot.DEFAULT_ENGINE) != q_pilot.DETERMINISTIC_ENGINE_SHA256:
        raise ValueError("deterministic Q engine hash mismatch")

    production_before = sha256_file(q_pilot.DEFAULT_PRODUCTION_ENGINE)
    selected, source = collect_source_pool(
        games=args.source_games,
        base_seed=args.source_base_seed,
        states=args.states,
        exhaustive_max_options=args.exhaustive_max_options,
        max_decisions=args.max_decisions,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    source_path = args.output_dir / "fresh_source_boundaries.jsonl.gz"
    q_pilot.write_jsonl_gz(source_path, selected)

    phase1 = _score_rows(
        selected,
        worlds=args.phase1_worlds,
        base_seed=args.phase1_seed,
        workers=args.workers,
        rollout_steps=args.rollout_steps,
    )
    phase1_path = args.output_dir / "phase1_four_worlds.jsonl.gz"
    q_pilot.write_jsonl_gz(phase1_path, phase1)

    phase2_source = choose_phase2(phase1, args.phase2_limit)
    phase2 = _score_rows(
        phase2_source,
        worlds=args.phase2_worlds,
        base_seed=args.phase2_seed,
        workers=args.workers,
        rollout_steps=args.rollout_steps,
    )
    phase2_path = args.output_dir / "phase2_fresh_twelve_worlds.jsonl.gz"
    q_pilot.write_jsonl_gz(phase2_path, phase2)

    phase3_source = choose_phase3(phase2, args.phase3_limit)
    phase3 = _score_rows(
        phase3_source,
        worlds=args.phase3_worlds,
        base_seed=args.phase3_seed,
        workers=args.workers,
        rollout_steps=args.rollout_steps,
    )
    phase3_path = args.output_dir / "phase3_fresh_thirtytwo_worlds.jsonl.gz"
    q_pilot.write_jsonl_gz(phase3_path, phase3)

    phase1_by_id, phase2_by_id = _by_id(phase1), _by_id(phase2)
    analyses: list[dict[str, Any]] = []
    for row in phase3:
        key = str(row["observation_sha256"])
        fresh_values = deltas(row)
        fresh = distribution_summary(fresh_values)
        fresh["bootstrap_two_sided_95"] = bootstrap_interval(fresh_values, key)
        analyses.append(
            {
                "observation_sha256": key,
                "source_game_id": row["source_game_id"],
                "source_decision": row["source_decision"],
                "actual_order": row["actual_order"],
                "select_context": row["select_context"],
                "select_context_name": row["select_context_name"],
                "deployed_a2_action": row["deployed_a2_action"],
                "candidate_action": row["candidate_action"],
                "deployed_a2_semantic": row["deployed_a2_semantic"],
                "candidate_semantic": row["candidate_semantic"],
                "candidate_proposers": row["candidate_proposers"],
                "phase1": distribution_summary(deltas(phase1_by_id[key])),
                "phase2": distribution_summary(deltas(phase2_by_id[key])),
                "confirmation": fresh,
                "pooled": distribution_summary(
                    deltas(phase1_by_id[key]) + deltas(phase2_by_id[key]) + fresh_values
                ),
            }
        )
    sign_q = bh_adjust([row["confirmation"]["sign_test_one_sided_p"] for row in analyses])
    normal_q = bh_adjust([row["confirmation"]["normal_one_sided_p"] for row in analyses])
    for row, sign_value, normal_value in zip(analyses, sign_q, normal_q):
        confirmation = row["confirmation"]
        confirmation["sign_test_bh_q"] = sign_value
        confirmation["normal_mean_bh_q"] = normal_value
        confirmation["robust_mean_positive"] = bool(
            confirmation["mean_advantage"] > 0
            and confirmation["normal_one_sided_95_lower"] > 0
            and confirmation["bootstrap_two_sided_95"][0] > 0
            and sign_value <= 0.10
            and normal_value <= 0.10
        )
    robust = [row for row in analyses if row["confirmation"]["robust_mean_positive"]]
    robust_ids = {row["observation_sha256"] for row in robust}
    robust_path = args.output_dir / "robust_fresh_labels.jsonl.gz"
    q_pilot.write_jsonl_gz(
        robust_path, (row for row in phase3 if row["observation_sha256"] in robust_ids)
    )

    production_after = sha256_file(q_pilot.DEFAULT_PRODUCTION_ENGINE)
    if production_before != production_after:
        raise RuntimeError("production engine changed during isolated Q screen")
    phase1_positive = sum(mean_delta(row) > 0 for row in phase1)
    phase2_positive = sum(mean_delta(row) > 0 for row in phase2)
    status = (
        "complete_fresh_label_volume_may_support_training"
        if len(robust) >= 20 and len({row["source_game_id"] for row in robust}) >= 10
        else "complete_fresh_signal_too_sparse_to_train"
    )
    outputs = {
        "source_boundaries": {"path": relative(source_path), "sha256": sha256_file(source_path)},
        "phase1": {"path": relative(phase1_path), "sha256": sha256_file(phase1_path)},
        "phase2": {"path": relative(phase2_path), "sha256": sha256_file(phase2_path)},
        "phase3": {"path": relative(phase3_path), "sha256": sha256_file(phase3_path)},
        "robust_labels": {"path": relative(robust_path), "sha256": sha256_file(robust_path)},
    }
    manifest = {
        "schema_version": 1,
        "status": status,
        "claim": "fresh A2-reached exact-Grim terminal-Q feasibility screen; no policy trained",
        "source": source,
        "selection": {
            "rule": "one semantic alternate per state, selected without outcomes from d842/temporal/A2-ranking/small-exhaustive proposals",
            "states": len(selected),
            "unique_public_states": len({row["public_observation_sha256"] for row in selected}),
            "unique_source_games": len({row["source_game_id"] for row in selected}),
        },
        "successive_halving": {
            "phase1": {
                "base_seed": args.phase1_seed,
                "worlds_per_state": args.phase1_worlds,
                "states": len(phase1),
                "mean_positive": phase1_positive,
                "promoted": len(phase2_source),
                "rule": "positive mean first; fill to 12 only with zero-mean/no-loss ambiguous rows; never promote negative rows",
            },
            "phase2": {
                "base_seed": args.phase2_seed,
                "worlds_per_state": args.phase2_worlds,
                "states": len(phase2),
                "mean_positive": phase2_positive,
                "promoted": len(phase3_source),
                "rule": "fresh mean terminal advantage > 0",
            },
            "phase3": {
                "base_seed": args.phase3_seed,
                "worlds_per_state": args.phase3_worlds,
                "states": len(phase3),
                "robust_mean_positive": len(robust),
                "robust_unique_source_games": len({row["source_game_id"] for row in robust}),
                "rule": "fresh mean > 0; bootstrap two-sided and normal one-sided 95% lower bounds > 0; sign and normal BH q <= 0.10",
            },
            "individual_negative_worlds_allowed": True,
            "selection_schedules_disjoint_from_confirmation": True,
        },
        "decision": {
            "train_candidate": status == "complete_fresh_label_volume_may_support_training",
            "minimum": "at least 20 robust labels across at least 10 fresh source games",
            "reason": (
                f"{len(robust)} robust labels across "
                f"{len({row['source_game_id'] for row in robust})} fresh source games"
            ),
        },
        "analyses": sorted(
            analyses,
            key=lambda row: (
                not row["confirmation"]["robust_mean_positive"],
                -row["confirmation"]["mean_advantage"],
                row["observation_sha256"],
            ),
        ),
        "rollout_contract": {
            "hero_continuation": "deployed shielded A2",
            "opponent_continuation": "byte-exact d842 fixed policy",
            "candidate_never_controls_opponent": True,
            "terminal_only": True,
            "rollout_steps": args.rollout_steps,
            "matched_hidden_determinization": True,
            "matched_rollout_seed": True,
            "independent_roots_per_arm": True,
            "manual_coin": False,
            "scoring_errors": 0,
        },
        "engine": {
            "path": relative(q_pilot.DEFAULT_ENGINE),
            "sha256": sha256_file(q_pilot.DEFAULT_ENGINE),
            "search_seed_entrypoint": "SearchSetSeed",
            "game_seed_entrypoint": "BattleStartSeeded",
        },
        "production_engine": {
            "path": relative(q_pilot.DEFAULT_PRODUCTION_ENGINE),
            "sha256_before": production_before,
            "sha256_after": production_after,
            "preserved": production_before == production_after,
        },
        "script": {
            "path": relative(Path(__file__)),
            "sha256": sha256_file(Path(__file__)),
        },
        "outputs": outputs,
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": status,
                "source_states": len(selected),
                "phase1_mean_positive": phase1_positive,
                "phase2_mean_positive": phase2_positive,
                "confirmation_states": len(phase3),
                "robust_labels": len(robust),
                "manifest": relative(manifest_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
