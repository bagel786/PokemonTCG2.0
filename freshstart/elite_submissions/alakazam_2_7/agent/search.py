"""Phase-2 search: use the engine forward model (search_begin/step) to evaluate
candidate actions by simulating them, instead of trusting a static heuristic.

Imports cg.api, so it works only where a compatible engine library loads (the
competition runtime or the native local build). Callers must guard with ENABLED.
"""
from __future__ import annotations

import os
import random
import re
import time
from collections import Counter
from dataclasses import asdict

try:
    from cg.api import (search_begin, search_step, search_end, search_release,
                        to_observation_class)
    ENABLED = True
except Exception:  # noqa: BLE001 - no engine on this platform
    ENABLED = False

from . import card_db
from . import encode
from . import features
from . import opponent_policy
from . import playbook
from . import policy
from . import policy_v2
from . import policy_v3

# v3 is the same interface trained on correctly-aligned labels (heldout top1
# 59.8% vs v2's 26.5%); v2 stays as the fallback if the artifact is missing so a
# packaging slip degrades instead of crashing.
_prior = policy_v3 if policy_v3.available() else policy_v2

# DO NOT add a "race harder" / urgency multiplier on ko_term. ATTACKING ENDS THE TURN,
# and Powerful Hand deals 20x HAND SIZE, so a truncated turn is also a weaker attack --
# the lever is to develop first and attack last, not to make attacking look better. A
# tempo multiplier was built, measured to push attack-commit the wrong way, and deleted
# (2026-07-14). See CLAUDE.md "trigger-happy" + docs/claude-memory/.

# Search budget knobs (kept conservative; Kaggle runs natively so this is plenty).
PLY_CAP = 60           # max simulated plies per rollout (our turn + opp reply)
MAX_BRANCH = 8         # top-level options to evaluate per decision
# Search depth/budget (v15): 5 worlds / 6s validated offline -- dragapult_kiyotah
# 41/41% -> 66/75% across two independent n=12 runs, Lucario 47->58, nothing down.
# Timing: 16s/game solo offline; Kaggle worst-case ~2x the 150-200s v13 episodes,
# far under the 2000s runTimeout (a timeout is an auto-loss, hence the margin check).
# v24: raised 5det/6s -> 8det/10s. Measured real replays (logs/v20_1, 25 eps/50
# seat-games): 99.8% of MAIN decisions finish well under the old 6s cap (p50
# 0.12s, p99 4.1s) -- budget rarely binds, so determinizations (more worlds,
# variance reduction) is the lever that actually buys search strength. Worst
# observed per-game search time at 8det/10s = 187.8s -> 10.65x margin under the
# 2000s runTimeout. Env kill switch back to old defaults: DETERMINIZATIONS=5
# MOVE_BUDGET_S=6.0.
def _configured_rung() -> str:
    explicit = os.environ.get("V26_RUNG")
    if explicit:
        return explicit
    for path in (os.path.join(os.path.dirname(os.path.abspath(__file__)), "v26_rung.json"),
                 "/kaggle_simulations/agent/agent/v26_rung.json"):
        if os.path.exists(path):
            try:
                import json
                with open(path, encoding="utf-8") as stream:
                    return str(json.load(stream).get("rung", "rollout"))
            except Exception:
                break
    return "policy"


V26_RUNG = _configured_rung().lower().replace("v26-", "")
if V26_RUNG not in {"correctness", "action", "rollout", "opponent", "policy"}:
    V26_RUNG = "policy"
CORRECTED_ROLLOUT = V26_RUNG in {"rollout", "opponent"}
LEARNED_OPPONENT = V26_RUNG == "opponent"
DIRECT_POLICY = os.environ.get("DIRECT_POLICY", "0") != "0"

DETERMINIZATIONS = int(os.environ.get("DETERMINIZATIONS", "8"))
MOVE_BUDGET_S = float(os.environ.get("MOVE_BUDGET_S", "10.0"))
SIMULATION_CAP = int(os.environ.get("SIMULATION_CAP", "0"))
# Opponent replies simulated per rollout (depth). 1 = classic our-turn + reply.
# Breadth is exhausted (DET 7 < DET 5 at n=48). Depth was the untested general lever
# until 2026-07-14: bumped 1->2 after a crash gate (0 exceptions, n=26 elite episodes,
# 1036 real decisions, +27% wall time -- safe against the 2000s runTimeout) and a
# decision-diff check showing it reshapes a real share of in-turn choices (~25/86 in
# a traced mirror, ~6/98 in a traced Grimmsnarl game) without changing attack-commit
# frequency (45.7%->43.6% at matched n=26, not the racing fix, a different mechanism).
# Offline cannot say whether this is BETTER -- see docs/claude-memory/
# rollout-depth-2-investigation-2026-07-14.md. Judge on converged rating after shipping.
ROLLOUT_TURNS = int(os.environ.get("ROLLOUT_TURNS", "1"))
TURN_PLAN = os.environ.get("TURN_PLAN", "1" if CORRECTED_ROLLOUT else "0") != "0"
TURN_PLAN_BRANCH = int(os.environ.get("TURN_PLAN_BRANCH", "4"))
TURN_PLAN_NODES = int(os.environ.get("TURN_PLAN_NODES", "40"))
# If the wall-clock budget expires immediately after a non-terminal candidate
# action, do not score the candidate in an artificial pre-attack same-turn state.
# Spend at most this many deterministic policy steps to close our current turn.
DEADLINE_TURN_FINISH_CAP = 16

# Card ids for KO-readiness shaping (alakazam branch: the Abra line).
# Alakazam's Powerful Hand costs 1 {P} and hits 20x our hand; energy attached to
# Abra/Kadabra CARRIES THROUGH evolution, so arming any line stage is progress.
# Dudunsparce/Dunsparce are draw engines, not attackers (mined: 2/820 attacks).
_ATTACKERS = (743, 742, 741)   # Alakazam, Kadabra, Abra
# Payoff attacker the line builds toward (dev-evolve nudge target).
_HERO = 743
# DO NOT reward attacker HP fraction: Alakazam is 140hp and gets OHKO'd, so it pays the
# brain to hide the attacker instead of trading. Protective intent lives in
# policy._retreat_dominated (dodge only when the swap-in survives better).


_PSYCHIC = 5   # EnergyType.PSYCHIC -- Powerful Hand's cost (attack_db[1072].energies == [5])


def _armed(mon) -> bool:
    """A line attacker (Abra/Kadabra/Alakazam) carrying energy that can actually pay
    Powerful Hand -- i.e. PSYCHIC. Colorless-only energy (e.g. Enriching) reads as
    'has energy' but cannot attack, so it must not count as armed. The engine resolves
    special energies to their provided colors in `mon.energies`; if that field is
    absent we fall back to the raw count (never crash / never silently disable search)."""
    if not (mon and mon.id in _ATTACKERS and len(mon.energyCards) >= 1):
        return False
    energies = getattr(mon, "energies", None)
    if not energies:
        return True   # color not visible -> preserve old count-based behavior
    return _PSYCHIC in energies


def _prize_value(pid: int) -> int:
    """Prizes the opponent gives up when this Pokemon is KO'd: Mega ex=3, ex=2, else 1."""
    c = card_db.card(pid) or {}
    rule = (c.get("rule") or "").lower()
    if "ex" in rule:
        return 3 if "mega" in rule else 2
    return 1


_ACT_COSTS: dict[int, tuple[int, int]] = {}


def _act_costs(pid: int) -> tuple[int, int]:
    """(cheapest move's energy cost, retreat cost) from card_db, cached.
    Moves with cost None are abilities, not attacks -- excluded. Cost strings
    mix "●" glyphs and "{P}"-style symbols, one energy each ("●●"=2, "{P}"=1).
    Unknown card -> (99, 0): never counts as able to act, never as stuck."""
    if pid not in _ACT_COSTS:
        c = card_db.card(pid) or {}
        costs = [len(re.findall(r"●|\{[^}]*\}", m["cost"]))
                 for m in (c.get("moves") or []) if m.get("cost") is not None]
        _ACT_COSTS[pid] = (min(costs) if costs else 99, int(c.get("retreat") or 0))
    return _ACT_COSTS[pid]

