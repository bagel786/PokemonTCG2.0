#!/usr/bin/env python3
"""Wait for order-PPO training and immediately start the gated evaluation phase."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "artifacts" / "order_ppo" / "azure" / "run_manifest.json"
LOG = ROOT / "artifacts" / "order_ppo" / "continuation_manifest.json"


def main() -> int:
    started = time.time()
    while time.time() - started < 6 * 3600:
        if MANIFEST.exists():
            try: state = json.loads(MANIFEST.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError): state = {}
            if state.get("status") == "failed":
                LOG.write_text(json.dumps({"status": "training_failed", "training": state}, indent=2), encoding="utf-8")
                return 2
            if state.get("status") == "complete":
                break
        time.sleep(20)
    else:
        LOG.write_text(json.dumps({"status": "training_timeout"}, indent=2), encoding="utf-8")
        return 3
    # The training orchestrator writes its final manifest immediately before
    # issuing fail-safe deallocations.  Let those asynchronous deallocations
    # settle before the evaluation orchestrator starts the same workers again.
    time.sleep(90)
    result = subprocess.run([sys.executable, "scripts/run_azure_order_evaluation.py"], cwd=ROOT)
    LOG.write_text(json.dumps({"status": "complete" if result.returncode == 0 else "evaluation_stopped",
                               "returncode": result.returncode}, indent=2), encoding="utf-8")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
