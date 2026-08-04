"""Matchup playbook for the Alakazam/Dudunsparce brain (alakazam branch).

Opponent-archetype inference (deck-containment vs meta_decks.json, pinned once
per real decision) is carried over from the Starmie brain -- it encodes
OPPONENT facts and was validated on 177 episodes. Entries were re-derived for
the elite meta the pivot targets (mined 2026-07-07 from logs/top_episodes, 295
elite games): Alakazam mirror 31%, Grimmsnarl 22%, Archaludon 14%, Garchomp
7%, Dragapult 7%, Kangaskhan wall 6%, Lucario 5%.

Consumers: policy._pick_opp_bench (kill_bonus), policy._choose_main
(bench_cap). No imports from policy/search (no cycles) -- card_db only.
"""
from __future__ import annotations

import json
import os
from collections import Counter

from . import card_db

_META = None
_INFER_CACHE: dict[tuple, str | None] = {}


def _meta() -> dict:
    global _META
    if _META is None:
        here = os.path.dirname(os.path.abspath(__file__))
        _META = {}
        for p in (os.path.join(here, "meta_decks.json"),
                  "/kaggle_simulations/agent/agent/meta_decks.json"):
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    _META = json.load(f)
                break
    return _META


# meta_decks key fragment -> playbook tag (first match wins).
_TAGS = [("lucario", "lucario"), ("archaludon", "archaludon"),
         ("alakazam", "mirror"), ("fezandipiti", "mirror"),
         ("dudunsparce", "mirror"), ("grimmsnarl", "grimmsnarl"),
         ("garchomp", "garchomp"), ("kangaskhan", "wall"), ("crustle", "wall"),
         ("starmie", "starmie"), ("dragapult", "dragapult")]


def _tag_for(deck_name: str) -> str | None:
    for frag, tag in _TAGS:
        if frag in deck_name:
            return tag
    return None


def infer_tag(state: dict) -> str | None:
    """Archetype tag from the opponent's visible Pokemon (containment +
    confidence: all matching meta decks must agree on the tag)."""
    my_idx = (state or {}).get("yourIndex", 0)
    players = (state or {}).get("players") or []
    if len(players) < 2:
        return None
    opp = players[1 - my_idx]
    vis = tuple(sorted(m["id"] for m in (opp.get("active") or []) + (opp.get("bench") or [])
                       if m and (card_db.card(m.get("id")) or {}).get("hp")))
    if not vis:
        return None
    if vis in _INFER_CACHE:
        return _INFER_CACHE[vis]
    need = Counter(vis)
    cands = [(len(set(v["pokemon"]) - set(vis)), nm)
             for nm, v in sorted(_meta().items())
             if not (need - Counter(v["pokemon"]))]
    tag = None
    if cands:
        unrevealed, nm = min(cands)
        tags = {_tag_for(n) for _, n in cands}
        if len(tags) == 1:
            if len(cands) == 1 or unrevealed == 0 or len(set(vis)) >= 3:
                tag = tags.pop()
    _INFER_CACHE[vis] = tag
    return tag


# --- the playbook -----------------------------------------------------------------
# kill_bonus: opponent card NAME -> bonus (engine mons to Boss-drag first).
# bench_cap:  override policy._BENCH_TARGET.
# All entries encode OPPONENT reads mined from elite replays; our own response
# (Powerful Hand race, wide bench, line development) is the default plan.

PLAYBOOK: dict[str, dict] = {
    # 31% of the elite meta -- the mirror. Both sides race Powerful Hand; the
    # line pieces (Abra 50hp / Kadabra 80hp) die to any attack, and elite Boss
    # drags in the corpus target exactly those (Abra was the #2 drag overall).
    # #1-player drag order (elite-yushin ctx3): Kadabra over Abra (denies the
    # Alakazam next turn, 80hp still dies to anything) and the 2-prize
    # Fezandipiti ex when fielded.
    "mirror": {"kill_bonus": {"Kadabra": 3, "Fezandipiti ex": 3, "Abra": 2,
                              "Dudunsparce": 1}},
    # 22% of elite meta. Munkidori's ability shuffles damage counters; the
    # Impidimp line becomes 280hp Grimmsnarl ex. Drag-and-kill the support
    # engine before it stabilizes (elite drags: Munkidori top-3).
    "grimmsnarl": {"kill_bonus": {"Munkidori": 3, "Marnie's Impidimp": 2,
                                  "Marnie's Morgrem": 1}},
    # 14%. Assemble Alloy accel on 300hp bodies + Relicanth (Memory Dive).
    # Kill 130hp Duraludons BEFORE they wall up. Our race math vs them is new:
    # they 2-shot 140hp Alakazam but each KO feeds us only 1 prize; Powerful
    # Hand at hand>=15 one-shots a 300hp Archaludon.
    "archaludon": {"kill_bonus": {"Duraludon": 2, "Relicanth": 3}},
    # 7%. Cynthia's Garchomp ex ramps via Roselia/Roserade; Gible/Gabite are
    # 70/100hp windows. (#3 on the board flies this.)
    "garchomp": {"kill_bonus": {"Cynthia's Roselia": 2, "Cynthia's Gible": 2,
                                "Cynthia's Gabite": 2}},
    # 7%. Phantom Dive 200 + 60 spread: benched 50hp Abras are free spread
    # kills, so bench one fewer body into this matchup.
    "dragapult": {"kill_bonus": {"Dreepy": 2, "Drakloak": 2}, "bench_cap": 3},
    # 5%. Lunatone/Solrock accel engine, Hariyama drags our bench. Their Megas
    # give up 3 prizes to a single Powerful Hand -- pure race, kill the engine.
    "lucario": {"kill_bonus": {"Lunatone": 3, "Solrock": 2, "Hariyama": 2}},
    # 2% but DANGEROUS: Mega Froslass' Resentful Refrain = 50x OUR hand, and
    # this deck lives at hand 10-20 (= 500-1000 damage). Kill the Snorunt line
    # on sight; the rollout damage model (policy._MULT_DMG 1240) makes search
    # see the threat, this makes Boss act on it.
    "starmie": {"kill_bonus": {"Snorunt": 3, "Mega Froslass ex": 3, "Staryu": 1}},
    # Walls (Kangaskhan/Crustle, 7% combined): their reflect/Jumbo Ice Cream
    # tech punishes ex attackers -- every mon we field is 1-prize non-ex, so
    # the wall plan largely whiffs into us. No special read yet; entry reserved
    # for inference-coverage visibility in scans.
    "wall": {},
}


# The tag is PINNED once per real decision (main.decide -> set_context) so that
# search rollouts -- whose opponent boards contain determinizer filler mons --
# never re-infer from an imagined roster.
_CUR_TAG: str | None = None


def set_context(state: dict) -> None:
    """Call with the REAL obs once per decision. Never raises."""
    global _CUR_TAG
    try:
        _CUR_TAG = infer_tag(state)
    except Exception:  # noqa: BLE001
        _CUR_TAG = None


def current_tag() -> str | None:
    return _CUR_TAG


def _entry() -> dict:
    return PLAYBOOK.get(_CUR_TAG, {}) if _CUR_TAG else {}


def kill_bonus(mon_id: int) -> int:
    """Boss/snipe targeting bonus for this opponent mon (0 = no opinion)."""
    kb = _entry().get("kill_bonus")
    if not kb:
        return 0
    return kb.get((card_db.card(mon_id) or {}).get("name", ""), 0)


def bench_cap(default: int) -> int:
    return _entry().get("bench_cap", default)