# Diagnostics (inspected by scripts/diag_search.py).
STATS = {"calls": 0, "not_main": 0, "begin_none": 0, "begin_raise": 0,
         "root_action_raise": 0, "lethal_step_raise": 0,
         "release_raise": 0, "search_end_raise": 0,
         "finish_turn_raise": 0, "rollout_raise": 0,
         "searched": 0, "rollout_steps": 0, "step_raise": 0, "free_play": 0,
         "sparse_bail": 0, "candidate_options": 0, "candidate_members": 0,
         "simulations": 0, "decisions_below_two_sims": 0,
         "opponent_policy_calls": 0, "opponent_policy_fallbacks": 0,
         "direct_policy_calls": 0, "direct_policy_picks": 0,
         "direct_policy_load_failures": 0, "direct_policy_fallbacks": 0,
         "tactical_vetoes": 0, "lethal_overrides": 0,
         "search_s_total": 0.0, "search_s_max": 0.0,
         "last_err": ""}


def _record_error(kind: str, exc: Exception) -> None:
    """Record a recoverable search failure without sacrificing legal fallback."""
    STATS[kind] = STATS.get(kind, 0) + 1
    STATS["last_err"] = f"{kind} {type(exc).__name__}: {exc}"

# A generic legal filler for opponent hidden cards: a basic Pokémon + basic energy.
# (Card 3 = Basic Water Energy; we pick a cheap Basic Pokémon id for the "needs a
# basic" constraint.)  These only stand in for *unknown* cards.
_BASIC_ENERGY = 3
_FILLER_BASIC_POKEMON = 722  # Snover (a Basic Pokémon present in the pool)


def _basic_pokemon_ids(sample: int = 1) -> list[int]:
    out = []
    for cid, c in card_db.db().items():
        if c.get("stage_or_type") == "Basic Pokémon":
            out.append(cid)
            if len(out) >= sample:
                break
    return out or [_FILLER_BASIC_POKEMON]


def _known_my_cards(ps: dict) -> list[int]:
    """Card IDs we can see among our own non-deck, non-prize locations."""
    ids: list[int] = []
    for p in (ps.get("active") or []):
        if p:
            ids.append(p["id"])
            for e in p.get("energyCards", []):
                ids.append(e["id"])
            for t in p.get("tools", []):
                ids.append(t["id"])
            for pe in p.get("preEvolution", []):
                ids.append(pe["id"])
    for p in ps.get("bench", []):
        ids.append(p["id"])
        for e in p.get("energyCards", []):
            ids.append(e["id"])
        for t in p.get("tools", []):
            ids.append(t["id"])
        for pe in p.get("preEvolution", []):
            ids.append(pe["id"])
    for c in (ps.get("hand") or []):
        ids.append(c["id"])
    for c in ps.get("discard", []):
        ids.append(c["id"])
    return ids


# --- archetype posterior ---------------------------------------------------------
# Default ON for rules-correct hidden-world construction.  Weak evidence does not
# collapse to our own list: it deliberately abstains to an equal-weight broad meta
# mixture.  ARCH_PRIOR=0 is retained only as a controlled historical comparison.
_ARCH_PRIOR = os.environ.get("ARCH_PRIOR", "1" if CORRECTED_ROLLOUT else "0") != "0"
_META_DECKS = None
_ACTIVE_WORLD = {"archetype": "mixed", "behavior": [0.0] * 5}


def _meta_decks() -> dict:
    global _META_DECKS
    if _META_DECKS is None:
        here = os.path.dirname(os.path.abspath(__file__))
        _META_DECKS = {}
        for p in (os.path.join(here, "meta_decks.json"),
                  "/kaggle_simulations/agent/agent/meta_decks.json"):
            if os.path.exists(p):
                import json
                with open(p, "r", encoding="utf-8") as f:
                    _META_DECKS = json.load(f)
                break
    return _META_DECKS


def _is_pokemon(cid: int) -> bool:
    return bool((card_db.card(cid) or {}).get("hp"))


def _registered_meta_decks() -> dict:
    """Only archetypes with a complete registered 60-card list are samplable."""
    return {name: info for name, info in _meta_decks().items()
            if len(info.get("deck") or []) == 60}


_INFER_CACHE: dict[tuple, list[tuple[str, list[int], float]]] = {}


def _opp_posterior(visible_pokemon: tuple) -> list[tuple[str, list[int], float]]:
    """Posterior over registered archetypes from revealed Pokémon.

    With fewer than two distinct reveals, incompatible evidence, or no archetype
    above 65%, identification is considered weak and we abstain to the broad meta
    mixture.  This prevents an early generic support Pokémon from being treated as
    certain deck identity while also eliminating the old mirror-fill distortion.
    """
    key = tuple(sorted(visible_pokemon))
    if key in _INFER_CACHE:
        return _INFER_CACHE[key]
    decks = _registered_meta_decks()
    broad = [(name, list(info["deck"]), 1.0 / len(decks))
             for name, info in sorted(decks.items())] if decks else []
    if len(set(key)) < 2:
        _INFER_CACHE[key] = broad
        return broad
    need = Counter(key)
    scored = []
    for name, info in sorted(decks.items()):
        have = Counter(info["pokemon"])
        if need - have:
            continue
        # Product of revealed-card frequencies: a small, transparent likelihood
        # model that rewards archetypes where the observed line is central.
        total = max(len(info["pokemon"]), 1)
        likelihood = 1.0
        for cid, count in need.items():
            likelihood *= (have[cid] / total) ** count
        scored.append((name, list(info["deck"]), likelihood))
    norm = sum(item[2] for item in scored)
    posterior = [(name, deck, likelihood / norm) for name, deck, likelihood in scored] if norm else []
    if not posterior or max(item[2] for item in posterior) < 0.65:
        posterior = broad
    _INFER_CACHE[key] = posterior
    return posterior


def _behavior_properties(deck: list[int]) -> list[float]:
    pokemon = [card_db.card(cid) or {} for cid in deck if (card_db.card(cid) or {}).get("hp")]
    text = " ".join(str(card.get("effect") or "") + " "
                    + " ".join(str(move.get("effect") or "") for move in card.get("moves") or [])
                    for card in pokemon).lower()
    damages = []
    for card in pokemon:
        for move in card.get("moves") or []:
            match = re.search(r"\d+", str(move.get("damage") or ""))
            damages.append(float(match.group()) if match else 0.0)
    evolved = sum(card.get("stage_or_type") not in (None, "Basic Pokémon") for card in pokemon)
    return [min(max(damages or [0.0]) / 300.0, 1.0),
            min(sum(text.count(term) for term in ("prevent all", "less damage", "heal", "recover")) / 8.0, 1.0),
            min(sum(text.count(term) for term in ("your opponent can’t", "your opponent can't", "discard", "confused", "paralyzed", "can’t retreat")) / 12.0, 1.0),
            min(sum(text.count(term) for term in ("draw ", "search your deck", "from your deck")) / 10.0, 1.0),
            evolved / max(len(pokemon), 1)]


def _sample_opp_world(visible_pokemon: tuple, rng: random.Random) -> tuple[str, list[int], list[float]] | None:
    posterior = _opp_posterior(visible_pokemon)
    if not posterior:
        return None
    draw = rng.random()
    cumulative = 0.0
    for name, deck, probability in posterior:
        cumulative += probability
        if draw <= cumulative:
            return name, list(deck), _behavior_properties(deck)
    name, deck, _probability = posterior[-1]
    return name, list(deck), _behavior_properties(deck)


