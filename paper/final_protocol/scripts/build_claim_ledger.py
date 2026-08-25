#!/usr/bin/env python3
"""Build the final sentence-level claim ledger and reject unbound claims."""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
FINAL = SCRIPT.parents[1]
ROOT = SCRIPT.parents[3]
PROTOCOL_COMMIT = "803257f102232763fc88d28c14b668f9b62eb277"
FIELDS = [
    "claim_id", "exact_sentence", "section", "status", "raw_source",
    "source_sha256", "protocol_commit", "analysis_script",
    "analysis_script_sha256", "generation_command", "analysis_unit",
    "sample_size", "estimate", "interval_or_test", "assumptions",
    "limitations", "allowed_wording", "forbidden_wording", "human_verified",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def source_hashes(paths: str) -> str:
    values = []
    for item in paths.split(";"):
        path = ROOT / item.strip()
        if not path.is_file():
            raise FileNotFoundError(path)
        values.append(sha256(path))
    return ";".join(values)


def row(
    claim_id: str,
    sentence: str,
    section: str,
    raw_source: str,
    *,
    status: str = "VERIFIED_WITH_CAVEAT",
    analysis_script: str = "",
    generation_command: str = "",
    analysis_unit: str = "not applicable",
    sample_size: str = "not applicable",
    estimate: str = "not applicable",
    interval_or_test: str = "not applicable",
    assumptions: str,
    limitations: str,
    allowed_wording: str,
    forbidden_wording: str,
) -> dict[str, str]:
    script_hash = sha256(ROOT / analysis_script) if analysis_script else "not applicable"
    return {
        "claim_id": claim_id,
        "exact_sentence": normalize(sentence),
        "section": section,
        "status": status,
        "raw_source": raw_source,
        "source_sha256": source_hashes(raw_source),
        "protocol_commit": PROTOCOL_COMMIT if any(
            marker in raw_source.lower()
            for marker in ("paper/data/", "paper/synthetic/", "protocol")
        ) else "not applicable",
        "analysis_script": analysis_script or "not applicable",
        "analysis_script_sha256": script_hash,
        "generation_command": generation_command or "not applicable",
        "analysis_unit": analysis_unit,
        "sample_size": sample_size,
        "estimate": estimate,
        "interval_or_test": interval_or_test,
        "assumptions": assumptions,
        "limitations": limitations,
        "allowed_wording": allowed_wording,
        "forbidden_wording": forbidden_wording,
        "human_verified": "NO — corresponding-author sign-off required",
    }


def build_rows() -> list[dict[str, str]]:
    reference = "paper/final_protocol/REFERENCE_AUDIT.csv"
    protocol = "paper/protocol/PEVL_PROSPECTIVE_PROTOCOL.md"
    combined = "paper/data/pevl/summary.json"
    preflight = "paper/data/pevl/trace_preflight_summary.json"
    stress = "paper/data/pevl/timed_search_stress_summary.json"
    factorial = "paper/data/pevl/factorial_summary.json;paper/data/pevl/factorial/units.csv"
    historical = "paper/data/ablation/summary.json;paper/data/ablation/canonical_ablation.csv"
    synthetic = "paper/synthetic/results/pevl_results.json"
    seed_audit = "paper/data/seed_namespace_audit.json"
    stochastic_audit = "paper/data/stochastic_source_audit.json"
    verifier = "paper/final_protocol/scripts/verify_statistics.py"
    rows = [
        row(
            "C001",
            "Common-random-number (CRN) theory makes that gain conditional on the construction and on properties such as system structure and event timing, rather than on the reuse of an integer alone \\cite{glasserman1992crn}.",
            "Introduction", reference, status="VERIFIED",
            assumptions="The sentence is limited to the cited source's stated conditions.",
            limitations="Does not show failure or success in the case-study engine.",
            allowed_wording="CRN guarantees and efficiency gains are conditional.",
            forbidden_wording="CRN always reduces variance or same seeds are sufficient.",
        ),
        row(
            "C002",
            "Streams and substreams are established ways to organize synchronized simulation and independent replications \\cite{lecuyer2002streams}.",
            "Introduction", reference, status="VERIFIED",
            assumptions="Use is limited to the published stream/substream design.",
            limitations="A stream label does not prove semantic event assignment.",
            allowed_wording="Streams and substreams are prior art.",
            forbidden_wording="This protocol invented independent streams.",
        ),
        row(
            "C003",
            "The contribution is the operational integration of a declared recorded-trace projection, a self-contained conformance suite, and an executable admission map.",
            "Introduction", reference, status="VERIFIED_WITH_CAVEAT",
            assumptions="Contribution is descriptive, not a priority claim.",
            limitations="The release is not legally public until rights and licensing are confirmed.",
            allowed_wording="We integrate established components in an executable black-box protocol.",
            forbidden_wording="first; novel; unprecedented; groundbreaking",
        ),
        row(
            "C004",
            "The Sharma and Buffalo papers are arXiv preprints, not verified peer-reviewed publications.",
            "Related work and contribution boundary", reference, status="VERIFIED",
            assumptions="Publication-status search current through 2026-08-24.",
            limitations="Status may later change.",
            allowed_wording="arXiv preprints",
            forbidden_wording="peer-reviewed studies",
        ),
        row(
            "C005",
            "A/A experiments are also an established diagnostic in randomized online experimentation \\cite{kohavi2010aa}; the identical-artifact trace repetition used here adapts that diagnostic idea, rather than importing its sampled-user inference.",
            "Related work and contribution boundary", reference, status="VERIFIED_WITH_CAVEAT",
            assumptions="A/A is used as a testing analogy only.",
            limitations="Online-experiment Type-I-error inference differs from deterministic trace repetition.",
            allowed_wording="A/A trace repetition is an adaptation of established diagnostics.",
            forbidden_wording="The protocol invented A/A testing.",
        ),
        row(
            "C006",
            "The implementation compares the SHA-256 digest and byte count of that complete recorded projection.",
            "Definitions — Execution repeatability",
            "training/evaluate_deterministic_crn.py;paper/scripts/analyze_pevl.py",
            status="VERIFIED", analysis_script="paper/scripts/analyze_pevl.py",
            generation_command="python -B paper/scripts/analyze_pevl.py",
            analysis_unit="execution trajectory",
            assumptions="Canonical trace serialization and collision-resistant SHA-256.",
            limitations="Raw public observations and opaque search state are excluded.",
            allowed_wording="digest and byte count of the complete recorded projection",
            forbidden_wording="byte-identical raw public states; full hidden-state trace",
        ),
        row(
            "C007",
            "The restricted engine lacks these event identifiers, so its evaluations cannot establish this property.",
            "Definitions — Semantic event alignment", protocol, status="VERIFIED_WITH_CAVEAT",
            assumptions="Engine interface and retained logs are as documented.",
            limitations="Absence of exposed identifiers is not proof that internal events are unaligned.",
            allowed_wording="Level 7 cannot be established from available evidence.",
            forbidden_wording="Events are proven misaligned.",
        ),
        row(
            "C008",
            "A failed required gate suppresses or downgrades the affected comparison even if its interval excludes zero.",
            "Definitions — Statistical admission", protocol, status="VERIFIED",
            assumptions="The frozen admission rule is followed without outcome-driven amendment.",
            limitations="A protocol rule does not prove all possible rules are optimal.",
            allowed_wording="The protocol fails closed.",
            forbidden_wording="Significance repairs a failed gate.",
        ),
        row(
            "C009",
            "The suite writes complete JSON evidence, a level-by-mode CSV, a JSON Schema, and a SHA-256 manifest.",
            "Self-contained synthetic conformance suite", synthetic, status="VERIFIED",
            analysis_script="paper/synthetic/pevl_synthetic.py",
            generation_command="python paper/synthetic/pevl_synthetic.py verify",
            analysis_unit="synthetic mode by protocol level", sample_size="5 modes; 8 levels",
            assumptions="The released implementation and expected bytes match the manifest.",
            limitations="Fixtures do not estimate external prevalence.",
            allowed_wording="self-contained conformance suite",
            forbidden_wording="validation of the restricted engine",
        ),
        row(
            "C010",
            "The stateful draw-shift fixture repeats exactly within each arm but aligns only one of five shared events after one arm consumes an extra draw.",
            "Self-contained synthetic conformance suite", synthetic, status="DERIVED_BY_CHECKED_SCRIPT",
            analysis_script="paper/synthetic/pevl_synthetic.py",
            generation_command="python -m pevl_bench verify",
            analysis_unit="shared semantic event", sample_size="5 events", estimate="1/5 aligned",
            assumptions="The declared event ontology is complete for the fixture.",
            limitations="Does not imply an external engine contains this mode.",
            allowed_wording="1/5 logged shared events align in the fixture.",
            forbidden_wording="stateful generators universally invalidate CRN.",
        ),
        row(
            "C011",
            "Deriving random quantities from the base seed and semantic event key aligns all five logged shared events.",
            "Self-contained synthetic conformance suite", synthetic, status="DERIVED_BY_CHECKED_SCRIPT",
            analysis_script="paper/synthetic/pevl_synthetic.py",
            generation_command="python -m pevl_bench verify",
            analysis_unit="shared semantic event", sample_size="5 events", estimate="5/5 aligned",
            assumptions="SHA-256 construction and ontology used by the fixture.",
            limitations="Only the logged ontology and fixture distributions are covered.",
            allowed_wording="event-keyed repair aligns 5/5 fixture events.",
            forbidden_wording="event-keyed hashing is universally sufficient.",
        ),
        row(
            "C012",
            "The historical files do not contain the complete field set required for a current Stage-3 pass and did not capture the later trace projection.",
            "Restricted game-agent case study", historical, status="VERIFIED_WITH_CAVEAT",
            analysis_script="paper/scripts/analyze_pevl.py",
            analysis_unit="historical evaluation row", sample_size="2,800 units",
            assumptions="Retained files are the complete available historical record.",
            limitations="Cannot rule out lost metadata or reconstruct traces.",
            allowed_wording="recorded schedule fields agree; full Stage 3 unavailable.",
            forbidden_wording="historical full schedule and trace parity passed.",
        ),
        row(
            "C012A",
            "The bounded source audit verified frozen digests for all 13 inventoried artifacts and applied the Python source-pattern scan to \\SourceAssessedPackageTrees{} package trees.",
            "Restricted game-agent case study", stochastic_audit,
            status="DERIVED_BY_CHECKED_SCRIPT", analysis_script=verifier,
            generation_command="python -B paper/final_protocol/scripts/verify_statistics.py",
            analysis_unit="frozen artifact", sample_size="13 artifacts; 11 Python package trees",
            estimate="13/13 artifact digests matched; 11 trees source scanned",
            assumptions="Canonical tree hashing and the bounded AST/pattern scanner match their checked implementations.",
            limitations="The scan covers only Python source patterns and is neither dynamic evidence nor proof of determinism.",
            allowed_wording="bounded source-pattern audit; 13 digest checks; 11 source-assessed trees",
            forbidden_wording="complete stochastic-source audit; deterministic packages",
        ),
        row(
            "C012B",
            "The \\SourceUnassessedBinaries{} engine binaries were hash checked but not source assessed.",
            "Restricted game-agent case study", stochastic_audit,
            status="DERIVED_BY_CHECKED_SCRIPT", analysis_script=verifier,
            generation_command="python -B paper/final_protocol/scripts/verify_statistics.py",
            analysis_unit="binary engine artifact", sample_size="2 binaries", estimate="2 hash checked; 0 source assessed",
            assumptions="Retained binary-only inventory is complete for the two engine artifacts.",
            limitations="Internal random-source behavior is unobserved.",
            allowed_wording="binary internals were not source assessed",
            forbidden_wording="engine source audit passed; binary determinism established",
        ),
        row(
            "C013",
            "That projection disagreed on \\HistoricalOutcomeMismatch{}/\\HistoricalUnits{} units when it included win and draw fields and on \\HistoricalAvailableRecordMismatch{}/\\HistoricalUnits{} units after decision count was added.",
            "Restricted game-agent case study", historical, status="DERIVED_BY_CHECKED_SCRIPT",
            analysis_script=verifier,
            generation_command="python -B paper/final_protocol/scripts/verify_statistics.py",
            analysis_unit="historical seed-condition unit", sample_size="2,800", estimate="210 outcome/error mismatches; 458 after decision count",
            assumptions="Three separately executed control records are compared on retained fields.",
            limitations="Not full serialization and not trace parity.",
            allowed_wording="available-record projection mismatch",
            forbidden_wording="serialized-record mismatch; full-trace mismatch",
        ),
        row(
            "C014",
            "Both mismatch sets were confined to two timed-search opponent packages.",
            "Restricted game-agent case study", historical, status="DERIVED_BY_CHECKED_SCRIPT",
            analysis_script=verifier,
            generation_command="python -B paper/final_protocol/scripts/verify_statistics.py",
            analysis_unit="fixed opponent package", sample_size="7 packages", estimate="2 packages with mismatches",
            assumptions="Package classification follows the bounded source audit.",
            limitations="Association does not isolate a mechanism.",
            allowed_wording="confined to two timed-search packages",
            forbidden_wording="wall-clock timing caused every mismatch",
        ),
        row(
            "C015",
            "Under the frozen rule, the historical factorial contrasts were not estimable and were suppressed.",
            "Restricted game-agent case study", historical, status="VERIFIED",
            analysis_script="paper/scripts/analyze_pevl.py",
            generation_command="python -B paper/scripts/analyze_pevl.py",
            analysis_unit="planned seven-opponent factorial", sample_size="2,800 units", estimate="suppressed",
            assumptions="Frozen repeated-control gate is authoritative.",
            limitations="Suppression does not erase descriptive mismatch diagnostics.",
            allowed_wording="historical contrasts suppressed/not estimable under the rule",
            forbidden_wording="historical +2.786 pp confirmatory effect",
        ),
        row(
            "C016",
            "Across \\PreflightUnits{} arm--seed-condition units and \\PreflightExecutions{} execution trajectories, the digest and byte count of the complete recorded public-observation-hash/action stream, terminal outcome, errors, and decision count had \\PreflightMismatches{} mismatches.",
            "Prospective validation results — Deterministic preflight", preflight, status="DERIVED_BY_CHECKED_SCRIPT",
            analysis_script=verifier,
            generation_command="python -B paper/scripts/analyze_pevl.py && python -B paper/final_protocol/scripts/verify_statistics.py",
            analysis_unit="arm–seed-condition unit across 3 execution profiles", sample_size="1,000 units; 3,000 executions", estimate="0 mismatches",
            assumptions="Frozen 4-arm by 5-context schedule and canonical trace projection.",
            limitations="No inference to other hardware, loads, or hidden state.",
            allowed_wording="zero trace-projection digest/byte-count mismatches in tested scope",
            forbidden_wording="universally deterministic; event aligned",
        ),
        row(
            "C016A",
            "The prospective boundary-seed audit found all scheduled values in range and distinct, with no overlap with the converted historical namespace.",
            "Prospective validation results", seed_audit,
            status="DERIVED_BY_CHECKED_SCRIPT", analysis_script=verifier,
            generation_command="python -B paper/scripts/audit_seed_namespace.py && python -B paper/final_protocol/scripts/verify_statistics.py",
            analysis_unit="scheduled boundary-seed value", sample_size="2,450 prospective values; 2,800 historical values",
            estimate="0 prospective conversions; 0 prospective collisions; 0 historical/prospective overlaps",
            assumptions="The observable adapter conversion is scheduled_seed & 0xffffffff and all declared schedules are present.",
            limitations="Does not observe the engine's internal seed consumption.",
            allowed_wording="boundary values were in range, distinct, and disjoint on the audited schedules",
            forbidden_wording="internal engine random streams were unique or independent",
        ),
        row(
            "C017",
            "Of \\StressClusters{} clusters and \\StressExecutions{} executions, \\StressTraceMismatch{} clusters had a trace-projection disagreement (\\StressTracePct\\%; empirical 95\\% whole-cluster-resampling interval [\\StressTraceLowPct\\%, \\StressTraceHighPct\\%]).",
            "Prospective validation results — Timed-search stress test", stress, status="DERIVED_BY_CHECKED_SCRIPT",
            analysis_script=verifier,
            generation_command="python -B paper/scripts/analyze_pevl.py && python -B paper/final_protocol/scripts/verify_statistics.py",
            analysis_unit="seed-condition cluster containing 4 execution profiles", sample_size="200 clusters; 800 executions", estimate="99/200 = 49.5%",
            interval_or_test="100,000-draw empirical cluster-resampling interval [42.5%, 56.5%]",
            assumptions="All four profiles remain together during resampling.",
            limitations="Stability interval for a fixed diagnostic battery; not a population CI.",
            allowed_wording="exact repeatability rejected for exercised seeds",
            forbidden_wording="all search agents are nondeterministic",
        ),
        row(
            "C018",
            "Outcomes disagreed in \\StressOutcomeMismatch{} clusters, decision counts in \\StressDecisionMismatch{}, and error records in \\StressErrorMismatch{}.",
            "Prospective validation results — Timed-search stress test", stress, status="DERIVED_BY_CHECKED_SCRIPT",
            analysis_script=verifier, generation_command="python -B paper/final_protocol/scripts/verify_statistics.py",
            analysis_unit="seed-condition cluster", sample_size="200 clusters", estimate="47 outcome; 93 decision; 0 error",
            assumptions="Boolean cluster flags are correctly derived from the four profiles.",
            limitations="Counts can overlap and do not identify a unique source.",
            allowed_wording="endpoint disagreement counts",
            forbidden_wording="independent execution-level observations",
        ),
        row(
            "C018A",
            "All \\StressTraceMismatch{} localized earliest differences occurred on recorded opponent-action events.",
            "Prospective validation results — Timed-search stress test", stress,
            status="DERIVED_BY_CHECKED_SCRIPT", analysis_script=verifier,
            generation_command="python -B paper/final_protocol/scripts/verify_statistics.py",
            analysis_unit="trace-disagreeing seed-condition cluster", sample_size="99 localized clusters",
            estimate="99 opponent-event localizations",
            assumptions="The retained first-divergence actor labels are complete and correctly aggregated.",
            limitations="Localization is association, not causal attribution to wall-clock timing or the opponent implementation.",
            allowed_wording="earliest recorded differences occurred on opponent-action events",
            forbidden_wording="opponent timing caused every divergence",
        ),
        row(
            "C019",
            "Factorial acquisitions recorded schedule, boundary-seed, outcome, error, and decision-count fields; they did \\emph{not} record trace digests.",
            "Gated factorial demonstration", factorial, status="VERIFIED",
            analysis_script="paper/scripts/analyze_pevl.py",
            analysis_unit="factorial evaluation row", sample_size="2,000 common units per cell",
            assumptions="Raw rows report trace_mode=none and null digest fields.",
            limitations="Factorial repeatability is checked only on the captured record.",
            allowed_wording="factorial trace digest not captured",
            forbidden_wording="zero factorial trace mismatches; factorial trace parity",
        ),
        row(
            "C020",
            "The repeated-control audit had \\FactorialControlMismatch{} mismatches, so the frozen rule admitted the finite-schedule seed-matched analysis of \\FactorialUnits{} common units per cell (\\FactorialGames{} engine games across the four cells and separately executed controls).",
            "Gated factorial demonstration", factorial, status="DERIVED_BY_CHECKED_SCRIPT",
            analysis_script="paper/scripts/analyze_pevl.py",
            generation_command="python -B paper/scripts/analyze_pevl.py && python -B paper/final_protocol/scripts/verify_statistics.py",
            analysis_unit="paired unit within 10 opponent-by-order strata", sample_size="2,000 units per cell; 12,000 games", estimate="0 captured-record control mismatches",
            assumptions="Schedule, outcome, error, and decision fields satisfy the frozen gate.",
            limitations="No factorial trace, event alignment, or new-opponent inference.",
            allowed_wording="bounded seed-matched factorial admitted",
            forbidden_wording="fully coupled CRN factorial",
        ),
        row(
            "C021",
            "The total contrast was \\PrimaryEstimatePP{} \\pp{} with paired-resampling interval [\\PrimaryLowPP{}, \\PrimaryHighPP{}].",
            "Gated factorial demonstration", factorial, status="DERIVED_BY_CHECKED_SCRIPT",
            analysis_script=verifier,
            generation_command="python -B paper/final_protocol/scripts/verify_statistics.py",
            analysis_unit="paired unit, equal-weight average across 10 strata", sample_size="2,000", estimate="+0.55 percentage points",
            interval_or_test="100,000-draw empirical paired-resampling interval [-2.05, +3.15] pp",
            assumptions="Frozen schedule and admitted captured-record gate.",
            limitations="Not a population CI or equivalence test.",
            allowed_wording="null-compatible finite-schedule estimate",
            forbidden_wording="policy superiority; equality; equivalence",
        ),
        row(
            "C022",
            "The representation, training, and interaction contrasts were \\RepresentationEstimatePP{}, \\TrainingEstimatePP{}, and \\InteractionEstimatePP{} \\pp{}, respectively; all four intervals span zero.",
            "Gated factorial demonstration", factorial, status="DERIVED_BY_CHECKED_SCRIPT",
            analysis_script=verifier,
            generation_command="python -B paper/final_protocol/scripts/verify_statistics.py",
            analysis_unit="paired unit, equal-weight average across 10 strata", sample_size="2,000", estimate="+0.95, -0.40, +1.30 pp",
            interval_or_test="all four empirical intervals include zero",
            assumptions="Factorial cell mapping and contrast signs are correct.",
            limitations="Does not identify mechanism or prove no effect.",
            allowed_wording="estimates compatible with effects in either direction",
            forbidden_wording="no effect; equivalent policies",
        ),
        row(
            "C022A",
            "The exact two-sided McNemar comparison for the total factorial contrast has \\FactorialInterventionOnlyWins{} intervention-only wins, \\FactorialControlOnlyWins{} control-only wins, and $p=\\McNemarP$; it is secondary and cannot override admission.",
            "Appendix — Resampling and multiplicity details", factorial,
            status="DERIVED_BY_CHECKED_SCRIPT", analysis_script=verifier,
            generation_command="python -B paper/final_protocol/scripts/verify_statistics.py",
            analysis_unit="discordant paired factorial unit", sample_size="705 discordant units",
            estimate="358 intervention-only; 347 control-only",
            interval_or_test="exact two-sided McNemar p=0.706483",
            assumptions="Binary C4 and C1 outcomes remain paired by the frozen unit identifier.",
            limitations="Secondary test; cannot repair a failed admission gate or establish equivalence.",
            allowed_wording="secondary exact McNemar result",
            forbidden_wording="confirmatory superiority test",
        ),
        row(
            "C023",
            "No generative-image system was used; all figures are deterministic plots produced by the checked-in artifact builder.",
            "AI-assisted research methods", "paper/final_protocol/supplement/AI_USE_LOG.csv;paper/final_protocol/scripts/build_final_artifacts.py",
            status="VERIFIED_WITH_CAVEAT",
            analysis_script="paper/final_protocol/scripts/build_final_artifacts.py",
            generation_command="python -B paper/final_protocol/scripts/build_final_artifacts.py",
            assumptions="The activity log is complete for the manuscript figures.",
            limitations="Complete historical AI use still requires human confirmation.",
            allowed_wording="deterministic code-generated figures",
            forbidden_wording="AI-generated figures",
        ),
        row(
            "C024",
            "Public archival availability is not established: the author has not confirmed ownership, an open-source/software-data license, archive creators, maintainer contact, or a DOI.",
            "Data Availability Statement", "paper/final_protocol/supplement/RIGHTS_AND_ACCESS_AUDIT.md;paper/final_protocol/release/LICENSE",
            status="VERIFIED_WITH_CAVEAT",
            assumptions="Current repository records are authoritative for rights status.",
            limitations="A later human-approved license/archive could change status.",
            allowed_wording="public availability is not established",
            forbidden_wording="publicly released; DOI forthcoming",
        ),
        row(
            "C025",
            "The tournament engine and source, engine binaries, third-party opponent packages, game assets and metadata, private replay observations, policy packages, and restricted raw traces are unavailable because of organizer terms, third-party rights, privacy constraints, and unresolved release authority.",
            "Data Availability Statement", "paper/final_protocol/supplement/RIGHTS_AND_ACCESS_AUDIT.md;paper/final_protocol/supplement/PROVENANCE_AUDIT.md",
            status="VERIFIED_WITH_CAVEAT",
            assumptions="Rights audit correctly identifies current authority and constraints.",
            limitations="Final legal determination requires the human author/rightsholders.",
            allowed_wording="restricted and unavailable under current authority",
            forbidden_wording="available on request; publicly reproducible end to end",
        ),
    ]
    return rows


def main() -> int:
    manuscript = normalize((FINAL / "main.tex").read_text(encoding="utf-8"))
    rows = build_rows()
    ids = [item["claim_id"] for item in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate claim IDs")
    allowed = {"VERIFIED", "VERIFIED_WITH_CAVEAT", "DERIVED_BY_CHECKED_SCRIPT"}
    for item in rows:
        if item["status"] not in allowed:
            raise ValueError(f"inadmissible claim status: {item['claim_id']}")
        if item["exact_sentence"] not in manuscript:
            raise ValueError(f"claim sentence not found in manuscript: {item['claim_id']}")
        if not all(item[field] for field in FIELDS):
            raise ValueError(f"empty claim-ledger field: {item['claim_id']}")
    output = FINAL / "claim_ledger.csv"
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} claims to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
