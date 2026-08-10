#!/usr/bin/env python3
"""Upload exactly one prevalidated emergency Grim candidate and record it."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPETITION = "pokemon-tcg-ai-battle"
ARCHIVE = ROOT / "artifacts" / "emergency_d842" / "grim_a2_ordered.tar.gz"
EXPECTED = "F294AA1183C132BEED5BEAF542BD8A05BE5729AA11C9D114C9EEFF78B730847E"
LEDGER = ROOT / "artifacts" / "emergency_d842" / "submission_ledger.json"


def main() -> int:
    actual = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest().upper()
    if actual != EXPECTED:
        raise SystemExit(f"archive changed after validation: {actual}")
    from kaggle.api.kaggle_api_extended import KaggleApi
    api = KaggleApi(); api.authenticate()
    before = api.competition_submissions(COMPETITION, page_size=100)
    if any(str(getattr(row, "description", "")).startswith("emergency-d842-a2-ordered-") for row in before):
        raise SystemExit("refusing duplicate emergency upload")
    today = dt.datetime.now(dt.timezone.utc).date()
    used = sum(1 for row in before if getattr(row, "date", None) is not None and row.date.date() == today)
    if used >= 5:
        raise SystemExit(f"daily submission quota exhausted ({used}/5)")
    latest_complete = [row for row in before if "COMPLETE" in str(row.status).upper()][:2]
    if len(latest_complete) < 2 or not all("grimmsnarl_5k_reference" in str(row.file_name) for row in latest_complete):
        raise SystemExit("expected two exact-d842 active controls before the one-slot replacement")

    description = f"emergency-d842-a2-ordered-full-corpus-{int(time.time())}"
    response = api.competition_submit(str(ARCHIVE), description, COMPETITION, quiet=False)
    submission_id = int(getattr(response, "ref", 0) or getattr(response, "id", 0) or 0)
    if not submission_id:
        raise RuntimeError("Kaggle returned no submission ID")
    ledger = {
        "competition": COMPETITION,
        "submission_id": submission_id,
        "description": description,
        "archive": str(ARCHIVE.resolve()),
        "archive_sha256": actual,
        "submitted_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "SUBMITTED",
        "active_slot_policy": "one candidate uploaded; newest exact-d842 control intentionally retained",
        "daily_uploads_before": used,
    }
    LEDGER.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    deadline = time.time() + 900
    while time.time() < deadline:
        rows = api.competition_submissions(COMPETITION, page_size=100)
        row = next((item for item in rows if int(item.ref) == submission_id), None)
        if row is not None:
            status = str(row.status).upper()
            ledger["status"] = status
            ledger["public_score_at_validation"] = getattr(row, "public_score", None)
            LEDGER.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
            if "COMPLETE" in status:
                ledger["validated_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
                LEDGER.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
                print(json.dumps(ledger, indent=2))
                return 0
            if "ERROR" in status or "FAILED" in status:
                raise RuntimeError(f"submission {submission_id} failed validation: {getattr(row, 'error_description', None)}")
        time.sleep(15)
    raise TimeoutError(f"submission {submission_id} did not validate within 900 seconds")


if __name__ == "__main__":
    raise SystemExit(main())