def _sample_opp_deck(visible_pokemon: tuple, rng: random.Random) -> list[int] | None:
    """Compatibility projection used by diagnostics and historical tests."""
    world = _sample_opp_world(visible_pokemon, rng)
    return world[1] if world else None


def _infer_opp_deck(visible_pokemon: tuple) -> list[int] | None:
    """Compatibility helper: return a deck only for a confident posterior."""
    posterior = _opp_posterior(visible_pokemon)
    if posterior and max(item[2] for item in posterior) >= 0.65:
        return list(max(posterior, key=lambda item: item[2])[1])
    return None


def determinize(obs: dict, full_deck: list[int], rng: random.Random):
    """Build the hidden-info arguments for search_begin from a real obs.

    Returns kwargs dict for search_begin, or None if we cannot (e.g. deck phase).
    """
    state = obs.get("current")
    if state is None:
        return None
    me = state["yourIndex"]
    my = state["players"][me]
    opp = state["players"][1 - me]

    # --- our deck + prize split: full deck minus everything we can see ---
    known = _known_my_cards(my)
    pool = list(full_deck)
    for cid in known:
        if cid in pool:
            pool.remove(cid)
    rng.shuffle(pool)
    deck_n = my["deckCount"]
    prize_n = len(my["prize"])
    # If counts don't line up (effects, special energies), pad/truncate with energy.
    while len(pool) < deck_n + prize_n:
        pool.append(_BASIC_ENERGY)

    # Prize-aware split (the 1250-Starmie lesson). A search card (Petrel / Pokegear /
    # Hop's Bag) can reveal our WHOLE deck; when it does we know the deck exactly, so
    # everything else in `pool` is prized -> pin it OUT of your_deck. Otherwise the
    # engine's forward search can assemble a "lethal" on a card that's actually under
    # a prize and then fizzle in the real game (a NOMATCH). Random split only when we
    # genuinely can't tell.
    sel = obs.get("select") or {}
    revealed = sel.get("deck")
    if revealed is not None and len(revealed) == deck_n:
        your_deck = [c["id"] for c in revealed if c]
        rng.shuffle(your_deck)                       # order re-randomizes after a search
        rem = Counter(pool); rem.subtract(Counter(your_deck))
        your_prize = list(Counter({k: v for k, v in rem.items() if v > 0}).elements())
        while len(your_prize) < prize_n:             # visible-zone accounting drift
            your_prize.append(_BASIC_ENERGY)
        your_prize = your_prize[:prize_n]
    else:
        your_deck = pool[:deck_n]
        your_prize = pool[deck_n:deck_n + prize_n]

    # --- opponent: contents unknown. Sample the archetype posterior; on weak
    # evidence it is the broad registered-meta mixture, never our own deck. ---
    opp_deck_n = opp["deckCount"]
    opp_prize_n = len(opp["prize"])
    opp_hand_n = opp["handCount"]
    opp_visible = _known_my_cards(opp)  # their face-up cards (in play / discard)
    global _ACTIVE_WORLD
    opp_pool = None
    _ACTIVE_WORLD = {"archetype": "mixed", "behavior": [0.0] * 5}
    if _ARCH_PRIOR:
        inferred = _sample_opp_world(
            tuple(sorted(c for c in opp_visible if _is_pokemon(c))), rng)
        if inferred:
            name, deck, behavior = inferred
            opp_pool = list(deck)
            _ACTIVE_WORLD = {"archetype": name, "behavior": behavior}
    if opp_pool is None:
        if CORRECTED_ROLLOUT:
            meta = list(_registered_meta_decks().items())
            if meta:
                name, info = rng.choice(meta)
                opp_pool = list(info["deck"])
                _ACTIVE_WORLD = {"archetype": name,
                                 "behavior": _behavior_properties(opp_pool)}
        if opp_pool is None:
            opp_pool = list(full_deck)
    for cid in opp_visible:
        if cid in opp_pool:
            opp_pool.remove(cid)
    rng.shuffle(opp_pool)
    need = opp_deck_n + opp_prize_n + opp_hand_n
    basics = _basic_pokemon_ids(3)
    # Ensure at least one Basic Pokémon among the opponent's hidden cards (setup rule).
    if opp_pool and not any(card_db.card(c) and
                            card_db.card(c).get("stage_or_type") == "Basic Pokémon"
                            for c in opp_pool[:need]):
        opp_pool.insert(0, basics[0])
    while len(opp_pool) < need:
        opp_pool.append(_BASIC_ENERGY)
    opponent_deck = opp_pool[:opp_deck_n]
    opponent_prize = opp_pool[opp_deck_n:opp_deck_n + opp_prize_n]
    opponent_hand = opp_pool[opp_deck_n + opp_prize_n:need]

    # opponent active only needed when it is face-down (unknown) to us
    opp_active = opp.get("active") or []
    opponent_active = [basics[0]] if (len(opp_active) > 0 and opp_active[0] is None) else []

    return dict(
        your_deck=your_deck,
        your_prize=your_prize,
        opponent_deck=opponent_deck,
        opponent_prize=opponent_prize,
        opponent_hand=opponent_hand,
        opponent_active=opponent_active,
    )


def begin(obs: dict, full_deck: list[int], rng: random.Random):
    """search_begin with a determinization. Returns root SearchState or None."""
    if not ENABLED:
        return None
    kw = determinize(obs, full_deck, rng)
    if kw is None:
        return None
    obs_cls = to_observation_class(obs)
    return search_begin(obs_cls, **kw)


def _dmg_frac(p) -> float:
    """Prize-weighted damage already on a mon: (missing hp fraction) * its prize value."""
    return ((p.maxHp - p.hp) / p.maxHp) * _prize_value(p.id)


# Learned value: state -> win prob (submission/agent/value_net.npz, trained by
# scripts/train_value.py on outcome-labeled top-agent replays). Replaces the
# hand-tuned heuristic middle of value(); terminal short-circuits and the
# deck-out rules-fact stay. VALUE_NET=0 restores the full heuristic.
# v18 readout: the outcome-labeled net regressed (confound: prices digs negative).
# Default OFF -> v17 heuristic; VALUE_NET=1 re-enables for experiments.
VALUE_NET = os.environ.get("VALUE_NET", "0") != "0"
# Policy-first integration ladder (v20/v21). POLICY_ORDER: order search candidates
# by the pooled elite clone's score before the MAX_BRANCH cut (replaces
# first-8-by-index truncation). POLICY_MAIN: the clone DECIDES the MAIN action over
# the veto-filtered survivors -- no rollouts, no value(); search keeps only the
# verified-lethal override. Each has an env kill switch to the previous rung.
POLICY_ORDER = os.environ.get("POLICY_ORDER", "1") != "0"
POLICY_MAIN = os.environ.get("POLICY_MAIN", "0") != "0"
# v20.3: force-append Dudunsparce evolves to the candidate set. Measured on our
# v20.1 replays: the Dudunsparce evolve was legal at 12.8% of MAIN decisions and
# EXCLUDED from candidates entirely at 34.3% of those (index >= MAX_BRANCH, not a
# decisive type) -- search can't pick what it never evaluates, and Dudunsparce IS
# the draw engine on a 20x-hand deck. Membership change (the v20-regression
# class), so it ships alone with this kill switch back to v20.1 membership.
# Default OFF 2026-07-19: v20.3 (54822923) converged 710.7 vs its concurrent
# identical-base control v20.1r (54822248) at 782.5 -- the append is regressive
# (membership-widening class). See docs/claude-memory/v20-3-verdict-*.md.
DUDUN_EVOLVE = os.environ.get("DUDUN_EVOLVE", "0") != "0"
VNET_CALLS = 0  # mechanism-check counter: proves the net path actually runs
_VNET_W = None


def _vnet():
    global _VNET_W
    if _VNET_W is None:
        import numpy as np
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "value_net.npz")
        d = np.load(path)
        _VNET_W = (d["W1"], d["b1"], d["W2"], d["b2"])
    return _VNET_W


