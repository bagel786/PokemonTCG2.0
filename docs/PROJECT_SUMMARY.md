# Pokémon TCG AI competition: complete project summary

**Status timestamp:** 2026-07-30 10:30 UTC  
**Workspace:** `/Users/safiullahbaig/Projects/pokemonTCG2.0`  
**Goal:** reach approximately the top 20 before the competition ends in about 15 days.  
**Submission allowance:** up to five per day, but the plan favors one or two
evidence-backed uploads per day because the ladder is noisy and only two agents
remain live.

## Executive summary

**Current execution supersedes the earlier dual-policy sequence below.** Ladder
results showed that both shipped heuristic-era agents were far too weak, so the
active recovery is Grimmsnarl-only: rebuild from elite behavior, train on 468,506
Grimmsnarl decisions, preserve a package-ready BC candidate, and permit one
corrected 5,000-game PPO generation only after correctness tests pass. The full
run record is in `docs/OVERNIGHT_2026-07-30.md`.

The v2 BC policy reached 72.38% exact selection agreement on 43,533 held-out
elite decisions. The corrected 5,000-game PPO generation then beat BC 52.5% over
1,000 games while improving elite agreement to 72.49%. It also improved the
authentic Alakazam 2.7 screen from 65% to 74%, held Crustle flat, and lost only
0.5 points against Mewtwo. PPO passed Linux packaging with zero errors and is the
recommended unsubmitted candidate. Full evidence is in
`docs/OVERNIGHT_2026-07-30.md`.

We restarted strictly from `freshstart` and built a clean competition stack around
the official simulator. The deployed agent is a fail-closed hybrid: deck-specific
heuristics provide a legal fallback, while a compact neural policy ranks legal
options when confidence and packaging allow it. Training begins with imitation of
elite replay decisions and then uses synchronized two-policy PPO league training.

The two live learners are Cynthia's Garchomp ex and Marnie's Grimmsnarl ex. Both
collect games against the same opponent generation before either is updated, then
both advance together. Their opponent pool contains the other live learner, mirror
play, all ten tracked meta archetypes, strong historical Alakazam submissions, and
a bounded set of old checkpoints to detect forgetting.

The original million-game default has been rejected. More importantly, the
sequencing is now **ladder first**: ship legal Garchomp and Grimmsnarl baselines,
let real matches select one primary archetype, and only then spend substantial
time on focused BC/RL. Offline metrics are fail-fast diagnostics, not proxies for
ladder strength.

## Ladder-first correction (2026-07-30)

The first implementation sequence went too deeply into dual-policy RL before
placing a freshstart agent on the ladder. That was a strategic mistake with about
15 days remaining. Historical Alakazam work showed that heuristic win rates,
action agreement, AUC-like diagnostics, and simulator matchups can all disagree
with the real ladder.

The corrected sequence is:

1. upload two legal baselines immediately;
2. accumulate roughly 60 or more real matches per agent;
3. keep one ladder anchor and use the other slot for challengers;
4. choose one primary archetype from ladder evidence;
5. process and train data for that archetype first;
6. use short 5,000-20,000-game iterations; and
7. revisit dual-policy or 100,000-plus-game campaigns only if ladder improvement
   justifies them.

The two ready baseline artifacts are:

- `artifacts/garchomp-bc500-candidate-v2.tar.gz`, SHA-256
  `1951cde27d93c13e7c0090d3962ca186a7a7ecbe9c9cc7e38e1f48923fbec693`;
- `artifacts/grimmsnarl-heuristic-v1.tar.gz`, SHA-256
  `d196059a596ed74a2f5dabd8b04a425a7ab92b707e6c4170e8153912251b6488`.

Both archives passed native and Linux/amd64 execution games. Grimmsnarl uses its
heuristic because the existing Grimmsnarl BC checkpoint lost to that heuristic
locally. Garchomp BC is being shipped despite limited data specifically so the
ladder—not the 169-decision validation set—can judge it.

At the status timestamp, the Kaggle API returned HTTP 429 to submission-list
queries from both local and Azure environments. The archives are ready for manual
portal upload. No CLI upload was attempted without first confirming live-slot
state.

