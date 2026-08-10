#!/usr/bin/env python3
"""Recover and inventory exact-original-deck Grim games from known submissions.

The first replay of each submission is used only to identify the submitted
deck.  Every episode is downloaded only for submissions whose 60-card deck
matches the frozen original Grim list.  Episode files are immutable inputs;
existing local copies are reused by episode ID.  ``--recover-missing-lineage``
adds explicit reviewed D842 lineage IDs omitted by Kaggle's truncated recent
submission listing; it never infers policy identity from a description or deck.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import shutil
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "grim_5k_history"
COMPETITION = "pokemon-tcg-ai-battle"
D842_LINEAGE = frozenset({
    55114709, 55171235, 55180261, 55189658, 55198075,
    55198084, 55222011, 55246709, 55246712, 55278940,
    55280574, 55280578, 55323437, 55358290, 55358291,
})
HASH_PROVEN_D842 = frozenset({55323437, 55358290, 55358291})
FROZEN_D842_MODEL_SHA256 = "D842F85ABFC44AF9F41979F91795E22C92C179B62E04D5A0A2F9C734E70AF1C3"
PARTIAL_SCHEMA_VERSION = 2


class ReplayRateLimited(RuntimeError):
    """Kaggle replay quota is temporarily exhausted; the run is resumable."""


def _is_http_429(exc: BaseException) -> bool:
    """Recognize Kaggle's differently wrapped replay/listing quota errors."""

    return "429" in repr(exc) or "too many requests" in str(exc).lower()


