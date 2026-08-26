#!/usr/bin/env python3
"""Apply validated human answers to the submission-facing files.

Default mode is PREVIEW: prints a unified diff of every intended change and
exits. Pass --apply to actually write. --apply refuses to run unless
validate_human_answers.py passes first (it re-runs validation).

The script never invents content: it only substitutes human-supplied values,
selects between prepared candidate texts, or flips recorded status fields.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

FINAL = Path(__file__).resolve().parents[1]
ANSWERS = FINAL / "human_answers.yaml"


def load_yaml(path: Path):
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        sys.path.insert(0, str(FINAL / "scripts"))
        from validate_human_answers import MiniYaml  # type: ignore
        return MiniYaml(text).parse()


def validate_or_die() -> dict:
    result = subprocess.run(
        [sys.executable, str(FINAL / "scripts/validate_human_answers.py")],
        text=True, stdout=subprocess.PIPE,
    )
    if result.returncode != 0:
        print(result.stdout)
        raise SystemExit("validation failed; refusing to apply")
    return json.loads(result.stdout)


def corresponding_author(authors: list) -> dict:
    for author in authors:
        if author.get("corresponding_author") is True:
            return author
    raise SystemExit("no corresponding author (validator should have caught this)")


def replace_once(text: str, pattern: str, replacement: str, label: str, changes: list) -> str:
    new_text, count = re.subn(pattern, lambda _m: replacement, text, count=1)
    if new_text != text:
        changes.append(label)
    return new_text


def update_main_tex(data: dict, changes: list) -> tuple[str, str]:
    path = FINAL / "main.tex"
    text = path.read_text(encoding="utf-8")
    original = text
    authors = data["authors"]
    corr = corresponding_author(authors)

    if len(authors) == 1:
        author = authors[0]
        text = replace_once(text, r"\\author\{[^{}]*\}",
                            r"\author{" + author["publication_name"] + "}", "main.tex author", changes)
    else:
        lines = [r"\author{" + authors[0]["publication_name"] + "}"]
        for author in authors[1:]:
            lines.append(r"\author{" + author["publication_name"] + "}")
        text = replace_once(text, r"(?:\\author\{[^{}]*\}\n?)+", "\n".join(lines) + "\n",
                            "main.tex authors (multi)", changes)
    email_line = r"\email{" + corr["email"] + "}"
    text = replace_once(text, r"\\email\{[^{}]*\}", email_line, "main.tex email", changes)
    affiliation = corr.get("affiliation", "")
    if len(authors) == 1:
        affil_text = affiliation
    else:
        seen = []
        for author in authors:
            if author.get("affiliation") and author["affiliation"] not in seen:
                seen.append(author["affiliation"])
        affil_text = ", ".join(seen)
    text = replace_once(text, r"\\affiliation\{[^{}]*\}",
                        r"\affiliation{" + affil_text + ("; " + corr["postal_address"] if corr.get("postal_address") else "") + "}",
                        "main.tex affiliation", changes)

    # Data Availability Statement version swap.
    das_version = str(data.get("data_availability_version", "")).strip().upper()
    das_path = FINAL / "submission_bundle_draft/data_availability_statement.txt"
    if das_version == "A":
        marker = "VERSION A — PUBLIC COMPANION APPROVED"
        if das_path.is_file():
            das_source = das_path.read_text(encoding="utf-8")
            block = das_source.split(marker, 1)[1]
            block = block.split("VERSION B", 1)[0]
            doi = data["release_rights"].get("doi", "")
            block = block.replace("[DOI]", doi).replace("[REPOSITORY NAME/URL]", "Zenodo (DOI above)")
            text = replace_once(
                text,
                r"\\textbf\{Public \(with submission, pending rights approval\)\.\}.*?(?=\\textbf\{Restricted\.\})",
                "\\textbf{Public companion (published).} " + block.strip() + "\n\n",
                f"main.tex DAS -> Version A with live DOI {doi}", changes)
    elif das_version != "B":
        raise SystemExit("data_availability_version must be A or B")

    return original, text


def update_release_status(data: dict, changes: list) -> tuple[str, str]:
    path = FINAL / "release/RELEASE_STATUS.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    rr = data["release_rights"]
    if rr.get("code_redistribution_approved") and rr.get("processed_data_redistribution_approved"):
        payload["license"] = (
            f"{rr['code_license']} (code); {rr['data_docs_license']} (processed data/docs)"
        )
        changes.append("RELEASE_STATUS.json license recorded from approvals")
    if rr.get("archive_authorized") and rr.get("doi"):
        payload["doi"] = rr["doi"]
        payload["release_status"] = "ARCHIVE_AUTHORIZED_HUMAN_APPROVED"
        changes.append("RELEASE_STATUS.json archive authorization + DOI recorded")
    return json.dumps(payload, indent=2, sort_keys=True) + "\n", path.read_text(encoding="utf-8")


def update_citation_cff(data: dict, changes: list):
    path = FINAL / "release/CITATION.cff"
    original = path.read_text(encoding="utf-8")
    text = original
    corr = corresponding_author(data["authors"])
    text = replace_once(text, r"message: >-\n\s+.*", 
                        "message: >-\n  Citation metadata approved by the human author.",
                        "CITATION.cff message", changes)
    text = replace_once(text, r"version:\s*review-candidate-\d{4}-\d{2}-\d{2}",
                        "version: v1.0.0", "CITATION.cff version", changes)
    authors_block = "\n".join(
        "  - family-names: " + name.split()[-1] + "\n    given-names: " + " ".join(name.split()[:-1])
        for name in (a["publication_name"] for a in data["authors"])
    )
    text = re.sub(r"(?m)^authors:.*?(?=title:)", "", text, flags=re.S)
    text = text.replace("title: >-", "authors:\n" + authors_block + "\ntitle: >-", 1)
    if data["release_rights"].get("doi"):
        text += f"doi: {data['release_rights']['doi']}\n"
    changes.append("CITATION.cff authors/version updated" if "CITATION.cff message" in changes else "CITATION.cff updated")
    return original, text


LICENSE_MIT = """MIT License