The user subsequently uploaded both baselines:

| Ladder role | Submission ID | Artifact |
|---|---:|---|
| Garchomp BC baseline | `55099955` | `garchomp-bc500-candidate-v2.tar.gz` |
| Grimmsnarl heuristic baseline | `55099961` | `grimmsnarl-heuristic-v1.tar.gz` |

These IDs are the comparison anchors for the ladder-first campaign. Kaggle status
could not yet be independently queried because the API continued to return HTTP
429; portal status and match counts remain the source of truth until throttling
clears.

## Competition and operating constraints

- Start from `freshstart`; older unrelated project approaches are not dependencies.
- Target top 20 rather than merely producing a legal agent.
- Preserve one stable ladder agent while testing a challenger in the other live slot.
- Never automatically replace an incumbent from a training result alone.
- Keep Azure competition infrastructure below an operational ceiling of **$150**
  against the user's **$200** credit balance.
- Keep at least $50 in reserve for storage, billing lag, and safety.
- Current VM retail compute estimate: **$0.484/hour** for Linux
  `Standard_D8s_v6` in South Central US.
- Daily Azure auto-shutdown remains enabled. No second paid worker is allowed by
  default. Azure budget alerts are not treated as hard spending stops.

## What we learned about the game and meta

The official game has three principal win paths: take the last Prize card, remove
all opposing Pokémon from play, or win when the opponent cannot draw at the start
of a turn. Prize-taking is therefore progress, but not a complete objective.
Prize mapping, single-/two-/three-Prize attackers, setup, energy tempo, protection,
bench liability, hand disruption, board locks, and deck-out all matter.

The recovered top-ladder snapshot in `freshstart/META.md` contains these ten
tracked archetypes:

| Approximate share | Archetype | Primary strategic issue |
|---:|---|---|
| 54% | Marnie's Grimmsnarl ex | Fast energy acceleration, 180 active plus bench snipe, Grass weakness |
| 14% | Team Rocket's Mewtwo ex | Wide Rocket board requirement, energy recursion, effect protection |
| 10% | Alakazam / Dudunsparce | One-Prize attacker whose damage counters scale with hand size |
| 8% | Mega Kangaskhan / Crustle | Damage-immunity prison and one-Prize trade |
| 4% | Dragapult ex | Active damage plus distributed bench counters and denial |
| 4% | Cynthia's Garchomp ex | 260-290 burst, 400-HP ceiling, post-attack rebuild turn |
| 2% | Mega Kangaskhan toolbox | Wide bench, free pivots, matchup-specific attackers |
| 2% | Mega Lopunny ex | One-energy pivot damage |
| 2% | Dipplin / Thwackey | Stadium-dependent double attacks and universal tutoring |
| unknown/small | Mega Starmie / Froslass | Efficient attacks and hand-size punishment |

The dominant practical conclusion is that every candidate must be strong into
Grimmsnarl without becoming exploitable by Alakazam, Mewtwo, Crustle, Dragapult,
or the low-share counter decks.

## Agent architecture

### Competition-facing behavior

- The agent sees only live/public observation fields.
- Opponent hand contents, hidden deck order, private simulator state, and other
  unavailable information are excluded from features.
- Every neural selection passes through legal-action sanitation.
- Any model or heuristic exception falls back to a guaranteed-legal action and is
  counted as a policy error.
- Garchomp and Grimmsnarl have deck-specific heuristic foundations.

### Neural model

The compact policy is trained in PyTorch and exported to compressed NumPy weights
for lightweight Kaggle inference. It contains:

- embeddings for state tokens, cards, attacks, option types, contexts, and areas;
- global and option numeric projections;
- an option-ranking policy head;
- a selection-count head for multi-selection contexts; and
- a value head estimating win probability.

The model ranks the options supplied by the official engine rather than predicting
from a fixed global action vocabulary. This keeps inference compatible with the
engine's variable legal-action sets.

## Data and elite imitation

### Processed local snapshot

- Source: public elite competition replays dated 2026-07-28.
- Downloaded locally: 513 replay JSON files, approximately 2.3 GB raw.
- Processed: 69,638 legal decisions from 486 episodes.
- Grimmsnarl subset: 48,048 decisions.
- Garchomp subset: 1,231 decisions.
- Replay alignment was audited as observation at step `t` with the submitted action
  at step `t+1`.
