#!/usr/bin/env python3
"""Build a deterministic, development-only Grimmsnarl policy disagreement bank.

The replay convention used by the competition stores the response to the
observation at replay step ``t`` in the same seat at step ``t + 1``.  This
module keeps that alignment explicit and calls every policy in episode order so
stateful public-information routes are reset by, and advance from, the real deck
handshake.

This is a proposal miner, not a search runner.  In particular, the legacy v2.2
native one-ply search is disabled.  Its greedy package policy remains useful as
a proposer, while complete-turn certification is performed by a separate,
equal-coverage oracle.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib
import importlib.util
import io
import json
import os
import sys
import tarfile
import tempfile
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Protocol, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BANK = ROOT / "artifacts" / "grim_5k_training_bank"
DEFAULT_REPLAY_ROOT = ROOT / "artifacts" / "grim_5k_history" / "replays"
DEFAULT_OUTPUT = ROOT / "artifacts" / "grim_policy_disagreements"
DEFAULT_REFERENCE = ROOT / "grimmsnarl_5k_reference.tar.gz"
DEFAULT_ENGINE_ROOT = ROOT / "artifacts" / "recovery_probes" / "extracted" / "control"

SCHEMA_VERSION = 1
FROZEN_ARCHIVE_SHA256 = "3ECB0BBF119E23C31905E39E19ECA8F6145104AAEFFC0A5675D2FE03855BB458"
FROZEN_MODEL_SHA256 = "D842F85ABFC44AF9F41979F91795E22C92C179B62E04D5A0A2F9C734E70AF1C3"
FROZEN_DECK_CANONICAL_SHA256 = "C20A8A46F5C635773754F03103652F5C534B13DC622448ED2255A97234C103AF"
ALLOWED_SPLITS = ("development", "calibration")
FORBIDDEN_SPLIT = "untouched_holdout"

AREA_NAMES = {
    1: "deck",
    2: "hand",
    3: "discard",
    4: "active",
    5: "bench",
    6: "prize",
    7: "stadium",
    8: "energy",
    9: "tool",
    10: "pre_evolution",
    11: "player",
    12: "looking",
}


@dataclass(frozen=True)
class PackageSpec:
    name: str
    root: Path
    environment: Mapping[str, str] = field(default_factory=dict)
    source_label: str = "extracted_submission"


DEFAULT_CANDIDATES = (
    PackageSpec(
        "tempo",
        ROOT / "artifacts" / "wave1_push" / "extracted_tempo_v2",
        {"PTCG_TEMP": "0", "PTCG_SEARCH": "0", "PTCG_TACTICAL_SHIELD": "1", "PTCG_WAVE1_RAIL": "tempo"},
        "exact_deck_tempo_extracted",
    ),
    PackageSpec(
        "master_v1",
        ROOT / "artifacts" / "recovery_final" / "opponents" / "master_v1",
    ),
    PackageSpec(
        "replay_refresh",
        ROOT / "artifacts" / "recovery_final" / "opponents" / "replay_refresh",
    ),
    PackageSpec(
        "v2_2",
        ROOT / "artifacts" / "recovery_final" / "opponents" / "v2_2",
        {"PTCG_SEARCH": "0", "PTCG_TEMP": "0"},
        "extracted_submission_greedy_proposer_search_disabled",
    ),
    PackageSpec(
        "a2",
        ROOT / "artifacts" / "recovery_probes" / "extracted" / "a2",
        {"PTCG_TEMP": "0", "PTCG_SEARCH": "0", "PTCG_TACTICAL_SHIELD": "1"},
    ),
    PackageSpec(
        "floor_director_v1",
        ROOT / "artifacts" / "grim_5k_floor_director" / "extracted_v1",
        {"PTCG_TEMP": "0", "PTCG_SEARCH": "0"},
        "unqualified_broad_controller_proposal_only",
    ),
)


class Policy(Protocol):
    name: str
    metadata: Mapping[str, Any]

    def act(self, observation: Mapping[str, Any]) -> list[int]: ...

    def features(self, observation: Mapping[str, Any]) -> Mapping[str, Any]: ...


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def stable_id(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest().upper()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def canonical_deck(cards: Iterable[Any]) -> tuple[int, ...]:
    try:
        deck = tuple(sorted(int(card) for card in cards))
    except (TypeError, ValueError):
        return ()
    return deck if len(deck) == 60 else ()


def deck_hash(cards: Iterable[Any]) -> str | None:
    deck = canonical_deck(cards)
    if not deck:
        return None
    return hashlib.sha256(",".join(map(str, deck)).encode("ascii")).hexdigest().upper()


def load_deck(path: Path) -> list[int]:
    try:
        deck = [int(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid deck file {path}: {exc}") from exc
    if len(deck) != 60:
        raise ValueError(f"expected exactly 60 cards in {path}, got {len(deck)}")
    return deck


def source_tree_hash(root: Path) -> tuple[str, list[str]]:
    """Hash executable Python/config sources without caches or native binaries."""
    paths: list[Path] = []
    main = root / "main.py"
    if main.is_file():
        paths.append(main)
    paths.extend(path for path in root.glob("*.json") if path.is_file())
    package = root / "ptcg_ai"
    if package.is_dir():
        paths.extend(path for path in package.rglob("*") if path.is_file() and path.suffix in {".py", ".json"})
    paths = sorted(set(paths), key=lambda path: path.relative_to(root).as_posix())
    if not paths:
        raise FileNotFoundError(f"no package sources in {root}")
    digest = hashlib.sha256()
    names: list[str] = []
    for path in paths:
        name = path.relative_to(root).as_posix()
        names.append(name)
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest().upper(), names


def package_metadata(spec: PackageSpec) -> dict[str, Any]:
    root = spec.root.resolve()
    deck_path = root / "deck.csv"
    model_path = root / "policy_weights.npz"
    main_path = root / "main.py"
    for required in (deck_path, model_path, main_path, root / "ptcg_ai" / "__init__.py"):
        if not required.is_file():
            raise FileNotFoundError(f"missing package artifact: {required}")
    deck = load_deck(deck_path)
    canonical_hash = deck_hash(deck)
    if canonical_hash != FROZEN_DECK_CANONICAL_SHA256:
        raise ValueError(
            f"{spec.name} deck mismatch: {canonical_hash}; expected {FROZEN_DECK_CANONICAL_SHA256}"
        )
    tree_hash, sources = source_tree_hash(root)
    return {
        "name": spec.name,
        "source_label": spec.source_label,
        "model_sha256": sha256_file(model_path),
        "deck_sha256": sha256_file(deck_path),
        "deck_canonical_sha256": canonical_hash,
        "main_sha256": sha256_file(main_path),
        "source_tree_sha256": tree_hash,
        "source_files": sources,
        "effective_environment": dict(sorted(spec.environment.items())),
        "native_search_executed": False,
    }


_PTCG_ENVIRONMENT_KEYS = (
    "PTCG_POLICY",
    "PTCG_TEMP",
    "PTCG_SEARCH",
    "PTCG_TACTICAL_SHIELD",
    "PTCG_WAVE1_RAIL",
    "PTCG_DIRECTOR_ARM",
    "PTCG_DIRECTOR_TRIGGER",
    "PTCG_DIRECTOR_HORIZON",
    "PTCG_DIRECTOR_SWAP_FALLBACK",
)


@contextmanager
def package_environment(values: Mapping[str, str]) -> Iterator[None]:
    old = {key: os.environ.get(key) for key in _PTCG_ENVIRONMENT_KEYS}
    try:
        for key in _PTCG_ENVIRONMENT_KEYS:
            os.environ.pop(key, None)
        for key, value in values.items():
            os.environ[str(key)] = str(value)
        yield
    finally:
        for key in _PTCG_ENVIRONMENT_KEYS:
            os.environ.pop(key, None)
            if old[key] is not None:
                os.environ[key] = old[key]  # type: ignore[assignment]


@contextmanager
def working_directory(path: Path) -> Iterator[None]:
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class LoadedPackagePolicy:
    """Load one extracted package under a private module namespace."""

    def __init__(self, spec: PackageSpec, *, feature_provider: bool = False):
        self.name = spec.name
        self.root = spec.root.resolve()
        self.metadata = package_metadata(spec)
        alias_suffix = stable_id({"name": spec.name, "root": self.root.as_posix()})[:16].lower()
        self.alias = f"_grim_policy_{alias_suffix}"
        init_path = self.root / "ptcg_ai" / "__init__.py"
        module_spec = importlib.util.spec_from_file_location(
            self.alias,
            init_path,
            submodule_search_locations=[str(init_path.parent)],
        )
        if module_spec is None or module_spec.loader is None:
            raise ImportError(f"cannot load package {spec.name} from {init_path}")
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[self.alias] = module
        module_spec.loader.exec_module(module)
        with package_environment(spec.environment), working_directory(self.root):
            agent_class = getattr(module, "CompetitionAgent")
            self._agent = agent_class(
                deck_path=self.root / "deck.csv",
                model_path=self.root / "policy_weights.npz",
            )
        self._feature_provider = feature_provider
        self._features_module = importlib.import_module(f"{self.alias}.features") if feature_provider else None
        self._api = importlib.import_module("cg.api") if feature_provider else None

    def act(self, observation: Mapping[str, Any]) -> list[int]:
        action = self._agent(dict(observation))
        if not isinstance(action, list):
            raise TypeError(f"{self.name} returned {type(action).__name__}, expected list[int]")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in action):
            raise TypeError(f"{self.name} returned a non-integer action: {action!r}")
        errors = int(getattr(self._agent, "errors", 0) or 0)
        if errors:
            raise RuntimeError(f"{self.name} swallowed {errors} policy exception(s)")
        return list(action)

    def features(self, observation: Mapping[str, Any]) -> Mapping[str, Any]:
        if not self._feature_provider or self._features_module is None or self._api is None:
            raise RuntimeError(f"{self.name} is not the feature provider")
        obs = self._api.to_observation_class(dict(observation))
        version = int(self._agent.policy.model.feature_version)
        encoded = self._features_module.encode_observation(obs, version)
        return encoded.to_json()


def _safe_extract_reference(archive: Path, destination: Path) -> Path:
    if sha256_file(archive) != FROZEN_ARCHIVE_SHA256:
        raise ValueError(f"reference archive hash mismatch: {archive}")
    destination = destination.resolve()
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        for member in members:
            target = (destination / member.name).resolve()
            try:
                target.relative_to(destination)
            except ValueError as exc:
                raise ValueError(f"unsafe reference archive member: {member.name}") from exc
            if member.issym() or member.islnk():
                raise ValueError(f"links are forbidden in reference archive: {member.name}")
        # Loading a DLL from a TemporaryDirectory permanently locks that path on
        # Windows.  The engine is verified and loaded from the stable control
        # extraction below; only policy assets/sources are needed here.
        policy_members = [
            member for member in members
            if member.name in {"deck.csv", "main.py", "policy_weights.npz"}
            or member.name.startswith("ptcg_ai/")
        ]
        bundle.extractall(destination, members=policy_members)
    return destination


def verify_reference_engine(archive: Path, engine_root: Path) -> dict[str, str]:
    """Verify the stable engine extraction byte-for-byte against the archive."""
    expected: dict[str, str] = {}
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            if not member.isfile() or not member.name.startswith("cg/"):
                continue
            handle = bundle.extractfile(member)
            if handle is None:
                raise ValueError(f"cannot read engine member {member.name}")
            expected[member.name] = hashlib.sha256(handle.read()).hexdigest().upper()
    if not expected:
        raise ValueError("reference archive contains no engine files")
    for name, expected_hash in expected.items():
        local = engine_root / name
        if not local.is_file() or sha256_file(local) != expected_hash:
            raise ValueError(f"stable engine extraction differs from reference: {local}")
    return expected


@contextmanager
def frozen_baseline(reference_archive: Path = DEFAULT_REFERENCE) -> Iterator[LoadedPackagePolicy]:
    with tempfile.TemporaryDirectory(prefix="grim-d842-reference-") as directory:
        root = _safe_extract_reference(reference_archive.resolve(), Path(directory))
        # The bundled cg package is the exact engine API expected by every
        # package.  It is added once; all candidate policy packages are imported
        # under private namespaces and cannot shadow each other.
        engine_hashes = verify_reference_engine(reference_archive.resolve(), DEFAULT_ENGINE_ROOT.resolve())
        inserted = str(DEFAULT_ENGINE_ROOT.resolve())
        sys.path.insert(0, inserted)
        try:
            spec = PackageSpec("d842", root, {"PTCG_SEARCH": "0", "PTCG_TEMP": "0"}, "frozen_reference_archive")
            baseline = LoadedPackagePolicy(spec, feature_provider=True)
            if baseline.metadata["model_sha256"] != FROZEN_MODEL_SHA256:
                raise ValueError("frozen reference model hash mismatch")
            baseline.metadata["reference_archive_sha256"] = FROZEN_ARCHIVE_SHA256
            baseline.metadata["engine_files"] = dict(sorted(engine_hashes.items()))
            baseline.metadata["engine_tree_sha256"] = stable_id(dict(sorted(engine_hashes.items())))
            yield baseline
        finally:
            if inserted in sys.path:
                sys.path.remove(inserted)


def _card_id(card: Any) -> int | None:
    return int(card["id"]) if isinstance(card, Mapping) and card.get("id") is not None else None


def _player_role(player_index: Any, own_index: int) -> str | None:
    if player_index not in (0, 1):
        return None
    return "own" if int(player_index) == own_index else "opponent"


def _zone(observation: Mapping[str, Any], area: int, player_index: int) -> Sequence[Any]:
    current = observation.get("current") or {}
    select = observation.get("select") or {}
    players = current.get("players") or []
    if area == 1:
        return select.get("deck") or []
    if area == 7:
        return current.get("stadium") or []
    if area == 12:
        return current.get("looking") or []
    if not (0 <= player_index < len(players)) or not isinstance(players[player_index], Mapping):
        return []
    player = players[player_index]
    key = {2: "hand", 3: "discard", 4: "active", 5: "bench", 6: "prize"}.get(area)
    return player.get(key) or [] if key else []


def _resolve_card(
    observation: Mapping[str, Any], area: Any, index: Any, player_index: Any = None
) -> Mapping[str, Any] | None:
    current = observation.get("current") or {}
    own = int(current.get("yourIndex", 0) or 0)
    try:
        area_int, index_int = int(area), int(index)
        owner = own if player_index is None else int(player_index)
    except (TypeError, ValueError):
        return None
    zone = _zone(observation, area_int, owner)
    if 0 <= index_int < len(zone) and isinstance(zone[index_int], Mapping):
        return zone[index_int]
    return None


def _entity_semantic(card: Mapping[str, Any] | None, *, owner_role: str | None = None) -> dict[str, Any] | None:
    if card is None:
        return None
    result: dict[str, Any] = {"card_id": _card_id(card)}
    if owner_role is not None:
        result["owner"] = owner_role
    # Public board condition distinguishes meaningful targets without binding
    # them to temporary option or bench indices.  Serials are intentionally not
    # included in semantic identity.
    for source, target in (("hp", "hp"), ("maxHp", "max_hp"), ("appearThisTurn", "appeared_this_turn")):
        if card.get(source) is not None:
            result[target] = card[source]
    if "energyCards" in card or "energies" in card:
        energy_cards = card.get("energyCards") or []
        result["energy_card_ids"] = sorted(card_id for item in energy_cards if (card_id := _card_id(item)) is not None)
        result["energy_types"] = sorted(int(value) for value in (card.get("energies") or []))
    if "tools" in card:
        result["tool_ids"] = sorted(card_id for item in (card.get("tools") or []) if (card_id := _card_id(item)) is not None)
    if "preEvolution" in card:
        result["pre_evolution_ids"] = [card_id for item in (card.get("preEvolution") or []) if (card_id := _card_id(item)) is not None]
    return result


def semantic_option(observation: Mapping[str, Any], raw: Mapping[str, Any]) -> dict[str, Any]:
    """Describe an option without its ephemeral option-list/zone positions."""
    current = observation.get("current") or {}
    own = int(current.get("yourIndex", 0) or 0)
    option_type = int(raw.get("type", -1))
    area = raw.get("area")
    owner_index = raw.get("playerIndex", own)
    source_area = 2 if option_type == 7 else area  # PLAY indexes the acting hand.
    source = _resolve_card(observation, source_area, raw.get("index"), owner_index)
    source_role = _player_role(owner_index, own)
    target = _resolve_card(observation, raw.get("inPlayArea"), raw.get("inPlayIndex"), own)

    result: dict[str, Any] = {"option_type": option_type}
    if source_area is not None:
        result["source_zone"] = AREA_NAMES.get(int(source_area), f"area_{source_area}")
    source_semantic = _entity_semantic(source, owner_role=source_role)
    if source_semantic is not None:
        result["source"] = source_semantic
    elif raw.get("cardId") is not None:
        result["source"] = {"card_id": int(raw["cardId"]), "owner": source_role}
    if raw.get("inPlayArea") is not None:
        result["target_zone"] = AREA_NAMES.get(int(raw["inPlayArea"]), f"area_{raw['inPlayArea']}")
    target_semantic = _entity_semantic(target, owner_role="own")
    if target_semantic is not None:
        result["target"] = target_semantic
    if option_type in {4, 5, 6} and source is not None:
        attached_key = "tools" if option_type == 4 else "energyCards"
        attached_index_key = "toolIndex" if option_type == 4 else "energyIndex"
        attached = source.get(attached_key) or []
        try:
            attached_index = int(raw.get(attached_index_key))
        except (TypeError, ValueError):
            attached_index = -1
        if 0 <= attached_index < len(attached) and isinstance(attached[attached_index], Mapping):
            result["attached_card_id"] = _card_id(attached[attached_index])
    for key in ("attackId", "number", "count"):
        if raw.get(key) is not None:
            result[{"attackId": "attack_id"}.get(key, key)] = int(raw[key])
    if raw.get("playerIndex") is not None:
        result["selected_owner"] = _player_role(raw["playerIndex"], own)
    return result


def semantic_action(observation: Mapping[str, Any], action: Sequence[int]) -> dict[str, Any]:
    select = observation.get("select") or {}
    options = select.get("option") or []
    chosen = [semantic_option(observation, options[index]) for index in action]
    context_card = _entity_semantic(select.get("contextCard")) if isinstance(select.get("contextCard"), Mapping) else None
    effect_card = _entity_semantic(select.get("effect")) if isinstance(select.get("effect"), Mapping) else None
    return {
        "select_type": int(select.get("type", -1)),
        "context": int(select.get("context", -1)),
        "context_card": context_card,
        "effect_card": effect_card,
        "count": len(action),
        "options": chosen,
    }


def validate_action(observation: Mapping[str, Any], action: Any, *, policy_name: str) -> list[int]:
    select = observation.get("select")
    if not isinstance(select, Mapping):
        raise ValueError(f"{policy_name}: actionable observation has no select object")
    if not isinstance(action, list) or any(isinstance(item, bool) or not isinstance(item, int) for item in action):
        raise ValueError(f"{policy_name}: action must be list[int], got {action!r}")
    options = select.get("option") or []
    minimum, maximum = int(select.get("minCount", 0)), int(select.get("maxCount", 0))
    if not minimum <= len(action) <= maximum:
        raise ValueError(f"{policy_name}: action count {len(action)} outside [{minimum}, {maximum}]")
    if len(set(action)) != len(action):
        raise ValueError(f"{policy_name}: duplicate option indices {action!r}")
    if any(index < 0 or index >= len(options) for index in action):
        raise ValueError(f"{policy_name}: invalid option index in {action!r} for {len(options)} options")
    return list(action)


def replay_decks(replay: Mapping[str, Any]) -> tuple[list[int], list[int]]:
    found: list[list[int]] = [[], []]
    for step in replay.get("steps") or []:
        if not isinstance(step, list):
            continue
        for seat in (0, 1):
            if found[seat] or seat >= len(step) or not isinstance(step[seat], Mapping):
                continue
            action = step[seat].get("action")
            if isinstance(action, list) and len(action) == 60:
                try:
                    found[seat] = [int(card) for card in action]
                except (TypeError, ValueError):
                    pass
        if all(found):
            break
    if not all(found):
        raise ValueError("replay is missing one or both 60-card deck handshakes")
    return found[0], found[1]


def load_json(path: Path) -> dict[str, Any]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def load_split_rows(bank_dir: Path, splits: Sequence[str]) -> list[dict[str, Any]]:
    requested = tuple(str(split) for split in splits)
    if not requested or any(split not in ALLOWED_SPLITS for split in requested):
        raise ValueError(
            f"only {', '.join(ALLOWED_SPLITS)} may be mined; {FORBIDDEN_SPLIT} is hard-protected"
        )
    if len(set(requested)) != len(requested):
        raise ValueError("duplicate split requested")
    rows: list[dict[str, Any]] = []
    for split in requested:
        path = (bank_dir / f"{split}.jsonl.gz").resolve()
        if FORBIDDEN_SPLIT in path.name.casefold() or FORBIDDEN_SPLIT in str(path.parent).casefold():
            raise ValueError("refusing to read untouched holdout")
        if not path.is_file():
            raise FileNotFoundError(path)
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"{path}:{line_number}: expected object")
                if row.get("split") != split:
                    raise ValueError(f"{path}:{line_number}: row split is {row.get('split')!r}")
                if row.get("split") == FORBIDDEN_SPLIT:
                    raise ValueError("refusing untouched holdout row")
                if row.get("frozen_model_sha256") != FROZEN_MODEL_SHA256:
                    raise ValueError(f"{path}:{line_number}: not frozen d842")
                if row.get("hero_deck_canonical_sha256") != FROZEN_DECK_CANONICAL_SHA256:
                    raise ValueError(f"{path}:{line_number}: hero deck mismatch")
                rows.append(row)
    return sorted(rows, key=lambda row: (str(row["split"]), str(row["episode_id"]), int(row["hero_seat"])))


def _row_replay_path(row: Mapping[str, Any], replay_root: Path) -> Path:
    relative = Path(str(row.get("replay_path", "")))
    if relative.is_absolute():
        raise ValueError(f"absolute replay path forbidden: {relative}")
    target = (replay_root / relative).resolve()
    try:
        target.relative_to(replay_root.resolve())
    except ValueError as exc:
        raise ValueError(f"replay escapes replay root: {relative}") from exc
    if not target.is_file():
        raise FileNotFoundError(target)
    if row.get("replay_sha256") and sha256_file(target) != str(row["replay_sha256"]).upper():
        raise ValueError(f"replay hash mismatch: {target}")
    return target


def mine_episode(
    episode: Mapping[str, Any],
    replay: Mapping[str, Any],
    baseline: Policy,
    candidates: Sequence[Policy],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Mine one replay, preserving observation-t/action-(t+1) alignment."""
    steps = replay.get("steps") or []
    seat = int(episode["hero_seat"])
    if seat not in (0, 1):
        raise ValueError(f"invalid hero seat: {seat}")
    decks = replay_decks(replay)
    if deck_hash(decks[seat]) != FROZEN_DECK_CANONICAL_SHA256:
        raise ValueError(f"episode {episode['episode_id']}: replay hero deck mismatch")
    opponent_deck = decks[1 - seat]
    opponent_hash = deck_hash(opponent_deck)
    if opponent_hash != episode.get("opponent_deck_canonical_sha256"):
        raise ValueError(f"episode {episode['episode_id']}: opponent deck does not match bank manifest")

    policies = (baseline, *candidates)
    rows: list[dict[str, Any]] = []
    metrics = Counter()
    saw_handshake = False
    seen_state_candidate: set[tuple[str, str]] = set()

    for step_t in range(max(0, len(steps) - 1)):
        current_step, following_step = steps[step_t], steps[step_t + 1]
        if not isinstance(current_step, list) or not isinstance(following_step, list):
            raise ValueError(f"episode {episode['episode_id']} step {step_t}: malformed step")
        if seat >= len(current_step) or seat >= len(following_step):
            raise ValueError(f"episode {episode['episode_id']} step {step_t}: missing seat")
        current_row = current_step[seat]
        next_row = following_step[seat]
        if not isinstance(current_row, Mapping) or not isinstance(next_row, Mapping):
            raise ValueError(f"episode {episode['episode_id']} step {step_t}: malformed seat row")
        if str(current_row.get("status", "")).upper() != "ACTIVE":
            continue
        observation = current_row.get("observation")
        historical = next_row.get("action")
        if not isinstance(observation, Mapping) or not isinstance(historical, list):
            raise ValueError(f"episode {episode['episode_id']} step {step_t}: missing aligned action")

        select = observation.get("select")
        if select is None:
            expected = list(decks[seat])
            for policy in policies:
                returned = policy.act(observation)
                if returned != expected:
                    raise ValueError(
                        f"episode {episode['episode_id']}: {policy.name} failed deck handshake/reset"
                    )
            if historical != expected:
                raise ValueError(f"episode {episode['episode_id']}: historical deck handshake mismatch")
            saw_handshake = True
            metrics["handshakes"] += 1
            continue
        if not saw_handshake:
            raise ValueError(f"episode {episode['episode_id']}: action occurred before deck handshake")
        if not isinstance(select, Mapping):
            raise ValueError(f"episode {episode['episode_id']} step {step_t}: invalid select")

        historical_action = validate_action(observation, historical, policy_name="historical")
        baseline_action = validate_action(observation, baseline.act(observation), policy_name=baseline.name)
        candidate_actions = {
            policy.name: validate_action(observation, policy.act(observation), policy_name=policy.name)
            for policy in candidates
        }
        metrics["decisions"] += 1
        exact_agreement = historical_action == baseline_action
        semantic_historical = semantic_action(observation, historical_action)
        semantic_baseline = semantic_action(observation, baseline_action)
        semantic_agreement = semantic_historical == semantic_baseline
        metrics["historical_exact_agreement"] += int(exact_agreement)
        metrics["historical_semantic_agreement"] += int(semantic_agreement)
        if not exact_agreement:
            metrics[f"historical_exact_mismatch_step:{step_t}"] += 1

        grouped: dict[str, dict[str, Any]] = {}
        for proposer, action in candidate_actions.items():
            candidate_semantic = semantic_action(observation, action)
            if candidate_semantic == semantic_baseline:
                metrics[f"{proposer}:agrees"] += 1
                continue
            semantic_id = stable_id(candidate_semantic)
            group = grouped.setdefault(
                semantic_id,
                {
                    "semantic": candidate_semantic,
                    "representative_action": action,
                    "proposers": [],
                    "proposer_actions": {},
                },
            )
            group["proposers"].append(proposer)
            group["proposer_actions"][proposer] = action
            metrics[f"{proposer}:disagrees"] += 1

        if not grouped:
            continue
        observation_value = json.loads(json.dumps(observation))
        observation_id = stable_id(observation_value)
        features = dict(baseline.features(observation))
        baseline_id = stable_id(semantic_baseline)
        for candidate_id in sorted(grouped):
            group = grouped[candidate_id]
            dedupe_key = (observation_id, candidate_id)
            if dedupe_key in seen_state_candidate:
                metrics["deduplicated_rows"] += 1
                continue
            seen_state_candidate.add(dedupe_key)
            proposers = sorted(group["proposers"])
            proposer_actions = {name: group["proposer_actions"][name] for name in proposers}
            representative_action = list(min(tuple(action) for action in proposer_actions.values()))
            semantic_action_pair_id = stable_id({
                "baseline": semantic_baseline,
                "candidate": group["semantic"],
            })
            # Keep the historically named field observation-bound so consumers
            # cannot accidentally collapse the same move pair across unrelated
            # states.  semantic_action_pair_id is the explicit global grouping
            # key; record_id is the unique training/certification record key.
            semantic_pair_id = stable_id({
                "observation_sha256": observation_id,
                "baseline_semantic_id": baseline_id,
                "candidate_semantic_id": candidate_id,
            })
            record_id = stable_id({
                "split": episode["split"],
                "episode_id": str(episode["episode_id"]),
                "hero_seat": seat,
                "replay_step_t": step_t,
                "semantic_pair_id": semantic_pair_id,
            })
            rows.append({
                "schema_version": SCHEMA_VERSION,
                "record_type": "semantic_disagreement",
                "record_id": record_id,
                "split": episode["split"],
                "episode_id": str(episode["episode_id"]),
                "submission_id": int(episode["submission_id"]),
                "hero_seat": seat,
                "replay_step_t": step_t,
                "historical_action_step_t_plus_1": step_t + 1,
                "actual_first_player": episode.get("actual_first_player"),
                "actual_order": episode.get("actual_order"),
                "opponent_matchup": episode.get("opponent_matchup"),
                "opponent_rating_bucket": episode.get("opponent_rating_bucket"),
                "opponent_team": episode.get("opponent_team"),
                "opponent_submission_id": episode.get("opponent_submission_id"),
                "outcome": episode.get("outcome"),
                "target": episode.get("target"),
                "opponent_deck": opponent_deck,
                "opponent_deck_canonical_sha256": opponent_hash,
                "observation": observation_value,
                "observation_sha256": observation_id,
                "features": features,
                "historical_action": historical_action,
                "historical_semantic": semantic_historical,
                "historical_agrees_with_baseline": exact_agreement,
                "historical_semantically_agrees_with_baseline": semantic_agreement,
                "baseline_action": baseline_action,
                "baseline_semantic": semantic_baseline,
                "baseline_semantic_id": baseline_id,
                "candidate_action": representative_action,
                "candidate_semantic": group["semantic"],
                "candidate_semantic_id": candidate_id,
                "proposers": proposers,
                "proposer_actions": proposer_actions,
                "semantic_pair_id": semantic_pair_id,
                "semantic_action_pair_id": semantic_action_pair_id,
            })
            metrics["disagreement_rows"] += 1
    if not saw_handshake:
        raise ValueError(f"episode {episode['episode_id']}: no deck handshake was processed")
    return rows, dict(metrics)


