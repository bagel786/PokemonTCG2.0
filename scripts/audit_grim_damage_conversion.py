#!/usr/bin/env python3
"""Audit public A2 replay states for exact Munkidori/Shadow Bullet regret.

This script is descriptive only.  It never advances the engine and never
changes a gameplay policy.  Candidate routes use only the public observation
at the recorded decision; opponent archetypes are attached after scoring and
are never inputs to the arithmetic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

from cg.api import AreaType, SelectContext, to_observation_class  # noqa: E402
from ptcg_ai.card_ids import MARNIES_GRIMMSNARL_EX, MUNKIDORI, SHADOW_BULLET  # noqa: E402
from ptcg_ai.features import encode_observation  # noqa: E402
from ptcg_ai.model import NumpyPolicyModel  # noqa: E402
from ptcg_ai.prevention import attack_nullified  # noqa: E402
from ptcg_ai.safety import sanitize_selection  # noqa: E402
from ptcg_ai.tactical_shield import apply_tactical_shield  # noqa: E402
from ptcg_ai.view import card_table, resolve_area_card  # noqa: E402

BATTLE_CAGE = 1264


@dataclass(frozen=True)
class Target:
    serial: int
    card_id: int
    name: str
    zone: str
    slot: int
    hp: int
    max_hp: int
    damage: int
    prizes: int
    energy: int
    tera: bool
    counter_prevented: bool
    bench_damage_prevented: bool


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _prizes(card: Any) -> int:
    meta = card_table().get(int(card.id))
    return 3 if meta and meta.megaEx else 2 if meta and meta.ex else 1


def _target(obs: Any, option_index: int, effect: str) -> Target | None:
    option = obs.select.option[option_index]
    card = resolve_area_card(obs, option.area, option.index, option.playerIndex)
    if card is None:
        return None
    meta = card_table().get(int(card.id))
    benched = int(option.area) == int(AreaType.BENCH)
    stadium = {int(c.id) for c in (obs.current.stadium or [])}
    tera = bool(meta and meta.tera)
    maximum = int(getattr(card, "maxHp", 0) or (meta.hp if meta else 0) or 0)
    return Target(
        serial=int(getattr(card, "serial", 0) or 0),
        card_id=int(card.id),
        name=str(meta.name if meta else card.id),
        zone="active" if int(option.area) == int(AreaType.ACTIVE) else "bench",
        slot=int(option.index), hp=int(card.hp), max_hp=maximum,
        damage=max(0, maximum - int(card.hp)), prizes=_prizes(card),
        energy=len(card.energies or []), tera=tera,
        counter_prevented=bool(effect == "munk" and benched and BATTLE_CAGE in stadium),
        bench_damage_prevented=bool(effect == "shadow" and benched and tera),
    )


def _a2_action(model: NumpyPolicyModel, obs: Any) -> list[int]:
    features = encode_observation(obs, model.feature_version)
    logits, count_logits, _ = model.predict(features)
    ranked = np.argsort(-logits).astype(int).tolist()
    if int(obs.select.minCount) == int(obs.select.maxCount):
        desired = int(obs.select.maxCount)
    else:
        lo = int(obs.select.minCount)
        hi = min(int(obs.select.maxCount), len(count_logits) - 1)
        desired = lo + int(np.argmax(count_logits[lo : hi + 1]))
    ranked, desired, _ = apply_tactical_shield(obs, ranked, desired)
    return sanitize_selection(obs.select, ranked, desired)


def _valid_action(obs: Any, action: Any) -> list[int] | None:
    if not isinstance(action, list) or not all(isinstance(i, int) for i in action):
        return None
    if any(i < 0 or i >= len(obs.select.option) for i in action):
        return None
    if not int(obs.select.minCount) <= len(action) <= int(obs.select.maxCount):
        return None
    return list(action)


def _semantic(obs: Any, action: list[int]) -> tuple:
    fields = ("type", "number", "area", "index", "playerIndex", "attackId")
    return tuple(tuple(getattr(obs.select.option[i], f, None) for f in fields) for i in action)


def _shadow_ready(obs: Any) -> bool:
    state = obs.current
    me = state.players[state.yourIndex]
    active = next(iter(me.active or []), None)
    return bool(
        active is not None
        and int(active.id) == MARNIES_GRIMMSNARL_EX
        and len(active.energies or []) >= 2
        and not bool(me.asleep)
        and not bool(me.paralyzed)
    )


def _shadow_active_damage(obs: Any, target: Target) -> int:
    if attack_nullified(obs, SimpleNamespace(attackId=SHADOW_BULLET)):
        return 0
    meta = card_table().get(target.card_id)
    return 360 if meta is not None and int(meta.weakness or -1) == 7 else 180


def _score_munk(obs: Any, targets: list[Target], chosen: Target, counters: int, shadow: bool) -> dict:
    moved = 0 if chosen.counter_prevented else 10 * counters
    hp = {target.serial: target.hp for target in targets}
    hp[chosen.serial] -= moved
    immediate = [target for target in targets if hp[target.serial] <= 0]
    active_ko = any(target.zone == "active" for target in immediate)
    best = {
        "prizes": sum(t.prizes for t in immediate), "kos": len(immediate),
        "breakpoints": 0, "overkill": max(0, moved - chosen.hp),
        "shadow_target": None, "active_promotion_abstain": active_ko,
    }
    # A Munk KO of the Active changes promotion.  Refuse to assume which new
    # Active the opponent supplies, as the eventual runtime must do.
    if not shadow or active_ko:
        return best
    active = next((t for t in targets if t.zone == "active"), None)
    active_prizes = active.prizes if active and hp[active.serial] > 0 and hp[active.serial] <= _shadow_active_damage(obs, active) else 0
    active_kos = int(active_prizes > 0)
    bench = [t for t in targets if t.zone == "bench" and not t.bench_damage_prevented and hp[t.serial] > 0]
    choices = bench or [None]
    routes = []
    for bench_target in choices:
        bench_ko = bool(bench_target and hp[bench_target.serial] <= 30)
        breakpoint = int(bool(bench_target and bench_target.serial == chosen.serial and chosen.hp > 30 and hp[chosen.serial] <= 30))
        routes.append((
            best["prizes"] + active_prizes + (bench_target.prizes if bench_ko else 0),
            best["kos"] + active_kos + int(bench_ko), breakpoint,
            -(best["overkill"] + (max(0, 30 - hp[bench_target.serial]) if bench_target else 0)),
            0 if bench_target is None else -bench_target.serial,
            bench_target,
        ))
    route = max(routes, key=lambda item: item[:-1])
    best.update(prizes=route[0], kos=route[1], breakpoints=route[2], overkill=-route[3],
                shadow_target=None if route[5] is None else route[5].serial)
    return best


def _score_shadow(target: Target) -> dict:
    protected = target.bench_damage_prevented
    damage = 0 if protected else 30
    ko = damage >= target.hp
    return {"prizes": target.prizes if ko else 0, "kos": int(ko),
            "breakpoints": int(ko), "overkill": max(0, damage - target.hp),
            "protected": protected}


def _objective(score: dict) -> tuple[int, int, int, int]:
    return (int(score["prizes"]), int(score["kos"]), int(score["breakpoints"]), -int(score["overkill"]))


def _best(scores: dict[int, dict], a2_serial: int) -> int:
    # Stable public serial is the final deterministic tie-break.  Prefer A2 on
    # exact objective ties so the audit does not manufacture disagreement.
    top = max(_objective(value) for value in scores.values())
    tied = [serial for serial, value in scores.items() if _objective(value) == top]
    return a2_serial if a2_serial in tied else min(tied)


def _archetype(names: set[str]) -> str:
    support = {"Munkidori", "Fezandipiti ex", "Fezandipiti", "Dunsparce", "Dudunsparce", "Shaymin", "Relicanth", "Dedenne", "Snorunt", "Froslass", "Riolu", "Sylveon", "Eevee", "Staryu"}
    fingerprints = (
        ("Grimmsnarl", ("Grimmsnarl", "Marnie's Impidimp", "Marnie's Morgrem")),
        ("Alakazam", ("Alakazam", "Kadabra", "Abra")),
        ("Lucario", ("Lucario",)), ("Crustle", ("Crustle", "Dwebble")),
        ("Dragapult", ("Dragapult", "Drakloak", "Dreepy")),
        ("Garchomp", ("Garchomp", "Gabite", "Gible")),
        ("Kangaskhan", ("Kangaskhan",)), ("Ogerpon", ("Ogerpon",)),
        ("Archaludon", ("Archaludon", "Duraludon")),
    )
    core = names - support
    for label, needles in fingerprints:
        if any(needle in name for name in core for needle in needles):
            return label
    return "unknown"


def _episode_archetype(replay: dict, hero: int) -> str:
    names: set[str] = set()
    for step in replay.get("steps", []):
        if hero >= len(step):
            continue
        current = (step[hero].get("observation") or {}).get("current")
        if not current:
            continue
        player = current["players"][1 - hero]
        cards = list(player.get("active") or []) + list(player.get("bench") or []) + list(player.get("discard") or [])
        for card in cards:
            if not card:
                continue
            meta = card_table().get(int(card["id"]))
            if meta is not None and meta.hp:
                names.add(meta.name)
            for prior in card.get("preEvolution") or []:
                prior_meta = card_table().get(int(prior["id"]))
                if prior_meta is not None:
                    names.add(prior_meta.name)
    return _archetype(names)


def _split(rows: list[dict], key: str) -> dict:
    report = {}
    for value in sorted({str(row[key]) for row in rows}):
        part = [row for row in rows if str(row[key]) == value]
        report[value] = {
            "decisions": len(part), "meaningful": sum(r["meaningful"] for r in part),
            "different": sum(r["different"] for r in part),
            "extra_prize": sum(r["extra_prize"] for r in part),
            "extra_ko": sum(r["extra_ko"] for r in part),
            "breakpoint": sum(r["breakpoint"] for r in part),
        }
    return report


def audit(replay_root: Path, submission_id: int, model_path: Path) -> dict:
    metadata = json.loads((replay_root / "episodes_metadata.json").read_text())
    episode_meta = {int(row["id"]): row for row in metadata}
    model = NumpyPolicyModel(model_path)
    rows: list[dict] = []
    counts = Counter()
    parse_failures: dict[str, str] = {}
    parity = Counter()
    examples: list[dict] = []

    for path in sorted(replay_root.glob("episode-*-replay.json")):
        try:
            episode_id = int(path.stem.split("-")[1])
            meta = episode_meta[episode_id]
            hero = next(i for i, agent in enumerate(meta["agents"]) if int(agent.get("submissionId", -1)) == submission_id)
            replay = json.loads(path.read_text())
            archetype = _episode_archetype(replay, hero)
            pending_count: dict[int, int] = {}
            pending_available: dict[int, int] = {}
            turn_targets: defaultdict[int, Counter[int]] = defaultdict(Counter)
            steps = replay.get("steps", [])
            for step_index, step in enumerate(steps[:-1]):
                following = steps[step_index + 1]
                if hero >= len(step) or hero >= len(following):
                    continue
                raw = step[hero]
                if str(raw.get("status", "")).upper() != "ACTIVE":
                    continue
                obs_dict = raw.get("observation") or {}
                if not obs_dict.get("select") or not obs_dict.get("current"):
                    continue
                obs = to_observation_class(obs_dict)
                # Kaggle row t contains the action that produced observation t;
                # the response to observation t is stored in row t+1.
                captured = _valid_action(obs, following[hero].get("action"))
                if captured is None:
                    counts["invalid_captured_action"] += 1
                    continue
                a2 = _a2_action(model, obs)
                parity["decisions"] += 1
                parity["semantic_match"] += int(_semantic(obs, captured) == _semantic(obs, a2))
                effect_id = int(getattr(obs.select.effect, "id", 0) or 0)
                effect_serial = int(getattr(obs.select.effect, "serial", 0) or 0)
                context = int(obs.select.context)
                order = "first" if int(obs.current.firstPlayer) == hero else "second"

                if effect_id == MUNKIDORI and context == int(SelectContext.REMOVE_DAMAGE_COUNTER):
                    counts["munk_source"] += 1
                    if captured:
                        source = _target(obs, captured[0], "source")
                        if source is not None:
                            pending_available[effect_serial] = min(3, source.damage // 10)
                    continue
                if effect_id == MUNKIDORI and context == int(SelectContext.REMOVE_DAMAGE_COUNTER_COUNT):
                    counts["munk_count"] += 1
                    if captured:
                        pending_count[effect_serial] = int(getattr(obs.select.option[captured[0]], "number", 0) or 0)
                    continue
                if not (
                    (effect_id == MUNKIDORI and context == int(SelectContext.DAMAGE_COUNTER))
                    or (effect_id == MARNIES_GRIMMSNARL_EX and context == int(SelectContext.DAMAGE))
                ):
                    continue

                kind = "munk_destination" if effect_id == MUNKIDORI else "shadow_destination"
                counts[kind] += 1
                effect = "munk" if kind.startswith("munk") else "shadow"
                targets = [target for i in range(len(obs.select.option)) if (target := _target(obs, i, effect)) is not None]
                by_serial = {target.serial: target for target in targets}
                if not captured or captured[0] >= len(obs.select.option):
                    continue
                selected = _target(obs, captured[0], effect)
                if selected is None:
                    continue
                legal = [target for target in targets if not target.counter_prevented and not target.bench_damage_prevented]
                meaningful = len(legal) >= 2
                if effect == "munk":
                    chosen_count = pending_count.pop(effect_serial, None)
                    available_counters = pending_available.pop(effect_serial, chosen_count or 0)
                    counters = available_counters if chosen_count is None else chosen_count
                else:
                    available_counters = counters = 0
                scores = (
                    {target.serial: _score_munk(obs, targets, target, counters, _shadow_ready(obs)) for target in legal}
                    if effect == "munk" else {target.serial: _score_shadow(target) for target in legal}
                )
                if selected.serial not in scores:
                    # Preserve the selected protected target as a scoreable zero
                    # so avoidance is visible rather than silently discarded.
                    scores[selected.serial] = _score_munk(obs, targets, selected, counters, _shadow_ready(obs)) if effect == "munk" else _score_shadow(selected)
                best_serial = _best(scores, selected.serial)
                selected_score, best_score = scores[selected.serial], scores[best_serial]
                different = meaningful and best_serial != selected.serial and _objective(best_score) > _objective(selected_score)
                count_score = (
                    _score_munk(obs, targets, selected, available_counters, _shadow_ready(obs))
                    if effect == "munk" and available_counters > counters else selected_score
                )
                count_regret = _objective(count_score) > _objective(selected_score)
                row = {
                    "episode": episode_id, "step": step_index, "turn": int(obs.current.turn),
                    "order": order, "archetype": archetype, "kind": kind,
                    "meaningful": meaningful, "different": different,
                    "counters": counters, "available_counters": available_counters,
                    "count_regret": count_regret, "shadow_ready": _shadow_ready(obs),
                    "a2_target": selected.serial, "best_target": best_serial,
                    "extra_prize": max(0, int(best_score["prizes"]) - int(selected_score["prizes"])),
                    "extra_ko": max(0, int(best_score["kos"]) - int(selected_score["kos"])),
                    "breakpoint": int(best_score["breakpoints"] > selected_score["breakpoints"]),
                    "waste_reduction": max(0, int(selected_score["overkill"]) - int(best_score["overkill"])),
                    "a2_score": selected_score, "best_score": best_score,
                    "targets": [asdict(target) for target in targets],
                    "prizes_remaining": len(obs.current.players[obs.current.yourIndex].prize or []),
                }
                rows.append(row)
                if effect == "munk":
                    turn_targets[int(obs.current.turn)][selected.serial] += counters
                if different and len(examples) < 30:
                    examples.append(row)
        except Exception as exc:
            parse_failures[path.name] = repr(exc)

    meaningful = [row for row in rows if row["meaningful"]]
    different = [row for row in rows if row["different"]]
    clear = [row for row in different if row["extra_prize"] or row["extra_ko"] or row["breakpoint"]]
    munk_by_turn: defaultdict[tuple[int, int], list[dict]] = defaultdict(list)
    for row in rows:
        if row["kind"] == "munk_destination":
            munk_by_turn[(row["episode"], row["turn"])].append(row)
    spread_turns = [part for part in munk_by_turn.values() if len({row["a2_target"] for row in part}) >= 2]
    spread_missed = [part for part in spread_turns if any(row["different"] and (row["extra_ko"] or row["breakpoint"]) for row in part)]
    stop = len(meaningful) < 20 or len(clear) < 5
    return {
        "label": "PUBLIC REPLAY DAMAGE-REGRET AUDIT — DESCRIPTIVE, NOT GAMEPLAY CAUSAL",
        "source": {"replays": str(replay_root), "submission_id": submission_id,
                   "games": len(list(replay_root.glob("episode-*-replay.json"))),
                   "model": str(model_path), "model_sha256": sha256(model_path)},
        "a2_reconstruction": dict(parity), "prompt_counts": dict(counts),
        "summary": {
            "target_decisions": len(rows), "meaningful_multi_target": len(meaningful),
            "arithmetically_different": len(different), "clear_prize_ko_or_breakpoint": len(clear),
            "extra_prize_decisions": sum(row["extra_prize"] > 0 for row in rows),
            "extra_ko_decisions": sum(row["extra_ko"] > 0 for row in rows),
            "breakpoint_improvements": sum(row["breakpoint"] for row in rows),
            "waste_reductions": sum(row["waste_reduction"] > 0 for row in rows),
            "munk_count_regrets": sum(row["count_regret"] for row in rows),
            "spread_turns": len(spread_turns),
            "spread_turns_with_missed_concentration_ko_or_breakpoint": len(spread_missed),
            "overkill_with_alternate_breakpoint": sum(
                row["different"] and row["a2_score"]["overkill"] > 0 and row["breakpoint"] for row in rows
            ),
            "protected_targets_selected": sum(
                any(t["serial"] == row["a2_target"] and (t["counter_prevented"] or t["bench_damage_prevented"]) for t in row["targets"])
                for row in rows
            ),
            "stop_spread_experiment": stop,
            "stop_reason": "fewer than 20 meaningful states or fewer than 5 clear decisions" if stop else None,
        },
        "by_order": _split(rows, "order"), "by_archetype_description_only": _split(rows, "archetype"),
        "representative_changes": examples[:15], "parse_failures": parse_failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replays", type=Path, default=ROOT / "data/replays/55399728")
    parser.add_argument("--submission-id", type=int, default=55399728)
    parser.add_argument("--model", type=Path, default=ROOT / "artifacts/recovery_probes/extracted/a2/policy_weights.npz")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/grim_damage_conversion/damage_regret_audit.json")
    args = parser.parse_args()
    report = audit(args.replays, args.submission_id, args.model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), **report["summary"], "prompt_counts": report["prompt_counts"],
                      "a2_reconstruction": report["a2_reconstruction"], "by_order": report["by_order"]}, indent=2))


if __name__ == "__main__":
    main()
