# Break-1000 Plan — Research + Handoff for Codex

Date: 2026-08-04 · Deadline: ~10 days · Goal: push a tracked submission's rating-at-close past **1000**.
Author context: main analyst thread. This document is the full brief for the codex agent that will design/run the training. Read it top to bottom before proposing anything.

---

## 0. DECISIONS LOCKED (user, 2026-08-04) — build to these

1. **Effort split: mostly safe distillation.** ~80% on the AFBC + search-teacher BC refresh (§5). Inference-time-search-as-agent is a **small side prototype only**, not the main bet. No pure variance farming.
2. **Distill all three sources in parallel** (§5.1/5.2/5.3). Let the advantage filter sort quality across mirror + Alakazam/RagingBolt + Lucario simultaneously. Higher Azure spend is fine ($167 budget).
3. **Both tracked slots = trained models.** No slot spent on cold-start d842 variance farming. §6 is therefore reframed to *snapshot-timing of trained submissions*, not variance farming.
4. **Gates allow small regressions on already-winning matchups.** An easy matchup (e.g. Alakazam, +1230 net) may drop a few % if it buys a real gain vs the 850+ mirror/top field. Optimize **net rating expectation**, not strict per-matchup non-regression. This is deliberate — strict non-regression is *why* every prior candidate came back flat. Hard floor still applies to the mirror and to zero engine/policy errors.

---

## 1. Situation in one paragraph

Our best model is `grimmsnarl_5k_reference` (model SHA `d842f85...`, "d842"). It converges anywhere from mid-600s to high-800s and has **already touched 1005.1** on one submission (55171235). Multiple experiments to improve it have failed (three PPO regimes, Lucario BC, exposure curricula, MCTS adversary — all refuted; see §4). The scoring is **best-of-2**: final rank = the better of your two latest tracked submissions' rating **at competition close**. That single fact reshapes the whole strategy.

## 2. The two findings that reframe the problem

### Finding A — the model is already strong enough to reach 1000; the barrier is largely variance.
Win rate bucketed by **our own** live rating at game start (776 games, 14 submissions):

| our rating | win rate | drift |
|---|---|---|
| 500–599 | 69% (20/29) | ↑ |
| 600–699 | 64% (66/103) | ↑ |
| 700–799 | 59% (96/162) | ↑ |
| 800–899 | 57% (177/311) | ↑ |
| 900–999 | **55% (84/152)** | **↑ still positive** |
| 1000–1099 | 20% (2/10) | ↓ (n tiny) |

At 900–999 we win 55% — **positive expected drift**. A 55% agent climbs through that band on average; it just does so slowly, and cold-start + game-count variance dominates whether any given submission's *snapshot at close* lands above 1000. d842 peaking at 1005.1 confirms the raw ceiling is already ≥1000.

**Implication:** breaking 1000 = (a) small real strength gain at the very top of the ladder **plus** (b) aggressive variance/slot management under best-of-2. Do not treat this as a pure "the model is too weak" problem.

### Finding B — seat-2 RL is the wrong lever; the 850+ field is the right one.
- Elite top-team pool (613 daily-dataset episodes): **seat 0 wins 58.2%**. Going first is a ~16pt *structural* advantage for everyone.
- Us: seat 0 65.3% / seat 1 50.8% = 14.5pt gap — **at/below the field baseline**. We are not unusually bad going second. "More RL from seat two" chases a structural constant.
- What actually gates 1000 is the **850+ opponent field**, where we go 44.5% overall:

| 850+ opponent | n | win rate | seat0 / seat1 |
|---|---:|---:|---|
| Grim mirror | 96 | 45% | 47% / 43% |
| Alakazam | 52 | 46% | 48% / 45% |
| Raging Bolt | 20 | 30% | 33% / 29% |
| Crustle | 15 | 47% | 62% / 29% |
| (Lucario) | 3 | 0% | — (Lucario lives at 600–799, not here) |

