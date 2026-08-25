#!/usr/bin/env python3
"""Build the final sentence-level claim ledger and reject unbound claims."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
FINAL = SCRIPT.parents[1]
ROOT = SCRIPT.parents[3]
PROTOCOL_COMMIT = "803257f102232763fc88d28c14b668f9b62eb277"
SCOPE_AUDIT = FINAL / "source_data/claim_scope_audit.json"
SCOPE_TYPES = {
    "quantitative", "comparative", "novelty", "procedural", "rights", "contribution",
}
FIELDS = [
    "claim_id", "exact_sentence", "manuscript_location", "claim_type",
    "status", "raw_source", "source_sha256", "protocol_commit",
    "analysis_script", "analysis_script_sha256", "command", "analysis_unit",
    "sample_size", "estimate", "interval_or_test", "assumptions",
    "limitations", "prior_work_overlap", "allowed_wording",
    "forbidden_wording", "machine_verified", "human_verified", "notes",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def strict_json_bytes(value: Any) -> bytes:
    """Return the single canonical JSON representation used by this builder."""
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def strip_tex_comment(line: str) -> str:
    """Strip an unescaped TeX comment while preserving escaped percent signs."""
    for index, character in enumerate(line):
        if character != "%":
            continue
        slash_count = 0
        cursor = index - 1
        while cursor >= 0 and line[cursor] == "\\":
            slash_count += 1
            cursor -= 1
        if slash_count % 2 == 0:
            return line[:index]
    return line


def command_payload(lines: list[str], start: int, command: str) -> tuple[str, int]:
    """Extract a possibly multiline braced command payload without rendering TeX."""
    line = lines[start]
    marker = f"\\{command}{{"
    offset = line.find(marker)
    if offset < 0:
        raise ValueError(f"missing {marker} at line {start + 1}")
    text = line[offset + len(marker):]
    parts: list[str] = []
    depth = 1
    index = start
    while True:
        cursor = 0
        segment: list[str] = []
        while cursor < len(text):
            character = text[cursor]
            escaped = cursor > 0 and text[cursor - 1] == "\\"
            if character == "{" and not escaped:
                depth += 1
            elif character == "}" and not escaped:
                depth -= 1
                if depth == 0:
                    parts.append("".join(segment))
                    return "\n".join(parts), index
            segment.append(character)
            cursor += 1
        parts.append("".join(segment))
        index += 1
        if index >= len(lines):
            raise ValueError(f"unterminated {marker} beginning at line {start + 1}")
        text = lines[index]


def split_sentences(text: str) -> list[str]:
    """Split prose conservatively while retaining exact normalized TeX text."""
    value = normalize(text)
    if not value:
        return []
    # The manuscript uses sentence-final punctuation.  A new sentence must
    # begin with an uppercase letter, opening quote, or a TeX macro.  This
    # avoids splitting decimals and most abbreviations without pretending to
    # be a natural-language parser.
    pieces = re.split(r"(?<=[.!?])\s+(?=(?:[A-Z]|``|\\[A-Z]))", value)
    return [normalize(piece) for piece in pieces if normalize(piece)]


def extract_prose_sentences(manuscript_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Enumerate narrative/caption sentences and explicit non-prose exclusions."""
    lines = manuscript_path.read_text(encoding="utf-8").splitlines()
    records: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    section = "Abstract"
    in_document = False
    skipped_environment: str | None = None
    paragraph: list[str] = []
    paragraph_line = 0

    def flush() -> None:
        nonlocal paragraph, paragraph_line
        if not paragraph:
            return
        for sentence in split_sentences("\n".join(paragraph)):
            records.append({
                "source_line": paragraph_line,
                "section": section,
                "kind": "narrative",
                "exact_sentence": sentence,
            })
        paragraph = []
        paragraph_line = 0

    structural = re.compile(
        r"^\\(?:begin|end|label|includegraphics|centering|input|bibliography|"
        r"bibliographystyle|maketitle|appendix|clearpage|widetext|vspace|newpage)\b"
    )
    skipped = {"equation", "equation*", "align", "align*", "gather", "gather*", "tabular", "tabularx"}
    index = 0
    while index < len(lines):
        raw = strip_tex_comment(lines[index]).rstrip()
        stripped = raw.strip()
        line_number = index + 1
        if stripped == "\\begin{document}":
            in_document = True
            index += 1
            continue
        if not in_document or stripped == "\\end{document}":
            flush()
            index += 1
            continue

        if skipped_environment:
            if stripped.startswith(f"\\end{{{skipped_environment}}}"):
                skipped_environment = None
            index += 1
            continue
        begin = re.match(r"\\begin\{([^}]+)\}", stripped)
        if begin and begin.group(1) in skipped:
            flush()
            skipped_environment = begin.group(1)
            exclusions.append({
                "source_line": line_number,
                "construct": f"{begin.group(1)} environment",
                "reason": "Displayed mathematics or tabular structure is not a prose sentence; equations and tables are independently generated and audited.",
            })
            index += 1
            continue

        heading = re.match(r"\\(?:section|subsection|subsubsection)\*?\{(.+)\}\s*$", stripped)
        if heading:
            flush()
            section = normalize(heading.group(1))
            index += 1
            continue
        if stripped == "\\begin{abstract}":
            flush()
            section = "Abstract"
            index += 1
            continue
        if stripped == "\\end{abstract}":
            flush()
            index += 1
            continue

        if "\\caption{" in raw:
            flush()
            payload, end_index = command_payload(lines, index, "caption")
            for sentence in split_sentences(payload):
                records.append({
                    "source_line": line_number,
                    "section": f"{section} — figure caption",
                    "kind": "caption",
                    "exact_sentence": sentence,
                })
            index = end_index + 1
            continue

        input_match = re.match(r"\\input\{([^}]+)\}", stripped)
        if input_match:
            flush()
            exclusions.append({
                "source_line": line_number,
                "construct": f"input:{input_match.group(1)}",
                "reason": "The included artifact is generated macro or tabular data, not an evidentiary prose sentence; its values and inventory are checked by artifact, statistics, and release tests.",
            })
            index += 1
            continue
        if not stripped:
            flush()
            index += 1
            continue
        if structural.match(stripped) or stripped in {"\\preprint{APS Open Science Protocol Article}", "\\appendix"}:
            flush()
            index += 1
            continue
        if re.match(r"^\\(?:title|author|email|affiliation|date)\{", stripped):
            flush()
            index += 1
            continue

        if stripped.startswith("\\item"):
            stripped = stripped[len("\\item"):].strip()
        if not paragraph:
            paragraph_line = line_number
        paragraph.append(stripped)
        index += 1
    flush()
    return records, exclusions


