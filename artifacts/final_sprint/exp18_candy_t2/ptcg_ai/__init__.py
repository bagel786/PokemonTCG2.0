"""Clean-room Pokémon TCG competition agent."""

__all__ = ["CompetitionAgent"]


def __getattr__(name):
    # Keep utility modules importable in development environments where the official cg
    # package has not been placed on PYTHONPATH yet.
    if name == "CompetitionAgent":
        from .agent import CompetitionAgent

        return CompetitionAgent
    raise AttributeError(name)
