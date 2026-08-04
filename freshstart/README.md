# freshstart — Pokémon TCG AI Battle, from zero

Everything you need to enter the Kaggle **Pokémon TCG AI Battle** competition and be
competitive on day one. No agent code, no project history — just the competition, the
engine, the cards, the meta, and the decklists that are actually winning.

Competition: https://www.kaggle.com/competitions/pokemon-tcg-ai-battle

## Read in this order

| File | What's in it |
|---|---|
| [COMPETITION.md](COMPETITION.md) | Game rules as implemented, submission mechanics, scoring/ladder, deck legality |
| [ENGINE.md](ENGINE.md) | The `cg` engine API: observation format, action format, enums, how to run games locally |
| [META.md](META.md) | The top-of-ladder field: archetype shares, how each deck wins, matchup structure |
| [TOP_PLAYERS.md](TOP_PLAYERS.md) | How the leading teams actually build their agents (timing-based survey of 30,000 games) |

## What's on disk

```
submission_template/       unmodified Kaggle sample submission — main.py + deck.csv + cg/
  main.py                  the entry point Kaggle calls; returns option indices
  deck.csv                 60 card IDs, one per line
  cg/                      engine bindings + prebuilt binaries for Linux x64/arm64, macOS, Windows
engine/ptcgProgram/        full C++ source of the battle engine (the "cabt Engine"), as shipped
data/EN_Card_Data.csv      every card: HP, type, weakness, retreat, attacks, costs, effect text
data/JP_Card_Data.csv      same, Japanese
decklists/                 ten real top-player 60-card lists, human-readable + drop-in deck.csv
```

Both `submission_template/` and `engine/ptcgProgram/` are byte-for-byte the official downloads —
no local edits.

## Fastest possible start

```bash
cp -r submission_template mysub
cp decklists/grimmsnarl_marnie.deck.csv mysub/deck.csv   # 54% of the top field plays this
cd mysub && zip -r ../mysub.zip .                        # main.py must be at the zip root
kaggle competitions submit -c pokemon-tcg-ai-battle -f ../mysub.zip -m "first try"
```

That gets you a legal, meta-correct entry that plays randomly. Everything after that is
decision quality — see [ENGINE.md](ENGINE.md) for the API you make decisions through.

To check the engine loads and the deck is legal before submitting (on macOS run
`xattr -cr mysub/cg` once first):

```bash
cd mysub && python -c "
from cg.game import battle_start, battle_finish
deck = [int(l) for l in open('deck.csv')]
print('deck legal:', battle_start(deck, deck)[1].errorType == 0)
battle_finish()"
```

See [ENGINE.md](ENGINE.md) for a full self-play loop.

## Card data

`data/EN_Card_Data.csv` is the ground truth for card text. One row per *move*, so a card
with two attacks plus an Ability spans three rows sharing a `Card ID`. Columns:

`Card ID, Card Name, Expansion, Collection No., Stage/Type, Rule, Category, Previous stage,
HP, Type, Weakness, Resistance, Retreat, Move Name, Cost, Damage, Effect Explanation`

- `Card ID` is the integer the engine speaks. It's what goes in `deck.csv`.
- `Cost` uses `{P}` for a typed requirement and `●` for a colorless/any requirement.
- Abilities appear in `Move Name` as `[Ability] <name>` with no damage.
- The engine also exposes the same data at runtime via `cg.api.all_card_data()` and
  `all_attack()` — prefer those inside an agent, they're authoritative and versioned with
  the binary.
- **Currency check (2026-07-29):** the shipped engine reports **1267 cards and 1556 attacks**,
  and the CSV contains exactly those 1267 card IDs with no gaps or extras — so this CSV is in
  sync with the engine. Re-run the check after any engine update:
  ```python
  from cg.api import all_card_data, all_attack
  print(len(all_card_data()), len(all_attack()))
  ```
  (The engine's C++ source references a few card IDs above 1267 that aren't in the released card
  list yet, so expect this count to grow.)
