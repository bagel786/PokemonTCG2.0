#!/usr/bin/env python3
"""Mine local daily-dump episodes for exact-Grim winning decisions with the
PLAY-identity fix enabled (v2 schema, identity-bound trainer data)."""
from __future__ import annotations

import gzip
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
sys.path.insert(0, str(ROOT / "vendor"))

import ptcg_ai.features as _f  # noqa: E402
_f.PLAY_IDENTITY_ENABLED = True

from scripts.mine_daily_grim import mine_episode, deck_hash  # noqa: E402
from training.lucario_data import canonical_deck, deterministic_gzip_text  # noqa: E402

DATE = "2026-08-15"
DUMP = ROOT / "data" / "daily_dumps" / DATE
OUT = ROOT / "artifacts" / "final_sprint" / "identity_train"
OUT.mkdir(parents=True, exist_ok=True)
DECK = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"
grim_signature = canonical_deck([int(x) for x in DECK.read_text().split() if x.strip()])
print("grim signature deck:", len(grim_signature), "cards", flush=True)


def main() -> int:
    files = sorted(DUMP.glob("*.json"))
    print("episode files:", len(files), flush=True)
    rows_out = OUT / "decisions_0815.jsonl.gz"
    units = []
    row_count = 0
    statuses = Counter()
    with gzip.open(rows_out, "wt", encoding="utf-8") as handle:
        for i, path in enumerate(files):
            try:
                result = mine_episode(path, grim_signature, "daily_top_episode", DATE)
            except Exception as exc:
                statuses["error"] += 1
                if statuses["error"] <= 3:
                    print("  err", path.name, type(exc).__name__, str(exc)[:80], flush=True)
                path.unlink(missing_ok=True)
                continue
            statuses[result["status"]] += 1
            units.extend(result["units"])
            for row in result["rows"]:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                row_count += 1
            path.unlink(missing_ok=True)
            if (i + 1) % 500 == 0:
                print(f"  {i+1}/{len(files)} rows={row_count}", flush=True)
    print("statuses:", dict(statuses), flush=True)
    print("rows:", row_count, "units:", len(units), flush=True)
    (OUT / "units_0815.jsonl").write_text("\n".join(json.dumps(u, sort_keys=True) for u in units))
    manifest = {
        "date": DATE,
        "play_identity_fix": True,
        "feature_version": 2,
        "rows": row_count,
        "units": len(units),
        "statuses": dict(statuses),
        "unit_seats": Counter(u["seat"] for u in units),
        "mirror_units": sum(1 for u in units if u["opponent_exact_grim"]),
    }
    manifest["unit_seats"] = dict(manifest["unit_seats"])
    (OUT / "mining_manifest_0815.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    print(json.dumps(manifest, indent=1, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
