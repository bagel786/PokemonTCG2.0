# The engine (`cg`) — API reference

The battle engine is a C++ library (the "cabt Engine"). Full source is in
`engine/ptcgProgram/` (C++20, header-only style, entry points in `Export.cpp`; no third-party
deps). You talk to it through the Python package in `submission_template/cg/`:

| File | Role |
|---|---|
| `cg/api.py` | The types and enums your agent uses, plus the forward-search API |
| `cg/game.py` | `battle_start` / `battle_select` / `battle_finish` — drive a whole local game |
| `cg/sim.py` | ctypes plumbing; picks the right binary for your platform |
| `cg/utils.py` | small helpers |

**All four platforms ship prebuilt.** `sim.py` selects on `platform.system()` /
`platform.machine()`:

| Platform | Binary |
|---|---|
| Windows | `cg.dll` |
| macOS (Intel or Apple Silicon) | `libcg.dylib` |
| Linux arm64 / aarch64 | `libcg-arm64.so` |
| Linux x86-64 (what Kaggle runs) | `libcg.so` |

On macOS the downloaded binary is quarantined and `dlopen` will refuse it with *"library load
disallowed by system policy"*. Clear the attribute once:

```bash
xattr -cr cg/
```

Measured cost of one complete random-vs-random game (same script, Apple Silicon host):

| Where | Binary | ms/game |
|---|---|---|
| macOS host, native | `libcg.dylib` | **18** |
| Linux arm64 container | `libcg-arm64.so` | 25 |
| Linux x86-64 container, emulated | `libcg.so` (what Kaggle runs) | 285 |

Local self-play is effectively free on a native binary. Running Kaggle's exact x86-64 `.so` under
emulation on ARM costs **~15×**, so use it to confirm behaviour, not to generate volume.

## The decision loop

Kaggle calls `agent(obs_dict)` once per decision. You convert and answer:

```python
from cg.api import Observation, to_observation_class

def agent(obs_dict: dict) -> list[int]:
    obs: Observation = to_observation_class(obs_dict)
    if obs.select is None:          # first call: hand over your deck
        return read_deck_csv()      # 60 card IDs
    return [0]                      # otherwise: indices into obs.select.option
```

### `Observation`

| Field | Meaning |
|---|---|
| `select` | What you're being asked (`SelectData`). `None` only at deck selection. |
| `logs` | Every event since your last decision (`list[Log]`) — the only way to see what the opponent did |
| `current` | Full `State` snapshot |
| `search_begin_input` | Opaque blob you pass to `search_begin()` to fork the engine |

### `State`

