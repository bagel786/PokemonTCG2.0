"""Fail-closed promotion manifest for the clone-free Turn Director."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.promotion import ONE_SIDED_Z_95, wilson_interval
from training.evaluation_schema import sha256_file


def diff(cw: int, cg: int, bw: int, bg: int) -> dict[str, float]:
    if min(cg, bg) <= 0:
        raise ValueError("empty promotion comparison")
    cp, bp = cw / cg, bw / bg
    se = math.sqrt(cp * (1 - cp) / cg + bp * (1 - bp) / bg)
    return {"uplift": cp - bp, "one_sided_95_lower": cp - bp - ONE_SIDED_Z_95 * se}


def owned_gate(payload: dict[str, Any]) -> dict[str, Any]:
    cells = payload.get("cells")
    if not isinstance(cells, list) or not cells:
        raise ValueError("owned tournament cells missing")
    if any(cell.get("source_type") == "behavior_clone" for cell in cells):
        raise ValueError("behavior clone entered owned tournament")
    lineages = sorted({str(cell["lineage"]) for cell in cells})
    if len(lineages) < 3:
        raise ValueError("owned tournament requires three qualification lineages")
    if {str(cell["actual_order"]) for cell in cells} != {"first", "second"}:
        raise ValueError("owned tournament is missing an actual-order stratum")
    if len({int(cell["shard"]) for cell in cells}) < 8:
        raise ValueError("owned tournament requires eight independent shards")

    summaries = {}
    for lineage in lineages:
        for order in ("first", "second"):
            selected = [cell for cell in cells if str(cell["lineage"]) == lineage and str(cell["actual_order"]) == order]
            cw = sum(int(cell["candidate_wins"]) for cell in selected)
            cg = sum(int(cell["candidate_games"]) for cell in selected)
            bw = sum(int(cell["control_wins"]) for cell in selected)
            bg = sum(int(cell["control_games"]) for cell in selected)
            if min(cg, bg) < 2_000:
                raise ValueError(f"underfilled owned cell: {lineage}/{order}")
            summaries[f"{lineage}/{order}"] = diff(cw, cg, bw, bg)

    def aggregate(excluded: str | None = None, order: str | None = None) -> dict[str, float]:
        selected = [cell for cell in cells if str(cell["lineage"]) != excluded and (order is None or str(cell["actual_order"]) == order)]
        # Equal-lineage weighting is achieved by equal required cell counts;
        # fail if any lineage/order totals differ.
        totals = {}
        for lineage in {str(cell["lineage"]) for cell in selected}:
            subset = [cell for cell in selected if str(cell["lineage"]) == lineage]
            totals[lineage] = (sum(int(cell["candidate_games"]) for cell in subset), sum(int(cell["control_games"]) for cell in subset))
        if len(set(totals.values())) != 1:
            raise ValueError("owned lineages are not equally weighted")
        return diff(
            sum(int(cell["candidate_wins"]) for cell in selected), sum(int(cell["candidate_games"]) for cell in selected),
            sum(int(cell["control_wins"]) for cell in selected), sum(int(cell["control_games"]) for cell in selected),
        )

    overall = aggregate()
    orders = {order: aggregate(order=order) for order in ("first", "second")}
    leave_one_out = {lineage: aggregate(excluded=lineage) for lineage in lineages}
    direct = payload.get("direct_vs_r0") or {}
    direct_games, direct_wins = int(direct.get("games", 0)), int(direct.get("wins", -1))
    direct_lower = wilson_interval(direct_wins, direct_games, ONE_SIDED_Z_95)[0] if direct_games > 0 and 0 <= direct_wins <= direct_games else -1
    checks = {
        "equal_lineage_uplift_at_least_5": overall["uplift"] >= 0.05,
        "equal_lineage_lower_at_least_2": overall["one_sided_95_lower"] >= 0.02,
        "each_order_uplift_at_least_4": all(row["uplift"] >= 0.04 for row in orders.values()),
        "each_order_lower_nonnegative": all(row["one_sided_95_lower"] >= 0 for row in orders.values()),
        "leave_one_lineage_out_lower_positive": all(row["one_sided_95_lower"] > 0 for row in leave_one_out.values()),
        "no_lineage_order_regression_worse_than_1": all(row["uplift"] >= -0.01 for row in summaries.values()),
        "direct_r0_win_rate_at_least_55": direct_games > 0 and direct_wins / direct_games >= 0.55,
        "direct_r0_lower_at_least_52": direct_lower >= 0.52,
        "zero_errors": all(int(cell.get("policy_errors", -1)) == 0 for cell in cells),
        "hashes_complete": all(cell.get("candidate_sha256") and cell.get("control_sha256") and cell.get("opponent_sha256") for cell in cells),
    }
    return {"passed": all(checks.values()), "checks": checks, "overall": overall, "orders": orders, "leave_one_out": leave_one_out, "worst_cells": summaries, "direct_vs_r0": {**direct, "one_sided_95_lower": direct_lower}}


def replay_gate(payload: dict[str, Any]) -> dict[str, Any]:
    required_banks = ("munkidori_attachment", "adrena_brain", "shadow_bullet", "search_composition")
    checks = {
        "at_least_100_episodes": int(payload.get("episodes", 0)) >= 100,
        "at_least_8_teams": int(payload.get("teams", 0)) >= 8,
        "at_least_30_each_order": all(int((payload.get("orders") or {}).get(order, 0)) >= 30 for order in ("first", "second")),
        "all_compatible_variants": bool(payload.get("all_signature_compatible_variants", False)),
        "branching_gain_at_least_5": float(payload.get("agreement_gain", -1)) >= 0.05,
        "clustered_lower_positive": float(payload.get("clustered_lower", -1)) > 0,
        "no_team_or_order_regression_over_3": float(payload.get("worst_team_or_order_regression", -1)) >= -0.03,
        "critical_banks_positive": all(float((payload.get("banks") or {}).get(bank, {}).get("movement", -1)) > 0 for bank in required_banks),
        "public_prefix_only": bool(payload.get("public_prefix_only", False)),
        "first_pre_divergence_only": bool(payload.get("first_pre_divergence_only", False)),
        "no_clone_metrics": not bool(payload.get("uses_behavior_clone", True)),
    }
    return {"passed": all(checks.values()), "checks": checks}


def decide(package: dict[str, Any], macro: dict[str, Any], owned: dict[str, Any], replay: dict[str, Any], calibration: dict[str, Any] | None = None) -> dict[str, Any]:
    safety = (
        package.get("status") == "packaged_not_promoted"
        and package.get("sterile_load", {}).get("errors") == 0
        and package.get("upload_allowed") is False
        and bool(package.get("archive_sha256"))
    )
    macro_decision = macro.get("decision", macro)
    causal = bool(macro_decision.get("passed")) and macro_decision.get("stage") == "confirmation"
    owned_result = owned_gate(owned)
    replay_result = replay_gate(replay)
    required = safety and causal and owned_result["passed"] and replay_result["passed"]
    classification = "REJECT"
    if required:
        classification = "PROBE_UPLOAD"
        if calibration and (
            float(calibration.get("median_endpoint", 0)) >= 950
            and float(calibration.get("p10_endpoint", 0)) >= 900
            and float(calibration.get("probability_above_900", 0)) >= 0.80
            and float(calibration.get("leave_one_submission_out_mae", 1e9)) <= 50
            and float(calibration.get("rank_correlation", 0)) >= 0.6
            and float(calibration.get("direction_accuracy", 0)) >= 0.75
        ):
            classification = "QUALIFIED_24H_CHALLENGER"
    return {
        "passed": required,
        "classification": classification,
        "checks": {"package_safety": safety, "causal_confirmation": causal, "owned_tournament": owned_result["passed"], "external_replay": replay_result["passed"]},
        "owned": owned_result,
        "replay": replay_result,
        "calibration": calibration,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--macro", type=Path, required=True)
    parser.add_argument("--owned", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    load = lambda path: json.loads(path.read_text(encoding="utf-8"))
    package, macro, owned, replay = map(load, (args.package, args.macro, args.owned, args.replay))
    if sha256_file(Path(package["archive"])) .upper() != str(package["archive_sha256"]).upper():
        raise RuntimeError("promotion package archive hash mismatch")
    result = decide(package, macro, owned, replay, load(args.calibration) if args.calibration else None)
    result["archive_sha256"] = package["archive_sha256"]
    result["upload_allowed"] = result["classification"] in {"PROBE_UPLOAD", "QUALIFIED_24H_CHALLENGER"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
