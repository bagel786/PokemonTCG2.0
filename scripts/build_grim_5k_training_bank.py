#!/usr/bin/env python3
"""Build a leakage-resistant whole-episode bank for frozen-d842 Grim games.

This is deliberately an offline processor.  It consumes only the public replay
inventory produced by ``build_grim_5k_history.py`` and never calls Kaggle (or any
other network service).  A row in an output shard is an episode/team unit, not a
decision.  Downstream feature extraction must therefore keep every decision from
that unit in the row's assigned split.

The untouched holdout is protected in two ways:

* every occurrence of an opponent team is assigned atomically; and
* duplicate/mirror entries for one episode are unioned before assignment.

The resulting connected components are greedily balanced 60/20/20 across actual
play order and opponent-rating buckets.  The allocator and gzip output are fully
deterministic, so adding a partial download produces an auditable new bank rather
than silently claiming that the source inventory was complete.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HISTORY = ROOT / "artifacts" / "grim_5k_history"
DEFAULT_MANIFEST = DEFAULT_HISTORY / "manifest.partial.json"
DEFAULT_REPLAY_ROOT = DEFAULT_HISTORY / "replays"
DEFAULT_OUTPUT = ROOT / "artifacts" / "grim_5k_training_bank"
DEFAULT_DECK = ROOT / "artifacts" / "recovery_probes" / "extracted" / "control" / "deck.csv"
DEFAULT_ARCHETYPES = ROOT / "freshstart" / "decklists"

SCHEMA_VERSION = 1
FROZEN_D842_MODEL_SHA256 = "D842F85ABFC44AF9F41979F91795E22C92C179B62E04D5A0A2F9C734E70AF1C3"
FROZEN_GRIM_DECK_CANONICAL_SHA256 = "C20A8A46F5C635773754F03103652F5C534B13DC622448ED2255A97234C103AF"

# This is intentionally not inferred from descriptions or deck identity.  These
# IDs are the reviewed frozen-d842 lineage recorded by the history harvester.
D842_LINEAGE = frozenset({
    55114709,
    55171235,
    55180261,
    55189658,
    55198075,
    55198084,
    55222011,
    55246709,
    55246712,
    55278940,
    55280574,
    55280578,
    55323437,
    55358290,
    55358291,
})
HASH_PROVEN_D842 = frozenset({55323437, 55358290, 55358291})
ALLOWED_LINEAGE_LABELS = frozenset({"frozen_d842_hash_proven", "frozen_d842_documented"})

SPLIT_WEIGHTS = {
    "development": 0.60,
    "calibration": 0.20,
    "untouched_holdout": 0.20,
}
SPLIT_NAMES = tuple(SPLIT_WEIGHTS)
RATING_BUCKETS = (
    "<650",
    "650-749",
    "750-849",
    "850-899",
    "900-949",
    "950+",
    "unknown",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def stable_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_deck(cards: Iterable[Any]) -> tuple[int, ...]:
    try:
        result = tuple(sorted(int(card) for card in cards))
    except (TypeError, ValueError):
        return ()
    return result if len(result) == 60 else ()


def deck_hash(cards: Iterable[Any]) -> str | None:
    deck = canonical_deck(cards)
    if not deck:
        return None
    payload = ",".join(map(str, deck)).encode("ascii")
    return hashlib.sha256(payload).hexdigest().upper()


def load_deck(path: Path) -> tuple[int, ...]:
    deck = canonical_deck(line for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    if not deck:
        raise ValueError(f"expected exactly 60 integer cards in {path}")
    return deck


def load_archetype_catalog(directory: Path) -> dict[str, tuple[int, ...]]:
    catalog: dict[str, tuple[int, ...]] = {}
    if not directory.exists():
        return catalog
    for path in sorted(directory.glob("*.deck.csv")):
        try:
            catalog[path.name.removesuffix(".deck.csv")] = load_deck(path)
        except (OSError, ValueError):
            continue
    return catalog


def classify_matchup(deck: tuple[int, ...], catalog: Mapping[str, tuple[int, ...]]) -> tuple[str, str, float]:
    """Return ``(name, evidence, multiset_jaccard)`` for an opponent deck."""
    if not deck:
        return "unknown", "missing_deck", 0.0
    for name, signature in sorted(catalog.items()):
        if deck == signature:
            return name, "exact_signature", 1.0
    counts = Counter(deck)
    best_name, best_score = "other", 0.0
    for name, signature in sorted(catalog.items()):
        other = Counter(signature)
        overlap = sum((counts & other).values())
        union = sum((counts | other).values())
        score = overlap / union if union else 0.0
        if score > best_score:
            best_name, best_score = name, score
    if best_score >= 0.55:
        return best_name, "nearest_signature", round(best_score, 6)
    return "other", "below_similarity_threshold", round(best_score, 6)


def parse_rating(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def rating_bucket(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value < 650:
        return "<650"
    if value < 750:
        return "650-749"
    if value < 850:
        return "750-849"
    if value < 900:
        return "850-899"
    if value < 950:
        return "900-949"
    return "950+"


def normalize_team(value: Any) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", str(value)).casefold()
    normalized = " ".join(normalized.split())
    if not normalized or normalized in {"unknown", "none", "null", "seat-0", "seat-1"}:
        return None
    return normalized


def load_json(path: Path) -> dict[str, Any]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return payload


def replay_decks(replay: Mapping[str, Any]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    found: list[tuple[int, ...]] = [(), ()]
    for step in replay.get("steps") or []:
        if not isinstance(step, list):
            continue
        for seat in (0, 1):
            if found[seat] or seat >= len(step) or not isinstance(step[seat], dict):
                continue
            action = step[seat].get("action")
            if isinstance(action, list) and len(action) == 60:
                found[seat] = canonical_deck(action)
        if all(found):
            break
    return found[0], found[1]


def replay_episode_id(replay: Mapping[str, Any]) -> str | None:
    info = replay.get("info") or {}
    value = info.get("EpisodeId", replay.get("id")) if isinstance(info, dict) else replay.get("id")
    return None if value is None else str(value)


def actual_first_player(replay: Mapping[str, Any]) -> int | None:
    observed: set[int] = set()
    for step in replay.get("steps") or []:
        if not isinstance(step, list):
            continue
        for row in step[:2]:
            if not isinstance(row, dict):
                continue
            observation = row.get("observation") or {}
            current = observation.get("current") or {} if isinstance(observation, dict) else {}
            value = current.get("firstPlayer") if isinstance(current, dict) else None
            if value in (0, 1):
                observed.add(int(value))
    return next(iter(observed)) if len(observed) == 1 else None


def terminal_target(replay: Mapping[str, Any], seat: int) -> int | None:
    rewards = replay.get("rewards")
    if isinstance(rewards, list) and len(rewards) >= 2:
        own, other = rewards[seat], rewards[1 - seat]
        if (
            isinstance(own, (int, float)) and not isinstance(own, bool)
            and isinstance(other, (int, float)) and not isinstance(other, bool)
            and math.isfinite(float(own)) and math.isfinite(float(other)) and own != other
        ):
            return int(float(own) > float(other))
    for step in reversed(replay.get("steps") or []):
        if not isinstance(step, list):
            continue
        for row in step[:2]:
            observation = row.get("observation") or {} if isinstance(row, dict) else {}
            current = observation.get("current") or {} if isinstance(observation, dict) else {}
            winner = current.get("result") if isinstance(current, dict) else None
            if winner in (0, 1):
                return int(int(winner) == seat)
    return None


def is_explicitly_public(episode_row: Mapping[str, Any], replay: Mapping[str, Any]) -> bool:
    """Reject explicit private/local provenance; manifest membership proves public origin."""
    containers: list[Mapping[str, Any]] = [episode_row, replay]
    info = replay.get("info")
    if isinstance(info, dict):
        containers.append(info)
    for container in containers:
        for key in ("public", "is_public", "isPublic"):
            if key in container and container[key] is False:
                return False
        for key in ("private", "is_private", "isPrivate"):
            if container.get(key) is True:
                return False
        visibility = str(container.get("visibility", "")).strip().casefold()
        if visibility in {"private", "local", "selfplay", "self-play"}:
            return False
    return True


def replay_teams(replay: Mapping[str, Any]) -> tuple[str | None, str | None]:
    info = replay.get("info") or {}
    teams = info.get("TeamNames") if isinstance(info, dict) else None
    if not isinstance(teams, list) or len(teams) < 2:
        return None, None
    return str(teams[0]), str(teams[1])


def hero_decision_count(replay: Mapping[str, Any], seat: int) -> int:
    steps = replay.get("steps") or []
    count = 0
    for index in range(max(0, len(steps) - 1)):
        current, following = steps[index], steps[index + 1]
        if not isinstance(current, list) or not isinstance(following, list):
            continue
        if seat >= len(current) or seat >= len(following):
            continue
        row = current[seat] if isinstance(current[seat], dict) else {}
        next_row = following[seat] if isinstance(following[seat], dict) else {}
        observation = row.get("observation") or {}
        select = observation.get("select") if isinstance(observation, dict) else None
        action = next_row.get("action")
        if str(row.get("status", "")).upper() == "ACTIVE" and isinstance(select, dict) and isinstance(action, list):
            count += 1
    return count


def replay_index(root: Path) -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = defaultdict(list)
    if not root.exists():
        return result
    pattern = re.compile(r"episode-(.+?)-replay\.json(?:\.gz)?$")
    for path in sorted(root.rglob("episode-*-replay.json*")):
        match = pattern.match(path.name)
        if match:
            result[match.group(1)].append(path.resolve())
    return result


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def resolve_replay(
    episode_row: Mapping[str, Any],
    submission_id: int,
    root: Path,
    index: Mapping[str, list[Path]],
) -> Path | None:
    episode_id = str(episode_row.get("episode_id"))
    expected_parent = root.resolve() / str(submission_id)
    candidates: list[Path] = []
    declared = episode_row.get("replay")
    if declared:
        candidates.append(Path(str(declared)))
    candidates.extend(index.get(episode_id, []))
    candidates.extend((
        expected_parent / f"episode-{episode_id}-replay.json",
        expected_parent / f"episode-{episode_id}-replay.json.gz",
    ))
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file() and _inside(resolved, root):
            return resolved
    return None


def relative_source_path(path: Path, replay_root: Path) -> str:
    try:
        return path.resolve().relative_to(replay_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


class UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, value: int) -> int:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


def atomic_groups(units: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Connect units by episode and by public opponent team."""
    union = UnionFind(len(units))
    episode_owner: dict[str, int] = {}
    team_owner: dict[str, int] = {}
    for index, unit in enumerate(units):
        episode = str(unit["episode_id"])
        if episode in episode_owner:
            union.union(index, episode_owner[episode])
        else:
            episode_owner[episode] = index
        team = unit.get("opponent_team_normalized")
        if team:
            if team in team_owner:
                union.union(index, team_owner[team])
            else:
                team_owner[team] = index

    members: dict[int, list[int]] = defaultdict(list)
    for index in range(len(units)):
        members[union.find(index)].append(index)

    groups = []
    for indices in members.values():
        episodes = sorted({str(units[index]["episode_id"]) for index in indices})
        teams = sorted({str(units[index]["opponent_team_normalized"]) for index in indices if units[index].get("opponent_team_normalized")})
        atoms = [f"opponent_team:{team}" for team in teams] or [f"episode:{episode}" for episode in episodes]
        if len(atoms) == 1:
            key = atoms[0]
        else:
            key = "connected:" + stable_digest("|".join(atoms))[:20]
        groups.append({
            "key": key,
            "atoms": atoms,
            "indices": sorted(indices),
            "size": len(indices),
            "orders": Counter(str(units[index]["actual_order"]) for index in indices),
            "ratings": Counter(str(units[index]["opponent_rating_bucket"]) for index in indices),
            "episodes": episodes,
        })
    return groups