def _net_value(state, me: int) -> float:
    """Win prob from the net, mapped to a score. Terminals (+-1e6) still dominate."""
    import numpy as np
    W1, b1, W2, b2 = _vnet()
    x = np.asarray(encode.encode(state, me), dtype=np.float64)
    h = np.maximum(x @ W1 + b1, 0.0)
    z = min(max(float((h @ W2 + b2)[0]), -30.0), 30.0)
    p = 1.0 / (1.0 + 2.718281828459045 ** -z)
    return (2.0 * p - 1.0) * 10000.0


def value(state_obs, me: int) -> float:
    """State score from player `me`'s perspective. VALUE_NET=1 (default): learned
    win-prob net. VALUE_NET=0: the Alakazam-tuned heuristic (prizes dominate;
    KO-progress, KO-readiness, deck-out clock, attrition)."""
    global VALUE_NET, VNET_CALLS
    state = state_obs.current
    if state is None:
        return 0.0
    STATS["leaf_evaluations"] = STATS.get("leaf_evaluations", 0) + 1
    if state.result == me:
        STATS["leaf_terminal_win"] = STATS.get("leaf_terminal_win", 0) + 1
        return 1e6
    if state.result == (1 - me):
        STATS["leaf_terminal_loss"] = STATS.get("leaf_terminal_loss", 0) + 1
        return -1e6
    if state.result == 2:
        return 0.0
    my = state.players[me]
    opp = state.players[1 - me]
    if my.deckCount <= 8:
        STATS["leaf_low_deck"] = STATS.get("leaf_low_deck", 0) + 1
    if any(p and p.id in {345, 414, 533} for p in list(opp.active or []) + list(opp.bench or [])):
        STATS["leaf_wall_visible"] = STATS.get("leaf_wall_visible", 0) + 1

    if VALUE_NET:
        try:
            v = _net_value(state, me)
            # rules fact, not a heuristic: starting a turn with 0 deck is a loss
            if my.deckCount <= 0 and opp.deckCount > 0:
                v -= 30000.0
            VNET_CALLS += 1
            return v
        except Exception:
            VALUE_NET = False  # missing/corrupt model file: heuristic fallback

    prize_term = len(opp.prize) - len(my.prize)

    ko_term = sum(_dmg_frac(p) for p in (opp.active or []) if p and p.maxHp > 0)

    # Survival: empty bench = one KO from losing. Bench reward CAPPED AT 3, not 5 --
    # cap 5 was v11 and cost 75 rating points (benching spends from HAND, and Powerful
    # Hand = 20x hand size). Do not raise without a measured bench-width deficit vs elite.
    has_active = len([p for p in (my.active or []) if p]) > 0
    my_bench = len(my.bench)
    survival = -400.0 if (has_active and my_bench == 0) else 0.0
    survival += 40.0 * min(my_bench, 3)

    # Deck-out clock: deck 0 (opp not also at 0) is a forced loss -> terminal-scale.
    # Otherwise a linear cost inside the draw "runway" plus a quadratic that bites by
    # deck 1-2, scaled up to 3x as the prize race stalls (grind) so deck-burning lines
    # lose to any prize progress. grind: 1.0 when nobody's scoring, 0 by 6 prizes taken.
    prizes_off = (6 - len(my.prize)) + (6 - len(opp.prize))
    grind = max(0.0, 1.0 - prizes_off / 6.0)
    if my.deckCount <= 0 and opp.deckCount > 0:
        deckout = -30000.0
    else:
        deckout = 0.0
        runway = min(4 * len(my.prize) + 4, 20)
        if my.deckCount <= runway:
            deckout -= 10.0 * (runway + 1 - my.deckCount)
        if my.deckCount <= 8:
            deckout -= 15.0 * (9 - my.deckCount) ** 2
        deckout *= 1.0 + 2.0 * grind
    opp_deckout = 6.0 * max(0, 9 - opp.deckCount) if opp.deckCount <= 8 else 0.0

    # KO-readiness: energy on the Alakazam line (it carries through evolution, every
    # attack costs 1). +50 per armed line mon anywhere; +120 more when the ARMED
    # attacker is ACTIVE (only the active can attack -- without this, search left the
    # active at 0 energy for whole games). Small vs prize/KO: only breaks ties to setup.
    in_play = [p for p in (my.active or []) if p] + list(my.bench)
    ready = sum(50.0 for p in in_play if _armed(p))
    ready += sum(120.0 for p in (my.active or []) if _armed(p))
    # Non-line active mobility: +45 if it can use some move (below the line's +50 so
    # arming the line still wins ties); -100 if it can neither act NOR retreat while an
    # armed hero waits benched (a stuck wall in the active spot blocking our attacker).
    for p in (my.active or []):
        if not p or p.id in _ATTACKERS:
            continue
        act_cost, ret_cost = _act_costs(p.id)
        e = len(p.energyCards)
        if e >= act_cost:
            ready += 45.0
        elif e < ret_cost and any(
                b and b.id == _HERO and _armed(b)
                for b in my.bench):
            ready -= 100.0
    # Spread payoff: prize-weighted damage banked on the opp BENCH (ko_term is active-only).
    opp_bench_dmg = sum(_dmg_frac(p) for p in opp.bench if p and p.maxHp > 0)
    ready += 30.0 * min(opp_bench_dmg, 2.0)

    # When BEHIND on prizes, up-weight KO-progress to gamble for the catch-up KO.
    behind = max(0, len(my.prize) - len(opp.prize))
    desperation = 1.0 + 0.4 * behind

    # Attrition: a general 2nd win condition -- when the prize race stalls, reward our
    # deck-count edge (who decks out last). The abstract answer to heal-walls, off during
    # an active prize race.
    attrition = 5.0 * grind * (my.deckCount - opp.deckCount)

    return (1000.0 * prize_term
            + 200.0 * ko_term * desperation
            + ready
            + survival
            + deckout
            + opp_deckout
            + attrition)


def _finish_current_turn_for_value(state, me: int):
    """Best-effort bounded close of our current turn before heuristic scoring.

    Search evaluates candidates by applying the candidate action first and then
    rolling forward. If the wall-clock deadline is hit right after that first
    action, a development move (attach/evolve/play) can otherwise be valued
    before the already-encoded policy gets to take its normal attack/end-turn
    step, while an immediate ATTACK candidate has banked its KO/prize result.
    To avoid that systematic bias, allow only deterministic current-turn policy
    steps until ATTACK/END or turn transition, capped tightly.
    """
    for _ in range(DEADLINE_TURN_FINISH_CAP):
        cur = state.observation.current
        if cur is None or cur.result >= 0 or cur.yourIndex != me:
            break
        obs_d = asdict(state.observation)
        select = obs_d.get("select")
        if select is None:
            break
        try:
            choice = policy.choose(obs_d)
            terminal_main = False
            if (select.get("type") == policy.SelectType.MAIN
                    and choice and len(choice) == 1):
                opts = select.get("option") or []
                idx = choice[0]
                if 0 <= idx < len(opts):
                    terminal_main = opts[idx].get("type") in (
                        policy.OptionType.ATTACK, policy.OptionType.END)
            state = search_step(state.searchId, choice)
            STATS["rollout_steps"] += 1
            if terminal_main:
                break
        except Exception as e:  # noqa: BLE001 - score last stable state
            STATS["step_raise"] += 1
            _record_error("finish_turn_raise", e)
            break
    return state