- Validation episodes are split by episode hash to prevent step leakage.

### Azure replay expansion

The first Jul-27 download strategy made one request per episode and was throttled.
It was replaced by a bulk-download path with exponential backoff. As of this
document's timestamp, Azure contains **4,431 Jul-27 replay files**. They still need
to be extracted, filtered, and merged into the elite shards before being treated
as training data.

### Elite-decision evaluation

The incumbent Garchomp BC model has only 169 held-out exact-deck decisions, so the
confidence interval is weak. Current same-state metrics are:

- exact full selection: 43.20%;
- single-selection top-1: 48.30%;
- single-selection top-3: 78.91%;
- selection-count accuracy: 89.35%;
- neural coverage at confidence margin 0.15: 40.14%;
- top-1 agreement within covered decisions: 69.49%.

Exact agreement is useful but not sufficient: multiple legal choices can be
strategically equivalent. Promotion also requires outcome-based head-to-head and
matchup evaluation.

## Baselines and supervised-learning results

| Agent | Opponent | Games | Win rate | Decision |
|---|---|---:|---:|---|
| Grimmsnarl heuristic | random legal | 100 | 84.0% | legality floor |
| Garchomp heuristic | random legal | 100 | 91.0% | legality floor |
| Garchomp heuristic | Grimmsnarl heuristic | 1,000 | 55.4% | matchup baseline |
| Grimmsnarl BC | Grimmsnarl heuristic | 1,000 | 48.3% | rejected for deployment |
| Garchomp BC incumbent | Garchomp heuristic | 1,000 | 55.6% | candidate |
| Garchomp BC incumbent | Grimmsnarl heuristic | 1,000 | 58.3% | candidate |

An Azure partial-data Garchomp BC challenger scored 53.5% against the Garchomp
heuristic and 59.85% against the Grimmsnarl heuristic, but lost direct incumbent
head-to-head 48.2% over 2,000 games. It was correctly rejected. This established
that heuristic win rates cannot substitute for direct incumbent comparison.

## Reinforcement-learning design

### Two live learners

Garchomp and Grimmsnarl are both updated. A synchronized round works as follows:

1. generation-N Garchomp collects from its weighted league;
2. generation-N Grimmsnarl collects from its weighted league;
3. neither live policy changes until both rollout sets exist;
4. PPO produces both generation-N+1 challengers;
5. old checkpoints enter a bounded historical pool; and
6. challengers must pass promotion gates before deployment.

Historical policies are not the primary opponents. They are a minority retained
to prevent strategy cycling and catastrophic forgetting. At most eight historical
Garchomp/Grimmsnarl snapshots are kept in a round.

### PPO correctness work

The first PPO smoke revealed a real mathematical bug: collection sampled from
temperature-scaled logits while training recomputed unscaled action probabilities.
That invalidated PPO's importance ratio. The implementation now:

- stores the exact behavior temperature with every decision;
- evaluates the new log probability under the same behavior parameterization;
- clips the PPO importance ratio;
- reports approximate KL and clip fraction;
- stops early at a target KL;
- clips gradients;
- applies entropy regularization; and
- retains an elite behavior-cloning auxiliary loss.

Sixteen current automated tests pass, including behavior-ratio identity, replay
alignment, model parity, safety, league contents, external-agent isolation, and
deck-length checks.

### Reward and credit assignment

The objective remains the actual game result: `1` for a win and `0` for a loss.
The value head estimates win probability. We intentionally do not give independent
rewards for taking a Prize, attaching Energy, dealing damage, or surviving longer;
those proxies can teach locally attractive plays that lose the prize trade or miss
a board/deck-out win.

Terminal-only Monte Carlo credit is safe but noisy. A good decision inside a lost
game can receive a negative advantage relative to the value estimate. Before the
larger campaign, the same rollout data will compare:

- terminal-return PPO; and
- GAE/value-difference advantages while retaining terminal outcome as the true
  objective.

The GAE variant is intended to improve credit assignment without redefining what
winning means. A raw prize reward is not planned. Potential-based shaping would be
considered only as a controlled experiment, never as an unvalidated default.