def deterministic_gzip_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0, compresslevel=9) as compressed:
        for row in rows:
            compressed.write(_canonical_json(row) + b"\n")
    payload = buffer.getvalue()
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest().upper()


def build_bank(
    episode_rows: Sequence[Mapping[str, Any]],
    replay_root: Path,
    output_path: Path,
    baseline: Policy,
    candidates: Sequence[Policy],
    *,
    strict_historical: bool = True,
) -> dict[str, Any]:
    all_rows: list[dict[str, Any]] = []
    totals = Counter()
    episode_counts: dict[str, dict[str, int]] = {}
    for episode in sorted(
        episode_rows,
        key=lambda row: (str(row["split"]), str(row["episode_id"]), int(row["hero_seat"])),
    ):
        if episode.get("split") not in ALLOWED_SPLITS:
            raise ValueError(f"refusing protected or unknown split: {episode.get('split')!r}")
        replay_path = _row_replay_path(episode, replay_root)
        replay = load_json(replay_path)
        rows, metrics = mine_episode(episode, replay, baseline, candidates)
        all_rows.extend(rows)
        totals.update(metrics)
        episode_counts[str(episode["episode_id"])] = metrics

    decisions = totals["decisions"]
    if strict_historical and totals["historical_semantic_agreement"] != decisions:
        raise ValueError(
            "semantic d842 replay verification failed: "
            f"{totals['historical_semantic_agreement']}/{decisions} semantic agreements "
            f"({totals['historical_exact_agreement']}/{decisions} exact option-index agreements)"
        )
    all_rows.sort(
        key=lambda row: (
            row["split"],
            row["episode_id"],
            row["replay_step_t"],
            row["candidate_semantic_id"],
        )
    )
    output_sha = deterministic_gzip_jsonl(output_path, all_rows)
    split_counts = Counter(row["split"] for row in all_rows)
    proposer_counts = Counter(name for row in all_rows for name in row["proposers"])
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "allowed_input_splits": list(ALLOWED_SPLITS),
        "holdout_read": False,
        "alignment": "observation_t_to_same_seat_action_t_plus_1",
        "semantic_deduplication": "observation_sha256_plus_candidate_semantic_id",
        "native_search_executed": False,
        "episodes": len(episode_rows),
        "decisions": decisions,
        "disagreement_rows": len(all_rows),
        "rows_by_split": dict(sorted(split_counts.items())),
        "rows_by_proposer": dict(sorted(proposer_counts.items())),
        "historical_exact_agreement": totals["historical_exact_agreement"],
        "historical_semantic_agreement": totals["historical_semantic_agreement"],
        "strict_historical": strict_historical,
        "strict_historical_criterion": "semantic_action_identity_not_temporary_option_index",
        "baseline": dict(baseline.metadata),
        "candidates": [dict(policy.metadata) for policy in candidates],
        "output_file": output_path.name,
        "output_sha256": output_sha,
        "episode_metrics": dict(sorted(episode_counts.items())),
    }
    manifest_path = output_path.with_name("manifest.json")
    manifest_path.write_bytes(_canonical_json(manifest) + b"\n")
    manifest["manifest_sha256"] = sha256_file(manifest_path)
    return manifest


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank-dir", type=Path, default=DEFAULT_BANK)
    parser.add_argument("--replay-root", type=Path, default=DEFAULT_REPLAY_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--reference-archive", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument(
        "--splits",
        nargs="+",
        choices=ALLOWED_SPLITS,
        default=list(ALLOWED_SPLITS),
        help="Development/calibration only; untouched_holdout is intentionally not a valid choice.",
    )
    parser.add_argument(
        "--allow-historical-mismatch",
        action="store_true",
        help="Audit-only escape hatch; default is exact historical d842 agreement.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    rows = load_split_rows(args.bank_dir.resolve(), args.splits)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with frozen_baseline(args.reference_archive) as baseline:
        candidates = [LoadedPackagePolicy(spec) for spec in DEFAULT_CANDIDATES]
        manifest = build_bank(
            rows,
            args.replay_root.resolve(),
            args.output_dir / "disagreements.jsonl.gz",
            baseline,
            candidates,
            strict_historical=not args.allow_historical_mismatch,
        )
    print(json.dumps(manifest, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