def _rollout(state, me: int, deadline: float) -> float:
    """Finish OUR turn, then play out ROLLOUT_TURNS opponent replies (both sides
    via heuristic; our intermediate turns too when >1), and score the board once
    control returns to us. Including their counter-punch is what lets search
    prefer moves that don't expose us to a return-KO -- the thing a greedy 'max
    damage now' heuristic can't see. Depth >1 makes multi-turn RACES visible
    (a 440hp Cape'd Mega 2-shotting our actives is invisible at horizon 1) at the
    cost of throughput; default 1 until a >=2-sigma n=48 gate says otherwise."""
    steps = 0
    opp_turns = 0
    in_opp = False
    while steps < PLY_CAP * ROLLOUT_TURNS:
        cur = state.observation.current
        if cur is None or cur.result >= 0:
            break
        if cur.yourIndex != me:
            in_opp = True
        elif in_opp:                   # back to our turn -> opponent has replied
            in_opp = False
            opp_turns += 1
            if opp_turns >= ROLLOUT_TURNS:
                break
        obs_d = asdict(state.observation)
        if obs_d.get("select") is None:
            break
        try:
            choice = None
            if cur.yourIndex != me and LEARNED_OPPONENT:
                try:
                    choice = opponent_policy.choose(
                        obs_d["current"], obs_d["select"],
                        _ACTIVE_WORLD["archetype"], _ACTIVE_WORLD["behavior"])
                    STATS["opponent_policy_calls"] += 1
                except Exception as exc:  # model failure must remain legal and visible
                    STATS["opponent_policy_fallbacks"] += 1
                    _record_error("opponent_policy_raise", exc)
            if choice is None:
                choice = policy.choose(obs_d)
            # The correctness rung retains v25's attack-first opponent.  The
            # rollout/opponent rungs allow full development before attack/end.
            if (not CORRECTED_ROLLOUT and cur.yourIndex != me
                    and obs_d.get("select", {}).get("type") == policy.SelectType.MAIN):
                select_options = obs_d["select"]["option"]
                attacks = [(policy._attack_damage(option, obs_d["current"]), index)
                           for index, option in enumerate(select_options)
                           if option.get("type") == policy.OptionType.ATTACK]
                if attacks:
                    damage, index = max(attacks)
                    if damage > 0:
                        choice = [index]
            state = search_step(state.searchId, choice)
        except Exception as e:  # noqa: BLE001 - bail out, score what we have
            STATS["step_raise"] += 1
            _record_error("rollout_raise", e)
            break
        steps += 1
        STATS["rollout_steps"] += 1
        if time.monotonic() > deadline:
            state = _finish_current_turn_for_value(state, me)
            break
    return value(state.observation, me)


def _mon_signature(mon: dict | None):
    if not mon:
        return None
    return (mon.get("id"), mon.get("serial"), mon.get("hp"),
            tuple((c.get("id"), c.get("serial")) for c in mon.get("energyCards", [])),
            tuple((c.get("id"), c.get("serial")) for c in mon.get("tools", [])))


def _visible_signature(obs: dict) -> tuple:
    """Visible-state fingerprint used to invalidate cached turn plans."""
    state = obs.get("current") or {}
    players = state.get("players") or []
    player_sigs = []
    for ps in players:
        player_sigs.append((
            tuple((c.get("id"), c.get("serial")) for c in (ps.get("hand") or [])),
            tuple(_mon_signature(p) for p in (ps.get("active") or [])),
            tuple(_mon_signature(p) for p in (ps.get("bench") or [])),
            ps.get("deckCount"), len(ps.get("prize") or []),
            tuple((c.get("id"), c.get("serial")) for c in (ps.get("discard") or [])),
        ))
    stadium = state.get("stadium") or []
    return (state.get("turn"), state.get("yourIndex"), tuple(player_sigs),
            tuple(_mon_signature(card) for card in stadium))


def _option_fingerprint(option: dict, state: dict) -> tuple:
    """Action identity independent of engine option ordering."""
    me = state.get("yourIndex", 0)
    players = state.get("players") or []
    hand = players[me].get("hand", []) if me < len(players) else []
    index = option.get("index")
    source = hand[index].get("id") if isinstance(index, int) and index < len(hand) else option.get("cardId")
    return (option.get("type"), source, option.get("attackId"), option.get("area"),
            option.get("inPlayArea"), option.get("inPlayIndex"),
            option.get("playerIndex"), option.get("serial"))


_PLAN_CACHE: dict | None = None


def _cached_turn_pick(obs: dict, options: list[dict]) -> int | None:
    global _PLAN_CACHE
    if not _PLAN_CACHE:
        return None
    if not _PLAN_CACHE["steps"] or _PLAN_CACHE["steps"][0][0] != _visible_signature(obs):
        STATS["plan_invalidated"] = STATS.get("plan_invalidated", 0) + 1
        _PLAN_CACHE = None
        return None
    _signature, wanted = _PLAN_CACHE["steps"].pop(0)
    state = obs["current"]
    for index, option in enumerate(options):
        if _option_fingerprint(option, state) == wanted:
            STATS["plan_cache_hit"] = STATS.get("plan_cache_hit", 0) + 1
            if not _PLAN_CACHE["steps"]:
                _PLAN_CACHE = None
            return index
    STATS["plan_invalidated"] = STATS.get("plan_invalidated", 0) + 1
    _PLAN_CACHE = None
    return None


def _turn_plan_value(state, me: int, deadline: float, budget: list[int]) -> tuple[float, list]:
    """Search a complete current-turn action sequence, then evaluate the reply.

    MAIN prompts branch under the structured policy prior; forced sub-selections
    follow the legal policy.  The returned path contains visible-state guards so a
    cached continuation is reused only when no stochastic/reveal change occurred.
    """
    cur = state.observation.current
    if (not TURN_PLAN or cur is None or cur.result >= 0 or cur.yourIndex != me
            or budget[0] <= 0 or time.monotonic() > deadline):
        return _rollout(state, me, deadline), []
    obs_d = asdict(state.observation)
    select = obs_d.get("select")
    if select is None:
        return value(state.observation, me), []
    if select.get("type") != policy.SelectType.MAIN:
        choices = [policy.choose(obs_d)]
    else:
        state_d = obs_d.get("current") or {}
        yi = state_d.get("yourIndex", 0)
        hand = (state_d.get("players") or [{}])[yi].get("hand") or []
        choices = [[i] for i in _filter_cands(select.get("option") or [], state_d, hand)
                   [:TURN_PLAN_BRANCH]]
    best_value = float("-inf")
    best_path: list = []
    for choice in choices:
        if budget[0] <= 0 or time.monotonic() > deadline:
            break
        budget[0] -= 1
        try:
            child = search_step(state.searchId, choice)
            child_value, child_path = _turn_plan_value(child, me, deadline, budget)
            if child_value > best_value:
                best_value = child_value
                if select.get("type") == policy.SelectType.MAIN:
                    option = select["option"][choice[0]]
                    best_path = [(_visible_signature(obs_d),
                                  _option_fingerprint(option, obs_d["current"]))] + child_path
                else:
                    best_path = child_path
        except Exception as exc:  # noqa: BLE001
            _record_error("turn_plan_raise", exc)
        finally:
            if "child" in locals():
                try:
                    search_release(child.searchId)
                except Exception as exc:  # noqa: BLE001
                    _record_error("release_raise", exc)
                del child
    if best_value == float("-inf"):
        return _rollout(state, me, deadline), []
    return best_value, best_path


LETHAL_BRANCH = 6      # options explored per node in the lethal DFS
LETHAL_NODES = 160     # node budget per lethal probe (bounds worst-case cost)


