# Dipplin expert-policy audit

Final verdict: **KEEP_S1_NO_CLEAR_FIX**

Starting and current policy SHA: `a2ad27fec34e0e38e177a650b498cf1e6ea52e4a`.
The current Dipplin policy is S1 (`SECOND_OPENING_V2` plus D1 search). This
sprint did not change policy code, did not create an S2 flag, did not train a
model, and did not upload anything to Kaggle.

## Executive answer

The fresh data does not isolate a repeated action between “engine online” and
“winning the Prize race” that S1 consistently misses. Strong pilots usually
reach the first attack with a wider board and establish the strict engine more
reliably than the cached S1-vs-Grim sample, but this is not the same as a
certified post-setup policy defect. In 102 fresh DEV+VALIDATION episodes, the
completed-turn evaluator found expert dominance in 16 episodes (15.7%), spread
across energy, attack/develop, Bench, and replacement decisions. The public
Prize-route evaluator found **zero positive S1 Prize-regret rows in 86
certifiable S1 branches**. Boom Boom Groove target differences produced no
certified expert-dominant branch.

The same conclusion survived the aggregate-only SEALED pass: three of 18
episodes contained any expert-dominant completed-turn branch, but none of the
10 certifiable S1 Prize-route branches had positive Prize regret. That evidence
does not justify a new opponent-agnostic S2 rule.

## Data provenance and contamination boundary

The manifest is `artifacts/dipplin_expert_fresh/manifest.json`, schema
`dipplin-expert-fresh-manifest-v1`. Replays were selected from bounded,
explicit submission histories and downloaded only for this local audit.

| Source | Submission | List relation | History | Fresh selected |
|---|---:|---|---:|---:|
| PP kawada | 55408594 | exact PP kawada 60 | 106 | 18 |
| BluesLeeTW | 55404784 | similar Thwackey/Dipplin | 93 | 51 |
| 西松大祐 | 55430091 | similar Thwackey/Dipplin | 62 | 51 |

The exact deck multiset hash is
`e8e9908e4943584bcbf4d54c91feda6ccfd5a39c0a0cf7d30e5db4a5de7ebd7b`.
The selected replay timestamps range from 2026-08-10 13:08:07Z through
2026-08-12 08:51:48Z. Opponent initial ratings were present for all 120 games
(range 228.38–1186.47; mean 915.80); ranks were unavailable and remain null.

The contamination contract was enforced before selection:

- 1,241 known local or prior-manifest episode IDs were excluded;
- the previously used 88 PP kawada replay files were excluded;
- the prior frozen 80-episode corpus was not reused;
- selected overlap with known episode IDs was zero.

The 120 fresh episodes were split episode-wise as DEV 72, VALIDATION 30, and
SEALED 18. The deterministic marginal stratifier balances actual order,
opening Active, opponent family, expert result, and exact/similar list status.
The resulting order distribution is 37/35 first/second in DEV, 16/14 in
VALIDATION, and 10/8 in SEALED. SEALED emitted aggregate reports only; no
individual SEALED decision or failure row was written or inspected.

## Coverage

The full fresh corpus contains 63 actual-first and 57 actual-second games,
77 expert wins and 43 losses. Opening coverage is 40 Grookey, 60 Applin 92,
five Applin 42, four Volbeat with Quick Sign initially legal, two Volbeat with
it initially unavailable, and nine other openings.

| Opponent family | Episodes |
|---|---:|
| Grimmsnarl/Marnie | 35 |
| Alakazam/Dudunsparce | 29 |
| Other | 13 |
| Mega Lopunny ex | 11 |
| Kangaskhan/Crustle | 10 |
| Dragapult ex | 8 |
| Cynthia's Garchomp ex | 5 |
| Mega Lucario variants | 4 |
| Ogerpon | 3 |
| Dipplin mirror, Bellibolt | 2 |

The opponent-deck label is single-Prize for six games, two-Prize ex/mixed for
86, and three-Prize Mega/mixed for 28. The exact-list subset is only 18/120;
modern similar-list results are macro-strategy evidence, not direct action
imitation for cards absent from the PP kawada 60.

## Evaluation contract

The four evaluators are:

- `scripts/evaluate_dipplin_opening_pressure.py`
- `scripts/evaluate_dipplin_engine_conversion.py`
- `scripts/evaluate_dipplin_expert_regret.py`
- `scripts/evaluate_dipplin_prize_regret.py`

