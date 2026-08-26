"""Seeded Pokémon game acquisition with per-decision study telemetry."""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from .canonical import canonical_json_bytes, derive_u32, hash_json
from .runner import CaseContext, run_decision
from .stop_policy import FixedWorkStop, WallClockStop
from .telemetry import DecisionTelemetry, GameTelemetry
from .adapters.native_backend import SeededGameBackend
from .adapters.pokemon import PokemonAdapterConfig, PokemonSearchAdapter


def _combination_count(option_count: int, minimum: int, maximum: int) -> int:
    return sum(
        math.comb(option_count, count)
        for count in range(minimum, maximum + 1)
        if 0 <= count <= option_count
    )


class FixedAnchorAgent:
    """Frozen deterministic neural policy; it performs no forward search."""

    def __init__(self, deck_path: str | Path, model_path: str | Path):
        from ptcg_ai.model import NumpyPolicyModel
        from training.search_teacher import load_deck

        self.deck = load_deck(deck_path)
        self.model = NumpyPolicyModel(model_path)

    def __call__(self, raw: dict[str, Any]) -> list[int]:
        from cg.api import to_observation_class
        from training.search_teacher import deterministic_model_action

        if raw.get("select") is None:
            return list(self.deck)
        return deterministic_model_action(self.model, to_observation_class(raw))


class StudyGameAgent:
    def __init__(self, adapter: PokemonSearchAdapter, row: Mapping[str, Any]):
        self.adapter = adapter
        self.row = row
        self.decision_records: list[DecisionTelemetry] = []
        self.search_decision_index = 0

    def reset(self, row: Mapping[str, Any]) -> None:
        self.row = row
        self.decision_records.clear()
        self.search_decision_index = 0

    def _fallback(self, observation) -> list[int]:
        from training.search_teacher import deterministic_model_action

        return deterministic_model_action(self.adapter.hero_model, observation)

    def __call__(self, raw: dict[str, Any]) -> list[int]:
        from cg.api import to_observation_class

        if raw.get("select") is None:
            self.decision_records.clear()
            self.search_decision_index = 0
            return list(self.adapter.hero_deck)
        observation = to_observation_class(raw)
        select = observation.select
        possible = _combination_count(
            len(select.option),
            int(select.minCount),
            int(select.maxCount),
        )
        if possible <= 1:
            return self._fallback(observation)

        budget_mode = str(self.row["budget_mode"])
        if budget_mode == "fixed_work":
            stop = FixedWorkStop(int(self.row["requested_work_units"]))
        elif budget_mode == "wall_clock":
            stop = WallClockStop(int(self.row["requested_budget_ns"]), time.monotonic_ns)
        else:
            raise ValueError(f"unknown budget mode: {budget_mode}")
        decision_seed = derive_u32(
            int(self.row["agent_seed"]),
            "game_decision",
            self.search_decision_index,
        )
        context = CaseContext(
            case_id=str(self.row["case_id"]),
            block_id=str(self.row["block_id"]),
            decision_index=self.search_decision_index,
            load_condition=str(self.row["load_condition"]),
            lifecycle=str(self.row["lifecycle"]),
            lifecycle_id=str(self.row["lifecycle_id"]),
            process_instance_id=str(self.row["process_instance_id"]),
            sequence_index=int(self.row["sequence_index"]),
            load_batch_id=str(self.row["load_batch_id"]),
            agent_seed=decision_seed,
            instrumentation_enabled=True,
        )
        record = run_decision(self.adapter, raw, stop, context)
        self.search_decision_index += 1
        if record.terminal_status in {"ok", "deadline_no_work"} and record.selected_action:
            action = list(record.selected_action)
        else:
            action = self._fallback(observation)
            record.selected_action = list(action)
            try:
                identity = self.adapter.action_identity(action)
            except Exception:
                identity = {"option_indexes": action}
            record.selected_action_hash = hash_json(identity)
            record.extra["selected_action_identity"] = identity
            record.fallback_reason = record.fallback_reason or "deterministic_anchor_fallback"
        self.decision_records.append(record)
        return action


def _forced_order(select, hero_seat: int, requested_order: int) -> list[int]:
    from cg.api import OptionType
    from ptcg_ai.safety import sanitize_selection

    seat_zero_first = (requested_order == 0) == (hero_seat == 0)
    desired = OptionType.YES if seat_zero_first else OptionType.NO
    choices = [index for index, option in enumerate(select.option) if option.type == desired]
    if len(choices) != 1:
        raise RuntimeError("invalid forced-order choice set")
    return sanitize_selection(select, choices, 1)


