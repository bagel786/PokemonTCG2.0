"""Evaluation-only seeded native-search backend.

The backend binds a study-built engine that exports ``SearchSetSeed``.  It does
not replace ``vendor/cg`` and must never be included in a competition package.
"""

from __future__ import annotations

import ctypes
import json
from pathlib import Path
from typing import Mapping, Sequence


class SeededSearchBackend:
    def __init__(self, library_path: str | Path, *, initialize: bool = True):
        from cg.api import ApiResult, json_to_dataclass

        self._api_result_type = ApiResult
        self._json_to_dataclass = json_to_dataclass
        self.library_path = Path(library_path).resolve()
        if not self.library_path.is_file():
            raise FileNotFoundError(self.library_path)
        self.lib = ctypes.CDLL(str(self.library_path))
        self.lib.GameInitialize.argtypes = []
        self.lib.GameInitialize.restype = None
        if initialize:
            self.lib.GameInitialize()
        self.lib.AgentStart.argtypes = []
        self.lib.AgentStart.restype = ctypes.c_void_p
        if not hasattr(self.lib, "SearchSetSeed"):
            raise RuntimeError("evaluation engine lacks SearchSetSeed")
        self.lib.SearchSetSeed.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.lib.SearchSetSeed.restype = ctypes.c_int
        self.lib.SearchBegin.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_int,
        ]
        self.lib.SearchBegin.restype = ctypes.c_char_p
        self.lib.SearchStep.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int64,
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_int,
        ]
        self.lib.SearchStep.restype = ctypes.c_char_p
        self.lib.SearchEnd.argtypes = [ctypes.c_void_p]
        self.lib.SearchEnd.restype = None
        self.lib.SearchRelease.argtypes = [ctypes.c_void_p, ctypes.c_int64]
        self.lib.SearchRelease.restype = None
        self.agent_ptr = self.lib.AgentStart()
        if not self.agent_ptr:
            raise RuntimeError("evaluation engine failed to create search agent")
        self._instrumentation_enabled = True
        self.forward_model_calls = 0
        self.end_calls = 0
        self.release_calls = 0

    def configure_instrumentation(self, enabled: bool) -> None:
        """Enable optional timed-path counters without changing engine state."""

        self._instrumentation_enabled = bool(enabled)

    @staticmethod
    def _array(values: Sequence[int]):
        normalized = [int(value) for value in values]
        return (ctypes.c_int * len(normalized))(*normalized)

    def _state(self, payload: bytes):
        result = self._json_to_dataclass(payload, self._api_result_type)
        if int(result.error):
            raise RuntimeError(f"seeded search engine error {int(result.error)}")
        if result.state is None:
            raise RuntimeError("seeded search engine returned no state")
        return result.state

    def reset_seed(self, seed: int) -> None:
        error = self.lib.SearchSetSeed(self.agent_ptr, ctypes.c_uint32(int(seed)).value)
        if error:
            raise RuntimeError(f"SearchSetSeed failed with error {error}")

    def begin(self, observation, kwargs: Mapping[str, Sequence[int]], *, manual_coin: bool = False):
        serialized = observation.search_begin_input
        if serialized is None:
            raise ValueError("observation lacks search_begin_input")
        values = {
            name: self._array(kwargs[name])
            for name in (
                "your_deck",
                "your_prize",
                "opponent_deck",
                "opponent_prize",
                "opponent_hand",
                "opponent_active",
            )
        }
        payload = self.lib.SearchBegin(
            self.agent_ptr,
            serialized.encode("ascii"),
            len(serialized),
            values["your_deck"],
            values["your_prize"],
            values["opponent_deck"],
            values["opponent_prize"],
            values["opponent_hand"],
            values["opponent_active"],
            int(manual_coin),
        )
        return self._state(payload)

    def step(self, search_id: int, selection: Sequence[int]):
        values = self._array(selection)
        payload = self.lib.SearchStep(self.agent_ptr, int(search_id), values, len(values))
        if self._instrumentation_enabled:
            self.forward_model_calls += 1
        return self._state(payload)

    def release(self, search_id: int) -> None:
        self.lib.SearchRelease(self.agent_ptr, int(search_id))
        self.release_calls += 1

    def end(self) -> None:
        self.lib.SearchEnd(self.agent_ptr)
        self.end_calls += 1


class SeededGameBackend:
    """Seeded gameplay adapter sharing one initialized evaluation library."""

    def __init__(self, library_path: str | Path):
        from cg.sim import SerialData, StartData

        self.library_path = Path(library_path).resolve()
        if not self.library_path.is_file():
            raise FileNotFoundError(self.library_path)
        self.lib = ctypes.CDLL(str(self.library_path))
        self.lib.GameInitialize.argtypes = []
        self.lib.GameInitialize.restype = None
        self.lib.GameInitialize()
        if not hasattr(self.lib, "BattleStartSeeded"):
            raise RuntimeError("evaluation engine lacks BattleStartSeeded")
        self.lib.BattleStartSeeded.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_uint32]
        self.lib.BattleStartSeeded.restype = StartData
        self.lib.BattleFinish.argtypes = [ctypes.c_void_p]
        self.lib.BattleFinish.restype = None
        self.lib.GetBattleData.argtypes = [ctypes.c_void_p]
        self.lib.GetBattleData.restype = SerialData
        self.lib.Select.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.c_int]
        self.lib.Select.restype = ctypes.c_int

    def _observation(self, battle_ptr: int) -> dict:
        serial = self.lib.GetBattleData(battle_ptr)
        observation = json.loads(serial.json.decode("utf-8"))
        observation["search_begin_input"] = ctypes.string_at(serial.data, serial.count).decode("ascii")
        return observation

    def start(self, deck0: list[int], deck1: list[int], seed: int) -> tuple[int, dict]:
        if len(deck0) != 60 or len(deck1) != 60:
            raise ValueError("each deck must contain exactly 60 cards")
        cards = (ctypes.c_int * 120)(*(list(map(int, deck0)) + list(map(int, deck1))))
        started = self.lib.BattleStartSeeded(cards, ctypes.c_uint32(int(seed)).value)
        if not started.battlePtr:
            raise RuntimeError(
                f"seeded engine rejected deck for player {started.errorPlayer}: {started.errorType}"
            )
        pointer = int(started.battlePtr)
        return pointer, self._observation(pointer)

    def select(self, battle_ptr: int, selection: Sequence[int]) -> dict:
        values = self._array(selection)
        error = self.lib.Select(battle_ptr, values, len(selection))
        if error:
            raise RuntimeError(f"seeded engine rejected selection with error {error}")
        return self._observation(battle_ptr)

    @staticmethod
    def _array(values: Sequence[int]):
        normalized = [int(value) for value in values]
        return (ctypes.c_int * len(normalized))(*normalized)

    def finish(self, battle_ptr: int) -> None:
        self.lib.BattleFinish(battle_ptr)
