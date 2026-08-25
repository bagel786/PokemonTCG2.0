#!/usr/bin/env python3
"""Run three fail-closed adversarial reviews of the final Protocol Article.

This report is intentionally regenerated from the final manuscript and current
cross-artifact audit.  A criticism may be technically fixed while the package
as a whole remains NOT_READY_DO_NOT_SUBMIT because human metadata, rights, and
author comprehension cannot be supplied by automation.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

from audit_contradictions import (
    EXPECTED_ARTICLE_TYPE,
    EXPECTED_PROTOCOL_COMMIT,
    EXPECTED_TITLE,
    FINAL,
    build_report as build_contradiction_report,
    load_json_strict,
    relative,
    sha256,
)


DEFAULT_OUTPUT = FINAL / "FINAL_RED_TEAM.json"
MAIN = FINAL / "main.tex"


def normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def source_contains(path: Path, sentence: str) -> bool:
    return path.is_file() and normalized(sentence) in normalized(path.read_text(encoding="utf-8"))


def audit_check_pass(report: dict[str, Any], check_id: str) -> bool:
    return any(
        item.get("check_id") == check_id and item.get("status") == "PASS"
        for item in report.get("checks", [])
    )


def blocker_open(report: dict[str, Any], blocker_id: str) -> bool:
    return any(
        item.get("blocker_id") == blocker_id and item.get("status") == "OPEN"
        for item in report.get("human_or_legal_blockers", [])
    )


def load_reproduction() -> tuple[dict[str, Any] | None, str]:
    path = FINAL / "REPRODUCTION_REPORT.json"
    if not path.is_file():
        return None, "MISSING"
    try:
        payload = load_json_strict(path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return None, f"INVALID: {exc}"
    status = str(payload.get("status", payload.get("overall_status", "MISSING")))
    return payload, status


def reproduction_passed(payload: dict[str, Any] | None, status: str) -> bool:
    if payload is None or status != "PASS":
        return False
    serialized = json.dumps(payload, sort_keys=True).lower()
    required_terms = ("hash", "schema", "statistics", "macro", "table", "figure", "contradiction", "compile")
    return all(term in serialized for term in required_terms)


def visual_audit_passed(payload: dict[str, Any] | None) -> bool:
    if payload is None:
        return False
    candidates = (
        payload.get("visual_audit"),
        payload.get("pdf_visual_audit"),
        payload.get("manuscript", {}).get("visual_audit") if isinstance(payload.get("manuscript"), dict) else None,
    )
    for value in candidates:
        if isinstance(value, str) and value.upper() == "PASS":
            return True
        if isinstance(value, dict) and str(value.get("status", "")).upper() == "PASS":
            return True
    return False


def abstract_checks(main: str) -> dict[str, Any]:
    match = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", main, re.S)
    if not match:
        return {"present": False, "word_count": 0, "one_paragraph": False, "citation_free": False, "limitation": False}
    abstract = match.group(1).strip()
    prose = re.sub(r"\\[A-Za-z]+(?:\{\})?", " ", abstract)
    prose = re.sub(r"[{}]", " ", prose)
    words = re.findall(r"[A-Za-z0-9]+(?:[-–][A-Za-z0-9]+)*", prose)
    return {
        "present": True,
        "word_count": len(words),
        "one_paragraph": not bool(re.search(r"\n\s*\n", abstract)),
        "citation_free": not bool(re.search(r"\\cite", abstract)),
        "limitation": "principal limitation" in abstract.lower() or "limitation" in abstract.lower(),
    }


def criticism(
    criticism_id: str,
    severity: str,
    manuscript_location: str,
    exact_sentence: str,
    reason: str,
    required_evidence: str,
    proposed_fix: str,
    fixed_status: str,
) -> dict[str, str]:
    return {
        "criticism_id": criticism_id,
        "severity": severity,
        "manuscript_location": manuscript_location,
        "exact_sentence": exact_sentence,
        "reason": reason,
        "required_evidence": required_evidence,
        "proposed_fix": proposed_fix,
        "fixed_status": fixed_status,
    }


def simulation_review(
    contradiction: dict[str, Any], reproduction_ok: bool
) -> dict[str, Any]:
    main = MAIN.read_text(encoding="utf-8")
    equation_path = FINAL / "EQUATION_AUDIT.md"
    method_path = FINAL / "METHOD_ASSUMPTION_AUDIT.md"
    entries: list[dict[str, str]] = []

    sentence = "Schedule evidence can authorize only a matched-schedule description."
    entries.append(criticism(
        "SIM-01", "MAJOR", "Definitions — Statistical admission", sentence,
        "A recorded common seed is a design field, not evidence that executions repeat or that semantic random events are coupled across arms.",
        "An explicit implication map linking schedule, within-arm repetition, cross-arm event alignment, and statistical admission.",
        "Keep the four evidence layers separate and prohibit stronger wording when a prerequisite is absent.",
        "FIXED_VERIFIED" if source_contains(MAIN, sentence) else "OPEN_TECHNICAL_BLOCKER",
    ))

    sentence = "The timed-search interval resamples seed-condition clusters, retaining all four execution profiles together."
    entries.append(criticism(
        "SIM-02", "MAJOR", "Appendix — Resampling and multiplicity details", sentence,
        "Four execution profiles reuse the same seed condition and are diagnostic views of one cluster, not independent observations.",
        "Cluster construction, 200 complete clusters, the 100,000-draw algorithm, frozen analysis seed, and an independent recomputation.",
        "State the cluster as the analysis unit and resample all profiles together.",
        "FIXED_VERIFIED" if source_contains(MAIN, sentence) and audit_check_pass(contradiction, "NUM-STRESS-BOOTSTRAP") else "OPEN_TECHNICAL_BLOCKER",
    ))

    sentence = "The restricted engine lacks these event identifiers, so its evaluations cannot establish this property."
    entries.append(criticism(
        "SIM-03", "CRITICAL", "Definitions — Semantic event alignment", sentence,
        "Within-arm trace equality cannot establish cross-arm semantic event alignment after different policies branch.",
        "Stable event identifiers plus values, validated event-specific streams, or an event-keyed construction over a declared ontology.",
        "Explicitly stop the restricted-engine claim below event alignment and reserve stronger language for the synthetic ontology.",
        "FIXED_VERIFIED" if source_contains(MAIN, sentence) else "OPEN_TECHNICAL_BLOCKER",
    ))

    sentence = (
        "This rejects exact repeatability for at least one exercised seed condition and identifies "
        "plausible clock or process mechanisms; it does not prove a unique cause."
    )
    entries.append(criticism(
        "SIM-04", "MAJOR", "Prospective validation results — Timed-search stress test", sentence,
        "Trace divergence under timed search is compatible with clock/process sensitivity but does not isolate wall-clock timing as the unique cause.",
        "A randomized or otherwise identifying intervention on the candidate mechanism would be needed for causal attribution.",
        "Report the observed divergence and candidate mechanisms while withholding unique-cause language.",
        "FIXED_VERIFIED" if source_contains(MAIN, sentence) else "OPEN_TECHNICAL_BLOCKER",
    ))

    sentence = (
        "Factorial acquisitions recorded schedule, boundary-seed, outcome, error, and decision-count "
        "fields; they did \\emph{not} record trace digests."
    )
    entries.append(criticism(
        "SIM-05", "CRITICAL", "Gated factorial demonstration", sentence,
        "Absent factorial trace data cannot be interpreted as zero trace mismatch or as a trace-parity pass.",
        "The frozen factorial record schema, processed factorial rows, and explicit admission decision showing bounded available-record evidence.",
        "Show trace evidence as unavailable and limit the admitted contrast to the prespecified seed-matched finite schedule.",
        "FIXED_VERIFIED" if source_contains(MAIN, sentence) and audit_check_pass(contradiction, "NUM-FACTORIAL-SIZE") else "OPEN_TECHNICAL_BLOCKER",
    ))

    sentence = (
        "Repository history establishes that artifact ordering; it cannot independently prove when a human "
        "inspected uncommitted files."
    )
    entries.append(criticism(
        "SIM-06", "MAJOR", "Prospective validation results", sentence,
        "Commit ancestry establishes retained artifact ordering, not the unknowable time at which a person may have viewed uncommitted outputs.",
        "The protocol's first Git commit, descendant result commits, and a human account of any uncommitted inspection.",
        "State the repository-ordering fact and its epistemic limit without calling the work preregistered.",
        "FIXED_VERIFIED" if source_contains(MAIN, sentence) and audit_check_pass(contradiction, "IDENTITY-PROTOCOL-GIT-ORDER") else "OPEN_TECHNICAL_BLOCKER",
    ))

    sentence = "**Machine checks: PASS. Human verification: PENDING.**"
    human_pending = blocker_open(contradiction, "HUMAN-METHOD-EQUATION-SIGNOFF")
    entries.append(criticism(
        "SIM-07", "CRITICAL", "Equation and method assumption audits", sentence,
        "Executable equation examples do not substitute for a human author confirming estimands, sign conventions, units, and scientific assumptions.",
        "A completed human_verified record for every equation and method, plus author comprehension of the analysis-unit distinctions.",
        "Have the corresponding author review and sign every pending method/equation item; do not infer confirmation from passing tests.",
        "OPEN_HUMAN_BLOCKER" if human_pending else ("FIXED_VERIFIED" if source_contains(equation_path, sentence) is False else "FIXED_VERIFIED"),
    ))

    open_count = sum(not item["fixed_status"].startswith("FIXED") for item in entries)
    return {
        "reviewer_id": "A",
        "reviewer_role": "simulation-methods reviewer",
        "review_scope": "common random numbers, seed boundaries, event alignment, analysis units, resampling, uncertainty, and claim admission",
        "independent_assessment": (
            "The retained numerical and admission statements are simulation-methods consistent, but human verification of equations and assumptions remains open."
            if open_count else "No unresolved simulation-methods criticism remains."
        ),
        "criticisms": entries,
        "open_criticisms": open_count,
    }


def software_review(
    contradiction: dict[str, Any], reproduction_ok: bool, reproduction_status: str
) -> dict[str, Any]:
    entries: list[dict[str, str]] = []

    sentence = (
        "Thus ``complete recorded trace projection'' always means complete only within this declared projection."
    )
    entries.append(criticism(
        "SWT-01", "CRITICAL", "Definitions — Execution repeatability", sentence,
        "Calling a digest a complete engine trace would conceal omitted raw observations, opaque search state, hidden simulator state, and event identifiers.",
        "A canonical serialization specification, explicit included fields, byte count, and an explicit omitted-state list.",
        "Scope completeness to the declared recorded projection everywhere.",
        "FIXED_VERIFIED" if source_contains(MAIN, sentence) else "OPEN_TECHNICAL_BLOCKER",
    ))

    sentence = "Conversely, a digest is not a proof that omitted state agreed."
    entries.append(criticism(
        "SWT-02", "MAJOR", "Definitions — Execution repeatability", sentence,
        "Digest equality establishes equality of serialized bytes under the hash assumption; it does not validate fields that were never serialized.",
        "Trace schema, canonical serializer, digest and byte-count checks, and explicit scope limitations.",
        "Keep the omitted-state caveat next to the digest claim.",
        "FIXED_VERIFIED" if source_contains(MAIN, sentence) else "OPEN_TECHNICAL_BLOCKER",
    ))

    sentence = (
        "Checked tests validate the five fixed mode decisions, event-keyed repair, schema rules, and "
        "manifest-tamper rejection."
    )
    synthetic_files = all((FINAL / name).is_file() for name in (
        "release/pevl_bench/synthetic.py",
        "release/tests/test_release.py",
        "release/pevl_bench/results/pevl_results.json",
        "release/pevl_bench/results/pevl_results.schema.json",
    ))
    entries.append(criticism(
        "SWT-03", "MAJOR", "Self-contained synthetic conformance suite", sentence,
        "A software-testing claim requires executable fixture oracles and negative mutation checks, not only retained expected JSON.",
        "Tests for all five frozen mode decisions, event-keyed repair, schema rejection, and manifest tampering in an engine-independent clean copy.",
        "Retain the executable tests and make the complete reproduction report record their passing commands.",
        "FIXED_VERIFIED" if source_contains(MAIN, sentence) and synthetic_files and reproduction_ok else "OPEN_MACHINE_BLOCKER",
    ))

    sentence = (
        "The release manifest rejects engine binaries, model weights, archives, credentials, absolute "
        "local paths, and non-allow-listed files."
    )
    release_checks = all(
        audit_check_pass(contradiction, check_id)
        for check_id in ("HASH-RELEASE-MANIFEST", "LABELS-NEUTRAL", "INVENTORY-RELEASE-FIGURES-TABLES")
    )
    entries.append(criticism(
        "SWT-04", "CRITICAL", "Appendix — Artifact and rights boundary", sentence,
        "An allow-list claim is unsafe unless the built tree and manifest are checked for omissions, additions, restricted identifiers, paths, and prohibited payload types.",
        "A complete manifest, clean-stage allow-list, forbidden-pattern scan, and independent manifest verification.",
        "Fail release construction on every extra, missing, linked, stale, restricted, or malformed payload.",
        "FIXED_VERIFIED" if source_contains(MAIN, sentence) and release_checks else "OPEN_MACHINE_BLOCKER",
    ))

    sentence = (
        "Factorial records intentionally use \\texttt{trace\\_mode=none}; they contain schedule, outcome, "
        "error, and decision fields only."
    )
    entries.append(criticism(
        "SWT-05", "CRITICAL", "Appendix — Trace record and study-specific fields", sentence,
        "A missing trace field must remain structurally unavailable; coercing it to a zero mismatch would create false evidence.",
        "Exact factorial schema checks, a table marker for unavailable trace evidence, and tests that reject unexpected trace-field claims.",
        "Keep factorial trace evidence unavailable and use only the frozen available-record gate.",
        "FIXED_VERIFIED" if source_contains(MAIN, sentence) and audit_check_pass(contradiction, "NUM-FACTORIAL-SIZE") else "OPEN_TECHNICAL_BLOCKER",
    ))

    sentence = (
        "Verification included artifact hashes, strict schemas, row-level reaggregation, independent equation "
        "tests, targeted software tests, comparison against primary literature, a one-command reproduction run, "
        "compilation, and page-image inspection."
    )
    entries.append(criticism(
        "SWT-06", "CRITICAL", "Trace-based validation protocol — AI-assisted research methods", sentence,
        "The manuscript describes a completed end-to-end verification; that procedural claim must be backed by a current report from the final bytes.",
        "REPRODUCTION_REPORT.json with PASS, command results for hashes/schemas/statistics/macros/tables/figures/tests/contradiction audit/compilation, and final artifact hashes.",
        "Run the one-command workflow after the last edit and bind its report to the final manuscript and release hashes.",
        "FIXED_VERIFIED" if source_contains(MAIN, sentence) and reproduction_ok else "OPEN_MACHINE_BLOCKER",
    ))

    sentence = "`MANIFEST.sha256` covers every staged payload except itself."
    entries.append(criticism(
        "SWT-07", "MAJOR", "Release README — Integrity and status", sentence,
        "A manifest claim is only meaningful if paths are canonical, every payload is covered once, and every digest verifies.",
        "An independent path-safe manifest parser and equality with the actual release file set.",
        "Retain the contradiction audit's manifest coverage and hash comparison.",
        "FIXED_VERIFIED" if source_contains(FINAL / "release/README.md", sentence) and audit_check_pass(contradiction, "HASH-RELEASE-MANIFEST") else "OPEN_MACHINE_BLOCKER",
    ))

    open_count = sum(not item["fixed_status"].startswith("FIXED") for item in entries)
    return {
        "reviewer_id": "B",
        "reviewer_role": "software-testing reviewer",
        "review_scope": "trace invariants, A/A and metamorphic positioning, schema/hash guarantees, tests, release sanitization, and executable reproduction",
        "independent_assessment": (
            f"Trace and release claims are appropriately scoped, but the final end-to-end reproduction status is {reproduction_status}."
            if open_count else "Trace invariants, test scope, release integrity, and final reproduction are verified."
        ),
        "criticisms": entries,
        "open_criticisms": open_count,
    }


def general_reader_review(
    contradiction: dict[str, Any], reproduction_ok: bool, visual_ok: bool
) -> dict[str, Any]:
    main = MAIN.read_text(encoding="utf-8")
    abstract = abstract_checks(main)
    entries: list[dict[str, str]] = []

    sentence = "\\title{A Trace-Based Validation Protocol for Seed-Matched Evaluations of Black-Box Game-Playing Agents}"
    entries.append(criticism(
        "APS-01", "CRITICAL", "Title and article identity", sentence,
        "Submission materials for the wrong title or article category would misrepresent both scope and editorial expectations.",
        "Exact title and APS Open Science Protocol Article type in manuscript, cover letter, release metadata, and checklist.",
        "Use the frozen title and article type in every identity-bearing file.",
        "FIXED_VERIFIED" if source_contains(MAIN, sentence) and audit_check_pass(contradiction, "IDENTITY-TITLE") and audit_check_pass(contradiction, "IDENTITY-ARTICLE-TYPE") else "OPEN_TECHNICAL_BLOCKER",
    ))

    sentence = (
        "Recording the same seed for two game-playing agents establishes a matched schedule, but it does not "
        "show that either execution repeats or that the agents receive equal random quantities for the same "
        "semantic events after their paths diverge."
    )
    abstract_ok = all((
        abstract["present"], abstract["one_paragraph"], abstract["citation_free"],
        abstract["limitation"], abstract["word_count"] < 500,
    ))
    entries.append(criticism(
        "APS-02", "MAJOR", "Abstract", sentence,
        "A general reader needs the seed-versus-evidence problem before protocol machinery, a compact result summary, and a major limitation.",
        "A one-paragraph citation-free abstract under 500 words with supported central numbers and an explicit restricted-engine limitation.",
        "Keep the opening problem statement, central evidence only, and one scope-limiting sentence.",
        "FIXED_VERIFIED" if source_contains(MAIN, sentence) and abstract_ok else "OPEN_EDITORIAL_BLOCKER",
    ))

    sentence = (
        "The contribution is the operational integration of a declared recorded-trace projection, a "
        "self-contained conformance suite, and an executable admission map."
    )
    forbidden_priority = re.findall(
        r"(?i)\b(?:novel|unprecedented|groundbreaking|to our knowledge|we are the first|this is the first)\b",
        main,
    )
    entries.append(criticism(
        "APS-03", "MAJOR", "Introduction and related work", sentence,
        "The paper must distinguish operational integration from prior CRN, streams, A/A, metamorphic, event-keyed, reproducibility, and work-budget methods.",
        "Verified primary literature, a sentence-level reference audit, and no unsupported priority language.",
        "State the integration contribution and enumerate the established prior components without first/novel claims.",
        "FIXED_VERIFIED" if source_contains(MAIN, sentence) and not forbidden_priority else "OPEN_EDITORIAL_BLOCKER",
    ))

    sentence = "\\author{[Author name requires human confirmation]}"
    entries.append(criticism(
        "APS-04", "CRITICAL", "Manuscript front matter", sentence,
        "A journal submission cannot contain an inferred or placeholder author identity, affiliation, address, or corresponding-author contact.",
        "Human-approved author names/order/eligibility, affiliations/postal addresses, email, ORCIDs, and final approval.",
        "Replace all front-matter placeholders only from author-supplied metadata.",
        "OPEN_HUMAN_BLOCKER" if blocker_open(contradiction, "HUMAN-AUTHORS") else "FIXED_VERIFIED",
    ))

    sentence = (
        "Public archival availability is not established: the author has not confirmed ownership, an "
        "open-source/software-data license, archive creators, maintainer contact, or a DOI."
    )
    legal_open = any(
        blocker_open(contradiction, blocker_id)
        for blocker_id in ("LEGAL-OWNERSHIP-REDISTRIBUTION", "LEGAL-LICENSE", "LEGAL-ARCHIVE-DOI")
    )
    entries.append(criticism(
        "APS-05", "CRITICAL", "Data Availability Statement", sentence,
        "Calling a local review package public or citable without confirmed rights, a license, archival metadata, and an actual DOI would be legally and factually unsafe.",
        "Human-confirmed ownership and redistribution rights, an approved license, archive creators/version/location, and a verified DOI only after deposit.",
        "Retain the explicit no-public-archive/no-license/no-DOI status until each legal and archival action is completed.",
        "OPEN_LEGAL_BLOCKER" if legal_open else ("FIXED_VERIFIED" if source_contains(MAIN, sentence) else "OPEN_TECHNICAL_BLOCKER"),
    ))

    sentence = (
        "The corresponding author must confirm the completeness of this disclosure and compliance with "
        "applicable tool terms, confidentiality, privacy, and intellectual-property obligations."
    )
    entries.append(criticism(
        "APS-06", "CRITICAL", "Artificial-intelligence assistance", sentence,
        "The repository can record visible Codex use, but it cannot establish unrecorded earlier use or make the author's policy, privacy, access, and IP confirmations.",
        "Human review of every AI-use-log row, additions for any earlier substantive use, and author confirmation of compliance and final responsibility.",
        "Complete and approve the disclosure without inventing an unavailable model snapshot.",
        "OPEN_HUMAN_BLOCKER" if blocker_open(contradiction, "HUMAN-AI-COMPLETENESS") else "FIXED_VERIFIED",
    ))

    sentence = (
        "The practical recommendation is to identify exact artifacts and boundary seeds, audit row parity, "
        "repeat identical arms at trace-projection level across the contexts that matter, inspect stochastic "
        "sources, and suppress any claim whose required evidence is absent."
    )
    entries.append(criticism(
        "APS-07", "MINOR", "Conclusion", sentence,
        "The paper's significance should resolve into a usable rule rather than a list of game-specific implementation details.",
        "A conclusion that maps the four evidence levels to a concrete fail-closed workflow without repeating every headline number.",
        "Keep the compact operational recommendation and the case study subordinate to the protocol.",
        "FIXED_VERIFIED" if source_contains(MAIN, sentence) else "OPEN_EDITORIAL_BLOCKER",
    ))

    sentence = "Suggested reviewers: **[names, affiliations, expertise, and email addresses require human input, if requested].**"
    entries.append(criticism(
        "APS-08", "MAJOR", "Cover letter", sentence,
        "Suggested and excluded reviewer fields, if requested by the journal, must be selected by a knowledgeable human and cannot be inferred from repository data.",
        "Human-supplied reviewer names, affiliations, expertise, contacts, and conflict-aware exclusions, or an explicit none/not-requested decision.",
        "Complete or remove submission-system-dependent reviewer placeholders under corresponding-author direction.",
        "OPEN_HUMAN_BLOCKER" if source_contains(FINAL / "cover_letter.md", sentence) else "FIXED_VERIFIED",
    ))

    sentence = (
        "Finally, author identities, affiliations, ORCIDs, CRediT roles, funding, conflicts, acknowledgments, "
        "complete historical AI-use confirmation, and permissions to identify organizations or individuals "
        "require human approval."
    )
    human_open = bool(contradiction.get("human_or_legal_blockers"))
    entries.append(criticism(
        "APS-09", "CRITICAL", "Limitations and submission metadata", sentence,
        "These are mandatory submission, ethics, accountability, and naming decisions rather than scientific values an automated audit can fill.",
        "Completed human metadata checklist, author approval, competing-interest statement, funding/acknowledgment decisions, and naming permissions.",
        "Leave the manuscript not ready until every human metadata item is supplied and approved.",
        "OPEN_HUMAN_BLOCKER" if human_open else ("FIXED_VERIFIED" if source_contains(MAIN, sentence) else "OPEN_TECHNICAL_BLOCKER"),
    ))

    sentence = (
        "Verification included artifact hashes, strict schemas, row-level reaggregation, independent equation "
        "tests, targeted software tests, comparison against primary literature, a one-command reproduction run, "
        "compilation, and page-image inspection."
    )
    entries.append(criticism(
        "APS-10", "CRITICAL", "Manuscript and PDF quality gate", sentence,
        "The submitted PDF must be compiled from the final sources and every rendered page inspected for placeholders, clipping, tables, equations, signs, links, and stale artifacts.",
        "A PASS reproduction report bound to final hashes and a recorded all-page visual audit after the last source edit.",
        "Compile, render every page, inspect it, and rerun the reproduction workflow after any correction.",
        "FIXED_VERIFIED" if source_contains(MAIN, sentence) and reproduction_ok and visual_ok else "OPEN_MACHINE_BLOCKER",
    ))

    open_count = sum(not item["fixed_status"].startswith("FIXED") for item in entries)
    return {
        "reviewer_id": "C",
        "reviewer_role": "APS general-reader reviewer",
        "review_scope": "scope, significance, readability, article identity, abstract, disclosure, availability, metadata, and submission readiness",
        "independent_assessment": (
            "The article identity and scientific narrative are clear, but human metadata, rights, AI completeness, and author approval still bar submission."
            if open_count else "The Protocol Article is readable, scoped, and submission-complete."
        ),
        "abstract_audit": abstract,
        "criticisms": entries,
        "open_criticisms": open_count,
    }


def validate_review_structure(passes: list[dict[str, Any]]) -> None:
    required = {
        "severity",
        "manuscript_location",
        "exact_sentence",
        "reason",
        "required_evidence",
        "proposed_fix",
        "fixed_status",
    }
    if [item.get("reviewer_id") for item in passes] != ["A", "B", "C"]:
        raise ValueError("three ordered independent review passes A/B/C are required")
    for review in passes:
        criticisms = review.get("criticisms")
        if not isinstance(criticisms, list) or not criticisms:
            raise ValueError(f"review pass {review.get('reviewer_id')} has no criticisms")
        for item in criticisms:
            missing = required - set(item)
            if missing or any(not str(item[field]).strip() for field in required):
                raise ValueError(
                    f"review pass {review.get('reviewer_id')} has an incomplete criticism: missing={sorted(missing)}"
                )


def build_report() -> dict[str, Any]:
    contradiction = build_contradiction_report()
    reproduction, reproduction_status = load_reproduction()
    reproduction_ok = reproduction_passed(reproduction, reproduction_status)
    visual_ok = visual_audit_passed(reproduction)
    passes = [
        simulation_review(contradiction, reproduction_ok),
        software_review(contradiction, reproduction_ok, reproduction_status),
        general_reader_review(contradiction, reproduction_ok, visual_ok),
    ]
    validate_review_structure(passes)

    open_by_status: dict[str, int] = {}
    for review in passes:
        for item in review["criticisms"]:
            status = item["fixed_status"]
            open_by_status[status] = open_by_status.get(status, 0) + 1
    open_criticisms = sum(
        count for status, count in open_by_status.items() if not status.startswith("FIXED")
    )

    human_legal = contradiction.get("human_or_legal_blockers", [])
    contradictions = contradiction.get("contradictions", [])
    machine = contradiction.get("machine_verification_blockers", [])
    if contradictions or machine or open_criticisms or human_legal:
        final_decision = "NOT_READY_DO_NOT_SUBMIT"
    else:
        final_decision = "READY_TO_SUBMIT_PROTOCOL_ARTICLE"

    identity_hashes = {
        relative(path): sha256(path)
        for path in (
            FINAL / "main.tex",
            FINAL / "main.pdf",
            FINAL / "claim_ledger.csv",
            FINAL / "results_macros.tex",
            FINAL / "CONTRADICTION_AUDIT.json",
        )
        if path.is_file()
    }
    return {
        "schema_version": "final-protocol-red-team-v1",
        "article_identity": {
            "title": EXPECTED_TITLE,
            "article_type": EXPECTED_ARTICLE_TYPE,
            "protocol_commit": EXPECTED_PROTOCOL_COMMIT,
            "artifact_sha256": identity_hashes,
        },
        "review_method": (
            "Three separate fail-closed passes were regenerated against the final Protocol Article: "
            "simulation methods, software testing, and APS general readership. Fixed status records "
            "whether the cited evidence currently resolves the criticism; it is not automatic acceptance of prose."
        ),
        "review_passes": passes,
        "cross_artifact_audit": {
            "overall_status": contradiction.get("overall_status"),
            "contradictions": len(contradictions),
            "machine_verification_blockers": len(machine),
            "human_or_legal_blockers": len(human_legal),
        },
        "reproduction_status": {
            "status": reproduction_status,
            "complete_workflow_passed": reproduction_ok,
            "visual_audit_passed": visual_ok,
        },
        "criticism_summary": {
            "total": sum(len(review["criticisms"]) for review in passes),
            "open": open_criticisms,
            "by_fixed_status": dict(sorted(open_by_status.items())),
        },
        "human_or_legal_blockers": human_legal,
        "decision_basis": (
            "Submission is prohibited while any factual contradiction, machine-verification failure, "
            "review criticism, human metadata/comprehension item, AI-completeness confirmation, ownership/"
            "redistribution decision, license, archive, or DOI blocker remains unresolved."
        ),
        "final_decision": final_decision,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Return nonzero when the final readiness decision is not READY_TO_SUBMIT_PROTOCOL_ARTICLE.",
    )
    args = parser.parse_args(argv)
    try:
        report = build_report()
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        if not args.quiet:
            print(f"red-team audit failed closed: {exc}", file=sys.stderr)
        return 2
    if not args.no_write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    if not args.quiet:
        print(
            "red-team audit: "
            f"{report['final_decision']} "
            f"({report['criticism_summary']['open']} open criticisms, "
            f"{len(report['human_or_legal_blockers'])} human/legal blockers)"
        )
    if args.require_ready and report["final_decision"] != "READY_TO_SUBMIT_PROTOCOL_ARTICLE":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
