#!/usr/bin/env python3
"""Attach raw public observations and full deck identities to loss states."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from scripts.crawl_grim_daily import classify, load_archetype_catalog
from training.lucario_data import canonical_deck, deterministic_gzip_text, sha256_file


def load_rows(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def replay_path(row: dict, live_root: Path, a2_root: Path) -> Path:
    episode_id = row["episode_id"]
    if int(row.get("source_submission_id", 0)) == 55323436:
        return a2_root / f"episode-{episode_id}-replay.json"
    return live_root / str(row["source_submission_id"]) / f"episode-{episode_id}-replay.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elite", default="artifacts/live_grim_corpus_v4/combined_all.jsonl.gz")
    parser.add_argument("--a2-stream", action="append", default=[
        "data/grim_strength_v4/r1_train.jsonl.gz",
        "data/grim_strength_v4/r1_validation.jsonl.gz",
    ])
    parser.add_argument("--live-replays", default="artifacts/live_grim_corpus_v4/replays")
    parser.add_argument("--a2-replays", default="artifacts/recovery_ladder/replays/55323436")
    parser.add_argument("--output", default="data/grim_strength_v4/correction_states.jsonl.gz")
    args = parser.parse_args()
    rows = []
    for row in load_rows(ROOT / args.elite):
        if float(row.get("reward", 0)) == 0:
            row["objective_source"] = "elite_loss_state"
            rows.append(row)
    for stream in args.a2_stream:
        for row in load_rows(ROOT / stream):
            if row.get("objective_source") == "a2_anchor" and float(row.get("reward", 0)) == 0:
                row["objective_source"] = "a2_loss_state"
                rows.append(row)

    catalog = load_archetype_catalog(ROOT / "freshstart" / "decklists")
    live_root, a2_root = ROOT / args.live_replays, ROOT / args.a2_replays
    cache = {}
    enriched = []
    failures = []
    seen = set()
    for row in rows:
        key = (str(row["episode_id"]), int(row["seat"]), int(row["step"]), row["objective_source"])
        if key in seen:
            continue
        seen.add(key)
        path = replay_path(row, live_root, a2_root)
        try:
            if path not in cache:
                cache[path] = json.loads(path.read_text(encoding="utf-8"))
            episode = cache[path]
            step = int(row["step"])
            seat = int(row["seat"])
            observation = episode["steps"][step][seat].get("observation")
            if not observation or not observation.get("search_begin_input"):
                raise ValueError("decision has no searchable public observation")
            decks = [canonical_deck(episode["steps"][1][index].get("action") or []) for index in range(2)]
            if any(len(deck) != 60 for deck in decks):
                raise ValueError("deck handshake is incomplete")
            item = dict(row)
            item.update({
                "observation": observation,
                "hero_deck": list(decks[seat]),
                "opponent_deck": list(decks[1 - seat]),
                "opponent_archetype": classify(decks[1 - seat], catalog),
                "replay_path": str(path.resolve()),
            })
            enriched.append(item)
        except Exception as exc:
            failures.append({"key": key, "error": f"{type(exc).__name__}: {exc}"})
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    with deterministic_gzip_text(output) as handle:
        for row in sorted(enriched, key=lambda item: (
            item.get("hero_order") != "second",
            -(float(item.get("opponent_score_snapshot") or 0)),
            str(item["episode_id"]), int(item["seat"]), int(item["step"]),
        )):
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    manifest = {
        "status": "complete" if not failures else "failed",
        "input_loss_states": len(rows),
        "unique_states": len(seen),
        "enriched_states": len(enriched),
        "failures": len(failures),
        "first_failures": failures[:20],
        "by_source": dict(Counter(row["objective_source"] for row in enriched)),
        "by_actual_order": dict(Counter(str(row.get("hero_order")) for row in enriched)),
        "by_archetype": dict(Counter(str(row.get("opponent_archetype")) for row in enriched)),
        "output": str(output.resolve()),
        "output_sha256": sha256_file(output),
    }
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
