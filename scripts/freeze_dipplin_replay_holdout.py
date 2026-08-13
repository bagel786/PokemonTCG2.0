#!/usr/bin/env python3
"""Acquire and metadata-freeze an explicit Dipplin replay evaluation contract.

This tool is intentionally *not* a crawler.  It will only query the hero
submissions and download the episode IDs named in the seed inventory.  Network
access is opt-in via ``--acquire``; without that flag it verifies existing cache
files only.  It never imports or invokes replay-regret evaluation and never
reads replay actions beyond the two deck handshakes at ``steps[1]``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from scripts.crawl_grim_daily import (  # noqa: E402
    classify,
    deck_hash,
    load_archetype_catalog,
)
from training.lucario_data import canonical_deck, sha256_file  # noqa: E402


COMPETITION = "pokemon-tcg-ai-battle"
LIST_EPISODES = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"
DEFAULT_INVENTORY = ROOT / "data" / "dipplin_replay_eval" / "seed_inventory.json"
DEFAULT_CACHE = ROOT / "data" / "dipplin_replay_eval" / "cache"
DEFAULT_OUTPUT = ROOT / "data" / "dipplin_replay_eval" / "frozen"
DEFAULT_DECK_DIR = ROOT / "freshstart" / "decklists"
DEFAULT_CARD_DATA = ROOT / "freshstart" / "data" / "EN_Card_Data.csv"

SPLITS = ("VALIDATION", "FINAL_HOLDOUT")
FESTIVAL_LEAD_DIPPLIN = 93
GROOKEY = 89
THWACKEY = 90
RILLABOOM = 91
FESTIVAL_GROUNDS = 1245
MIN_FAMILY_CORE_COUNT = 2


class FreezeError(RuntimeError):
    """A provenance or identity check failed; no manifest may be frozen."""


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def object_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise FreezeError(f"{field} must be an integer, not bool")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise FreezeError(f"{field} must be an integer: {value!r}") from exc
    if isinstance(value, float) and value != result:
        raise FreezeError(f"{field} must be an integer: {value!r}")
    return result


def _number(value: object, field: str) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FreezeError(f"{field} must be numeric when present")
    return value


def _atomic_replace_json(path: Path, payload: object) -> None:
    """Atomically checkpoint mutable acquisition metadata."""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def add_manifest_digest(payload: Mapping[str, object]) -> dict:
    result = dict(payload)
    if "manifest_payload_sha256" in result:
        raise FreezeError("manifest payload already contains its digest field")
    result["manifest_payload_sha256"] = object_sha256(result)
    return result


def verify_manifest_digest(payload: Mapping[str, object]) -> bool:
    expected = payload.get("manifest_payload_sha256")
    unsigned = {key: value for key, value in payload.items() if key != "manifest_payload_sha256"}
    return isinstance(expected, str) and expected == object_sha256(unsigned)


def write_frozen_manifest(path: Path, payload: Mapping[str, object]) -> str:
    """Write once, or prove an existing frozen manifest is byte-identical."""
    signed = add_manifest_digest(payload)
    encoded = json.dumps(signed, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
    if path.exists():
        if path.read_bytes() != encoded:
            raise FreezeError(f"refusing to overwrite non-identical frozen manifest: {path}")
        return "unchanged"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        # The prior existence check provides the human-friendly immutability
        # contract; replace makes the first publication atomic.
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return "written"


def load_inventory(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    try:
        inventory = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FreezeError(f"invalid inventory JSON: {path}: {exc}") from exc
    validate_inventory(inventory)
    return inventory, hashlib.sha256(raw).hexdigest()


def resolved_selections(inventory: Mapping[str, object]) -> dict[str, list[dict]]:
    sources = inventory.get("sources")
    splits = inventory.get("splits")
    if not isinstance(sources, dict) or not isinstance(splits, dict):
        raise FreezeError("inventory requires object-valued sources and splits")
    resolved: dict[str, list[dict]] = {}
    for split in SPLITS:
        rows = splits.get(split)
        if not isinstance(rows, list):
            raise FreezeError(f"inventory split {split} must be a list")
        resolved[split] = []
        for position, raw_row in enumerate(rows):
            if not isinstance(raw_row, dict):
                raise FreezeError(f"{split}[{position}] must be an object")
            source_id = raw_row.get("source_id")
            source = sources.get(source_id)
            if not isinstance(source_id, str) or not isinstance(source, dict):
                raise FreezeError(f"{split}[{position}] has unknown source_id {source_id!r}")
            row = dict(raw_row)
            row.update({
                "split": split,
                "hero_submission_id": source.get("submission_id"),
                "expected_hero_team_id": source.get("team_id"),
                "expected_hero_pilot": source.get("pilot"),
                "hero_deck_family": source.get("deck_family"),
            })
            resolved[split].append(row)
    return resolved


def validate_inventory(inventory: Mapping[str, object]) -> None:
    if inventory.get("schema_version") != 1:
        raise FreezeError("inventory schema_version must be 1")
    provenance = inventory.get("selection_provenance")
    if not isinstance(provenance, dict) or provenance.get("selection_used_outcome") is not False:
        raise FreezeError("inventory must assert reward-blind selection_used_outcome=false")
    excluded = {
        _integer(value, "excluded_submission_id")
        for value in provenance.get("excluded_submission_ids", [])
    }
    resolved = resolved_selections(inventory)
    expected_counts = inventory.get("expected_counts")
    if not isinstance(expected_counts, dict):
        raise FreezeError("inventory requires expected_counts")
    seen: dict[int, str] = {}
    for split in SPLITS:
        rows = resolved[split]
        if len(rows) != _integer(expected_counts.get(split), f"expected_counts.{split}"):
            raise FreezeError(f"{split} count does not match expected_counts")
        for row in rows:
            episode_id = _integer(row.get("episode_id"), "episode_id")
            if episode_id <= 0:
                raise FreezeError("episode_id must be positive")
            if episode_id in seen:
                raise FreezeError(f"episode {episode_id} overlaps {seen[episode_id]} and {split}")
            seen[episode_id] = split
            hero = _integer(row.get("hero_submission_id"), "hero_submission_id")
            opponent = _integer(
                row.get("expected_opponent_submission_id"),
                "expected_opponent_submission_id",
            )
            if hero in excluded:
                raise FreezeError(f"episode {episode_id} uses excluded submission {hero}")
            if hero == opponent:
                raise FreezeError(f"episode {episode_id} is an unsupported same-submission game")
            _integer(row.get("expected_hero_team_id"), "expected_hero_team_id")
            _integer(row.get("expected_opponent_team_id"), "expected_opponent_team_id")
            if not str(row.get("expected_hero_pilot") or "").strip():
                raise FreezeError(f"episode {episode_id} has no expected hero pilot")
            reward = _integer(row.get("expected_expert_reward"), "expected_expert_reward")
            if reward not in (-1, 1):
                raise FreezeError(f"episode {episode_id} expected reward must be -1 or +1")


def _token_value(raw: str) -> str:
    """Accept either a bare token or the CLI's ``export KEY=value`` form."""
    value = raw.strip()
    if value.startswith("export KAGGLE_API_TOKEN="):
        value = value.split("=", 1)[1].strip().strip("'\"")
    return value


