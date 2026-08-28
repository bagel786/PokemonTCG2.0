#!/usr/bin/env python3
"""Dependency-minimal verification of the fail-closed campaign record."""

from __future__ import annotations

import csv
import hashlib
import json
import lzma
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "independent_confirmation"
BASE_SHA = "91ad7fa9571ee0ca10200fd7fe7b589589e8b794"
FREEZE_TAG = "claim-specific-prospective-repair-freeze-20260827"
FREEZE_TAG_OBJECT = "cb88ce6f27739bc71c2aa434e9c3a5d602bd2de3"
FREEZE_PEELED = "2bf3cea7a8a31b8e06dda814200ae83c20a163a0"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")


def git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, text=True, capture_output=True
    )
    return completed.stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def xz_identity(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    rows = 0
    trailing = b""
    with lzma.open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            rows += chunk.count(b"\n")
            trailing = chunk[-1:]
    require(trailing == b"\n", f"{path} lacks a final newline")
    return digest.hexdigest(), rows


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


with (CAMPAIGN / "FINAL_STATUS.json").open(encoding="utf-8") as stream:
    status = json.load(stream)
require(status["status"] == "NOT_READY_NOVELTY_FAILURE", "wrong final status")
require(status["confirmatory_acquisition_authorized"] is False, "acquisition authorized")
require(status["new_campaign"]["exact_surviving_contribution"] is None, "contribution claimed")
require(status["new_campaign"]["confirmatory_rows"] == 0, "new rows claimed")
require(status["gates"]["novelty"] == "FAIL", "novelty gate not failed")

with (CAMPAIGN / "literature" / "NOVELTY_VERDICT.json").open(encoding="utf-8") as stream:
    novelty = json.load(stream)
require(novelty["status"] == status["status"], "novelty/final status mismatch")
require(novelty["novelty_gate_pass"] is False, "novelty gate unexpectedly passes")
require(novelty["confirmatory_acquisition_authorized"] is False, "novelty authorizes acquisition")

source_header, sources = read_csv(CAMPAIGN / "literature" / "FULL_TEXT_VERIFICATION.csv")
require(len(source_header) == 13, "full-text ledger must have 13 columns")
require(len(sources) == 13, "full-text ledger must have 13 sources")
require(all(row["full_text_inspected"] == "YES" for row in sources), "source lacks full-text check")

defect_header, defects = read_csv(CAMPAIGN / "DEFECT_LEDGER.csv")
require(len(defect_header) == 9, "defect ledger must have 9 columns")
require(len(defects) == 55, "defect ledger must have 55 defects")
require(len({row["defect_id"] for row in defects}) == 55, "duplicate defect ID")
allowed_dispositions = {"PRESERVED_OPEN_IN_FAILED_CAMPAIGN", "PRESERVED_INTEGRITY_FAILURE"}
require({row["disposition"] for row in defects} <= allowed_dispositions, "invalid defect disposition")

raw_xz = ROOT / "prospective_repair" / "results" / "final" / "raw_rows.jsonl.xz"
cost_xz = ROOT / "prospective_repair" / "results" / "final" / "cost_rows.jsonl.xz"
require(sha256(raw_xz) == "b22ad70dfe9732990184e0a8ee117193bb385dca92388f2ea236c8092b04919b", "raw XZ hash")
require(sha256(cost_xz) == "e1cf7efaaa3cb14abdeef3bed05e81d9fe720c8f3aefac857aa2d741ef11589b", "cost XZ hash")
raw_hash, raw_rows = xz_identity(raw_xz)
cost_hash, cost_rows = xz_identity(cost_xz)
require(raw_hash == "792b6fd0a830c0c1b357becb0e7be661a8ceb9147b3a6ec2faadf604c5e447b1", "raw uncompressed hash")
require(raw_rows == 125600, "raw row count")
require(cost_hash == "17c1f296bf6821ea5638109e329e0122f6e40fc3528c04f56935c9fb4a2e8237", "cost uncompressed hash")
require(cost_rows == 4800, "cost row count")

require(git("rev-parse", FREEZE_TAG) == FREEZE_TAG_OBJECT, "historical tag object changed")
require(git("rev-parse", f"{FREEZE_TAG}^{{}}") == FREEZE_PEELED, "historical tag peel changed")
subprocess.run(
    ["git", "diff", "--exit-code", BASE_SHA, "HEAD", "--", "prospective_repair", "redesign"],
    cwd=ROOT,
    check=True,
    stdout=subprocess.DEVNULL,
)

for forbidden in (
    CAMPAIGN / "results",
    CAMPAIGN / "confirmatory",
    CAMPAIGN / "protocol" / "FREEZE_RECORD.json",
    CAMPAIGN / "manuscript" / "FINAL_MANUSCRIPT_FOR_REVIEW.tex",
    CAMPAIGN / "manuscript" / "FINAL_MANUSCRIPT_FOR_REVIEW.pdf",
):
    require(not forbidden.exists(), f"unexpected downstream artifact: {forbidden.relative_to(ROOT)}")

portal = CAMPAIGN / "HUMAN_PORTAL"
require(portal.is_dir(), "human portal missing")
for path in portal.glob("*.md"):
    text = path.read_text(encoding="utf-8")
    require(re.search(r"\[[xX]\]", text) is None, f"human checkbox completed in {path.name}")

claim_header, claims = read_csv(CAMPAIGN / "claim_ledger.csv")
required_claim_columns = [
    "claim_id", "manuscript_section", "manuscript_anchor", "exact_claim_text",
    "claim_type", "importance", "support_type", "supporting_dataset",
    "dataset_sha256", "supporting_code", "reproduction_command", "output_file",
    "output_key", "estimand", "experimental_unit", "numerator", "denominator",
    "interval_or_uncertainty", "supporting_citation", "citation_full_text_verified",
    "reaggregation_check", "known_limitation", "status", "reviewer_note",
]
require(claim_header == required_claim_columns, "claim-ledger schema mismatch")
require(len(claims) >= 10, "claim ledger is incomplete")
allowed_claim_statuses = {"VERIFIED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "HUMAN_VERIFICATION_REQUIRED"}
require({row["status"] for row in claims} <= allowed_claim_statuses, "invalid claim status")

print("PASS: fail-closed stop record verified; no new confirmatory campaign exists")
