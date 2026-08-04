"""Fresh policy for the Alakazam/Dudunsparce deck (alakazam branch).

Operates on the raw obs dict (no engine import) so it is unit-testable on
macOS. The Starmie brain lives on the v4-pressure branch; this file was
rebuilt from the elite-replay mining report (scripts/mine_elite.py over 183
elite Alakazam games, logs/top_episodes/):

  - Alakazam's Powerful Hand (attackId 1072) = 20x OUR OWN hand size; elites
    attack with hand ~14 (280 dmg). The hand is the weapon; the deck's
    abilities (Psychic Draw, Run Away Draw) refill it every turn.
  - Alakazam throws 85% of all attacks. Dudunsparce is a DRAW ENGINE, not an
    attacker (2/820 attacks). All our mons are 1-prize: the opponent needs
    6 KOs while we win prize trades against ex/Mega decks.
  - Rare Candy turn 2 (43% of uses), target Abra 99%.
  - Poffin: take BOTH slots (64%), Abra 58% > Dunsparce 41%.
  - Deck fetches (Dawn/Poke Pad/Hilda): complete the line in play first.
  - Discard recovery (Night Stretcher/Lana's Aid): Abra > Alakazam > Kadabra
    > energy.  Sacred Ash: line mons back to deck, take max.
  - Go FIRST (92% of elite choices): evolutions come online a turn sooner.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

from . import card_db
from . import features
from . import playbook

# --- our deck's card ids ---------------------------------------------------------
ABRA, KADABRA, ALAKAZAM = 741, 742, 743
DUNSPARCE, DUDUNSPARCE = 305, 66
_LINE_NEXT = {ABRA: KADABRA, KADABRA: ALAKAZAM, DUNSPARCE: DUDUNSPARCE}
_OUR_MONS = (ALAKAZAM, KADABRA, ABRA, DUDUNSPARCE, DUNSPARCE)
_BOSS = 1182          # Boss's Orders
_RARE_CANDY = 1079
POWERFUL_HAND = 1072  # Alakazam attackId
_DAWN, _HILDA, _POKE_PAD = 1231, 1225, 1152
_DRAW_CARDS = (_DAWN, _HILDA, _POKE_PAD)
_ENRICHING = 13   # Enriching Energy (ACE SPEC): draws on attach = free EV
# END-vs-attach guard extension (2026-07-12, traced from sub 54597486
# ep85539881: search chose END over attaching a 2nd energy -- including
# Enriching Energy, a free draw -- to our LONE active; bench-out loss).
# Default ON since 2026-07-12 A/B: mirror 88.3 vs base 87.5 (n=240),
# romanrozen 66.0 vs 63.9 (n=144) -- no regression, bug-fix class.
_END_ATTACH_EXT = int(os.environ.get("END_ATTACH_EXT", "1"))
# yushin-list additions (mechanics: docs/claude-memory/yushin-deck-cards.md)
_XEROSIC = 1197        # Supporter: opponent discards to 3 (kills Powerful Hand)
_NIGHTTIME_MINE = 1266  # Stadium: Tera attacks cost +1 {C} (we run no Tera)
_FEZ, _SHAYMIN = 140, 343
# Every .tera() pokemon in the engine (CardImpl.h) -- Nighttime Mine targets.
# Meta hits: Dragapult ex 121, Cinderace ex 153.
_TERA_IDS = frozenset({30, 40, 52, 83, 96, 99, 108, 117, 121, 130, 153, 154,
                       161, 176, 189, 193, 210, 223, 229, 231, 236, 239, 241,
                       243, 244, 246, 248, 249, 316, 320, 957, 979})

# Card-select decisions (fetch/keep/bench/promote/boss/...) are ranked by the
# yushin clone: per-family linear models over abstract state x option features,
# trained on the #1 player's 604 replays (features.py + yushin_model.json;
# held-out agreement per family in the model's meta). The count taken stays
# code (_pick_count); the clone only orders the options.


@lru_cache(maxsize=1)
def _attack_db() -> dict[int, int]:
    """attackId -> attack value (max of engine static damage and CSV-parsed
    base, so effect/multiplier attacks aren't valued at 0)."""
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, "attack_db.json"),
              "/kaggle_simulations/agent/agent/attack_db.json"):
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return {int(k): int(v.get("value", v.get("damage", 0)))
                    for k, v in raw.items()}
    return {}


@lru_cache(maxsize=1)
def _attack_cost_db() -> dict[int, int]:
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, "attack_db.json"),
              "/kaggle_simulations/agent/agent/attack_db.json"):
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return {int(k): len(v.get("energies") or []) for k, v in raw.items()}
    return {}


def _attack_cost(opt: dict) -> int:
    aid = opt.get("attackId")
    if aid is not None:
        c = _attack_cost_db().get(int(aid))
        if c is not None:
            return c
    return len(opt.get("cost") or "")


def _prize_value(mid: int) -> int:
    """Prizes the opp gives up when this mon is KO'd: Mega ex=3, ex=2, else 1."""
    rule = ((card_db.card(mid) or {}).get("rule") or "").lower()
    if "ex" in rule:
        return 3 if "mega" in rule else 2
    return 1


# --- mirrored from cg/api.py (kept in sync manually) ------------------------------

class SelectType:
    MAIN = 0
    CARD = 1
    ATTACHED_CARD = 2
    CARD_OR_ATTACHED_CARD = 3
    ENERGY = 4
    SKILL = 5
    ATTACK = 6
    EVOLVE = 7
    COUNT = 8
    YES_NO = 9
    SPECIAL_CONDITION = 10


class OptionType:
    NUMBER = 0
    YES = 1
    NO = 2
    CARD = 3
    TOOL_CARD = 4
    ENERGY_CARD = 5
    ENERGY = 6
    PLAY = 7
    ATTACH = 8
    EVOLVE = 9
    ABILITY = 10
    DISCARD = 11
    RETREAT = 12
    ATTACK = 13
    END = 14
    SKILL = 15
    SPECIAL_CONDITION = 16


class Ctx:
    IS_FIRST = 41
    MULLIGAN = 42
    ACTIVATE = 43


# Contexts where we KEEP/give up as little as possible -> minCount.
_MIN_CONTEXTS = {8, 10, 20, 23, 26, 27, 29, 30, 32}   # discard / detach / devolve
# Contexts where MORE is better -> maxCount (draw, damage, heal, place counters).
_MAX_CONTEXTS = {13, 14, 15, 17, 38, 39}
# NOTE: ctx 9 (TO_DECK) is NOT blanket-min: Sacred Ash returns OUR mons from the
# discard to the deck -> handled explicitly (take max); opp-forced mill stays min.

# MAIN action priority: lower = earlier in the turn. Abilities (the draw
# engines) first, then board development, then trainers, then ATTACK last so
# every hand-growing play has already resolved when Powerful Hand counts our
# hand.
_MAIN_PRIORITY = {
    OptionType.ABILITY: 0,
    OptionType.ATTACH: 1,
    OptionType.EVOLVE: 2,
    OptionType.PLAY: 3,
    OptionType.ATTACK: 4,
    OptionType.RETREAT: 5,
    OptionType.END: 9,
}

_LOOP_GUARD = 120  # actions in one turn before we force ATTACK/END


# --- board accessors ---------------------------------------------------------------

def _my_player(state: dict) -> dict:
    players = (state or {}).get("players") or []
    yi = (state or {}).get("yourIndex", 0)
    return players[yi] if yi < len(players) else {}


def _opp_player(state: dict) -> dict:
    players = (state or {}).get("players") or []
    yi = (state or {}).get("yourIndex", 0)
    return players[1 - yi] if 1 - yi < len(players) else {}


def _hand_n(p: dict) -> int:
    h = (p or {}).get("hand")
    if h is not None:
        return len(h)
    return (p or {}).get("handCount") or 0


def _hand_ids(p: dict) -> list[int]:
    return [c.get("id") for c in ((p or {}).get("hand") or []) if isinstance(c, dict)]


def _top_mon(slot) -> dict:
    """A board slot is a list of the evolution stack; last entry is on top."""
    if not slot:
        return {}
    mons = slot if isinstance(slot, list) else [slot]
    return mons[-1] or {}


def _in_play(p: dict) -> list[dict]:
    out = []
    for slot in [p.get("active")] + list(p.get("bench") or []):
        m = _top_mon(slot)
        if m:
            out.append(m)
    return out


def _mon_by_serial(cur: dict, serial) -> dict | None:
    """Find an in-play mon by engine serial across both players, or None."""
    if serial is None:
        return None
    for p in cur.get("players") or []:
        for m in _in_play(p):
            if m.get("serial") == serial:
                return m
    return None


