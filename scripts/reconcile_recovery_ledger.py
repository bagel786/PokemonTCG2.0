#!/usr/bin/env python3
"""Verify Kaggle recovery submissions and repair ledger-derived status/model fields."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPETITION = "pokemon-tcg-ai-battle"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    ledger_path = ROOT / "artifacts" / "recovery_probes" / "submission_ledger.json"
    ledger = json.loads(ledger_path.read_text())
    builds = json.loads((ROOT / "artifacts" / "recovery_probes" / "build_manifest.json").read_text())
    build_by_name = {row["name"]: row for row in builds["artifacts"]}
    model_hashes = {
        "a1": build_by_name["a1_d842_shield"]["model_sha256"],
        "a2": build_by_name["a2_v2_shield"]["model_sha256"],
        "d842_control_exact": sha256(ROOT / "artifacts" / "recovery_probes" / "extracted" / "control" / "policy_weights.npz"),
    }
    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()
    remote = {str(row.ref): row for row in api.competition_submissions(COMPETITION, page_size=100)}
    for row in ledger["submissions"]:
        submission = remote.get(str(row["submission_id"]))
        if submission is None:
            raise RuntimeError(f"submission is absent from Kaggle: {row['submission_id']}")
        if submission.description != row["message"]:
            raise RuntimeError(f"submission message mismatch: {row['submission_id']}")
        row["model_sha256"] = model_hashes[row["name"]]
        row["kaggle_file_name"] = submission.file_name
        row["kaggle_status"] = str(submission.status)
        row["public_score"] = submission.public_score or None
        row["verified_unix"] = time.time()
    ledger["verified_upload_order"] = [row["submission_id"] for row in sorted(
        ledger["submissions"], key=lambda item: item["upload_position"]
    )]
    temporary = ledger_path.with_name(ledger_path.name + ".tmp")
    temporary.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    temporary.replace(ledger_path)
    print(json.dumps({
        "verified": ledger["verified_upload_order"],
        "statuses": [row["kaggle_status"] for row in ledger["submissions"]],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