The 1000-break target set is **mirror + Alakazam + Raging Bolt at high rating** — not Lucario (that's a separate climb-region elo bleed, §3).

## 3. Full archetype ledger (776 games, all bands)

| matchup | n | win rate | net elo | elo lost in losses |
|---|---:|---:|---:|---:|
| Mega Lucario | 75 | 45.3% | **−451** | −1245 |
| Grim mirror | 156 | 53.2% | +610 | −876 |
| Alakazam | 132 | 63.6% | +1230 | −763 |
| Archaludon | 67 | 58.2% | +168 | −618 |
| Raging Bolt | 39 | 46.2% | −31 | −247 |
| Dragapult | 32 | 59.4% | +109 | −284 |
| Crustle | 52 | 65.4% | +368 | −254 |
| Mewtwo | 24 | 66.7% | +271 | −52 |

Point bleed concentrates in the **600–899 bands** (loss-delta −1558 / −1660 / −1394) — high K-factor climb region overlapping the Lucario zone. Lucario is the biggest single-archetype net-elo hole overall but you stop meeting it above ~800, so it matters for *climb speed*, not for *holding 900+*.

## 4. What is already refuted — do NOT re-propose (from project memory)

- **PPO on the self-play/high-band league from the replay-refresh anchor** — three regimes in 24h. Tiny KL (≈0.0015–0.0018) → behaviorally a no-op, all gates flat. Real KL (0.030) → mirror regresses to 46.5% and Lucario to 77.1%. The anchor sits at a local optimum for self-generated rollout signal. `artifacts/highband_20260804`, `artifacts/highband_aggressive_20260804`.
- **Exposure curricula vs weak Lucario/Iono recreations** — frozen d842 already beats our own recreations ~90%, so gradient ≈ 0. Refuted.
- **Lucario sparring BC** — 6 candidates hit ~51% action agreement but only 5–7% game win rate vs d842. Offline imitation accuracy did not transfer to game strength (exposure bias / incompatible source-policy pooling / weak credit assignment). `artifacts/lucario_gap_20260803`.
- **MCTS adversary** — parked, too slow for deadline.
- The **only** mechanism that ever shipped a measured gain: **replay-refresh BC** (+0.7% over d842 in 50k games, `artifacts/5k_improvement_20260802`). Every plan below is a variant of "make replay-refresh better," not a new optimizer.

## 5. The technical bet: retargeted counterfactual distillation (advantage-filtered BC + search teacher)

Codex's original proposal is sound in *method* — it is literally advantage-filtered behavioral cloning ([Grigsby & Qi 2021](https://arxiv.org/abs/2110.04698)) fed by an expert-iteration search teacher ([ExIt / Student of Games line](https://www.researchgate.net/publication/375669946)). AFBC is designed for exactly our failure mode: BC on noisy demonstrations (the Lucario BC disaster) fails; BC on *advantage-positive* actions only does not. But **retarget it** per §2/§3:

**Pipeline (three demonstration sources, one BC refresh):**

1. **Elite-disagreement mining (primary, mirror + generalists).** From the daily Kaggle top-episode datasets (`kaggle.com/datasets/kaggle/pokemon-tcg-ai-battle-episodes-index`), pull top-team Grim games. At each state where d842's greedy action ≠ the elite player's action, run the **search teacher** (`training/search_teacher.py`, already qualified: 146k decisions / 48k search calls / **zero errors** / $0.74 on Azure) to score both actions under d842-vs-d842 continuation. Keep the elite action as a BC target **only** when its counterfactual advantage over d842's action is positive beyond a margin. This filters replay-refresh's demonstrations by measured advantage — the noise filter the plain Lucario BC lacked. Valid in the mirror because both decks are known (search teacher requires both decklists — see §7 constraint).
2. **Alakazam / Raging Bolt at high rating (secondary).** Authentic Alakazam 2.4a and 2.7 exist as trustworthy rollout opponents, so search counterfactuals here are reliable. Raging Bolt is our worst 850+ matchup (30%) — needs a decklist opponent built or mined.
3. **Lucario-defense (climb-speed, outcome-weighted not search).** Search counterfactuals vs Lucario are noisy (lucario_ppo2 rollout opponent is weak, 16% qualified=false). Use **outcome-weighted BC** from the ~24 real ladder *wins* vs actual Lucario submissions + the existing anti-archetype shard (3,217 decisions, `artifacts/anti_archetype_20260804`). Don't distill search here.

**Training:** targeted BC refresh via `training/targeted_refresh.py` (not PPO), d842 rehearsal retained. Gates (per decision 4 — net-expectation, not strict non-regression): mirror vs d842 at 50k **must be ≥ anchor both seats** (hard floor, the 1000 gate); Alakazam/Raging Bolt/Lucario measured but **small regression on an already-winning matchup is acceptable if net rating expectation rises**; zero engine/policy errors is a hard floor.

## 6. Snapshot timing under best-of-2 (both slots trained — decision 3)

No pure variance farming, but under best-of-2 with rank = rating-at-close, **timing still matters even for trained models**:
- Fresh submissions play ~400 games in the first day, converging by ~day 2 (55246709 → 893, 55246712 → 837 within 2h). Cold-start walk spans roughly ±150; the high-K early window is where a strong model most easily *snapshots* above its convergence point.
- **Strategy:** both slots hold trained models (best candidate + best runner-up, or two variants). Time the **final resubmit** of each so its high-K early window overlaps the last day(s) — a strong model is more likely to snapshot >1000 during high-K games than after it has settled. Rank = best-of-2 snapshot at close, so a well-timed resubmit of an already-good model is free upside, not a reroll gamble.
- Freeze new submissions by ~day −1: late enough to catch the high-K window, not so late the sub has too few games to matter.

Open sub-questions in §8.D.

## 7. Infrastructure inventory (all present, reusable)

- `training/search_teacher.py` — information-set MC search teacher. **Constraint: requires BOTH decklists** (`determinize_known_matchup`). Fine as a training teacher in known matchups; **cannot** be dropped in as the live submission agent (opponent deck unknown at inference without a deck-classifier front-end). p99 for the plain neural policy was 0.42ms; the *search* teacher is far slower (320-step rollouts) — untested against the live per-move budget.
- `training/targeted_refresh.py`, `training/replay_refresh.py` — the BC-refresh pipeline that produced the only shipped gain.
- `scripts/mine_anti_archetype.py` — generalizes to any archetype; produced the Lucario/Iono shard.
- `training/run_lowband_exposure.py` — driver with full knob set (seat ratio, bench reward, extra BC shards, KL/epochs/lr all CLI).
- 5,000-game high-band rollout corpus: `artifacts/highband_20260804/rollouts/`.
- Azure: `training/azure_guard.py` cost-capped VM ops. **Budget confirmed: $167+ credits available.** Prior search qualification: $0.74 / 1.5h. Full counterfactual scoring at scale ≈ 10–30× that — well within budget.
- Kaggle CLI authed. Daily elite dataset index in memory `ptcg-daily-top-episodes-dataset-index`.

## 8. Open questions — answer before codex starts (grouped)

**A. Time budget / engine (blocking for any search idea):**
1. What is the real per-move wall-clock budget on the live ladder? Replays show `actTimeout=0`, `runTimeout=2000`, `remainingOverageTime=600` (a 600s pool per game?). Confirm the exact rule — it decides whether *any* inference-time search is even possible.
2. Has anyone measured the search teacher's per-decision latency? Qualification measured throughput, not per-move ms. Need this to rule inference-time search in or out.

**B. Deck knowledge (blocking for search targeting):**
3. Do we have clean, current decklists for **Raging Bolt** and **top-team Alakazam** variants to use as search-teacher opponents? Raging Bolt is our worst 850+ matchup but only n=39 total.
4. How reliable is our live deck-classifier (`classify_deck`)? If good, a deck-inference front-end could unlock inference-time search as the actual agent — high-risk, high-reward. Worth prototyping?

**C. Distillation scope (priority + strictness ANSWERED — decisions 2 & 4; still open below):**
5. Advantage margin threshold for AFBC filtering — start strict (only clearly-better actions) or tune it? Strict = fewer, cleaner targets. *Recommend strict first pass, loosen if the shard is too small.*
6. For "all three parallel," do we train one combined shard/model, or three separately-gated candidates we then pick between? (Affects Azure spend and gate bookkeeping.)

**D. Slot / snapshot timing (best-of-2; both slots trained — decision 3):**
7. Exact competition close time (UTC)? The final-resubmit timing (§6) depends on it.
8. Any submission-count / daily-submission limit remaining that constrains resubmits?

## 9. Sequencing (per locked decisions §0)

- **Days 0–1:** answer §8.A/B/C/D blockers. Measure search-teacher per-move latency (§8.A.2, gates the small inference-search prototype). Pull fresh elite datasets; build disagreement-state sets for **all three targets in parallel** (mirror, Alakazam/RagingBolt, Lucario). Source/build Raging Bolt + top Alakazam opponent decklists (§8.B.3).
- **Days 1–5:** run counterfactual scoring across all three sources; assemble AFBC shard with a strict advantage margin (§8.C.5); targeted BC refresh with d842 rehearsal. Gate per decision 4 (mirror hard-floor ≥ anchor both seats; small regressions on easy matchups allowed if net rises; zero errors).
- **Days 5–8:** ship the candidate(s) to **both trained slots** if gates pass. Small side prototype only: inference-time search-as-agent, *if* §8.A latency allows — do not let it consume the main track.
- **Days 8–10:** freeze training. Time the final resubmit of each slot so its high-K window overlaps close (§6, §8.D.7); pick the best-of-2 snapshot at close.

---

### Sources
- Advantage-Filtered BC: https://arxiv.org/abs/2110.04698 · overview https://www.emergentmind.com/topics/filtered-behavior-cloning
- Expert Iteration / Student of Games: https://www.researchgate.net/publication/375669946
- KataGo (playout cap randomization, policy target pruning — efficient self-play): https://github.com/lightvector/KataGo/blob/master/docs/KataGoMethods.md · https://arxiv.org/pdf/1902.10565
- Targeted Search Control in AlphaZero: https://arxiv.org/pdf/2302.12359
- Regularized policy optimization for two-player games: https://arxiv.org/pdf/2602.10894
- Inference-time search budgets / real-time MCTS: https://arxiv.org/html/2606.26463
- Competition: https://www.kaggle.com/competitions/pokemon-tcg-ai-battle