SCOPE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("rights", (
        r"\bright(?:s|sholder)?\b", r"\blicen[cs]", r"\bownership\b", r"redistribut",
        r"third[- ]party", r"\bdoi\b", r"\barchive\b", r"public(?:ly)? (?:release|available)",
        r"data availability", r"restricted materials?", r"permission", r"privacy",
    )),
    ("novelty", (
        r"\\cite\{", r"\bprior work\b", r"\bliterature\b", r"\bpreprints?\b", r"\bnovel(?:ty)?\b",
        r"\bfirst\b", r"\bunprecedented\b", r"\bestablished\b", r"\bcontribution boundary\b",
    )),
    ("quantitative", (
        r"\\(?:Preflight|Stress|Factorial|Historical|Primary|Representation|Training|Interaction|McNemar|Synthetic)[A-Za-z]*\{?\}?",
        r"(?<![A-Za-z\\])\d+(?:[.,]\d+)*(?:\\?%|\b)", r"\b(?:estimate|interval|quantile|rate|count|mismatch|executions?|clusters?|units?|rows?|strata|bootstrap|resampl|p[ -]?value|McNemar)\b",
        r"\bzero\b", r"\bboth signs\b",
    )),
    ("contribution", (
        r"\bwe (?:present|introduce|integrate|supply|provide)\b", r"\bthis (?:article|work|paper) (?:addresses|integrates|supplies|provides)\b",
        r"\btitle-level contribution\b", r"\bcontribution is\b",
    )),
    ("comparative", (
        r"\b(?:compar(?:e|ed|ing|ison)|contrast|difference|versus|between arms?|relative to|more than|less than|higher|lower|stronger|weaker|same|equal|identical|improve)\b",
        r"cross-arm", r"within-arm", r"A/A",
    )),
    ("procedural", (
        r"\b(?:protocol|procedure|workflow|method|implementation|stage|gate|rule|admission|audit|verify|verified|validation|test|suite|schema|manifest|hash|record|declare|freeze|frozen|require|reject|suppress|fail(?:s|ed)? closed|generate|compute|apply|define|classif|enumerat|input projection)\b",
        r"\b(?:schedule matching|execution repeatability|event alignment|analysis unit|seed-indexed|result independent|deterministic|synthetic)\b",
        r"\\texttt\{", r"python -m", r"SHA-256",
    )),
)


