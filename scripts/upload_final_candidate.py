#!/usr/bin/env python3
"""Upload only a fully promoted final candidate (or its prequalified contingency)."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPETITION = "pokemon-tcg-ai-battle"
FINAL_SELECTION_CUTOFF = dt.datetime(2026, 8, 10, 5, 0, tzinfo=dt.timezone.utc)
ALL_UPLOADS_CUTOFF = dt.datetime(2026, 8, 12, 5, 0, tzinfo=dt.timezone.utc)
CONTROL_HASH = "3ECB0BBF119E23C31905E39E19ECA8F6145104AAEFFC0A5675D2FE03855BB458"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="artifacts/recovery_final/promotion_manifest.json")
    parser.add_argument("--ledger", default="artifacts/recovery_final/submission_ledger.json")
    parser.add_argument("--mode", choices=("selected", "contingency"), default="selected")
    args = parser.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = FINAL_SELECTION_CUTOFF if args.mode == "selected" else ALL_UPLOADS_CUTOFF
    if now >= cutoff:
        raise SystemExit(f"{args.mode} upload window is closed")
    manifest = json.loads(Path(args.manifest).read_text())
    if manifest.get("promotion_result") != "passed":
        raise SystemExit("refusing final upload: promotion result is not passed")
    name = manifest.get(args.mode)
    if not name or not manifest["decisions"].get(name, {}).get("passed"):
        raise SystemExit(f"refusing final upload: {args.mode} is absent or did not pass every gate")
    package = manifest["packages"][name]
    archive = Path(package["archive"])
    if sha256(archive) != package["archive_sha256"]:
        raise SystemExit("final candidate archive hash mismatch")
    order = [(name, archive, package["archive_sha256"], package["model_sha256"])]
    if args.mode == "contingency":
        control = ROOT / "artifacts" / "recovery_probes" / "d842_control_exact.tar.gz"
        if sha256(control) != CONTROL_HASH:
            raise SystemExit("exact d842 contingency control hash mismatch")
        control_model = sha256(ROOT / "artifacts" / "recovery_probes" / "extracted" / "control" / "policy_weights.npz")
        order.append(("d842_control_exact", control, CONTROL_HASH, control_model))

    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()
    api.competition_submissions(COMPETITION, page_size=1)
    ledger_path = Path(args.ledger)
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {"competition": COMPETITION, "submissions": []}
    for position, (upload_name, upload_archive, archive_hash, model_hash) in enumerate(order, 1):
        message = f"grim-final-{args.mode}-{upload_name}-{int(time.time())}-{position}of{len(order)}"
        response = api.competition_submit(str(upload_archive), message, COMPETITION, quiet=False)
        submission_id = str(getattr(response, "ref", "") or getattr(response, "id", ""))
        if not submission_id:
            raise RuntimeError("Kaggle upload returned no submission ID")
        ledger["submissions"].append({
            "submission_id": submission_id,
            "name": upload_name,
            "mode": args.mode,
            "message": message,
            "uploaded_unix": time.time(),
            "promotion_manifest": str(Path(args.manifest).resolve()),
            "archive_sha256": archive_hash,
            "model_sha256": model_hash,
            "source_commit": manifest["source_commit"],
            "upload_position": position,
        })
        temporary = ledger_path.with_name(ledger_path.name + ".tmp")
        temporary.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
        temporary.replace(ledger_path)
    print(json.dumps({"uploaded": [row[0] for row in order], "submission_ids": [
        row["submission_id"] for row in ledger["submissions"][-len(order):]
    ]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
