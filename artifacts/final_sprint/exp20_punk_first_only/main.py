"""Full punk rail on the FIRST arm only, on exact A2+Damage V0."""

import os
os.environ['PTCG_GRIM_DAMAGE_SOLVER'] = 'v0'
os.environ['PTCG_WAVE1_RAIL'] = 'off'

from ptcg_ai.order_router import ActualOrderAgent

_AGENT = ActualOrderAgent()


class _FirstRailOnly:
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


_AGENT.policy_first = _FirstRailOnly(_AGENT.policy_first)

def agent(obs_dict: dict) -> list[int]:
    return _AGENT(obs_dict)