def _allocation_cost(
    counts: Mapping[str, Counter[str]],
    totals: Mapping[str, int],
    category: str,
) -> float:
    population = totals[category]
    if population <= 0:
        return 0.0
    return sum(
        ((counts[split][category] - SPLIT_WEIGHTS[split] * population) / population) ** 2
        for split in SPLIT_NAMES
    )


def assign_splits(units: list[dict[str, Any]], seed: str = "grim-5k-d842-bank-v1") -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Assign connected episode/team groups, balancing order and rating strata."""
    groups = atomic_groups(units)
    dimension_totals: Counter[str] = Counter({"__total__": len(units)})
    for unit in units:
        dimension_totals[f"order:{unit['actual_order']}"] += 1
        dimension_totals[f"rating:{unit['opponent_rating_bucket']}"] += 1

    counts = {split: Counter() for split in SPLIT_NAMES}
    assignments: dict[str, str] = {}

    def group_dimensions(group: Mapping[str, Any]) -> Counter[str]:
        dimensions = Counter({"__total__": int(group["size"])})
        dimensions.update({f"order:{key}": value for key, value in group["orders"].items()})
        dimensions.update({f"rating:{key}": value for key, value in group["ratings"].items()})
        return dimensions

    def objective(candidate: str, additions: Counter[str]) -> float:
        counts[candidate].update(additions)
        total_cost = 8.0 * _allocation_cost(counts, dimension_totals, "__total__")
        order_cost = sum(
            _allocation_cost(counts, dimension_totals, category)
            for category in dimension_totals if category.startswith("order:")
        )
        rating_cost = sum(
            _allocation_cost(counts, dimension_totals, category)
            for category in dimension_totals if category.startswith("rating:")
        )
        counts[candidate].subtract(additions)
        return total_cost + 2.0 * order_cost + rating_cost

    # Large connected components are the hard constraints and must be placed first.
    ordered_groups = sorted(
        groups,
        key=lambda group: (-int(group["size"]), stable_digest(f"{seed}|{group['key']}")),
    )
    for group in ordered_groups:
        additions = group_dimensions(group)
        candidates = []
        for split in SPLIT_NAMES:
            candidates.append((
                round(objective(split, additions), 15),
                stable_digest(f"{seed}|{group['key']}|{split}"),
                split,
            ))
        selected = min(candidates)[2]
        assignments[str(group["key"])] = selected
        counts[selected].update(additions)

    output = {split: [] for split in SPLIT_NAMES}
    group_lookup = {index: group for group in groups for index in group["indices"]}
    for index, unit in enumerate(units):
        group = group_lookup[index]
        split = assignments[str(group["key"])]
        row = dict(unit)
        row["split"] = split
        row["grouping_key"] = group["key"]
        row["grouping_atoms"] = group["atoms"]
        output[split].append(row)

    for rows in output.values():
        rows.sort(key=lambda row: (str(row["episode_id"]), int(row["submission_id"]), int(row["hero_seat"])))
    report = allocation_report(output, groups, assignments)
    return output, report


def _dimension_imbalance(
    splits: Mapping[str, Sequence[Mapping[str, Any]]],
    field: str | None,
) -> dict[str, Any]:
    all_rows = [row for rows in splits.values() for row in rows]
    categories = ["all"] if field is None else sorted({str(row.get(field, "unknown")) for row in all_rows})
    values: dict[str, Any] = {}
    max_error = 0.0
    for category in categories:
        population = len(all_rows) if field is None else sum(str(row.get(field, "unknown")) == category for row in all_rows)
        cells = {}
        for split in SPLIT_NAMES:
            actual = len(splits[split]) if field is None else sum(str(row.get(field, "unknown")) == category for row in splits[split])
            target = SPLIT_WEIGHTS[split] * population
            share = actual / population if population else 0.0
            error = share - SPLIT_WEIGHTS[split]
            max_error = max(max_error, abs(error))
            cells[split] = {
                "actual": actual,
                "target": round(target, 3),
                "delta": round(actual - target, 3),
                "share": round(share, 6),
                "share_error": round(error, 6),
            }
        values[category] = {"population": population, "splits": cells}
    return {"categories": values, "max_absolute_share_error": round(max_error, 6)}


def allocation_report(
    splits: Mapping[str, Sequence[Mapping[str, Any]]],
    groups: Sequence[Mapping[str, Any]],
    assignments: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "method": "deterministic_greedy_connected_components_v1",
        "target_weights": SPLIT_WEIGHTS,
        "atomic_constraints": ["episode_id", "normalized_opponent_team_when_available"],
        "group_count": len(groups),
        "largest_group_units": max((int(group["size"]) for group in groups), default=0),
        "groups_by_split": dict(sorted(Counter(assignments.values()).items())),
        "total_imbalance": _dimension_imbalance(splits, None),
        "actual_order_imbalance": _dimension_imbalance(splits, "actual_order"),
        "opponent_rating_imbalance": _dimension_imbalance(splits, "opponent_rating_bucket"),
        "coarse_imbalance_is_expected": any(int(group["size"]) > 1 for group in groups),
    }


@contextmanager
def deterministic_gzip_text(path: Path) -> Iterator[io.TextIOWrapper]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="\n") as text:
                yield text


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_jsonl_gz(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with deterministic_gzip_text(temporary) as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    temporary.replace(path)


def summarize_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "units": len(rows),
        "episodes": len({str(row["episode_id"]) for row in rows}),
        "grouping_keys": len({str(row["grouping_key"]) for row in rows}),
        "submission_lineages": dict(sorted(Counter(str(row["submission_id"]) for row in rows).items())),
        "actual_order": dict(sorted(Counter(str(row["actual_order"]) for row in rows).items())),
        "outcome": dict(sorted(Counter(str(row["outcome"]) for row in rows).items())),
        "hero_rating_bucket": dict(sorted(Counter(str(row["hero_rating_bucket"]) for row in rows).items())),
        "opponent_rating_bucket": dict(sorted(Counter(str(row["opponent_rating_bucket"]) for row in rows).items())),
        "opponent_matchup": dict(sorted(Counter(str(row["opponent_matchup"]) for row in rows).items())),
    }


def rejection(submission_id: int | None, episode_id: Any, reason: str, detail: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "submission_id": submission_id,
        "episode_id": None if episode_id is None else str(episode_id),
        "reason": reason,
    }
    if detail:
        result["detail"] = detail
    return result


def _manifest_target(row: Mapping[str, Any]) -> int | None:
    outcome = row.get("outcome")
    if isinstance(outcome, (int, float)) and not isinstance(outcome, bool):
        if outcome > 0:
            return 1
        if outcome < 0:
            return 0
    return None


def _submission_is_eligible(submission: Mapping[str, Any], expected_hash: str) -> tuple[bool, str | None]:
    try:
        submission_id = int(submission.get("submission_id"))
    except (TypeError, ValueError):
        return False, "invalid_submission_id"
    if submission_id not in D842_LINEAGE:
        return False, "outside_strict_d842_lineage"
    lineage = submission.get("policy_lineage")
    if lineage is not None and str(lineage) not in ALLOWED_LINEAGE_LABELS:
        return False, "manifest_lineage_conflict"
    if submission.get("deck_class") != "exact_original_grim":
        return False, "submission_not_exact_original_grim"
    declared_hash = submission.get("deck_canonical_sha256")
    if declared_hash is not None and str(declared_hash).upper() != expected_hash:
        return False, "submission_deck_hash_mismatch"
    declared_deck = submission.get("deck")
    if declared_deck is not None and deck_hash(declared_deck) != expected_hash:
        return False, "submission_deck_list_mismatch"
    return True, None


def collect_units(
    manifest: Mapping[str, Any],
    replay_root: Path,
    expected_deck: tuple[int, ...],
    catalog: Mapping[str, tuple[int, ...]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    expected_hash = deck_hash(expected_deck)
    assert expected_hash is not None
    source_expected = manifest.get("expected_deck_canonical_sha256")
    if source_expected is not None and str(source_expected).upper() != expected_hash:
        raise ValueError("history manifest expected-deck hash does not match the supplied frozen deck")

    index = replay_index(replay_root)
    units: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_units: dict[tuple[str, int, int], str] = {}
    seen_content_units: set[tuple[str, int, int]] = set()
    manifest_submission_ids: set[int] = set()
    eligible_submission_ids: set[int] = set()
    eligible_episode_entries = 0
    declared_rated_episodes = 0

    submissions = manifest.get("submissions") or []
    if not isinstance(submissions, list):
        raise ValueError("history manifest submissions must be a list")
    for submission in submissions:
        if not isinstance(submission, dict):
            rejected.append(rejection(None, None, "invalid_submission_record"))
            continue
        try:
            submission_id = int(submission.get("submission_id"))
            manifest_submission_ids.add(submission_id)
        except (TypeError, ValueError):
            rejected.append(rejection(None, None, "invalid_submission_id"))
            continue
        eligible, reason = _submission_is_eligible(submission, expected_hash)
        if not eligible:
            # Unknown/non-d842 submissions are an expected inventory exclusion, but
            # remain counted so the manifest proves that no description heuristic ran.
            rejected.append(rejection(submission_id, None, str(reason)))
            continue
        eligible_submission_ids.add(submission_id)
        episodes = submission.get("episodes") or []
        if not isinstance(episodes, list):
            rejected.append(rejection(submission_id, None, "episodes_not_a_list"))
            continue
        declared = submission.get("rated_episodes")
        if isinstance(declared, int) and not isinstance(declared, bool) and declared >= 0:
            declared_rated_episodes += declared
        else:
            declared_rated_episodes += len(episodes)

        for episode_row in episodes:
            eligible_episode_entries += 1
            if not isinstance(episode_row, dict):
                rejected.append(rejection(submission_id, None, "invalid_episode_record"))
                continue
            episode_id = episode_row.get("episode_id")
            if episode_id is None:
                rejected.append(rejection(submission_id, None, "missing_episode_id"))
                continue
            try:
                seat = int(episode_row.get("seat"))
            except (TypeError, ValueError):
                rejected.append(rejection(submission_id, episode_id, "invalid_hero_seat"))
                continue
            if seat not in (0, 1):
                rejected.append(rejection(submission_id, episode_id, "invalid_hero_seat"))
                continue
            path = resolve_replay(episode_row, submission_id, replay_root, index)
            if path is None:
                rejected.append(rejection(submission_id, episode_id, "missing_replay"))
                continue
            try:
                replay = load_json(path)
            except Exception as exc:
                rejected.append(rejection(submission_id, episode_id, "invalid_replay_json", f"{type(exc).__name__}: {exc}"))
                continue
            if not is_explicitly_public(episode_row, replay):
                rejected.append(rejection(submission_id, episode_id, "not_public"))
                continue
            replay_id = replay_episode_id(replay)
            if replay_id is not None and replay_id != str(episode_id):
                rejected.append(rejection(submission_id, episode_id, "episode_id_mismatch", replay_id))
                continue
            decks = replay_decks(replay)
            if not all(decks):
                rejected.append(rejection(submission_id, episode_id, "incomplete_deck_handshake"))
                continue
            hero_deck_hash = deck_hash(decks[seat])
            if hero_deck_hash != expected_hash:
                rejected.append(rejection(submission_id, episode_id, "hero_deck_mismatch", str(hero_deck_hash)))
                continue
            first_player = actual_first_player(replay)
            if first_player not in (0, 1):
                rejected.append(rejection(submission_id, episode_id, "missing_or_conflicting_first_player"))
                continue
            order = "first" if first_player == seat else "second"
            declared_order = episode_row.get("actual_order")
            if declared_order is not None and str(declared_order) != order:
                rejected.append(rejection(submission_id, episode_id, "actual_order_mismatch", f"manifest={declared_order}, replay={order}"))
                continue
            target = terminal_target(replay, seat)
            if target is None:
                rejected.append(rejection(submission_id, episode_id, "missing_terminal_outcome"))
                continue
            declared_target = _manifest_target(episode_row)
            if declared_target is not None and declared_target != target:
                rejected.append(rejection(submission_id, episode_id, "outcome_mismatch", f"manifest={declared_target}, replay={target}"))
                continue

            replay_hash = sha256_file(path)
            unit_key = (str(episode_id), submission_id, seat)
            previous_hash = seen_units.get(unit_key)
            if previous_hash is not None:
                reason = "duplicate_manifest_unit" if previous_hash == replay_hash else "duplicate_unit_conflict"
                rejected.append(rejection(submission_id, episode_id, reason))
                continue
            content_key = (replay_hash, submission_id, seat)
            if content_key in seen_content_units:
                rejected.append(rejection(submission_id, episode_id, "duplicate_replay_content"))
                continue
            seen_units[unit_key] = replay_hash
            seen_content_units.add(content_key)

            replay_team_names = replay_teams(replay)
            manifest_hero_team = episode_row.get("team")
            manifest_opponent_team = episode_row.get("opponent_team")
            hero_team = str(manifest_hero_team) if manifest_hero_team else replay_team_names[seat]
            opponent_team = str(manifest_opponent_team) if manifest_opponent_team else replay_team_names[1 - seat]
            normalized_opponent = normalize_team(opponent_team)
            replay_opponent_normalized = normalize_team(replay_team_names[1 - seat])
            # The API team name and replay display name are separate Kaggle
            # namespaces, so disagreement is diagnostic rather than a missing or
            # invalid label.  Grouping intentionally uses API opponent_team when
            # available because it is stable across that team's submissions.
            team_name_agrees_with_replay = (
                normalized_opponent is None
                or replay_opponent_normalized is None
                or normalized_opponent == replay_opponent_normalized
            )

            hero_rating = parse_rating(episode_row.get("initial_rating"))
            opponent_rating = parse_rating(episode_row.get("opponent_initial_rating"))
            opponent_matchup, matchup_evidence, matchup_similarity = classify_matchup(decks[1 - seat], catalog)
            matchup_labeled = opponent_matchup not in {"unknown", "other"}
            labels = {
                "public_manifest_provenance": True,
                "strict_d842_lineage": True,
                "exact_hero_deck": True,
                "terminal_outcome": True,
                "actual_first_player": True,
                "opponent_deck": True,
                "hero_rating": hero_rating is not None,
                "opponent_rating": opponent_rating is not None,
                "opponent_team": normalized_opponent is not None,
                "opponent_matchup": matchup_labeled,
            }
            required = (
                "public_manifest_provenance",
                "strict_d842_lineage",
                "exact_hero_deck",
                "terminal_outcome",
                "actual_first_player",
                "opponent_deck",
            )
            units.append({
                "schema_version": SCHEMA_VERSION,
                "unit_type": "whole_episode_team",
                "episode_id": str(episode_id),
                "submission_id": submission_id,
                "lineage_evidence": "hash_proven" if submission_id in HASH_PROVEN_D842 else "documented",
                "frozen_model_sha256": FROZEN_D842_MODEL_SHA256,
                "hero_seat": seat,
                "actual_first_player": first_player,
                "actual_order": order,
                "target": target,
                "outcome": "win" if target else "loss",
                "created_utc": episode_row.get("created_utc"),
                "hero_team": hero_team,
                "opponent_team": opponent_team,
                "opponent_team_normalized": normalized_opponent,
                "opponent_replay_display_name": replay_team_names[1 - seat],
                "opponent_team_name_agrees_with_replay": team_name_agrees_with_replay,
                "opponent_submission_id": episode_row.get("opponent_submission_id"),
                "hero_initial_rating": hero_rating,
                "opponent_initial_rating": opponent_rating,
                "hero_rating_bucket": rating_bucket(hero_rating),
                "opponent_rating_bucket": rating_bucket(opponent_rating),
                "opponent_matchup": opponent_matchup,
                "opponent_matchup_evidence": matchup_evidence,
                "opponent_matchup_similarity": matchup_similarity,
                "hero_deck_canonical_sha256": hero_deck_hash,
                "opponent_deck_canonical_sha256": deck_hash(decks[1 - seat]),
                "replay_path": relative_source_path(path, replay_root),
                "replay_sha256": replay_hash,
                "replay_bytes": path.stat().st_size,
                "replay_steps": len(replay.get("steps") or []),
                "hero_decisions": hero_decision_count(replay, seat),
                "public_source": "kaggle_competition_manifest",
                "required_labels_complete": all(labels[key] for key in required),
                "labels": labels,
                "stratum": {
                    "submission_lineage": str(submission_id),
                    "actual_order": order,
                    "opponent_rating_bucket": rating_bucket(opponent_rating),
                    "opponent_matchup": opponent_matchup,
                    "outcome": "win" if target else "loss",
                },
            })

    units.sort(key=lambda row: (str(row["episode_id"]), int(row["submission_id"]), int(row["hero_seat"])))
    stats = {
        "manifest_submission_ids": sorted(manifest_submission_ids),
        "eligible_submission_ids": sorted(eligible_submission_ids),
        "missing_allowlisted_submission_ids": sorted(D842_LINEAGE - manifest_submission_ids),
        "unverified_allowlisted_submission_ids": sorted(
            (D842_LINEAGE & manifest_submission_ids) - eligible_submission_ids
        ),
        "allowlisted_submissions_total": len(D842_LINEAGE),
        "allowlisted_submissions_present": len(D842_LINEAGE & manifest_submission_ids),
        "allowlisted_submissions_eligible": len(eligible_submission_ids),
        "eligible_episode_entries": eligible_episode_entries,
        "declared_rated_episodes": declared_rated_episodes,
        "admitted_units": len(units),
    }
    return units, rejected, stats


def build_bank(
    manifest_path: Path,
    replay_root: Path,
    output: Path,
    expected_deck_path: Path = DEFAULT_DECK,
    archetype_dir: Path = DEFAULT_ARCHETYPES,
    seed: str = "grim-5k-d842-bank-v1",
    enforce_frozen_default_hash: bool = False,
) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    replay_root = replay_root.resolve()
    output = output.resolve()
    expected_deck = load_deck(expected_deck_path.resolve())
    expected_hash = deck_hash(expected_deck)
    if enforce_frozen_default_hash and expected_hash != FROZEN_GRIM_DECK_CANONICAL_SHA256:
        raise ValueError(f"frozen deck hash mismatch: {expected_hash}")
    manifest = load_json(manifest_path)
    catalog = load_archetype_catalog(archetype_dir.resolve())
    units, rejected, source_stats = collect_units(manifest, replay_root, expected_deck, catalog)
    if not units:
        raise ValueError("no complete public frozen-d842 episode/team units were admitted")
    splits, allocation = assign_splits(units, seed)

    output.mkdir(parents=True, exist_ok=True)
    split_manifests: dict[str, Any] = {}
    for split in SPLIT_NAMES:
        shard = output / f"{split}.jsonl.gz"
        write_jsonl_gz(shard, splits[split])
        summary = summarize_rows(splits[split])
        split_manifest = {
            "schema_version": SCHEMA_VERSION,
            "split": split,
            "untouched": split == "untouched_holdout",
            "training_use": "forbidden_until_final_evaluation" if split == "untouched_holdout" else "allowed",
            "shard": shard.name,
            "shard_sha256": sha256_file(shard),
            **summary,
        }
        write_json(output / "manifests" / f"{split}.json", split_manifest)
        split_manifests[split] = split_manifest

    rejection_counts = dict(sorted(Counter(row["reason"] for row in rejected).items()))
    core_rejection_reasons = {
        "missing_replay",
        "invalid_replay_json",
        "not_public",
        "episode_id_mismatch",
        "incomplete_deck_handshake",
        "hero_deck_mismatch",
        "missing_or_conflicting_first_player",
        "actual_order_mismatch",
        "missing_terminal_outcome",
        "outcome_mismatch",
        "duplicate_unit_conflict",
    }
    core_rejections = sum(count for reason, count in rejection_counts.items() if reason in core_rejection_reasons)
    labels = sorted({key for row in units for key in row["labels"]})
    label_completeness = {
        key: {
            "present": sum(bool(row["labels"].get(key)) for row in units),
            "missing": sum(not bool(row["labels"].get(key)) for row in units),
            "fraction": round(sum(bool(row["labels"].get(key)) for row in units) / len(units), 6),
        }
        for key in labels
    }
    download_errors = manifest.get("download_errors") or []
    relevant_download_errors = [
        row for row in download_errors
        if isinstance(row, dict) and _safe_int(row.get("submission_id")) in D842_LINEAGE
    ]
    lineage_complete = set(source_stats["eligible_submission_ids"]) == set(D842_LINEAGE)
    declared_complete = source_stats["declared_rated_episodes"] == source_stats["eligible_episode_entries"]
    corpus_complete = lineage_complete and declared_complete and core_rejections == 0 and not relevant_download_errors
    source_partial = manifest_path.name.endswith("partial.json") or manifest.get("passed") is not True
    bank_status = "complete" if corpus_complete and not source_partial else "partial"

    # The allocator annotates copies with their connected-component grouping key;
    # summarize those annotated rows so source-level topology is also auditable.
    allocated_units = [row for split in SPLIT_NAMES for row in splits[split]]
    source_summary = summarize_rows(allocated_units)
    final_manifest = {
        "schema_version": SCHEMA_VERSION,
        "bank_status": bank_status,
        "corpus_complete": corpus_complete,
        "source_manifest_partial": source_partial,
        "offline_only": True,
        "public_only": True,
        "strict_lineage_allowlist": sorted(D842_LINEAGE),
        "hash_proven_lineage": sorted(HASH_PROVEN_D842),
        "frozen_model_sha256": FROZEN_D842_MODEL_SHA256,
        "expected_deck_canonical_sha256": expected_hash,
        "source_manifest": str(manifest_path),
        "source_manifest_sha256": sha256_file(manifest_path),
        "source_replay_root": str(replay_root),
        "archetype_catalog_entries": len(catalog),
        "split_seed": seed,
        "split_unit": "whole_episode_team",
        "split_weights": SPLIT_WEIGHTS,
        "source_completeness": {
            **source_stats,
            "declared_episode_entries_complete": declared_complete,
            "allowlist_coverage_complete": lineage_complete,
            "relevant_download_errors": len(relevant_download_errors),
            "core_validation_rejections": core_rejections,
        },
        "label_completeness": label_completeness,
        "rejections_by_reason": rejection_counts,
        "rejections": rejected,
        "source_strata": source_summary,
        "allocation": allocation,
        "splits": split_manifests,
    }
    bank_id_payload = {
        "schema_version": SCHEMA_VERSION,
        "source_manifest_sha256": final_manifest["source_manifest_sha256"],
        "deck": expected_hash,
        "seed": seed,
        "allowlist": sorted(D842_LINEAGE),
        "split_hashes": {split: split_manifests[split]["shard_sha256"] for split in SPLIT_NAMES},
    }
    final_manifest["bank_id"] = stable_digest(json.dumps(bank_id_payload, sort_keys=True)).upper()
    write_json(output / "manifest.json", final_manifest)
    return final_manifest


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--replay-root", type=Path, default=DEFAULT_REPLAY_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--expected-deck", type=Path, default=DEFAULT_DECK)
    parser.add_argument("--archetype-dir", type=Path, default=DEFAULT_ARCHETYPES)
    parser.add_argument("--seed", default="grim-5k-d842-bank-v1")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = build_bank(
        args.manifest,
        args.replay_root,
        args.output,
        args.expected_deck,
        args.archetype_dir,
        args.seed,
        enforce_frozen_default_hash=args.expected_deck.resolve() == DEFAULT_DECK.resolve(),
    )
    print(json.dumps({
        "manifest": str(args.output.resolve() / "manifest.json"),
        "bank_id": result["bank_id"],
        "bank_status": result["bank_status"],
        "corpus_complete": result["corpus_complete"],
        "admitted_units": result["source_completeness"]["admitted_units"],
        "splits": {name: result["splits"][name]["units"] for name in SPLIT_NAMES},
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
