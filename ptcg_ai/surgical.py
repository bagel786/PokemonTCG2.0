"""Deterministic surgical overlay for confirmed target routes.

Rules are gated by the frozen public detector route and controlled by the
PTCG_SURGICAL environment variable ("" = off; "dip_a,dip_b,..." = enabled).

Every rule only intercepts at OWN MAIN (or the immediate legal follow-up
selection it created) and never overrides protected base actions:
ATTACK, RETREAT, ABILITY (model/damage-solver outputs are authoritative).
"""

from __future__ import annotations

import os

from cg.api import AreaType, OptionType, SelectContext

SPIKEMUTH = 1219
BOSS = 1182
FESTIVAL_GROUNDS = 1245
THWACKEY = 90

# Late/mid low-value dev plays EXP-23 over-prefers vs Lucario where winning
# teachers attack instead (discovered on real Lucario win rows).
LUC_VETO_PLAYS = {1152, 1097, 860, 646}

PROTECTED_TYPES = {OptionType.ATTACK, OptionType.RETREAT, OptionType.ABILITY}


class SurgicalOverlay:
    def __init__(self) -> None:
        raw = os.environ.get("PTCG_SURGICAL", "")
        self.enabled = {piece.strip() for piece in raw.split(",") if piece.strip()}
        self.boss_thwackey_latch = False
        self.fires = []

    def reset(self) -> None:
        self.boss_thwackey_latch = False
        self.fires = []

    @staticmethod
    def _me(obs):
        current = obs.current
        players = current.players or []
        index = int(current.yourIndex)
        return players[index] if 0 <= index < len(players) else None

    @staticmethod
    def _opp(obs):
        current = obs.current
        players = current.players or []
        index = 1 - int(current.yourIndex)
        return players[index] if 0 <= index < len(players) else None

    def _play_card_map(self, obs):
        me = self._me(obs)
        hand = me.hand if me is not None else None
        result = {}
        if not hand:
            return result
        for index, option in enumerate(obs.select.option or []):
            if option.type == OptionType.PLAY and option.index is not None and 0 <= option.index < len(hand):
                card = hand[option.index]
                if card is not None:
                    result.setdefault(int(card.id), index)
        return result

    def _base_protected(self, obs, action):
        options = obs.select.option or []
        for index in action:
            if index < len(options) and options[index].type in PROTECTED_TYPES:
                return True
        return False

    def _dip_main(self, obs, action):
        if not (self.enabled & {"dip_a", "dip_b", "dip_ab"}):
            return action
        if self._base_protected(obs, action):
            return action
        current = obs.current
        play_map = self._play_card_map(obs)

        if self.enabled & {"dip_b", "dip_ab"}:
            opp = self._opp(obs)
            thwackey_stranded = False
            if opp is not None:
                for slot in opp.bench or []:
                    if slot is not None and int(slot.id) == THWACKEY and not (slot.energies or []):
                        thwackey_stranded = True
                        break
            if (
                thwackey_stranded
                and not current.supporterPlayed
                and BOSS in play_map
                and play_map[BOSS] not in action
            ):
                self.boss_thwackey_latch = True
                self.fires.append({"rule": "dip_b", "ctx": "main", "base_action": list(action)})
                return [play_map[BOSS]]

        if self.enabled & {"dip_a", "dip_ab"}:
            stadium_ids = {int(card.id) for card in current.stadium or [] if card is not None}
            if (
                FESTIVAL_GROUNDS in stadium_ids
                and not current.stadiumPlayed
                and SPIKEMUTH in play_map
                and play_map[SPIKEMUTH] not in action
            ):
                self.fires.append({"rule": "dip_a", "ctx": "main", "base_action": list(action)})
                return [play_map[SPIKEMUTH]]

        return action

    def _dip_boss_target(self, obs):
        opp = self._opp(obs)
        if opp is None:
            return None
        options = obs.select.option or []
        thwackey_indices = []
        for index, option in enumerate(options):
            if option.playerIndex is not None and option.playerIndex != int(obs.current.yourIndex):
                if option.area == AreaType.BENCH and option.index is not None:
                    bench = opp.bench or []
                    if option.index < len(bench):
                        slot = bench[option.index]
                        if slot is not None and int(slot.id) == THWACKEY and not (slot.energies or []):
                            thwackey_indices.append(index)
        if len(thwackey_indices) == 1:
            return [thwackey_indices[0]]
        return None

    def _luc_main(self, obs, action, ranked):
        if "luc_veto" not in self.enabled:
            return action
        if self._base_protected(obs, action):
            return action
        options = obs.select.option or []
        if len(action) != 1:
            return action
        index = action[0]
        if index >= len(options) or options[index].type != OptionType.PLAY:
            return action
        me = self._me(obs)
        hand = me.hand if me is not None else None
        if not hand or options[index].index is None or options[index].index >= len(hand):
            return action
        card = hand[options[index].index]
        if card is None or int(card.id) not in LUC_VETO_PLAYS:
            return action
        if not ranked:
            return action
        for candidate in ranked:
            if candidate < len(options) and options[candidate].type == OptionType.ATTACK:
                if candidate != index:
                    self.fires.append({
                        "rule": "luc_veto",
                        "ctx": "main",
                        "base_action": list(action),
                        "play_card": int(card.id),
                    })
                    return [candidate]
                break
        self.fires.append({
            "rule": "luc_veto_miss",
            "ctx": "main",
            "base_action": list(action),
            "play_card": int(card.id),
        })
        return action

    def intercept(self, obs, route, action, ranked=None):
        if route is None or not self.enabled:
            return action
        context = obs.select.context
        if route == "dipplin":
            if context == SelectContext.MAIN:
                return self._dip_main(obs, action)
            if context == SelectContext.EFFECT_TARGET and self.boss_thwackey_latch:
                self.boss_thwackey_latch = False
                replaced = self._dip_boss_target(obs)
                if replaced is not None:
                    return replaced
        elif route == "lucario":
            if context == SelectContext.MAIN:
                return self._luc_main(obs, action, ranked or [])
        return action