def call_with_backoff(
    operation: Callable[[], Any],
    *,
    label: str,
    rate_limited: threading.Event,
    attempts: int = 7,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """Retry transient API failures while failing closed immediately on HTTP 429."""

    if rate_limited.is_set():
        raise ReplayRateLimited(f"{label} paused after HTTP 429")
    last: BaseException | None = None
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:  # Kaggle wraps HTTP errors in several exception types.
            last = exc
            if _is_http_429(exc):
                rate_limited.set()
                raise ReplayRateLimited(f"{label} returned HTTP 429") from exc
            if attempt + 1 < attempts:
                sleep(min(30, 2 ** attempt))
    raise RuntimeError(f"{label} failed after {attempts} attempts: {last}") from last


def listed_submission_metadata(submission: Any, position: int) -> dict[str, Any]:
    """Return only metadata actually supplied by the recent-submissions listing."""

    def optional_text(name: str) -> str | None:
        value = getattr(submission, name, None)
        return None if value is None else str(value)

    return {
        "position": position,
        "submission_id": int(submission.ref),
        "description": optional_text("description"),
        "date": optional_text("date"),
        "public_score": getattr(submission, "public_score", None),
        "status": optional_text("status"),
        "submission_listing_metadata": {
            "status": "available",
            "source": "competition_submissions",
        },
    }


def recovered_submission_metadata(submission_id: int) -> dict[str, Any]:
    """Create a work item without fabricating unavailable listing metadata."""

    return {
        "position": None,
        "submission_id": int(submission_id),
        "description": None,
        "date": None,
        "public_score": None,
        "status": None,
        "submission_listing_metadata": {
            "status": "unavailable",
            "source": "explicit_d842_lineage_allowlist",
            "reason": "not_returned_by_recent_submission_listing",
        },
    }


def submission_work_items(
    submissions: Iterable[Any],
    *,
    recover_missing_lineage: bool,
) -> list[dict[str, Any]]:
    """Build a deterministic work list, optionally including unlisted lineage IDs."""

    items: list[dict[str, Any]] = []
    seen: set[int] = set()
    for position, submission in enumerate(submissions, 1):
        metadata = listed_submission_metadata(submission, position)
        submission_id = int(metadata["submission_id"])
        if submission_id in seen:
            continue
        seen.add(submission_id)
        items.append(metadata)
    if recover_missing_lineage:
        items.extend(recovered_submission_metadata(submission_id) for submission_id in sorted(D842_LINEAGE - seen))
    return items


def lineage_evidence(submission_id: int) -> dict[str, Any]:
    """Describe current evidence and a deliberately non-automatic parity promotion."""

    hash_proven = submission_id in HASH_PROVEN_D842
    documented = submission_id in D842_LINEAGE
    policy_lineage = (
        "frozen_d842_hash_proven" if hash_proven
        else "frozen_d842_documented" if documented
        else "other_or_unknown"
    )
    if hash_proven:
        parity = {
            "status": "not_required_hash_proven",
            "promoted": False,
            "promotion_target": None,
            "reference_model_sha256": FROZEN_D842_MODEL_SHA256,
            "evidence": None,
        }
    elif documented:
        parity = {
            "status": "pending_replay_reexecution",
            "promoted": False,
            "promotion_target": "frozen_d842_behavior_parity_proven",
            "reference_model_sha256": FROZEN_D842_MODEL_SHA256,
            "required_evidence": {
                "method": "sterile_replay_reexecution",
                "comparison": "complete_legal_action_digest",
                "require_all_decisions_equal": True,
            },
            "evidence": None,
        }
    else:
        parity = {
            "status": "not_applicable",
            "promoted": False,
            "promotion_target": None,
            "reference_model_sha256": FROZEN_D842_MODEL_SHA256,
            "evidence": None,
        }
    return {"policy_lineage": policy_lineage, "behavior_parity_promotion": parity}


def frozen_deck() -> tuple[int, ...]:
    path = ROOT / "artifacts" / "recovery_probes" / "extracted" / "control" / "deck.csv"
    cards = tuple(int(line) for line in path.read_text().splitlines() if line.strip())
    if len(cards) != 60:
        raise RuntimeError("frozen control deck is not 60 cards")
    return cards


def canonical_hash(cards) -> str:
    payload = ",".join(map(str, sorted(map(int, cards)))).encode("ascii")
    return hashlib.sha256(payload).hexdigest().upper()


def replay_deck(replay: dict, seat: int) -> tuple[int, ...]:
    for step in replay.get("steps") or []:
        if seat >= len(step):
            continue
        action = (step[seat] or {}).get("action")
        if isinstance(action, list) and len(action) == 60 and all(isinstance(x, int) for x in action):
            return tuple(action)
    return ()


def existing_replays(output: Path) -> dict[int, Path]:
    roots = [
        ROOT / "data" / "replays",
        ROOT / "artifacts" / "recovery_ladder" / "replays",
        ROOT / "artifacts" / "wave1_push" / "live" / "replays",
        ROOT / "artifacts" / "live_grim_corpus" / "replays",
        ROOT / "artifacts" / "live_grim_corpus_v4" / "replays",
        ROOT / "artifacts" / "live_grim_corpus_v5" / "replays",
        ROOT / "artifacts" / "flg_grim_corpus_v5_causal" / "replays",
        output,
    ]
    result = {}
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob("**/episode-*-replay.json"):
            try:
                episode = int(path.name.removeprefix("episode-").removesuffix("-replay.json"))
                result.setdefault(episode, path)
            except ValueError:
                continue
    return result


def agent_value(agent, name, default=None):
    return getattr(agent, name, default)


def episode_row(episode, submission_id: int) -> dict | None:
    own = [agent for agent in episode.agents if int(agent.submission_id) == submission_id]
    if len(own) != 1:
        return None
    hero = own[0]
    opponents = [agent for agent in episode.agents if int(agent.index) != int(hero.index)]
    opponent = opponents[0] if len(opponents) == 1 else None
    return {
        "episode_id": int(episode.id),
        "created_utc": str(episode.create_time),
        "seat": int(hero.index),
        "outcome": float(hero.reward),
        "state": str(hero.state),
        "initial_rating": agent_value(hero, "initial_score"),
        "updated_rating": agent_value(hero, "updated_score"),
        "opponent_submission_id": int(opponent.submission_id) if opponent is not None else None,
        "opponent_team": str(opponent.team_name) if opponent is not None else None,
        "opponent_initial_rating": agent_value(opponent, "initial_score") if opponent is not None else None,
        "opponent_updated_rating": agent_value(opponent, "updated_score") if opponent is not None else None,
    }


def actual_order(replay: dict, seat: int) -> str | None:
    for step in replay.get("steps") or []:
        if seat >= len(step):
            continue
        current = ((step[seat] or {}).get("observation") or {}).get("current")
        if current and int(current.get("firstPlayer", -1)) in (0, 1):
            return "first" if int(current["firstPlayer"]) == seat else "second"
    return None


def build_history(
    api: Any,
    *,
    recent_submissions: int,
    workers: int,
    scope: str,
    output: Path,
    recover_missing_lineage: bool = False,
    expected: tuple[int, ...] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Harvest history using an authenticated API object.

    This entry point is intentionally dependency-injected so explicit-lineage
    recovery and rate-limit behavior can be tested without touching Kaggle.
    """

    if recent_submissions <= 0 or workers <= 0:
        raise ValueError("recent_submissions and workers must be positive")
    if scope not in {"d842-lineage", "exact-deck"}:
        raise ValueError(f"unsupported scope: {scope}")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    replay_root = output / "replays"
    replay_root.mkdir(exist_ok=True)
    expected = frozen_deck() if expected is None else tuple(expected)
    if len(expected) != 60:
        raise ValueError("expected deck must contain exactly 60 cards")
    expected_counter = Counter(expected)
    index = existing_replays(output)
    index_lock = threading.Lock()
    replay_rate_limited = threading.Event()
    listing_rate_limited = threading.Event()

    recent_submission_listing_errors: list[dict[str, Any]] = []
    recent_listing_complete = True
    try:
        submissions = list(call_with_backoff(
            lambda: api.competition_submissions(COMPETITION, page_size=100),
            label="recent submission listing",
            rate_limited=listing_rate_limited,
            sleep=sleep,
        ))[:recent_submissions]
    except Exception as exc:
        recent_listing_complete = False
        submissions = []
        recent_submission_listing_errors.append({
            "error": repr(exc),
            "retryable": isinstance(exc, ReplayRateLimited) or _is_http_429(exc),
        })
    work_items = submission_work_items(
        submissions,
        recover_missing_lineage=recover_missing_lineage,
    )
    listed_ids = {int(item.ref) for item in submissions}
    recovered_ids = sorted(D842_LINEAGE - listed_ids) if recover_missing_lineage else []
    inventory: list[dict[str, Any]] = []
    download_errors: list[dict[str, Any]] = []
    episode_listing_errors: list[dict[str, Any]] = []

    def partial_payload() -> dict[str, Any]:
        processed = {int(row["submission_id"]) for row in inventory}
        planned = [int(item["submission_id"]) for item in work_items]
        return {
            "schema_version": PARTIAL_SCHEMA_VERSION,
            "expected_deck_canonical_sha256": canonical_hash(expected),
            "recent_submission_count_requested": recent_submissions,
            # Retain the original field for existing offline consumers.
            "recent_submission_count": recent_submissions,
            "recent_submission_count_returned": len(submissions) if recent_listing_complete else None,
            "recent_submission_listing_complete": recent_listing_complete,
            "scope": scope,
            "explicit_lineage_recovery": recover_missing_lineage,
            "lineage_allowlist_submission_ids": sorted(D842_LINEAGE),
            "listed_lineage_submission_ids": sorted(D842_LINEAGE & listed_ids),
            "recovered_lineage_submission_ids": recovered_ids,
            "planned_submission_ids": planned,
            "processed_submission_ids": [submission_id for submission_id in planned if submission_id in processed],
            "pending_submission_ids": [submission_id for submission_id in planned if submission_id not in processed],
            "replay_rate_limited": replay_rate_limited.is_set(),
            "episode_listing_rate_limited": listing_rate_limited.is_set(),
            "submissions": inventory,
            "recent_submission_listing_errors": recent_submission_listing_errors,
            "download_errors": download_errors,
            "episode_listing_errors": episode_listing_errors,
        }

    def checkpoint() -> None:
        # Atomic replacement avoids leaving malformed JSON if a run is interrupted.
        target = output / "manifest.partial.json"
        staging = output / "manifest.partial.json.tmp"
        staging.write_text(json.dumps(partial_payload(), indent=2), encoding="utf-8")
        staging.replace(target)

    # Create a useful resume ledger before the first potentially expensive query.
    checkpoint()

    def acquire(episode_id: int, target: Path) -> Path:
        destination = target / f"episode-{episode_id}-replay.json"
        if destination.exists():
            return destination
        with index_lock:
            source = index.get(episode_id)
        if source is not None and source.exists():
            shutil.copy2(source, destination)
            return destination
        if replay_rate_limited.is_set():
            raise ReplayRateLimited("replay acquisition paused after HTTP 429")

        def download() -> Path:
            api.competition_episode_replay(episode_id, path=str(target), quiet=True)
            if not destination.exists():
                candidates = list(target.glob(f"*{episode_id}*.json"))
                if len(candidates) == 1:
                    candidates[0].replace(destination)
            if not destination.exists():
                raise FileNotFoundError(f"Kaggle did not create replay {episode_id}")
            return destination

        downloaded = call_with_backoff(
            download,
            label=f"replay acquisition for episode {episode_id}",
            rate_limited=replay_rate_limited,
            sleep=sleep,
        )
        with index_lock:
            index[episode_id] = downloaded
        return downloaded

    for item in work_items:
        submission_id = int(item["submission_id"])
        base_metadata = dict(item)
        base_metadata.update(lineage_evidence(submission_id))
        if scope == "d842-lineage" and submission_id not in D842_LINEAGE:
            inventory.append({
                **base_metadata,
                "rated_episodes": None,
                "wins": None,
                "losses": None,
                "deck_class": "not_probed_outside_scope",
                "episodes": [],
            })
            checkpoint()
            print(json.dumps({"submission": submission_id, "class": "outside_d842_lineage"}), flush=True)
            continue

        try:
            episodes = list(call_with_backoff(
                lambda submission_id=submission_id: api.competition_list_episodes(submission_id),
                label=f"episode listing for submission {submission_id}",
                rate_limited=listing_rate_limited,
                sleep=sleep,
            ))
        except Exception as exc:
            pending = {
                "submission_id": submission_id,
                "error": repr(exc),
                "retryable": isinstance(exc, ReplayRateLimited) or _is_http_429(exc),
            }
            episode_listing_errors.append(pending)
            inventory.append({
                **base_metadata,
                "rated_episodes": None,
                "wins": None,
                "losses": None,
                "deck_class": "pending_episode_listing",
                "episodes": [],
            })
            checkpoint()
            print(json.dumps({
                "submission": submission_id,
                "class": "pending_episode_listing",
                "error": type(exc).__name__,
            }), flush=True)
            continue

        episodes.sort(key=lambda row: str(getattr(row, "create_time", "")))
        rows = [row for episode in episodes if (row := episode_row(episode, submission_id)) is not None]
        base = {
            **base_metadata,
            "rated_episodes": len(rows),
            "wins": sum(row["outcome"] > 0 for row in rows),
            "losses": sum(row["outcome"] < 0 for row in rows),
        }
        if not rows:
            inventory.append({**base, "deck_class": "no_episodes", "episodes": []})
            checkpoint()
            print(json.dumps({"submission": submission_id, "class": "no_episodes"}), flush=True)
            continue

        target = replay_root / str(submission_id)
        target.mkdir(exist_ok=True)
        try:
            probe = acquire(rows[0]["episode_id"], target)
        except Exception as exc:
            pending = {
                "submission_id": submission_id,
                "episode_id": rows[0]["episode_id"],
                "error": repr(exc),
                "retryable": isinstance(exc, ReplayRateLimited) or _is_http_429(exc),
            }
            download_errors.append(pending)
            inventory.append({**base, "deck_class": "pending_replay_probe", "episodes": rows})
            checkpoint()
            print(json.dumps({
                "submission": submission_id, "class": "pending_replay_probe",
                "games": len(rows), "error": type(exc).__name__,
            }), flush=True)
            # A replay 429 must stop further replay calls, but episode listings
            # continue so every explicit lineage ID can still be inventoried.
            continue
        replay = json.loads(probe.read_text(encoding="utf-8"))
        deck = replay_deck(replay, rows[0]["seat"])
        exact = len(deck) == 60 and Counter(deck) == expected_counter
        grim_variant = len(deck) == 60 and 648 in deck
        deck_class = "exact_original_grim" if exact else "grim_variant" if grim_variant else "other"
        base.update({
            "deck_class": deck_class,
            "deck_canonical_sha256": canonical_hash(deck) if deck else None,
            "deck": list(deck),
        })
        if not exact:
            inventory.append({**base, "episodes": rows[:1]})
            checkpoint()
            print(json.dumps({"submission": submission_id, "class": deck_class, "games": len(rows)}), flush=True)
            continue

        def fetch(row):
            try:
                path = acquire(row["episode_id"], target)
                replay_data = json.loads(path.read_text(encoding="utf-8"))
                observed = replay_deck(replay_data, row["seat"])
                if Counter(observed) != expected_counter:
                    raise RuntimeError("episode deck changed within submission")
                return {
                    **row, "actual_order": actual_order(replay_data, row["seat"]),
                    "replay": str(path), "replay_bytes": path.stat().st_size,
                }, None
            except Exception as exc:
                return row, {"submission_id": submission_id, "episode_id": row["episode_id"], "error": repr(exc)}

        completed = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for row, error in pool.map(fetch, rows):
                completed.append(row)
                if error:
                    download_errors.append(error)
        inventory.append({**base, "episodes": completed})
        print(json.dumps({
            "submission": submission_id, "class": deck_class, "games": len(rows),
            "downloaded": sum("replay" in row for row in completed), "errors": len(rows) - sum("replay" in row for row in completed),
        }), flush=True)
        checkpoint()
        if replay_rate_limited.is_set():
            print(json.dumps({
                "status": "paused_rate_limit",
                "message": "rerun later; all completed replay files are reusable",
            }), flush=True)

    exact_rows = [row for row in inventory if row["deck_class"] == "exact_original_grim"]
    manifest = {
        "schema_version": PARTIAL_SCHEMA_VERSION,
        "created_unix": time.time(),
        "competition": COMPETITION,
        "expected_deck": list(expected),
        "expected_deck_canonical_sha256": canonical_hash(expected),
        "recent_submission_count": recent_submissions,
        "recent_submission_count_requested": recent_submissions,
        "recent_submission_count_returned": len(submissions) if recent_listing_complete else None,
        "recent_submission_listing_complete": recent_listing_complete,
        "scope": scope,
        "explicit_lineage_recovery": recover_missing_lineage,
        "lineage_allowlist_submission_ids": sorted(D842_LINEAGE),
        "listed_lineage_submission_ids": sorted(D842_LINEAGE & listed_ids),
        "recovered_lineage_submission_ids": recovered_ids,
        "exact_deck_submissions": len(exact_rows),
        "exact_deck_games": sum(row["rated_episodes"] for row in exact_rows),
        "exact_deck_wins": sum(row["wins"] for row in exact_rows),
        "exact_deck_losses": sum(row["losses"] for row in exact_rows),
        "d842_lineage_submissions": sum(row["submission_id"] in D842_LINEAGE for row in exact_rows),
        "d842_lineage_games": sum(row["rated_episodes"] for row in exact_rows if row["submission_id"] in D842_LINEAGE),
        "recent_submission_listing_errors": recent_submission_listing_errors,
        "download_errors": download_errors,
        "episode_listing_errors": episode_listing_errors,
        "submissions": inventory,
        "passed": (
            not recent_submission_listing_errors
            and not download_errors
            and not episode_listing_errors
            and sum(row["rated_episodes"] for row in exact_rows) > 0
        ),
    }
    checkpoint()
    target = output / "manifest.json"
    target.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({
        "manifest": str(target), "exact_deck_submissions": manifest["exact_deck_submissions"],
        "exact_deck_games": manifest["exact_deck_games"], "download_errors": len(download_errors),
        "passed": manifest["passed"],
    }), flush=True)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recent-submissions", type=int, default=35)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--scope", choices=("d842-lineage", "exact-deck"), default="d842-lineage")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--recover-missing-lineage",
        action="store_true",
        help=(
            "directly query episodes for every explicit D842 lineage ID omitted "
            "from the recent-submissions response"
        ),
    )
    args = parser.parse_args()
    if args.recent_submissions <= 0 or args.workers <= 0:
        parser.error("recent-submissions and workers must be positive")

    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()
    manifest = build_history(
        api,
        recent_submissions=args.recent_submissions,
        workers=args.workers,
        scope=args.scope,
        output=args.output,
        recover_missing_lineage=args.recover_missing_lineage,
    )
    return 0 if manifest["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