`turn` (1 = first player's first turn), `turnActionCount`, `yourIndex`, `firstPlayer`,
`supporterPlayed`, `stadiumPlayed`, `energyAttached`, `retreated`, `result` (winner index, -1
while playing), `stadium` (0 or 1 cards), `looking`, `players[2]`.

### `PlayerState`

`active` (list of 0 or 1 `Pokemon`; `None` if face-down during setup), `bench`, `benchMax`,
`deckCount`, `discard`, `prize` (`None` entries are face-down), `handCount`, `hand`
(**`None` for the opponent**), and the condition flags `poisoned / burned / asleep /
paralyzed / confused`.

Note the asymmetry: you see the opponent's **hand count** but not its contents, their full
discard pile, their board, and their revealed plays via `logs`. Everything else about their
deck must be inferred.

### `Pokemon`

`id`, `serial` (unique per card per match — use it to track identity across zones), `hp`,
`maxHp`, `appearThisTurn`, `energies` (list of `EnergyType` actually attached), `energyCards`,
`tools`, `preEvolution`.

### `SelectData`

`type` (`SelectType`), `context` (`SelectContext` — *why* you're choosing), `minCount`,
`maxCount`, `remainDamageCounter`, `remainEnergyCost`, `option` (the choices),
`deck` (present when choosing from your deck), `contextCard`, `effect`.

Branch on `context`, not just `type` — the same `SelectType.CARD` covers "choose your setup
Active", "discard a card", "put damage counters", and 20 other situations.

### `Option`

A tagged union. `type` tells you which fields are populated:

| `OptionType` | Meaning | Populated fields |
|---|---|---|
| `NUMBER` (0) | pick a count | `number` |
| `YES` (1) / `NO` (2) | yes/no | — |
| `CARD` (3) | a card | `area`, `index`, `playerIndex` |
| `TOOL_CARD` (4) | attached tool | `area`, `index`, `playerIndex`, `toolIndex` |
| `ENERGY_CARD` (5) | attached energy card | `area`, `index`, `playerIndex`, `energyIndex` |
| `ENERGY` (6) | energy units | + `count` |
| `PLAY` (7) | play from hand | `index` |
| `ATTACH` (8) | attach to a Pokémon | `area`, `index`, `inPlayArea`, `inPlayIndex` |
| `EVOLVE` (9) | evolve | `area`, `index`, `inPlayArea`, `inPlayIndex` |
| `ABILITY` (10) | use an Ability | `area`, `index` |
| `DISCARD` (11) | discard from play | `area`, `index` |
| `RETREAT` (12) | retreat | — |
| `ATTACK` (13) | attack | `attackId` |
| `END` (14) | end turn | — |
| `SKILL` (15) | order simultaneous effects | `cardId`, `serial` |
| `SPECIAL_CONDITION` (16) | pick a condition | `specialConditionType` |

`SelectType.MAIN` (`context == SelectContext.MAIN`) is the main-phase decision, where
`option` mixes `PLAY / ATTACH / EVOLVE / ABILITY / DISCARD / RETREAT / ATTACK / END`. This is
where games are won and lost — and remember `ATTACK` ends your turn, so anything you wanted to
do first must come first.

### Other enums

- `AreaType`: DECK 1, HAND 2, DISCARD 3, ACTIVE 4, BENCH 5, PRIZE 6, STADIUM 7, ENERGY 8, TOOL 9, PRE_EVOLUTION 10, PLAYER 11, LOOKING 12
- `EnergyType`: COLORLESS 0, GRASS 1, FIRE 2, WATER 3, LIGHTNING 4, PSYCHIC 5, FIGHTING 6, DARKNESS 7, METAL 8, DRAGON 9, RAINBOW 10 (all types), TEAM_ROCKET 11 (psychic + darkness)
- `CardType`: POKEMON 0, ITEM 1, TOOL 2, SUPPORTER 3, STADIUM 4, BASIC_ENERGY 5, SPECIAL_ENERGY 6
- `SpecialConditionType`: POISON 0, BURN 1, SLEEP 2, PARALYZE 3, CONFUSE 4
- `SelectContext`: 0–48, self-documented in `cg/api.py`. Notables: MAIN 0, SETUP_ACTIVE_POKEMON 1, SETUP_BENCH_POKEMON 2, TO_HAND 7, DISCARD 8, DAMAGE_COUNTER_ANY 14, EVOLVE 37, IS_FIRST 41 (go first?), MULLIGAN 42, ACTIVATE 43, COIN_HEAD 46
- `LogType`: 0–23. Notables: TURN_START 2, DRAW 4, MOVE_CARD 6, SWITCH 8, PLAY 10, ATTACH 11, EVOLVE 12, ATTACK 15, HP_CHANGE 16 (`value` + `putDamageCounter`), COIN 22, RESULT 23

New enum members and class attributes may be appended during the competition — don't switch
exhaustively on integer values without a default branch.

### Card metadata at runtime

```python
from cg.api import all_card_data, all_attack
cards   = {c.cardId: c for c in all_card_data()}   # hp, weakness, ex, megaEx, tera, aceSpec,
attacks = {a.attackId: a for a in all_attack()}    #   evolvesFrom, skills[], attacks[]
```

## Running games locally

`cg/game.py` drives a complete match head-to-head, no Kaggle needed. Two random agents:

```python
import random
from cg.game import battle_start, battle_select, battle_finish
from cg.api import to_observation_class

deck = [int(l) for l in open("deck.csv")]
obs, start = battle_start(deck, deck)
while True:
    o = to_observation_class(obs)
    if o.current is not None and o.current.result != -1:
        print("winner:", o.current.result); break
    sel = o.select
    n = random.randint(sel.minCount, sel.maxCount)
    obs = battle_select(random.sample(range(len(sel.option)), n))
battle_finish()
```

That script is run-verified as written (macOS ARM, ~18 ms/game, ~140 decisions per game).
`visualize_data()` dumps the match in the visualizer's format.

## Forward search from inside an agent

The engine can fork the current match so you can try lines before committing. Because the game
is imperfect-information, **you must supply your beliefs** about the hidden cards:

```python
from cg.api import search_begin, search_step, search_release, search_end

st = search_begin(obs,                    # the observation passed to agent(), verbatim
                  your_deck, your_prize,  # predicted card IDs, counts must match exactly
                  opponent_deck, opponent_prize, opponent_hand,
                  opponent_active,        # only if their Active is still face-down
                  manual_coin=False)      # True lets you choose coin flips
st = search_step(st.searchId, [0])        # advance the forked state
search_release(st.searchId)               # free one branch
search_end()                              # free everything
```

Counts must match the real state or you get a `ValueError`, so the opponent-belief lists are
where the modelling work goes. `manual_coin=True` makes forked games deterministic, which is
what you want for evaluating a line rather than sampling one.
