#!/usr/bin/env python3
"""Upload two byte-identical copies of the qualified Grim damage-v0 agent."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPETITION = "pokemon-tcg-ai-battle"
MANIFEST = ROOT / "artifacts" / "grim_damage_conversion" / "winner" / "grim_a2_damage_v0.manifest.json"
LEDGER = ROOT / "artifacts" / "grim_damage_conversion" / "winner" / "submission_ledger.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def status_name(row: object) -> str:
    return str(getattr(row, "status", "")).upper()


def authenticate():
    # Kaggle CLI 2.x can use an OAuth access token directly. The local OAuth
    # cache is used only when the standard environment variable is absent.
    if not os.environ.get("KAGGLE_API_TOKEN"):
        credentials = Path.home() / ".kaggle" / "credentials.json"
        if credentials.exists():
            token = json.loads(credentials.read_text(encoding="utf-8")).get("access_token")
            if token:
                os.environ["KAGGLE_API_TOKEN"] = token
    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()
    return api


def wait_for_validation(api, submission_id: int, timeout_seconds: int = 900):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        rows = api.competition_submissions(COMPETITION, page_size=100)
        row = next((item for item in rows if int(item.ref) == submission_id), None)
        if row is not None:
            status = status_name(row)
            if "COMPLETE" in status:
                return row
            if "ERROR" in status or "FAILED" in status:
                raise RuntimeError(
                    f"submission {submission_id} failed validation: "
                    f"{getattr(row, 'error_description', None)}"
                )
        time.sleep(15)
    raise TimeoutError(f"submission {submission_id} did not validate within {timeout_seconds}s")


def write_ledger(ledger: dict) -> None:
    temporary = LEDGER.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(LEDGER)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="required acknowledgement for external uploads")
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("refusing external uploads without --execute")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("status") != "qualified_winner_packaged_not_uploaded":
        raise SystemExit("damage-v0 manifest is not in the qualified packaged state")
    archive = Path(manifest["archive"])
    expected_hash = manifest["archive_sha256"].upper()
    if sha256(archive) != expected_hash:
        raise SystemExit("damage-v0 archive hash changed after qualification")

    api = authenticate()
    existing = api.competition_submissions(COMPETITION, page_size=100)
    description_prefix = "grim-a2-damage-v0-copy-"
    if any(
        str(getattr(row, "description", "")).startswith(description_prefix)
        and "ERROR" not in status_name(row)
        and "FAILED" not in status_name(row)
        for row in existing
    ):
        raise SystemExit("refusing duplicate damage-v0 copy upload run")

    today_utc = dt.datetime.now(dt.timezone.utc).date()
    used_today = sum(
        1
        for row in existing
        if getattr(row, "date", None) is not None and row.date.date() == today_utc
    )
    if used_today > 3:
        raise SystemExit(f"need two daily submissions but {used_today}/5 are already used")

    ledger = {
        "competition": COMPETITION,
        "archive": str(archive.resolve()),
        "archive_sha256": expected_hash,
        "manifest": str(MANIFEST.resolve()),
        "purpose": "two byte-identical copies to maximize the chance of a high converged TrueSkill rating",
        "upload_started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "daily_uploads_before": used_today,
        "submissions": [],
    }
    write_ledger(ledger)

    for position, arm in enumerate(("A", "B"), 1):
        description = f"{description_prefix}{arm}-20260813"
        response = api.competition_submit(str(archive), description, COMPETITION, quiet=False)
        submission_id = int(getattr(response, "ref", 0) or getattr(response, "id", 0) or 0)
        if not submission_id:
            raise RuntimeError(f"Kaggle returned no submission ID for copy {arm}")
        entry = {
            "arm": arm,
            "position": position,
            "submission_id": submission_id,
            "description": description,
            "submitted_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "status": "SUBMITTED",
        }
        ledger["submissions"].append(entry)
        write_ledger(ledger)
        try:
            validated = wait_for_validation(api, submission_id)
        except Exception as error:
            entry["status"] = "ERROR"
            entry["validation_error"] = str(error)
            write_ledger(ledger)
            raise
        entry["status"] = "COMPLETE"
        entry["public_score_at_validation"] = getattr(validated, "public_score", None)
        entry["validated_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        write_ledger(ledger)
        print(json.dumps(entry, sort_keys=True), flush=True)

    ledger["upload_completed_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    write_ledger(ledger)
    print(json.dumps({"uploaded": ledger["submissions"]}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