def _my_bench_count(state: dict) -> int:
    return len([b for b in (_my_player(state).get("bench") or []) if b])


def _energy_n(mon: dict) -> int:
    return len((mon or {}).get("energyCards") or [])


# --- attack damage model -----------------------------------------------------------

_TR_ARTICUNO = 414
_MIST_ENERGY = 11
_ROCK_FIGHTING_ENERGY = 20

# Attacks of ours that PLACE DAMAGE COUNTERS rather than deal damage. Counters
# are an *effect*, so a whole family of cards nullifies them outright while our
# 20x-hand model happily reports a phantom OHKO.
_COUNTER_ATTACKS = (POWERFUL_HAND,)

# Opp mon serials observed absorbing one of our counter attacks for ZERO. Learned
# per game from the engine's own damage logs (see note_attack_result).
_COUNTER_IMMUNE: set[int] = set()

# (attackId, opp serial) pairs empirically shown to deal ZERO -- general form of
# _COUNTER_IMMUNE covering ANY attack, not just counter-placing ones. Kept
# separate from _COUNTER_IMMUNE (not folded in) because Repelling Veil/Battle
# Cage block EFFECTS specifically -- a serial known Powerful-Hand-immune must
# NOT suppress a different real-damage attack (test_attack_dominated_on_learned_
# immune_active_ep85765044 encodes this). _ATTACK_IMMUNE is move-scoped so it
# can't make that mistake.
_ATTACK_IMMUNE: set[tuple[int, int]] = set()

# Consecutive zero-observations per (attackId, serial), no nonzero in between.
# Some "prevent damage" effects are a ONE-TURN COIN FLIP (Hop's Phantump's
# Splashing Dodge: "flip a coin, if heads, prevent damage during opponent's
# NEXT turn"), not a permanent ability-block like Ogerpon's Cornerstone Stance.
# A single zero is not proof of a permanent block, and _attack_dominated fully
# removes the option from search candidates -- if it fired on one coin-flip
# miss, the attack could never be retried to observe the clearing hit, a
# self-reinforcing lockout that gives up ~50% of real future damage. Used only
# to gate the generalized (non-counter-attack) half of _attack_dominated; see
# _attack_repeatedly_immune.
_ATTACK_ZERO_STREAK: dict[tuple[int, int], int] = {}

# Attacks whose text is "flip a coin; if heads, prevent all damage (and
# effects) done to this Pokemon during opponent's next turn" -- a ONE-TURN,
# 50/50 dodge (Dig, Splashing Dodge, Hide, Cotton Wings, ...). Scanned from
# card_db for this exact effect-text pattern (14 cards, 2026-07-15). None of
# these are our own deck's cards (our Dunsparce/Dudunsparce are ids 305/66,
# not the id-65 Dunsparce with Dig).
_COIN_PREVENT_ATTACKS = (75, 244, 261, 505, 595, 684, 788, 790, 1054, 1205,
                          1266, 1309, 1382, 1470)

# serial -> turn the coin was observed, for opp mons whose coin-flip dodge
# landed heads. Latched until capture_turn + 1 has passed and NOT cleared per
# call: obs logs are per-step DELTAS (verified ep 86304608), so the t22 coin
# is only visible in ONE delta, while the ATTACK decision the flag exists to
# suppress comes many prompts later. A per-call clear wiped the flag before it
# could ever fire (v15 shipped that way; dead code live). The +1 grace exists
# because the coin can be observed at a prompt DURING the opponent's turn (a
# forced discard -- ep 86127978 captured heads at turns 2/6/10, their turns)
# and the effect protects their mon during OUR FOLLOWING turn; a same-turn
# latch would expire those captures exactly when they matter. A capture on our
# own turn T then also lingers through T+1 (their turn) -- harmless, we take
# no attack decisions there, and it is gone by our T+2.
_DODGE_LIVE: dict[int, int] = {}
_LAST_TURN = 0


def _expected_nonzero_attack(attack_id: int) -> bool:
    """True when this attackId is expected to deal nonzero damage under normal
    conditions -- distinguishes 'this move is inherently a 0-damage utility
    attack' from 'the target blocked/negated it' (Ogerpon ex's Cornerstone
    Stance on Shaymin's Smash Kick, ep 86139713). Counter-placing attacks and
    board-dependent multipliers report 0 in the static attack_db by
    construction, so they're whitelisted explicitly."""
    return (attack_id in _COUNTER_ATTACKS
            or attack_id in _MULT_DMG
            or _attack_db().get(attack_id, 0) > 0)


def note_attack_result(obs: dict) -> None:
    """Empirical immunity detector. _COUNTER_IMMUNE (Powerful-Hand/effect-based,
    serial-only) is legacy-preserved as-is. _ATTACK_IMMUNE generalizes to ANY
    attack: the engine's type16 damage log uses the same 'value' field for both
    counter-placement (positive int) and real HP loss (negative int) -- 0
    reliably means the attack did nothing to that target in BOTH cases (verified
    ep 86139713: Shaymin's Smash Kick, attackId 477, into Ogerpon ex logged
    {'putDamageCounter': False, 'value': 0} x64, never previously recorded
    because putDamageCounter was required truthy and attackId wasn't in
    _COUNTER_ATTACKS). Self-correcting per (attackId, serial): a later nonzero
    hit clears it; new game clears all."""
    global _LAST_TURN
    turn = ((obs.get("current") or {}).get("turn")) or 0
    if turn < _LAST_TURN:            # turn went backwards -> new game, new serials
        _COUNTER_IMMUNE.clear()
        _ATTACK_IMMUNE.clear()
        _ATTACK_ZERO_STREAK.clear()
        _DODGE_LIVE.clear()
    elif turn != _LAST_TURN:         # turn advanced -> expire dodges past their window
        for ser, t0 in list(_DODGE_LIVE.items()):
            if turn > t0 + 1:
                del _DODGE_LIVE[ser]
    _LAST_TURN = turn

    # NOTE: obs has no top-level "yourIndex" key in the real observation shape --
    # it only exists nested under obs["current"]["yourIndex"]. obs.get("yourIndex", 0)
    # silently defaulted to 0 every time (the key is MISSING, not None, so the
    # default always applied), which happened to match our seat only when we were
    # seat 0 -- in every seat-1 game (~half of all games) this attributed the
    # OPPONENT's attacks to us and vice versa, silently disabling the whole
    # immunity detector. Found by replaying ep 86132702 (seat 1): a real Powerful
    # Hand vs Great Tusk logged {'putDamageCounter': True, 'value': 0} and was
    # never recorded.
    me = (obs.get("current") or {}).get("yourIndex", 0)
    ours_aid = None
    for lg in (obs.get("logs") or []):
        t = lg.get("type")
        if t == 15:   # attack declared
            aid = int(lg.get("attackId") or 0)
            ours_aid = aid if (lg.get("playerIndex") == me
                                and _expected_nonzero_attack(aid)) else None
        elif t == 16 and ours_aid is not None:
            serial = lg.get("serial")
            if serial is not None:
                key = (ours_aid, serial)
                if lg.get("value"):          # nonzero -> not immune
                    _ATTACK_IMMUNE.discard(key)
                    _ATTACK_ZERO_STREAK.pop(key, None)
                    if ours_aid in _COUNTER_ATTACKS:
                        _COUNTER_IMMUNE.discard(serial)
                elif _effect_guard_attached(_mon_by_serial(obs.get("current") or {},
                                                           serial)):
                    # ZERO fully explained by removable effect-protection Energy
                    # still attached to the target -- transient, do NOT feed the
                    # permanent latch (or the streak). A latched transient zero
                    # can never self-correct:
                    # the veto stops us retrying, so the clearing nonzero is
                    # never observed (eps 86625232/86631800: one Mist zero each
                    # banned Powerful Hand for the rest of the game -> 30/turn
                    # chip -> deck-out while ahead). _attack_dominated already
                    # vetoes live while the Mist is attached, so nothing is
                    # lost by not recording it.
                    pass
                else:                        # ZERO -> target absorbed it
                    _ATTACK_IMMUNE.add(key)
                    _ATTACK_ZERO_STREAK[key] = _ATTACK_ZERO_STREAK.get(key, 0) + 1
                    if ours_aid in _COUNTER_ATTACKS:
                        _COUNTER_IMMUNE.add(serial)
            ours_aid = None

    # Read the OPPONENT's coin-flip dodge result directly (type22, {'head':
    # bool}) instead of waiting to infer it from a wasted attack. Accumulated
    # into the turn-latched _DODGE_LIVE (expiry is the turn-change clear above,
    # NOT a per-call reset -- per-step delta logs mean this call is the only
    # one that will ever see the coin). The strict t15-then-t22 pairing is
    # deliberate: other effects flip coins too (ep 86304608 logged a t22
    # BEFORE an unrelated t15), so only a coin that directly follows a known
    # coin-prevent attack counts. _COIN_PREVENT_ATTACKS re-verified complete
    # against card_db 2026-07-16; every real dodge in logs/v14a+v14b+v15 was
    # id 1266 and matched this exact pattern.
    pending_dodge_serial = None
    for lg in (obs.get("logs") or []):
        t = lg.get("type")
        if t == 15:
            aid = int(lg.get("attackId") or 0)
            pending_dodge_serial = (lg.get("serial") if aid in _COIN_PREVENT_ATTACKS
                                     else None)
        elif t == 22 and pending_dodge_serial is not None:
            if lg.get("head"):
                _DODGE_LIVE[pending_dodge_serial] = turn
            pending_dodge_serial = None


