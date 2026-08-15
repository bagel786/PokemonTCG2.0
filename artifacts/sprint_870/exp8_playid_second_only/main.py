"""Controlled dual-actual-order A2 plus exact damage conversion V0."""

import os
os.environ['PTCG_GRIM_DAMAGE_SOLVER'] = 'v0'
os.environ['PTCG_WAVE1_RAIL'] = 'punk_only'

from ptcg_ai.order_router import ActualOrderAgent

_AGENT = ActualOrderAgent()

def agent(obs_dict: dict) -> list[int]:
    return _AGENT(obs_dict)

import ptcg_ai.features as _features
_features.PLAY_IDENTITY_ENABLED = False


class _SecondIdentity:
    def __init__(self, agent):
        self._agent = agent

    def __call__(self, obs_dict):
        _features.PLAY_IDENTITY_ENABLED = True
        try:
            return self._agent(obs_dict)
        finally:
            _features.PLAY_IDENTITY_ENABLED = False

    def __getattr__(self, name):
        return getattr(self._agent, name)


_AGENT.policy_second = _SecondIdentity(_AGENT.policy_second)
