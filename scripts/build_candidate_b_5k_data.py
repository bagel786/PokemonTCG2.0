#!/usr/bin/env python3
"""Build behavior-matched own-ladder shards for Candidate B.

Only public episodes produced by the exact frozen 5k checkpoint are accepted.
The newest pure-5k submission is held out wholesale.  Episodes already used by
the anti-archetype demonstration shard are excluded from training.  Loss rows
are exported separately as hard-state inputs and are not negative BC labels.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.replay import iter_decisions, load_episode  # noqa: E402
from training.lucario_data import (  # noqa: E402
    canonical_deck,
    deterministic_gzip_text,
    load_deck,
    sha256_file,
)


MODEL_SHA256 = "d842f85abfc44af9f41979f91795e22c92c179b62e04d5a0a2f9c734e70af1c3"
TRAIN_SUBMISSIONS = (55114709, 55171235, 55180261, 55189658, 55198075, 55198084)
HOLDOUT_SUBMISSION = 55222011


def anti_units(path: Path) -> set[tuple[str, int]]:
    result = set()
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            result.add((str(row["episode_id"]), int(row["seat"])))
    return result


def metadata_by_id(directory: Path) -> dict[int, dict]:
    path = directory / "episodes_metadata.json"
    if not path.exists():
        raise FileNotFoundError(f"missing refreshed metadata: {path}")
    return {int(row["id"]): row for row in json.loads(path.read_text()) if "id" in row}


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with deterministic_gzip_text(temporary) as handle:
        for row in sorted(rows, key=lambda value: (
            str(value["episode_id"]), int(value["seat"]), int(value["step"])
        )):
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    temporary.replace(path)


def build(args) -> dict:
    if sha256_file(args.model) != MODEL_SHA256:
        raise RuntimeError("Candidate B base is not the frozen d842f85a 5k checkpoint")
    grim_signature = load_deck(args.deck)
    excluded = anti_units(Path(args.anti_shard))
    replay_root = Path(args.replay_root)
    train_rows = []
    loss_rows = []
    holdout_rows = []
    episodes = {}
    counters = Counter()
    seen_rows = set()

    for submission in (*TRAIN_SUBMISSIONS, HOLDOUT_SUBMISSION):
        directory = replay_root / str(submission)
        metadata = metadata_by_id(directory)
        for episode_id, meta in sorted(metadata.items()):
            if meta.get("type") != "EPISODE_TYPE_PUBLIC":
                counters["non_public_excluded"] += 1
                continue
            agents = meta.get("agents") or []
            seat = next(
                (index for index, agent in enumerate(agents) if int(agent.get("submissionId", -1)) == submission),
                None,
            )
            if seat is None:
                counters["missing_submission_seat"] += 1
                continue
            replay_path = directory / f"episode-{episode_id}-replay.json"
            if not replay_path.exists():
                counters["missing_replay"] += 1
                continue
            episode = load_episode(replay_path)
            steps = episode.get("steps") or []
            if len(steps) < 2 or len(steps[1]) <= seat:
                counters["invalid_replay"] += 1
                continue
            deck = canonical_deck(steps[1][seat].get("action", []))
            if deck != grim_signature:
                counters["deck_mismatch"] += 1
                continue
            unit = (str(episode_id), seat)
            split = "holdout" if submission == HOLDOUT_SUBMISSION else "train"
            if split == "train" and unit in excluded:
                counters["anti_overlap_episodes_excluded"] += 1
                continue

            us = agents[seat]
            them = agents[1 - seat] if len(agents) > 1 else {}
            reward = float(us.get("reward", 0.0))
            unit_rows = []
            for decision in iter_decisions(episode, None, feature_version=2):
                if int(decision.seat) != seat:
                    continue
                row = decision.to_json()
                key = (str(row["episode_id"]), int(row["seat"]), int(row["step"]))
                if key in seen_rows:
                    counters["duplicate_rows_excluded"] += 1
                    continue
                seen_rows.add(key)
                row.update(
                    {
                        "source": "own_5k_ladder",
                        "source_submission_id": submission,
                        "source_model_sha256": MODEL_SHA256,
                        "split": split,
                        "terminal_outcome": reward,
                        "created_at": meta.get("createTime", ""),
                        "opponent_submission_id": them.get("submissionId"),
                        "opponent_initial_score": them.get("initialScore"),
                        "our_initial_score": us.get("initialScore"),
                    }
                )
                unit_rows.append(row)
            if not unit_rows:
                counters["empty_episode"] += 1
                continue

            episodes[f"{episode_id}:{seat}"] = {
                "episode_id": episode_id,
                "seat": seat,
                "submission_id": submission,
                "reward": reward,
                "split": split,
                "decisions": len(unit_rows),
                "created_at": meta.get("createTime", ""),
            }
            counters[f"{split}_episodes"] += 1
            counters[f"{split}_wins" if reward > 0 else f"{split}_losses"] += 1
            counters[f"{split}_seat_{seat}"] += 1
            counters[f"{split}_decisions"] += len(unit_rows)
            if split == "holdout":
                holdout_rows.extend(unit_rows)
            else:
                train_rows.extend(unit_rows)
                if reward < 0:
                    loss_rows.extend(unit_rows)

    output_dir = Path(args.output_dir).resolve()
    train_path = output_dir / "own_5k_rehearsal.jsonl.gz"
    loss_path = output_dir / "own_5k_loss_states.jsonl.gz"
    holdout_path = output_dir / "holdout_55222011.jsonl.gz"
    write_rows(train_path, train_rows)
    write_rows(loss_path, loss_rows)
    write_rows(holdout_path, holdout_rows)

    manifest = {
        "version": 1,
        "purpose": "Candidate B behavior-matched rehearsal, hard-state discovery, and untouched latest-submission holdout",
        "base_model": str(Path(args.model).resolve()),
        "base_model_sha256": MODEL_SHA256,
        "deck": str(Path(args.deck).resolve()),
        "deck_sha256": sha256_file(args.deck),
        "train_submissions": list(TRAIN_SUBMISSIONS),
        "holdout_submission": HOLDOUT_SUBMISSION,
        "anti_shard": str(Path(args.anti_shard).resolve()),
        "anti_shard_sha256": sha256_file(args.anti_shard),
        "counts": dict(sorted(counters.items())),
        "episodes": episodes,
        "outputs": {
            "rehearsal": {"path": str(train_path), "sha256": sha256_file(train_path)},
            "loss_states": {"path": str(loss_path), "sha256": sha256_file(loss_path)},
            "holdout": {"path": str(holdout_path), "sha256": sha256_file(holdout_path)},
        },
        "loss_state_policy": "diagnostic/teacher-target input only; never blanket negative BC labels",
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-root", default="data/replays")
    parser.add_argument("--model", default="artifacts/overnight_grim_20260730/grim_selected.npz")
    parser.add_argument("--deck", default="freshstart/decklists/grimmsnarl_marnie.deck.csv")
    parser.add_argument("--anti-shard", default="artifacts/anti_archetype_20260804/anti_lucario_iono.jsonl.gz")
    parser.add_argument("--output-dir", default="artifacts/candidate_b_20260804/data")
    args = parser.parse_args()
    manifest = build(args)
    print(json.dumps({"counts": manifest["counts"], "outputs": manifest["outputs"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