def _find_lethal(state, me: int, deadline: float, budget: list) -> bool:
    """True if a sequence of OUR moves from `state` wins THIS turn (reaches
    result==me before the turn passes). A focused DFS that BRANCHES over our MAIN
    options (vs _rollout's single heuristic line) so it actually finds the
    attach/evolve/Boss + attack kill the averaged rollout can dilute or miss.
    Opponent-free by construction: a real this-turn lethal completes before they
    move. Called per determinization; choose_action only trusts a lethal that
    holds in ALL of them (a hand+board kill, not a phantom needing a prized card)."""
    cur = state.observation.current
    if cur is None:
        return False
    if cur.result == me:
        return True
    if cur.result >= 0 or cur.yourIndex != me:   # terminal-not-win, or turn passed
        return False
    if budget[0] <= 0 or time.monotonic() > deadline:
        return False
    obs_d = asdict(state.observation)
    select = obs_d.get("select")
    if select is None:
        return False
    # Branch over MAIN options; for forced sub-selects take the heuristic's one line.
    # Use the SAME candidate filter as the root (not the first LETHAL_BRANCH by
    # index): the engine lists the finishing ATTACK last, so a raw index cap hid
    # every 2-step lethal (attach/Boss/evolve -> attack) at interior nodes on this
    # deck's wide (hand 10-20) menus.
    if select.get("type") == policy.SelectType.MAIN:
        state_d = obs_d.get("current") or {}
        players = state_d.get("players") or []
        yi = state_d.get("yourIndex", 0)
        hand = (players[yi].get("hand") or []) if yi < len(players) else []
        choices = [[i] for i in _filter_cands(select["option"], state_d, hand)]
    else:
        choices = [policy.choose(obs_d)]
    for ch in choices:
        budget[0] -= 1
        if budget[0] < 0:
            return False
        try:
            child = search_step(state.searchId, ch)
        except Exception as e:  # noqa: BLE001
            _record_error("lethal_step_raise", e)
            continue
        try:
            if _find_lethal(child, me, deadline, budget):
                return True
        finally:
            try:
                search_release(child.searchId)
            except Exception as e:  # noqa: BLE001
                _record_error("release_raise", e)
    return False


def _is_dev_evolve(o: dict, hand: list) -> bool:
    """True if this EVOLVE option turns a basic in play into one of our Mega ex
    attackers (1031/861). Developing the attacker is near-always correct, but the
    averaged rollout ranks it equal to a draw card (both lines evolve during the
    rollout, so the leaves tie) -> index order then keeps the draw card and we durdle
    a 70hp basic into a 440hp Mega Lucario ex. Traced as the #1 real-ladder loss."""
    if o.get("type") != policy.OptionType.EVOLVE:
        return False
    idx = o.get("index")
    if idx is None or idx >= len(hand):
        return False
    h = hand[idx]
    return (h.get("id") if isinstance(h, dict) else h) in _ATTACKERS


_DUDUNSPARCE = 66


def _is_dudun_evolve(o: dict, hand: list) -> bool:
    """True if this EVOLVE option evolves into Dudunsparce (66) — the Run Away
    Draw engine. Membership-only companion to _is_dev_evolve: appended to the
    candidate set (behind DUDUN_EVOLVE) but given NO _nudge bonus, so ordering
    is untouched — the clone already ranks it near the front when present
    (measured mean rank 0.52)."""
    if o.get("type") != policy.OptionType.EVOLVE:
        return False
    idx = o.get("index")
    if idx is None or idx >= len(hand):
        return False
    h = hand[idx]
    return (h.get("id") if isinstance(h, dict) else h) == _DUDUNSPARCE


def _nudge(o: dict, hand: list, state: dict | None = None) -> float:
    """Tie-break bonus (< real value gaps, so only flips genuine ties/noise) toward
    making progress: ATTACK starts trading, evolving into our Mega ex develops the
    attacker. Evolve edges out attack so within a turn we evolve (free) before
    attacking (ends the turn). A lethal-enabling attach (attaching the energy that
    unlocks a KO on the opp active) outranks dev-evolve: the averaged rollout can tie
    'evolve a bench mon' with 'attach + KO' and index-order then durdles instead of
    securing the prize (traced: e0 Mega Froslass + Water in hand vs a 20hp Alakazam)."""
    if state is not None and policy._attach_enables_ko(o, state):
        return 6.0
    if o.get("type") == policy.OptionType.ATTACK:
        return 3.0
    if state is not None and policy._good_attach(o, state):
        # Arming an unarmed line mon edges out durdling (drawing/benching)
        # when the rollout ties them -- same physics as dev-evolve below,
        # just for the attach that feeds it.
        return 1.0
    if _is_dev_evolve(o, hand):
        # Completing the hero (Alakazam) edges out earlier line stages when
        # the rollouts tie.
        idx = o.get("index")
        hid = (hand[idx].get("id") if idx is not None and idx < len(hand)
               and isinstance(hand[idx], dict) else None)
        if hid == _HERO:
            return 4.5
        return 4.0
    return 0.0


def _candidates(options: list, hand: list, state: dict | None = None) -> list:
    """Policy-prior candidate coverage plus forced tactically decisive actions.

    Engine index is no longer a membership feature.  The structured v2 policy is
    used when trained; until then a deterministic semantic priority supplies
    coverage. The legacy model may order these candidates but cannot widen them.
    Hard tactical guards still force attacker evolution, attacks, and retreats.
    """
    scores = None
    if state is not None:
        try:
            if _prior.available():
                scores = _prior.scores(state, options)
                STATS["policy_v2_order"] = STATS.get("policy_v2_order", 0) + 1
        except Exception:  # noqa: BLE001 - prior failure cannot disable search
            scores = None
    if scores is not None:
        cand = sorted(range(len(options)), key=lambda i: -scores[i])[:MAX_BRANCH]
    else:
        # No model artifact: deterministic semantic priority, not engine index.
        priority = {policy.OptionType.ATTACK: 6, policy.OptionType.EVOLVE: 5,
                    policy.OptionType.ATTACH: 4, policy.OptionType.ABILITY: 3,
                    policy.OptionType.PLAY: 2, policy.OptionType.RETREAT: 1,
                    policy.OptionType.END: 0}
        cand = sorted(range(len(options)),
                      key=lambda i: (-priority.get(options[i].get("type"), 0),
                                     repr(sorted(options[i].items()))))[:MAX_BRANCH]
    for i, o in enumerate(options):
        if i not in cand and (_is_dev_evolve(o, hand)
                              or (DUDUN_EVOLVE and _is_dudun_evolve(o, hand))
                              or o.get("type") in (
                policy.OptionType.ATTACK, policy.OptionType.RETREAT)):
            cand.append(i)
    order_scores = scores
    if order_scores is None and state is not None and features.has_model("main"):
        try:
            order_scores = features.scores("main", state, options, None)
        except Exception:  # noqa: BLE001
            order_scores = None
    if POLICY_ORDER and order_scores is not None:
        try:
            cand.sort(key=lambda i: -order_scores[i])
            STATS["policy_order"] = STATS.get("policy_order", 0) + 1
        except Exception:  # noqa: BLE001 - clone must never cost us the search
            pass
    return cand


def _main_clone_top(options: list, state: dict, k: int = 2) -> list[int]:
    """Top structured-policy actions allowed to widen candidate membership.

    The legacy clone is deliberately excluded here: its top-k membership rung
    regressed on ladder. It remains an order/tie-break prior only.
    """
    if not _prior.available():
        return []
    try:
        sc = _prior.scores(state, options)
    except Exception:  # noqa: BLE001
        return []
    return sorted(range(len(options)), key=lambda i: -sc[i])[:k]


def _filter_cands(options: list, state: dict, hand: list) -> list:
    """Candidate indices for a MAIN select: _candidates plus forced good attaches
    and the clone's top picks, minus provably-wasteful moves. Single source shared
    by choose_action's root and every TURN_PLAN beam node, so the planner prunes
    exactly like the root. Wrapped defensively: a raising predicate must never
    crash the caller -- on any error keep the unfiltered set."""
    cand = _candidates(options, hand, state)
    for i in _main_clone_top(options, state):
        if i not in cand:
            cand.append(i)
    for i, option in enumerate(options):
        if i not in cand and (policy._good_attach(option, state)
                              or policy._attach_enables_ko(option, state)
                              or policy._attach_feeds_land_crush(option, state)):
            cand.append(i)
    return _apply_tactical_vetoes(cand, options, state)


