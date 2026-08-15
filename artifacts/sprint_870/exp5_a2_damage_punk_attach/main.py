"""Controlled dual-actual-order A2 plus exact damage conversion V0."""

import os
os.environ['PTCG_GRIM_DAMAGE_SOLVER'] = 'v0'
os.environ['PTCG_WAVE1_RAIL'] = 'punk_attach'

from ptcg_ai.order_router import ActualOrderAgent

_AGENT = ActualOrderAgent()

def agent(obs_dict: dict) -> list[int]:
    return _AGENT(obs_dict)
