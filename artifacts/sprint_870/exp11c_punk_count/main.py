"""punk-variant probe on exact A2+Damage V0."""

import os
os.environ['PTCG_GRIM_DAMAGE_SOLVER'] = 'v0'
os.environ['PTCG_WAVE1_RAIL'] = 'punk_count'

from ptcg_ai.order_router import ActualOrderAgent

_AGENT = ActualOrderAgent()

def agent(obs_dict: dict) -> list[int]:
    return _AGENT(obs_dict)