def access_token(runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> str:
    token = _token_value(os.environ.get("KAGGLE_API_TOKEN", ""))
    if token:
        return token
    command = [shutil.which("kaggle") or sys.executable]
    if command[0] == sys.executable:
        command.extend(("-m", "kaggle"))
    result = runner(
        [*command, "auth", "print-access-token"],
        capture_output=True,
        text=True,
    )
    token = _token_value(result.stdout or "")
    if result.returncode or not token:
        raise FreezeError(f"could not obtain Kaggle access token: {(result.stderr or '').strip()[:300]}")
    return token


def fetch_submission_episodes(
    submission_id: int,
    *,
    token: str,
    retries: int = 6,
    backoff_seconds: float = 5.0,
    sleeper: Callable[[float], None] = time.sleep,
    urlopen: Callable[..., object] = urllib.request.urlopen,
) -> list[dict]:
    """Fetch one explicitly named hero submission's history with backoff."""
    payload = json.dumps({"submissionId": int(submission_id)}).encode()
    context = None
    if urlopen is urllib.request.urlopen:
        cafile = os.environ.get("SSL_CERT_FILE")
        system_bundle = Path("/etc/ssl/cert.pem")
        if not cafile and system_bundle.is_file():
            cafile = str(system_bundle)
        context = ssl.create_default_context(cafile=cafile)
    last_error: Exception | None = None
    for attempt in range(retries):
        request = urllib.request.Request(
            LIST_EPISODES,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token,
                "Accept-Encoding": "identity",
                "User-Agent": "PokemonTCG2.0-DipplinFreeze/1",
            },
        )
        try:
            kwargs = {"timeout": 90}
            if context is not None:
                kwargs["context"] = context
            with urlopen(request, **kwargs) as response:
                body = json.loads(response.read().decode("utf-8"))
            episodes = (body.get("result") or {}).get("episodes") or body.get("episodes")
            if not isinstance(episodes, list):
                raise FreezeError(f"ListEpisodes({submission_id}) returned no episode list")
            return episodes
        except urllib.error.HTTPError as exc:
            last_error = exc
            transient = exc.code in {429, 500, 502, 503, 504}
            if not transient or attempt + 1 == retries:
                break
            hinted = exc.headers.get("Retry-After") if exc.headers else None
            try:
                delay = float(hinted) if hinted is not None else 0.0
            except ValueError:
                delay = 0.0
            sleeper(max(delay, min(120.0, backoff_seconds * (2**attempt))))
        except (OSError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 == retries:
                break
            sleeper(min(120.0, backoff_seconds * (2**attempt)))
    raise FreezeError(f"ListEpisodes({submission_id}) failed after {retries} attempts: {last_error}")


def _episodes_from_cache(path: Path, submission_id: int) -> list[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FreezeError(f"invalid metadata cache {path}: {exc}") from exc
    if _integer(payload.get("submission_id"), "cached submission_id") != submission_id:
        raise FreezeError(f"metadata cache submission mismatch: {path}")
    episodes = payload.get("episodes")
    if not isinstance(episodes, list):
        raise FreezeError(f"metadata cache has no episodes list: {path}")
    return episodes


def acquire_fixed_episode_metadata(
    selections: Iterable[Mapping[str, object]],
    cache_root: Path,
    *,
    allow_network: bool,
    refresh: bool = False,
    token: str | None = None,
    retries: int = 6,
    fetcher: Callable[..., list[dict]] = fetch_submission_episodes,
) -> tuple[dict[int, dict], list[dict]]:
    """Resolve only inventory episode IDs, querying each explicit hero once."""
    by_submission: dict[int, set[int]] = defaultdict(set)
    for row in selections:
        by_submission[_integer(row.get("hero_submission_id"), "hero_submission_id")].add(
            _integer(row.get("episode_id"), "episode_id")
        )
    resolved: dict[int, dict] = {}
    source_records: list[dict] = []
    live_token = token
    for submission_id in sorted(by_submission):
        path = cache_root / "episode_metadata" / f"submission-{submission_id}.json"
        episodes: list[dict] | None = None
        cache_reused = False
        if path.exists() and not refresh:
            episodes = _episodes_from_cache(path, submission_id)
            cached_ids = {_integer(row.get("id"), "cached episode id") for row in episodes}
            cache_reused = by_submission[submission_id].issubset(cached_ids)
            if not cache_reused:
                episodes = None
        if episodes is None:
            if not allow_network:
                missing = sorted(by_submission[submission_id])
                raise FreezeError(
                    f"metadata cache is absent/stale for submission {submission_id}; "
                    f"needed fixed episodes {missing}. Re-run with --acquire."
                )
            if live_token is None:
                live_token = access_token()
            fetched = fetcher(submission_id, token=live_token, retries=retries)
            fetched_index: dict[int, dict] = {}
            for episode in fetched:
                if not isinstance(episode, dict) or "id" not in episode:
                    continue
                episode_id = _integer(episode["id"], "fetched episode metadata id")
                if episode_id in fetched_index:
                    raise FreezeError(
                        f"duplicate episode {episode_id} in ListEpisodes({submission_id})"
                    )
                fetched_index[episode_id] = episode
            missing = by_submission[submission_id] - fetched_index.keys()
            if missing:
                raise FreezeError(
                    f"ListEpisodes({submission_id}) omitted fixed episodes {sorted(missing)}"
                )
            # ListEpisodes necessarily returns a submission history, but this is
            # a focused evaluator: discard every unselected row and checkpoint
            # only the explicit inventory episodes.
            episodes = [
                fetched_index[episode_id]
                for episode_id in sorted(by_submission[submission_id])
            ]
            payload = {
                "schema_version": 1,
                "source_endpoint": LIST_EPISODES,
                "submission_id": submission_id,
                "episodes": episodes,
            }
            _atomic_replace_json(path, payload)
        indexed: dict[int, dict] = {}
        for episode in episodes:
            if not isinstance(episode, dict) or "id" not in episode:
                continue
            episode_id = _integer(episode["id"], "episode metadata id")
            if episode_id in indexed:
                raise FreezeError(f"duplicate episode {episode_id} in ListEpisodes({submission_id})")
            indexed[episode_id] = episode
        missing = by_submission[submission_id] - indexed.keys()
        if missing:
            raise FreezeError(f"ListEpisodes({submission_id}) omitted fixed episodes {sorted(missing)}")
        for episode_id in by_submission[submission_id]:
            if episode_id in resolved and resolved[episode_id] != indexed[episode_id]:
                raise FreezeError(f"conflicting API metadata for episode {episode_id}")
            resolved[episode_id] = indexed[episode_id]
        source_records.append({
            "submission_id": submission_id,
            "metadata_cache_path": display_path(path),
            "metadata_cache_sha256": sha256_file(path),
            "selected_episode_count": len(by_submission[submission_id]),
        })
    return resolved, source_records


def _agent_seat(agent: Mapping[str, object], fallback: int) -> int:
    raw = agent.get("index", fallback)
    if raw is None:
        raw = fallback
    seat = _integer(raw, "agent.index")
    if seat not in (0, 1):
        raise FreezeError(f"agent seat must be 0 or 1, got {seat}")
    return seat


def _outcome_from_rewards(hero_reward: object, opponent_reward: object, field: str) -> str:
    hero = _number(hero_reward, f"{field}.hero_reward")
    opponent = _number(opponent_reward, f"{field}.opponent_reward")
    if hero is None or opponent is None or hero == opponent:
        raise FreezeError(f"{field} has no decisive terminal reward")
    return "win" if hero > opponent else "loss"


def normalize_episode_metadata(selection: Mapping[str, object], episode: Mapping[str, object]) -> dict:
    episode_id = _integer(selection.get("episode_id"), "episode_id")
    if _integer(episode.get("id"), "API episode id") != episode_id:
        raise FreezeError(f"episode metadata ID mismatch for {episode_id}")
    timestamp = episode.get("createTime") or episode.get("create_time")
    if not isinstance(timestamp, str) or not timestamp.strip():
        raise FreezeError(f"episode {episode_id} has no source timestamp")
    agents = episode.get("agents")
    if not isinstance(agents, list) or len(agents) != 2 or not all(isinstance(row, dict) for row in agents):
        raise FreezeError(f"episode {episode_id} does not have exactly two API agents")
    by_seat: dict[int, dict] = {}
    for fallback, agent in enumerate(agents):
        seat = _agent_seat(agent, fallback)
        if seat in by_seat:
            raise FreezeError(f"episode {episode_id} has duplicate API seat {seat}")
        by_seat[seat] = agent
    if set(by_seat) != {0, 1}:
        raise FreezeError(f"episode {episode_id} has incomplete API seat mapping")
    hero_submission = _integer(selection.get("hero_submission_id"), "hero_submission_id")
    hero_seats = [
        seat for seat, agent in by_seat.items()
        if _integer(agent.get("submissionId"), "agent.submissionId") == hero_submission
    ]
    if len(hero_seats) != 1:
        raise FreezeError(
            f"episode {episode_id} has {len(hero_seats)} seats for hero submission {hero_submission}"
        )
    hero_seat = hero_seats[0]
    opponent_seat = 1 - hero_seat
    hero = by_seat[hero_seat]
    opponent = by_seat[opponent_seat]
    checks = (
        (hero.get("teamId"), selection.get("expected_hero_team_id"), "hero team"),
        (
            opponent.get("submissionId"),
            selection.get("expected_opponent_submission_id"),
            "opponent submission",
        ),
        (opponent.get("teamId"), selection.get("expected_opponent_team_id"), "opponent team"),
    )
    for actual, expected, label in checks:
        if _integer(actual, label) != _integer(expected, f"expected {label}"):
            raise FreezeError(f"episode {episode_id} {label} mismatch: {actual} != {expected}")
    outcome = _outcome_from_rewards(hero.get("reward"), opponent.get("reward"), "API metadata")
    expected_outcome = "win" if _integer(
        selection.get("expected_expert_reward"), "expected_expert_reward"
    ) > 0 else "loss"
    if outcome != expected_outcome:
        raise FreezeError(f"episode {episode_id} expected {expected_outcome}, API metadata says {outcome}")

    def public_agent(agent: Mapping[str, object], seat: int) -> dict:
        return {
            "seat": seat,
            "submission_id": _integer(agent.get("submissionId"), "agent.submissionId"),
            "team_id": _integer(agent.get("teamId"), "agent.teamId"),
            "reward": _number(agent.get("reward"), "agent.reward"),
            "initial_rating": _number(agent.get("initialScore"), "agent.initialScore"),
            "updated_rating": _number(agent.get("updatedScore"), "agent.updatedScore"),
            "agent_id": _integer(agent["id"], "agent.id") if agent.get("id") is not None else None,
        }

    return {
        "episode_id": episode_id,
        "source_timestamp": timestamp,
        "source_metadata_sha256": object_sha256(episode),
        "hero": public_agent(hero, hero_seat),
        "opponent": public_agent(opponent, opponent_seat),
        "expert_result": outcome,
    }


def _validate_replay_identity(path: Path, episode_id: int) -> None:
    try:
        replay = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FreezeError(f"invalid replay cache file {path}: {exc}") from exc
    info = replay.get("info") or {}
    actual = info.get("EpisodeId", replay.get("id"))
    if _integer(actual, "replay episode id") != episode_id:
        raise FreezeError(f"replay cache identity mismatch at {path}: {actual} != {episode_id}")


def download_replay(
    episode_id: int,
    target: Path,
    *,
    env: Mapping[str, str],
    retries: int = 5,
    backoff_seconds: float = 4.0,
    sleeper: Callable[[float], None] = time.sleep,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    kaggle_command: Sequence[str] | None = None,
) -> str:
    """Download one fixed replay and atomically cache it before continuing."""
    if target.exists():
        _validate_replay_identity(target, episode_id)
        return "cached"
    target.parent.mkdir(parents=True, exist_ok=True)
    if kaggle_command is None:
        command = [shutil.which("kaggle") or sys.executable]
        if command[0] == sys.executable:
            command.extend(("-m", "kaggle"))
    else:
        command = list(kaggle_command)
    last_message = "no command executed"
    for attempt in range(retries):
        with tempfile.TemporaryDirectory(dir=target.parent, prefix=f".episode-{episode_id}.") as tmp:
            tmp_path = Path(tmp)
            result = runner(
                [
                    *command,
                    "competitions",
                    "replay",
                    str(episode_id),
                    "-p",
                    str(tmp_path),
                ],
                capture_output=True,
                text=True,
                env=dict(env),
            )
            candidate = tmp_path / f"episode-{episode_id}-replay.json"
            last_message = ((result.stderr or "") + " " + (result.stdout or "")).strip()[-500:]
            if result.returncode == 0 and candidate.exists() and candidate.stat().st_size:
                _validate_replay_identity(candidate, episode_id)
                os.replace(candidate, target)
                # The replay becomes durable before another episode is attempted.
                with target.open("rb") as handle:
                    os.fsync(handle.fileno())
                return "downloaded"
        if attempt + 1 < retries:
            sleeper(min(120.0, backoff_seconds * (2**attempt)))
    raise FreezeError(f"replay {episode_id} failed after {retries} attempts: {last_message}")


def load_card_name_ids(path: Path) -> dict[str, frozenset[int]]:
    ids: dict[str, set[int]] = defaultdict(set)
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle):
            if len(row) < 2:
                continue
            try:
                card_id = int(row[0])
            except ValueError:
                continue
            ids[row[1]].add(card_id)
    required = {"Applin", "Dipplin", "Grookey", "Thwackey", "Rillaboom", "Festival Grounds"}
    missing = required - ids.keys()
    if missing:
        raise FreezeError(f"card catalog is missing identities: {sorted(missing)}")
    return {name: frozenset(values) for name, values in ids.items()}


def verify_dipplin_family(
    deck: tuple[int, ...], card_ids: Mapping[str, frozenset[int]]
) -> tuple[str, dict[str, int]]:
    if len(deck) != 60:
        raise FreezeError(f"hero deck handshake has {len(deck)} cards, expected 60")
    counts = Counter(deck)
    core = {
        "applin": sum(counts[value] for value in card_ids["Applin"]),
        "festival_lead_dipplin": counts[FESTIVAL_LEAD_DIPPLIN],
        "grookey": counts[GROOKEY],
        "thwackey": counts[THWACKEY],
        "festival_grounds": counts[FESTIVAL_GROUNDS],
        "rillaboom": counts[RILLABOOM],
    }
    deficient = {
        name: count for name, count in core.items()
        if name != "rillaboom" and count < MIN_FAMILY_CORE_COUNT
    }
    if deficient:
        raise FreezeError(f"hero deck is not a full Festival Dipplin family deck: {deficient}")
    family = "rillaboom_dipplin" if core["rillaboom"] else "thwackey_dipplin"
    return family, core


def public_first_player(replay: Mapping[str, object]) -> int:
    """Read only public ``current.firstPlayer`` fields; never decision actions."""
    values: set[int] = set()
    for step in replay.get("steps") or []:
        if not isinstance(step, list):
            continue
        for row in step[:2]:
            if not isinstance(row, dict):
                continue
            current = ((row.get("observation") or {}).get("current") or {})
            value = current.get("firstPlayer")
            if isinstance(value, int) and not isinstance(value, bool) and value in (0, 1):
                values.add(int(value))
    if len(values) != 1:
        raise FreezeError(f"replay public first-player metadata is ambiguous: {sorted(values)}")
    return next(iter(values))


def public_terminal_result(replay: Mapping[str, object]) -> tuple[int, list[object] | None]:
    """Derive the winner from top-level rewards/public result, without actions."""
    reward_winner: int | None = None
    rewards = replay.get("rewards")
    normalized_rewards: list[object] | None = None
    if isinstance(rewards, list) and len(rewards) >= 2:
        normalized_rewards = [rewards[0], rewards[1]]
        left = _number(rewards[0], "replay.rewards[0]")
        right = _number(rewards[1], "replay.rewards[1]")
        if left is not None and right is not None and left != right:
            reward_winner = 0 if left > right else 1
    result_values: set[int] = set()
    for step in replay.get("steps") or []:
        if not isinstance(step, list):
            continue
        for row in step[:2]:
            if not isinstance(row, dict):
                continue
            result = (((row.get("observation") or {}).get("current") or {}).get("result"))
            if isinstance(result, int) and not isinstance(result, bool) and result in (0, 1):
                result_values.add(int(result))
    if len(result_values) > 1:
        raise FreezeError(f"replay contains conflicting terminal public results: {result_values}")
    public_winner = next(iter(result_values)) if result_values else None
    if reward_winner is not None and public_winner is not None and reward_winner != public_winner:
        raise FreezeError("top-level replay rewards disagree with public terminal result")
    winner = reward_winner if reward_winner is not None else public_winner
    if winner not in (0, 1):
        raise FreezeError("replay has no decisive terminal result")
    return winner, normalized_rewards


def opponent_classification(
    deck: tuple[int, ...], catalog: Mapping[str, tuple[int, ...]]
) -> dict:
    label = classify(deck, dict(catalog))
    signature = catalog.get(label)
    if signature is None:
        return {"archetype": label, "exact_catalog_match": False, "multiset_jaccard": None}
    left, right = Counter(deck), Counter(signature)
    overlap = sum((left & right).values())
    union = sum((left | right).values())
    return {
        "archetype": label,
        "exact_catalog_match": deck == signature,
        "multiset_jaccard": overlap / union if union else None,
    }


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT.resolve()))
    except ValueError:
        return str(resolved)