def _dodge_blocks_active(dfn_player: dict) -> bool:
    """True when dfn_player's current active's coin-flip dodge landed heads
    THIS TURN, read directly from the engine's own coin log (_DODGE_LIVE) --
    proactive proof, not an inference from a wasted attack."""
    act = _top_mon(dfn_player.get("active"))
    if not act:
        return False
    return act.get("serial") in _DODGE_LIVE


# General transient attack-effect protection.  EFFECT_GUARD_FIX is the current
# switch and defaults ON because this is rules correctness, not value shaping.
# MIST_FIX remains a deprecated compatibility alias for older A/B tooling: when
# explicitly supplied it becomes the default for the new switch.
_legacy_guard_default = os.environ.get("MIST_FIX", "1")
_EFFECT_GUARD_FIX = os.environ.get("EFFECT_GUARD_FIX", _legacy_guard_default) != "0"
_MIST_FIX = _EFFECT_GUARD_FIX

# energy card id -> required attached Pokémon type, or None for any type.
# Keep this explicit and coverage-test it against the bundled card rules text.
# Card 11 Mist Energy protects any Pokémon; card 20 Rock Fighting Energy only
# protects a {F} Pokémon. Both prevent effects, not ordinary attack damage.
_EFFECT_GUARD_ENERGY = {
    _MIST_ENERGY: None,
    _ROCK_FIGHTING_ENERGY: "{F}",
}


def _effect_guard_enabled() -> bool:
    return bool(_EFFECT_GUARD_FIX and _MIST_FIX)


def _effect_guard_attached(mon: dict | None) -> bool:
    """Whether removable attached Energy currently blocks attack effects.

    This is deliberately evaluated from the live mon on every call and is never
    latched.  If the Energy leaves, Powerful Hand becomes legal immediately.
    """
    if not _effect_guard_enabled() or not mon:
        return False
    mon_type = card_db.pokemon_type(mon.get("id") or 0)
    for energy in mon.get("energyCards") or []:
        cid = (energy or {}).get("id")
        if cid not in _EFFECT_GUARD_ENERGY:
            continue
        required_type = _EFFECT_GUARD_ENERGY[cid]
        if required_type is None or mon_type == required_type:
            return True
    return False


def _mist_attached(mon: dict | None) -> bool:
    """Deprecated Mist-specific probe retained for old diagnostics/tests."""
    return _effect_guard_enabled() and bool(mon) and any(
        (e or {}).get("id") == _MIST_ENERGY
        for e in (mon.get("energyCards") or []))


def _a_priori_counter_immune(mon: dict, dfn_player: dict) -> bool:
    """TR Articuno's Repelling Veil (414) makes every Basic Team Rocket mon of
    theirs immune to effects, board-wide -- not just the active (CardImpl.h:5054).
    Split out of _counters_blocked so _boss_useful's bench scan can apply the
    same a priori rule to drag targets, not just the empirically-learned
    _ATTACK_IMMUNE set. Also covers registered effect-protection Energy attached
    to THIS mon: same 'counters do nothing' consequence, same callers (damage
    model + drag-target scan), but per-mon and only while the Energy stays
    attached."""
    if not mon:
        return False
    if _effect_guard_attached(mon):
        return True
    if not any(m.get("id") == _TR_ARTICUNO for m in _in_play(dfn_player)):
        return False
    info = card_db.card(mon.get("id") or 0) or {}
    return (info.get("stage_or_type") == "Basic Pokémon"
            and "Team Rocket" in str(info.get("category") or ""))


def _counters_blocked(dfn_player: dict) -> bool:
    """True when our counter-placing attacks do NOTHING to their active: either
    already observed doing zero (note_attack_result) or a priori through TR
    Articuno's Repelling Veil -- 414 in play makes every Basic Team Rocket's mon
    of theirs immune to effects, so we don't need to waste a turn learning it.
    Real damage (Kadabra's Super Psy Bolt) still pierces both."""
    act = _top_mon(dfn_player.get("active"))
    if not act:
        return False
    if act.get("serial") in _COUNTER_IMMUNE:
        return True
    return _a_priori_counter_immune(act, dfn_player)


def _attack_immune(attack_id: int, dfn_player: dict) -> bool:
    """True when THIS specific attackId has already been shown to do zero to
    dfn_player's current active (_ATTACK_IMMUNE). Move-scoped: does not imply
    other attacks are also blocked."""
    act = _top_mon(dfn_player.get("active"))
    if not act:
        return False
    return (attack_id, act.get("serial")) in _ATTACK_IMMUNE


def _any_attack_blocked(dfn_player: dict) -> bool:
    """True when AT LEAST ONE of our attacks has already been shown to do zero
    to dfn_player's current active -- coarser than _attack_immune, for callers
    (like _boss_useful) that need to know 'can we hurt them AT ALL' before
    they've decided which specific attack to throw. Single-shot (not streak-
    gated like _attack_repeatedly_immune): a premature Boss play here only
    costs one supporter card, not a permanent lost-damage lockout, so there's
    no need for the extra confirmation."""
    act = _top_mon(dfn_player.get("active"))
    if not act:
        return False
    serial = act.get("serial")
    return any(s == serial for (_aid, s) in _ATTACK_IMMUNE)


def _attack_repeatedly_immune(attack_id: int, dfn_player: dict) -> bool:
    """True only after >=2 CONSECUTIVE zero observations for this (attackId,
    serial), no nonzero hit in between. Guards _attack_dominated's hard
    candidate-elimination against a one-turn coin-flip 'prevent damage' effect
    (Hop's Phantump's Splashing Dodge) -- a single zero isn't proof of a
    permanent block, and once an option is eliminated from search candidates it
    can never be retried to observe the clearing hit, a self-reinforcing
    lockout that would give up ~50% of real future damage."""
    act = _top_mon(dfn_player.get("active"))
    if not act:
        return False
    return _ATTACK_ZERO_STREAK.get((attack_id, act.get("serial")), 0) >= 2


def _attack_dominated(opt: dict, state: dict) -> bool:
    """Suppress an attack the engine has ALREADY shown does zero to this active.
    Counter-placing attacks (_COUNTER_ATTACKS) use single-shot _attack_immune,
    same as before this generalized: their known blockers (Repelling Veil,
    Battle Cage, TR Articuno) are permanent ability effects, already validated
    by test_attack_dominated_on_learned_immune_active_ep85765044. Any OTHER
    attack (generalized after ep 86139713: Shaymin's Smash Kick was blocked by
    Ogerpon ex's Cornerstone Stance the same way, but was never suppressed
    because this used to be scoped to _COUNTER_ATTACKS only) uses the stricter
    2-confirmation _attack_repeatedly_immune, since we don't know a priori
    whether an arbitrary block is permanent or a 1-turn coin flip -- UNLESS
    _dodge_blocks_active already has direct proof for this exact turn (the
    engine's own coin-flip log), in which case we don't need to wait for any
    confirmation at all. Move-scoped (not _counters_blocked's serial-only
    immunity) so a different, unproven attack against the same active stays
    legal -- real damage (Kadabra's Super Psy Bolt) still pierces a
    Powerful-Hand-specific block."""
    if opt.get("type") != OptionType.ATTACK:
        return False
    aid = int(opt.get("attackId") or 0)
    opp = _opp_player(state)
    if _dodge_blocks_active(opp):
        return True
    if aid in _COUNTER_ATTACKS:
        # Removable effect-protection Energy on their active is a priori proof
        # counters do nothing RIGHT NOW. Checked live, not latched: the moment
        # the Energy leaves, the veto lifts with it.
        return (_attack_immune(aid, opp)
                or _effect_guard_attached(_top_mon(opp.get("active"))))
    return _attack_repeatedly_immune(aid, opp)