Opening and engine measurements use only public hero observations and the
recorded action aligned at replay step `t + 1`. `ENGINE_ONLINE` means Dipplin
Active, Do the Wave legal, Festival Grounds active, and an established
Thwackey on the public board. Completed-turn regret uses an identical safely
reconstructed state for both branches and fails closed on ambiguity or hidden
deck/RNG dependence. Prize regret considers relevant deterministic public
roots through the hero-turn boundary, not the entire game. The statistical
unit for rates is the episode.

Cached local comparison is limited to 100 forced-second S1 games against the
actual Grimmsnarl agent `d842`, per the user's simulation constraint. No new
agent-vs-agent screen was needed. That trace lacks per-turn Prize timing, so
Prize-rate fields are intentionally null rather than imputed. The nine rated
games from submission 55483388 are replay observations, not a new simulation.

## Opening and time to pressure

| Sample | N | First Do the Wave mean / median | No Do the Wave | Bench at first attack | Festival | Ready replacement | Diagnostic wins |
|---|---:|---:|---:|---:|---:|---:|---:|
| Fresh expert DEV+VAL | 102 | 2.34 / 2 | 1.0% | 4.48 | 87.1% | 11.9% | 65/102 |
| Exact PP list within DEV+VAL | 16 | 2.73 / 2 | 6.3% | 4.47 | 93.3% | 26.7% | 7/16 |
| Similar modern lists | 86 | 2.27 / 2 | 0% | 4.48 | 86.0% | 9.3% | 58/86 |
| Live 55483388 | 9 | 2.11 / 2 | 0% | 3.67 | 88.9% | 11.1% | 4/9 |
| Cached S1 vs Grim, forced second | 100 | 2.27 / 2 | 9.0% | 3.54 | 80.2% | 17.6% | 48/100 |

S1 does not show a broad “wait too long before attacking” defect: medians are
turn 2, and the live sample attacks earlier than the experts. The clearer
descriptive gap is board width and reliability. The local S1 trace attacks
with roughly one fewer Benched Pokémon and fails to produce Do the Wave in
9/100 games. Because that local sample is forced-second and Grim-only, it
cannot establish an opponent-agnostic S2 by itself.

### Grookey Active

Fresh experts went 25/35 from Grookey Active, moved Grookey out of the Active
on mean own turn 1.29, and first attacked on mean turn 2.29 with 4.63 Benched
Pokémon. Only one evolved the Active Grookey before escape. Before the first Do
the Wave, recorded Grass attachments most often targeted Grookey (28), Dipplin
(25), or Applin 92 (16); this reflects route-specific retreat and attacker
banking, not one universal attachment rule.

The live policy moved Grookey out on mean turn 1.67, attacked on turn 2.33 with
only 3.0 Benched Pokémon, and went 0/3. The cached S1-vs-Grim Grookey bucket
attacked on turn 2.59, failed to attack in 4/21 games, and went 11/21. This is
a plausible recovery/reliability weakness. It is not a clean expert-action
rule: the only three exact-list fresh Grookey games averaged turn 3.33 and went
2/3, while most faster expert games used modern pivot cards absent from this
deck.

### Quick Sign

Quick Sign converted setup but did not guarantee wins. Fresh DEV+VALIDATION
had three initially legal Volbeat openings, used Quick Sign in all three,
attacked at mean turn 2.67, and won one. Live used it in all three legal
openings, attacked on turn 2, but won one and did not take its first Prize
until mean turn 4 among the two games that ever did. Cached S1-vs-Grim had
32 legal openings, used Quick Sign in 29, attacked at mean turn 2.09, and won
19. This supports the prompt's conclusion: setup conversion alone is not the
missing win condition.

## Engine-to-Prize conversion

| Sample | N | Engine-online episodes | First engine turn | First-turn Prize | First-hit KO | Prizes / engine turn | Zero-Prize engine turns | Ready replacement |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Fresh expert DEV+VAL | 102 | 94 (92.2%) | 2.52 | 56.4% | 54.3% | 0.422 | 62.6% | 10.6% |
| Exact PP list | 16 | 15 (93.8%) | 3.07 | 53.3% | 53.3% | 0.348 | 67.4% | 20.0% |
| Similar modern lists | 86 | 79 (91.9%) | 2.42 | 57.0% | 54.4% | 0.434 | 61.8% | 8.9% |
| Live 55483388 | 9 | 9 (100%) | 2.78 | 33.3% | 33.3% | 0.333 | 74.1% | 11.1% |
| Cached S1 vs Grim | 100 | 77 (77.0%) | 2.66 | unavailable | 54.5% | unavailable | unavailable | 19.5% |

