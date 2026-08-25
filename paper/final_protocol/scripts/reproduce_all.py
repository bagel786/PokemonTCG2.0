#!/usr/bin/env python3
"""Rebuild and verify the final Protocol Article without running the game engine.

The canonical profile consumes retained acquisition artifacts and immutable raw
rows.  It regenerates only derived audits, summaries, manuscript artifacts, and
the sanitized review package.  Any command failure stops the pipeline after a
machine-readable failure report has been written.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
FINAL = SCRIPT.parents[1]
ROOT = SCRIPT.parents[3]
REPORT = FINAL / "REPRODUCTION_REPORT.json"
VISUAL_AUDIT = FINAL / "supplement/PDF_VISUAL_AUDIT.json"
PROTOCOL_COMMIT = "803257f102232763fc88d28c14b668f9b62eb277"
TITLE = "A Trace-Based Validation Protocol for Seed-Matched Evaluations of Black-Box Game-Playing Agents"
SOURCE_DATE_EPOCH = "1787529600"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_output(value: str) -> str:
    """Keep diagnostic tails useful without leaking the local checkout path."""
    text = value.replace(str(ROOT), "<repo>")
    lines = text.splitlines()
    return "\n".join(lines[-40:])


def write_report(report: dict[str, Any]) -> None:
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(command: list[str], purpose: str, *, cwd: Path = ROOT, timeout: int = 900) -> dict[str, Any]:
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "SOURCE_DATE_EPOCH": SOURCE_DATE_EPOCH,
        },
    )
    record = {
        "purpose": purpose,
        "command": " ".join(command),
        "returncode": completed.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "output_tail": clean_output(completed.stdout),
    }
    if completed.returncode != 0:
        raise RuntimeError(json.dumps(record, sort_keys=True))
    return record


def key_outputs() -> dict[str, dict[str, Any]]:
    paths = {
        "manuscript_pdf": FINAL / "main.pdf",
        "claim_ledger": FINAL / "claim_ledger.csv",
        "results_macros": FINAL / "results_macros.tex",
        "contradiction_audit": FINAL / "CONTRADICTION_AUDIT.json",
        "red_team": FINAL / "FINAL_RED_TEAM.json",
        "release_manifest": FINAL / "release/MANIFEST.sha256",
        "statistics_verification": FINAL / "source_data/statistics_verification.json",
        "artifact_build": FINAL / "source_data/build_report.json",
        "pdf_visual_audit": VISUAL_AUDIT,
    }
    result: dict[str, dict[str, Any]] = {}
    for role, path in paths.items():
        result[role] = {
            "path": str(path.relative_to(ROOT)),
            "exists": path.is_file(),
            "sha256": sha256(path) if path.is_file() else None,
        }
    return result


def render_and_validate_pdf() -> dict[str, Any]:
    """Render every PDF page and bind a recorded visual inspection to final bytes."""
    if shutil.which("pdftoppm") is None or shutil.which("pdfinfo") is None:
        raise RuntimeError("pdftoppm and pdfinfo are required for the all-page visual audit")
    if not VISUAL_AUDIT.is_file():
        raise RuntimeError(f"missing PDF visual-inspection attestation: {VISUAL_AUDIT}")
    try:
        attestation = json.loads(VISUAL_AUDIT.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid PDF visual-inspection attestation: {exc}") from exc
    if not isinstance(attestation, dict) or attestation.get("status") != "PASS":
        raise RuntimeError("PDF visual-inspection attestation must have status PASS")
    source_hash = sha256(FINAL / "main.tex")
    pdf_hash = sha256(FINAL / "main.pdf")
    if attestation.get("manuscript_source_sha256") != source_hash:
        raise RuntimeError("PDF visual-inspection attestation is stale for main.tex")
    if attestation.get("manuscript_pdf_sha256") != pdf_hash:
        raise RuntimeError("PDF visual-inspection attestation is stale for main.pdf")

    info = subprocess.run(
        ["pdfinfo", "main.pdf"], cwd=FINAL, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    if info.returncode != 0:
        raise RuntimeError(f"pdfinfo failed: {clean_output(info.stdout)}")
    match = re.search(r"^Pages:\s+(\d+)\s*$", info.stdout, flags=re.MULTILINE)
    if not match:
        raise RuntimeError("pdfinfo did not report a page count")
    expected_pages = int(match.group(1))
    if expected_pages <= 0 or attestation.get("page_count") != expected_pages:
        raise RuntimeError("PDF visual-inspection attestation page count is stale")
    inspected_pages = attestation.get("inspected_pages")
    if inspected_pages != list(range(1, expected_pages + 1)):
        raise RuntimeError("PDF visual-inspection attestation must enumerate every page")
    checklist = attestation.get("checklist")
    if not isinstance(checklist, dict) or not checklist or not all(value is True for value in checklist.values()):
        raise RuntimeError("PDF visual-inspection checklist is incomplete")

    with tempfile.TemporaryDirectory(prefix="final-protocol-render-") as directory:
        prefix = Path(directory) / "page"
        rendered = subprocess.run(
            ["pdftoppm", "-r", "150", "-png", "main.pdf", str(prefix)],
            cwd=FINAL, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            check=False, env={**os.environ, "SOURCE_DATE_EPOCH": SOURCE_DATE_EPOCH},
        )
        if rendered.returncode != 0:
            raise RuntimeError(f"pdftoppm failed: {clean_output(rendered.stdout)}")
        pages = sorted(
            Path(directory).glob("page-*.png"),
            key=lambda path: int(path.stem.rsplit("-", 1)[1]),
        )
        if len(pages) != expected_pages:
            raise RuntimeError(f"rendered {len(pages)} pages; expected {expected_pages}")
        page_records = []
        for index, path in enumerate(pages, 1):
            data = path.read_bytes()
            if len(data) < 33 or not data.startswith(b"\x89PNG\r\n\x1a\n") or data[12:16] != b"IHDR":
                raise RuntimeError(f"invalid rendered PNG for page {index}")
            width = int.from_bytes(data[16:20], "big")
            height = int.from_bytes(data[20:24], "big")
            if width < 900 or height < 900:
                raise RuntimeError(f"rendered page {index} is unexpectedly small: {width}x{height}")
            page_records.append({
                "page": index,
                "width_pixels": width,
                "height_pixels": height,
                "sha256": sha256(path),
            })
    return {
        "status": "PASS",
        "method": "Every page rendered at 150 dpi; PNG structure and dimensions checked; PDF-bound checklist records page-by-page visual inspection.",
        "attestation": str(VISUAL_AUDIT.relative_to(ROOT)),
        "attestation_sha256": sha256(VISUAL_AUDIT),
        "manuscript_source_sha256": source_hash,
        "manuscript_pdf_sha256": pdf_hash,
        "page_count": expected_pages,
        "rendered_pages": page_records,
    }


def validate_final_audits() -> None:
    """Require every remaining open item to be explicitly human or legal."""
    contradiction_path = FINAL / "CONTRADICTION_AUDIT.json"
    red_team_path = FINAL / "FINAL_RED_TEAM.json"
    contradiction = json.loads(contradiction_path.read_text(encoding="utf-8"))
    summary = contradiction.get("summary", {})
    if summary.get("contradictions") != 0 or summary.get("machine_verification_blockers") != 0:
        raise RuntimeError("final contradiction audit retains a factual or machine blocker")
    if summary.get("factual_consistency_status") != "PASS" or summary.get("machine_verification_status") != "PASS":
        raise RuntimeError("final contradiction audit did not pass factual and machine checks")

    red_team = json.loads(red_team_path.read_text(encoding="utf-8"))
    if red_team.get("reproduction_status") != {
        "status": "PASS",
        "complete_workflow_passed": True,
        "visual_audit_passed": True,
    }:
        raise RuntimeError("red-team report is not bound to the passing workflow and visual audit")
    allowed_open = {"OPEN_HUMAN_BLOCKER", "OPEN_LEGAL_BLOCKER"}
    disallowed: list[str] = []
    for review in red_team.get("review_passes", []):
        for item in review.get("criticisms", []):
            status = str(item.get("fixed_status", ""))
            if not status.startswith("FIXED") and status not in allowed_open:
                disallowed.append(f"{item.get('criticism_id')}={status}")
    if disallowed:
        raise RuntimeError("red-team technical criticisms remain open: " + ", ".join(disallowed))
    if red_team.get("final_decision") != "NOT_READY_DO_NOT_SUBMIT":
        raise RuntimeError("final red-team decision must remain fail-closed while human/legal blockers are open")


def base_report() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "RUNNING",
        "title": TITLE,
        "article_type": "APS Open Science Protocol Article",
        "protocol_commit": PROTOCOL_COMMIT,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Derived-artifact reproduction only; no restricted-engine execution and no new policy experiment.",
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": __import__("numpy").__version__,
            "matplotlib": __import__("matplotlib").__version__,
            "tectonic_available": shutil.which("tectonic") is not None,
        },
        "commands": [],
        "outputs": {},
        "limitations": [
            "The restricted game engine and private acquisition materials are not rerun.",
            "The command verifies retained canonical artifacts and reproduces synthetic and processed analyses.",
            "Rights, licensing, DOI, human metadata, and author comprehension remain human blockers.",
        ],
    }


def main() -> int:
    report = base_report()
    write_report(report)
    python = sys.executable
    commands: list[tuple[list[str], str, Path]] = [
        (["git", "merge-base", "--is-ancestor", PROTOCOL_COMMIT, "HEAD"], "verify frozen protocol ancestry", ROOT),
        ([python, "paper/scripts/audit_seed_namespace.py"], "rebuild observable boundary-seed namespace audit", ROOT),
        ([python, "paper/scripts/audit_stochastic_sources.py"], "rebuild bounded stochastic-source pattern audit", ROOT),
        ([python, "paper/scripts/analyze_pevl.py"], "rebuild canonical PEVL summaries and factorial units from retained acquisition artifacts", ROOT),
        ([python, "paper/final_protocol/scripts/verify_statistics.py"], "independently verify raw-source hashes, schedules, audits, reaggregation, and statistics", ROOT),
        ([python, "paper/final_protocol/scripts/build_final_artifacts.py"], "rebuild generated macros, tables, figures, and source data", ROOT),
        ([python, "paper/final_protocol/scripts/recalculate_equation_examples.py"], "recalculate independent equation examples", ROOT),
        ([
            python, "-m", "pytest", "-q",
            "tests/test_analyze_pevl.py",
            "tests/test_build_pevl_artifacts.py",
            "tests/test_build_pevl_result_macros.py",
            "tests/test_build_release_pevl.py",
            "tests/test_pevl_synthetic.py",
            "tests/test_seed_namespace_audit.py",
            "tests/test_stochastic_source_audit.py",
            "tests/test_verify_pevl_release.py",
            "paper/final_protocol/tests/test_equations.py",
        ], "run targeted analyzer, audit, synthetic, release, and equation tests", ROOT),
        ([python, "paper/final_protocol/scripts/build_final_release.py"], "build sanitized engine-free review package", ROOT),
        ([python, "-m", "pevl_bench", "generate"], "regenerate synthetic conformance outputs through the review-package interface", FINAL / "release"),
        ([python, "-m", "pevl_bench", "verify"], "verify synthetic conformance outputs through the review-package interface", FINAL / "release"),
        ([python, "-m", "pevl_bench", "report", "--json"], "summarize processed evidence through the review-package interface", FINAL / "release"),
        ([python, "-m", "pytest", "-q", "tests/test_release.py"], "run engine-independent release tests", FINAL / "release"),
        ([python, "scripts/verify_release.py"], "verify release manifest and reaggregate processed rows", FINAL / "release"),
        ([python, "paper/final_protocol/scripts/build_claim_ledger.py"], "rebuild sentence-level claim ledger", ROOT),
        ([python, "paper/final_protocol/scripts/build_final_release.py"], "refresh release manifest after claim-ledger generation", ROOT),
        (["tectonic", "--keep-logs", "main.tex"], "compile current REVTeX manuscript", FINAL),
    ]
    try:
        if shutil.which("tectonic") is None:
            raise RuntimeError("tectonic is required to compile the manuscript")
        for command, purpose, cwd in commands:
            record = run(command, purpose, cwd=cwd)
            report["commands"].append(record)
            write_report(report)

        pdf_started = time.monotonic()
        extracted = subprocess.run(
            ["pdftotext", "main.pdf", "-"], cwd=FINAL, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
        normalized_pdf_text = " ".join(extracted.stdout.split())
        if extracted.returncode != 0 or TITLE not in normalized_pdf_text:
            raise RuntimeError("compiled PDF title does not match the Protocol Article")
        pdf_text = {
            "purpose": "extract compiled PDF text for identity check",
            "command": "pdftotext main.pdf -",
            "returncode": extracted.returncode,
            "duration_seconds": round(time.monotonic() - pdf_started, 3),
            "output_tail": "Protocol Article title matched compiled PDF text.",
        }
        report["commands"].append(pdf_text)
        manuscript_source = (FINAL / "main.tex").read_text(encoding="utf-8")
        abstract_source = manuscript_source.split("\\begin{abstract}", 1)[1].split("\\end{abstract}", 1)[0]
        abstract_plain = re.sub(r"\\[A-Za-z]+(?:\{\})?", " ", abstract_source)
        abstract_plain = re.sub(r"[{}]", " ", abstract_plain)
        report["word_count"] = {
            "compiled_pdf_text_including_references": len(normalized_pdf_text.split()),
            "abstract_source_words_approximate": len(re.findall(r"[A-Za-z0-9]+(?:[-–][A-Za-z0-9]+)*", abstract_plain)),
            "method": "whitespace words from pdftotext; approximate regex words from the unexpanded TeX abstract",
        }
        report["visual_audit"] = render_and_validate_pdf()

        # A provisional PASS lets the cross-file auditors verify the reproduction
        # status without a circular missing-report dependency.
        report["status"] = "PASS"
        report["outputs"] = key_outputs()
        write_report(report)
        for command, purpose in (
            ([python, "paper/final_protocol/scripts/audit_contradictions.py"], "run cross-file contradiction audit"),
            ([python, "paper/final_protocol/scripts/red_team_audit.py"], "run three-pass adversarial review"),
        ):
            report["commands"].append(run(command, purpose, cwd=ROOT))
        validate_final_audits()
        report["outputs"] = key_outputs()
        report["status"] = "PASS"
        report["readiness_decision"] = "NOT_READY_DO_NOT_SUBMIT"
        write_report(report)
    except (RuntimeError, subprocess.TimeoutExpired, OSError) as exc:
        report["status"] = "FAIL"
        report["error"] = clean_output(str(exc))
        report["outputs"] = key_outputs()
        write_report(report)
        print(json.dumps({"status": "FAIL", "report": str(REPORT.relative_to(ROOT))}, sort_keys=True))
        return 1

    print(json.dumps({"status": "PASS", "report": str(REPORT.relative_to(ROOT))}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