### Corrected multi-selection RL

The previous single-selection limitation has been removed. Rollout collection now
samples variable counts and ordered options without replacement, while storing the
exact count and stepwise behavior likelihood. PPO reconstructs the same masked,
ordered likelihood and updates both single- and multi-selection decisions. The
collector records trajectory ID, decision index, chosen order, behavior
temperature, model hash, and schema version. Terminal-outcome GAE uses gamma 1.0
and lambda 0.95; the objective remains win/loss only.

## Opponent league

The weighted league is defined in `training/meta_league.json` and contains:

- the other current live learner with extra weight;
- current mirror play;
- all ten tracked meta archetypes;
- elite-BC policies where replay coverage is adequate;
- rare archetypes oversampled above their ladder share; and
- a bounded historical checkpoint pool.

Most non-Garchomp/non-Grimmsnarl archetypes still use generic heuristics, so their
smoke-test win rates are not competitive-strength estimates. More elite replay
coverage and deck-specific opponent policies remain important.

## Historical Alakazam submissions

The user supplied two older Alakazam Kaggle archives, recalled as roughly low 800s
and approximately 870, although the exact rating-to-file mapping is unknown and
may now be stale.

- `alakazam_2.7.zip`: newer learned direct-policy submission.
- `alakazam_2.4a (1).zip`: older determinized search submission.

Both archives passed path-traversal and static-source audits, contain legal
60-card Alakazam lists, and are loaded through an isolated module adapter. Their
authentic variants completed four seat-balanced integration games with zero policy
errors and defeated the Garchomp BC incumbent in all four. Four games do not
estimate win rate, but they establish a useful hard regression matchup.

For scaled training, both run in fast learned-prior mode with verified-lethal
search disabled and a combined league weight capped at eight. Authentic search is
reserved for promotion evaluation because its long decision tail is too expensive
for high-volume rollout generation.

## Legality and packaging

- Ten-archetype smoke: 100 games and 11,063 decisions, with zero hero or opponent
  policy errors after attached-card feature handling was fixed.
- The small matchup win rates from that smoke are not strength estimates.
- Current Garchomp package:
  `artifacts/garchomp-bc500-candidate-v2.tar.gz`.
- Package SHA-256:
  `1951cde27d93c13e7c0090d3962ca186a7a7ecbe9c9cc7e38e1f48923fbec693`.
- Official Linux engine SHA-256:
  `d16244a3157fc55c3314f08dcc7c5179168697d78c105b95c7debd556b764bb7`.
- The exact archive passed a native package game and an emulated Linux/amd64 game
  of 91 decisions without a crash or illegal action.
- Files containing `sample-not-promoted` are diagnostics and must not be uploaded.
- Kaggle uploads remain manual because a new upload evicts an older live agent.

## Current synchronized calibration result

The 1,000-games-per-learner calibration round has completed on Azure.

### Collection

| Learner | Games | Training win rate | Decisions |
|---|---:|---:|---:|
| Garchomp | 1,000 | 43.4% | 80,356 |
| Grimmsnarl | 1,000 | 37.3% | 116,291 |

These are exploratory temperature-0.65 games against a deliberately difficult
mixed league. They are not deployment win rates.

### PPO update

| Learner | Final approximate KL | Final clip fraction | Output |
|---|---:|---:|---|
| Garchomp | 0.00489 | 0.05845 | Azure `round_001/garchomp_challenger.npz` |
| Grimmsnarl | 0.00233 | 0.02331 | Azure `round_001/grimmsnarl_challenger.npz` |

Both model files were produced and the synchronized round state is complete.
Neither challenger is promoted yet. They still require direct incumbent,
archetype, imitation, legality, packaging, and ladder gates.

## Revised scale and timing

The selected timing concern is incorporated here: one to two million games would
consume too much of the remaining competition window and delay ladder feedback.

