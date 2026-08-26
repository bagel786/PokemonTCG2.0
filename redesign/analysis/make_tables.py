"""Generate Tables 1-6 as CSV and Markdown from canonical sources."""

import ast
import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGG = ROOT / "results/final/aggregates"
OUT = ROOT / "results/final/tables"
OUT.mkdir(parents=True, exist_ok=True)


def write(name, rows):
    fields = list(rows[0])
    with (OUT / f"{name}.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    lines = ["| " + " | ".join(fields) + " |",
             "| " + " | ".join("---" for _ in fields) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row[k]).replace("|", "\\|") for k in fields) + " |")
    (OUT / f"{name}.md").write_text("\n".join(lines) + "\n")


def table1():
    systems = json.loads((ROOT / "protocol/SYSTEM_MANIFEST.json").read_text())["systems"]
    rows = [{"system": x["name"], "role": x["role"], "version": x["version_pin"],
             "license": x["license"], "seed_handling": x["seed_handling"],
             "principal_limit": x["limitations"][0]} for x in systems]
    write("table1_systems_licenses", rows)


def table2():
    claims = json.loads((ROOT / "framework/claim_classes.json").read_text())
    evidence = json.loads((ROOT / "framework/evidence_requirements.json").read_text())
    rows = []
    # The generated Markdown is canonical for descriptive names/questions; the
    # evidence JSON supplies the exact identifiers copied below by branch.
    exact = evidence["requirements_by_class"]
    names = {
        "BRANCH_A": ("Matched descriptive comparison", "Do recorded runs share the declared schedule?"),
        "BRANCH_B": ("Statistically paired inference", "Is the reference distribution justified?"),
        "BRANCH_C": ("Deterministic replay", "Does the declared trace projection repeat?"),
        "BRANCH_D": ("CRN variance reduction", "Does a valid coupling improve precision?"),
        "BRANCH_E": ("Event-aligned counterfactual", "Do corresponding events receive equal values?"),
    }
    assert all(branch in json.dumps(claims) for branch in exact)
    for branch, required in exact.items():
        rows.append({"branch": branch, "claim": names[branch][0], "question": names[branch][1],
                     "required_evidence": "; ".join(required)})
    write("table2_claims_evidence", rows)


def table3():
    tree = ast.parse((ROOT / "benchmark/baselines.py").read_text())
    docs = {n.name: (ast.get_docstring(n) or "").replace("\n", " ")
            for n in tree.body if isinstance(n, ast.FunctionDef)}
    mapping = [
        ("B0", "Schedule matching", "b0_schedule_matching_only"),
        ("B1", "Outcome-only A/A", "b1_outcome_only_aa"),
        ("B2", "Trace-level A/A", "b2_trace_level_aa"),
        ("B3", "Within-seed replication", "b3_within_seed_replication"),
        ("B4", "Unpaired analysis", "b4_unpaired_analysis"),
        ("B5", "Clustered/hierarchical", "b5_clustered_hierarchical"),
        ("B6", "Event-keyed white-box", "b6_event_keyed_whitebox"),
        ("B7", "Full claim-specific framework", "classify_all"),
    ]
    complexity = {r["method"].split("_")[0]: r for r in csv.DictReader((AGG / "complexity_counts.csv").open())}
    rows = []
    for code, label, fn in mapping:
        rows.append({"method": code, "strategy": label,
                     "implementation_summary": docs.get(fn, "Five independent claim gates over the complete evidence bundle."),
                     "required_field_count": complexity[code]["required_field_count"]})
    write("table3_baseline_strategies", rows)


def table4():
    items = json.loads((ROOT / "protocol/FAILURE_INJECTION_MANIFEST.json").read_text())["injections"]
    rows = [{"scenario": x["id"], "name": x["name"], "construction": x["implementation"],
             "paired_gt": x["gt_labels"]["paired_inference"],
             "replay_gt": x["gt_labels"]["replay"], "crn_gt": x["gt_labels"]["crn"]}
            for x in items]
    write("table4_frozen_scenarios", rows)


def table5():
    rows = []
    for row in csv.DictReader((AGG / "decision_metrics.csv").open()):
        if row["system"] == "pooled" and row["branch"] == "BRANCH_B":
            rows.append({"method": row["method"].split("_")[0],
                         "hard_invalid_detection": f"{100*float(row['detection_est']):.1f}% ({row['detected_n']}/{row['invalid_n']})",
                         "false_suppression": f"{100*float(row['false_suppression_est']):.1f}% ({row['false_suppression_n']}/{row['valid_n']})",
                         "caveat_blindness": f"{100*float(row['caveat_blindness_est']):.1f}% ({row['downgrade_missed_n']}/{row['downgrade_n']})"})
    write("table5_main_empirical_results", rows)


def table6():
    estimability = json.loads((AGG / "estimability.json").read_text())
    systems = json.loads((ROOT / "protocol/SYSTEM_MANIFEST.json").read_text())["systems"]
    rows = []
    for metric, item in estimability.items():
        if item["status"] not in {"CONFIRMATORY_COMPLETE", "COMPLETE_CODE_FACT", "COMPLETE_ANALYSIS_MICROBENCHMARK"}:
            rows.append({"scope": metric, "status": item["status"],
                         "limitation": item.get("reason", item.get("source", "See analysis output."))})
    for system in systems:
        rows.append({"scope": system["id"], "status": "SYSTEM_BOUNDARY",
                     "limitation": "; ".join(system["limitations"])})
    rows.extend([
        {"scope": "benchmark", "status": "IMPLEMENTATION_FINDING",
         "limitation": "Ising S4/S8 mechanics did not inject intended clock residual randomness; Branch-C detection is a wrapper-validity finding, not natural-failure prevalence."},
        {"scope": "historical case", "status": "MOTIVATION_ONLY",
         "limitation": "Restricted assets, retrospective rules, and no semantic event alignment; never pooled with prospective evidence."},
    ])
    write("table6_limitations", rows)


def main():
    table1(); table2(); table3(); table4(); table5(); table6()
    print(f"generated {len(list(OUT.glob('*.csv')))} CSV and {len(list(OUT.glob('*.md')))} Markdown tables")


if __name__ == "__main__":
    main()
