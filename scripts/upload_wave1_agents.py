#!/usr/bin/env python3
"""Upload qualified Wave-1 agents in Fan-then-tempo active-slot order."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPETITION = "pokemon-tcg-ai-battle"
QUALIFICATION = ROOT / "artifacts" / "wave1_push" / "qualification_manifest.json"
LEDGER = ROOT / "artifacts" / "wave1_push" / "submission_ledger.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def status_name(row) -> str:
    return str(getattr(row, "status", "")).upper()


def wait_for_validation(api, submission_id: int, timeout_seconds: int = 900):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        rows = api.competition_submissions(COMPETITION, page_size=100)
        row = next((item for item in rows if int(item.ref) == int(submission_id)), None)
        if row is not None:
            status = status_name(row)
            if "COMPLETE" in status:
                return row
            if "ERROR" in status or "FAILED" in status:
                raise RuntimeError(f"submission {submission_id} failed validation: {getattr(row, 'error_description', None)}")
        time.sleep(15)
    raise TimeoutError(f"submission {submission_id} did not finish validation within {timeout_seconds}s")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="required acknowledgement for external upload")
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit("refusing external upload without --execute")
    qualification = json.loads(QUALIFICATION.read_text(encoding="utf-8"))
    if not qualification.get("upload_allowed") or qualification.get("hard_gate_failures"):
        raise SystemExit("Wave-1 qualification manifest does not permit upload")
    if qualification.get("upload_order") != ["fan", "tempo"]:
        raise SystemExit("unexpected Wave-1 upload order")

    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()
    existing = api.competition_submissions(COMPETITION, page_size=100)
    descriptions = {str(getattr(row, "description", "")) for row in existing}
    if any(value.startswith("wave1-topgrim-") for value in descriptions):
        raise SystemExit("refusing duplicate Wave-1 upload")
    today_utc = dt.datetime.now(dt.timezone.utc).date()
    used_today = sum(
        1 for row in existing
        if getattr(row, "date", None) is not None and getattr(row, "date").date() == today_utc
    )
    if used_today > 3:
        raise SystemExit(f"need two daily submissions but {used_today}/5 are already used")

    ledger = {
        "competition": COMPETITION,
        "qualification_manifest_sha256": sha256(QUALIFICATION),
        "upload_started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "submissions": [],
    }
    for position, mode in enumerate(("fan", "tempo"), 1):
        package = qualification["packages"][mode]
        archive = Path(package["archive"])
        if sha256(archive) != package["archive_sha256"]:
            raise RuntimeError(f"{mode} archive hash changed after qualification")
        description = (
            f"wave1-topgrim-{mode}-"
            + ("fan-deck-a2-deterministic-rail" if mode == "fan" else "exact-a2-t1t2-tempo-rail")
        )
        response = api.competition_submit(str(archive), description, COMPETITION, quiet=False)
        submission_id = int(getattr(response, "ref", 0) or getattr(response, "id", 0) or 0)
        if not submission_id:
            raise RuntimeError(f"Kaggle returned no submission ID for {mode}")
        entry = {
            "mode": mode,
            "submission_id": submission_id,
            "description": description,
            "archive": str(archive.resolve()),
            "archive_sha256": package["archive_sha256"],
            "position": position,
            "submitted_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "status": "SUBMITTED",
        }
        ledger["submissions"].append(entry)
        LEDGER.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        validated = wait_for_validation(api, submission_id)
        entry["status"] = "COMPLETE"
        entry["public_score_at_validation"] = getattr(validated, "public_score", None)
        entry["validated_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        LEDGER.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(entry, sort_keys=True), flush=True)
    ledger["upload_completed_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    LEDGER.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"uploaded": ledger["submissions"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