def extract_metadata_only(
    replay_path: Path,
    selection: Mapping[str, object],
    api_metadata: Mapping[str, object],
    catalog: Mapping[str, tuple[int, ...]],
    card_ids: Mapping[str, frozenset[int]],
) -> dict:
    """Handshake/order/outcome extraction only.  No decision action is accessed."""
    try:
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FreezeError(f"invalid replay {replay_path}: {exc}") from exc
    episode_id = _integer(selection.get("episode_id"), "episode_id")
    info = replay.get("info") or {}
    replay_id = info.get("EpisodeId", replay.get("id"))
    if _integer(replay_id, "replay episode id") != episode_id:
        raise FreezeError(f"episode {episode_id} replay identity mismatch")
    steps = replay.get("steps")
    if not isinstance(steps, list) or len(steps) < 2:
        raise FreezeError(f"episode {episode_id} has no deck handshake step")
    handshake = steps[1]
    if not isinstance(handshake, list) or len(handshake) < 2:
        raise FreezeError(f"episode {episode_id} has fewer than two deck handshakes")
    decks: dict[int, tuple[int, ...]] = {}
    for seat in (0, 1):
        row = handshake[seat]
        action = row.get("action") if isinstance(row, dict) else None
        if not isinstance(action, list) or len(action) != 60:
            raise FreezeError(f"episode {episode_id} seat {seat} handshake is not a 60-card list")
        if any(not isinstance(card, int) or isinstance(card, bool) for card in action):
            raise FreezeError(
                f"episode {episode_id} seat {seat} handshake contains a non-integer card ID"
            )
        decks[seat] = canonical_deck(action)

    normalized = normalize_episode_metadata(selection, api_metadata)
    hero_seat = _integer(normalized["hero"]["seat"], "hero seat")
    opponent_seat = 1 - hero_seat
    family, core_counts = verify_dipplin_family(decks[hero_seat], card_ids)
    expected_family = selection.get("hero_deck_family")
    if expected_family == "Thwackey / Dipplin" and family != "thwackey_dipplin":
        raise FreezeError(f"episode {episode_id} expected classic Thwackey/Dipplin, got {family}")
    if expected_family == "Rillaboom / Dipplin" and family != "rillaboom_dipplin":
        raise FreezeError(f"episode {episode_id} expected Rillaboom/Dipplin, got {family}")

    teams = info.get("TeamNames")
    if not isinstance(teams, list) or len(teams) < 2 or not all(
        isinstance(value, str) and value.strip() for value in teams[:2]
    ):
        raise FreezeError(f"episode {episode_id} has no two-seat replay pilot names")
    expected_pilot = str(selection.get("expected_hero_pilot"))
    if teams[hero_seat].strip() != expected_pilot.strip():
        raise FreezeError(
            f"episode {episode_id} hero pilot/seat mismatch: "
            f"{teams[hero_seat]!r} != {expected_pilot!r}"
        )
    first_player = public_first_player(replay)
    winner, terminal_rewards = public_terminal_result(replay)
    replay_outcome = "win" if winner == hero_seat else "loss"
    if replay_outcome != normalized["expert_result"]:
        raise FreezeError(
            f"episode {episode_id} replay outcome {replay_outcome} disagrees with API "
            f"{normalized['expert_result']}"
        )
    hero = dict(normalized["hero"])
    hero.update({
        "pilot": teams[hero_seat],
        "actual_order": "first" if hero_seat == first_player else "second",
        "deck_family": family,
        "deck_sha256": deck_hash(decks[hero_seat]),
        "deck_core_counts": core_counts,
    })
    opponent = dict(normalized["opponent"])
    opponent.update({
        "pilot": teams[opponent_seat],
        "deck_sha256": deck_hash(decks[opponent_seat]),
        **opponent_classification(decks[opponent_seat], catalog),
    })
    return {
        "episode_id": episode_id,
        "selection_source_id": selection.get("source_id"),
        "source_timestamp": normalized["source_timestamp"],
        "source_metadata_sha256": normalized["source_metadata_sha256"],
        "replay_cache_path": display_path(replay_path),
        "replay_sha256": sha256_file(replay_path),
        "first_player_seat": first_player,
        "terminal_winner_seat": winner,
        "terminal_replay_rewards": terminal_rewards,
        "expert_result": replay_outcome,
        "hero": hero,
        "opponent": opponent,
        "selection_contract_verified": True,
    }