# Multiplier attacks whose REAL damage depends on live board state. Includes
# opponent attacks so rollouts model the threats we face at the elite tier.
_MULT_DMG = {
    POWERFUL_HAND: lambda atk, dfn: (       # Alakazam: 20x OWN hand (counters)
        0 if _counters_blocked(dfn) else 20 * _hand_n(atk)),
    1240: lambda atk, dfn: 50 * _hand_n(dfn),   # Froslass: 50x DEFENDER hand
    183: lambda atk, dfn: 100,                  # Cruel Arrow: 100 to any target
}

# card id -> (attackId, best-reach fn over (my_player, opp_player)) for
# _active_max_dmg on multiplier mons.
_MULT_REACH = {
    ALAKAZAM: (POWERFUL_HAND, lambda me, opp: (
        0 if _counters_blocked(opp) else 20 * _hand_n(me))),
    861: (1240, lambda me, opp: 50 * _hand_n(opp)),  # Mega Froslass (opp)
}

# (card id, move name) -> flat single-target damage, for attacks whose damage
# lives only in effect text (card_db's "damage" field is null) -- the numeric-
# prefix parse in _active_max_dmg reads these as 0, a real threat-detection
# blind spot (found via _retreat_dominated's Cruel Arrow case, 2026-07-08).
# Scanned card_db for damage=null + numeric effect text; kept to unambiguous
# single-target flat hits (excludes heals, multi-target splits, per-energy/
# counter multipliers -- those need _MULT_DMG-style per-move logic, not a
# flat lookup). Keyed by (card id, move name), not name alone: "Drag Off"
# collides across Primeape (30 dmg) and Cryogonal (20 dmg).
_EFFECT_DMG = {
    (140, "Cruel Arrow"): 100,        # Fezandipiti ex
    (153, "Garnet Volley"): 180,      # Cinderace ex
    (591, "Telekinesis"): 70,         # Sigilyph
    (377, "Thunder Raid"): 210,       # Zeraora
    (52, "Tricolor Pump"): 60,        # Wugtrio ex
    (152, "Jumping Kick"): 40,        # Raboot
    (438, "Drag Off"): 30,            # Primeape
    (508, "Drag Off"): 20,            # Cryogonal
}


def _attack_damage(opt: dict, state: dict | None = None) -> int:
    aid = opt.get("attackId")
    if aid is None:
        return 0
    aid = int(aid)
    if state is not None and aid in _MULT_DMG:
        yi = (state or {}).get("yourIndex", 0)
        players = (state or {}).get("players") or []
        if yi < len(players):
            return _MULT_DMG[aid](players[yi], players[1 - yi])
    return _attack_db().get(aid, 0)


_ENERGY_LETTER = {"G": 1, "R": 2, "W": 3, "L": 4, "P": 5, "F": 6, "D": 7, "M": 8}


def _pays_cost(cost: str, energies) -> bool:
    """True if attached energy (resolved color codes, engine's `energies` field)
    can pay a move's cost string. Colored slots ({P}, {D}, ...) need that exact
    color; colorless slots (bullet) are paid by whatever's left over. energies=None
    (color unresolved) is a no-op True -- caller's existing total-count check
    already gates this path, so missing data never makes search stricter than
    before (same fallback contract as search._armed)."""
    if energies is None:
        return True
    avail = list(energies)
    for letter, code in _ENERGY_LETTER.items():
        for _ in range(cost.count("{" + letter + "}")):
            if code not in avail:
                return False
            avail.remove(code)
    return len(avail) >= cost.count("●")


_LINE_ATTACK_COST = "{P}"


def _line_armed(mon: dict) -> bool:
    """Whether an Abra-line Pokemon can pay its intended attack's {P} cost.

    The engine's resolved ``energies`` list is authoritative when present --
    including when ``energyCards`` is absent, which happens on partially
    visible states and would otherwise read a real Psychic as unarmed.
    Fixtures omitting ``energies`` keep the prior permissive fallback while
    still requiring an attached Energy card.
    """
    energies = (mon or {}).get("energies")
    if energies is not None:
        return _pays_cost(_LINE_ATTACK_COST, energies)
    return _energy_n(mon) > 0


# Dudunsparce's Land Crush: 90 PLAIN damage for {C}{C}{C} on a 140hp body.
# Powerful Hand places damage COUNTERS (an effect), so Repelling Veil / Mist /
# Battle Cage zero it outright -- Land Crush is real damage and pierces all of
# them. Measured 2026-07-23: yushin fires it 13.9x per win against the
# counter-immune decks (127/127 uses logged -90, never once blanked) and we have
# fired it 0 times in 131 games, because _attach_enables_ko only ever recognised
# ALAKAZAM and nothing else would fund a 3-energy investment off the Abra line.
# We are 0W-9L versus those decks.
# card_db writes colorless slots as the bullet char, and _pays_cost counts
# exactly that ("●", not "{C}") -- spelling this "{C}{C}{C}" parses as a ZERO-cost
# attack, so _land_crush_ready answers True on an empty Dudunsparce.
_LAND_CRUSH_COST = "●●●"


def _energy_count(mon: dict) -> int:
    """Attached energy count that survives partially visible states.

    The engine's resolved ``energies`` is authoritative when present -- and it is
    present on exactly the states where ``energyCards`` is absent, so counting
    only the latter reads 0 off a fully powered Pokemon. Same contract as
    _line_armed; Land Crush's cost is all-colorless, so a plain count is enough.
    """
    energies = (mon or {}).get("energies")
    if energies is not None:
        return len(energies)
    return _energy_n(mon)


def _dudun_is_the_plan(state: dict) -> bool:
    """True while our counter attacks are proven dead against their active AND
    the Abra line is already paid for.

    Two conditions, both required:
      * _counters_blocked -- the existing, shipped detector (true in 2 of 55 v29
        games), so every normal matchup is untouched.
      * some line copy can already pay {P}. Land Crush must never be the reason
        Alakazam sits unarmed: the counter-immunity is a property of THEIR CURRENT
        active, so it evaporates the moment they promote something else, and an
        unarmed Alakazam would then have nothing. Feeding Dudunsparce is strictly
        the spare-energy plan -- first {P} still goes to the line, always.
    """
    if not _counters_blocked(_opp_player(state)):
        return False
    return any(m.get("id") in (ALAKAZAM, KADABRA, ABRA) and _line_armed(m)
               for m in _in_play(_my_player(state)))


def _land_crush_ready(mon: dict) -> bool:
    """Can this Dudunsparce pay {C}{C}{C} right now?"""
    if (mon or {}).get("id") != DUDUNSPARCE:
        return False
    energies = (mon or {}).get("energies")
    if energies is None:
        return _energy_n(mon) >= 3
    return _pays_cost(_LAND_CRUSH_COST, energies)


def _attach_provides_line_cost(opt: dict, state: dict) -> bool:
    """Whether the Energy selected by an ATTACH option supplies {P}.

    Card ``type`` is sufficient for this deck's Basic Psychic, Telepath Psychic,
    and colorless Enriching Energy. Unknown energy metadata keeps the existing
    permissive contract rather than silently removing a legal conversion line.
    """
    cid = _play_card_id(opt, state)
    energy_type = str((card_db.card(cid) or {}).get("type") or "")
    if not energy_type:
        return True
    supplied = []
    for letter, code in _ENERGY_LETTER.items():
        supplied.extend([code] * energy_type.count("{" + letter + "}"))
    supplied.extend([0] * energy_type.count("{C}"))
    if not supplied:
        return True  # non-brace metadata: unparseable, not evidence of "no {P}"
    return _pays_cost(_LINE_ATTACK_COST, supplied)


def _active_max_dmg(state: dict, my_idx: int) -> int:
    """Best single-attack damage the given player's active can deal this turn,
    gated by attached energy (count AND color -- e.g. Powerful Hand's {P} cost
    can't be paid by colorless-only Enriching Energy)."""
    players = (state or {}).get("players") or []
    if my_idx >= len(players):
        return 0
    act = _top_mon(players[my_idx].get("active"))
    energy = _energy_n(act)
    mid = act.get("id") or 0
    best = 0
    for m in ((card_db.card(mid) or {}).get("moves") or []):
        if "[Ability]" in str(m.get("name") or ""):
            continue
        cost = str(m.get("cost") or "")
        if cost.count("{") + cost.count("●") > energy:
            continue
        if not _pays_cost(cost, act.get("energies")):
            continue
        dmg_str = str(m.get("damage") or "")
        if mid in _MULT_REACH and (not dmg_str.strip() or "×" in dmg_str):
            best = max(best, _MULT_REACH[mid][1](
                players[my_idx], players[1 - my_idx]))
            continue
        if not dmg_str.strip() and (mid, m.get("name")) in _EFFECT_DMG:
            best = max(best, _EFFECT_DMG[(mid, m.get("name"))])
            continue
        num = ""
        for ch in dmg_str:
            if ch.isdigit():
                num += ch
            else:
                break
        if num:
            best = max(best, int(num))
    return best


