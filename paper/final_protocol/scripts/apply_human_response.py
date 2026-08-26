#!/usr/bin/env python3
"""Apply parsed questionnaire answers (human_answers.generated.yaml) to every
submission-facing file.

Default mode previews a diff; --apply writes. Refuses to run when the parsed
file is INCOMPLETE or carries unanswered clarifications. Never auto-approves
authorship, licenses, release, or submission: those exist only as explicit
YES answers from the author, and contribution-category suggestions are marked
SUGGESTED until --confirm-credit is passed.
"""
from __future__ import annotations

import argparse
import difflib
import json
import subprocess
import sys
from pathlib import Path

FINAL = Path(__file__).resolve().parents[1]
GENERATED = FINAL / "human_answers.generated.yaml"
sys.path.insert(0, str(FINAL / "scripts"))

from apply_human_answers import (  # noqa: E402
    LICENSE_CCBY_NOTICE,
    LICENSE_MIT,
    corresponding_author,
    load_yaml,
    update_citation_cff,
    update_main_tex,
    update_release_status,
)
from validate_human_answers import MiniYaml  # noqa: E402


def validate_or_die() -> dict:
    data = load_yaml(GENERATED)
    if not isinstance(data, dict) or data.get("complete") is not True:
        problems = data.get("clarifications", ["generated file missing or incomplete"])
        print(json.dumps({"status": "BLOCKED", "clarifications": problems}, indent=1))
        raise SystemExit(2)
    if data.get("ai_use", {}).get("ip_tool_terms_confirmation") is None:
        print(json.dumps({"status": "BLOCKED", "clarifications": [
            "Please confirm you used the AI tools in compliance with their terms and "
            "with confidentiality/IP obligations (yes/no)."
        ]}, indent=1))
        raise SystemExit(2)
    return data


def update_contributions(data: dict, changes: list[str]) -> tuple[str, str]:
    path = FINAL / "author_contributions.md"
    original = path.read_text(encoding="utf-8")
    authors = data["authors"]
    suggested = data["credit_roles"]["suggested_from_prose"]
    approved = "--confirm-credit" in sys.argv
    lines = ["# Author contributions (CRediT)", ""]
    for author in authors:
        roles = suggested.get(author["publication_name"], [])
        marker = "" if approved else " *(SUGGESTED - approve in your reply)*"
        lines.append(f"- {author['publication_name']}: "
                     f"{', '.join(r.replace('_', ' ') for r in roles)}{marker}")
    lines += [
        "",
        "All listed authors meet contributor standards per the author's questionnaire",
        "answer 7. AI tools are not credited as authors or roles; their assistance is",
        "disclosed separately.",
    ]
    text = "\n".join(lines) + "\n"
    if text != original:
        changes.append("author_contributions.md rewritten from answer 7")
    return original, text


