#!/usr/bin/env python3
"""Fail-closed qualification gate for a schema-5 public-policy clone."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.evaluation_schema import load_evaluation


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def total_variation(left: dict, right: dict) -> float:
    keys = set(left) | set(right)
    return 0.5 * sum(abs(float(left.get(key, 0)) - float(right.get(key, 0))) for key in keys)


def required_agreement(report: dict, name: str) -> float:
    row = report.get("strata", {}).get(f"category:{name}")
    if not isinstance(row, dict) or int(row.get("records", 0)) <= 0:
        raise ValueError(f"missing held-out clone stratum: {name}")
    value = row.get("direct_complete_agreement")
    if not isinstance(value, (int, float)):
        raise ValueError(f"missing agreement for stratum: {name}")
    return float(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agreement", required=True)
    parser.add_argument("--gameplay", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    agreement = json.loads((ROOT / args.agreement).read_text(encoding="utf-8"))
    gameplay = load_evaluation(ROOT / args.gameplay)
    model_hash = sha256_file(ROOT / args.model)
    if str(agreement.get("direct_model_sha256", "")).upper() != model_hash:
        raise RuntimeError("agreement report/model hash mismatch")
    provenance_hash = str(gameplay["artifact_provenance"].get("model_a_sha256") or "").upper()
    if provenance_hash and provenance_hash != model_hash:
        raise RuntimeError("gameplay/model hash mismatch")

    overall = agreement.get("overall", {})
    branching = agreement.get("strata", {}).get("category:branching", {})
    checks = {
        "complete_action_agreement_at_least_82": float(overall.get("direct_complete_agreement", -1)) >= .82,
        "main_agreement_at_least_75": required_agreement(agreement, "MAIN") >= .75,
        "attachment_agreement_at_least_75": required_agreement(agreement, "attachment") >= .75,
        "damage_removal_agreement_at_least_75": required_agreement(agreement, "damage_removal") >= .75,
        "attack_target_agreement_at_least_75": required_agreement(agreement, "attack_target") >= .75,
        "search_target_agreement_at_least_75": required_agreement(agreement, "search_target") >= .75,
        "branching_gain_over_r0_at_least_10_points": float(branching.get("uplift_points", -999)) >= 10,
        "gameplay_at_least_2000": int(gameplay["games"]) >= 2000,
        "gameplay_win_rate_at_least_55": float(gameplay["win_rate_a"]) >= .55,
        "zero_policy_errors": gameplay["hero_policy_errors"] == 0 and gameplay["opponent_policy_errors"] == 0,
    }
    order = gameplay.get("first_player_results_a")
    if not isinstance(order, dict) or set(order) != {"first", "second"}:
        raise ValueError("gameplay is missing actual-order cells")
    checks["balanced_actual_order"] = (
        int(order["first"].get("games", 0)) == int(order["second"].get("games", 0))
        and int(order["first"].get("games", 0)) * 2 == int(gameplay["games"])
    )

    stats = agreement.get("sequence_statistics", {})
    teacher, direct = stats.get("teacher"), stats.get("direct")
    if not isinstance(teacher, dict) or not isinstance(direct, dict):
        raise ValueError("missing sequence statistics")
    scalar_deltas = {
        name: abs(float(teacher[name]) - float(direct[name]))
        for name in ("attack_action_rate", "munkidori_attachment_rate", "target_choice_rate")
    }
    attack_turn_tv = total_variation(teacher["attack_turn_distribution"], direct["attack_turn_distribution"])
    target_tv = total_variation(
        agreement["selected_target_card_distribution"]["teacher"],
        agreement["selected_target_card_distribution"]["direct"],
    )
    checks["sequence_statistics_within_10_points"] = max(
        *scalar_deltas.values(), attack_turn_tv, target_tv
    ) <= .10
    result = {
        "status": "passed" if all(checks.values()) else "failed",
        "model_sha256": model_hash,
        "checks": checks,
        "measurements": {
            "overall_agreement": overall.get("direct_complete_agreement"),
            "branching_uplift_points": branching.get("uplift_points"),
            "gameplay_win_rate": gameplay["win_rate_a"],
            "actual_order": order,
            "sequence_scalar_deltas": scalar_deltas,
            "attack_turn_total_variation": attack_turn_tv,
            "target_distribution_total_variation": target_tv,
        },
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
