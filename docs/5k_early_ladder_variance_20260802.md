# 5k Grimmsnarl ladder variance — data analysis (2026-08-02)

Question: same checkpoint, 6 submissions (55198084, 55198075, 55189658, 55180261,
55171235, 55114709), ratings spread 365-1005 early on. Why, and is it the
"lower-tier non-meta decks" hole (elite_prior hypothesis)?

## Method

Refetched fresh episode metadata for all 6 subs via Kaggle EpisodeService,
built per-game rating trajectory (`initialScore`→`updatedScore`) ordered by
`createTime`. Script: `scripts/analyze_5k.py` pattern (ad hoc, not committed).

## Finding 1: elite_prior fallback hypothesis is WRONG

`ElitePriorHeuristic` (trained only on elite/meta replays, [[ptcg-crustle-answer-is-in-deck]]-adjacent
concern) is wired as `NeuralPolicy`'s constructor arg but **`NeuralPolicy.choose()`
never calls `self.fallback`** ([ptcg_ai/model.py:62-77](ptcg_ai/model.py#L62)).
Fallback only fires on an *exception* in `CompetitionAgent.__call__`
([ptcg_ai/agent.py:62-69](ptcg_ai/agent.py#L62)) — i.e. crashes, not routine
low-quality-opponent play. So elite_prior narrowness is not silently steering
every-turn decisions against weak decks. Rule out this mechanism.

## Finding 2: the 365-1005 spread is mostly rating-system cold start, not skill

Per-game `|updatedScore - initialScore|` averaged across all 6 subs:

| game range | avg |delta| |
|---|---|
| games 1-10  | ~54-74 |
| games 11-30 | ~14-16 |
| last 10 played | ~4-10 |

K-factor (or equivalent uncertainty term) is ~4-5x larger in the first 10
games than by game 20+. Same checkpoint, pure luck of who it's paired against
in the first ~10 games, produces huge divergent walks — this alone explains
most of the 360→1035 range seen across "identical" submissions. This is a
matchmaking/rating variance artifact, not evidence the agent is bad.

## Finding 3: real (if smaller) skill signal — a dip at opp_init 600-699

Win rate by opponent `initialScore` bucket, all 6 subs pooled, **restricted to
game 20+ only** (removes cold-start noise):

| opp_init bucket | n | win rate |
|---|---|---|
| <500 | 8 | 1.00 |
| 500-599 | 11 | 0.91 |
| **600-699** | **37** | **0.59** |
| 700-799 | 42 | 0.62 |
| 800-899 | 90 | 0.63 |
| 900-999 | 51 | 0.37 |
| 1000+ | 8 | 0.50 |

Agent crushes weak/low-rated opponents (<600, presumably non-meta/scripted) —
opposite of "no idea how to play bad decks." 900+ (genuine elite tier) is
legitimately hard, expected. The anomaly is 600-699: win rate there is *worse*
than 700-899 despite facing weaker-rated opponents. That band is where the
early-ladder population sits (new/mid entrants, mixed meta+non-meta), and it's
the one tier that underperforms its rating gap. This is the part of the
original hypothesis that survives, just narrower: not "bad vs all low tier,"
but a specific dip against the 600-699 population.

## Implication for next steps (no training done, per instructions)

- Don't chase "elite_prior needs non-elite examples" — it's not in the hot path.
- Early-ladder rating swings (game 1-15) are largely unavoidable noise from the
  rating system itself; don't over-index on any single submission's first-15
  record as a quality signal.
- If chasing the 600-699 dip: pull replays specifically in that opp_init band
  (not just "early games") and look for archetype clustering — that's a
  narrower, higher-signal slice than "early games are bad."
- 55180261 flagged "bugged" by user: metadata shows no errored/incomplete
  episodes, and its win rate (0.60) isn't an outlier vs the other 5 subs. If
  the bug is a known code issue (e.g. [[ptcg-feature-version-must-be-threaded]]),
  it isn't visibly manifesting in ladder outcome yet — worth checking what
  submission variant 55180261 actually packaged.

## Update 20260802 (later same day): Lucario matchup gap confirmed

User's follow-up read of raw replays (not just opp_init buckets) found the
600-699 dip is substantially a **single-archetype hole: Mega Lucario ex**.
Verified independently against `scripts/generate_loss_report.py` on
submission 55198084's first 12 games:

| # | ep_id | result | opp key cards |
|---|---|---|---|
| 3 | 89618027 | LOSS | Riolu x4, Mega Lucario ex x4 |
| 4 | 89618601 | LOSS | Deino/Zweilous (not Lucario) |
| 7 | 89620298 | LOSS | Mega Lucario ex x4, Riolu x4 |
| 8 | 89620861 | LOSS | Riolu x4, Mega Lucario ex x4 |
| 9 | 89621427 | LOSS | Mega Lucario ex x4 |
| 11 | 89622571 | WIN | Riolu x4, Mega Lucario ex x4 |

Lucario appeared 5 of the first 12 games, went 1-4 against it. This is the
dominant driver of the 600-699 win-rate dip, not generic "off-meta fragility."

**Tooling gap found in the process:** `classify_deck()` in
[scripts/generate_loss_report.py:25](scripts/generate_loss_report.py#L25) has
no Lucario branch — every Lucario game falls into the catch-all "Custom /
Off-Meta" bucket, which is why the earlier opp_init-bucket analysis in this
doc couldn't see the pattern on its own; it took manual replay reading to
surface it. Every past report/script that used `classify_deck` for archetype
breakdowns has silently merged Lucario into "Off-Meta" alongside truly random
decks.

**Deck/league gap confirmed:** zero references to "lucario" (any case) in
any training league config (`training/*_league.json`) or in
`freshstart/decklists/`. Lucario is not in the sparring pool, the coevolution
league, or the elite_prior training data. The only place "lucario" appears
in the repo is inside `episode-*-replay.json` files (opponents we've played
against) and one competitor's bundled `meta_decks.json`
(`freshstart/elite_submissions/alakazam_2_7`), not anywhere in our own
training/eval assets.

**Base-rate check on "wildly different ratings for the same checkpoint":**
for a true ~61% agent, P(winning ≥6 of first 7 games) ≈ 17%, P(≥5 of 7) is
under 50%. 55171235's 6-1 opening (helped by two easy Mewtwo pairings) vs.
55198084's 4-Lucario draw in its first 8 games is consistent with schedule
variance on top of a real archetype hole — both mechanisms (cold-start rating
noise + Lucario gap) are operating at once, not either/or.

**User's stated direction (recorded, not yet started):** no broad retrain, no
generic setup-behavior override yet. Targeted matchup expansion against
Lucario specifically, with setup/benching behavior tested as its own separate
ablation rather than bundled in — the Lucario losses include games where
Grimmsnarl came down on curve (turn 3 Froslass / turn 5 Grimmsnarl) and still
lost 1-5, so setup speed alone doesn't explain the loss cluster.
