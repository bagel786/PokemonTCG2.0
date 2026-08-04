#!/usr/bin/env python3
"""Atomically update the resumable overnight run state."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--status", choices=("running", "complete", "failed", "skipped"), required=True)
    parser.add_argument("--detail", default="{}", help="JSON object merged into the phase record")
    args = parser.parse_args()
    path = Path(args.path)
    payload = json.loads(path.read_text()) if path.exists() else {"version": 1, "started_at": datetime.now(timezone.utc).isoformat(), "phases": {}}
    detail = json.loads(args.detail)
    payload["phases"][args.phase] = {"status": args.status, "updated_at": datetime.now(timezone.utc).isoformat(), **detail}
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)
    print(json.dumps(payload["phases"][args.phase], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
