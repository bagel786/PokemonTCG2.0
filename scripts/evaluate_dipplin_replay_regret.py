#!/usr/bin/env python3
"""Completed-turn expert-regret evaluation for the frozen Dipplin S1 policy.

The evaluator replays each hero prompt chronologically.  S1 is allowed to make
its normal D0+D1 proposal, but persistent ``PlanMemory`` is advanced with the
recorded expert action.  A disagreement is compared from two independent
``SearchBegin`` roots through the end of the hero turn under the same frozen D0
continuation.

Official production search has no callable seed reset on this host.  Therefore
any root or continuation which touches RNG/hidden-deck work is deliberately
``UNCERTIFIABLE``.  The evaluator never treats two ordinary SearchBegin calls as
common-random-number trials.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").is_dir():
    sys.path.insert(0, str(ROOT / "vendor"))

from cg.api import AreaType, OptionType, SelectContext, SelectType, to_observation_class  # noqa: E402
from ptcg_ai.dipplin.cards import (  # noqa: E402
    APPLIN_DRAGON,
    APPLIN_GRASS,
    BLACK_BELT,
    BOSS,
    BRAVE_BANGLE,
    BROCK,
    BUG_SET,
    DIPPLIN,
    DO_THE_WAVE,
    FESTIVAL,
    HILDA,
    LILLIE,
    NIGHT_STRETCHER,
    POFFIN,
    POKE_PAD,
    QUICK_SIGN,
    SACRED_ASH,
    THWACKEY,
    UNFAIR_STAMP,
)
from ptcg_ai.dipplin.policy import FestivalD0Planner, semantic_final_action  # noqa: E402
from ptcg_ai.dipplin.resolvers import (  # noqa: E402
    PromptResolver,
    effect_id,
    option_card_id,
    option_source,
    option_target,
)
from ptcg_ai.dipplin.search import (  # noqa: E402
    D1Config,
    METRIC_FIELDS,
    D1Error,
    FestivalD1Search,
    RootCandidate,
    _Budget,
    _NativeBackend,
    _WorldRunner,
    _action_touches_rng_or_hidden_deck,
    capture_semantic_selection,
)
from ptcg_ai.dipplin.snapshot import PlanMemory, PlanSnapshot  # noqa: E402
from ptcg_ai.dipplin.telemetry import Telemetry  # noqa: E402
from ptcg_ai.replay import episode_order, own_turn_ordinal  # noqa: E402
from ptcg_ai.safety import emergency_selection, sanitize_selection  # noqa: E402
from scripts.freeze_dipplin_replay_holdout import verify_manifest_digest  # noqa: E402


SCHEMA = "dipplin-replay-regret-v1"
DEFAULT_INCUMBENT_MANIFEST = ROOT / "artifacts" / "dipplin_s1" / "submission.manifest.json"
DEFAULT_PP_REPLAYS = ROOT / "artifacts" / "dipplin_forensics" / "pp_kawada_replays"
CLASSIFICATIONS = (
    "EQUIVALENT",
    "AGENT_DOMINATES",
    "EXPERT_DOMINATES",
    "INCOMPARABLE",
    "UNCERTIFIABLE",
)
RNG_LIMITATION = (
    "official SearchBegin has no seed-reset API on this host; RNG or hidden-deck "
    "branches fail closed"
)


class RegretError(RuntimeError):
    """A replay contract or counterfactual certification failed closed."""


def _integer(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _object_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest().upper()


def _resolve_replay_path(raw: object, manifest_path: Path) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise RegretError("manifest episode has no replay_cache_path")
    supplied = Path(raw).expanduser()
    candidates = [supplied] if supplied.is_absolute() else [ROOT / supplied, manifest_path.parent / supplied]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise RegretError(f"manifest replay path does not exist: {raw}")


def load_manifest(path: str | Path) -> dict[str, Any]:
    """Load a frozen replay manifest and verify its digest and replay hashes.

    Relative replay paths are resolved against the repository first (the freeze
    tool's normal representation), then against the manifest directory.
    """

    manifest_path = Path(path).resolve()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegretError(f"invalid manifest {manifest_path}: {exc}") from exc
    if not isinstance(payload, dict) or not verify_manifest_digest(payload):
        raise RegretError("manifest payload digest is absent or invalid")
    if _integer(payload.get("schema_version")) != 1:
        raise RegretError("manifest schema_version must be 1")
    split = str(payload.get("split") or "")
    sealed = bool(payload.get("sealed"))
    if split == "FINAL_HOLDOUT" and not sealed:
        raise RegretError("FINAL_HOLDOUT manifest must be sealed")
    if sealed and split != "FINAL_HOLDOUT":
        raise RegretError("only FINAL_HOLDOUT may be sealed")
    inspection = payload.get("inspection_policy") or {}
    if sealed and inspection.get("individual_failure_inspection_permitted") is not False:
        raise RegretError("sealed manifest permits individual failure inspection")
    episodes = payload.get("episodes")
    if not isinstance(episodes, list) or len(episodes) != _integer(payload.get("episode_count")):
        raise RegretError("manifest episode_count does not match episodes")

    result = copy.deepcopy(payload)
    result["_manifest_path"] = str(manifest_path)
    seen: set[int] = set()
    for row in result["episodes"]:
        if not isinstance(row, dict):
            raise RegretError("manifest episode row is not an object")
        episode_id = _integer(row.get("episode_id"))
        if episode_id <= 0 or episode_id in seen:
            raise RegretError(f"invalid or duplicate manifest episode_id {episode_id}")
        seen.add(episode_id)
        if row.get("selection_contract_verified") is not True:
            raise RegretError(f"episode {episode_id} selection contract is unverified")
        hero = row.get("hero") or {}
        seat = _integer(hero.get("seat"))
        if seat not in (0, 1):
            raise RegretError(f"episode {episode_id} has invalid hero seat")
        if hero.get("actual_order") not in {"first", "second"}:
            raise RegretError(f"episode {episode_id} has no actual order")
        replay_path = _resolve_replay_path(row.get("replay_cache_path"), manifest_path)
        expected = str(row.get("replay_sha256") or "").upper()
        if len(expected) != 64 or _sha256(replay_path) != expected:
            raise RegretError(f"episode {episode_id} replay sha256/hash mismatch")
        row["_resolved_replay_path"] = str(replay_path)
    return result


def verify_incumbent(manifest_path: str | Path = DEFAULT_INCUMBENT_MANIFEST) -> dict[str, Any]:
    """Prove that imported S1 sources and archive match the frozen incumbent."""

    path = Path(manifest_path).resolve()
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegretError(f"cannot load incumbent manifest: {exc}") from exc
    if manifest.get("variant") != "s1" or manifest.get("status") != "packaged":
        raise RegretError("incumbent manifest is not packaged S1")
    output = manifest.get("output") or {}
    archive = ROOT / "artifacts" / "dipplin_s1" / "submission.tar.gz"
    if not archive.is_file() or _sha256(archive) != str(output.get("archive_sha256") or "").upper():
        raise RegretError("frozen S1 archive hash mismatch")
    files = output.get("file_manifest") or {}
    checked: dict[str, str] = {}
    for relative in (
        "ptcg_ai/dipplin/cards.py",
        "ptcg_ai/dipplin/damage.py",
        "ptcg_ai/dipplin/objective.py",
        "ptcg_ai/dipplin/plan.py",
        "ptcg_ai/dipplin/policy.py",
        "ptcg_ai/dipplin/resolvers.py",
        "ptcg_ai/dipplin/search.py",
        "ptcg_ai/dipplin/snapshot.py",
        "ptcg_ai/dipplin/telemetry.py",
        "ptcg_ai/safety.py",
    ):
        local = ROOT / relative
        expected = str((files.get(relative) or {}).get("sha256") or "").upper()
        actual = _sha256(local)
        if not expected or actual != expected:
            raise RegretError(f"working source differs from frozen S1: {relative}")
        checked[relative] = actual
    return {
        "archive_sha256": _sha256(archive),
        "manifest_sha256": _sha256(path),
        "source_sha256": checked,
        "configuration": {
            "search": True,
            "second_opening_v2": True,
            "go_first": True,
            "route_v2": False,
            "worlds": 2,
        },
    }


def _card_id(card: Any) -> int | None:
    value = getattr(card, "id", None) if card is not None else None
    return _integer(value) if value is not None else None


def _lineage(card: Any) -> int | None:
    if card is None:
        return None
    pre = [value for value in (getattr(card, "preEvolution", None) or []) if value is not None]
    base = pre[0] if pre else card
    value = getattr(base, "serial", None)
    return _integer(value) if value is not None else None


def _semantic_card(card: Any, *, physical_line: bool) -> tuple[Any, ...] | None:
    card_id = _card_id(card)
    if card_id is None:
        return None
    if physical_line:
        return (card_id, _lineage(card), _integer(getattr(card, "playerIndex", None)))
    # Card ID deliberately remains present: Applin 42 and Applin 92 are not
    # interchangeable, while two copies of either print are.
    return (card_id,)


def _semantic_option_key(obs: Any, option: Any) -> tuple[Any, ...]:
    option_type = _integer(getattr(option, "type", None))
    raw_area = getattr(option, "area", None)
    area = _integer(raw_area) if raw_area is not None else None
    source = option_source(obs, option)
    target = option_target(obs, option)
    board_source = area in {int(AreaType.ACTIVE), int(AreaType.BENCH)} or option_type in {
        int(OptionType.ABILITY),
        int(OptionType.RETREAT),
    }
    if source is None and area == int(AreaType.PRIZE):
        source_key: tuple[Any, ...] | None = ("opaque_prize",)
    else:
        source_key = _semantic_card(source, physical_line=board_source)
        if source_key is None and getattr(option, "cardId", None) is not None:
            source_key = (_integer(getattr(option, "cardId", None)),)

    attached_id: int | None = None
    if source is not None and option_type in {
        int(OptionType.TOOL_CARD),
        int(OptionType.ENERGY_CARD),
        int(OptionType.ENERGY),
    }:
        collection = (
            getattr(source, "tools", None)
            if option_type == int(OptionType.TOOL_CARD)
            else getattr(source, "energyCards", None)
        ) or []
        position = _integer(
            getattr(option, "toolIndex", None)
            if option_type == int(OptionType.TOOL_CARD)
            else getattr(option, "energyIndex", None)
        )
        if 0 <= position < len(collection):
            attached_id = _card_id(collection[position])

    return (
        option_type,
        area,
        source_key,
        _semantic_card(target, physical_line=True),
        attached_id,
        _integer(getattr(option, "attackId", None)),
        _integer(getattr(option, "number", None)),
        _integer(getattr(option, "count", None)),
        _integer(getattr(option, "playerIndex", None)),
        _integer(getattr(option, "specialConditionType", None)),
    )


def semantic_action_key(obs: Any, action: Sequence[int]) -> tuple[Any, ...]:
    """Canonical action identity without temporary duplicate-card positions."""

    select = getattr(obs, "select", None)
    if select is None:
        raise RegretError("semantic action requires a selection")
    indices = [int(value) for value in action]
    minimum, maximum = int(select.minCount), int(select.maxCount)
    if len(indices) != len(set(indices)) or not minimum <= len(indices) <= maximum:
        raise RegretError("semantic action has invalid selection count")
    options = list(getattr(select, "option", None) or [])
    if any(index < 0 or index >= len(options) for index in indices):
        raise RegretError("semantic action index is invalid")
    selected = sorted(
        (_canonical_bytes(_semantic_option_key(obs, options[index])).decode("ascii") for index in indices)
    )
    context_card = _card_id(getattr(select, "contextCard", None))
    effect = _card_id(getattr(select, "effect", None))
    return (
        _integer(getattr(select, "type", None)),
        _integer(getattr(select, "context", None)),
        len(indices),
        context_card,
        effect,
        tuple(selected),
    )


def semantic_actions_equivalent(obs: Any, left: Sequence[int], right: Sequence[int]) -> bool:
    return semantic_action_key(obs, left) == semantic_action_key(obs, right)


def _valid_action(obs: Any, action: Any) -> list[int]:
    if not isinstance(action, list) or any(isinstance(value, bool) or not isinstance(value, int) for value in action):
        raise RegretError(f"recorded action must be list[int], got {action!r}")
    select = obs.select
    if not int(select.minCount) <= len(action) <= int(select.maxCount):
        raise RegretError("recorded action count is outside prompt bounds")
    if len(action) != len(set(action)) or any(index < 0 or index >= len(select.option) for index in action):
        raise RegretError("recorded action has invalid option index")
    return list(action)


def rng_or_deck_touch(obs: Any, action: Sequence[int]) -> bool:
    """Return whether production search cannot safely pair this action here."""

    values = [int(value) for value in action]
    options = list(getattr(getattr(obs, "select", None), "option", None) or [])
    if len(values) != len(set(values)) or any(index < 0 or index >= len(options) for index in values):
        raise RegretError("action index is invalid for RNG/deck-touch check")
    return bool(_action_touches_rng_or_hidden_deck(obs, values))


def _visualizer_stream(replay: Mapping[str, Any]) -> list[dict[str, Any]]:
    steps = replay.get("steps") or []
    if not steps:
        raise RegretError("replay has no steps/visualizer")
    for row in steps[0] if isinstance(steps[0], list) else []:
        frames = row.get("visualize") if isinstance(row, dict) else None
        if isinstance(frames, list) and frames:
            return frames
    raise RegretError("replay has no visualize stream")


def aligned_visualizer_frame(replay: Mapping[str, Any], step_index: int, obs: Any) -> dict[str, Any]:
    """Return the exact full-state frame for replay observation ``step_index``.

    Kaggle frame ``t-1`` is the post-action state shown as replay observation
    ``t``.  Alignment is checked before hidden identities are read.
    """

    if int(step_index) <= 0:
        raise RegretError("visualizer alignment requires replay step >= 1")
    frames = _visualizer_stream(replay)
    position = int(step_index) - 1
    if position >= len(frames) or not isinstance(frames[position], dict):
        raise RegretError("visualizer does not contain aligned step t-1")
    frame = frames[position]
    full = frame.get("current")
    if not isinstance(full, dict):
        raise RegretError("aligned visualizer frame has no current state")
    observed = obs.current
    checks = (
        ("turn", _integer(full.get("turn")), _integer(getattr(observed, "turn", None))),
        (
            "turnActionCount",
            _integer(full.get("turnActionCount")),
            _integer(getattr(observed, "turnActionCount", None)),
        ),
        ("yourIndex", _integer(full.get("yourIndex")), _integer(getattr(observed, "yourIndex", None))),
        (
            "firstPlayer",
            _integer(full.get("firstPlayer")),
            _integer(getattr(observed, "firstPlayer", None)),
        ),
    )
    for label, actual, expected in checks:
        if actual != expected:
            raise RegretError(f"visualizer alignment {label} mismatch: {actual} != {expected}")
    frame_select = frame.get("select")
    if isinstance(frame_select, dict):
        def enum_token(value: Any) -> str:
            name = getattr(value, "name", value)
            return "".join(character.lower() for character in str(name) if character.isalnum())

        for field in ("type", "context"):
            if (
                frame_select.get(field) is not None
                and enum_token(frame_select[field])
                != enum_token(getattr(obs.select, field, None))
            ):
                raise RegretError(f"visualizer alignment select {field} mismatch")
        for field in ("minCount", "maxCount"):
            if frame_select.get(field) is not None and _integer(frame_select[field]) != _integer(getattr(obs.select, field, None)):
                raise RegretError(f"visualizer alignment {field} mismatch")
        frame_options = frame_select.get("option")
        if isinstance(frame_options, list) and len(frame_options) != len(obs.select.option):
            raise RegretError("visualizer alignment option-count mismatch")
    return frame


def _dict_card_ids(cards: Any) -> list[int]:
    result: list[int] = []
    for card in cards or []:
        if card is None:
            continue
        if not isinstance(card, Mapping) or card.get("id") is None:
            raise RegretError("visualizer hidden zone contains an invalid card")
        result.append(_integer(card["id"]))
    return result


def _public_identities(cards: Any) -> list[tuple[int, int | None]]:
    result: list[tuple[int, int | None]] = []
    for card in cards or []:
        if card is None:
            continue
        if isinstance(card, Mapping):
            result.append((_integer(card.get("id")), _integer(card.get("serial")) if card.get("serial") is not None else None))
        else:
            serial = getattr(card, "serial", None)
            result.append((_integer(getattr(card, "id", None)), _integer(serial) if serial is not None else None))
    return result


def validate_exact_hidden(obs: Any, frame: Mapping[str, Any]) -> dict[str, list[int]]:
    """Extract ordered hidden IDs and validate all actor-visible zone counts."""

    full = frame.get("current")
    if not isinstance(full, Mapping):
        raise RegretError("visualizer frame has no full current state")
    me = _integer(getattr(obs.current, "yourIndex", None))
    if me not in (0, 1) or _integer(full.get("yourIndex")) != me:
        raise RegretError("visualizer public actor identity mismatch")
    players = full.get("players")
    public_players = list(getattr(obs.current, "players", None) or [])
    if not isinstance(players, list) or len(players) != 2 or len(public_players) != 2:
        raise RegretError("visualizer/public player shape mismatch")
    opponent = 1 - me
    mine, theirs = players[me], players[opponent]
    if not isinstance(mine, Mapping) or not isinstance(theirs, Mapping):
        raise RegretError("visualizer player state is invalid")

    hidden = {
        "your_deck": _dict_card_ids(mine.get("deck")),
        "your_prize": _dict_card_ids(mine.get("prize")),
        "opponent_deck": _dict_card_ids(theirs.get("deck")),
        "opponent_prize": _dict_card_ids(theirs.get("prize")),
        "opponent_hand": _dict_card_ids(theirs.get("hand")),
        "opponent_active": [],
    }
    public_mine, public_theirs = public_players[me], public_players[opponent]
    counts = (
        ("your deck", len(hidden["your_deck"]), _integer(getattr(public_mine, "deckCount", None))),
        ("your prize", len(hidden["your_prize"]), len(getattr(public_mine, "prize", None) or [])),
        ("opponent deck", len(hidden["opponent_deck"]), _integer(getattr(public_theirs, "deckCount", None))),
        ("opponent prize", len(hidden["opponent_prize"]), len(getattr(public_theirs, "prize", None) or [])),
        ("opponent hand", len(hidden["opponent_hand"]), _integer(getattr(public_theirs, "handCount", None))),
    )
    for label, actual, expected in counts:
        if actual != expected:
            raise RegretError(f"hidden {label} count mismatch: {actual} != {expected}")

    # Exact frame and actor-visible zones must describe the same public state.
    for label, public_zone, full_zone in (
        ("own hand", getattr(public_mine, "hand", None), mine.get("hand")),
        ("own active", getattr(public_mine, "active", None), mine.get("active")),
        ("own bench", getattr(public_mine, "bench", None), mine.get("bench")),
        ("own discard", getattr(public_mine, "discard", None), mine.get("discard")),
        ("opponent bench", getattr(public_theirs, "bench", None), theirs.get("bench")),
        ("opponent discard", getattr(public_theirs, "discard", None), theirs.get("discard")),
    ):
        if _public_identities(public_zone) != _public_identities(full_zone):
            raise RegretError(f"visualizer public {label} identity mismatch")

    visible_active = list(getattr(public_theirs, "active", None) or [])
    full_active = theirs.get("active") or []
    if visible_active and visible_active[0] is None:
        hidden["opponent_active"] = _dict_card_ids(full_active)
    elif _public_identities(visible_active) != _public_identities(full_active):
        raise RegretError("visualizer public opponent active identity mismatch")
    return hidden


def componentwise_label(
    expert_vectors: Sequence[Sequence[float]],
    agent_vectors: Sequence[Sequence[float]],
) -> str:
    """Classify paired completed-turn vectors without lexicographic collapse."""

    if not expert_vectors or len(expert_vectors) != len(agent_vectors):
        return "UNCERTIFIABLE"
    expert_better = False
    agent_better = False
    expected_width: int | None = None
    for expert, agent in zip(expert_vectors, agent_vectors):
        if not expert or len(expert) != len(agent):
            return "UNCERTIFIABLE"
        if expected_width is None:
            expected_width = len(expert)
        elif len(expert) != expected_width:
            return "UNCERTIFIABLE"
        values = tuple(expert) + tuple(agent)
        try:
            if not all(math.isfinite(float(value)) for value in values):
                return "UNCERTIFIABLE"
        except (TypeError, ValueError):
            return "UNCERTIFIABLE"
        world_expert_better = any(float(left) > float(right) for left, right in zip(expert, agent))
        world_agent_better = any(float(right) > float(left) for left, right in zip(expert, agent))
        # Pareto dominance must hold within every paired world.  A tradeoff
        # between fields in even one world is incomparable, not evidence that
        # either branch is componentwise non-inferior.
        if world_expert_better and world_agent_better:
            return "INCOMPARABLE"
        expert_better = expert_better or world_expert_better
        agent_better = agent_better or world_agent_better
    if expert_better and agent_better:
        return "INCOMPARABLE"
    if agent_better:
        return "AGENT_DOMINATES"
    if expert_better:
        return "EXPERT_DOMINATES"
    return "EQUIVALENT"


def strategic_sample(
    records: Sequence[Mapping[str, Any]],
    *,
    cap_per_episode: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Take deterministic, priority-first, episode-capped strategic states."""

    if int(cap_per_episode) <= 0:
        raise RegretError("cap_per_episode must be positive")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in records:
        row = dict(raw)
        grouped[str(row.get("episode_id"))].append(row)

    selected: list[dict[str, Any]] = []
    for episode_id in sorted(grouped):
        def rank(row: Mapping[str, Any]) -> tuple[float, int, str]:
            stable = _object_sha256({
                "seed": int(seed),
                "episode": episode_id,
                "step": row.get("step"),
                "record": row.get("record_id"),
                "family": row.get("decision_family"),
            })
            return (
                -float(row.get("strategic_priority", 0.0)),
                int(bool(row.get("semantic_equivalent", False))),
                stable,
            )

        ordered = sorted(grouped[episode_id], key=rank)
        chosen: list[dict[str, Any]] = []
        chosen_ids: set[str] = set()
        routine_counts: Counter[str] = Counter()
        deferred: list[dict[str, Any]] = []

        # Reserve one slot for a non-forced actual-second setup decision.  These
        # are rare by construction and otherwise lose every small cap to later
        # attack states despite being an explicit causal target.
        setup = next(
            (
                row
                for row in ordered
                if row.get("actual_order") == "second"
                and row.get("decision_family") == "setup"
                and not bool(row.get("semantic_equivalent", False))
            ),
            None,
        )
        if setup is not None:
            chosen.append(setup)
            chosen_ids.add(str(setup.get("record_id")))
        for row in ordered:
            if len(chosen) >= int(cap_per_episode):
                break
            if str(row.get("record_id")) in chosen_ids:
                continue
            family = str(row.get("decision_family") or "unknown")
            priority = float(row.get("strategic_priority", 0.0))
            # Repeated zero-priority mechanics are useful only as a small floor;
            # do not let them consume an episode's diverse strategic sample.
            if priority <= 0 and routine_counts[family] >= 2:
                deferred.append(row)
                continue
            chosen.append(row)
            chosen_ids.add(str(row.get("record_id")))
            if priority <= 0:
                routine_counts[family] += 1
        if len(chosen) < int(cap_per_episode):
            chosen.extend(deferred[: int(cap_per_episode) - len(chosen)])
        selected.extend(chosen)
    return sorted(selected, key=lambda row: (str(row.get("episode_id")), _integer(row.get("step"))))


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    position = fraction * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def aggregate_results(
    rows: Sequence[Mapping[str, Any]],
    *,
    bootstrap_samples: int = 2000,
    seed: int = 20260813,
) -> dict[str, Any]:
    """Aggregate decisions with episodes—not decisions—as statistical units."""

    if int(bootstrap_samples) <= 0:
        raise RegretError("bootstrap_samples must be positive")
    normalized = sorted(
        (dict(row) for row in rows),
        key=lambda row: (str(row.get("episode_id")), _integer(row.get("step"))),
    )
    by_episode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    counts: Counter[str] = Counter()
    for row in normalized:
        label = str(row.get("classification") or "UNCERTIFIABLE")
        if label not in CLASSIFICATIONS:
            raise RegretError(f"unknown classification {label}")
        counts[label] += 1
        by_episode[str(row.get("episode_id"))].append(row)
    episode_ids = sorted(by_episode)
    per_episode: dict[str, dict[str, float]] = {}
    for episode_id in episode_ids:
        episode_rows = by_episode[episode_id]
        episode_counts = Counter(str(row.get("classification")) for row in episode_rows)
        per_episode[episode_id] = {
            label: episode_counts[label] / len(episode_rows) for label in CLASSIFICATIONS
        }
    episode_rates = {
        label: (
            sum(per_episode[episode_id][label] for episode_id in episode_ids) / len(episode_ids)
            if episode_ids else 0.0
        )
        for label in CLASSIFICATIONS
    }

    rng = random.Random(int(seed))
    boot: dict[str, list[float]] = {label: [] for label in CLASSIFICATIONS}
    if episode_ids:
        for _ in range(int(bootstrap_samples)):
            sampled = [episode_ids[rng.randrange(len(episode_ids))] for _ in episode_ids]
            for label in CLASSIFICATIONS:
                boot[label].append(sum(per_episode[item][label] for item in sampled) / len(sampled))
    intervals = {
        label: [_percentile(boot[label], 0.025), _percentile(boot[label], 0.975)]
        if episode_ids else [0.0, 0.0]
        for label in CLASSIFICATIONS
    }
    decisions = len(normalized)
    return {
        "episode_count": len(episode_ids),
        "decision_count": decisions,
        "classification_counts": {label: int(counts[label]) for label in CLASSIFICATIONS},
        "decision_rates": {
            label: counts[label] / decisions if decisions else 0.0 for label in CLASSIFICATIONS
        },
        "episode_rates": episode_rates,
        "episode_bootstrap_95": intervals,
        "expert_dominates_rate": episode_rates["EXPERT_DOMINATES"],
        "agent_dominates_rate": episode_rates["AGENT_DOMINATES"],
    }


def _public_row(row: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in row.items():
        if str(key).startswith("_"):
            continue
        if key in {"observation", "visualizer_frame", "hidden_arguments", "memory"}:
            continue
        if isinstance(value, tuple):
            result[key] = list(value)
        else:
            result[key] = value
    return result


def _grouped_aggregates(
    rows: Sequence[Mapping[str, Any]],
    field: str,
    *,
    bootstrap_samples: int,
    seed: int,
) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(field) or "unknown")].append(row)
    return {
        key: aggregate_results(
            groups[key],
            bootstrap_samples=bootstrap_samples,
            seed=int.from_bytes(hashlib.sha256(f"{seed}:{field}:{key}".encode()).digest()[:8], "big"),
        )
        for key in sorted(groups)
    }


