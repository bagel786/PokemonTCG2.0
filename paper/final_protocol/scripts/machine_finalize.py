#!/usr/bin/env python3
"""Single final machine-finalization command for the Protocol Article.

Runs, in order: deterministic rebuild of the public-release candidate and
submission bundle; final five-pass desk aggregation; verification of every
FINAL audit artifact; then the canonical full reproduction pipeline
(scripts/reproduce_all.py) covering starting identity, frozen protocol
ancestry, raw hashes, reaggregation, independent statistics, synthetic suite,
admission properties, tables/figures/macros, claim ledger, novelty/reference
audits, chronology/contradiction audits, release rebuild + manifest,
clean-environment checks, REVTeX compile, all-page rendering, visual checks;
and finally writes the SHA-256-sidecar-bound REPRODUCTION_REPORT_MACHINE_FINAL.json.

Scientific files must not change afterward without rerunning this command.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

FINAL = Path(__file__).resolve().parents[1]
ROOT = FINAL.parents[2]
MACHINE_REPORT = FINAL / "REPRODUCTION_REPORT_MACHINE_FINAL.json"
MACHINE_SIDECAR = FINAL / "REPRODUCTION_REPORT_MACHINE_FINAL.sha256"
CANONICAL_REPORT = FINAL / "REPRODUCTION_REPORT.json"

REQUIRED_FINAL_ARTIFACTS = (
    "MACHINE_CLOSEOUT_START.json",
    "APS_REQUIREMENTS_CURRENT.md",
    "APS_REQUIREMENTS_CURRENT.json",
    "STALE_ARTIFACT_AUDIT.json",
    "HUMAN_PROSE_REVIEW.md",
    "CHRONOLOGY_AUDIT_V2.json",
    "NOVELTY_AUDIT_FINAL.md",
    "NOVELTY_MATRIX_FINAL.csv",
    "REFERENCE_AUDIT_FINAL.csv",
    "NOVELTY_SEARCH_LOG_FINAL.json",
    "EQUATION_AUDIT_FINAL.md",
    "INDEPENDENT_STATISTICAL_AUDIT_FINAL.md",
    "human_answers.template.yaml",
    "scripts/validate_human_answers.py",
    "scripts/apply_human_answers.py",
    "HUMAN_MINIMUM_ACTIONS.md",
    "RELEASE_OWNERSHIP_MATRIX_FINAL.csv",
    "ARCHIVE_METADATA_TEMPLATE.json",
    "ZENODO_METADATA_TEMPLATE.json",
    "PUBLIC_RELEASE_CHECKLIST.md",
    "data_availability_versions.md",
    "cover_letter_final_draft.md",
    "cover_letter_final_draft.txt",
    "APS_SCOPE_INQUIRY_READY.txt",
    "SUGGESTED_REVIEWERS_CANDIDATES.md",
    "EXCLUDED_REVIEWERS_TEMPLATE.md",
    "PHYSH_CANDIDATES.md",
    "SUBMISSION_METADATA_DRAFT.yaml",
    "WHAT_TO_SUBMIT_TO_APS.md",
    "OXFORD_FAILURE_MODE_AUDIT_FINAL.md",
    "DESK_REVIEW_SIMULATION_FINAL.json",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def run(command: list[str], cwd: Path) -> None:
    completed = subprocess.run(command, cwd=cwd, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if completed.returncode != 0:
        print(completed.stdout[-4000:])
        raise SystemExit(f"FAILED: {' '.join(command)}")
    print(f"[ok] {' '.join(command)}")


def main() -> int:
    # 14. public release candidate (rebuilt deterministically from verified release/)
    run([sys.executable, "paper/final_protocol/scripts/build_public_release_candidate.py"], ROOT)

    # 21./19. submission bundle draft (deterministic)
    run([sys.executable, "paper/final_protocol/scripts/build_submission_bundle.py"], ROOT)

    # 22./23. final five-pass desk simulation aggregate (deterministic)
    run([sys.executable, "paper/final_protocol/scripts/aggregate_desk_reviews_final.py"], ROOT)

    # Final-artifact inventory check.
    missing = [name for name in REQUIRED_FINAL_ARTIFACTS if not (FINAL / name).is_file()]
    if missing:
        raise SystemExit("missing FINAL artifacts: " + ", ".join(missing))

    # 24. canonical full reproduction pipeline (steps 1-18 of the brief).
    run([sys.executable, "paper/final_protocol/scripts/reproduce_all.py"], ROOT)

    # Bind everything into the machine-final report (canonical JSON, no wall clock).
    candidate_zip = FINAL / "public_release_candidate.zip"
    report = {
        "schema_version": "machine-final-reproduction-report-v1",
        "status": "PASS",
        "generated_by": "paper/final_protocol/scripts/machine_finalize.py",
        "subject_head_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
            stdout=subprocess.PIPE, check=True).stdout.strip(),
        "canonical_report_sha256": sha256(CANONICAL_REPORT),
        "final_desk_simulation_sha256": sha256(FINAL / "DESK_REVIEW_SIMULATION_FINAL.json"),
        "public_release_candidate_zip_sha256": sha256(candidate_zip),
        "key_artifact_sha256": {
            name: sha256(FINAL / name) for name in REQUIRED_FINAL_ARTIFACTS
        },
        "human_gate": {
            "overall_submission_status": "NOT_READY_DO_NOT_SUBMIT_UNTIL_HUMAN_CLOSEOUT_COMPLETE",
            "machine_verdict": None,
            "note": "Machine pass complete; human YAML/signoffs still required before any submission.",
        },
    }
    payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    MACHINE_REPORT.write_bytes(payload)
    MACHINE_SIDECAR.write_text(
        f"{hashlib.sha256(payload).hexdigest()}  {MACHINE_REPORT.name}\n", encoding="ascii")

    print(json.dumps({
        "status": "PASS",
        "report": str(MACHINE_REPORT.relative_to(ROOT)),
        "sidecar": str(MACHINE_SIDECAR.relative_to(ROOT)),
        "next_steps": [
            "git add -A && git commit  -> commit E (sole child of reproduced subject)",
            "python3 paper/final_protocol/scripts/verify_reproduction_report.py",
        ],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
