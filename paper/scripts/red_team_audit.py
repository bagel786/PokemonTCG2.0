#!/usr/bin/env python3
"""Fail-closed final audit of manuscript, claims, figures, data, and release."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PAPER = ROOT / "paper"
RELEASE = ROOT / "release"
REQUIRED_CLAIM_FIELDS = [
    "claim_id", "manuscript_section", "proposed_claim", "status", "raw_source",
    "json_or_line_locator", "branch", "commit", "artifact_sha256",
    "calculation_script", "verified_value", "unit", "sample_size",
    "statistical_method", "limitations", "include_or_omit",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def citation_keys() -> set[str]:
    return set(re.findall(r"^@[^{]+\{([^,]+),", (PAPER / "references.bib").read_text(encoding="utf-8"), re.M))


def used_citations(tex: str) -> set[str]:
    keys = set()
    for group in re.findall(r"\\cite\{([^}]+)\}", tex):
        keys.update(key.strip() for key in group.split(","))
    return keys


def defined_commands() -> set[str]:
    commands = set()
    for path in (PAPER / "main.tex", PAPER / "results_macros.tex", PAPER / "diagnostic_macros.tex"):
        text = path.read_text(encoding="utf-8")
        commands.update(re.findall(r"\\newcommand\{\\([A-Za-z]+)\}", text))
    return commands


def main() -> int:
    checks = {}
    failures = []
    required = [
        "main.tex", "main.pdf", "references.bib", "results.tex", "results_macros.tex",
        "diagnostic_macros.tex", "claim_ledger.csv", "cover_letter.md",
        "data_availability.md", "ai_disclosure.md", "author_contributions.md",
        "conflict_of_interest.md", "limitations.md", "word_count.json",
    ]
    missing = [name for name in required if not (PAPER / name).is_file()]
    checks["required_paper_files"] = not missing
    if missing:
        failures.append(f"missing paper files: {missing}")

    tex = (PAPER / "main.tex").read_text(encoding="utf-8")
    forbidden = {
        "historical_4_5": r"(?:approximately|~|\\sim)\s*\+?4\.5",
        "unsupported_macro_1_8": r"\+1\.8",
        "unsupported_meta_2_0": r"\+2\.0",
        "false_cert_decisive": r"529\s+decisive",
        "private_team": r"Dreamer|GrimmsnaRL|Mint120|TMTA|lollipop947",
    }
    hits = {name: bool(re.search(pattern, tex, re.I)) for name, pattern in forbidden.items()}
    checks["unsupported_values_absent"] = not any(hits.values())
    if any(hits.values()):
        failures.append(f"forbidden manuscript strings: {hits}")

    available = citation_keys()
    used = used_citations(tex)
    checks["citations_resolve"] = used <= available
    checks["all_bibliography_entries_used"] = available <= used
    if not used <= available:
        failures.append(f"undefined citation keys: {sorted(used - available)}")
    if not available <= used:
        failures.append(f"unused bibliography keys: {sorted(available - used)}")

    generated = defined_commands()
    used_commands = set(re.findall(r"\\([A-Z][A-Za-z]+)", tex))
    builtins = {"Delta", "LaTeX"}
    unresolved = used_commands - generated - builtins
    checks["generated_macros_resolve"] = not unresolved
    if unresolved:
        failures.append(f"unresolved manuscript macros: {sorted(unresolved)}")

    with (PAPER / "claim_ledger.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        claims = list(reader)
        fields_ok = reader.fieldnames == REQUIRED_CLAIM_FIELDS
    statuses = {"VERIFIED", "VERIFIED_WITH_CAVEAT", "CONFLICT", "UNSUPPORTED", "REQUIRES_RERUN"}
    bad_status = [row["claim_id"] for row in claims if row["status"] not in statuses]
    bad_include = [row["claim_id"] for row in claims
                   if row["include_or_omit"] == "INCLUDE"
                   and row["status"] not in {"VERIFIED", "VERIFIED_WITH_CAVEAT"}]
    duplicate_ids = [key for key, count in __import__("collections").Counter(
        row["claim_id"] for row in claims
    ).items() if count > 1]
    checks["claim_schema"] = fields_ok
    checks["claim_statuses"] = not bad_status
    checks["claim_gate"] = not bad_include
    checks["claim_ids_unique"] = not duplicate_ids
    if not all((fields_ok, not bad_status, not bad_include, not duplicate_ids)):
        failures.append(
            f"claim ledger error: fields={fields_ok}, statuses={bad_status}, "
            f"included={bad_include}, duplicates={duplicate_ids}"
        )

    figures = sorted((PAPER / "figures").glob("fig*.pdf"))
    pngs = sorted((PAPER / "figures").glob("fig*.png"))
    checks["six_figures_two_formats"] = len(figures) == 6 and len(pngs) == 6
    if not checks["six_figures_two_formats"]:
        failures.append(f"figure count pdf/png = {len(figures)}/{len(pngs)}")

    stats = json.loads((PAPER / "data/statistical_summary.json").read_text(encoding="utf-8"))
    source_hashes = {
        item["path"]: sha256(ROOT / item["path"])
        for item in stats["source_inventory"]
    }
    drift = [item["path"] for item in stats["source_inventory"]
             if source_hashes[item["path"]] != item["sha256"]]
    checks["statistical_sources_unchanged"] = not drift
    if drift:
        failures.append(f"source digest drift: {drift}")

    manifest = RELEASE / "MANIFEST.sha256"
    manifest_errors = []
    if manifest.is_file():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            expected, relative = line.split("  ", 1)
            if sha256(RELEASE / relative) != expected:
                manifest_errors.append(relative)
    else:
        manifest_errors.append("MANIFEST.sha256 missing")
    checks["release_manifest"] = not manifest_errors
    if manifest_errors:
        failures.append(f"release manifest errors: {manifest_errors}")

    tracked_historical = subprocess.check_output(
        ["git", "diff", "--name-only", "ee567ed5b75029b3785c3b44725c5d55f94f9abd", "--"],
        cwd=ROOT, text=True,
    ).splitlines()
    unexpected = [path for path in tracked_historical if not (path.startswith("paper/") or path.startswith("release/"))]
    checks["historical_tree_untouched"] = not unexpected
    if unexpected:
        failures.append(f"non-paper/release tracked changes: {unexpected}")

    report = {
        "status": "PASS" if not failures else "FAIL",
        "checks": checks,
        "failures": failures,
        "claim_count": len(claims),
        "claim_status_counts": dict(__import__("collections").Counter(row["status"] for row in claims)),
        "paper_pdf_sha256": sha256(PAPER / "main.pdf") if (PAPER / "main.pdf").is_file() else None,
        "release_manifest_sha256": sha256(manifest) if manifest.is_file() else None,
    }
    output = PAPER / "supplement/FINAL_RED_TEAM.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