def _my_attacker_type(state: dict):
    """Our active's type for weakness math -- None when our reach comes from
    PLACING DAMAGE COUNTERS, which weakness does not modify.

    Alakazam's Powerful Hand places counters, so the {P} weakness on the whole
    Mega Lucario line (Mega Lucario ex 340hp, Hariyama, Makuhita, Riolu -- the
    only meaningfully {P}-weak deck in meta_decks.json) is worth NOTHING to us.
    Verified on 33 damage events landing on Mega Lucario ex across ep_23a/ep_23b:
    every value is a clean multiple of 20 (= 20 x hand), never doubled, with
    putDamageCounter=true on 28 of them.  Doubling here made us believe we had
    lethal at half the real requirement, commit the ATTACK, end the turn and
    deal half -- in those losses our Alakazam was one-shot 1.15x/game vs
    0.08x/game in the wins.
    """
    mid = _top_mon(_my_player(state).get("active")).get("id") or 0
    reach = _MULT_REACH.get(mid)
    if reach and reach[0] in _COUNTER_ATTACKS:
        return None
    return card_db.pokemon_type(mid)


def _can_ko_opp_active(state: dict) -> bool:
    yi = (state or {}).get("yourIndex", 0)
    opp = _opp_player(state)
    opp_act = _top_mon(opp.get("active"))
    if not opp_act:
        return False
    if _dodge_blocks_active(opp):
        return False  # coin-flip dodge landed heads this turn -- 0 regardless of our reach
    dmg = _active_max_dmg(state, yi)
    my_type = _my_attacker_type(state)
    if my_type and card_db.weakness(opp_act.get("id") or 0) == my_type:
        dmg *= 2
    return dmg >= (opp_act.get("hp") or 9999)


def _incoming_dmg(mon: dict, state: dict, opp_dmg: int, opp_type) -> int:
    eff = opp_dmg
    if opp_type and card_db.weakness(mon.get("id") or 0) == opp_type:
        eff *= 2
    return eff


def _retreat_dominated(opt: dict, state: dict, options=None) -> bool:
    """RETREAT is dominated when an attack is on the menu and no bench mon
    would survive the opponent's predicted hit any better than the incumbent
    -- almost everything here is OHKO range (140hp max), so a retreat only
    earns its keep when the swap-in actually dodges the kill (traced
    2026-07-08: ala_v1 retreated a full-hp armed Kadabra into an equally
    fragile Dunsparce vs Mega Lucario's 270 -- both die just the same, the
    retreat only wasted the attack and de-armed the line paying its energy
    cost; ala_v2 ep 84739248 retreated out of LETHAL RANGE with deck=0 and
    Powerful Hand already at 440). Preserves the legitimate dodge (ala_v1
    t51: 50hp Abra dies to a 100 flat attack, 140hp Alakazam on the bench
    survives it -- that retreat stays legal)."""
    if opt.get("type") != OptionType.RETREAT or options is None:
        return False
    if not any(o.get("type") == OptionType.ATTACK for o in options):
        return False
    yi = (state or {}).get("yourIndex", 0)
    if _active_max_dmg(state, yi) <= 0:
        return False   # incumbent literally can't damage the opp active (e.g.
                       # Powerful Hand nullified by Repelling Veil, ep85689246)
                       # -- "attack instead" is worthless, retreating to a mon
                       # that deals real damage IS the play; let search decide
    opp_dmg = _active_max_dmg(state, 1 - yi)
    if opp_dmg <= 0:
        return False   # can't verify the threat (e.g. text-effect damage _active_max_dmg
                        # can't parse, like Cruel Arrow's flat 100) -- never override a
                        # possible dodge on an unverifiable read
    opp_type = card_db.pokemon_type(_top_mon(_opp_player(state).get("active")).get("id") or 0)
    incumbent = _top_mon(_my_player(state).get("active"))
    if not incumbent:
        return False
    incumbent_dies = (incumbent.get("hp") or 0) <= _incoming_dmg(incumbent, state, opp_dmg, opp_type)
    if not incumbent_dies:
        return True   # already survives whatever they throw -- attack instead
    bench = _in_play(_my_player(state))
    bench = [m for m in bench if m is not incumbent]
    improves = any((m.get("hp") or 0) > _incoming_dmg(m, state, opp_dmg, opp_type) for m in bench)
    return not improves


# --- opp-bench targeting (Boss ctx3, snipes ctx15) ----------------------------------

def _pick_opp_bench(options: list[dict], state: dict, mn: int, kill_dmg: int):
    """Prefer a mon we can KO; among killable the most prizes; else the matchup
    playbook's kill_bonus (drag-and-stall the support engine). Returns None if
    the options aren't opp-bench."""
    my_idx = (state or {}).get("yourIndex", 0)
    players = (state or {}).get("players") or []
    pi = options[0].get("playerIndex")
    if pi is None or pi == my_idx or pi >= len(players):
        return None
    opp_bench = players[pi].get("bench") or []
    my_type = _my_attacker_type(state)

    def score(i: int) -> tuple:
        slot = options[i].get("index") or 0
        mon = _top_mon(opp_bench[slot]) if slot < len(opp_bench) else {}
        mid = mon.get("id", 0)
        hp = mon.get("hp", 9999)
        eff = kill_dmg * 2 if (my_type and card_db.weakness(mid) == my_type) else kill_dmg
        koable = bool(mon) and kill_dmg > 0 and hp <= eff
        return (0 if koable else 1, -_prize_value(mid) if koable else 0,
                -playbook.kill_bonus(mid), hp)

    ranked = sorted(range(len(options)), key=score)
    return sorted(ranked[:max(mn, 1)])


# --- helpers the search imports (candidate filters) ---------------------------------

def _attach_enables_ko(opt: dict, state: dict) -> bool:
    """Would attaching to our active unlock the KO on the opp active this turn?
    Powerful Hand needs exactly 1 energy, so this fires on the arm-up turn."""
    if opt.get("type") != OptionType.ATTACH:
        return False
    if (opt.get("inPlayArea"), opt.get("playerIndex", (state or {}).get("yourIndex", 0))) \
            != (4, (state or {}).get("yourIndex", 0)):
        if opt.get("inPlayArea") != 4:
            return False
    me = _my_player(state)
    act = _top_mon(me.get("active"))
    if not act:
        return False
    opp_act = _top_mon(_opp_player(state).get("active"))
    if not opp_act:
        return False
    # Land Crush: the 3rd energy onto an active Dudunsparce unlocks 90 PLAIN
    # damage. Checked before the {P} guards below on purpose -- the cost is
    # {C}{C}{C}, so ANY energy counts, and the Abra-line arming rules do not
    # apply. Only while counters are dead (_dudun_is_the_plan), so this cannot
    # divert energy off the line in a normal matchup.
    if act.get("id") == DUDUNSPARCE and _dudun_is_the_plan(state):
        if _energy_count(act) + 1 >= 3:
            return 90 >= (opp_act.get("hp") or 9999)
        return False
    if _line_armed(act) or not _attach_provides_line_cost(opt, state):
        return False  # already armed, or this attachment still cannot pay {P}
    mid = act.get("id") or 0
    if mid == ALAKAZAM:
        # Attaching removes the energy card from hand before Powerful Hand counts
        # it (20x hand), so the real reach this turn is 20*(hand-1).
        return 20 * max(_hand_n(me) - 1, 0) >= (opp_act.get("hp") or 9999)
    return False


def _attach_feeds_land_crush(opt: dict, state: dict) -> bool:
    """Forced-in candidate: any energy onto a Dudunsparce while counters are dead.

    A POSITIVE hook, deliberately -- v29 tried to steer attaches by VETOING the
    rival option and search simply wandered off to a draw instead, which is how
    it lost 39 rating points. Land Crush needs 3 energy, so the first two attaches
    look worthless to a bounded rollout and get pruned before the payoff is ever
    reachable; this keeps them on the menu so the investment can complete.
    """
    if opt.get("type") != OptionType.ATTACH:
        return False
    if not _dudun_is_the_plan(state):
        return False
    tgt = _attach_target_mon(opt, state)
    return bool(tgt) and tgt.get("id") == DUDUNSPARCE and not _land_crush_ready(tgt)