| Stage | Total games | Expected wall time | Purpose |
|---|---:|---:|---|
| Completed calibration | 2,000 | collection about 11 minutes, plus PPO | verify end-to-end synchronized learning |
| One practical round | 20,000 | about 2-3 hours | produce a serious challenger |
| Initial campaign | 60,000-100,000 | about 10-18 hours | 3-5 short rounds with promotion checks |
| Extended focused campaign | 200,000-300,000 | about 1.5-2.5 days | target ladder-exposed weaknesses |
| One million | not planned | roughly 7-9 continuous days | only reconsider if learning curves still improve |

The immediate target is **5,000-20,000 games per focused iteration**. A cumulative
100,000-300,000 games is only a conditional ceiling after the ladder demonstrates
that the selected learner is improving. One to two million games is not planned.

## Candidate gates

A normal iteration uses a deliberately small ship gate:

1. zero policy errors in a short official-engine smoke;
2. no catastrophic regression in a 200-500-game incumbent screen;
3. a packaged Linux/amd64 legality and timeout smoke; and
4. an explicit decision about which live ladder agent it replaces.

This is enough to submit a reversible challenger and get real signal. Elite
agreement, full archetype sweeps, 2,000-game confidence tests, and authentic
Alakazam evaluation remain diagnostic or final-candidate gates, not mandatory
two-day blockers for every ladder experiment.

For close final comparisons, expand to 10,000 games per important matchup. Near a
50% win rate, 2,000 games has an approximate 95% sampling margin of 2.2 percentage
points, 10,000 about 1 point, and 50,000 about 0.44 points.

## Remaining risks

- Garchomp elite replay coverage is much smaller than Grimmsnarl coverage.
- The newly downloaded Jul-27 replay set is not processed yet.
- Most of the eight non-primary archetypes need stronger deck-specific opponents.
- Terminal-only reward has high variance; the GAE A/B is still pending.
- Ordered multi-selection PPO is implemented and covered by correctness tests.
- Local simulation can rank candidates, but only the Kaggle ladder measures the
  real opponent distribution and competition runtime behavior.
- Ladder rating is noisy and stale agents can mislead; retain an anchor agent and
  avoid reacting to a handful of games.
- Azure cost reporting can lag. The operational runtime ceiling and daily shutdown
  are the protection, not an assumption that the portal updates immediately.
- The rollout writer streams one gzip per collection. Before another multi-hour
  run, it needs sharded checkpoints and a resume manifest so auto-shutdown cannot
  silently invalidate an entire partial rollout.

## Next execution sequence

1. Upload the ready Garchomp BC and Grimmsnarl heuristic archives now.
2. Accumulate roughly 60 or more ladder matches per baseline.
3. Select one primary archetype and retain the other agent as the ladder anchor.
4. Process the 4,431 Jul-27 replays, prioritizing the selected archetype.
5. Add sharded rollout/resume support before the next multi-hour collection.
6. Run a 5,000-20,000-game focused BC/RL iteration on the selected learner.
7. Apply the fast legality/regression/package gate and submit the challenger.
8. Use ladder behavior to choose the next matchup or model change.
9. Use deep gates only for close or final candidates.
10. Freeze risky architectural changes for the final 48 hours.

## Key files

- `freshstart/META.md`: recovered meta and archetype strategy.
- `freshstart/decklists/`: exact ten-archetype deck lists.
- `training/meta_league.json`: weighted league configuration.
- `training/collect_selfplay.py`: official-engine rollout collection.
- `training/train_bc.py`: elite behavior cloning.
- `training/train_ppo.py`: PPO plus BC anchor.
- `training/run_league.py`: synchronized N-live-policy orchestration (`training/learners.json`).
- `training/evaluate.py`: seat-balanced head-to-head evaluation.
- `training/evaluate_league.py`: per-archetype evaluation matrix.
- `training/evaluate_imitation.py`: same-state elite decision comparison.
- `ptcg_ai/external.py`: isolated historical-submission adapter.
- `scripts/package_submission.py`: reproducible Kaggle archive builder.
- `scripts/validate_submission.py`: extracted archive execution smoke.
- `docs/EXPERIMENTS.md`: detailed experiment ledger.
- `docs/OPERATIONS.md`: Azure and packaging operations.
- `docs/RL_PLAN.md`: current hybrid RL plan.
- `docs/PROJECT_SUMMARY.md`: this complete handoff summary.