def _apply_tactical_vetoes(cand: list[int], options: list, state: dict) -> list[int]:
    """Apply the existing proven tactical guards to an explicit candidate set.

    Direct v26 passes every legal engine option here, while legacy rollout search
    passes its bounded candidate set.  If soft guards eliminate everything, only
    the three hard safety vetoes remain in force.
    """
    original = list(cand)
    try:
        attack_on_menu = any(o.get("type") == policy.OptionType.ATTACK
                             or "attackId" in o for o in options)
        lethal_attack_on_menu = (attack_on_menu
                                 and any(o.get("type") == policy.OptionType.RETREAT
                                         for o in options)
                                 and policy._can_ko_opp_active(state))

        def retreat_forfeits_ko(i: int) -> bool:
            return (lethal_attack_on_menu
                    and options[i].get("type") == policy.OptionType.RETREAT)

        filtered = [i for i in cand
                    if not policy._play_suppressed(options[i], state, options)
                    # Root-only; off by default. See policy._setup_supporter_displaced.
                    and not policy._setup_supporter_displaced(options[i], state, options)
                    and not policy._suicide_ability(options[i], state)
                    and not policy._bad_attach(options[i], state, options)
                    and not policy._evolve_dominated(options[i], state, options)
                    and not policy._end_dominated(options[i], state, options)
                    and not policy._draw_dominated(options[i], state)
                    and not policy._attack_dominated(options[i], state)
                    and not policy._attack_ends_turn_early(options[i], state, options)
                    # _choose_main already forbids cashing a guaranteed KO into
                    # a retreat. Search used only _retreat_dominated, which
                    # deliberately preserves a swap that survives better; in
                    # real replays that let it retreat an armed, lethal
                    # Alakazam and then END (7 turns across v27_399/417).
                    and not retreat_forfeits_ko(i)
                    and not policy._retreat_dominated(options[i], state, options)]
        if filtered:
            cand = filtered
        else:
            # Every option got vetoed at once (real state: ep 86189547 step 112,
            # PLAY/ATTACK/END all suppressed). Falling back to the raw set here
            # resurrected the proven-immune ATTACK -- and rollouts can't model
            # learned immunity, so Powerful Hand priced a phantom 20x-hand OHKO
            # and we swung into the wall every turn. Keep the soft-suppressed
            # options but never the hard vetoes: attacks proven to do zero,
            # suicide abilities, and wasteful card burns (_play_suppressed) --
            # resurrecting those replayed Xerosic into opp-hand-4 (ep 86334998
            # step 76: all 8 options vetoed, END only by _end_dominated against
            # plays that were themselves vetoed, and search picked Xerosic).
            hard_ok = [i for i in cand
                       if not policy._attack_dominated(options[i], state)
                       and not policy._suicide_ability(options[i], state)
                       and not policy._play_suppressed(options[i], state, options)
                       # _draw_dominated is hard here too: resurrecting a draw
                       # while _draw_suppressed donates the deck-out race (ep
                       # 87498522: led the race 24-20 at T10, decked out T34
                       # picking suppressed Hilda/Poke Pad/abilities).
                       and not policy._draw_dominated(options[i], state)
                       and not retreat_forfeits_ko(i)]
            if hard_ok:
                cand = hard_ok
    except Exception:  # noqa: BLE001 - keep the unfiltered candidates
        cand = original
    STATS["tactical_vetoes"] += max(0, len(original) - len(cand))
    return cand


def _safe_main_candidates(options: list, state: dict) -> list[int]:
    """All engine-legal MAIN options after tactical safety filtering."""
    return _apply_tactical_vetoes(list(range(len(options))), options, state)


def _verified_lethal_pick(obs: dict, options: list, cand: list[int], me: int,
                          full_deck: list[int], rng: random.Random) -> list[int] | None:
    """Return a root action whose same-turn win is robust across sampled worlds."""
    deadline = time.monotonic() + MOVE_BUDGET_S
    hits = [0] * len(options)
    tries = [0] * len(options)
    for _d in range(DETERMINIZATIONS):
        if time.monotonic() > deadline:
            break
        try:
            root = begin(obs, full_deck, rng)
        except Exception as exc:  # noqa: BLE001
            _record_error("begin_raise", exc)
            continue
        if root is None:
            STATS["begin_none"] += 1
            break
        for i in cand:
            try:
                child = search_step(root.searchId, [i])
                tries[i] += 1
                if _find_lethal(child, me, deadline, [LETHAL_NODES]):
                    hits[i] += 1
                search_release(child.searchId)
            except Exception as exc:  # noqa: BLE001
                _record_error("root_action_raise", exc)
            if time.monotonic() > deadline:
                break
        try:
            search_end()
        except Exception as exc:  # noqa: BLE001
            _record_error("search_end_raise", exc)
    for i in cand:
        if tries[i] >= 2 and hits[i] == tries[i]:
            STATS["lethal"] = STATS.get("lethal", 0) + 1
            STATS["lethal_overrides"] += 1
            return [i]
    return None


def _direct_policy_pick(obs: dict, options: list, cand: list[int], me: int,
                        full_deck: list[int], rng: random.Random,
                        try_lethal: bool) -> list[int] | None:
    """v26: model argmax is the MAIN controller, after tactical vetoes."""
    STATS["direct_policy_calls"] += 1
    if try_lethal:
        lethal = _verified_lethal_pick(obs, options, cand, me, full_deck, rng)
        if lethal is not None:
            return lethal
    try:
        if not _prior.available():
            STATS["direct_policy_load_failures"] += 1
            return None
        scores = _prior.scores(obs["current"], options)
        if len(scores) != len(options) or not cand:
            STATS["direct_policy_fallbacks"] += 1
            return None
        pick = max(cand, key=lambda i: scores[i])
    except Exception as exc:  # noqa: BLE001
        STATS["direct_policy_fallbacks"] += 1
        _record_error("direct_policy_raise", exc)
        return None
    STATS["direct_policy_picks"] += 1
    return [pick]


def _policy_main_pick(obs: dict, options: list, cand: list, me: int,
                      full_deck: list[int], rng: random.Random,
                      try_lethal: bool) -> list[int] | None:
    """v21 (POLICY_MAIN): the pooled elite clone decides the MAIN action --
    argmax clone score over the veto-filtered survivors, no rollouts, no value().
    Search keeps ONE job: the finish-mode verified-lethal override (a lethal
    robust across every determinization that evaluated it). Returns None when
    the clone can't score, so the caller falls back to full search (v20)."""
    state = obs["current"]
    try:
        sc = features.scores("main", state, options, None)
    except Exception:  # noqa: BLE001
        return None
    if try_lethal:
        deadline = time.monotonic() + MOVE_BUDGET_S
        hits = [0] * len(options)
        tries = [0] * len(options)
        for _d in range(DETERMINIZATIONS):
            if time.monotonic() > deadline:
                break
            try:
                root = begin(obs, full_deck, rng)
            except Exception:  # noqa: BLE001
                continue
            if root is None:
                break
            for i in cand:
                try:
                    child = search_step(root.searchId, [i])
                    tries[i] += 1
                    if _find_lethal(child, me, deadline, [LETHAL_NODES]):
                        hits[i] += 1
                    search_release(child.searchId)
                except Exception as e:  # noqa: BLE001
                    _record_error("root_action_raise", e)
                    continue
                if time.monotonic() > deadline:
                    break
            try:
                search_end()
            except Exception as e:  # noqa: BLE001
                _record_error("search_end_raise", e)
        for i in cand:
            if tries[i] >= 2 and hits[i] == tries[i]:
                STATS["lethal"] = STATS.get("lethal", 0) + 1
                return [i]
    STATS["policy_main"] = STATS.get("policy_main", 0) + 1
    return [max(cand, key=lambda i: sc[i])]


