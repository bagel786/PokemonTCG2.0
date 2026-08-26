"""Generate the claim ledger and machine-readable integrity audits."""

import csv
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
AGG = ROOT / "results/final/aggregates"
MANUSCRIPT = ROOT / "manuscript/manuscript.md"


def sha(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "MISSING"


def pct(x):
    return f"{100*x:.1f}%"


def write_csv(path, rows):
    fields = list(rows[0])
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def claim_ledger():
    macros = json.loads((AGG / "results_macros.json").read_text())
    success = json.loads((AGG / "success_criteria.json").read_text())
    cross = json.loads((AGG / "cross_system.json").read_text())
    decision = json.loads((AGG / "decision_metrics.json").read_text())
    variance = json.loads((AGG / "variance_ratios.json").read_text())
    costs = json.loads((AGG / "costs.json").read_text())
    overhead = json.loads((AGG / "overhead.json").read_text())["results"]
    estimability = json.loads((AGG / "estimability.json").read_text())
    def d(method, branch, system="pooled"):
        return next(r for r in decision if r["method"] == method and r["branch"] == branch and r["system"] == system)
    def score(system):
        return next(r for r in cross["method_scores"] if r["system"] == system and r["method"] == "B7_csvf_full")
    def vr(system, scenario):
        return next(r for r in variance if r["system"] == system and r["scenario"] == scenario)
    def cost(system):
        return next(r for r in costs if r["system"] == system and r["scenario"] == "ALL")
    def over(system):
        return next(r for r in overhead if r["system"] == system)

    raw = ROOT / "results/final/raw/decisions_and_pairs.jsonl"
    expected = ROOT / "protocol/EXPECTED_DECISION_TABLE.json"
    protocol = ROOT / "protocol/PROSPECTIVE_PROTOCOL.md"
    common = {
        "protocol_commit": "62ad878",
        "command": "redesign/.venv/bin/python redesign/analysis/complete_analysis.py",
    }
    claims = [
        ("C001", "Abstract/8", f"The retained corpus contains {macros['decision_rows']} decision cells and {macros['outcome_pairs']} outcome pairs.", raw, "rows", str(macros["raw_rows"]), "exact count", "none; exact corpus count", "JSONL parses and level field is valid", "report exact retained counts", "call S7 accidental missingness", "VERIFIED"),
        ("C002", "8", "The raw-integrity audit passes and binds the raw file to its SHA-256.", AGG/"raw_integrity.json", "file", "1", "cryptographic digest", "none", "SHA-256 implementation", "state PASS with digest", "imply independent scientific validation", "DERIVED_BY_CHECKED_SCRIPT"),
        ("C003", "4/5", "S7 retains 27/40 rows per system by the frozen drop-every-third construction.", expected, "schedule rows per system", "40", "27 retained exactly", "none; deterministic schedule rule", "manifest order and runner rule", "planned missingness", "silent accidental loss", "VERIFIED"),
        ("C004", "Abstract/8", f"B7 Branch-B hard-invalid detection is {macros['b7_branch_b_detection_pct']}% ({d('B7_csvf_full','BRANCH_B')['detected_n']}/{d('B7_csvf_full','BRANCH_B')['invalid_n']}).", AGG/"decision_metrics.json", "labeled decision cell", str(d('B7_csvf_full','BRANCH_B')['invalid_n']), pct(d('B7_csvf_full','BRANCH_B')['detection_est']), f"Wilson [{d('B7_csvf_full','BRANCH_B')['detection_lo']:.3f},{d('B7_csvf_full','BRANCH_B')['detection_hi']:.3f}]", "construction labels; cell unit", "detected all designed hard-invalid Branch-B cells", "generalizes to natural failure prevalence", "DERIVED_BY_CHECKED_SCRIPT"),
        ("C005", "Abstract/8", f"B7 Branch-B false suppression is {macros['b7_branch_b_false_suppression_pct']}% ({d('B7_csvf_full','BRANCH_B')['false_suppression_n']}/{d('B7_csvf_full','BRANCH_B')['valid_n']}).", AGG/"decision_metrics.json", "labeled decision cell", str(d('B7_csvf_full','BRANCH_B')['valid_n']), pct(d('B7_csvf_full','BRANCH_B')['false_suppression_est']), f"Wilson [{d('B7_csvf_full','BRANCH_B')['false_suppression_lo']:.3f},{d('B7_csvf_full','BRANCH_B')['false_suppression_hi']:.3f}]", "construction-valid labels", "suppressed/downgraded valid designed cells", "universal real-world false-suppression rate", "DERIVED_BY_CHECKED_SCRIPT"),
        ("C006", "Abstract/8", f"B5 Branch-B detection is {pct(d('B5_cluster_hier','BRANCH_B')['detection_est'])} and false suppression is {pct(d('B5_cluster_hier','BRANCH_B')['false_suppression_est'])}.", AGG/"decision_metrics.json", "labeled decision cell", f"invalid {d('B5_cluster_hier','BRANCH_B')['invalid_n']}; valid {d('B5_cluster_hier','BRANCH_B')['valid_n']}", "100.0%; 0.0%", "Wilson intervals in source", "same scenario bank as B7", "observed on frozen bank", "equivalent to B7 or universally better", "DERIVED_BY_CHECKED_SCRIPT"),
        ("C007", "Abstract/8/15", f"B7 overall detection is {pct(success['overall_method_metrics']['B7_csvf_full']['detection'])} and pooled false suppression is {pct(success['framework_pooled_false_suppression'])}; the gate fails.", AGG/"success_criteria.json", "labeled decision cell", "all applicable hard-invalid/valid cells", "gate=false", "branch Wilson intervals", "prespecified criteria", "failed predeclared recommendation gate", "framework invalid in every possible use", "DERIVED_BY_CHECKED_SCRIPT"),
        ("C008", "8", f"B7 Branch-C detection is {pct(d('B7_csvf_full','BRANCH_C')['detection_est'])}.", AGG/"decision_metrics.json", "labeled decision cell", str(d('B7_csvf_full','BRANCH_C')['invalid_n']), pct(d('B7_csvf_full','BRANCH_C')['detection_est']), f"Wilson [{d('B7_csvf_full','BRANCH_C')['detection_lo']:.3f},{d('B7_csvf_full','BRANCH_C')['detection_hi']:.3f}]", "frozen labels include defective Ising mechanics", "reference implementation missed designed Branch-C labels", "natural replay failure sensitivity", "VERIFIED_WITH_CAVEAT"),
        ("C009", "11", f"B7 differs by system: hold'em detection {pct(score('holdem')['detection'])}, Ising {pct(score('ising')['detection'])}.", AGG/"cross_system.json", "labeled decision cell", "two systems", "system-specific pooled rates", "descriptive only", "systems and wrappers differ", "cross-system magnitude difference", "causal attribution to domain", "VERIFIED_WITH_CAVEAT"),
        ("C010", "11", f"Cross-system Kendall tau-b is {cross['kendall_tau_b_tradeoff']:.2f}.", AGG/"cross_system.json", "eight method scores", "8 methods x 2 systems", f"tau-b={cross['kendall_tau_b_tradeoff']:.6f}", "no interval; two systems", "predeclared M1-M2 ordering only", "rank association", "probability/utility or broad consistency", "DERIVED_BY_CHECKED_SCRIPT"),
        ("C011", "Abstract/9/14", "M4-M6 are not estimable as frozen because promised outcome banks were not retained.", AGG/"estimability.json", "planned metric", "M4-M6", "NOT_ESTIMABLE/PARTIAL", "schema audit", "absence verified against raw fields/runner", "not estimable as predeclared", "call centered proxies confirmatory coverage/type-I/power", "VERIFIED"),
        ("C012", "9", f"S0 R is {vr('holdem','S0')['var_ratio_R']:.3f} in hold'em and {vr('ising','S0')['var_ratio_R']:.3f} in Ising; intervals include one.", AGG/"variance_ratios.json", "seed pair", "40 per system", "two ratios", "delta-method intervals", "cyclic re-pairing; shared bank", "measured S0 ratios", "coupling validity or general variance benefit", "VERIFIED_WITH_CAVEAT"),
        ("C013", "9", "Hold'em S3 has zero paired-difference variance because the event-keyed path collapses the policy contrast.", REPO/"redesign/benchmark/runner.py", "seed pair", "40", "variance=0", "exact code/row inspection", "event-keyed action function ignores policy", "degenerate benchmark warning", "strong CRN evidence", "VERIFIED_WITH_CAVEAT"),
        ("C014", "10", f"Median pair runtime is {cost('holdem')['runtime_median_s']:.4f}s hold'em and {cost('ising')['runtime_median_s']:.3f}s Ising.", AGG/"costs.json", "retained outcome pair", "427 per system", "medians", "descriptive p95 in source", "instrumented scenario mixture", "observed system acquisition cost", "per-method runtime", "DERIVED_BY_CHECKED_SCRIPT"),
        ("C015", "10", f"Trace microbenchmark overhead is {over('holdem')['trace_overhead_percent']:.1f}% hold'em and {over('ising')['trace_overhead_percent']:.1f}% Ising.", AGG/"overhead.json", "analysis microbenchmark run", "50 per mode/system", "median relative overhead", "run distribution descriptive", "bare and instrumented implementations differ only in logging intent, not necessarily exact path", "bounded analysis-stage overhead", "universal performance cost", "VERIFIED_WITH_CAVEAT"),
        ("C016", "12", "Historical counts are 99/200 trace, 210/2800 outcome-record, and 458/2800 available-record disagreements.", REPO/"paper/final_protocol/INDEPENDENT_STATISTICAL_AUDIT_FINAL.md", "historical unit", "200 and 2800", "exact counts", "historical audit", "restricted retrospective sources", "motivation only", "pool with prospective evidence", "VERIFIED_WITH_CAVEAT"),
        ("C017", "3", "The manuscript-stage novelty gate found no single source supplying all fatal-gate elements.", ROOT/"NOVELTY_AUDIT.md", "literature source", "targeted audit", "gate passed", "search cannot prove absence", "current primary metadata checked", "no substantially complete overlap found", "absolute priority claim", "VERIFIED_WITH_CAVEAT"),
        ("C018", "4", "Protocol commit 62ad878 was pushed before final outcome acquisition.", ROOT/"protocol/FREEZE_RECORD.md", "git commit chronology", "1 freeze", "commit precedes untracked raw acquisition", "git history and handoff log", "system clock/git history trusted", "public git-history freeze", "public registry registration", "VERIFIED"),
        ("C019", "4/16", "RLCard 1.2.0 and ising-monte-carlo-toolkit are MIT-licensed.", ROOT/"release/THIRD_PARTY_NOTICES.md", "selected system", "2", "MIT/MIT", "verbatim installed license copies", "installed distributions match selected versions", "license files identify upstream terms", "legal opinion beyond copied terms", "VERIFIED"),
        ("C020", "15", "The final machine go/no-go is NOT_READY_DO_NOT_SUBMIT.", AGG/"success_criteria.json", "readiness criterion", "multiple required gates", "not ready", "fail-closed decision", "human review and M4-M6 absent; gate failed", "machine readiness decision", "journal rejection forecast", "DERIVED_BY_CHECKED_SCRIPT"),
    ]
    rows = []
    for cid, section, claim, source, unit, denominator, estimate, uncertainty, assumptions, allowed, forbidden, status in claims:
        rows.append({
            "claim_id": cid, "manuscript_section": section, "claim": claim,
            "raw_source": str(Path(source).relative_to(REPO)) if Path(source).is_absolute() else str(source),
            "source_hash": sha(source), **common,
            "analysis_script": "redesign/analysis/complete_analysis.py; redesign/analysis/independent_reaggregate.py",
            "unit": unit, "denominator": denominator, "estimate": estimate,
            "uncertainty": uncertainty, "assumptions": assumptions,
            "allowed_wording": allowed, "forbidden_wording": forbidden,
            "status": status,
        })
    write_csv(ROOT / "claim_ledger.csv", rows)


def contradiction_audit():
    text = MANUSCRIPT.read_text()
    checks = [
        {"id": "no_unresolved_tokens", "pattern": r"\{\{", "expected": 0},
        {"id": "no_preregistered_term", "pattern": r"\bpreregistered\b", "expected": 0},
        {"id": "no_positive_equivalence", "pattern": r"(establishes|demonstrates|shows).{0,25}equivalen", "expected": 0},
        {"id": "no_nonsignificant_no_effect", "pattern": r"nonsignificant.{0,25}no effect", "expected": 0},
        {"id": "no_submission_ready_claim", "pattern": r"\b(?:is|was|deemed) submission-ready\b", "expected": 0},
        {"id": "no_apache_rlcard", "pattern": r"RLCard.{0,30}Apache", "expected": 0},
        {"id": "explicit_not_ready", "pattern": r"NOT_READY_DO_NOT_SUBMIT", "minimum": 1},
        {"id": "explicit_m4_m6_gap", "pattern": r"M4.M6.{0,80}(?:not estimable|missing)", "minimum": 1},
    ]
    for item in checks:
        item["observed"] = len(re.findall(item["pattern"], text, flags=re.I|re.S))
        item["pass"] = item["observed"] == item["expected"] if "expected" in item else item["observed"] >= item["minimum"]
    conflicts = [
        {"id": "K001", "status": "DISCLOSED_CONFLICT", "topic": "Branch-B independence", "detail": "Conceptual framework permits design-based pairing without replay/event alignment; B7 classifier downgrades some such valid cells."},
        {"id": "K002", "status": "DISCLOSED_CONFLICT", "topic": "Ising S4/S8 construction", "detail": "Frozen labels say replay invalid, but Ising runner does not inject the intended clock residual mechanics."},
        {"id": "K003", "status": "DISCLOSED_CONFLICT", "topic": "Hold'em S3 arms", "detail": "Event-keyed action implementation ignores policy, collapsing the intended arm contrast."},
        {"id": "K004", "status": "DISCLOSED_CONFLICT", "topic": "Analysis output contract", "detail": "A/A null banks, S8 repeats, method timers, and bundle bytes promised by the frozen plan were not retained."},
        {"id": "K005", "status": "CORRECTED_WITH_LOG", "topic": "RLCard license", "detail": "Frozen manifest said Apache-2.0; installed 1.2.0 license is MIT. Corrected in D007."},
    ]
    result = {"status": "PASS_WITH_DISCLOSED_CONFLICTS" if all(x["pass"] for x in checks) else "FAIL",
              "manuscript_sha256": sha(MANUSCRIPT), "checks": checks, "conflicts": conflicts}
    (ROOT / "CONTRADICTION_AUDIT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


def reference_audit():
    rows = [
        ("R01", "When Does Pairing Seeds Reduce Variance? Evidence from a Multi-Agent Economic Simulation", "Udit Sharma", "arXiv preprint v3", "2025/2026 revision", "10.48550/arXiv.2512.24145", "https://arxiv.org/abs/2512.24145", "paired-seed variance theory in one simulator"),
        ("R02", "Realizing Common Random Numbers: Event-Keyed Hashing for Causally Valid Stochastic Models", "Vince Buffalo; Carl A. B. Pearson; Daniel Klein", "arXiv preprint", "2026", "10.48550/arXiv.2603.11084", "https://arxiv.org/abs/2603.11084", "stateful draw shifts and event-keyed remedy"),
        ("R03", "Rollout Cards: A Reproducibility Standard for Agent Research", "Charlie Masters; Ziyuan Liu; Stefano V. Albrecht", "arXiv preprint", "2026", "10.48550/arXiv.2605.12131", "https://arxiv.org/abs/2605.12131", "rollout records and drop manifests"),
        ("R04", "Automated Synthesis and Adversarial Validation of Executable Causal Research Pipelines", "Irena Girshovitz; Dan Zeltzer; Ran Gilad-Bachrach", "arXiv preprint", "2026", "10.48550/arXiv.2607.21173", "https://arxiv.org/abs/2607.21173", "planted causal violations and validity-first downgrades"),
        ("R05", "Deterministic Replay for AI Agent Systems", "Rasheed Mudasiru", "arXiv preprint", "2026", "10.48550/arXiv.2607.16200", "https://arxiv.org/abs/2607.16200", "deterministic replay infrastructure"),
        ("R06", "Some Guidelines and Guarantees for Common Random Numbers", "Paul Glasserman; David D. Yao", "Management Science 38(6)", "1992", "10.1287/mnsc.38.6.884", "https://doi.org/10.1287/mnsc.38.6.884", "classical CRN guidance"),
        ("R07", "An Object-Oriented Random-Number Package with Many Long Streams and Substreams", "Pierre L'Ecuyer; Richard Simard; E. Jack Chen; W. David Kelton", "Operations Research 50(6)", "2002", "10.1287/opre.50.6.1073.358", "https://doi.org/10.1287/opre.50.6.1073.358", "streams and substreams"),
        ("R08", "Empirical Design in Reinforcement Learning", "Andrew Patterson; Samuel Neumann; Martha White; Adam White", "JMLR 25(318)", "2024", "", "https://www.jmlr.org/papers/v25/23-0183.html", "RL empirical design"),
        ("R09", "Deep Reinforcement Learning at the Edge of the Statistical Precipice", "Rishabh Agarwal et al.", "NeurIPS 34", "2021", "", "https://proceedings.neurips.cc/paper/2021/hash/f514cec81cb148559cf475e7426eed5e-Abstract.html", "uncertainty and aggregation in RL"),
        ("R10", "Bootstrapping Clustered Data", "C. A. Field; A. H. Welsh", "JRSS B 69(3)", "2007", "10.1111/j.1467-9868.2007.00593.x", "https://doi.org/10.1111/j.1467-9868.2007.00593.x", "cluster bootstrap assumptions"),
        ("R11", "Verification and Validation of Simulation Models", "Robert G. Sargent", "Journal of Simulation 7(1)", "2013", "10.1057/jos.2012.20", "https://doi.org/10.1057/jos.2012.20", "simulation V&V background"),
        ("R12", "RLCard: A Toolkit for Reinforcement Learning in Card Games", "Daochen Zha et al.", "arXiv preprint", "2019", "10.48550/arXiv.1910.04376", "https://arxiv.org/abs/1910.04376", "RLCard system description"),
    ]
    out = []
    for rid, title, authors, venue, year, doi, url, support in rows:
        out.append({"reference_id": rid, "title": title, "authors": authors,
                    "venue_status": venue, "year": year, "doi_or_identifier": doi,
                    "canonical_url": url, "exact_sentence_supported": support,
                    "metadata_checked": "2026-08-26",
                    "status": "VERIFIED" if rid <= "R05" else "VERIFIED_WITH_CAVEAT",
                    "caveat": "Primary current record checked directly." if rid <= "R05" else "Metadata carried from prior audited bibliography; human full-text sentence check still required."})
    write_csv(ROOT / "REFERENCE_AUDIT.csv", out)


def main():
    claim_ledger(); contradiction_audit(); reference_audit()
    print("claim ledger, contradiction audit, and reference audit generated")


if __name__ == "__main__":
    main()
