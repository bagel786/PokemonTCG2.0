#!/usr/bin/env python3
"""Upload only the promotion-manifest artifacts and append an immutable ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPETITION = "pokemon-tcg-ai-battle"
UPLOAD_CUTOFF_UTC = dt.datetime(2026, 8, 12, 5, 0, tzinfo=dt.timezone.utc)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def planned_upload_window_open(now: dt.datetime | None = None) -> bool:
    observed = now or dt.datetime.now(dt.timezone.utc)
    if observed.tzinfo is None:
        raise ValueError("upload-window timestamp must be timezone-aware")
    return observed.astimezone(dt.timezone.utc) < UPLOAD_CUTOFF_UTC


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="artifacts/recovery_probes/promotion_manifest.json")
    parser.add_argument("--ledger", default="artifacts/recovery_probes/submission_ledger.json")
    args = parser.parse_args()
    if not planned_upload_window_open():
        raise SystemExit("planned upload window closed after 2026-08-11 Central Time")
    manifest = json.loads(Path(args.manifest).read_text())
    if manifest.get("promotion_result") not in {"passed", "control_only"}:
        raise SystemExit("refusing upload: promotion result is neither passed nor control_only")
    order = manifest.get("upload_order")
    expected = [manifest["selected"], "d842_control_exact"] if manifest["selected"] != "d842_control_exact" else ["d842_control_exact"]
    if order != expected:
        raise SystemExit(f"refusing unexpected upload order: {order!r}")
    for name in order:
        path = Path(manifest["archives"][name]["path"])
        if sha256(path) != manifest["archives"][name]["sha256"]:
            raise SystemExit(f"archive hash mismatch: {name}")
    if manifest["archives"]["d842_control_exact"]["sha256"] != "3ECB0BBF119E23C31905E39E19ECA8F6145104AAEFFC0A5675D2FE03855BB458":
        raise SystemExit("exact d842 control hash mismatch")

    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()
    # Read authorization and competition access before any state-changing call.
    api.competition_submissions(COMPETITION, page_size=1)
    builds = json.loads((ROOT / "artifacts" / "recovery_probes" / "build_manifest.json").read_text())
    build_by_name = {row["name"]: row for row in builds["artifacts"]}
    model_hashes = {
        "a1": build_by_name["a1_d842_shield"]["model_sha256"],
        "a2": build_by_name["a2_v2_shield"]["model_sha256"],
        "d842_control_exact": sha256(ROOT / "artifacts" / "recovery_probes" / "extracted" / "control" / "policy_weights.npz"),
    }
    ledger_path = Path(args.ledger)
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {"competition": COMPETITION, "submissions": []}
    for index, name in enumerate(order):
        archive = Path(manifest["archives"][name]["path"])
        message = f"grim-recovery-{name}-{int(time.time())}-{index + 1}of{len(order)}"
        attempts = 3 if name == "d842_control_exact" else 1
        response = None
        for attempt in range(attempts):
            try:
                response = api.competition_submit(str(archive), message, COMPETITION, quiet=False)
                break
            except Exception:
                if attempt + 1 == attempts:
                    raise
                time.sleep(15 * (attempt + 1))
        submission_id = str(getattr(response, "ref", "") or getattr(response, "id", ""))
        ledger["submissions"].append({
            "submission_id": submission_id,
            "name": name,
            "message": message,
            "uploaded_unix": time.time(),
            "promotion_manifest": str(Path(args.manifest).resolve()),
            "archive_sha256": manifest["archives"][name]["sha256"],
            "model_sha256": model_hashes[name],
            "source_commit": manifest["source_commit"],
            "upload_position": index + 1,
        })
        temporary = ledger_path.with_name(ledger_path.name + ".tmp")
        temporary.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
        temporary.replace(ledger_path)
    print(json.dumps({"uploaded": order, "submission_ids": [row["submission_id"] for row in ledger["submissions"][-len(order):]]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