class GameExecutor:
    """Reusable process-local executor for fresh or bounded persistent cases."""

    def __init__(
        self,
        *,
        engine_path: str | Path,
        adapter_configs: Mapping[str, PokemonAdapterConfig],
        anchor_deck_path: str | Path,
        anchor_model_path: str | Path,
        max_decisions: int = 2_000,
    ):
        self.engine = SeededGameBackend(engine_path)
        self.adapter_configs = dict(adapter_configs)
        self.adapters: dict[str, PokemonSearchAdapter] = {}
        self.anchor = FixedAnchorAgent(anchor_deck_path, anchor_model_path)
        self.max_decisions = int(max_decisions)

    def _adapter(self, agent_id: str) -> PokemonSearchAdapter:
        if agent_id not in self.adapters:
            config = self.adapter_configs[agent_id]
            # The gameplay backend already initialized this exact library.
            config = PokemonAdapterConfig(**{**asdict(config), "initialize_engine": False})
            self.adapters[agent_id] = PokemonSearchAdapter(config)
        return self.adapters[agent_id]

    def run(self, row: Mapping[str, Any]) -> dict[str, Any]:
        from cg.api import SelectContext, to_observation_class

        agent_id = str(row["agent_id"])
        hero_seat = int(row["physical_seat"])
        requested_order = int(row["play_order"])
        study_agent = StudyGameAgent(self._adapter(agent_id), row)
        decks = (
            [study_agent.adapter.hero_deck, self.anchor.deck]
            if hero_seat == 0
            else [self.anchor.deck, study_agent.adapter.hero_deck]
        )
        battle_ptr = 0
        gameplay_decisions = 0
        trace_digest = hashlib.sha256()
        terminal_status = "completed"
        error_type = ""
        error_message = ""
        score: float | None = None
        winner: int | None = None
        observed_first_player: int | None = None
        try:
            battle_ptr, raw = self.engine.start(
                decks[0],
                decks[1],
                int(row["environment_seed"]),
            )
            while True:
                observation = to_observation_class(raw)
                current = observation.current
                if current is not None and int(current.firstPlayer) in (0, 1):
                    observed = int(current.firstPlayer)
                    if observed_first_player is None:
                        observed_first_player = observed
                    elif observed_first_player != observed:
                        raise RuntimeError("first player changed after latch")
                if current is not None and int(current.result) >= 0:
                    winner = int(current.result)
                    score = 0.5 if winner == 2 else float(winner == hero_seat)
                    break
                if observation.select.context == SelectContext.IS_FIRST:
                    action = _forced_order(observation.select, hero_seat, requested_order)
                    actor = "forced_order"
                else:
                    acting_seat = int(current.yourIndex)
                    if acting_seat == hero_seat:
                        action = study_agent(raw)
                        actor = "study_agent"
                    else:
                        action = self.anchor(raw)
                        actor = "fixed_anchor"
                trace_digest.update(
                    canonical_json_bytes(
                        {
                            "decision": gameplay_decisions,
                            "actor": actor,
                            "action": list(action),
                            "public_state_hash": hash_json(
                                {key: value for key, value in raw.items() if key != "search_begin_input"}
                            ),
                        }
                    )
                )
                raw = self.engine.select(battle_ptr, action)
                gameplay_decisions += 1
                if gameplay_decisions >= self.max_decisions:
                    raise RuntimeError("game exceeded decision cap")
            if observed_first_player is None:
                raise RuntimeError("terminal game has no latched first player")
            observed_order = 0 if observed_first_player == hero_seat else 1
            if observed_order != requested_order:
                raise RuntimeError(
                    f"requested play order {requested_order}, observed {observed_order}"
                )
        except Exception as exc:
            terminal_status = "engine_error"
            error_type = type(exc).__name__
            error_message = str(exc)
        finally:
            if battle_ptr:
                self.engine.finish(battle_ptr)

        if any(
            decision.terminal_status == "fixed_work_invalid"
            for decision in study_agent.decision_records
        ):
            terminal_status = "protocol_invalid"
        game = GameTelemetry.from_decisions(
            case_id=str(row["case_id"]),
            block_id=str(row["block_id"]),
            agent_id=agent_id,
            decisions=study_agent.decision_records,
            score=score,
            winner=winner,
            terminal_status=terminal_status,
            error_type=error_type,
            error_message=error_message,
        )
        payload = {
            "schedule_row": dict(row),
            "game": game.__dict__,
            "decisions": [decision.to_dict() for decision in study_agent.decision_records],
            "gameplay_decisions": gameplay_decisions,
            "public_trace_sha256": trace_digest.hexdigest(),
        }
        payload["artifact_sha256"] = hash_json(payload)
        return payload
