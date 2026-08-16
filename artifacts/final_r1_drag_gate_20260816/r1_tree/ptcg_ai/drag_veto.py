"""One-shot Dragapult END->Grim-line-EVOLVE veto (R1 shadow proposer).

Frozen evidence: complete-turn root 93755661:58 ADMITTED 4/4 worlds
(baseline EXP23 END -> candidate R1 EVOLVE Marnie line, prizes 0->1,
ready_attackers 0->1, route_progress 3.25->4.25).

Fail-closed: base action is returned unchanged unless every predicate below
holds. Fires at most once per game.
"""
from __future__ import annotations

from pathlib import Path

from cg.api import AreaType, OptionType, SelectContext, to_observation_class

DRAG_IDS = {119, 120, 121}   # Dreepy, Drakloak, Dragapult ex
EVOLVE_SOURCES = {647, 648}  # Marnie's Morgrem, Marnie's Grimmsnarl ex
EVOLVE_TARGETS = {646, 647}  # Marnie's Impidimp, Marnie's Morgrem


def _zone_cards(zone):
    return [c for c in (zone or []) if c is not None]


class DragEndEvolveVeto:
    def __init__(self, model_path=None) -> None:
        if model_path is not None:
            model_path = str(Path(model_path).resolve())
        self.model_path = model_path
        self.pending = False
        self.locked = False
        self.fired = False
        self.telemetry = []
        self._model = None

    def reset(self) -> None:
        self.pending = False
        self.locked = False
        self.fired = False
        self.telemetry = []

    def _shadow_model(self):
        if self._model is None and self.model_path is not None:
            from .features import PLAY_IDENTITY_ENABLED  # noqa: F401
            from .model import NumpyPolicyModel

            self._model = NumpyPolicyModel(self.model_path)
        return self._model

    def _public_drag_evidence(self, obs) -> bool:
        current = obs.current
        if current is None:
            return False
        players = current.players or []
        opp_index = 1 - int(current.yourIndex)
        if opp_index < 0 or opp_index >= len(players):
            return False
        opp = players[opp_index]
        for slot in _zone_cards(opp.active) + _zone_cards(opp.bench):
            if int(slot.id) in DRAG_IDS:
                return True
            for pre in _zone_cards(getattr(slot, "preEvolution", None)):
                if int(pre.id) in DRAG_IDS:
                    return True
        for card in _zone_cards(opp.discard):
            if int(card.id) in DRAG_IDS:
                return True
        for card in _zone_cards(current.stadium):
            if int(card.id) in DRAG_IDS:
                return True
        return False

    def _has_ready_grim(self, obs) -> bool:
        current = obs.current
        if current is None:
            return True
        players = current.players or []
        me_index = int(current.yourIndex)
        if me_index >= len(players):
            return True
        me = players[me_index]
        for slot in _zone_cards(me.active) + _zone_cards(me.bench):
            if int(slot.id) == 648 and len(_zone_cards(getattr(slot, "energies", None))) >= 2:
                return True
        return False

    def _opp_active_drag(self, obs) -> bool:
        current = obs.current
        if current is None:
            return False
        players = current.players or []
        opp_index = 1 - int(current.yourIndex)
        if opp_index >= len(players):
            return False
        active = _zone_cards(players[opp_index].active)
        return bool(active) and int(active[0].id) in DRAG_IDS

    def _resolve_card(self, obs, area, index, player_index=None):
        current = obs.current
        if current is None or area is None or index is None:
            return None
        state = current
        owner = int(state.yourIndex) if player_index is None else int(player_index)
        players = state.players or []
        if owner >= len(players):
            return None
        player = players[owner]
        zone = {
            int(AreaType.HAND): player.hand,
            int(AreaType.DISCARD): player.discard,
            int(AreaType.ACTIVE): player.active,
            int(AreaType.BENCH): player.bench,
            int(AreaType.PRIZE): player.prize,
        }.get(int(area), []) or []
        zone = _zone_cards(zone)
        return zone[index] if 0 <= index < len(zone) else None

    def _grim_evolve_options(self, obs):
        options = obs.select.option or []
        hand = _zone_cards(obs.current.players[int(obs.current.yourIndex)].hand)
        out = []
        for index, option in enumerate(options):
            if int(option.type) != int(OptionType.EVOLVE):
                continue
            source = None
            if option.area is not None and int(option.area) == int(AreaType.HAND):
                i = int(option.index)
                source = hand[i] if 0 <= i < len(hand) else None
            else:
                source = self._resolve_card(obs, option.area, option.index, option.playerIndex)
            target = self._resolve_card(obs, option.inPlayArea, option.inPlayIndex, obs.current.yourIndex)
            if source is None or target is None:
                continue
            sid, tid = int(source.id), int(target.id)
            if sid in EVOLVE_SOURCES and tid in EVOLVE_TARGETS and sid == tid + 1:
                out.append((index, sid, tid))
        return out

    def _is_end(self, obs, action) -> bool:
        if len(action) != 1:
            return False
        options = obs.select.option or []
        idx = int(action[0])
        return 0 <= idx < len(options) and int(options[idx].type) == int(OptionType.END)

    def _shadow_choice(self, obs):
        model = self._shadow_model()
        if model is None:
            return None
        import numpy as np

        from . import features as _f
        from .safety import sanitize_selection

        previous = _f.PLAY_IDENTITY_ENABLED
        _f.PLAY_IDENTITY_ENABLED = True
        try:
            feats = _f.encode_observation(obs, model.feature_version)
            logits, count_logits, _ = model.predict(feats)
        finally:
            _f.PLAY_IDENTITY_ENABLED = previous
        if not len(logits):
            return []
        ranked = np.argsort(-logits).astype(int).tolist()
        minimum = int(obs.select.minCount)
        maximum = min(int(obs.select.maxCount), len(count_logits) - 1, len(ranked))
        desired = maximum if minimum == maximum else minimum + int(
            np.argmax(count_logits[minimum : maximum + 1])
        )
        return sanitize_selection(obs.select, ranked, desired)

    def intercept(self, obs, action):
        if obs.current is None:
            return action
        if self._public_drag_evidence(obs) and not self.fired:
            self.pending = True
        if self.pending and int(obs.select.context) == int(SelectContext.MAIN):
            self.pending = False
            self.locked = True
        if not self.locked or self.fired:
            return action
        if int(obs.select.context) != int(SelectContext.MAIN):
            return action
        if not self._is_end(obs, action):
            return action
        if self._has_ready_grim(obs):
            return action
        if not self._opp_active_drag(obs):
            return action
        evolves = self._grim_evolve_options(obs)
        if not evolves:
            return action
        try:
            shadow = self._shadow_choice(obs)
        except Exception:
            return action
        if shadow is None:
            return action
        matches = [index for index, _, _ in evolves if len(shadow) == 1 and int(shadow[0]) == index]
        if len(matches) != 1:
            self.telemetry.append({
                "event": "veto_failed_closed",
                "base_end": True,
                "evolve_candidates": evolves,
                "shadow_choice": [int(i) for i in shadow],
            })
            return action
        self.fired = True
        index, sid, tid = matches[0], evolves[0][1], evolves[0][2]
        self.telemetry.append({
            "event": "veto_fired",
            "source_card": sid,
            "target_card": tid,
            "evolve_option": index,
        })
        return [index]