def _good_attach(opt: dict, state: dict) -> bool:
    """Attach that develops the plan: energy onto the Alakazam line (pre-evo
    charging carries through evolution) when the target isn't armed yet."""
    if opt.get("type") != OptionType.ATTACH:
        return False
    tgt = _attach_target_mon(opt, state)
    if not tgt:
        return False
    return tgt.get("id") in (ALAKAZAM, KADABRA, ABRA) and not _line_armed(tgt)


def _bad_attach(opt: dict, state: dict, options=None) -> bool:
    """Wasted attach relative to the Abra line's required Psychic energy.

    A line Pokemon is armed only when it can pay {P}; colorless Enriching Energy
    does not make a later Psychic attachment redundant.
    """
    if opt.get("type") != OptionType.ATTACH:
        return False
    tgt = _attach_target_mon(opt, state)
    if not tgt:
        return False
    in_play = _in_play(_my_player(state))
    # Feeding Dudunsparce toward Land Crush is the ONLY real damage we have while
    # counters are dead -- Powerful Hand is doing a literal 0 here, so the
    # "power the line first" rule below would starve the only attack that works.
    # Once it can already pay ●●●, further energy is waste again (7 energy in the
    # whole deck), so it goes back to being a bad attach.
    if tgt.get("id") == DUDUNSPARCE and _dudun_is_the_plan(state):
        return _land_crush_ready(tgt)
    if tgt.get("id") not in (ALAKAZAM, KADABRA, ABRA):
        line_mons = [m for m in in_play if m.get("id") in (ALAKAZAM, KADABRA, ABRA)]
        # Only safe to power support after at least one line copy can pay {P}.
        return bool(line_mons) and all(not _line_armed(m) for m in line_mons)
    if not _line_armed(tgt):
        return False
    unarmed = any(m.get("id") in (ALAKAZAM, KADABRA, ABRA) and not _line_armed(m)
                  for m in in_play)
    return unarmed


def _attach_target_mon(opt: dict, state: dict) -> dict:
    p = _my_player(state)
    area, idx = opt.get("inPlayArea"), opt.get("inPlayIndex")
    if area == 4:
        return _top_mon(p.get("active"))
    if area == 5:
        b = p.get("bench") or []
        if idx is not None and idx < len(b):
            return _top_mon(b[idx])
    return {}


def _evolve_dominated(opt: dict, state: dict, options=None) -> bool:
    """The same evolution card could evolve an energized copy instead -> prefer
    that one (generic: evolving the armed copy keeps the attacker live)."""
    if opt.get("type") != OptionType.EVOLVE or options is None:
        return False
    tgt = _attach_target_mon(opt, state)  # same area/index shape as attach
    if not tgt:
        return False
    my_e = _energy_n(tgt)
    for o in options:
        if o is opt or o.get("type") != OptionType.EVOLVE:
            continue
        if o.get("index") != opt.get("index"):
            continue  # different hand card
        other = _attach_target_mon(o, state)
        if other and _energy_n(other) > my_e:
            return True
    return False


def _end_dominated(opt: dict, state: dict, options=None) -> bool:
    """END is dominated when a strictly-progressing option is on the menu -- this
    deck never passes with a free energy attach, evolution, payable attack, bench
    room, or an unused draw supporter/ability. A hard guard (not a value nudge)
    because the averaged rollout ties these against END and noise can land on END.
    Draw options are additionally gated by _draw_dominated so the "don't draw when
    thin+huge+ahead" comeback logic still applies, plus a bench check (Run Away Draw
    shuffles its user away and would strand an empty board)."""
    if opt.get("type") != OptionType.END or options is None:
        return False
    bench_target = playbook.bench_cap(_BENCH_TARGET)
    for o in options:
        t = o.get("type")
        if t == OptionType.ATTACH:
            tgt = _attach_target_mon(o, state)
            if tgt and _energy_n(tgt) == 0 and not _bad_attach(o, state, options):
                return True
            if _END_ATTACH_EXT and tgt:
                # (a) Enriching Energy: the attach itself draws a card -- never
                # pass on it unless the draw regime is suppressed (shared
                # _draw_suppressed gate; routed here because _draw_dominated's
                # type switch never marks an ATTACH opt as dominated).
                if _play_card_id(o, state) == _ENRICHING:
                    if not _draw_suppressed(state):
                        return True
                # (b) empty bench + lone active: ending the turn with a legal,
                # non-wasteful attach unused is pure donk exposure (ep85539881:
                # END over a 2nd energy on the lone un-powered active).
                if _my_bench_count(state) == 0 and not _bad_attach(o, state, options):
                    return True
        elif t == OptionType.EVOLVE:
            if not _evolve_dominated(o, state, options):
                return True
        elif t == OptionType.ATTACK:
            return True
        elif t == OptionType.PLAY:
            cid = _play_card_id(o, state)
            cinfo = card_db.card(cid) or {}
            st = cinfo.get("stage_or_type", "")
            if st == "Stadium":
                return True
            if st == "Basic Pokémon" and _my_bench_count(state) < bench_target:
                return True
            if cid in _DRAW_CARDS and not _draw_dominated(o, state):
                return True
        elif t == OptionType.ABILITY:
            if not _draw_dominated(o, state) and not _suicide_ability(o, state):
                return True
    return False


def _attack_ends_turn_early(opt: dict, state: dict, options=None) -> bool:
    """An attack is premature while a safe, free development action remains.

    ATTACK ends the turn.  This guard implements sequencing, not a preference to
    delay damage: once the useful attach/evolve/draw/bench action is consumed it
    disappears from the next MAIN menu and the attack becomes available again.
    """
    if opt.get("type") != OptionType.ATTACK or options is None:
        return False
    bench_target = playbook.bench_cap(_BENCH_TARGET)
    for other in options:
        action_type = other.get("type")
        if action_type == OptionType.ATTACH:
            target = _attach_target_mon(other, state)
            if target and _energy_n(target) == 0 and not _bad_attach(other, state, options):
                return True
        elif action_type == OptionType.EVOLVE:
            if not _evolve_dominated(other, state, options):
                return True
        elif action_type == OptionType.ABILITY:
            if not _draw_dominated(other, state) and not _suicide_ability(other, state):
                return True
        elif action_type == OptionType.PLAY:
            if _play_suppressed(other, state, options) or _draw_dominated(other, state):
                continue
            card_id = _play_card_id(other, state)
            card = card_db.card(card_id) or {}
            stage = card.get("stage_or_type", "")
            if stage == "Stadium" or card_id in _DRAW_CARDS:
                return True
            if stage == "Basic Pokémon" and _my_bench_count(state) < bench_target:
                return True
    return False


_SELF_REMOVING_ABILITY = (DUDUNSPARCE,)   # Run Away Draw shuffles the user away


def _suicide_ability(opt: dict, state: dict) -> bool:
    """ABILITY that removes its own user from play (Run Away Draw) while it is our
    ONLY Pokemon = instant loss (no Pokemon in play), strictly dominated. END at
    least keeps real-opponent outs, so never prefer this."""
    if opt.get("type") != OptionType.ABILITY:
        return False
    # ABILITY opts carry the user in area/index (4=active, 5=bench), unlike
    # ATTACH which uses inPlayArea/inPlayIndex (verified on ep85539881 step31).
    p = _my_player(state)
    area = opt.get("area")
    if area == 4:
        user = _top_mon(p.get("active"))
    elif area == 5:
        b = p.get("bench") or []
        idx = opt.get("index")
        user = _top_mon(b[idx]) if idx is not None and idx < len(b) else {}
    else:
        return False
    if user.get("id") not in _SELF_REMOVING_ABILITY:
        return False
    # Run Away Draw shuffles its user AND every attached card back into the deck.
    # While Land Crush is our only working attack, drawing 3 off a Dudunsparce we
    # have been feeding throws away the whole multi-turn investment -- the fix
    # would undo itself. Only bites once energy is actually committed to it.
    if _dudun_is_the_plan(state) and _energy_n(user) > 0:
        return True
    return _my_bench_count(state) == 0


# Kill switch back to pre-attrition behavior exactly (ship-rule convention).
_ATTRITION_GUARD = os.environ.get("ATTRITION_GUARD", "1") != "0"