def catalog_provenance(
    deck_dir: Path,
    card_data: Path,
    catalog: Mapping[str, tuple[int, ...]],
) -> dict:
    deck_files = [
        {
            "path": display_path(path),
            "sha256": sha256_file(path),
        }
        for path in sorted(deck_dir.glob("*.deck.csv"))
    ]
    if not deck_files:
        raise FreezeError(f"freshstart deck catalog is empty: {deck_dir}")
    return {
        "card_data_path": display_path(card_data),
        "card_data_sha256": sha256_file(card_data),
        "freshstart_deck_files": deck_files,
        "resolved_catalog_sha256": object_sha256({
            name: list(signature) for name, signature in sorted(catalog.items())
        }),
        "classification": "exact match, else multiset Jaccard >= 0.55, else other",
    }


def build_manifest(
    *,
    split: str,
    records: list[dict],
    inventory: Mapping[str, object],
    inventory_path: Path,
    inventory_sha256: str,
    metadata_sources: list[dict],
    catalog_source: Mapping[str, object],
) -> dict:
    sealed = split == "FINAL_HOLDOUT"
    used_sources = {record["hero"]["submission_id"] for record in records}
    return {
        "schema_version": 1,
        "dataset": inventory.get("dataset"),
        "split": split,
        "sealed": sealed,
        "episode_count": len(records),
        "freeze_contract_created_at": inventory.get("freeze_contract_created_at"),
        "inspection_policy": {
            "metadata_only": True,
            "permitted_fields": [
                "deck_handshake",
                "public_first_player",
                "terminal_result",
                "episode_service_metadata",
            ],
            "action_level_inspected": False,
            "replay_regret_executed": False,
            "individual_failure_inspection_permitted": not sealed,
        },
        "selection_provenance": inventory.get("selection_provenance"),
        "provenance": {
            "inventory_path": display_path(inventory_path),
            "inventory_sha256": inventory_sha256,
            "freeze_script_path": display_path(Path(__file__)),
            "freeze_script_sha256": sha256_file(Path(__file__)),
            "metadata_sources": [
                source for source in metadata_sources if source["submission_id"] in used_sources
            ],
            "deck_catalog": dict(catalog_source),
        },
        "episodes": sorted(records, key=lambda row: _integer(row["episode_id"], "episode_id")),
    }


