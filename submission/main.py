"""Kaggle submission entry point."""

from ptcg_ai import CompetitionAgent

_AGENT = CompetitionAgent()


def agent(obs_dict: dict) -> list[int]:
    return _AGENT(obs_dict)

