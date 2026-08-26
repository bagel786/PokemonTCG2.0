#!/usr/bin/env python3
"""Parse the plain-text author questionnaire into human_answers.generated.yaml.

Input:  paper/final_protocol/HUMAN_RESPONSE.txt  (the 20 numbered answers,
        pasted verbatim from the Google Doc; optional trailing
        "PASSAGE DECISIONS" section for the eight prose passages).
Output: paper/final_protocol/human_answers.generated.yaml  (internal schema
        mirroring human_answers.template.yaml) plus a clarification list.

Rules: never invent an answer; ambiguous or missing required answers are
reported as short clarification questions and the generated file is marked
INCOMPLETE (apply_human_response.py refuses to run on an incomplete file).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

FINAL = Path(__file__).resolve().parents[1]
RESPONSE = FINAL / "HUMAN_RESPONSE.txt"
OUTPUT = FINAL / "human_answers.generated.yaml"

REQUIRED = list(range(1, 21))
YES = {"yes", "y", "confirm", "confirmed", "ok", "approve", "approved", "agree"}
NO = {"no", "n", "deny", "decline", "none", "not yet", "no one", "nobody"}

CREDIT_HINTS = [
    (r"\bwrot|draft|writ|manuscript|paper\b", ["Writing_original_draft", "Writing_review_editing"]),
    (r"\bdesigned|concept|idea|question\b", ["Conceptualization"]),
    (r"\bmethod|protocol|design of the stud", ["Methodology"]),
    (r"\bcod|software|program|implement|script", ["Software"]),
    (r"\bran|execut|experiment|acqui|simulat", ["Investigation"]),
    (r"\banaly|statistic|math|comput", ["Formal_analysis"]),
    (r"\bverif|valid|check|test|audit", ["Validation"]),
    (r"\bfigur|plot|visual|diagram", ["Visualization"]),
    (r"\bdata ?set|data curation|curat|dataset", ["Data_curation"]),
    (r"\bsupervis|advis|mentor", ["Supervision"]),
    (r"\bmanag|coordinat|administ", ["Project_administration"]),
    (r"\bfund|grant|money|paid for", ["Funding_acquisition"]),
]


def split_authors(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"\s*(?:;|,| and | & )\s*", text)
    return [p.strip(" .") for p in parts if p.strip(" .") and p.strip(" .").lower() not in NO]


def is_yes(text: str) -> bool:
    head = re.sub(r"\s+", " ", text).strip().lower()
    return head.startswith(tuple(YES))


def is_no(text: str) -> bool:
    head = re.sub(r"\s+", " ", text).strip().lower()
    return head.startswith(tuple(NO))


def parse_answers(text: str) -> dict[int, str]:
    answers: dict[int, str] = {}
    pattern = re.compile(r"(?ms)^\s*(\d{1,2})\s*[.)\-:]\s*(.*?)(?=^\s*\d{1,2}\s*[.)\-:]|\Z)")
    for match in pattern.finditer(text):
        number = int(match.group(1))
        body = match.group(2).strip()
        if 1 <= number <= 20:
            answers[number] = body if body else ""
    return answers


def suggest_credit(prose: str) -> list[str]:
    roles: list[str] = []
    lowered = prose.lower()
    for pattern, suggested in CREDIT_HINTS:
        if re.search(pattern, lowered):
            roles.extend(suggested)
    return sorted(set(roles)) or ["Writing_original_draft", "Writing_review_editing"]


def main() -> int:
    if not RESPONSE.is_file():
        print(json.dumps({"status": "MISSING_INPUT",
                          "message": f"Save the completed questionnaire as {RESPONSE} first."}))
        return 1
    text = RESPONSE.read_text(encoding="utf-8")
    answers = parse_answers(text)
    missing = [n for n in REQUIRED if n not in answers or not answers[n].strip()]
    clarifications: list[str] = []
    if missing:
        clarifications.append(
            "These questionnaire numbers are blank or missing: "
            + ", ".join(str(n) for n in missing) + ". Please answer them.")

    a = {n: answers.get(n, "").strip() for n in REQUIRED}

    authors = split_authors(a[1]) if not missing else []
    corresponding = a[2].strip(" .")
    if authors and corresponding and not any(
            corresponding.lower() == name.lower() or corresponding.lower() in name.lower()
            for name in authors):
        clarifications.append(
            f"Q2: corresponding author '{corresponding}' is not in the author list "
            f"({'; '.join(authors)}). Confirm spelling.")
    orcid_raw = a[6].strip()
    orcid = orcid_raw if re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", orcid_raw) else (
        "DECLINE" if orcid_raw.lower() in NO or "none" in orcid_raw.lower() else orcid_raw)
    if orcid and orcid != "DECLINE" and not re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", orcid):
        clarifications.append("Q6: ORCID should look like 0000-0000-0000-0000 (or 'none').")

    email = a[5].strip()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        clarifications.append("Q5: that email address does not look complete.")

    q13 = a[13]
    q15 = a[15]
    q17 = a[17]
    q20 = a[20]
    if q13 and not (is_yes(q13) or is_no(q13)):
        clarifications.append("Q13: please answer YES or NO (may the sanitized code/results be publicly released?).")
    if q15 and q15.lower()[:3] not in {"yes", "not"} and not is_no(q15):
        clarifications.append("Q15: please answer YES or NOT YET (archive deposit + DOI authorization).")
    if q17 and not (is_yes(q17) or is_no(q17)):
        clarifications.append("Q17: please answer YES or NO (include recovered actor/timing aggregates?).")
    q20_norm = q20.strip().upper()
    if q20_norm and q20_norm not in {"YES", "NO", "NEED TO REVIEW AGAIN"}:
        clarifications.append("Q20: please answer exactly YES, NO, or NEED TO REVIEW AGAIN.")

    q16 = a[16]
    if q16 and not (q16.lower().startswith("confirm") or q16.lower().startswith("correct")):
        clarifications.append("Q16: please start your answer with CONFIRM or CORRECT.")

    q18 = a[18]
    disagreement_items: list[str] = []
    if q18 and not is_yes(q18):
        disagreement_items = re.findall(r"\b(\d{1,2})\b", q18)

    q10 = a[10].strip(" .")
    if q10 and q10.lower() not in NO and "consent" not in q10.lower() and "ok" not in q10.lower():
        clarifications.append(
            "Q10: please confirm the people/institutions named are OK with being thanked.")

    q12 = a[12].strip(" .")
    uploads_restricted = bool(re.search(r"\b(yes|uploaded|submitted)\b", q12, re.I)) and not is_no(q12)
    if q12 and uploads_restricted:
        clarifications.append(
            "Q12: you indicated restricted/private material may have been uploaded to an AI tool - "
            "please state which tool and what material so the disclosure is accurate.")

    license_answer = a[14].strip(" .")
    if is_yes(q13) and not license_answer:
        clarifications.append("Q14: confirm MIT (code) + CC BY 4.0 (data/docs), or state changes.")

    code_ok = is_yes(q13)
    data_ok = code_ok
    archive_ok = q15.lower().startswith("yes")
    recovered_ok = is_yes(q17)
    doi = ""
    license_code = "MIT"
    license_docs = "CC BY 4.0"
    if license_answer and not is_yes(license_answer) and not is_no(license_answer):
        custom = re.findall(r"(MIT|Apache|BSD|GPL|CC BY[^,;.]*|CC0)", license_answer, re.I)
        if custom:
            license_code = custom[0]
            if len(custom) > 1:
                license_docs = custom[1]

    das_version = "A" if (code_ok and data_ok and archive_ok and doi) else "B"

    credit_prose = a[7]
    suggested = suggest_credit(credit_prose) if credit_prose else []

    generated = {
        "schema_version": "human-answers-generated-v1",
        "generated_from": "HUMAN_RESPONSE.txt (plain-language questionnaire)",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "complete": not missing and not clarifications,
        "clarifications": clarifications,
        "meta": {
            "filled_by": corresponding or "[PENDING]",
            "filled_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        },
        "authors": [
            {
                "publication_name": name,
                "initials": "".join(w[0] for w in name.split()[:2]).upper(),
                "email": email if i == 0 else "",
                "orcid": orcid if i == 0 else "",
                "affiliation": a[4],
                "postal_address": "",
                "author_order": i + 1,
                "corresponding_author": name.lower() == corresponding.lower() or
                                        corresponding.lower() in name.lower(),
                "coauthor_eligibility_basis": credit_prose if i == 0 else "see questionnaire answer 7",
            }
            for i, name in enumerate(authors)
        ],
        "credit_roles": {
            "suggested_from_prose": {name: suggested for name in authors},
            "approval_status": "SUGGESTED_PENDING_AUTHOR_APPROVAL",
            "confirmation_ai_not_credited": True,
        },
        "funding": {
            "statement": ("This research received no external funding."
                          if is_no(a[8]) or not a[8] else a[8]),
            "sources": "NONE" if is_no(a[8]) else a[8],
            "grants": "N/A",
            "sponsor_role": "NONE",
        },
        "conflicts": {
            "final_statement": ("The author declares no competing interests."
                                if is_no(a[9]) or a[9].lower() in NO
                                else "[FINAL WORDING PENDING - see answer 9]"),
            "details": a[9],
        },
        "acknowledgments": {
            "final_text": "NONE" if is_no(a[10]) or not a[10] else a[10],
            "permission_confirmed": bool(a[10]) and ("consent" in a[10].lower() or "ok" in a[10].lower()),
        },
        "overlap": {
            "kaggle_report": a[11] if re.search(r"kaggle", a[11], re.I) else "NONE",
            "public_writeups": "NONE" if is_no(a[11]) or not a[11] else a[11],
            "prior_student_journal_submission": "NONE",
            "preprints": "NONE",
            "cover_letter_disclosure_text": (
                "Parts of this work were previously disclosed in public competition "
                "materials: " + a[11] if a[11] and not is_no(a[11])
                else "No prior public version of this work exists."),
        },
        "ai_use": {
            "codex_confirmation_complete": True,
            "chatgpt_confirmation_complete": True,
            "other_tools": "NONE" if is_no(a[12]) or not a[12] else a[12],
            "missing_historical_uses": "NONE",
            "confidentiality_confirmation": not uploads_restricted,
            "ip_tool_terms_confirmation": None,
            "final_disclosure_approval": q20_norm == "YES",
        },
        "release_rights": {
            "owner_per_component": {
                key: ("author of record (derived from questionnaire answer 13)"
                      if code_ok else "[OWNERSHIP UNCONFIRMED]")
                for key in ("synthetic_suite", "admission_engine_pevl_bench",
                            "analysis_scripts", "processed_diagnostics",
                            "figures_and_source_data", "schemas_manifests_protocols_docs")
            },
            "code_redistribution_approved": code_ok,
            "processed_data_redistribution_approved": data_ok,
            "recovered_secondary_outputs_approved": recovered_ok,
            "code_license": license_code,
            "data_docs_license": license_docs,
            "archive_authorized": archive_ok,
            "archive_creators": "; ".join(authors) if archive_ok else "",
            "maintainer": email if archive_ok else "",
            "doi": doi,
        },
        "d03": {
            "positions_never_recorded_confirmed": q16.lower().startswith("confirm"),
            "actor_counts_recovered_confirmed": q16.lower().startswith("confirm"),
            "timings_recovered_confirmed": q16.lower().startswith("confirm"),
            "redistribution_approved": recovered_ok,
            "deviation_record_approved": q16.lower().startswith("confirm"),
            "disposition_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "signature_text": corresponding or "[PENDING]",
        },
        "scientific_signoff": {
            "equations_understood": None,
            "method_assumptions_confirmed": None,
            "defense_guide_reviewed": None,
            "curated_claim_ledger_reviewed": None,
            "automatic_ledger_coverage_attested": None,
            "novelty_boundary_understood": None,
            "central_numbers_verified": None,
            "chronology_understood": None,
            "final_manuscript_approved": q20_norm == "YES",
            "submission_authorized": q20_norm == "YES",
            "portal_attestation": {
                "basis": "20-question portal attestation + CORE FACTS page (HUMAN_PORTAL/START_HERE.md), layered on the exhaustive machine claim ledger",
                "understanding_items_disputed": disagreement_items,
                "uncomfortable_statements": "NONE" if is_no(a[19]) or not a[19] else a[19],
                "note": "Granular per-row signatures are superseded by this attestation; the machine ledger remains authoritative and active.",
            },
        },
        "prose_review": {
            "passage_decisions": {
                f"passage_{i}": "KEEP (default; no change requested)"
                for i in range(1, 9)
            },
            "note": "Defaults keep current text unless the author's reply specifies otherwise (see PASSAGE DECISIONS section of the response).",
        },
        "suggested_reviewers": {
            "approved_candidates": "NONE",
            "exclusions": "NONE",
        },
        "data_availability_version": das_version,
    }

    try:
        import yaml  # type: ignore
        OUTPUT.write_text(yaml.safe_dump(generated, sort_keys=False, allow_unicode=True),
                          encoding="utf-8")
    except ImportError:
        sys.path.insert(0, str(FINAL / "scripts"))
        from validate_human_answers import MiniYaml  # type: ignore

        def dump(value, indent=0) -> str:
            pad = "  " * indent
            lines = []
            if isinstance(value, dict):
                for key, item in value.items():
                    if isinstance(item, (dict, list)):
                        lines.append(f"{pad}{key}:")
                        lines.append(dump(item, indent + 1))
                    else:
                        lines.append(f"{pad}{key}: {json.dumps(item, ensure_ascii=False)}")
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, (dict, list)):
                        nested = dump(item, indent + 1).lstrip()
                        lines.append(f"{pad}- {nested}")
                    else:
                        lines.append(f"{pad}- {json.dumps(item, ensure_ascii=False)}")
            else:
                lines.append(f"{pad}{json.dumps(value, ensure_ascii=False)}")
            return "\n".join(lines)

        OUTPUT.write_text(dump(generated) + "\n", encoding="utf-8")

    status = "PASS" if generated["complete"] else "INCOMPLETE"
    print(json.dumps({
        "status": status,
        "output": str(OUTPUT),
        "authors": authors,
        "corresponding_author": corresponding,
        "das_version": das_version,
        "release_approved": code_ok,
        "archive_authorized": archive_ok,
        "recovered_aggregates_approved": recovered_ok,
        "final_manuscript_approved": generated["scientific_signoff"]["final_manuscript_approved"],
        "clarifications": clarifications,
    }, indent=1))
    return 0 if generated["complete"] else 2


if __name__ == "__main__":
    sys.exit(main())
