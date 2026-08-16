#!/usr/bin/env python3
"""Compare sanitized B0/B1/B2/B3 actions on local public replay states.

This is a replay-sequential decision audit.  After the first disagreement,
later observations still follow the captured replay, so it is descriptive and
not a causal gameplay estimate.  No hidden opponent information is read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]

from cg.api import OptionType, SelectContext, to_observation_class
from ptcg_ai.features import encode_observation
from ptcg_ai.grim_guardrails import GrimGuardrailDirector
from ptcg_ai.grim_runtime_policy import GrimRuntimePolicy, SearchDisabledProof
from ptcg_ai.grim_variance_floor import GrimVarianceConfig, GrimVarianceFloorDirector
from ptcg_ai.model import NumpyPolicyModel
from ptcg_ai.safety import sanitize_selection


DEFAULT_REPLAYS = ROOT / "data" / "replays"
DEFAULT_OUTPUT = ROOT / "artifacts" / "grim_variance_floor" / "decision_audit.json"


def _paths(source: Path) -> list[Path]:
    if source.is_file():
        return [source]
    return sorted(source.rglob("*.json")) if source.exists() else []


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _d842_intent(model: NumpyPolicyModel, obs) -> tuple[list[int], int, list[int]]:
    features = encode_observation(obs, model.feature_version)
    logits, count_logits, _ = model.predict(features)
    ranked = np.argsort(-logits).astype(int).tolist()
    if obs.select.minCount == obs.select.maxCount:
        desired = int(obs.select.maxCount)
    else:
        minimum = int(obs.select.minCount)
        maximum = min(int(obs.select.maxCount), len(count_logits) - 1)
        desired = minimum + int(np.argmax(count_logits[minimum : maximum + 1]))
    return ranked, desired, sanitize_selection(obs.select, ranked, desired)


def _option_signature(option: Any) -> tuple:
    fields = (
        "type",
        "number",
        "area",
        "index",
        "playerIndex",
        "toolIndex",
        "energyIndex",
        "count",
        "inPlayArea",
        "inPlayIndex",
        "attackId",
        "cardId",
        "serial",
    )
    return tuple((field, str(getattr(option, field, None))) for field in fields)


def _action_signature(obs, action: list[int]) -> tuple:
    return tuple(_option_signature(obs.select.option[index]) for index in action)


def _ordinal(obs) -> int:
    state = obs.current
    if state is None or int(state.turn) <= 0 or int(state.firstPlayer) not in (0, 1):
        return 0
    return (int(state.turn) + 1) // 2 if int(state.yourIndex) == int(state.firstPlayer) else int(state.turn) // 2


def _bucket(ordinal: int) -> str:
    return "setup/0" if ordinal <= 0 else str(ordinal) if ordinal <= 3 else "4+"


def _category(reason: str | None) -> str | None:
    if reason is None:
        return None
    reason = str(reason)
    if reason.startswith("setup:"):
        return "setup"
    if reason == "attack:shadow_over_retreat":
        return "shadow_over_retreat"
    if reason == "attack:shadow_over_boss_active_ko":
        return "shadow_over_Boss"
    if reason == "variance_floor:punk_up_activate":
        return "Punk Up activate"
    if reason == "variance_floor:punk_up_count":
        return "Punk Up count"
    if reason == "variance_floor:punk_up_target":
        return "Punk Up target"
    if reason == "variance_floor:attach_to_escape_dead_support":
        return "attach_to_escape"
    if reason == "variance_floor:dead_support_retreat_to_ready_grim":
        return "direct retreat escape"
    if reason == "variance_floor:complete_escape_retreat":
        return "complete escape retreat"
    if reason == "variance_floor:escape_promote_ready_grim":
        return "escape promotion"
    if reason == "nullified_attack":
        return "tactical:nullified_attack"
    if reason == "end_with_productive_attack":
        return "tactical:end_with_productive_attack"
    return reason


def _policy(variant: str) -> GrimRuntimePolicy:
    if variant == "B1":
        guardrail = GrimGuardrailDirector()
    elif variant == "B2":
        guardrail = GrimVarianceFloorDirector(
            GrimVarianceConfig(punk_up_floor=True, dead_active_escape=False)
        )
    elif variant == "B3":
        guardrail = GrimVarianceFloorDirector(
            GrimVarianceConfig(punk_up_floor=True, dead_active_escape=True)
        )
    else:
        raise ValueError(variant)
    return GrimRuntimePolicy(guardrail=guardrail, proof=SearchDisabledProof())


def _reason(policy: GrimRuntimePolicy) -> str | None:
    last = policy.telemetry().get("last", {})
    return last.get("guardrail_reason") or last.get("tactical_reason")


def _trace(obs, action: list[int], reason: str, episode: str, seat: int, step: int) -> dict:
    state = obs.current
    me = state.players[state.yourIndex]
    active = next((card for card in (me.active or []) if card is not None), None)
    return {
        "episode_id": episode,
        "seat": seat,
        "step": step,
        "turn": int(state.turn),
        "own_turn_ordinal": _ordinal(obs),
        "actual_order": "first" if int(state.firstPlayer) == seat else "second",
        "reason": reason,
        "active": None
        if active is None
        else {"id": int(active.id), "serial": int(active.serial), "energy": len(active.energies or [])},
        "bench": [
            {"id": int(card.id), "serial": int(card.serial), "energy": len(card.energies or [])}
            for card in (me.bench or [])
        ],
        "selected": [_option_signature(obs.select.option[index]) for index in action],
    }


def audit(*, replays: Path, model_path: Path, seat: int = 0) -> dict:
    model = NumpyPolicyModel(model_path)
    rows_by_variant = {variant: [] for variant in ("B0", "B1", "B2", "B3")}
    traces_by_variant = {variant: [] for variant in ("B1", "B2", "B3")}
    failures = {}
    for path in _paths(replays):
        try:
            replay = json.loads(path.read_text(encoding="utf-8"))
            episode = str((replay.get("info") or {}).get("EpisodeId") or path.stem)
            policies = {variant: _policy(variant) for variant in ("B1", "B2", "B3")}
            for policy in policies.values():
                policy.reset()
            steps = replay.get("steps") or []
            for step, current_step in enumerate(steps[:-1]):
                if seat >= len(current_step) or seat >= len(steps[step + 1]):
                    continue
                row = current_step[seat]
                if str(row.get("status", "")).upper() != "ACTIVE":
                    continue
                obs_dict = row.get("observation") or {}
                if not obs_dict.get("select") or not obs_dict.get("current"):
                    continue
                obs = to_observation_class(obs_dict)
                if int(obs.current.yourIndex) != seat:
                    continue
                ranked, desired, b0_action = _d842_intent(model, obs)
                b0_signature = _action_signature(obs, b0_action)
                first_player = int(obs.current.firstPlayer)
                order = "first" if first_player == seat else "second" if first_player in (0, 1) else "unknown"
                ordinal = _ordinal(obs)
                rows_by_variant["B0"].append(
                    {
                        "episode_id": episode,
                        "seat": seat,
                        "step": step,
                        "actual_order": order,
                        "ordinal": ordinal,
                        "action": b0_signature,
                        "changed": False,
                        "reason": None,
                    }
                )
                for variant, policy in policies.items():
                    action = policy.choose(obs, ranked, desired)
                    reason = _reason(policy)
                    signature = _action_signature(obs, action)
                    rows_by_variant[variant].append(
                        {
                            "episode_id": episode,
                            "seat": seat,
                            "step": step,
                            "actual_order": order,
                            "ordinal": ordinal,
                            "action": signature,
                            "changed": signature != b0_signature,
                            "reason": reason,
                            "category": _category(reason),
                        }
                    )
                    if _category(reason) in {
                        "attach_to_escape",
                        "direct retreat escape",
                        "complete escape retreat",
                        "escape promotion",
                    }:
                        traces_by_variant[variant].append(
                            _trace(obs, action, reason or "", episode, seat, step)
                        )
        except Exception as exc:
            failures[str(path)] = repr(exc)

    report = {
        "label": "LOCAL REPLAY DECISION AUDIT - DESCRIPTIVE, NOT CAUSAL GAMEPLAY",
        "model_path": str(model_path),
        "model_sha256": _hash(model_path),
        "replays": str(replays),
        "seat": seat,
        "parse_failures": failures,
        "candidates": {},
    }
    for variant, rows in rows_by_variant.items():
        changed = [row for row in rows if row.get("changed")]
        by_reason = Counter(row.get("category") for row in changed if row.get("category"))
        interventions = Counter(row.get("category") for row in rows if row.get("category"))
        by_ordinal = {}
        for bucket in ("setup/0", "1", "2", "3", "4+"):
            part = [row for row in changed if _bucket(int(row["ordinal"])) == bucket]
            by_ordinal[bucket] = {"decisions_changed": len(part), "decisions": sum(_bucket(int(row["ordinal"])) == bucket for row in rows)}
        by_order = {
            order: {
                "decisions": sum(row["actual_order"] == order for row in rows),
                "decisions_changed": sum(row["actual_order"] == order for row in changed),
            }
            for order in ("first", "second")
        }
        disagreement = len(changed) / len(rows) if rows else None
        report["candidates"][variant] = {
            "hero_decisions": len(rows),
            "decisions_changed_vs_d842": len(changed),
            "disagreement_rate": disagreement,
            "disagreement_percent": disagreement * 100 if disagreement is not None else None,
            "required_gate_passed": disagreement is not None and disagreement <= 0.03,
            "preferred_gate_passed": disagreement is not None and disagreement <= 0.02,
            "hard_stop_over_5_percent": disagreement is not None and disagreement > 0.05,
            "interventions_by_reason": dict(sorted(interventions.items())),
            "changed_by_reason": dict(sorted(by_reason.items())),
            "by_own_turn_ordinal": by_ordinal,
            "by_actual_order": by_order,
            "escape_traces": traces_by_variant.get(variant, []),
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replays", type=Path, default=DEFAULT_REPLAYS)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--seat", type=int, default=0, choices=(0, 1))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = audit(replays=args.replays, model_path=args.model, seat=args.seat)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