def _should_try_lethal(obs: dict, me: int) -> bool:
    """Whether to spend budget probing for a this-turn lethal. A lethal takes OUR
    last prizes, so it's only plausible when we are near winning (a single 3-prize
    KO on a Mega ex wins from my.prize <= 3). Pure (no engine) so it is testable."""
    if os.environ.get("NO_LETHAL"):
        return False
    return len(obs["current"]["players"][me]["prize"]) <= 3


def choose_action(obs: dict, full_deck: list[int], rng: random.Random) -> list[int] | None:
    """Search-based choice for a branching MAIN decision. Returns a 1-element
    index list, or None to signal 'use the heuristic instead'."""
    if not ENABLED:
        return None
    STATS["calls"] += 1
    select = obs.get("select")
    if select is None or select.get("type") != policy.SelectType.MAIN:
        STATS["not_main"] += 1
        return None
    options = select["option"]
    if len(options) < 2:
        STATS["not_main"] += 1
        return None
    cached = _cached_turn_pick(obs, options)
    if cached is not None:
        return [cached]

    me = obs["current"]["yourIndex"]
    hand = obs["current"]["players"][me].get("hand") or []
    state = obs["current"]
    cand = (_safe_main_candidates(options, state) if DIRECT_POLICY
            else _filter_cands(options, state, hand))
    STATS["candidate_options"] += len(options)
    STATS["candidate_members"] += len(cand)
    deadline = time.monotonic() + MOVE_BUDGET_S
    totals = [0.0] * len(options)
    counts = [0] * len(options)
    plan_samples: list[list[list]] = [[] for _ in options]
    did_search = False
    decision_sims = 0

    # Finish mode gate: a "win THIS turn" takes OUR last prizes, so a lethal is
    # only plausible when WE are near winning -- gate on our own prize count, not
    # the opponent's (the old `opp.prize <= 3` fired only when the OPPONENT was
    # near winning and never when we were ahead and one KO from closing).
    try_lethal = _should_try_lethal(obs, me)

    if DIRECT_POLICY:
        # A missing/bad model returns None directly to main.py, which invokes the
        # deterministic heuristic.  It must never resurrect v25's normal rollout.
        return _direct_policy_pick(obs, options, cand, me, full_deck, rng, try_lethal)

    if POLICY_MAIN and features.has_model("main"):
        pick = _policy_main_pick(obs, options, cand, me, full_deck, rng, try_lethal)
        if pick is not None:
            return pick

    lethal_hits = [0] * len(options)
    lethal_tries = [0] * len(options)

    for _d in range(DETERMINIZATIONS):
        if time.monotonic() > deadline or (SIMULATION_CAP and decision_sims >= SIMULATION_CAP):
            break
        try:
            root = begin(obs, full_deck, rng)   # a fresh imagined opponent
        except Exception as e:  # noqa: BLE001
            _record_error("begin_raise", e)
            continue
        if root is None:
            STATS["begin_none"] += 1
            break
        did_search = True
        # Rotate evaluation order on every shared determinization.  Every candidate
        # receives one fair simulation before deadline-based truncation can expand
        # favored branches.
        offset = _d % len(cand)
        ordered_cand = cand[offset:] + cand[:offset]
        for i in ordered_cand:
            if SIMULATION_CAP and decision_sims >= SIMULATION_CAP:
                break
            try:
                child = search_step(root.searchId, [i])
                lethal_tries[i] += 1
                if try_lethal and _find_lethal(child, me, deadline, [LETHAL_NODES]):
                    lethal_hits[i] += 1
                v, plan = _turn_plan_value(child, me, deadline, [TURN_PLAN_NODES])
                search_release(child.searchId)
            except Exception as e:  # noqa: BLE001
                _record_error("root_action_raise", e)
                continue
            totals[i] += v
            counts[i] += 1
            STATS["simulations"] += 1
            decision_sims += 1
            plan_samples[i].append(plan)
            if time.monotonic() > deadline and all(counts[j] >= 1 for j in cand):
                break
        try:
            search_end()
        except Exception as e:  # noqa: BLE001
            _record_error("search_end_raise", e)

    if not did_search:
        return None
    STATS["searched"] += 1
    spent = time.monotonic() - (deadline - MOVE_BUDGET_S)
    STATS["search_s_total"] += spent
    STATS["search_s_max"] = max(STATS["search_s_max"], spent)

    # Finish mode: commit to a move that wins THIS turn in EVERY determinization that
    # evaluated it (>=2). Robust across imagined worlds => a hand+board kill, not a
    # phantom needing a card that's really prized. Overrides the heuristic: the
    # averaged rollout can rank a "safe" setup over a real lethal (a win in 1 of 3
    # determinizations gets averaged down). "Normal turns by rules, winning turns
    # verified by search." -- the 1250 author's Finish mode.
    for i in cand:
        if lethal_tries[i] >= 2 and lethal_hits[i] == lethal_tries[i]:
            STATS["lethal"] = STATS.get("lethal", 0) + 1
            return [i]

    # Live-safety: if any candidate never got a single evaluation (engine
    # mismatch throwing in rollouts, or deadline cut mid-list on slow hardware),
    # ranking the survivors is ranking garbage -- let the policy decide.
    # A verified finish-mode lethal above still fires; this only guards the avg.
    # (2026-07-10: stale bundled engine made live search do exactly this.)
    if any(counts[i] < 2 for i in cand):
        STATS["decisions_below_two_sims"] += 1
    if any(counts[i] == 0 for i in cand):
        STATS["sparse_bail"] = STATS.get("sparse_bail", 0) + 1
        return None

    # Average value per option; options never evaluated are skipped.
    # Tie-break toward ATTACK: when developing another bench mon and attacking
    # score ~equally (the short horizon can't see the chip payoff, so the leaf
    # values saturate), index order otherwise picks develop -> we durdle, build a
    # full bench, take 0 prizes and get out-paced (the #1 real-ladder loss). A tiny
    # nudge below any real value gap breaks those ties toward making progress
    # (attacking starts trading, which ALSO arms the Trevenant Revenge combo).
    # ponytail: epsilon < real value gaps (hundreds); only flips genuine ties/noise.
    # Clone tie-break (2026-07-10): among near-ties, prefer the option yushin's
    # main-phase clone ranks highest. Scale ±30: ~5% of the learned value term's
    # median successive-state delta (~600 at W=20000, measured on value_states),
    # so it flips close calls but never a clear value gap. (First cut used ±0.2,
    # tuned to v1's tie behavior -- measured inert: <2% of deltas that small.)
    clone_bonus = [0.0] * len(options)
    if features.has_model("main"):
        try:
            sc = features.scores("main", state, options, None)
            lo, hi = min(sc), max(sc)
            span = hi - lo
            if span > 1e-9:
                clone_bonus = [60.0 * (s - lo) / span - 30.0 for s in sc]
        except Exception:  # noqa: BLE001
            pass
    best_i, best_v = None, float("-inf")
    for i in cand:
        if counts[i] == 0:
            continue
        avg = totals[i] / counts[i] + _nudge(options[i], hand, state) + clone_bonus[i]
        if avg > best_v:
            best_v, best_i = avg, i
    if os.environ.get("SEARCH_DEBUG"):
        scored = [(options[i].get("type"), round(totals[i] / counts[i], 1))
                  for i in cand if counts[i]]
        with open("/app/search_debug.log", "a") as f:
            f.write(f"pick idx{best_i} type{options[best_i].get('type')} | {scored}\n")
    if best_i is not None:
        global _PLAN_CACHE
        samples = plan_samples[best_i]
        if len(samples) >= 2 and samples[0] and all(path == samples[0] for path in samples[1:]):
            _PLAN_CACHE = {"steps": list(samples[0])}
            STATS["plan_cached"] = STATS.get("plan_cached", 0) + 1
        else:
            _PLAN_CACHE = None
    return [best_i] if best_i is not None else None
