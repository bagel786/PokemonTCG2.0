#!/usr/bin/env python3
"""Build a bounded, de-duplicated fresh Dipplin expert replay manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").is_dir():
    sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.dipplin.cards import DECK_MULTISET_SHA256  # noqa: E402
from scripts.crawl_grim_daily import classify, load_archetype_catalog  # noqa: E402
from scripts.dipplin_eval_common import (  # noqa: E402
    analyze_episode,
    canonical_deck_hash,
    replay_decks,
    sha256_file,
)
from scripts.parse_live_episodes import auth_header  # noqa: E402


LIST_EPISODES = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"
KAGGLE = Path("/Users/safiullahbaig/Library/Python/3.11/bin/kaggle")
SCHEMA = "dipplin-expert-fresh-manifest-v1"
SOURCES = (
    {"submission_id": 55408594, "pilot": "PP kawada", "priority": 1, "target": 18, "list_relation": "exact_60"},
    {"submission_id": 55404784, "pilot": "BluesLeeTW", "priority": 2, "target": 51, "list_relation": "similar_thwackey_dipplin"},
    {"submission_id": 55430091, "pilot": "西松大祐", "priority": 3, "target": 51, "list_relation": "similar_thwackey_dipplin"},
)


def _integer(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _fetch(submission_id: int) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        LIST_EPISODES,
        data=json.dumps({"submissionId": submission_id}).encode(),
        headers={"Content-Type": "application/json", "Authorization": auth_header(), "User-Agent": "DipplinFresh/1"},
    )
    with urllib.request.urlopen(request, context=ssl._create_unverified_context(), timeout=60) as response:
        payload = json.loads(response.read().decode())
    episodes = (payload.get("result") or {}).get("episodes") or payload.get("episodes") or []
    if not isinstance(episodes, list):
        raise RuntimeError(f"ListEpisodes({submission_id}) returned no list")
    return episodes


def _known_episode_ids(exclude_root: Path | None = None) -> set[int]:
    result: set[int] = set()
    for path in ROOT.rglob("episode-*-replay.json"):
        if exclude_root is not None:
            try:
                path.resolve().relative_to(exclude_root.resolve())
                continue
            except ValueError:
                pass
        token = path.name.removeprefix("episode-").removesuffix("-replay.json")
        if token.isdigit():
            result.add(int(token))
    for path in (
        ROOT / "data/dipplin_replay_eval/seed_inventory.json",
        ROOT / "data/dipplin_replay_eval/frozen/validation_manifest.json",
        ROOT / "data/dipplin_replay_eval/frozen/final_holdout_manifest.json",
    ):
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        stack = [payload]
        while stack:
            value = stack.pop()
            if isinstance(value, Mapping):
                if isinstance(value.get("episode_id"), int):
                    result.add(int(value["episode_id"]))
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
    return result


def _hero_seat(metadata: Mapping[str, Any], submission_id: int) -> int:
    agents = metadata.get("agents") or []
    seats = [index for index, agent in enumerate(agents) if _integer(agent.get("submissionId")) == submission_id]
    if len(seats) != 1:
        raise RuntimeError(f"episode {metadata.get('id')} has {len(seats)} hero seats")
    return seats[0]


def _download(episode_id: int, target: Path) -> None:
    if target.is_file() and target.stat().st_size:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(5):
        with tempfile.TemporaryDirectory(dir=target.parent, prefix=f".episode-{episode_id}.") as raw:
            result = subprocess.run(
                [str(KAGGLE), "competitions", "replay", str(episode_id), "-p", raw],
                capture_output=True,
                text=True,
            )
            downloaded = Path(raw) / target.name
            if result.returncode == 0 and downloaded.is_file() and downloaded.stat().st_size:
                os.replace(downloaded, target)
                return
        time.sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"failed to download episode {episode_id}")


def _prize_structure(deck: Sequence[int]) -> str:
    # The manifest records a coarse deck-level label. The evaluator derives a
    # state-level public label again at ENGINE_ONLINE, which is authoritative.
    from cg.api import all_card_data

    table = {int(card.cardId): card for card in all_card_data()}
    values: list[int] = []
    for card_id in set(map(int, deck)):
        card = table.get(card_id)
        if card is None:
            continue
        if bool(getattr(card, "megaEx", False)):
            values.append(3)
        elif bool(getattr(card, "ex", False)):
            values.append(2)
        else:
            values.append(1)
    if 3 in values:
        return "three_prize_mega_or_mixed"
    if 2 in values:
        return "two_prize_ex_or_mixed"
    return "single_prize"


def _assign_splits(rows: list[dict[str, Any]]) -> None:
    targets = {"DEV": round(len(rows) * 0.60), "VALIDATION": round(len(rows) * 0.25)}
    targets["SEALED"] = len(rows) - targets["DEV"] - targets["VALIDATION"]
    fields = ("actual_order", "opening_active", "opponent_archetype", "expert_result", "list_relation")
    totals = Counter((field, str(row[field])) for row in rows for field in fields)
    assigned = Counter()
    category_assigned = Counter()
    ratios = {split: target / len(rows) for split, target in targets.items()}

    # Place rare-category episodes first, then minimize the incremental global
    # squared error from each split's proportional marginal targets.  This is
    # deterministic, episode-wise, capacity-exact, and remains usable when a
    # composite stratum has only one member.
    ordered = sorted(
        rows,
        key=lambda row: (
            -sum(1 / totals[(field, str(row[field]))] for field in fields),
            hashlib.sha256(str(row["episode_id"]).encode()).hexdigest(),
        ),
    )
    for row in ordered:
        categories = [(field, str(row[field])) for field in fields]
        choices: list[tuple[float, str]] = []
        for split, capacity in targets.items():
            if assigned[split] >= capacity:
                continue
            score = 0.0
            capacity_target = float(capacity)
            before_capacity = assigned[split]
            score += ((before_capacity + 1 - capacity_target) ** 2 - (before_capacity - capacity_target) ** 2) / capacity_target
            for category in categories:
                target = totals[category] * ratios[split]
                before = category_assigned[(split, category)]
                score += ((before + 1 - target) ** 2 - (before - target) ** 2) / max(1.0, target)
            choices.append((score, split))
        _, split = min(choices)
        row["split"] = split
        assigned[split] += 1
        for category in categories:
            category_assigned[(split, category)] += 1
    if assigned != Counter(targets):
        raise RuntimeError(f"split allocation mismatch: {assigned} != {targets}")


def build(*, output: Path, acquire: bool) -> dict[str, Any]:
    output = output.resolve()
    replay_dir = output.parent / "replays"
    known = _known_episode_ids(replay_dir)
    catalog = load_archetype_catalog(ROOT / "freshstart/decklists")
    selected: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    source_summary: list[dict[str, Any]] = []
    for source in SOURCES:
        history = _fetch(int(source["submission_id"]))
        candidates = [row for row in history if _integer(row.get("id")) not in known]
        candidates.sort(key=lambda row: (str(row.get("createTime") or ""), _integer(row.get("id"))), reverse=True)
        chosen = candidates[: int(source["target"])]
        if len(chosen) != int(source["target"]):
            raise RuntimeError(f"source {source['submission_id']} has only {len(chosen)} unused episodes")
        selected.extend((source, row) for row in chosen)
        source_summary.append({
            **source,
            "history_count": len(history),
            "unused_before_selection": len(candidates),
            "selected": len(chosen),
        })

    if acquire:
        for index, (_source, metadata) in enumerate(selected, 1):
            episode_id = _integer(metadata.get("id"))
            _download(episode_id, replay_dir / f"episode-{episode_id}-replay.json")
            if index % 20 == 0:
                print(f"downloaded/verified {index}/{len(selected)}", flush=True)

    rows: list[dict[str, Any]] = []
    for source, metadata in selected:
        episode_id = _integer(metadata.get("id"))
        path = replay_dir / f"episode-{episode_id}-replay.json"
        if not path.is_file():
            raise RuntimeError(f"missing replay {episode_id}; rerun with --acquire")
        replay = json.loads(path.read_text(encoding="utf-8"))
        seat = _hero_seat(metadata, int(source["submission_id"]))
        decks = replay_decks(replay)
        hero_hash = canonical_deck_hash(decks[seat])
        opponent_hash = canonical_deck_hash(decks[1 - seat])
        agents = metadata.get("agents") or []
        hero_agent, opponent_agent = agents[seat], agents[1 - seat]
        # Use the common analyzer to derive order/opening with the same public
        # definitions consumed downstream.
        from scripts.dipplin_eval_common import ReplaySpec
        diagnostic = analyze_episode(ReplaySpec(
            dataset="fresh_expert", split="UNASSIGNED", episode_id=episode_id, path=path,
            hero_seat=seat, pilot=str(source["pilot"]), submission_id=int(source["submission_id"]),
            opponent_archetype=classify(tuple(sorted(decks[1 - seat])), catalog),
            opponent_prize_structure=None, exact_deck_hash=hero_hash,
            source_timestamp=metadata.get("createTime"), metadata={},
        ))
        hero_reward = hero_agent.get("reward")
        opponent_reward = opponent_agent.get("reward")
        result = "win" if hero_reward > opponent_reward else "loss"
        rows.append({
            "episode_id": episode_id,
            "submission_id": int(source["submission_id"]),
            "pilot": source["pilot"],
            "list_relation": source["list_relation"],
            "exact_deck_hash": hero_hash,
            "exact_pp_kawada_60": hero_hash == DECK_MULTISET_SHA256,
            "opponent_submission_id": _integer(opponent_agent.get("submissionId")),
            "opponent_team": _integer(opponent_agent.get("teamId")),
            "opponent_archetype": diagnostic["opponent_archetype"],
            "opponent_deck_hash": opponent_hash,
            "opponent_prize_structure": _prize_structure(decks[1 - seat]),
            "opponent_initial_rating": opponent_agent.get("initialScore"),
            "opponent_rank": None,
            "expert_result": result,
            "actual_first_second": diagnostic["actual_order"],
            "actual_order": diagnostic["actual_order"],
            "opening_active": diagnostic["opening_bucket"],
            "hero": {
                "seat": seat,
                "submission_id": int(source["submission_id"]),
                "team_id": _integer(hero_agent.get("teamId")),
                "pilot": source["pilot"],
                "deck_sha256": hero_hash,
                "actual_order": diagnostic["actual_order"],
            },
            "opponent": {
                "seat": 1 - seat,
                "submission_id": _integer(opponent_agent.get("submissionId")),
                "team_id": _integer(opponent_agent.get("teamId")),
                "archetype": diagnostic["opponent_archetype"],
                "prize_structure": _prize_structure(decks[1 - seat]),
                "deck_sha256": opponent_hash,
                "initial_rating": opponent_agent.get("initialScore"),
            },
            "source_timestamp": metadata.get("createTime"),
            "replay_cache_path": str(path.relative_to(ROOT)),
            "replay_sha256": sha256_file(path),
        })
    _assign_splits(rows)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "schema_version": 1,
        "dataset": "dipplin_expert_fresh_20260813",
        "created_from_starting_sha": "a2ad27fec34e0e38e177a650b498cf1e6ea52e4a",
        "contamination_contract": {
            "known_local_or_prior_manifest_episode_count": len(known),
            "selected_episode_overlap_with_known": 0,
            "pp_kawada_prior_88_replays_excluded": True,
            "prior_80_episode_frozen_corpus_reused": False,
        },
        "selection": {
            "bounded": True,
            "requested_total": sum(int(source["target"]) for source in SOURCES),
            "selected_total": len(rows),
            "sources": source_summary,
        },
        "split_counts": dict(sorted(Counter(row["split"] for row in rows).items())),
        "coverage": {
            "actual_order": dict(sorted(Counter(row["actual_order"] for row in rows).items())),
            "opening_active": dict(sorted(Counter(row["opening_active"] for row in rows).items())),
            "opponent_archetype": dict(sorted(Counter(row["opponent_archetype"] for row in rows).items())),
            "expert_result": dict(sorted(Counter(row["expert_result"] for row in rows).items())),
            "exact_pp_kawada_60": sum(row["exact_pp_kawada_60"] for row in rows),
        },
        "sealed_policy": {
            "individual_failure_inspection_permitted_during_development": False,
            "aggregate_evaluation_only_until_candidate_frozen": True,
        },
        "episodes": sorted(rows, key=lambda row: row["episode_id"]),
    }
    unsigned = dict(payload)
    payload["manifest_payload_sha256"] = hashlib.sha256(_canonical(unsigned)).hexdigest()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/dipplin_expert_fresh/manifest.json")
    parser.add_argument("--acquire", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build(output=args.output, acquire=args.acquire)
    print(json.dumps({"episodes": len(payload["episodes"]), "splits": payload["split_counts"], "coverage": payload["coverage"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