def classify_sentence(sentence: str) -> tuple[list[str], list[str]]:
    """Return every matched scope class and the exact deterministic rule labels."""
    types: list[str] = []
    rules: list[str] = []
    for claim_type, patterns in SCOPE_RULES:
        matched = [pattern for pattern in patterns if re.search(pattern, sentence, flags=re.IGNORECASE)]
        if matched:
            types.append(claim_type)
            rules.extend(f"{claim_type}:{pattern}" for pattern in matched)
    if not types:
        # Fail closed.  A protocol article can make an evidentiary assertion in
        # ordinary declarative language that a keyword list misses.  Treating
        # every residual narrative/caption sentence as procedural is
        # deliberately over-inclusive and prevents silent claim loss.
        types.append("procedural")
        rules.append("procedural:fail-closed-evidentiary-prose-catch-all")
    return types, rules


def automatic_sources(claim_types: list[str], section: str) -> str:
    """Choose conservative, existing evidence bundles for mechanically added rows."""
    if "rights" in claim_types:
        return "paper/final_protocol/supplement/RIGHTS_AND_ACCESS_AUDIT.md;paper/final_protocol/data_availability.md"
    if any(value in claim_types for value in ("novelty", "contribution", "comparative")):
        return "paper/final_protocol/NOVELTY_AUDIT.md;paper/final_protocol/NOVELTY_MATRIX.csv;paper/final_protocol/REFERENCE_AUDIT.csv"
    if "quantitative" in claim_types:
        return "paper/final_protocol/source_data/statistics_verification.json;paper/final_protocol/source_data/build_report.json"
    if "Artificial-intelligence" in section or "AI-assisted" in section:
        return "paper/final_protocol/ai_disclosure.md;paper/final_protocol/supplement/AI_USE_LOG.csv"
    return "paper/protocol/PEVL_PROSPECTIVE_PROTOCOL.md;paper/final_protocol/METHOD_ASSUMPTION_AUDIT.md"


