"""Clone-free randomized complete-turn experiment and fail-closed gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing as mp
import random
import socket
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from training.evaluate import run_game_diagnostic
from training.promotion import ONE_SIDED_Z_95
from training.evaluation_schema import sha256_path


@dataclass(frozen=True)
class MacroTrialRow:
    game_id: int
    arm: str
    propensity: float
    selected_turn: int | None
    actual_order: str
    opponent_lineage: str
    opponent_sha256: str
    worker: str
    shard: int
    complied: bool
    routed: bool
    terminal_outcome: int
    policy_errors: int
    fallback_reason: str | None


def _difference(rows: list[MacroTrialRow], order: str | None = None) -> dict[str, float | int]:
    selected = [row for row in rows if order is None or row.actual_order == order]
    treatment = [row for row in selected if row.arm == "treatment"]
    control = [row for row in selected if row.arm == "control"]
    if not treatment or not control:
        raise ValueError(f"missing randomized arm for order={order}")
    tw = sum(row.terminal_outcome for row in treatment)
    cw = sum(row.terminal_outcome for row in control)
    tp, cp = tw / len(treatment), cw / len(control)
    se = math.sqrt(tp * (1 - tp) / len(treatment) + cp * (1 - cp) / len(control))
    return {
        "treatment_games": len(treatment),
        "control_games": len(control),
        "treatment_win_rate": tp,
        "control_win_rate": cp,
        "uplift": tp - cp,
        "one_sided_95_lower": tp - cp - ONE_SIDED_Z_95 * se,
    }


def analyze(rows: list[MacroTrialRow]) -> dict[str, Any]:
    if not rows:
        raise ValueError("macro trial has no rows")
    ids = [row.game_id for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate macro trial game IDs")
    overall = _difference(rows)
    first = _difference(rows, "first")
    second = _difference(rows, "second")
    errors = sum(row.policy_errors for row in rows)
    final = len(rows) >= 16_000
    if len(rows) < 4_000:
        stage = "incomplete"
        passed = False
    elif not final:
        stage = "kill_screen"
        passed = overall["uplift"] >= 0.03 and overall["one_sided_95_lower"] > 0 and errors == 0
    else:
        stage = "confirmation"
        passed = (
            overall["one_sided_95_lower"] >= 0.015
            and second["one_sided_95_lower"] >= 0.02
            and first["one_sided_95_lower"] >= -0.01
            and errors == 0
        )
    return {
        "stage": stage,
        "passed": passed,
        "rows": len(rows),
        "overall": overall,
        "actual_first": first,
        "actual_second": second,
        "policy_errors": errors,
        "intention_to_treat": True,
        "engine_randomness": "independent_unpaired",
    }


def _parse_opponent(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("opponent must be LINEAGE=SUBMISSION_DIR")
    name, raw_path = value.split("=", 1)
    path = Path(raw_path).resolve()
    if not name or not path.is_dir() or not (path / "deck.csv").is_file():
        raise argparse.ArgumentTypeError(f"invalid opponent: {value}")
    return name, path


def _telemetry(result: dict) -> tuple[bool, bool, int | None, str | None]:
    route = result.get("hero_telemetry") or {}
    director = route.get("director") or {}
    last = director.get("last_result") or {}
    routed = route.get("status") == "compatible" or bool(route.get("mirror_activations"))
    complied = last.get("status") == "planned"
    return routed, complied, director.get("planned_turn"), last.get("fallback_reason")


def run_trial(candidate: Path, opponents: list[tuple[str, Path]], games: int, workers: int, seed: int) -> list[MacroTrialRow]:
    if games % (2 * len(opponents)):
        raise ValueError("games must be divisible by two arms times opponent lineages")
    candidate = candidate.resolve()
    candidate_deck = candidate / "deck.csv"
    if not candidate_deck.is_file():
        raise FileNotFoundError(candidate_deck)
    schedule = []
    rng = random.Random(seed)
    per_lineage = games // len(opponents)
    game_id = 0
    for lineage, opponent in opponents:
        block = ["control", "treatment"] * (per_lineage // 2)
        rng.shuffle(block)
        for arm in block:
            task = (
                game_id,
                str(candidate_deck), "",
                str(opponent / "deck.csv"), "",
                str(candidate), {"PTCG_DIRECTOR_ARM": arm},
                str(opponent), {}, seed, 2_000,
            )
            schedule.append((game_id, lineage, opponent, arm, task))
            game_id += 1
    rng.shuffle(schedule)

    rows: list[MacroTrialRow] = []
    context = mp.get_context("spawn")
    tasks = [item[-1] for item in schedule]
    metadata = {item[0]: item[:-1] for item in schedule}
    # run_game_diagnostic returns seat from the task index, so result order may
    # be unordered but task index remains a stable join key.
    with context.Pool(workers) as pool:
        for completed, (task, result) in enumerate(zip(tasks, pool.imap(run_game_diagnostic, tasks, chunksize=1)), 1):
            gid = int(task[0])
            _gid, lineage, opponent, arm = metadata[gid]
            routed, complied, selected_turn, fallback_reason = _telemetry(result)
            rows.append(MacroTrialRow(
                game_id=gid,
                arm=arm,
                propensity=0.5,
                selected_turn=int(selected_turn) if selected_turn is not None else None,
                actual_order="first" if result["hero_went_first"] else "second",
                opponent_lineage=lineage,
                opponent_sha256=sha256_path(opponent),
                worker=socket.gethostname(),
                shard=gid % max(8, workers),
                complied=complied,
                routed=routed,
                terminal_outcome=int(result["win"]),
                policy_errors=int(result["hero_errors"]),
                fallback_reason=fallback_reason,
            ))
            if completed % 100 == 0:
                print(json.dumps({"complete": completed, "games": games}), flush=True)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True, help="extracted Director submission")
    parser.add_argument("--opponent", action="append", type=_parse_opponent, required=True)
    parser.add_argument("--games", type=int, default=4_000)
    parser.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    parser.add_argument("--seed", type=int, default=2026080801)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.time()
    rows = run_trial(args.candidate, args.opponent, args.games, args.workers, args.seed)
    decision = analyze(rows)
    payload = {
        "schema": "macro_trial_v1",
        "candidate_sha256": sha256_path(args.candidate),
        "seed": args.seed,
        "started_unix": started,
        "elapsed_seconds": time.time() - started,
        "decision": decision,
        "rows": [asdict(row) for row in sorted(rows, key=lambda row: row.game_id)],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(decision, indent=2))
    return 0 if decision["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
