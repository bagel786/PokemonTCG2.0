# Competition & rules

Official rules (binding): https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/rules
Discussion forum: https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/discussion

## Format

A Kaggle **simulation competition** on `kaggle_environments`. You submit a Python agent that
plays live matches of the Pokémon TCG against other competitors' agents on Kaggle's servers.
There is no fixed test set — your score is a rating earned against the current field.

There are **two related competitions** — check both, they have different deadlines and prizes:

| | Deadline | Reward | Teams |
|---|---|---|---|
| [pokemon-tcg-ai-battle](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle) — the agent ladder, what this folder covers | 2026-08-16 | Knowledge | 5,950 |
| [pokemon-tcg-ai-battle-challenge-strategy](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle-challenge-strategy) | 2026-09-13 | **$240,000** | 262 |

(As listed by `kaggle competitions list -s pokemon-tcg` on 2026-07-29.)

## What you submit

A zip with `main.py` **at the root**, plus whatever it needs:

```
main.py          must define  agent(obs_dict) -> list[int]
deck.csv         60 card IDs, one per line
cg/              engine bindings (ship the ones Kaggle provides; see the parity note below)
<your files>     models, data, modules
```

At runtime your submission is unpacked to `/kaggle_simulations/agent/`. **`__file__` is not
defined** in the exec'd `main.py`, so resolve paths the way the sample does:

```python
file_path = "deck.csv"
if not os.path.exists(file_path):
    file_path = "/kaggle_simulations/agent/" + file_path
```

`agent()` is called for **every decision**, including the very first one. On the first call
`obs.select is None` and you must return your 60-card deck as a list of card IDs. On every
later call you return **option indices** into `obs.select.option`:

- every element `>= 0` and `< len(obs.select.option)`
- length between `obs.select.minCount` and `obs.select.maxCount` inclusive
- no duplicates

An illegal answer or an exception loses you the game, so never let one escape.

**Engine parity — check this before every submission.** The `cg/` package (and its `libcg.so`)
you ship must match the engine version running on Kaggle. A stale `.so` breaks anything that
calls the engine locally inside your agent, silently and without an exception. The organizers
push updates mid-competition, and `libcg.so` has changed more than once. **Re-download the sample
submission from the competition's Data page and diff `cg/` against yours before you ship.** Never
ship a self-compiled `.so`.

## Scoring and the ladder

- Matches are skill-matched; your rating moves after each game based on result and opponent
  strength. Everyone starts around **600**.
- Rating is **relative to the current field** and drifts as the field improves. It is not an
  absolute skill measure, and the same code scores differently in different weeks.
- The K-factor decays as a submission plays more games, so a submission's score is unstable
  early and stiffens later. Very early readings are close to meaningless.
- **5 submissions per day, and only your newest 2 stay live and count.** A new submission
  evicts the *older* of the current live pair, so sequence deliberately: to keep a good agent
  alive alongside a new one, re-submit the good one first so it becomes the *newer* half.
- The public leaderboard is **per team** — one row, one score, 5,950 teams as of 2026-07-29,
  topping out at 1190.9. Both of your live submissions play and are rated, and the leaderboard
  shows the **higher-rated of the two**. Retired submissions keep displaying their last score on
  your Submissions tab, but they no longer play and no longer count.

## Episode replays

Full replays include every decision both agents made and the cards they revealed. Four ways to
get them:

- **Your own submissions** — the Submissions tab on the competition page.
- **Other teams' submissions** — the Leaderboard page offers replay downloads.
- **The CLI (or MCP)**: see
  https://github.com/Kaggle/kaggle-cli/blob/main/docs/simulation_competitions.md
- **The episode index dataset**, for bulk BC/RL/IL data:
  https://www.kaggle.com/datasets/kaggle/pokemon-tcg-ai-battle-episodes-index — a daily export of
  the top-rated episodes. New drops are announced in the competition forums.

Raw replay files are a few MB each, so pull what you need and extract rather than hoarding.

A replay's first recorded action per seat is that agent's 60-card deck list — which is how the
lists in `decklists/` were read off.

The public leaderboard itself comes from
`kaggle competitions leaderboard -c pokemon-tcg-ai-battle --show` (or `--download` for the full
CSV of all teams).

## Time budget

**600 seconds per game**, per agent, tracked across all your decisions in that game — plus
process startup. A hand-written bot uses ~0.03s per move; a heavy neural net can burn tens of
seconds just loading. Budget explicitly: a game can run 30+ turns with many decisions per
turn, and overrunning is a loss.

## Game rules as implemented by the engine

From `engine/ptcgProgram/Core.h` — these are the real constants:

| | |
|---|---|
| Deck size | 60 cards exactly |
| Copies of the same card | max 4 (Basic Energy exempt) |
| ACE SPEC cards | max 1 per deck (flagged `aceSpec` in card data) |
| Opening hand | 7 |
| Prize cards | 6 |
| Bench | 5, raised to 8 while a Tera Pokémon + Area Zero Underdepths are in play |

**Win conditions** (engine `LogType.RESULT.reason`):
1. You take your last Prize card.
2. Your opponent starts their turn with an empty deck (deck-out).
3. Your opponent has no Pokémon in the Active Spot after a Knock Out.
4. A card effect wins the game.

Turn structure per turn: draw, then any number of Item/Ability/evolve/bench plays, **one**
Supporter, **one** Stadium, **one** manual Energy attachment, **one** retreat, and then
optionally **one attack — which immediately ends your turn**. The first player cannot attack
or play Rare Candy on turn 1.

Knocking out a Pokémon ex takes **2** Prize cards; a Mega Evolution Pokémon ex takes **3**.
That prize math drives nearly every deckbuilding decision in the meta.

Weakness is **×2 damage** (not +30). Resistance subtracts. Weakness/Resistance never apply to
Benched Pokémon.

## Deck legality

Checked by the engine when you submit your deck list. A deck must be 60 cards, ≤4 copies of
any non-Basic-Energy card, ≤1 ACE SPEC, and must contain at least one Basic Pokémon (with no
Basic Pokémon in your opening 7 you mulligan). Copy any file in `decklists/*.deck.csv`
straight to `deck.csv` for a known-legal, known-strong list.
