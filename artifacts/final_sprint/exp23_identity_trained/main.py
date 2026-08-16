"""Identity-fixed A2 heads refresh on exact A2+Damage V0 runtime."""

import os
os.environ['PTCG_GRIM_DAMAGE_SOLVER'] = 'v0'

from ptcg_ai.order_router import ActualOrderAgent
import ptcg_ai.features as _features
_features.PLAY_IDENTITY_ENABLED = True

_AGENT = ActualOrderAgent()

def agent(obs_dict: dict) -> list[int]:
    return _AGENT(obs_dict)
