#!/usr/bin/env python3
"""Create the exact fail-closed shard mapping for the two B finalists."""

from __future__ import annotations

import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATCHUP_GAMES = {
    "d842": 20_000,
    "master_v1": 10_000,
    "replay_refresh": 10_000,
    "v2_2": 10_000,
    "alakazam_2_4a": 2_000,
    "alakazam_2_7": 2_000,
    "lucario": 2_000,
    "crustle": 2_000,
    "ogerpon": 2_000,
    "bellibolt": 2_000,
    "starmie_froslass": 2_000,
}


def pattern(arm: str, opponent: str) -> str:
    return str(ROOT / "artifacts" / "recovery_final_azure" / "shards" / f"full__{arm}__vs__{opponent}__shard_*.json")


def main() -> int:
    screen = json.loads((ROOT / "artifacts" / "recovery_final_azure" / "screen_manifest.json").read_text())
    candidate_manifest = json.loads((ROOT / "artifacts" / "recovery_final" / "candidate_manifest.json").read_text())
    finalists = list(screen["selected"].values())
    if len(finalists) != 2 or len(set(finalists)) != 2:
        raise RuntimeError("screen did not select one distinct finalist per family")
    payload = {"candidates": {}}
    for finalist in finalists:
        if finalist not in candidate_manifest.get("candidates", {}):
            raise RuntimeError(f"screen finalist is absent from candidate manifest: {finalist}")
        matchups = {}
        for opponent, games in MATCHUP_GAMES.items():
            candidate_pattern, control_pattern = pattern(finalist, opponent), pattern("control", opponent)
            expected = games // 500
            candidate_paths, control_paths = glob.glob(candidate_pattern), glob.glob(control_pattern)
            if len(candidate_paths) != expected or len(control_paths) != expected:
                raise RuntimeError(
                    f"incomplete {finalist}/{opponent}: candidate={len(candidate_paths)}, "
                    f"control={len(control_paths)}, expected={expected}"
                )
            matchups[opponent] = {"candidate": candidate_pattern, "control": control_pattern}
        payload["candidates"][finalist] = {
            "model": str(ROOT / "artifacts" / "recovery_final" / "candidates" / finalist / "policy_weights.npz"),
            "d842_name": "d842",
            "grim_opponents": ["master_v1", "replay_refresh", "v2_2"],
            "matchups": matchups,
        }
    output = ROOT / "artifacts" / "recovery_final" / "final_gate_config.json"
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
