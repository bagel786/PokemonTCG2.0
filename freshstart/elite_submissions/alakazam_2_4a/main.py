"""Submission entry point for the PTCG AI Battle Challenge.

Contract (from cg/api.py / cabt.py):
  agent(obs_dict) -> list[int]
    - If obs_dict["select"] is None -> return the 60-card deck (list of card IDs).
    - Else return option indices, len in [minCount, maxCount], no duplicates,
      each in [0, len(option)).

Must never crash and must respond well within the time budget, or it loses.
We deliberately work on the raw dict (no cg.api import) so the decision logic
is import-safe on any platform; the engine itself is provided by the runtime.
"""
import os
import random

# Alakazam 2.4a CONTROL. Deliberately sets nothing here: search.py's own defaults
# are v30's (ATTRITION_V2=0, ATTRITION_W=5.0), so this artifact is v30 plus ONLY the
# Powerful-Hand weakness fix in policy.py.  Its paired experiment 2.4b sets those two
# knobs to 1 and 60 at this point in the file and is otherwise byte-identical.
#
# Do NOT write the opt-in calls here even inside a comment: build_artifact.py's
# config_defaults() regexes main.py for setdefault calls without stripping comments,
# so a quoted example silently reports the CONTROL as carrying the experiment's
# config -- which is exactly the audit this pair depends on.

from agent import playbook
from agent import policy
from agent import search

_DECK_CACHE: list[int] | None = None
_RNG = random.Random(12345)
RUNTIME_STATS = {
    "search_exception": 0, "search_invalid": 0,
    "policy_exception": 0, "policy_invalid": 0,
    "legal_fallback": 0, "last_error": "",
}
_SEARCH_ENABLED = search.ENABLED and os.environ.get("NO_SEARCH", "0") != "1"


# NOTE: Kaggle loads this file via exec() WITHOUT defining __file__, so guard it.
try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _HERE = "/kaggle_simulations/agent"


def _deck_path() -> str:
    for p in (
        "deck.csv",
        os.path.join(_HERE, "deck.csv"),
        "/kaggle_simulations/agent/deck.csv",
    ):
        if os.path.exists(p):
            return p
    return "deck.csv"


def read_deck_csv() -> list[int]:
    global _DECK_CACHE
    if _DECK_CACHE is not None:
        return _DECK_CACHE
    with open(_deck_path(), "r") as f:
        rows = [r.strip() for r in f.read().splitlines() if r.strip() != ""]
    deck = [int(rows[i]) for i in range(60)]
    _DECK_CACHE = deck
    return deck


def _legal_fallback(select: dict) -> list[int]:
    """Guaranteed-legal selection if everything else fails."""
    n = len(select.get("option", []))
    mn = max(select.get("minCount", 1), 0)
    k = min(max(mn, 1), n) if n else 0
    return list(range(k))


def decide(obs_dict: dict, deck: list[int]) -> list[int]:
    """Core decision for a given deck. (Deck is a parameter so we can A/B test
    different decks with the same brain in local self-play.)"""
    select = obs_dict.get("select")
    if select is None:
        return deck

    # Pin the matchup playbook to the REAL board once per decision -- rollout
    # states contain determinizer filler mons and must never re-infer from them.
    playbook.set_context(obs_dict.get("current") or {})
    # Learn from the engine's own damage logs which opp mons our counter-placing
    # attacks do nothing to (Repelling Veil, Battle Cage) -- REAL obs only.
    try:
        policy.note_attack_result(obs_dict)
    except Exception:
        pass

    def _valid(choice) -> bool:
        n = len(select["option"])
        mn, mx = select.get("minCount", 1), select.get("maxCount", 1)
        return (
            isinstance(choice, list)
            and all(isinstance(i, int) and 0 <= i < n for i in choice)
            and len(set(choice)) == len(choice)
            and mn <= len(choice) <= mx
        )

    # Prefer search on branching MAIN decisions; heuristic for the rest. CRUCIAL:
    # search and the heuristic get SEPARATE guards. If search raises (an engine-side
    # exception, not a timeout), we must still fall through to the heuristic -- NOT skip
    # straight to _legal_fallback, which blindly returns option 0 (often a wrong-energy
    # attach). A shared try/except here cost real ladder games: search threw, and the
    # agent attached Mist instead of Water and lost. The heuristic is a smart fallback;
    # _legal_fallback is the dumb last resort only.
    if _SEARCH_ENABLED:
        try:
            choice = search.choose_action(obs_dict, deck, _RNG)
            if choice is not None and _valid(choice):
                return choice
        except Exception as exc:
            RUNTIME_STATS["search_exception"] += 1
            RUNTIME_STATS["last_error"] = f"search {type(exc).__name__}: {exc}"
        else:
            if choice is not None:
                RUNTIME_STATS["search_invalid"] += 1
    try:
        choice = policy.choose(obs_dict)
        if _valid(choice):
            return choice
    except Exception as exc:
        RUNTIME_STATS["policy_exception"] += 1
        RUNTIME_STATS["last_error"] = f"policy {type(exc).__name__}: {exc}"
    else:
        RUNTIME_STATS["policy_invalid"] += 1
    RUNTIME_STATS["legal_fallback"] += 1
    return _legal_fallback(select)


def agent(obs_dict: dict) -> list[int]:
    return decide(obs_dict, read_deck_csv())
