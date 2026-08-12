"""Audited card identities for the PP kawada Festival Lead deck.

Policy code must distinguish the two Applin printings by ID.  ``EXACT_DECK``
is deliberately stored in the same stable order as the source entry in
``data/meta/top_decklists.json`` so the packaged ``deck.csv`` can be checked
byte-for-byte as well as by multiset.
"""

from __future__ import annotations

from collections import Counter
from hashlib import sha256


DECK_ID = "291b0afd6ead"
DECK_ARCHETYPE = "Thwackey / Dipplin"

# Energy and Pokemon.
GRASS_ENERGY = 1
APPLIN_DRAGON = 42
VOLBEAT = 88
GROOKEY = 89
THWACKEY = 90
APPLIN_GRASS = 92
DIPPLIN = 93
SHAYMIN = 343

# Trainers.
UNFAIR_STAMP = 1080
POFFIN = 1086
BUG_SET = 1094
NIGHT_STRETCHER = 1097
SACRED_ASH = 1129
POKE_PAD = 1152
BRAVE_BANGLE = 1175
BOSS = 1182
BROCK = 1210
BLACK_BELT = 1211
HILDA = 1225
LILLIE = 1227
FESTIVAL = 1245

# Public opposing effect handled by the prompt resolver.  This is not a deck
# member: Xerosic makes the affected player choose cards from their own hand to
# discard, so a competition agent must understand the resulting CARD prompt.
XEROSIC = 1197

# Attacks used by the exact list.
FIND_FRIEND = 37
ROLLING_TACKLE = 38
QUICK_SIGN = 107
TUMBLING = 114
DO_THE_WAVE = 115


EXACT_DECK: tuple[int, ...] = (
    (GRASS_ENERGY,) * 8
    + (APPLIN_DRAGON,) * 3
    + (VOLBEAT,) * 3
    + (GROOKEY,) * 4
    + (THWACKEY,) * 4
    + (APPLIN_GRASS,)
    + (DIPPLIN,) * 4
    + (SHAYMIN,)
    + (UNFAIR_STAMP,)
    + (POFFIN,) * 4
    + (BUG_SET,) * 4
    + (NIGHT_STRETCHER,) * 2
    + (SACRED_ASH,)
    + (POKE_PAD,) * 4
    + (BRAVE_BANGLE,)
    + (BOSS,)
    + (BROCK,)
    + (BLACK_BELT,)
    + (HILDA,) * 4
    + (LILLIE,) * 4
    + (FESTIVAL,) * 4
)

EXACT_COUNTS = Counter(
    {
        GRASS_ENERGY: 8,
        APPLIN_DRAGON: 3,
        VOLBEAT: 3,
        GROOKEY: 4,
        THWACKEY: 4,
        APPLIN_GRASS: 1,
        DIPPLIN: 4,
        SHAYMIN: 1,
        UNFAIR_STAMP: 1,
        POFFIN: 4,
        BUG_SET: 4,
        NIGHT_STRETCHER: 2,
        SACRED_ASH: 1,
        POKE_PAD: 4,
        BRAVE_BANGLE: 1,
        BOSS: 1,
        BROCK: 1,
        BLACK_BELT: 1,
        HILDA: 4,
        LILLIE: 4,
        FESTIVAL: 4,
    }
)

# Public audit identities.  The first hashes the newline-terminated deck.csv;
# the second is insensitive to line ordering and hashes a comma-joined multiset.
DECK_CSV_SHA256 = "269bc5808a0db862c7afe8f2daaa3d0b3b6e3c68bd651dd515d14f9d85392326"
DECK_MULTISET_SHA256 = "e8e9908e4943584bcbf4d54c91feda6ccfd5a39c0a0cf7d30e5db4a5de7ebd7b"

APPLIN_IDS = frozenset({APPLIN_DRAGON, APPLIN_GRASS})
APPLIN_LINE = frozenset({APPLIN_DRAGON, APPLIN_GRASS, DIPPLIN})
GROOKEY_LINE = frozenset({GROOKEY, THWACKEY})
BASIC_POKEMON = frozenset({APPLIN_DRAGON, VOLBEAT, GROOKEY, APPLIN_GRASS, SHAYMIN})
POFFIN_ELIGIBLE = frozenset({APPLIN_DRAGON, VOLBEAT, GROOKEY, APPLIN_GRASS})
# Bug Catching Set can reveal Grass Pokemon of any stage or Basic Grass Energy.
# The Dragon-type Applin printing is intentionally absent.
BUG_SET_ELIGIBLE = frozenset(
    {GRASS_ENERGY, VOLBEAT, GROOKEY, THWACKEY, APPLIN_GRASS, DIPPLIN, SHAYMIN}
)


def deck_csv_bytes() -> bytes:
    """Return the exact bytes that must be written to packaged ``deck.csv``."""

    return ("\n".join(map(str, EXACT_DECK)) + "\n").encode("ascii")


def deck_csv_sha256() -> str:
    return sha256(deck_csv_bytes()).hexdigest()


def deck_multiset_sha256() -> str:
    return sha256(",".join(map(str, sorted(EXACT_DECK))).encode("ascii")).hexdigest()


if len(EXACT_DECK) != 60 or Counter(EXACT_DECK) != EXACT_COUNTS:
    raise AssertionError("audited Dipplin deck identity is internally inconsistent")
if deck_csv_sha256() != DECK_CSV_SHA256 or deck_multiset_sha256() != DECK_MULTISET_SHA256:
    raise AssertionError("audited Dipplin deck hash is internally inconsistent")
