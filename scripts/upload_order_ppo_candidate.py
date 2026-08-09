#!/usr/bin/env python3
"""Upload exactly one fully promoted CONTROLLED_LADDER_PROBE before cutoff."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import time
from pathlib import Path

COMPETITION = "pokemon-tcg-ai-battle"
CUTOFF_UTC = dt.datetime(2026, 8, 8, 23, 30, tzinfo=dt.timezone.utc)  # 6:30 PM CDT
PROBE_IDS = {"55358290", "55358291"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--promotion", default="artifacts/order_ppo/promotion_manifest.json")
    parser.add_argument("--package", default="artifacts/order_ppo/package_manifest.json")
    parser.add_argument("--ledger", default="artifacts/order_ppo/submission_ledger.json")
    args = parser.parse_args()
    if dt.datetime.now(dt.timezone.utc) >= CUTOFF_UTC:
        raise SystemExit("refusing 5k+ upload after the 2026-08-08 6:30 PM Central cutoff")
    promotion = json.loads(Path(args.promotion).read_text(encoding="utf-8"))
    package = json.loads(Path(args.package).read_text(encoding="utf-8"))
    if not promotion.get("passed") or not all(promotion.get("checks", {}).values()):
        raise SystemExit("refusing upload: promotion manifest did not pass every gate")
    if promotion.get("label") != "CONTROLLED_LADDER_PROBE" or package.get("label") != "CONTROLLED_LADDER_PROBE":
        raise SystemExit("refusing upload: controlled-probe label is absent")
    archive = Path(package["archive"])
    if sha256(archive) != str(package["archive_sha256"]).upper():
        raise SystemExit("refusing upload: archive hash mismatch")
    if not package.get("deterministic_archive") or not package.get("no_r0_director_d1_search"):
        raise SystemExit("refusing upload: runtime/package invariants are incomplete")

    from kaggle.api.kaggle_api_extended import KaggleApi
    api = KaggleApi(); api.authenticate()
    existing = api.competition_submissions(COMPETITION, page_size=100)
    existing_ids = {str(getattr(row, "ref", "") or getattr(row, "id", "")) for row in existing}
    if not PROBE_IDS.issubset(existing_ids):
        raise SystemExit("refusing upload: both exact 5k variance probes are not present")
    if any("CONTROLLED_LADDER_PROBE 5k+ 20260808" in str(getattr(row, "description", "")) for row in existing):
        raise SystemExit("refusing duplicate 5k+ upload")
    response = api.competition_submit(
        str(archive), "CONTROLLED_LADDER_PROBE 5k+ 20260808", COMPETITION, quiet=False
    )
    submission_id = str(getattr(response, "ref", "") or getattr(response, "id", ""))
    if not submission_id:
        raise RuntimeError("Kaggle accepted no submission ID")
    ledger_path = Path(args.ledger)
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["submissions"].append({
        "submission_id": submission_id,
        "label": "CONTROLLED_LADDER_PROBE 5k+ 20260808",
        "submitted_unix": time.time(),
        "archive": str(archive.resolve()),
        "archive_sha256": package["archive_sha256"],
        "promotion_manifest": str(Path(args.promotion).resolve()),
    })
    temporary = ledger_path.with_suffix(ledger_path.suffix + ".tmp")
    temporary.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    temporary.replace(ledger_path)
    print(json.dumps({"submission_id": submission_id, "archive_sha256": package["archive_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