def _draw_suppressed(state: dict) -> bool:
    """State-level gate for suppressing optional draws (shared by _draw_dominated
    and _end_dominated's Enriching branch so they can't diverge). Only fires in a
    danger zone of deck <= min(4*need+4, 20), need = prizes we still must take;
    above that runway, draw freely. Inside it:
    - lethal-banked (any prize state): hand >= 10 and 20*hand already KOs their
      active -> further draws only burn clock (raw 20x model, since drawing past
      a lethal hand builds nothing that persists across attacks).
    - non-lethal: the draw IS the comeback plan, stays legal EXCEPT when strictly
      ahead (nothing to come back from): deck<=6 & hand>=7, or the hard floor
      deck <= 2*need+2 & hand>=15 where a certain deck-out outweighs the draw."""
    me = _my_player(state)
    opp = _opp_player(state)
    deck = me.get("deckCount", 99)
    hand = _hand_n(me)
    need = len(me.get("prize") or [])
    # Attrition branch: counters proven dead vs their active (latched
    # _COUNTER_IMMUNE / a priori Articuno -- permanent signals, not transient
    # Mist) means hand size has NO attack value, so every optional draw only
    # donates the deck-out race the 30-chip war has become. Traced 2026-07-19
    # (eps 86751681/86831768/86574733): we started the race ahead or even,
    # dug 7-13 cards/turn into a dead Powerful Hand, and decked out with the
    # opponent still holding 11-23 -- while ep 86750104 won the identical race
    # by decking them first. Only fires while the race is contestable
    # (deck <= theirs + 4); a big runway lead keeps setup draws legal, and
    # non-wall games (_counters_blocked False) are untouched.
    if _ATTRITION_GUARD and _counters_blocked(opp) \
            and deck <= opp.get("deckCount", 99) + 4:
        return True
    if deck > min(4 * need + 4, 20):
        return False
    opp_hp = (_top_mon(opp.get("active")) or {}).get("hp") or 0
    if hand >= 10 and 20 * hand >= opp_hp:
        return True
    if len(opp.get("prize") or []) > len(me.get("prize") or []):
        if deck <= 6 and hand >= 7:
            return True
        if hand >= 15 and deck <= 2 * need + 2:
            return True
    return False


def _draw_dominated(opt: dict, state: dict) -> bool:
    """Suppress pure draw/fetch (our abilities, Dawn/Hilda/Poke Pad) when
    _draw_suppressed says the deck runway can't afford it. Dudunsparce's Run
    Away Draw is ~deck-neutral (shuffles its stack back) so suppressing it is
    slightly over-broad -- accepted; it also removes a 1-prize body.
    Boss/Battle Cage/hammers/recovery stay legal (not draw engines)."""
    t = opt.get("type")
    if t == OptionType.ABILITY:
        return _draw_suppressed(state)
    if t == OptionType.PLAY:
        return (_play_card_id(opt, state) in _DRAW_CARDS
                and _draw_suppressed(state))
    return False


def _boss_useful(state: dict) -> bool:
    """Boss is worth its supporter slot only when the drag SECURES A KO we can't
    already get on the current active, and only on a target our active can actually
    KO -- not merely "some damage". Never scope it to "any bench mon is killable"."""
    if _can_ko_opp_active(state):
        return False  # already lethal on the current active, don't spend Boss
    # Immune active + a bench mon we haven't ALSO proven immune: Boss is the
    # only way to break the wall lock. Our active can't touch the immune
    # active, so dmg will be 0 and the normal path below returns False -- but
    # Boss pulling a not-yet-proven-immune bench mon is the play that avoids a
    # deck-out (traced: ep 86139713, Boss held 25+ turns vs Cornerstone Mask
    # Ogerpon ex, decked out). Originally required exactly 1 bench mon (the
    # only case where dragging was guaranteed to matter); generalized to ANY
    # bench mon not already known-blocked (ep 86132702 had 2 bench mons and
    # never triggered this branch at all) -- if EVERY bench mon is also
    # proven immune, dragging changes nothing, so don't fire.
    opp = _opp_player(state)
    opp_bench = [b for b in (opp.get("bench") or []) if b]
    # TR Articuno's a priori exclusion only matters when OUR block is the
    # counter-placing kind (Powerful Hand blocked on the active) -- Repelling
    # Veil protects Basic TR mons from EFFECTS, not from real damage, so it
    # must not exclude a bench target that's merely blocking a different,
    # real-damage attack (Ogerpon ex's Cornerstone Stance on Smash Kick,
    # ep 86139713, is unrelated to Articuno and still a valid drag target).
    counters_dead = _counters_blocked(opp)
    if (counters_dead or _any_attack_blocked(opp)
            or _dodge_blocks_active(opp)) and any(
            not any(s == b.get("serial") for (_aid, s) in _ATTACK_IMMUNE)
            and not (counters_dead and _a_priori_counter_immune(b, opp))
            for b in opp_bench):
        return True
    yi = (state or {}).get("yourIndex", 0)
    dmg = _active_max_dmg(state, yi)
    if dmg <= 0:
        return False
    # _boss_useful runs at the MAIN menu BEFORE Boss is played; playing Boss
    # (a supporter) removes a card from hand, so the Alakazam attacker's
    # 20x-hand reach drops by 20 by the time it swings on the dragged target.
    if _top_mon(_my_player(state).get("active")).get("id") == ALAKAZAM:
        dmg = max(dmg - 20, 0)
    my_type = _my_attacker_type(state)
    for b in (opp.get("bench") or []):
        if not b:
            continue
        eff = dmg * 2 if my_type and card_db.weakness(b.get("id") or 0) == my_type else dmg
        if eff >= (b.get("hp") or 9999):
            return True
    return False


def _play_suppressed(opt: dict, state: dict, options=None) -> bool:
    """Suppress plays that waste a card: Boss with no useful drag."""
    if opt.get("type") != OptionType.PLAY:
        return False
    cid = _play_card_id(opt, state)
    if cid == _BOSS:
        return not _boss_useful(state)
    if cid == _XEROSIC:
        # opponent discards to 3: elite plays it nonzero (8%) even at opp-hand 4-6,
        # not 0% -- the old <6 cutoff removed it from the candidate set entirely in
        # that range, stricter than yushin's real behavior, and traced this session
        # (1000-wall-evolution-race-2026-07-14.md) to real, repeated firings at
        # opp-hand 4-5 in actual games. Loosened to <4 so search can still weigh the
        # 4-6 range instead of never seeing it; search weighs the real cases either way.
        # Also suppress when Boss is the better supporter: burning Xerosic wastes
        # the supporter slot on a hand-size reduction when Boss would secure a KO
        # (traced: ep 86131675 T9, Xerosic fired then Alakazam retreated without
        # attacking; ep 86131664 T14, Xerosic burned while Boss sat in hand).
        if _boss_useful(state) and _BOSS in _hand_ids(_my_player(state)):
            return True
        opp = _opp_player(state)
        # <= 4, not < 4: at exactly 4 Xerosic discards ONE card -- v15 burned
        # the once-per-turn supporter slot on that 12 times in 69 games.
        return (opp.get("handCount", len(opp.get("hand") or []))) <= 4
    if cid == _NIGHTTIME_MINE:
        # Tera tax: dead vs non-Tera boards, and playing it thins OUR hand
        # (= Powerful Hand damage); only play into a visible Tera mon
        return not any(m.get("id") in _TERA_IDS for m in _in_play(_opp_player(state)))
    return False


def _play_card_id(opt: dict, state: dict, my_idx: int | None = None) -> int:
    idx = opt.get("index")
    hand = _hand_ids(_my_player(state))
    if idx is not None and idx < len(hand):
        return hand[idx] or 0
    return 0


# --- entry point ---------------------------------------------------------------------

def choose(obs: dict) -> list[int]:
    """Return the list of selected option indices for this obs."""
    select = obs.get("select")
    if select is None:
        raise ValueError("choose() called with select=None (deck phase handled in main)")

    options = select["option"]
    n = len(options)
    mn = select.get("minCount", 1)
    mx = select.get("maxCount", 1)
    stype = select.get("type")
    ctx = select.get("context")
    state = obs.get("current") or {}

    try:
        if stype == SelectType.MAIN:
            return [_choose_main(options, state)]
        if stype == SelectType.ATTACK:
            return [_best_attack(options, state)]
        if stype == SelectType.EVOLVE:
            return [_choose_evolve(options, state)]
        if stype == SelectType.YES_NO:
            return [_choose_yes_no(options, ctx, state)]
        if stype == SelectType.COUNT:
            return [_choose_count(options, ctx, state)]
        if stype == SelectType.CARD:
            return _choose_cards(options, state, ctx, mn, mx, select)
    except Exception:
        pass  # never crash -> guaranteed-legal fallback

    return _fallback(n, mn, mx, ctx)