def automatic_row(sentence: str, section: str, claim_types: list[str]) -> dict[str, str]:
    sentence_hash = hashlib.sha256(normalize(sentence).encode("utf-8")).hexdigest()
    primary = claim_types[0]
    item = row(
        f"AUTO-{sentence_hash[:16]}",
        sentence,
        section,
        automatic_sources(claim_types, section),
        status="VERIFIED_WITH_CAVEAT",
        assumptions="The exact sentence and cited evidence-file identities are machine bound; substantive interpretation still requires corresponding-author review.",
        limitations="Mechanical classification and file identity do not independently establish truth, legal authority, novelty, causality, or external validity.",
        allowed_wording="Only the exact, qualified manuscript sentence recorded in this row.",
        forbidden_wording="Any stronger causal, priority, universal, public-availability, or legal conclusion.",
        claim_type=primary,
        prior_work_overlap="Prior-work and contribution boundaries remain governed by NOVELTY_AUDIT.md and require human confirmation.",
        notes="Automatically added by the deterministic exhaustive prose-scope pass; matched classes: " + ", ".join(claim_types),
    )
    item["machine_verified"] = (
        "YES — exact sentence, deterministic scope classification, and evidence-file identities checked; substantive human verification not performed"
    )
    return item


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
    claim_type: str = "procedural",
    prior_work_overlap: str = "No priority claim; component overlap is documented in NOVELTY_AUDIT.md.",
    notes: str = "none",
) -> dict[str, str]:
    script_hash = sha256(ROOT / analysis_script) if analysis_script else "not applicable"
    return {
        "claim_id": claim_id,
        "exact_sentence": normalize(sentence),
        "manuscript_location": section,
        "claim_type": claim_type,
        "status": status,
        "raw_source": raw_source,
        "source_sha256": source_hashes(raw_source),
        "protocol_commit": PROTOCOL_COMMIT if any(
            marker in raw_source.lower()
            for marker in ("paper/data/", "paper/synthetic/", "protocol")
        ) else "not applicable",
        "analysis_script": analysis_script or "not applicable",
        "analysis_script_sha256": script_hash,
        "command": generation_command or "not applicable",
        "analysis_unit": analysis_unit,
        "sample_size": sample_size,
        "estimate": estimate,
        "interval_or_test": interval_or_test,
        "assumptions": assumptions,
        "limitations": limitations,
        "prior_work_overlap": prior_work_overlap,
        "allowed_wording": allowed_wording,
        "forbidden_wording": forbidden_wording,
        "machine_verified": "YES — source identity and exact manuscript sentence checked",
        "human_verified": "NO — corresponding-author sign-off required",
        "notes": notes,
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
            "This work integrates those components into an executable protocol for validating the pairing assumptions behind statistical comparisons in black-box stochastic agent evaluation and maps the evidence obtained to the paired claim that may be admitted.",
            "Introduction", "paper/final_protocol/NOVELTY_AUDIT.md;paper/final_protocol/NOVELTY_MATRIX.csv", status="VERIFIED_WITH_CAVEAT",
            assumptions="The fatal novelty test and source-by-source matrix support this integration boundary; the sentence is descriptive, not a priority claim.",
            limitations="The release is not legally public until rights and licensing are confirmed.",
            allowed_wording="We integrate established components in an executable black-box protocol.",
            forbidden_wording="first; novel; unprecedented; groundbreaking",
        ),
        row(
            "C003A",
            "Prior work supplies conditional CRN theory, structured random streams, trace preservation, deterministic testing, and event-keyed randomness.",
            "Introduction", "paper/final_protocol/NOVELTY_AUDIT.md;paper/final_protocol/NOVELTY_MATRIX.csv",
            status="VERIFIED", claim_type="contribution",
            assumptions="The audited sources are described only within their verified component contributions.",
            limitations="This sentence deliberately assigns the components to prior work and makes no priority claim.",
            allowed_wording="Established components are prior art; the contribution is their audited integration.",
            forbidden_wording="first; invented trace testing; invented event-keyed randomness",
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
            "C005A",
            "Rollout Cards preserves rollouts, declared views, reporting rules, and dropped-record manifests \\cite{masters2026rolloutcards}.",
            "Related work and contribution boundary", reference, status="VERIFIED",
            assumptions="The cited preprint is used for its declared evidence-record standard only.",
            limitations="It does not establish pairing validity for this case study.",
            allowed_wording="Rollout Cards preserves and structures agent evaluation evidence.",
            forbidden_wording="Rollout Cards validates same-seed stochastic coupling.",
            claim_type="prior_work",
        ),
        row(
            "C005B",
            "The trace-assurance framework of Paduraru, Bouruc, and Stefanescu uses Message--Action Traces for contracts, replay, fault injection, localization, and governance \\cite{paduraru2026traceassurance}.",
            "Related work and contribution boundary", reference, status="VERIFIED",
            assumptions="The official proceedings record and paper are authoritative.",
            limitations="Trace assurance is not represented as a same-seed claim-admission protocol.",
            allowed_wording="The framework supports trace contracts, replay, perturbation, localization, and governance.",
            forbidden_wording="The framework is equivalent to this admission engine.",
            claim_type="prior_work",
        ),
        row(
            "C005C",
            "AEVAL turns agent-workflow changes into deterministic evaluation-contract tests and preserves first-attempt evidence \\cite{anand2026aeval}.",
            "Related work and contribution boundary", reference, status="VERIFIED",
            assumptions="The current arXiv record and manuscript are used at preprint status.",
            limitations="Workflow determinism does not itself prove semantic stochastic coupling.",
            allowed_wording="AEVAL provides deterministic workflow contract tests.",
            forbidden_wording="AEVAL supplies this statistical pairing admission map.",
            claim_type="prior_work",
        ),
        row(
            "C005D",
            "These methods improve evidence preservation and workflow assurance, but none validates same-seed stochastic coupling through the within-arm/cross-arm distinction or maps a failed pairing gate to automatic suppression of a statistical claim.",
            "Related work and contribution boundary", "paper/final_protocol/NOVELTY_AUDIT.md;paper/final_protocol/NOVELTY_MATRIX.csv",
            status="VERIFIED_WITH_CAVEAT", claim_type="comparative",
            assumptions="The statement is limited to the three immediately preceding close works and the audit cutoff of 2026-08-24.",
            limitations="It is not a universal priority claim and must be rechecked if the sources change.",
            allowed_wording="The audited close works do not combine this within/cross distinction with automatic statistical suppression.",
            forbidden_wording="No prior work has ever considered pairing validation.",
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
            "C008A",
            "This executable bundle was created after acquisition as a conservative formalization of the prospectively frozen experiment-specific admission logic; it is not represented as having existed at the protocol commit, and the frozen rules remain authoritative.",
            "Pairing-assumption validation protocol — Executable admission map and formal properties",
            "paper/protocol/PEVL_PROSPECTIVE_PROTOCOL.md;paper/final_protocol/release_templates/protocol/admission_rules.json",
            status="VERIFIED_WITH_CAVEAT", claim_type="procedural",
            assumptions="Repository chronology and explicit formalization metadata are accurate.",
            limitations="The generic engine cannot retroactively become a prospectively frozen artifact.",
            allowed_wording="post-acquisition executable formalization; frozen experiment-specific rule authoritative",
            forbidden_wording="the generic engine was preregistered or frozen before acquisition",
        ),
        row(
            "C008B",
            "Observed outcomes, treatment estimates, intervals, $p$ values, and result favorability are outside its input projection.",
            "Pairing-assumption validation protocol — Executable admission map and formal properties",
            "paper/final_protocol/release_templates/protocol/admission_schema.json;paper/final_protocol/release_templates/pevl_bench/admission.py",
            status="VERIFIED", claim_type="admission_rule",
            analysis_script="paper/final_protocol/release_templates/pevl_bench/admission.py",
            generation_command="python -m pevl_bench admit examples/example_evidence.json",
            analysis_unit="one structurally valid evidence record", sample_size="all tested state vectors",
            assumptions="The schema and evaluator are the packaged implementation.",
            limitations="Human changes to rules would require a new audit and version.",
            allowed_wording="admission is result independent by input construction and property test",
            forbidden_wording="the observed effect determines admission",
        ),
        row(
            "C008C",
            "For any structurally valid evidence record, the implemented admission map is result independent, prerequisite monotone, failure dominant, projection scoped, deterministic, idempotent, and fail closed for unknown states.",
            "Pairing-assumption validation protocol — Admission-safety proposition",
            "paper/final_protocol/release_templates/pevl_bench/admission.py;paper/final_protocol/release_templates/tests/test_release.py",
            status="DERIVED_BY_CHECKED_SCRIPT", claim_type="admission_rule",
            analysis_script="paper/final_protocol/release_templates/tests/test_release.py",
            generation_command="python -B -m pytest -q -p no:cacheprovider",
            analysis_unit="evidence-state vector", sample_size="6^7 exhaustive state combinations plus malformed and tamper cases",
            assumptions="The declared schema, gate order, and claim ordering define the domain.",
            limitations="The proposition is about the implementation, not the scientific sufficiency of every possible future gate design.",
            allowed_wording="the seven implemented formal properties hold over the declared domain",
            forbidden_wording="the engine proves all possible admission systems safe",
        ),
        row(
            "C008D",
            "Checked property tests replace all result values, weaken every prerequisite, inject extreme favorable results after failures, remove trace-projection scope, repeat identical evaluations, exercise malformed and unknown inputs, and enumerate every combination of the six evidence states across seven gates.",
            "Pairing-assumption validation protocol — Admission-safety proposition",
            "paper/final_protocol/release_templates/tests/test_release.py",
            status="DERIVED_BY_CHECKED_SCRIPT", claim_type="procedural",
            analysis_script="paper/final_protocol/release_templates/tests/test_release.py",
            generation_command="python -B -m pytest -q -p no:cacheprovider",
            analysis_unit="test case and evidence-state vector", sample_size="6^7 exhaustive state combinations plus targeted mutations",
            assumptions="pytest completes without selection changes.",
            limitations="Tests establish conformance to the declared rules, not external validity.",
            allowed_wording="exhaustive declared-state and targeted property tests pass",
            forbidden_wording="testing proves the protocol universally correct",
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
            "An apparently favorable estimate failed the prespecified control gate, so the frozen rule suppressed the historical paired comparison.",
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
            "Of \\StressClusters{} clusters and \\StressExecutions{} executions, \\StressTraceMismatch{} clusters had a trace-projection disagreement (\\StressTracePct\\%; empirical 95\\% pooled whole-cluster bootstrap interval [\\StressTraceLowPct\\%, \\StressTraceHighPct\\%]).",
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
            "Because those rows recorded schedule, boundary seed, outcome, error, and decision count but not trace digests or semantic event identifiers, the rule did not admit trace-parity, event-aligned, counterfactual, or full-CRN wording.",
            "Claim-admission consequence", factorial, status="VERIFIED",
            analysis_script="paper/scripts/analyze_pevl.py",
            analysis_unit="factorial evaluation row", sample_size="2,000 common units per cell",
            assumptions="Raw rows report trace_mode=none and null digest fields.",
            limitations="Factorial repeatability is checked only on the captured record.",
            allowed_wording="factorial trace digest not captured",
            forbidden_wording="zero factorial trace mismatches; factorial trace parity",
        ),
        row(
            "C020",
            "The frozen rule therefore admitted a bounded seed-matched analysis of \\FactorialUnits{} common units per cell (\\FactorialGames{} engine games).",
            "Claim-admission consequence", factorial, status="DERIVED_BY_CHECKED_SCRIPT",
            analysis_script="paper/scripts/analyze_pevl.py",
            generation_command="python -B paper/scripts/analyze_pevl.py && python -B paper/final_protocol/scripts/verify_statistics.py",
            analysis_unit="paired unit within 10 opponent-by-order strata", sample_size="2,000 units per cell; 12,000 games", estimate="0 captured-record control mismatches",
            assumptions="Schedule, outcome, error, and decision fields satisfy the frozen gate.",
            limitations="No factorial trace, event alignment, or new-opponent inference.",
            allowed_wording="bounded seed-matched factorial admitted",
            forbidden_wording="fully coupled CRN factorial",
        ),
        row(
            "C020A",
            "Admission was determined from gate evidence before inspecting that result; replacing every outcome value while holding the evidence fixed leaves the admission decision unchanged.",
            "Claim-admission consequence",
            "paper/protocol/PEVL_PROSPECTIVE_PROTOCOL.md;paper/final_protocol/release_templates/tests/test_release.py",
            status="DERIVED_BY_CHECKED_SCRIPT", claim_type="admission_decision",
            analysis_script="paper/final_protocol/release_templates/tests/test_release.py",
            generation_command="python -B -m pytest -q -p no:cacheprovider",
            analysis_unit="admission evidence record", sample_size="outcome-replacement property cases",
            assumptions="Gate evidence and formal rule version remain fixed.",
            limitations="This does not establish that every scientific design choice was outcome blind.",
            allowed_wording="the implemented decision is invariant to replaced outcome fields",
            forbidden_wording="all research decisions were blinded",
        ),
        row(
            "C021",
            "The total fixed-package contrast was \\PrimaryEstimatePP{} \\pp{} with an empirical 95\\% paired-resampling interval [\\PrimaryLowPP{}, \\PrimaryHighPP{}].",
            "Claim-admission consequence", factorial, status="DERIVED_BY_CHECKED_SCRIPT",
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
            "Appendix — Secondary factorial details", factorial, status="DERIVED_BY_CHECKED_SCRIPT",
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
        row(
            "C026",
            "In the restricted-engine case study, the deterministic preflight found zero required trace, outcome, error, or decision-count mismatches across \\PreflightUnits{} arm--seed-condition units and \\PreflightExecutions{} executions.",
            "Abstract", preflight, status="DERIVED_BY_CHECKED_SCRIPT",
            analysis_script="paper/final_protocol/scripts/independent_statistics_audit.py",
            generation_command="python paper/final_protocol/scripts/independent_statistics_audit.py --check",
            analysis_unit="arm–seed-condition unit across three profiles", sample_size="1,000 units; 3,000 executions", estimate="zero required mismatches",
            assumptions="The complete frozen deterministic preflight battery is retained.",
            limitations="Scoped to tested artifacts, projection, and contexts.",
            allowed_wording="zero required mismatches in 3,000 deterministic executions",
            forbidden_wording="universal determinism",
            claim_type="quantitative",
        ),
        row(
            "C027",
            "A separate timed-search population produced complete recorded-trace-projection disagreements in \\StressTraceMismatch{}/\\StressClusters{} seed-condition clusters.",
            "Abstract", stress, status="DERIVED_BY_CHECKED_SCRIPT",
            analysis_script="paper/final_protocol/scripts/independent_statistics_audit.py",
            generation_command="python paper/final_protocol/scripts/independent_statistics_audit.py --check",
            analysis_unit="seed-condition cluster retaining four execution profiles", sample_size="200 clusters; 800 executions", estimate="99/200 disagreements",
            assumptions="The fixed timed-search population and declared trace projection are the target.",
            limitations="No population prevalence or unique causal attribution.",
            allowed_wording="99/200 exercised clusters disagreed",
            forbidden_wording="49.5% of all timed-search agents fail",
            claim_type="quantitative",
        ),
        row(
            "C028",
            "The restricted engine exposes neither semantic event identifiers nor event-keyed streams, so its evidence cannot establish cross-arm semantic event alignment.",
            "Abstract", protocol, status="VERIFIED_WITH_CAVEAT",
            assumptions="The documented observable interface and retained evidence are complete for this claim.",
            limitations="Unavailable evidence is not evidence that the internal events are misaligned.",
            allowed_wording="event alignment cannot be established from the available interface",
            forbidden_wording="event alignment is disproven",
            claim_type="limitation",
        ),
    ]
    claim_types = {
        "C001": "prior_work", "C002": "prior_work", "C003": "contribution",
        "C003A": "contribution", "C004": "publication_status", "C005": "prior_work",
        "C005A": "prior_work", "C005B": "prior_work", "C005C": "prior_work",
        "C005D": "comparative",
        "C006": "procedural", "C007": "limitation", "C008": "admission_rule",
        "C008A": "procedural", "C008B": "admission_rule", "C008C": "admission_rule",
        "C008D": "procedural",
        "C009": "artifact", "C010": "quantitative", "C011": "quantitative",
        "C012": "limitation", "C012A": "quantitative", "C012B": "limitation",
        "C013": "quantitative", "C014": "comparative", "C015": "admission_decision",
        "C016": "quantitative", "C016A": "quantitative", "C017": "quantitative",
        "C018": "quantitative", "C018A": "quantitative", "C019": "procedural",
        "C020": "admission_decision", "C020A": "admission_decision", "C021": "quantitative", "C022": "quantitative",
        "C022A": "quantitative", "C023": "AI_transparency", "C024": "rights",
        "C025": "rights", "C026": "quantitative", "C027": "quantitative", "C028": "limitation",
    }
    for item in rows:
        item["claim_type"] = claim_types.get(item["claim_id"], item["claim_type"])
    return rows


