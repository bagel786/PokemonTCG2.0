"""Independent raw-row reaggregation for headline decision counts.

Deliberately imports no production analysis code.
"""

import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "results/final/raw/decisions_and_pairs.jsonl"
EXPECTED = ROOT / "results/final/aggregates/results_macros.json"
OUT = ROOT / "results/final/aggregates/independent_reaggregation.json"


def main():
    counts = defaultdict(int)
    decision_rows = pair_rows = 0
    with RAW.open() as stream:
        for line in stream:
            row = json.loads(line)
            if row["level"] == "outcome_pair":
                pair_rows += 1
                continue
            decision_rows += 1
            if row["method"] not in {"B5_cluster_hier", "B7_csvf_full"}:
                continue
            if row["branch"] != "BRANCH_B":
                continue
            method = row["method"]
            if row["gt"] == "INVALID":
                counts[(method, "invalid")] += 1
                counts[(method, "detected")] += row["score_class"] == "CORRECT"
            elif row["gt"] == "VALID":
                counts[(method, "valid")] += 1
                counts[(method, "suppressed")] += row["score_class"] in {
                    "FALSE_SUPPRESSION_SOFT", "FALSE_SUPPRESSION_HARD"
                }
    observed = {
        "raw_rows": decision_rows + pair_rows,
        "decision_rows": decision_rows,
        "outcome_pairs": pair_rows,
        "b7_branch_b_detection_pct": 100 * counts[("B7_csvf_full", "detected")] / counts[("B7_csvf_full", "invalid")],
        "b7_branch_b_detection_n": counts[("B7_csvf_full", "invalid")],
        "b7_branch_b_false_suppression_pct": 100 * counts[("B7_csvf_full", "suppressed")] / counts[("B7_csvf_full", "valid")],
        "b7_branch_b_valid_n": counts[("B7_csvf_full", "valid")],
        "b5_branch_b_detection_pct": 100 * counts[("B5_cluster_hier", "detected")] / counts[("B5_cluster_hier", "invalid")],
        "b5_branch_b_false_suppression_pct": 100 * counts[("B5_cluster_hier", "suppressed")] / counts[("B5_cluster_hier", "valid")],
    }
    expected = json.loads(EXPECTED.read_text())
    checks = {
        key: observed[key] == expected[key]
        for key in observed if key in expected
    }
    result = {"status": "PASS" if all(checks.values()) else "FAIL",
              "observed": observed, "checks": checks}
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if result["status"] != "PASS":
        raise SystemExit("independent reaggregation mismatch")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