# --- MAIN menu -------------------------------------------------------------------

# Elite bench runs wide (3-5 from turn 2): every bench mon is a 1-prize body,
# a draw ability, and Boss insurance.
_BENCH_TARGET = 4


def _choose_main(options: list[dict], state: dict) -> int:
    action_count = state.get("turnActionCount", 0)
    force_finish = action_count >= _LOOP_GUARD
    bench_n = _my_bench_count(state)
    bench_target = playbook.bench_cap(_BENCH_TARGET)
    best_idx, best_key = 0, None
    for i, opt in enumerate(options):
        t = opt.get("type")
        if force_finish and t not in (OptionType.ATTACK, OptionType.END):
            continue
        prio = _MAIN_PRIORITY.get(t, 7)
        tiebreak = (0, 0)
        if t == OptionType.ATTACK:
            # Counter-blocked attack (Powerful Hand into a Repelling Veil /
            # coin-flip-dodge wall) does 0 -- deprioritize below END (9) so we
            # develop instead of a futile swing. Real-damage attacks (Kadabra
            # Super Psy Bolt) still pierce and stay at normal ATTACK prio.
            # (traced: ep 86127978 22 turns of 0 dmg; ep 86139713 60 turns.)
            if _attack_dominated(opt, state):
                prio = 10
            tiebreak = (-_attack_damage(opt, state), _attack_cost(opt))
        elif t == OptionType.ATTACH:
            if _attach_enables_ko(opt, state):
                prio, tiebreak = 0, (1, 0)  # secure the KO right after abilities
            elif _bad_attach(opt, state, options):
                prio = 8
            else:
                tgt = _attach_target_mon(opt, state)
                # prefer arming the line: Alakazam > Kadabra > Abra > others
                rank = {ALAKAZAM: 0, KADABRA: 1, ABRA: 2}.get(tgt.get("id"), 3)
                tiebreak = (rank, _energy_n(tgt))
        elif t == OptionType.EVOLVE and _evolve_dominated(opt, state, options):
            prio = 8
        elif t == OptionType.RETREAT and (_can_ko_opp_active(state)
                                           or _retreat_dominated(opt, state, options)):
            prio = 8   # attack instead of retreating a lethal attacker / a no-benefit dodge
        elif t == OptionType.ABILITY and _suicide_ability(opt, state):
            prio = 11  # Run Away Draw on our lone mon = conceding; below even END
        elif t == OptionType.ABILITY and _draw_dominated(opt, state):
            prio = 8   # deck critically thin, hand already huge: don't draw closer to a loss
        elif t == OptionType.PLAY:
            cid = _play_card_id(opt, state)
            cinfo = card_db.card(cid) or {}
            st = cinfo.get("stage_or_type", "")
            is_trainer = st in ("Supporter", "Item", "Stadium", "Special Energy")
            if bench_n >= bench_target and not is_trainer:
                prio = 8  # bench is stocked; stop benching Pokemon
            if st == "Stadium":
                prio = 2  # Battle Cage before supporters
            elif _play_suppressed(opt, state, options) or _draw_dominated(opt, state):
                prio = 9
            tiebreak = (0 if card_db.evolvable(cid) else 1, 0)
        elif t == OptionType.END and _end_dominated(opt, state, options):
            prio = 10
        key = (prio, tiebreak[0], tiebreak[1], i)
        if best_key is None or key < best_key:
            best_key, best_idx = key, i
    return best_idx


def _best_attack(options: list[dict], state: dict | None = None) -> int:
    best_i, best = 0, -1
    for i, opt in enumerate(options):
        d = _attack_damage(opt, state)
        if d > best:
            best, best_i = d, i
    return best_i


def _choose_evolve(options: list[dict], state: dict) -> int:
    """SelectType.EVOLVE (Rare Candy ctx 37): options pair a hand card with an
    in-play target. Pick the target with the most energy (it attacks the turn
    it evolves), active over bench on ties."""
    def score(i: int) -> tuple:
        o = options[i]
        tgt = _attach_target_mon(o, state)
        return (-_energy_n(tgt), 0 if o.get("inPlayArea") == 4 else 1, i)
    return min(range(len(options)), key=score)


def _choose_yes_no(options: list[dict], ctx: int, state: dict | None = None) -> int:
    """YES to abilities/effects, and to ctx 41 (elites go FIRST 92% -- evolutions
    come online a turn sooner and this deck is all lines). MULLIGAN stays NO
    (keep our hand -- proven behavior, no mining evidence for flipping it).
    ACTIVATE (ctx 43) is the on-evolve draw prompt (Kadabra +2 / Alakazam +3);
    it never passes through search or _draw_dominated, so it must apply the
    shared _draw_suppressed gate itself -- traced ep 87498522 (v27): auto-YES
    draws helped lose a deck race we led 24-20 at T10, deckout at T34.
    Additionally floored at deck <= 20: _draw_suppressed's attrition branch can
    fire from T3 with a 40+ deck (early opp effect-guard energy), and refusing
    SETUP draws there hurt games we won (eps 87490862/87491392 T3-T7)."""
    want = OptionType.NO if ctx == Ctx.MULLIGAN else OptionType.YES
    if (ctx == Ctx.ACTIVATE and state
            and (_my_player(state).get("deckCount", 99) <= 20)
            and _draw_suppressed(state)):
        want = OptionType.NO
    for i, o in enumerate(options):
        if o.get("type") == want:
            return i
    return 0


def _choose_count(options: list[dict], ctx: int, state: dict | None = None) -> int:
    """Counts: max for draws (more hand = more Powerful Hand damage) -- EXCEPT
    when _draw_suppressed says the deck runway can't afford it (full-agent
    review 2026-07-19: the attrition guard suppressed draw PLAYS/ABILITIES but
    a COUNT cascade reaching here still maxed the draw, burning the same deck
    the guard protects). Suppressed -> take the smallest count instead."""
    lo = state is not None and _draw_suppressed(state)
    best_i, best = 0, None
    for i, o in enumerate(options):
        v = o.get("number", o.get("value", 0)) or 0
        if best is None or (v < best if lo else v > best):
            best, best_i = v, i
    return best_i


# --- CARD selects (cascades) -----------------------------------------------------

def _pick_count(fam: str, ctx: int, options: list[dict], state: dict, mn: int,
                mx: int, sel: dict | None) -> int:
    """How many options to take (the clone only ORDERS them)."""
    n = len(options)
    if fam == "fetch":
        return max(mn, min(mx, 1)) or 1
    if fam == "recover" or (fam == "bench" and ctx == 5):
        return min(max(mx, mn), n)   # take MAX (Night Stretcher / Poffin)
    if fam == "bench":  # ctx2 setup: bench every line basic, never expose utility
        line = sum(1 for op in options
                   if features._card_id(op, state, sel) in (DUNSPARCE, ABRA))
        return min(max(mn, line), mx or n, n)
    if fam == "keep":
        return min(max(mn, 1), n)    # engine forces the discard count
    return max(mn, 1)                # lead / promote / rotate / boss: pick one


def _choose_cards(options: list[dict], state: dict, ctx: int, mn: int, mx: int,
                  sel: dict | None = None) -> list[int]:
    fam = features.family_of(ctx, options, state)
    # candy (ctx37 evolve target) stays code: near-forced, code beats the model.
    # "main" is a SelectType.MAIN family (search._nudge/_candidates consume it
    # directly); _choose_cards only ever sees SelectType.CARD, so this branch
    # should be unreachable for it, but the guard is cheap insurance.
    if fam and fam not in ("candy", "main") and features.has_model(fam):
        k = _pick_count(fam, ctx, options, state, mn, mx, sel)
        if k <= 0:
            return []
        sc = features.scores(fam, state, options, sel)
        ranked = sorted(range(len(options)), key=lambda i: (-sc[i], i))
        return sorted(ranked[:k])

    # ctx 15 snipe -> opp bench (no snipe decisions in the elite data; KO math)
    if ctx == 15 and options:
        picked = _pick_opp_bench(options, state, mn, 50)
        if picked is not None:
            return picked

    return _fallback(len(options), mn, mx, ctx)


# --- generic fallback --------------------------------------------------------------

def _fallback(n: int, mn: int, mx: int, ctx: int) -> list[int]:
    n = max(n, 0)
    if n == 0:
        return []
    if ctx in _MAX_CONTEXTS:
        k = mx
    elif ctx in _MIN_CONTEXTS:
        k = mn
    else:
        k = mn if mn > 0 else 1
    k = max(0, min(k, n))
    return list(range(k))
