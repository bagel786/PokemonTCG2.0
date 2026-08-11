#!/usr/bin/env python3
"""Collect one causal temporal-vs-A2 intervention from each seeded A2 game.

Each task first plays deployed A2 against A2 while observing deterministic
temporal-continuation proposals.  It reservoir-samples one semantic single-index
disagreement, then replays the identical seeded game, changes only that decision,
and returns to deployed A2 for the rest of the game.  The resulting terminal
win-indicator difference is noisy per row but locally causal before divergence.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import random
import sys
import time
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from cg.api import SelectContext, to_observation_class
from ptcg_ai.external import ExternalSubmissionAgent
from ptcg_ai.features import encode_observation
from ptcg_ai.model import NumpyPolicyModel
from ptcg_ai.safety import sanitize_selection
from scripts.screen_temporal_context_gate import public_gate_features, semantic_key
from training.evaluate_deterministic_crn import (
    DEFAULT_ENGINE,
    _forced_order,
    _policy_errors,
    _public_observation_sha256,
    get_engine,
    sha256_file,
    sha256_path,
)


DEFAULT_A2 = ROOT / "artifacts/recovery_probes/extracted/a2"
DEFAULT_TEMPORAL = ROOT / "artifacts/elite_policy_candidates/temporal_continue_lr25/package/extracted"
DEFAULT_A2_MODEL = ROOT / "artifacts/emergency_strength_sprint/temporal_elite_schema3/a2_schema3_zero_init.npz"
DEFAULT_TEMPORAL_MODEL = ROOT / "artifacts/elite_policy_candidates/temporal_continue_lr25/policy_weights.npz"
DEFAULT_OUTPUT = ROOT / "artifacts/emergency_strength_sprint/temporal_single_interventions"


_MODELS: tuple[NumpyPolicyModel, NumpyPolicyModel] | None = None
_MODEL_PATHS: tuple[Path, Path] | None = None


def _models(a2_path: Path, temporal_path: Path) -> tuple[NumpyPolicyModel, NumpyPolicyModel]:
    global _MODELS, _MODEL_PATHS
    paths = (a2_path.resolve(), temporal_path.resolve())
    if _MODELS is None:
        _MODELS = (NumpyPolicyModel(paths[0]), NumpyPolicyModel(paths[1]))
        _MODEL_PATHS = paths
    elif _MODEL_PATHS != paths:
        raise RuntimeError("one worker cannot load multiple intervention model pairs")
    return _MODELS


def _terminal(raw: dict[str, Any]) -> bool:
    current = raw.get("current")
    return current is not None and int(current.get("result", -1)) >= 0


def _semantic_action(features, action: list[int]) -> tuple | None:
    if len(action) != 1 or not 0 <= int(action[0]) < len(features.options):
        return None
    return semantic_key(features.options[int(action[0])])


def _run_baseline(task: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    seed = int(task["seed"])
    order = str(task["actual_order"])
    hero_seat = int(task["physical_seat"])
    max_decisions = int(task["max_decisions"])
    rng = random.Random(seed ^ 0xA251C0DE)
    engine = get_engine(task["engine"])
    hero = ExternalSubmissionAgent(task["baseline"], {})
    a2_reference = ExternalSubmissionAgent(task["a2"], {})
    temporal_reference = ExternalSubmissionAgent(task["temporal"], {})
    opponent = ExternalSubmissionAgent(task["opponent"], {})
    decks = [hero.deck, opponent.deck] if hero_seat == 0 else [opponent.deck, hero.deck]
    a2_model, temporal_model = _models(Path(task["a2_model"]), Path(task["temporal_model"]))
    battle_ptr = 0
    decisions = 0
    first_player = None
    target = None
    disagreement_count = 0
    try:
        battle_ptr, raw = engine.start(decks[0], decks[1], seed)
        while True:
            obs = to_observation_class(raw)
            if obs.current is not None and int(obs.current.firstPlayer) in (0, 1):
                first_player = int(obs.current.firstPlayer) if first_player is None else first_player
            if _terminal(raw):
                result = int(raw["current"]["result"])
                observed_order = "first" if first_player == hero_seat else "second"
                if observed_order != order:
                    raise RuntimeError(f"requested {order}, observed {observed_order}")
                return {
                    "win": int(result == hero_seat),
                    "draw": int(result == 2),
                    "decisions": decisions,
                    "hero_policy_errors": _policy_errors(hero),
                    "a2_reference_policy_errors": _policy_errors(a2_reference),
                    "temporal_reference_policy_errors": _policy_errors(temporal_reference),
                    "opponent_policy_errors": _policy_errors(opponent),
                    "disagreements": disagreement_count,
                }, target

            if obs.select.context == SelectContext.IS_FIRST:
                action = _forced_order(obs.select, hero_seat, order)
            else:
                acting_seat = int(obs.current.yourIndex)
                if acting_seat != hero_seat:
                    action = opponent(raw)
                else:
                    action = hero(raw)
                    a2_action = a2_reference(raw)
                    temporal_action = temporal_reference(raw)
                    features = encode_observation(obs, 3)
                    baseline_semantic = _semantic_action(features, action)
                    a2_semantic = _semantic_action(features, a2_action)
                    temporal_semantic = _semantic_action(features, temporal_action)
                    if (
                        baseline_semantic is not None
                        and a2_semantic is not None
                        and temporal_semantic is not None
                        and a2_semantic != temporal_semantic
                        and baseline_semantic in {a2_semantic, temporal_semantic}
                    ):
                        if baseline_semantic == a2_semantic:
                            alternative = temporal_action
                            alternative_policy = "temporal"
                        else:
                            alternative = a2_action
                            alternative_policy = "a2"
                        disagreement_count += 1
                        if rng.randrange(disagreement_count) == 0:
                            a2_logits, _, a2_value = a2_model.predict(features)
                            temporal_logits, _, temporal_value = temporal_model.predict(features)
                            vector, slices = public_gate_features(
                                features,
                                a2_model,
                                temporal_model,
                                a2_logits,
                                temporal_logits,
                                a2_value,
                                temporal_value,
                                int(a2_action[0]),
                                int(temporal_action[0]),
                            )
                            target = {
                                "decision": decisions,
                                "public_observation_sha256": _public_observation_sha256(raw),
                                "alternative_action": list(map(int, alternative)),
                                "baseline_action": list(map(int, action)),
                                "a2_action": list(map(int, a2_action)),
                                "temporal_action": list(map(int, temporal_action)),
                                "alternative_policy": alternative_policy,
                                "turn": int(obs.current.turn or 0),
                                "context": int(features.options[0].context),
                                "a2_option_type": int(features.options[int(a2_action[0])].option_type),
                                "temporal_option_type": int(features.options[int(temporal_action[0])].option_type),
                                "a2_source_card": int(features.options[int(a2_action[0])].source_card),
                                "temporal_source_card": int(features.options[int(temporal_action[0])].source_card),
                                "a2_target_card": int(features.options[int(a2_action[0])].target_card),
                                "temporal_target_card": int(features.options[int(temporal_action[0])].target_card),
                                "a2_attack_id": int(features.options[int(a2_action[0])].attack_id),
                                "temporal_attack_id": int(features.options[int(temporal_action[0])].attack_id),
                                "feature_slices": slices,
                                "gate_features": vector.astype(np.float32, copy=False).tolist(),
                            }
            raw = engine.select(battle_ptr, action)
            decisions += 1
            if decisions >= max_decisions:
                raise RuntimeError("baseline exceeded decision cap")
    finally:
        if battle_ptr:
            engine.finish(battle_ptr)
        hero.close()
        a2_reference.close()
        temporal_reference.close()
        opponent.close()


def _run_intervention(task: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    seed = int(task["seed"])
    order = str(task["actual_order"])
    hero_seat = int(task["physical_seat"])
    max_decisions = int(task["max_decisions"])
    engine = get_engine(task["engine"])
    hero = ExternalSubmissionAgent(task["baseline"], {})
    opponent = ExternalSubmissionAgent(task["opponent"], {})
    decks = [hero.deck, opponent.deck] if hero_seat == 0 else [opponent.deck, hero.deck]
    battle_ptr = 0
    decisions = 0
    first_player = None
    applied = False
    try:
        battle_ptr, raw = engine.start(decks[0], decks[1], seed)
        while True:
            obs = to_observation_class(raw)
            if obs.current is not None and int(obs.current.firstPlayer) in (0, 1):
                first_player = int(obs.current.firstPlayer) if first_player is None else first_player
            if _terminal(raw):
                if not applied:
                    raise RuntimeError("intervention target was never reached")
                result = int(raw["current"]["result"])
                observed_order = "first" if first_player == hero_seat else "second"
                if observed_order != order:
                    raise RuntimeError(f"requested {order}, observed {observed_order}")
                return {
                    "win": int(result == hero_seat),
                    "draw": int(result == 2),
                    "decisions": decisions,
                    "hero_policy_errors": _policy_errors(hero),
                    "opponent_policy_errors": _policy_errors(opponent),
                }

            if obs.select.context == SelectContext.IS_FIRST:
                action = _forced_order(obs.select, hero_seat, order)
            else:
                acting_seat = int(obs.current.yourIndex)
                if acting_seat != hero_seat:
                    action = opponent(raw)
                elif decisions == int(target["decision"]):
                    observed_hash = _public_observation_sha256(raw)
                    if observed_hash != target["public_observation_sha256"]:
                        raise RuntimeError("intervention replay diverged before target")
                    action = sanitize_selection(
                        obs.select,
                        list(map(int, target["alternative_action"])),
                        len(target["alternative_action"]),
                    )
                    if action != target["alternative_action"]:
                        raise RuntimeError("recorded intervention no longer sanitizes identically")
                    applied = True
                else:
                    action = hero(raw)
            raw = engine.select(battle_ptr, action)
            decisions += 1
            if decisions >= max_decisions:
                raise RuntimeError("intervention exceeded decision cap")
    finally:
        if battle_ptr:
            engine.finish(battle_ptr)
        hero.close()
        opponent.close()


def _worker(task: dict[str, Any]) -> dict[str, Any]:
    seed = int(task["seed"])
    random.seed(seed)
    np.random.seed(seed & 0xFFFFFFFF)
    baseline, target = _run_baseline(task)
    row = {
        "task_id": task["task_id"],
        "seed": seed,
        "actual_order": task["actual_order"],
        "physical_seat": int(task["physical_seat"]),
        "baseline": baseline,
        "target": target,
    }
    if target is None:
        row["status"] = "no_semantic_disagreement"
        return row
    intervention = _run_intervention(task, target)
    row["status"] = "complete"
    row["intervention"] = intervention
    row["advantage"] = int(intervention["win"]) - int(baseline["win"])
    return row


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    complete = [row for row in rows if row["status"] == "complete"]
    groups: dict[str, Counter] = defaultdict(Counter)
    for row in complete:
        keys = [
            "overall",
            f"order:{row['actual_order']}",
            f"context:{row['target']['context']}",
            f"types:{row['target']['a2_option_type']}->{row['target']['temporal_option_type']}",
            f"alternative:{row['target']['alternative_policy']}",
        ]
        for key in keys:
            group = groups[key]
            group["rows"] += 1
            group["baseline_wins"] += int(row["baseline"]["win"])
            group["intervention_wins"] += int(row["intervention"]["win"])
            group["advantage_sum"] += int(row["advantage"])
            group[f"advantage:{row['advantage']}"] += 1
    return {
        "tasks": len(rows),
        "status": dict(sorted(Counter(row["status"] for row in rows).items())),
        "groups": {key: dict(value) for key, value in sorted(groups.items())},
        "policy_errors": {
            "baseline_hero": sum(int(row["baseline"]["hero_policy_errors"]) for row in rows),
            "a2_reference": sum(int(row["baseline"]["a2_reference_policy_errors"]) for row in rows),
            "temporal_reference": sum(int(row["baseline"]["temporal_reference_policy_errors"]) for row in rows),
            "baseline_opponent": sum(int(row["baseline"]["opponent_policy_errors"]) for row in rows),
            "intervention_hero": sum(int(row.get("intervention", {}).get("hero_policy_errors", 0)) for row in rows),
            "intervention_opponent": sum(int(row.get("intervention", {}).get("opponent_policy_errors", 0)) for row in rows),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_A2)
    parser.add_argument("--opponent", type=Path, default=DEFAULT_A2)
    parser.add_argument("--a2", type=Path, default=DEFAULT_A2)
    parser.add_argument("--temporal", type=Path, default=DEFAULT_TEMPORAL)
    parser.add_argument("--a2-model", type=Path, default=DEFAULT_A2_MODEL)
    parser.add_argument("--temporal-model", type=Path, default=DEFAULT_TEMPORAL_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--games-per-order", type=int, default=1000)
    parser.add_argument("--actual-order", choices=("both", "first", "second"), default="both")
    parser.add_argument("--base-seed", type=int, default=2026081701)
    parser.add_argument("--workers", type=int, default=max(1, min(8, (mp.cpu_count() or 2) - 1)))
    parser.add_argument("--max-decisions", type=int, default=2000)
    args = parser.parse_args()

    for path in (
        args.engine, args.baseline, args.opponent, args.a2, args.temporal,
        args.a2_model, args.temporal_model,
    ):
        if not path.exists():
            raise FileNotFoundError(path)
    tasks = []
    actual_orders = (
        ("first", "second") if args.actual_order == "both" else (args.actual_order,)
    )
    for order in actual_orders:
        order_index = 0 if order == "first" else 1
        for index in range(args.games_per_order):
            tasks.append(
                {
                    "task_id": f"{order}-{index:05d}",
                    "seed": args.base_seed + order_index * 1_000_000 + index,
                    "actual_order": order,
                    "physical_seat": index % 2,
                    "engine": str(args.engine.resolve()),
                    "baseline": str(args.baseline.resolve()),
                    "opponent": str(args.opponent.resolve()),
                    "a2": str(args.a2.resolve()),
                    "temporal": str(args.temporal.resolve()),
                    "a2_model": str(args.a2_model.resolve()),
                    "temporal_model": str(args.temporal_model.resolve()),
                    "max_decisions": args.max_decisions,
                }
            )

    started = time.time()
    context = mp.get_context("spawn")
    os.environ["PYTHONHASHSEED"] = "0"
    with context.Pool(args.workers) as pool:
        rows = sorted(pool.imap_unordered(_worker, tasks, chunksize=1), key=lambda row: row["task_id"])

    args.output.mkdir(parents=True, exist_ok=True)
    rows_path = args.output / "rows.jsonl.gz"
    with gzip.open(rows_path, "wt", encoding="utf-8", compresslevel=6) as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
    manifest = {
        "schema_version": 1,
        "method": "single_a2_temporal_disagreement_seeded_replay_then_return_to_baseline",
        "base_seed": args.base_seed,
        "games_per_order": args.games_per_order,
        "actual_orders": list(actual_orders),
        "workers": args.workers,
        "elapsed_seconds": time.time() - started,
        "engine_sha256": sha256_file(args.engine),
        "baseline_tree_sha256": sha256_path(args.baseline),
        "opponent_tree_sha256": sha256_path(args.opponent),
        "a2_tree_sha256": sha256_path(args.a2),
        "temporal_tree_sha256": sha256_path(args.temporal),
        "a2_model_sha256": sha256_file(args.a2_model),
        "temporal_model_sha256": sha256_file(args.temporal_model),
        "rows": str(rows_path.resolve()),
        "rows_sha256": hashlib.sha256(rows_path.read_bytes()).hexdigest(),
        "summary": _summary(rows),
    }
    manifest_path = args.output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in manifest.items() if key != "rows"}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