def main() -> int:
    manuscript_path = FINAL / "main.tex"
    manuscript = normalize(manuscript_path.read_text(encoding="utf-8"))
    prose, exclusions = extract_prose_sentences(manuscript_path)

    # Curated rows retain claim-specific analytical detail when their exact
    # sentence remains in the final manuscript.  Removed or rewritten prose is
    # not allowed to leave a stale ledger entry; the exhaustive pass below adds
    # every newly in-scope sentence deterministically.
    curated = [item for item in build_rows() if item["exact_sentence"] in manuscript]
    by_sentence = {item["exact_sentence"]: item for item in curated}
    scope_records: list[dict[str, Any]] = []
    for record in prose:
        sentence = record["exact_sentence"]
        claim_types, matched_rules = classify_sentence(sentence)
        audit_record = {
            "source_path": str(manuscript_path.relative_to(ROOT)),
            "source_line": record["source_line"],
            "section": record["section"],
            "kind": record["kind"],
            "sentence_sha256": hashlib.sha256(sentence.encode("utf-8")).hexdigest(),
            "exact_sentence": sentence,
            "scope": "IN_SCOPE" if claim_types else "OUTSIDE_SCOPE",
            "matched_claim_types": claim_types,
            "matched_rules": matched_rules,
        }
        if claim_types:
            if sentence not in by_sentence:
                by_sentence[sentence] = automatic_row(sentence, record["section"], claim_types)
            audit_record["claim_id"] = by_sentence[sentence]["claim_id"]
            audit_record["outside_scope_reason"] = None
        else:
            audit_record["claim_id"] = None
            audit_record["outside_scope_reason"] = (
                "No declared quantitative, comparative, novelty, procedural, rights, or contribution rule matched this exact prose sentence."
            )
        scope_records.append(audit_record)

    rows = sorted(by_sentence.values(), key=lambda item: item["claim_id"])
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
        if not item["human_verified"].startswith("NO"):
            raise ValueError(f"claim row prematurely reports human verification: {item['claim_id']}")
    output = FINAL / "claim_ledger.csv"
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    in_scope = [record for record in scope_records if record["scope"] == "IN_SCOPE"]
    outside_scope = [record for record in scope_records if record["scope"] == "OUTSIDE_SCOPE"]
    occurrence_counts = {
        claim_type: sum(claim_type in record["matched_claim_types"] for record in in_scope)
        for claim_type in sorted(SCOPE_TYPES)
    }
    scope_payload = {
        "schema_version": 1,
        "status": "PASS",
        "manuscript": str(manuscript_path.relative_to(ROOT)),
        "manuscript_sha256": sha256(manuscript_path),
        "builder": str(SCRIPT.relative_to(ROOT)),
        "builder_sha256": sha256(SCRIPT),
        "ledger": str(output.relative_to(ROOT)),
        "ledger_sha256": sha256(output),
        "scope_boundary": {
            "included": "Every complete sentence in main.tex narrative paragraphs and figure captions after \\begin{document}.",
            "excluded": "Displayed mathematics, generated macro inputs, and tabular cells are structured artifacts rather than evidentiary prose sentences; each exclusion is enumerated below and covered by equation, artifact, statistics, or release checks.",
            "classifier_categories": sorted(SCOPE_TYPES),
            "classification_precedence": [item[0] for item in SCOPE_RULES],
            "fail_closed_rule": "Any residual prose sentence that matches no keyword rule is treated as procedural and receives a ledger row.",
        },
        "counts": {
            "prose_sentence_occurrences": len(scope_records),
            "in_scope_occurrences": len(in_scope),
            "outside_scope_occurrences": len(outside_scope),
            "unique_ledger_rows": len(rows),
            "curated_rows_retained": len(curated),
            "automatic_rows": len(rows) - len(curated),
            "human_verified_yes": 0,
            "in_scope_occurrences_by_type": occurrence_counts,
        },
        "all_in_scope_bound": all(record.get("claim_id") in ids for record in in_scope),
        "all_outside_scope_explained": all(record.get("outside_scope_reason") for record in outside_scope),
        "records": scope_records,
        "excluded_structured_constructs": exclusions,
        "human_verification_boundary": "All claim_ledger.csv rows remain NO; this audit proves coverage and byte identity, not human comprehension or sign-off.",
    }
    SCOPE_AUDIT.parent.mkdir(parents=True, exist_ok=True)
    SCOPE_AUDIT.write_bytes(strict_json_bytes(scope_payload))
    print(
        f"wrote {len(rows)} claims ({len(curated)} curated, {len(rows) - len(curated)} automatic) "
        f"and audited {len(scope_records)} prose-sentence occurrences"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