The live nine-game signal is indeed conversion-shaped: it reaches the strict
engine in every game but takes a Prize on only 3/9 first engine turns. The
sample is too small for a rule, and the causal branch tests below do not locate
a repeated missed route. No sample produced a measured two-KO Festival window;
the archetype's value here more often came from a two-hit KO on one target or
later Prize pressure.

By opponent public Prize structure, fresh experts converted first engine turns
at 50.0% in four single-Prize games, 64.7% in 68 online two-Prize games, and
31.8% in 22 online three-Prize games. Prizes per engine turn were 0.625, 0.488,
and 0.255 respectively. The Mega result is a real difficulty signal, but not a
license for one generic modifier rule: only five of 604 tutor events occurred
where an available modifier changed the public projection to a first-hit KO.

## Boom Boom Groove targets

There were 604 recorded expert Groove targets in DEV+VALIDATION: 153 immediate
pressure cards (Festival, Boss, Bangle, or Belt), 136 board/replacement cards,
and 315 draw, recovery, or other cards. Festival (112), Night Stretcher (61),
Energy (60), Air Balloon (48), and Thwackey (43) were the most common targets.
Air Balloon and Secret Box are modern-list evidence only; this exact 60 cannot
copy those lines.

| Public context | Targets | Pressure | Board/continuity | Draw/recovery/other |
|---|---:|---:|---:|---:|
| No attack available | 138 | 47 | 45 | 46 |
| Attack available, no baseline KO | 134 | 40 | 17 | 77 |
| Baseline two-hit KO | 160 | 35 | 26 | 99 |
| Baseline first-hit KO | 172 | 31 | 48 | 93 |
| Replacement missing | 46 | 5 | 7 | 34 |
| Two or fewer Prizes remaining | 123 | 26 | 24 | 73 |

Experts therefore do not switch categorically from setup to immediate-pressure
tutoring merely because an attack is available. They frequently preserve draw
and recovery even with a KO route. More importantly, the regret evaluator saw
179 strategically important Groove decisions across 87 episodes: 39 were
semantically equivalent, 140 were uncertifiable due deck-search dependence,
and **zero** certified expert- or S1-dominant outcomes remained. A tutor-target
S2 would be speculation.

## Replacement readiness

At the first strict engine turn, fresh expert replacement readiness was 12.3%
in wins and 6.9% in losses; live was 25% in wins and 0% in losses. Cached S1 vs
Grim was 23.9% in wins and 12.9% in losses. Readiness is somewhat more common
in wins, not evidence of harmful overinvestment. Completed-turn regret found
one expert-dominant and one S1-dominant replacement-development episode among
101 exposed episodes. Prize regret found no current-Prize loss. The proposed
“continuity over current pressure” defect is falsified at the available
certification level.

## Expert completed-turn regret

| Decision family | Decisions | Episodes exposed | Expert-dominant decisions / episodes | S1-dominant decisions / episodes | Conclusion |
|---|---:|---:|---:|---:|---|
| Energy target | 328 | 102 | 5 / 4 | 4 / 4 | Balanced at episode level; often retained-resource only |
| Bangle | 41 | 33 | 2 / 2 | 0 / 0 | Sparse and threshold-specific |
| Attack now vs develop | 170 | 88 | 5 / 5 | 1 / 1 | Sparse; no matching Prize regret |
| Bench expansion | 259 | 88 | 4 / 4 | 1 / 1 | Sparse and threshold-specific |
| Replacement development | 433 | 101 | 1 / 1 | 1 / 1 | Balanced, not repeated |
| Boom Boom Groove target | 179 | 87 | 0 / 0 | 0 / 0 | Mostly uncertifiable deck search |
| Hilda vs Lillie | 183 | 91 | 0 / 0 | 0 / 0 | No certified defect |
| Retreat/promotion | 183 | 83 | 0 / 0 | 1 / 1 | No expert advantage |
| Recovery | 62 | 45 | 0 / 0 | 0 / 0 | No certified defect |

Overall: 1,989 decisions in 102 episodes; 1,177 equivalent, 17
expert-dominant, eight S1-dominant, 48 incomparable, and 739 uncertifiable.
Expert dominance occurred in 16 episodes (15.7%), with similar rates going
first (9/53) and second (7/49). It appeared across several archetypes rather
than identifying one matchup, but no single family supplied a repeated
Prize-causing mechanism.

## Deterministic public Prize-route regret