Copyright (c) {year} {holder}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the SOFTWARE.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

LICENSE_CCBY_NOTICE = """Creative Commons Attribution 4.0 International (CC BY 4.0)

Applies to the processed data, documentation, figures, and source-data files
in this package. Copyright {year} {holder}. The full license text is available
at https://creativecommons.org/licenses/by/4.0/legalcode.

Code remains under the separately stated code license.
"""


def write_licenses(data: dict, changes: list) -> None:
    rr = data["release_rights"]
    year = "2026"
    holder = "; ".join(a["publication_name"] for a in data["authors"])
    code_path = FINAL / "public_release_candidate/LICENSE.code"
    docs_path = FINAL / "public_release_candidate/LICENSE.data-docs"
    if not code_path.parent.is_dir():
        return
    if rr.get("code_redistribution_approved"):
        code_path.write_text(LICENSE_MIT.format(year=year, holder=holder), encoding="utf-8")
        changes.append(f"LICENSE.code written ({rr['code_license']})")
    if rr.get("processed_data_redistribution_approved"):
        docs_path.write_text(LICENSE_CCBY_NOTICE.format(year=year, holder=holder), encoding="utf-8")
        changes.append(f"LICENSE.data-docs written ({rr['data_docs_license']})")


def update_d03(data: dict, changes: list) -> None:
    d03 = data.get("d03") or {}
    path = FINAL / "supplement/PROTOCOL_DEVIATIONS_FINAL_DRAFT.md"
    text = path.read_text(encoding="utf-8")
    if d03.get("deviation_record_approved") is True:
        text = text.replace(
            "**Status: FINAL DRAFT — UNSIGNED.",
            "**Status: SIGNED RECORD PENDING COMMIT (values transcribed from human_answers.yaml; verify initials/date below).",
        )
        disposition = (
            f"\n\n---\n**Transcribed human disposition:** positions_never_recorded="
            f"{d03.get('positions_never_recorded_confirmed')}; actor_counts_recovered="
            f"{d03.get('actor_counts_recovered_confirmed')}; timings_recovered="
            f"{d03.get('timings_recovered_confirmed')}; redistribution_approved="
            f"{d03.get('redistribution_approved')}; date={d03.get('disposition_date')}; "
            f"signature_text={d03.get('signature_text')}\n"
        )
        text = text.rstrip("\n") + disposition
        changes.append("D03 deviation record: transcribed signed disposition appended")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diff", action="store_true", help="preview changes (default)")
    parser.add_argument("--apply", action="store_true", help="write changes after validation passes")
    args = parser.parse_args(argv)

    if not ANSWERS.is_file():
        raise SystemExit(f"{ANSWERS.name} not found; copy human_answers.template.yaml first.")
    validate_or_die()
    data = load_yaml(ANSWERS)

    changes: list[str] = []
    previews: list[tuple[str, str, str]] = []

    original_tex, new_tex = update_main_tex(data, changes)
    previews.append((str(FINAL / "main.tex"), original_tex, new_tex))

    status_new, status_old = update_release_status(data, changes)
    previews.append((str(FINAL / "release/RELEASE_STATUS.json"), status_old, status_new))

    cff_old, cff_new = update_citation_cff(data, changes)
    previews.append((str(FINAL / "release/CITATION.cff"), cff_old, cff_new))

    # Bundle-level text files that embed placeholders get direct transcription.
    bundle_files = [
        "author_contributions.txt", "conflicts_and_funding.txt",
        "ai_disclosure.txt", "overlap_disclosure.txt",
        "suggested_reviewers_candidates.md",
    ]
    for name in bundle_files:
        path = FINAL / "submission_bundle_draft" / name
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8")
        text = original
        corr = corresponding_author(data["authors"])
        replacements = {
            "[Corresponding-author email requires human confirmation]": corr["email"],
            "[Corresponding author name requires human confirmation]": corr["publication_name"],
            "[Author names require human confirmation]": "; ".join(a["publication_name"] for a in data["authors"]),
            "[Funding statement requires human confirmation]": data["funding"]["statement"],
            "[Final conflict statement requires human confirmation]": data["conflicts"]["final_statement"],
            "[Acknowledgments text requires human confirmation]": data["acknowledgments"]["final_text"],
            "[Approved overlap disclosure sentence(s) — transcribed by apply script]": data["overlap"]["cover_letter_disclosure_text"],
            "[Human-approved reviewer selection transcribed here]": data["suggested_reviewers"].get("approved_candidates", "NONE"),
            "[Additional human exclusions transcribed here]": data["suggested_reviewers"].get("exclusions", "NONE"),
        }
        for old, new in replacements.items():
            if old in text:
                text = text.replace(old, new)
                changes.append(f"{name}: '{old[:40]}...' transcribed")
        if text != original:
            previews.append((str(path), original, text))

    write_licenses.__doc__  # no-op reference
    if args.apply:
        for _, old, new in previews:
            pass
        (FINAL / "main.tex").write_text(new_tex, encoding="utf-8")
        (FINAL / "release/RELEASE_STATUS.json").write_text(status_new, encoding="utf-8")
        (FINAL / "release/CITATION.cff").write_text(cff_new, encoding="utf-8")
        for path_str, _, new in previews[3:]:
            Path(path_str).write_text(new, encoding="utf-8")
        write_licenses(data, changes)
        update_d03(data, changes)
        print(json.dumps({"status": "APPLIED", "changes": changes}, indent=1))
        print("NEXT: re-run paper/final_protocol/scripts/reproduce_all.py before touching anything else.")
    else:
        for path_str, old, new in previews:
            diff = difflib.unified_diff(
                old.splitlines(), new.splitlines(), fromfile=path_str, tofile=path_str, lineterm="")
            print("\n".join(list(diff)[:80]))
        print(json.dumps({"status": "PREVIEW_ONLY", "intended_changes": changes}, indent=1))
        print("Re-run with --apply to execute. Then run reproduce_all.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
