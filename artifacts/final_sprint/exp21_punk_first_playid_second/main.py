"""punk rail on the FIRST arm, PLAY-identity binding on the SECOND arm.

Two independent mechanisms, each applied to the arm where its local evidence
was strongest. Exact A2+Damage V0 everywhere else.
"""

import os
os.environ['PTCG_GRIM_DAMAGE_SOLVER'] = 'v0'
os.environ['PTCG_WAVE1_RAIL'] = 'off'

from ptcg_ai.order_router import ActualOrderAgent
import ptcg_ai.features as _features

_AGENT = ActualOrderAgent()
_features.PLAY_IDENTITY_ENABLED = False


class _FirstRail:
    def __init__(self, agent):
        self._agent = agent

    def __call__(self, obs_dict):
        rail = getattr(self._agent.policy, 'wave1_rail', None)
        previous = rail.mode if rail is not None else None
        if rail is not None:
            rail.mode = 'punk_only'
        try:
            return self._agent(obs_dict)
        finally:
            if rail is not None:
                rail.mode = previous

    def __getattr__(self, name):
        return getattr(self._agent, name)


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


_AGENT.policy_first = _FirstRail(_AGENT.policy_first)
_AGENT.policy_second = _SecondIdentity(_AGENT.policy_second)

def agent(obs_dict: dict) -> list[int]:
    return _AGENT(obs_dict)