def update_simple_files(data: dict, changes: list[str]) -> list[tuple[str, str, str]]:
    previews = []
    corr = corresponding_author(data["authors"])

    conflicts_path = FINAL / "conflict_of_interest.md"
    original = conflicts_path.read_text(encoding="utf-8")
    text = (
        "# Competing-interests statement\n\n"
        + data["conflicts"]["final_statement"] + "\n\n"
        + ("Details: " + data["conflicts"]["details"] if data["conflicts"]["details"]
           and data["conflicts"]["details"].lower() not in {"none", "n/a"} else "")
    )
    previews.append((str(conflicts_path), original, text.rstrip() + "\n"))
    changes.append("conflict_of_interest.md from answer 9")

    ack = data["acknowledgments"]
    ack_text = (
        "# Acknowledgments\n\n"
        + (ack["final_text"] if ack["final_text"] != "NONE"
           else "No additional acknowledgments.")
    )
    previews.append((str(FINAL / "acknowledgments.md"), "", ack_text + "\n"))
    changes.append("acknowledgments.md from answer 10")

    ai_path = FINAL / "ai_disclosure.md"
    original = ai_path.read_text(encoding="utf-8")
    extra = ""
    if data["ai_use"]["other_tools"] not in ("NONE", ""):
        extra = ("\n\n## Additional tools confirmed by the author\n\n"
                 + data["ai_use"]["other_tools"] + "\n")
    if original.rstrip().endswith("obligations.") or "Policy refresh" in original:
        new = original.rstrip() + extra
    else:
        new = original + extra
    previews.append((str(ai_path), original, new))
    changes.append("ai_disclosure.md updated from answer 12")

    overlap = data["overlap"]
    overlap_text = (
        "# Prior/overlapping disclosure (approved language)\n\n"
        + overlap["cover_letter_disclosure_text"] + "\n"
        + ("Public writeups: " + str(overlap["public_writeups"]) + "\n"
           if overlap["public_writeups"] != "NONE" else "")
    )
    previews.append((str(FINAL / "submission_bundle_draft/overlap_disclosure.txt"),
                     Path(FINAL / "submission_bundle_draft/overlap_disclosure.txt").read_text()
                     if (FINAL / "submission_bundle_draft/overlap_disclosure.txt").is_file() else "",
                     overlap_text))
    changes.append("overlap disclosure from answer 11")

    cover_path = FINAL / "submission_bundle_draft/cover_letter.txt"
    if cover_path.is_file():
        original = cover_path.read_text(encoding="utf-8")
        text = original
        text = text.replace(
            "[Corresponding-author name, email, and ORCID transcribed from human_answers.yaml]",
            f"{corr['publication_name']}\n{corr['email']}\nORCID: "
            + (corr.get("orcid", "") or "to be linked at submission"))
        text = text.replace(
            "Overlap disclosure: [exact approved sentence(s) transcribed from "
            "human_answers.yaml at apply time].",
            "Overlap disclosure: " + overlap["cover_letter_disclosure_text"])
        text = text.replace(
            "Suggested reviewers: [human-approved candidates or 'omitted' - "
            "transcribed from human_answers.yaml at apply time].",
            "Suggested reviewers: omitted.")
        previews.append((str(cover_path), original, text))
        changes.append("cover letter personalized")
    return previews


def update_deviation_and_status(data: dict, changes: list[str]) -> None:
    d03 = data["d03"]
    rr = data["release_rights"]
    status_path = FINAL / "release/RELEASE_STATUS.json"
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    if rr["code_redistribution_approved"] and rr["processed_data_redistribution_approved"]:
        payload["license"] = f"{rr['code_license']} (code); {rr['data_docs_license']} (processed data/docs)"
        changes.append("RELEASE_STATUS.json license recorded")
    if rr["archive_authorized"] and rr["doi"]:
        payload["doi"] = rr["doi"]
        payload["release_status"] = "ARCHIVE_AUTHORIZED_HUMAN_APPROVED"
        changes.append("RELEASE_STATUS.json archive + DOI recorded")
    status_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    dev_path = FINAL / "supplement/PROTOCOL_DEVIATIONS_FINAL_DRAFT.md"
    original = dev_path.read_text(encoding="utf-8")
    if d03["deviation_record_approved"]:
        disposition = (
            f"\n\n---\n**Transcribed human disposition:** positions_never_recorded="
            f"{d03['positions_never_recorded_confirmed']}; actor_counts_recovered="
            f"{d03['actor_counts_recovered_confirmed']}; timings_recovered="
            f"{d03['timings_recovered_confirmed']}; redistribution_approved="
            f"{d03['redistribution_approved']}; date={d03['disposition_date']}; "
            f"signature_text={d03['signature_text']}\n"
        )
        if "Transcribed human disposition" not in original:
            dev_path.write_text(original.rstrip("\n") + disposition, encoding="utf-8")
            changes.append("D03 deviation record transcribed and dated")

    if (FINAL / "public_release_candidate").is_dir() and rr["code_redistribution_approved"]:
        year, holder = "2026", "; ".join(a["publication_name"] for a in data["authors"])
        (FINAL / "public_release_candidate/LICENSE.code").write_text(
            LICENSE_MIT.replace("[AUTHOR NAME(S) REQUIRE HUMAN CONFIRMATION]", holder)
            .replace("{year}", year).replace("{holder}", holder), encoding="utf-8")
        (FINAL / "public_release_candidate/LICENSE.data-docs").write_text(
            LICENSE_CCBY_NOTICE.replace("[AUTHOR NAME(S) REQUIRE HUMAN CONFIRMATION]", holder)
            .replace("{year}", year).replace("{holder}", holder), encoding="utf-8")
        changes.append("approved license files written into release candidate")