def build_output(
    manifest: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    sealed: bool,
    bootstrap_samples: int = 2000,
    seed: int = 20260813,
    incumbent: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build validation detail output or sealed aggregate-only output."""

    manifest_sealed = bool(manifest.get("sealed"))
    if manifest_sealed and not sealed:
        raise RegretError("sealed FINAL_HOLDOUT requires --sealed aggregate-only mode")
    public_rows = [_public_row(row) for row in rows]
    aggregate = aggregate_results(public_rows, bootstrap_samples=bootstrap_samples, seed=seed)
    aggregate["opponent_archetypes"] = dict(sorted(Counter(
        str(row.get("opponent_archetype") or "unknown") for row in public_rows
    ).items()))
    aggregate["by_actual_order"] = _grouped_aggregates(
        public_rows, "actual_order", bootstrap_samples=bootstrap_samples, seed=seed
    )
    aggregate["by_opponent_archetype"] = _grouped_aggregates(
        public_rows, "opponent_archetype", bootstrap_samples=bootstrap_samples, seed=seed
    )
    aggregate["by_decision_family"] = _grouped_aggregates(
        public_rows, "decision_family", bootstrap_samples=bootstrap_samples, seed=seed
    )
    aggregate["by_hero_deck_family"] = _grouped_aggregates(
        public_rows, "hero_deck_family", bootstrap_samples=bootstrap_samples, seed=seed
    )
    aggregate["by_game_phase"] = _grouped_aggregates(
        public_rows, "game_phase", bootstrap_samples=bootstrap_samples, seed=seed
    )
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "sealed": bool(sealed),
        "split": manifest.get("split", "REPLAY_INPUT"),
        "manifest_payload_sha256": manifest.get("manifest_payload_sha256"),
        "method": {
            "proposal": "chronological frozen S1; recorded expert actions committed to shadow memory",
            "continuation": "independent fresh exact-state roots; frozen D0 through hero turn",
            "comparison": "componentwise across equal completed-turn coverage",
            "rng_seed_reset_available": False,
            "rng_limitation": RNG_LIMITATION,
            "statistical_unit": "episode",
            "rillaboom_metric_scope": (
                "completed-turn resource fields cover the frozen S1 Dipplin/Thwackey "
                "core; Rillaboom-only resources are not credited"
            ),
        },
        "incumbent": dict(incumbent or {}),
        "aggregate": aggregate,
    }
    if not sealed:
        payload["decision_rows"] = public_rows
    return payload


@dataclass
class ShadowProposal:
    action: list[int]
    working_memory: PlanMemory
    snapshot: PlanSnapshot
    proposal: Any
    error: str | None = None


class ChronologicalS1:
    """Frozen S1 proposal stream whose state follows recorded expert history."""

    def __init__(self) -> None:
        self.planner = FestivalD0Planner(go_first=True)
        # Set the archive-forced configuration explicitly; do not inherit a
        # caller's environment.
        self.planner.second_opening_v2 = True
        self.planner.resolver = PromptResolver(go_first=True, second_opening_v2=True)
        self.planner.route_v2_enabled = False
        self.memory = PlanMemory()
        self.telemetry = Telemetry()
        self.search = FestivalD1Search(
            self.planner,
            self.telemetry,
            D1Config(worlds=2),
        )

    def propose(self, raw: Mapping[str, Any], obs: Any) -> ShadowProposal:
        working = self.memory.clone()
        try:
            snapshot = PlanSnapshot.from_observation(obs, working)
            proposal = self.planner.propose(obs, snapshot, working)
            baseline = sanitize_selection(
                obs.select,
                list(proposal.intent.ranked_indices),
                proposal.intent.desired_count,
            )
            action = self.search.choose(raw, obs, snapshot, working, proposal, baseline)
            if list(action) != list(baseline):
                action = sanitize_selection(obs.select, list(action), len(action))
            return ShadowProposal(list(action), working, snapshot, proposal)
        except Exception as exc:
            # Keep chronological memory reconstructable, but never present an
            # emergency proposal as certifiable S1 evidence.
            try:
                snapshot = PlanSnapshot.from_observation(obs, working)
                proposal = self.planner.propose(obs, snapshot, working)
            except Exception:
                snapshot = PlanSnapshot.from_observation(obs, working)
                proposal = None
            return ShadowProposal(
                list(emergency_selection(obs.select)),
                working,
                snapshot,
                proposal,
                f"{type(exc).__name__}:{exc}",
            )

    def commit_expert(self, obs: Any, expert_action: Sequence[int], shadow: ShadowProposal) -> None:
        self.memory = shadow.working_memory
        semantic = semantic_final_action(
            obs,
            list(map(int, expert_action)),
            "recorded_replay",
            "chronological expert shadow",
        )
        snapshot = shadow.snapshot
        self.memory.commit(
            semantic,
            decision_key=(
                int(snapshot.global_turn),
                int(snapshot.turn_action_count),
                int(snapshot.select.type),
                int(snapshot.select.context),
                snapshot.parent_serial,
            ),
        )


def _selected_card_ids(obs: Any, *actions: Sequence[int]) -> set[int]:
    ids: set[int] = set()
    for action in actions:
        for index in action:
            value = option_card_id(obs, int(index))
            if value >= 0:
                ids.add(value)
    return ids


def _selected_types(obs: Any, *actions: Sequence[int]) -> set[int]:
    options = obs.select.option
    return {_integer(options[int(index)].type) for action in actions for index in action}


def _decision_family(
    obs: Any,
    expert: Sequence[int],
    agent: Sequence[int],
    shadow: ShadowProposal,
) -> str:
    context = _integer(obs.select.context)
    select_type = _integer(obs.select.type)
    if context in {int(SelectContext.SETUP_ACTIVE_POKEMON), int(SelectContext.SETUP_BENCH_POKEMON)}:
        return "setup"
    if context in {int(SelectContext.TO_ACTIVE), int(SelectContext.SWITCH)}:
        return "promotion_or_switch"
    if select_type == int(SelectType.ATTACK) and context == int(SelectContext.ATTACK):
        return "festival_second_attack"
    parent = effect_id(obs)
    if select_type != int(SelectType.MAIN):
        if parent in {THWACKEY, BUG_SET, POFFIN, POKE_PAD, HILDA, BROCK, SACRED_ASH, NIGHT_STRETCHER}:
            return "search_target"
        if context == int(SelectContext.DISCARD):
            return "discard_cost"
        return "effect_sequencing"
    types = _selected_types(obs, expert, agent)
    cards = _selected_card_ids(obs, expert, agent)
    attacks = {
        _integer(obs.select.option[int(index)].attackId)
        for action in (expert, agent)
        for index in action
    }
    if DO_THE_WAVE in attacks:
        return "first_productive_attack" if shadow.working_memory.festival_attack_count == 0 else "festival_attack"
    if int(OptionType.ATTACH) in types:
        return "attachment_allocation"
    if int(OptionType.EVOLVE) in types:
        return "replacement_development"
    if cards & {BOSS, BLACK_BELT, UNFAIR_STAMP}:
        return "prize_route_or_disruption"
    if cards & {HILDA, LILLIE, BROCK}:
        return "supporter_timing"
    if cards & {SACRED_ASH, NIGHT_STRETCHER}:
        return "recovery"
    if cards & {FESTIVAL, BRAVE_BANGLE}:
        return "attack_threshold"
    if int(OptionType.RETREAT) in types:
        return "trapped_active"
    if int(OptionType.PLAY) in types:
        return "board_development"
    return "main_sequencing"


def _strategic_priority(
    obs: Any,
    shadow: ShadowProposal,
    family: str,
    own_turn: int,
    actual_order: str,
) -> int:
    priority = {
        "festival_second_attack": 100,
        "first_productive_attack": 95,
        "promotion_or_switch": 90,
        "prize_route_or_disruption": 88,
        "attack_threshold": 85,
        "recovery": 82,
        "trapped_active": 80,
        "replacement_development": 72,
        "attachment_allocation": 68,
        "supporter_timing": 64,
        "search_target": 55,
        "board_development": 45,
        # Retain non-forced setup disagreements: rare actual-second Applin vs
        # Grookey active choices are a measured causal candidate, even though
        # setup itself is earlier than a completed hero-turn boundary.
        "setup": 55,
    }.get(family, 0)
    if actual_order == "second" and own_turn == 1:
        priority += 30
    plan = getattr(shadow.proposal, "plan", None)
    if plan is not None:
        phase = str(getattr(getattr(plan, "phase", None), "value", getattr(plan, "phase", "")))
        if phase in {"MAXIMIZE_PRIZES_NOW", "CLOSE_GAME"}:
            priority += 20
        elif phase == "RECOVER":
            priority += 18
        if not bool(getattr(plan, "replacement_attacker_ready", True)):
            priority += 10
        if getattr(plan, "trapped_active_serial", None) is not None:
            priority += 12
        bench_count = int(getattr(plan, "bench_count", 0))
        if bench_count <= 2 or bench_count >= 5:
            priority += 5
    me = _integer(obs.current.yourIndex)
    players = list(obs.current.players)
    if 0 <= me < len(players) and len(getattr(players[me], "prize", None) or []) <= 2:
        priority += 20
    return priority


def _game_phase(shadow: ShadowProposal) -> str:
    plan = getattr(shadow.proposal, "plan", None)
    phase = getattr(plan, "phase", None)
    return str(getattr(phase, "value", phase or "UNKNOWN"))


def _is_useful_prompt(obs: Any) -> bool:
    select = obs.select
    options = list(select.option or [])
    if not options:
        return False
    # Forced prompts provide neither imitation nor counterfactual information.
    if int(select.minCount) == int(select.maxCount) == len(options):
        return False
    return True


def reconstruct_episode_candidates(
    replay: Mapping[str, Any],
    episode_meta: Mapping[str, Any],
    *,
    proposal_repeats: int = 2,
) -> list[dict[str, Any]]:
    """Reconstruct chronological S1 proposals while following expert memory."""

    steps = replay.get("steps") or []
    hero = episode_meta.get("hero") or {}
    seat = _integer(hero.get("seat"))
    if seat not in (0, 1) or len(steps) < 2:
        raise RegretError("episode has invalid hero seat or no aligned steps")
    episode_id = _integer(episode_meta.get("episode_id"))
    actual_order = str(hero.get("actual_order") or "unknown")
    archetype = str((episode_meta.get("opponent") or {}).get("archetype") or "unknown")
    if int(proposal_repeats) < 2:
        raise RegretError("proposal_repeats must be at least 2")
    shadow_policies = [ChronologicalS1() for _ in range(int(proposal_repeats))]
    rows: list[dict[str, Any]] = []
    for step_index in range(len(steps) - 1):
        current = steps[step_index]
        following = steps[step_index + 1]
        if not isinstance(current, list) or not isinstance(following, list) or seat >= len(current) or seat >= len(following):
            continue
        current_row = current[seat]
        following_row = following[seat]
        if str(current_row.get("status") or "").upper() != "ACTIVE":
            continue
        raw = current_row.get("observation") or {}
        if not isinstance(raw, Mapping) or raw.get("current") is None or raw.get("select") is None:
            continue
        obs = to_observation_class(dict(raw))
        expert = _valid_action(obs, following_row.get("action"))
        proposals = [policy.propose(raw, obs) for policy in shadow_policies]
        proposed = proposals[0]
        agent = list(proposed.action)
        _valid_action(obs, agent)
        proposal_keys: list[tuple[Any, ...]] = []
        for repeat in proposals:
            _valid_action(obs, repeat.action)
            proposal_keys.append(semantic_action_key(obs, repeat.action))
        proposal_error = proposed.error
        if any(repeat.error for repeat in proposals):
            proposal_error = proposal_error or "s1_repeat_policy_error"
        if len(set(proposal_keys)) != 1:
            proposal_error = "s1_action_unstable"
        first_player = _integer(getattr(obs.current, "firstPlayer", None))
        turn = _integer(getattr(obs.current, "turn", None), 0)
        ordinal = own_turn_ordinal(turn, seat, first_player)
        family = _decision_family(obs, expert, agent, proposed)
        if _is_useful_prompt(obs):
            equivalent = semantic_actions_equivalent(obs, expert, agent)
            row = {
                "record_id": f"{episode_id}:{seat}:{step_index}",
                "episode_id": episode_id,
                "replay_sha256": episode_meta.get("replay_sha256"),
                "seat": seat,
                "step": step_index,
                "turn": turn,
                "own_turn_ordinal": ordinal,
                "actual_order": actual_order,
                "opponent_archetype": archetype,
                "hero_deck_family": hero.get("deck_family", "unknown"),
                "decision_family": family,
                "game_phase": _game_phase(proposed),
                "strategic_priority": _strategic_priority(obs, proposed, family, ordinal, actual_order),
                "expert_action": expert,
                "agent_action": agent,
                "expert_semantic": repr(semantic_action_key(obs, expert)),
                "agent_semantic": repr(semantic_action_key(obs, agent)),
                "semantic_equivalent": equivalent,
                "s1_resolver": getattr(getattr(proposed.proposal, "intent", None), "resolver", "error"),
                "s1_searches_this_game": int(shadow_policies[0].search.searches_this_game),
                "s1_proposal_repeats": int(proposal_repeats),
                "proposal_error": proposal_error,
                "_obs": obs,
                "_memory": proposed.working_memory.clone(),
            }
            rows.append(row)
        for policy, repeat in zip(shadow_policies, proposals):
            policy.commit_expert(obs, expert, repeat)
    return rows


def _branch_metric(
    obs: Any,
    action: Sequence[int],
    hidden: Mapping[str, Any],
    memory: PlanMemory,
    planner: FestivalD0Planner,
    *,
    category: str,
) -> tuple[float, ...]:
    semantic = capture_semantic_selection(obs, action)
    candidate = RootCandidate(tuple(map(int, action)), semantic, category, True)
    config = D1Config(
        worlds=2,
        soft_timeout_seconds=1.50,
        hard_timeout_seconds=2.00,
    )
    started = time.monotonic()
    budget = _Budget(
        started=started,
        soft_deadline=started + config.soft_timeout_seconds,
        hard_deadline=started + config.hard_timeout_seconds,
        max_nodes=config.max_nodes_per_decision,
        max_calls=config.max_native_calls_per_decision,
        clock=time.monotonic,
    )
    runner = _WorldRunner(
        planner,
        _NativeBackend(),
        budget,
        config,
        allow_random=False,
        planning_enabled=False,
    )
    outcomes = runner.run(obs, (candidate,), dict(hidden), memory)
    vector = outcomes.get(candidate.key)
    if vector is None or len(vector) != len(METRIC_FIELDS):
        raise RegretError("branch has no complete named metric vector")
    return tuple(float(value) for value in vector)


def evaluate_candidate(
    row: Mapping[str, Any],
    replay: Mapping[str, Any],
    *,
    repeat_passes: int = 2,
) -> dict[str, Any]:
    """Evaluate one sampled state, failing closed on every parity uncertainty."""

    result = dict(row)
    obs = result.get("_obs")
    memory = result.get("_memory")
    expert = list(result.get("expert_action") or [])
    agent = list(result.get("agent_action") or [])
    if result.get("proposal_error"):
        proposal_error = str(result.get("proposal_error"))
        reason = "s1_action_unstable" if "unstable" in proposal_error else "policy_error"
        result.update({"classification": "UNCERTIFIABLE", "uncertifiable_reason": reason})
        return result
    if bool(result.get("semantic_equivalent")):
        result.update({"classification": "EQUIVALENT", "uncertifiable_reason": None})
        return result
    if int(repeat_passes) < 2:
        raise RegretError("repeat_passes must be at least 2")
    try:
        if rng_or_deck_touch(obs, expert) or rng_or_deck_touch(obs, agent):
            raise RegretError("rng_or_hidden_deck_root")
        frame = aligned_visualizer_frame(replay, _integer(result.get("step")), obs)
        hidden = validate_exact_hidden(obs, frame)
        frame_digest = _object_sha256(frame)
        planner = FestivalD0Planner(go_first=True)
        planner.second_opening_v2 = True
        planner.resolver = PromptResolver(go_first=True, second_opening_v2=True)
        planner.route_v2_enabled = False
        metrics: dict[str, list[tuple[float, ...]]] = {"expert": [], "agent": []}
        for pass_index in range(int(repeat_passes)):
            order = ("expert", "agent") if pass_index % 2 == 0 else ("agent", "expert")
            for arm in order:
                action = expert if arm == "expert" else agent
                metrics[arm].append(
                    _branch_metric(
                        obs,
                        action,
                        hidden,
                        memory,
                        planner,
                        category=f"replay_regret_{arm}",
                    )
                )
        if len(set(metrics["expert"])) != 1 or len(set(metrics["agent"])) != 1:
            raise RegretError("rng_repeat_disagreement")
        expert_worlds = [metrics["expert"][0]]
        agent_worlds = [metrics["agent"][0]]
        classification = componentwise_label(expert_worlds, agent_worlds)
        result.update({
            "classification": classification,
            "uncertifiable_reason": None,
            "exact_state_frame_sha256": frame_digest,
            "metric_fields": list(METRIC_FIELDS),
            "expert_metric": list(expert_worlds[0]),
            "agent_metric": list(agent_worlds[0]),
            "repeat_passes": int(repeat_passes),
        })
    except Exception as exc:
        text = str(exc).lower()
        if "rng" in text or "hidden_deck" in text:
            reason = "rng_or_hidden_deck_unseeded"
        elif "visual" in text or "align" in text:
            reason = "visualizer_alignment_error"
        elif "count" in text or "public" in text or "identity" in text:
            reason = "exact_hidden_validation_error"
        elif "semantic" in text or "remap" in text:
            reason = "semantic_remap_error"
        elif "incomplete" in text or "path_depth" in text:
            reason = "incomplete_turn"
        elif "release[" in text or "search_end" in text:
            reason = "cleanup_error"
        elif "ambiguous_nonhero" in text:
            reason = "ambiguous_nonhero_prompt"
        else:
            reason = "engine_error"
        result.update({
            "classification": "UNCERTIFIABLE",
            "uncertifiable_reason": reason,
            "uncertifiable_detail": f"{type(exc).__name__}:{exc}"[:240],
        })
    return result


def _load_json_replay(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegretError(f"invalid replay {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RegretError(f"replay is not an object: {path}")
    return payload


def _infer_dipplin_seat(replay: Mapping[str, Any]) -> int:
    steps = replay.get("steps") or []
    if len(steps) < 2 or not isinstance(steps[1], list):
        raise RegretError("cannot infer Dipplin seat without deck handshake")
    scored: list[tuple[int, int]] = []
    for seat, row in enumerate(steps[1][:2]):
        deck = row.get("action") if isinstance(row, Mapping) else None
        cards = Counter(map(int, deck or [])) if isinstance(deck, list) and len(deck) == 60 else Counter()
        score = (
            5 * cards[DIPPLIN]
            + 3 * (cards[APPLIN_DRAGON] + cards[APPLIN_GRASS])
            + 3 * cards[THWACKEY]
            + 2 * cards[FESTIVAL]
        )
        scored.append((score, seat))
    scored.sort(reverse=True)
    if not scored or scored[0][0] < 20 or (len(scored) > 1 and scored[0][0] == scored[1][0]):
        raise RegretError("Dipplin hero seat is absent or ambiguous; pass --hero-seat")
    return scored[0][1]


def _raw_input_manifest(paths: Sequence[Path], hero_seat: int | None) -> dict[str, Any]:
    episodes: list[dict[str, Any]] = []
    for path in sorted({candidate.resolve() for candidate in paths}):
        replay = _load_json_replay(path)
        info = replay.get("info") or {}
        episode_id = _integer(info.get("EpisodeId", replay.get("id")))
        seat = int(hero_seat) if hero_seat is not None else _infer_dipplin_seat(replay)
        _chooser, _choice, first_player = episode_order(replay)
        if first_player not in (0, 1):
            raise RegretError(f"replay {episode_id} has no public first player")
        episodes.append({
            "episode_id": episode_id,
            "replay_cache_path": str(path),
            "_resolved_replay_path": str(path),
            "replay_sha256": _sha256(path),
            "hero": {
                "seat": seat,
                "actual_order": "first" if seat == first_player else "second",
                "deck_family": "diagnostic_input",
            },
            "opponent": {"archetype": "unknown"},
            "selection_contract_verified": False,
        })
    if not episodes:
        raise RegretError("no replay inputs were supplied")
    return {
        "schema_version": 0,
        "split": "DIAGNOSTIC_REPLAY_INPUT",
        "sealed": False,
        "episode_count": len(episodes),
        "episodes": episodes,
    }


def evaluate_manifest(
    manifest: Mapping[str, Any],
    *,
    cap_per_episode: int,
    sample_seed: int,
    repeat_passes: int,
    proposal_repeats: int = 2,
    max_episodes: int | None = None,
) -> list[dict[str, Any]]:
    episode_rows = list(manifest.get("episodes") or [])
    if max_episodes is not None:
        episode_rows = episode_rows[: int(max_episodes)]
    candidates: list[dict[str, Any]] = []
    replay_cache: dict[int, dict[str, Any]] = {}
    for meta in episode_rows:
        path = Path(str(meta.get("_resolved_replay_path") or meta.get("replay_cache_path"))).resolve()
        replay = _load_json_replay(path)
        episode_id = _integer(meta.get("episode_id"))
        replay_id = _integer((replay.get("info") or {}).get("EpisodeId", replay.get("id")))
        if replay_id != episode_id:
            raise RegretError(f"replay identity mismatch: {replay_id} != {episode_id}")
        replay_cache[episode_id] = replay
        candidates.extend(
            reconstruct_episode_candidates(
                replay,
                meta,
                proposal_repeats=proposal_repeats,
            )
        )
    sampled = strategic_sample(candidates, cap_per_episode=cap_per_episode, seed=sample_seed)
    return [
        evaluate_candidate(row, replay_cache[_integer(row.get("episode_id"))], repeat_passes=repeat_passes)
        for row in sampled
    ]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, help="frozen validation or FINAL_HOLDOUT manifest")
    parser.add_argument("--replay", type=Path, action="append", default=[], help="diagnostic replay file")
    parser.add_argument("--replays", type=Path, help="diagnostic directory of episode-*-replay.json")
    parser.add_argument("--hero-seat", type=int, choices=(0, 1), help="hero seat for raw replay input")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cap-per-episode", type=int, default=24)
    parser.add_argument("--sample-seed", type=int, default=20260813)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--repeat-passes", type=int, default=2)
    parser.add_argument("--proposal-repeats", type=int, default=3)
    parser.add_argument("--max-episodes", type=int)
    parser.add_argument("--incumbent-manifest", type=Path, default=DEFAULT_INCUMBENT_MANIFEST)
    parser.add_argument(
        "--sealed",
        action="store_true",
        help="emit aggregate-only output (mandatory for FINAL_HOLDOUT)",
    )
    args = parser.parse_args(argv)
    if args.manifest and (args.replay or args.replays):
        parser.error("use either --manifest or raw --replay/--replays input")
    if not args.manifest and not args.replay and not args.replays:
        parser.error("one of --manifest, --replay, or --replays is required")
    if args.cap_per_episode <= 0:
        parser.error("--cap-per-episode must be positive")
    if args.bootstrap_samples <= 0:
        parser.error("--bootstrap-samples must be positive")
    if args.repeat_passes < 2:
        parser.error("--repeat-passes must be at least 2")
    if args.proposal_repeats < 2:
        parser.error("--proposal-repeats must be at least 2")
    if args.max_episodes is not None and args.max_episodes <= 0:
        parser.error("--max-episodes must be positive")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        incumbent = verify_incumbent(args.incumbent_manifest)
        if args.manifest:
            manifest = load_manifest(args.manifest)
            if manifest.get("sealed") and not args.sealed:
                raise RegretError("FINAL_HOLDOUT requires --sealed aggregate-only mode")
            if manifest.get("sealed") and args.max_episodes is not None:
                raise RegretError("sealed evaluation cannot select a partial episode set")
            if manifest.get("sealed") and args.output.exists():
                raise RegretError("refusing to overwrite an existing sealed evaluation output")
        else:
            paths = list(args.replay)
            if args.replays:
                paths.extend(sorted(args.replays.glob("episode-*-replay.json")))
            manifest = _raw_input_manifest(paths, args.hero_seat)
        rows = evaluate_manifest(
            manifest,
            cap_per_episode=args.cap_per_episode,
            sample_seed=args.sample_seed,
            repeat_passes=args.repeat_passes,
            proposal_repeats=args.proposal_repeats,
            max_episodes=args.max_episodes,
        )
        output = build_output(
            manifest,
            rows,
            sealed=bool(args.sealed),
            bootstrap_samples=args.bootstrap_samples,
            seed=args.sample_seed,
            incumbent=incumbent,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        aggregate = output["aggregate"]
        print(json.dumps({
            "output": str(args.output),
            "sealed": bool(args.sealed),
            "episode_count": aggregate["episode_count"],
            "decision_count": aggregate["decision_count"],
            "classification_counts": aggregate["classification_counts"],
            "episode_rates": aggregate["episode_rates"],
        }, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        if "args" in locals() and bool(getattr(args, "sealed", False)):
            print(
                "sealed replay-regret evaluation failed closed; no individual detail emitted",
                file=sys.stderr,
            )
        else:
            print(f"replay-regret evaluation failed closed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