def freeze(args: argparse.Namespace) -> tuple[Path, Path]:
    inventory_path = Path(args.inventory).resolve()
    cache_root = Path(args.cache_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    deck_dir = Path(args.deck_dir).resolve()
    card_data = Path(args.card_data).resolve()
    inventory, inventory_sha256 = load_inventory(inventory_path)
    selections = resolved_selections(inventory)
    all_rows = [row for split in SPLITS for row in selections[split]]
    api_metadata, metadata_sources = acquire_fixed_episode_metadata(
        all_rows,
        cache_root,
        allow_network=bool(args.acquire),
        refresh=bool(args.refresh_metadata),
        retries=args.retries,
    )
    catalog = load_archetype_catalog(deck_dir)
    card_ids = load_card_name_ids(card_data)
    catalog_source = catalog_provenance(deck_dir, card_data, catalog)
    env: dict[str, str] | None = None
    records: dict[str, list[dict]] = {split: [] for split in SPLITS}
    for split in SPLITS:
        for selection in selections[split]:
            episode_id = _integer(selection["episode_id"], "episode_id")
            replay_path = cache_root / "replays" / f"episode-{episode_id}-replay.json"
            if not replay_path.exists():
                if not args.acquire:
                    raise FreezeError(
                        f"fixed replay {episode_id} is not cached at {replay_path}; "
                        "re-run with --acquire"
                    )
                if env is None:
                    env = dict(os.environ)
                    env["KAGGLE_API_TOKEN"] = access_token()
                download_replay(
                    episode_id,
                    replay_path,
                    env=env,
                    retries=args.retries,
                )
            else:
                _validate_replay_identity(replay_path, episode_id)
            records[split].append(extract_metadata_only(
                replay_path,
                selection,
                api_metadata[episode_id],
                catalog,
                card_ids,
            ))

    paths = {
        "VALIDATION": output_dir / "validation_manifest.json",
        "FINAL_HOLDOUT": output_dir / "final_holdout_manifest.json",
    }
    # Build everything before publishing either split.  A mismatch in the sealed
    # set therefore cannot leave a newly frozen half-dataset behind.
    manifests = {
        split: build_manifest(
            split=split,
            records=records[split],
            inventory=inventory,
            inventory_path=inventory_path,
            inventory_sha256=inventory_sha256,
            metadata_sources=metadata_sources,
            catalog_source=catalog_source,
        )
        for split in SPLITS
    }
    for split in SPLITS:
        write_frozen_manifest(paths[split], manifests[split])
    return paths["VALIDATION"], paths["FINAL_HOLDOUT"]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--deck-dir", type=Path, default=DEFAULT_DECK_DIR)
    parser.add_argument("--card-data", type=Path, default=DEFAULT_CARD_DATA)
    parser.add_argument(
        "--acquire",
        action="store_true",
        help="opt in to bounded API calls/downloads for only the fixed inventory",
    )
    parser.add_argument(
        "--refresh-metadata",
        action="store_true",
        help="refresh per-submission API caches (requires --acquire)",
    )
    parser.add_argument("--retries", type=int, default=5)
    args = parser.parse_args(argv)
    if args.refresh_metadata and not args.acquire:
        parser.error("--refresh-metadata requires --acquire")
    if args.retries < 1:
        parser.error("--retries must be positive")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validation, holdout = freeze(args)
    except (FreezeError, FileNotFoundError) as exc:
        print(f"freeze failed closed: {exc}", file=sys.stderr)
        return 2
    print(f"frozen VALIDATION manifest: {validation}")
    print(f"frozen FINAL_HOLDOUT manifest: {holdout}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