def update_archive_metadata(data: dict, changes: list[str]) -> None:
    rr = data["release_rights"]
    path = FINAL / "ARCHIVE_METADATA_TEMPLATE.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if rr["archive_authorized"]:
        payload["creators"] = [
            {"name": a["publication_name"],
             "orcid": a.get("orcid", "") if a.get("orcid") != "DECLINE" else ""}
            for a in data["authors"]
        ]
        payload["license"] = {"code": rr["code_license"], "data_docs": rr["data_docs_license"]}
        payload["publication_date"] = data["meta"]["filled_date"]
        if rr["doi"]:
            payload["doi"] = rr["doi"]
        changes.append("archive metadata creators/licenses filled")


def update_submission_metadata(data: dict, changes: list[str]) -> None:
    path = FINAL / "SUBMISSION_METADATA_DRAFT.yaml"
    original = path.read_text(encoding="utf-8")
    corr = corresponding_author(data["authors"])
    text = original
    replacements = {
        "placeholders: \"[transcribed from human_answers.yaml authors list — name, order, corresponding flag]\"":
            f"authors: {'; '.join(a['publication_name'] for a in data['authors'])} (corresponding: {corr['publication_name']})",
        "placeholders: \"[institution-level affiliation(s) + postal address from human_answers.yaml]\"":
            f"affiliations: {data['authors'][0]['affiliation']}",
        "placeholder: \"[name + email from human_answers.yaml]\"":
            f"corresponding_author: {corr['publication_name']} <{corr['email']}>",
        "placeholder: \"[corresponding-author ORCID REQUIRED by APS; coauthor ORCIDs optional]\"":
            f"orcid: {corr.get('orcid', '') or 'to be linked at submission'}",
        "statement_placeholder: \"[from human_answers.yaml funding.statement]\"":
            f"statement: {data['funding']['statement']}",
        "statement_placeholder: \"[from human_answers.yaml conflicts.final_statement]\"":
            f"statement: {data['conflicts']['final_statement']}",
    }
    for old, new in replacements.items():
        if old in text:
            text = text.replace(old, new)
    das = data.get("data_availability_version", "B")
    text = text.replace("current_version: B", f"current_version: {das}")
    if text != original:
        changes.append("submission metadata draft filled")
    (FINAL / "SUBMISSION_METADATA_DRAFT.yaml").write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diff", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-credit", action="store_true",
                        help="write suggested contribution categories as final")
    args = parser.parse_args()

    data = validate_or_die()
    changes: list[str] = []
    previews: list[tuple[str, str, str]] = []

    old_tex, new_tex = update_main_tex(data, changes)
    previews.append((str(FINAL / "main.tex"), old_tex, new_tex))

    status_new, status_old = update_release_status(data, changes)
    previews.append((str(FINAL / "release/RELEASE_STATUS.json"), status_old, status_new))

    cff_old, cff_new = update_citation_cff(data, changes)
    previews.append((str(FINAL / "release/CITATION.cff"), cff_old, cff_new))

    old_contrib, new_contrib = update_contributions(data, changes)
    previews.append((str(FINAL / "author_contributions.md"), old_contrib, new_contrib))

    previews.extend(update_simple_files(data, changes))
    update_deviation_and_status(data, changes)
    update_archive_metadata(data, changes)
    update_submission_metadata(data, changes)

    if args.apply:
        (FINAL / "main.tex").write_text(new_tex, encoding="utf-8")
        (FINAL / "release/RELEASE_STATUS.json").write_text(status_new, encoding="utf-8")
        (FINAL / "release/CITATION.cff").write_text(cff_new, encoding="utf-8")
        for path_str, _, new in previews[3:]:
            Path(path_str).write_text(new, encoding="utf-8")
        print(json.dumps({"status": "APPLIED", "changes": changes,
                          "credit_approval": "final" if args.confirm_credit else "SUGGESTED (re-run with --confirm-credit to finalize)"},
                         indent=1))
        print("NEXT: machine_finalize.py, then rebuild the submission bundle.")
    else:
        for path_str, old, new in previews:
            diff = difflib.unified_diff(old.splitlines(), new.splitlines(),
                                        fromfile=path_str, tofile=path_str, lineterm="")
            print("\n".join(list(diff)[:60]))
        print(json.dumps({"status": "PREVIEW_ONLY", "intended_changes": changes}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
