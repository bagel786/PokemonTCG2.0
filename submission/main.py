"""Kaggle submission entry point."""

import os

# v2.2 safety lock: force greedy inference.
# The temperature-sampling "variance twin" (PTCG_TEMP>0) occasionally samples a
# turn-ending pass (OptionType.END), which forfeits the whole turn and loses games
# (root cause of the 55303334 Elo bleed). Greedy is strictly safer on the ladder,
# so we pin it here where no submission-time environment can override it.
os.environ["PTCG_TEMP"] = "0"

from ptcg_ai import CompetitionAgent

_AGENT = CompetitionAgent()


def agent(obs_dict: dict) -> list[int]:
    return _AGENT(obs_dict)

