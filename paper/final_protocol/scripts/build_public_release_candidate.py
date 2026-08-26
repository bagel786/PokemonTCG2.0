#!/usr/bin/env python3
"""Assemble the sanitized public-release CANDIDATE from the verified review package.

The candidate contains only potentially author-owned material staged by
build_final_release.py. It adds proposed license placeholders and citation
templates, a SHA-256 manifest, and a deterministic zip. Nothing is uploaded,
published, or licensed: LICENSE files stay `.proposed` and the status stays
CANDIDATE_NOT_AUTHORIZED until the human YAML approves otherwise.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

FINAL = Path(__file__).resolve().parents[1]
SOURCE = FINAL / "release"
STAGE = FINAL / "public_release_candidate"
ZIP_PATH = FINAL / "public_release_candidate.zip"
MANIFEST = STAGE / "MANIFEST.sha256"

EXCLUDED_NAMES = {"MANIFEST.sha256"}
FIXED_ZIP_DATE = (2026, 8, 25, 0, 0, 0)

PROPOSED_MIT = """# PROPOSED code license — NOT GRANTED UNTIL HUMAN APPROVAL
# Recommendation only (human_answers.yaml `release_rights.code_license`).
# Replace this file with an approved license before any distribution.

MIT License

Copyright (c) 2026 [AUTHOR NAME(S) REQUIRE HUMAN CONFIRMATION]

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

PROPOSED_CCBY = """# PROPOSED data/docs license — NOT GRANTED UNTIL HUMAN APPROVAL
# Recommendation only (human_answers.yaml `release_rights.data_docs_license`).

Creative Commons Attribution 4.0 International (CC BY 4.0)
Applies to processed data, documentation, figures, and source-data files.
Copyright 2026 [AUTHOR NAME(S) REQUIRE HUMAN CONFIRMATION]
Full text: https://creativecommons.org/licenses/by/4.0/legalcode
Code remains under the separately stated code license.
"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    if not SOURCE.is_dir():
        raise SystemExit("review package missing; run build_final_release.py first")
    if STAGE.exists():
        shutil.rmtree(STAGE)
    shutil.copytree(SOURCE, STAGE)
    # Candidate status markers replace review-only markers.
    status_path = STAGE / "RELEASE_STATUS.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["release_status"] = "CANDIDATE_NOT_AUTHORIZED"
    status["candidate_note"] = (
        "Public-release candidate assembled from the verified review package. "
        "License files are .proposed placeholders; no license is granted and no "
        "DOI exists until the human author authorizes them via human_answers.yaml."
    )
    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    (STAGE / "LICENSE").unlink(missing_ok=True)
    (STAGE / "LICENSE.code.proposed").write_text(PROPOSED_MIT, encoding="utf-8")
    (STAGE / "LICENSE.data-docs.proposed").write_text(PROPOSED_CCBY, encoding="utf-8")

    # Deterministic manifest over every payload file except the manifest itself.
    files = sorted(
        path for path in STAGE.rglob("*")
        if path.is_file() and path.name not in EXCLUDED_NAMES
    )
    lines = [f"{sha256(path)}  {path.relative_to(STAGE).as_posix()}\n" for path in files]
    MANIFEST.write_text("".join(lines), encoding="ascii")

    # Deterministic zip (fixed timestamps, sorted paths).
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files + [MANIFEST]:
            info = zipfile.ZipInfo(path.relative_to(FINAL).as_posix(), date_time=FIXED_ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())

    print(json.dumps({
        "status": "BUILT",
        "candidate": str(STAGE.relative_to(FINAL.parent.parent)),
        "files_manifested": len(files),
        "zip": str(ZIP_PATH.relative_to(FINAL.parent.parent)),
        "zip_sha256": sha256(ZIP_PATH),
        "authorization": "CANDIDATE_NOT_AUTHORIZED",
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