The evaluator found 359 meaningful DEV+VALIDATION MAIN states in 93 episodes,
written as 718 expert/S1 actor rows. The best public route guaranteed zero
Prizes in 210 states, one Prize in 117, and two in 32. Attack now was the best
root in 291 states; Bangle in 21, Energy in 18, evolve Dipplin in 16, Festival
in 10, Black Belt in two, and Bench expansion in one.

| Actor | Rows | Certifiable | Positive-regret rows | Mean certified regret |
|---|---:|---:|---:|---:|
| Expert | 359 | 78 | 0 | 0.0 |
| Current S1 | 359 | 86 | 0 | 0.0 |
| Combined | 718 | 164 | 0 | 0.0 |

This does not prove every policy route optimal. It proves that the requested
deterministic public search did not reproduce a missed Prize among branches it
could certify. Uncertifiable hidden/RNG/deck-search states were not guessed.

## SEALED aggregate

The candidate was frozen as unchanged S1 before the intended aggregate-only
SEALED pass. Across 18 episodes, first Do the Wave was observed in 17 at mean
turn 2.0; the strict engine appeared in 16 at mean turn 2.31. First engine-turn
Prize rate was 37.5%, with 0.404 Prizes per engine turn. Completed-turn regret
found expert dominance in 3/18 episodes and S1 dominance in 1/18. Prize-route
regret covered 62 meaningful states in 16 episodes; ten S1 and nine expert
branches were certifiable, with zero positive regret for either actor. No
individual SEALED row was emitted or inspected.

## Ranked remaining defects

| Rank | Candidate defect | Frequency/evidence | Causal loss | Confidence |
|---:|---|---|---|---|
| 1 | Engine reliability and board width from awkward openings | S1-vs-Grim: 77% engine-online and 3.54 Bench vs 92% and 4.48 for broad experts; Grookey no-attack 4/21 | Plausible lower damage/availability, but confounded by order, opponent, and modern cards | Medium-low |
| 2 | Energy allocation | Expert and S1 each dominate in 4/102 exposed episodes | Mostly retained attacker resources, not reproduced Prize loss | Low |
| 3 | Attack/develop threshold choice | Expert dominates in 5/88 exposed episodes | Output/resource gains, zero certified Prize regret | Low |
| 4 | Live engine-to-Prize conversion | Live first-turn Prize 3/9 vs expert 53/94 | Descriptive gap only; nine games and no repeated action family | Low |
| 5 | Tutor objective | 0 certified expert-dominant Groove outcomes | Hidden deck dependence prevents certainty; no positive evidence | Very low |
| 6 | Replacement overinvestment | One expert- and one S1-dominant episode; no Prize regret | Hypothesis contradicted by outcome splits | Very low |

## S2 decision

No S2 is proposed or implemented.

**FAILURE:** No single repeated failure cleared the causal bar.

**FREQUENCY:** Energy targeting had expert and S1 dominance in 4/102 episodes
each; attack/develop had expert dominance in 5/88 and S1 dominance in 1/88.

**EXPERT BEHAVIOR:** Context-dependent attachment, board-width, and recovery
choices; modern pilots also use unavailable pivot/compression cards.

**CURRENT S1 BEHAVIOR:** Usually attacks on the same turn clock and matches the
best certifiable current Prize route.

**CAUSAL REASON:** No proposed family produced positive deterministic S1 Prize
regret.

**PROPOSED FIX:** None. Preserve S1.

**WHY GENERAL:** A general fix cannot be claimed from matchup-confounded
descriptive gaps or rare resource-only branch differences.

**HOW TO FALSIFY:** Acquire more fresh exact-60 games, especially actual-second
Grookey/Volbeat openings and non-Grim opponents, then require repeated
episode-level expert dominance plus positive public Prize regret before a
single gated S2.

## Limitations

- Only 18 fresh episodes use the exact 60; most macro evidence uses similar
  modern lists with Air Balloon, Secret Box, or other absent cards.
- The nine live games are diagnostic, not statistically stable.
- Cached local S1 traces are forced-second Grim games and lack per-turn Prize
  timing; their win rate is not a cross-archetype strength estimate.
- Completed-turn branching fails closed: 739/1,989 DEV+VALIDATION decisions
  were uncertifiable, especially deck-search choices.
- Prize regret is a bounded relevant-root search, not an exhaustive game or
  belief-state solver.
- Opponent family and prize-structure counts are uneven; single-Prize coverage
  is especially small.

These limitations favor restraint. The evidence answers the key question by
rejecting the tempting simple stories—generic attack delay, tutor greed, and
replacement bias—rather than inventing a policy change the data cannot support.
