# Dipplin strength and held-out evaluation

> Final verdict: `KEEP_S1`

## Executive decision

This sprint asked whether one measured, opponent-agnostic correction could make
Dipplin a stronger **general** pilot, with particular emphasis on actual-second
play. The immutable S1 package remains the incumbent and the shared S2 code
remains default-off. S2 passed the small Stage 1 screen but failed the
predeclared 300-game-per-opponent actual-second gate: 531/1,200 (44.25%) for
S2 versus 536/1,200 (44.67%) for S1. The sequential contract therefore killed
the candidate and left Stages 3–6, including the sealed holdout, unopened.

No package was uploaded to Kaggle and no neural or reinforcement-learning
project was started.

## Provenance and evidence contract

| Item | Identity |
|---|---|
| Starting repository SHA | `a73f2fbf31494ebd97bc2e9357600388fe0805d5` |
| Incumbent S1 source/selection SHA | `a73f2fbf31494ebd97bc2e9357600388fe0805d5` |
| Incumbent | D1 bounded completed-turn search + `CONTINUITY_PROOF` + S1 `SECOND_OPENING_V2` |
| S1 archive SHA-256 | `ec74efe096473c58a2057cabfee93bf337bc18848c202a6e3d36bcba802db171` |
| S1 manifest SHA-256 | `4071c03a020446436b8d33e1951fdaf5229ae4ab760a8283dc7d6f323e02f92c` |
| S1 extracted tree SHA-256 | `940654489ea1f286982226f1f0cba4dd7340378b997a3f88ab6915c5d67f6c98` |
| S1 runtime-source tree SHA-256 | `d5aaefab29b5850b298810c21dc628880822381c05bdbad5ecea1716bcef4241` |
| Exact deck SHA-256 | `269bc5808a0db862c7afe8f2daaa3d0b3b6e3c68bd651dd515d14f9d85392326` |

The strength hierarchy was enforced throughout:

1. Exact A2, d842, Alakazam 2.4a/2.7, and same-deck games are strength evidence.
2. Fresh frozen expert replays are generalization evidence.
3. Public-board mechanics fixtures are correctness evidence.
4. Weak behavior clones are coverage-only and their win rates are excluded.

Native engine randomness is independent. Reused schedule seeds are not paired
games, and all game-arm differences use unpaired intervals. Historical S1
screens evaluated the stale `82ff4920...` extracted tree; they remain context
only. Every headline S1 result below is exact to the immutable `94065448...`
archive tree.

## Incumbent S1 baseline

### Current-tree strong anchors

Each cell contains 100 forced-order games.

| Opponent | Actual first | Actual second | Order-balanced |
|---|---:|---:|---:|
| A2 | 50/100 (50%) | 51/100 (51%) | 50.5% |
| d842 | 60/100 (60%) | 48/100 (48%) | 54.0% |
| Alakazam 2.4a | 59/100 (59%) | 33/100 (33%) | 46.0% |
| Alakazam 2.7 | 48/100 (48%) | 39/100 (39%) | 43.5% |
| **Macro / pooled** | **217/400 (54.25%)** | **171/400 (42.75%)** | **48.50%** |

The first-order Wilson 95% interval is 49.35–59.07%; the second-order interval
is 37.99–47.64%. `robust_anchor = min(first, second) = 42.75%`. One A2-first
game drew; all failure, policy-error, illegal-action, and unknown-context
counters were zero.

### Exact S1-versus-S1 initiative split

Two fresh safe extractions of the same S1 archive played 500 games per forced
order, crossing physical seats 250/250 in each arm.

| Hero order | Wins | Win rate | Wilson 95% | Seat 0 / seat 1 |
|---|---:|---:|---:|---:|
| Actual first | 302/500 | 60.4% | 56.05–64.59% | 152/250 / 150/250 |
| Actual second | 197/500 | 39.4% | 35.21–43.75% | 99/250 / 98/250 |

The measured initiative split is 21.0 percentage points; the independent
Newcombe interval is approximately 14.85–26.92pp. Both arms had zero failed
games, policy errors, or illegal actions and retained the same archive/tree
hashes. This is strong evidence that much of the second-player disadvantage is
structural, but it does not establish that every remaining second-player defect
is intrinsic.

Artifacts:

- `artifacts/general_strength/s1_mirror/s1_vs_s1_first_500.json`, SHA-256
  `c1dd38044323376cf090c95e834718b029af323a48e815a24f74455c2d3fc286`.
- `artifacts/general_strength/s1_mirror/s1_vs_s1_second_500.json`, SHA-256
  `5ef530f3bec98947d09700ed818c572fd0347b6f1a91f8b329ae224540447e6d`.

## Actual-second causal buckets

The first retained 1,200-game S1 corpus contained only shard aggregates, so it
could not support honest bucket-by-outcome reconstruction. A separate
current-archive refresh traced 400 games with public-information-only,
action-inert instrumentation. All 400 rows were eligible; there were no
duplicate, incomplete, wrong-order, error, or unknown-bucket exclusions.

| Opening Active | Games | Wins | First productive attack¹ | Never attacked | First Festival double¹ | Never doubled | Productive attacks | Dead turns | Trapped turns |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Volbeat, Quick Sign legal | 133 | 51.88% | 2.23 | 0 (0%) | 2.40 | 7 (5.26%) | 6.22 | 1.23 | 0.98 |
| Volbeat, Quick Sign unavailable | 7 | 14.29% | 3.17 | 1 (14.29%) | 3.60 | 2 (28.57%) | 4.14 | 2.86 | 2.71 |
| Applin 42 | 119 | 42.02% | 2.21 | 8 (6.72%) | 2.37 | 17 (14.29%) | 5.70 | 1.25 | 0.86 |
| Applin 92 | 30 | 23.33% | 2.13 | 7 (23.33%) | 2.27 | 8 (26.67%) | 4.03 | 1.47 | 0.73 |
| Grookey | 100 | 41.00% | 2.67 | 10 (10%) | 2.75 | 13 (13%) | 5.60 | 1.86 | 1.22 |
| Shaymin | 11 | 27.27% | 2.20 | 1 (9.09%) | 2.40 | 1 (9.09%) | 6.00 | 1.27 | 1.00 |

¹ Mean own-turn number conditional on the event occurring; the adjacent
columns retain the censored games.

The outcome-independent visible-tempo ranking placed Grookey first because it
was common and had delayed attacks/dead turns relative to the Quick Sign
reference. That ranking was observational, not causal. A 5,000-opening setup
audit then found Grookey selected 1,271 times but only 119/5,000 openings
(2.38%) where Volbeat was also selectable; every one of those 119 lacked a
visible known Quick Sign Energy path. The tempting blanket “prefer Volbeat”
rule was therefore falsified rather than implemented.

The table is abbreviated; the artifact retains outcome splits, turn-one and
first-attack boards, and missed prerequisites. In the highest-ranked Grookey
bucket, wins versus losses averaged 7.98 versus 3.95 productive attacks, 0.80
versus 2.59 dead turns, and 0.56 versus 1.68 trapped turns; ten losses never
attacked. Its missed-prerequisite event counts were replacement 172, Dipplin
130, Festival 87, Thwackey 61, retreat/promotion 37, and Energy 17. These are
descriptive associations, not estimates of the effect of changing setup play.

Artifacts:

- `artifacts/general_strength/s1_buckets/second_bucket_analysis_400.json`,
  SHA-256 `cf52262d2acf02108fe956de0ce2dc5fcdca7b91b218d0172a28b3320be8d8a8`.
- `artifacts/general_strength/s1_buckets/setup_choice_audit_5000.json`,
  SHA-256 `83aa304aa75d3de59f81083993591d3069020ccb7b57ce5f900a81787e667244`.

## Fresh expert replay dataset

The old 88-episode PP Kawada corpus is explicitly contaminated DEV data. It was
used only to debug exact-state replay reconstruction and evaluator failure
modes. Three separately cached fresh episodes were also used only as DEV
smokes.

The new reward-blind frozen inventory contains seven hero submissions from five
pilots:

| Split | Episodes | Order | Expert outcome | Status |
|---|---:|---:|---:|---|
| VALIDATION | 50 | 31 first / 19 second | 25 wins / 25 losses | Evaluated once with S1 |
| FINAL_HOLDOUT | 30 | 19 first / 11 second | 15 wins / 15 losses | Action-level result `NOT_RUN` |

Validation spans 12 opponent archetypes and 30/50 episodes are neither Grim nor
Alakazam. Exact frozen manifest file/payload SHA-256 pairs are:

- validation: `f147f14c670223b22bf9cba28f6ea166a4bbb5153c0efea941c61f39ff2bb163`
  / `d6cc5a7339dcc466546e68c8ea29301c150966be1f287adc00003bd86716c4c1`;
- final holdout: `5f7a3faa6d5ba37ca4c0a5725f99ba2db9e362498712a36681b77cbb6657430d`
  / `708fe9e318434d1eaee6ab65661c23323ab9f1ceaa4dc5337bfc5ac22b39298d`.

The acquisition/freeze tool fails closed on seat, submission, team, deck,
order, result, split-overlap, or manifest-digest mismatches. The sealed split
has not been parsed for action-level evaluation and remains reusable only under
its one-shot qualification contract.

## Counterfactual expert-regret evaluator

The evaluator measures completed-turn regret, not imitation accuracy. It first
reconstructs each episode chronologically, generating proposals while
committing the recorded expert actions to the candidate's shadow memory; only
after that pass does it strategically sample prompts. Equivalent duplicate-card
choices are collapsed while mechanically distinct Applin 42/92 choices remain
distinct. Sampled native-search proposals are repeated from the exact
pre-prompt memory and search-counter checkpoint; instability is
`UNCERTIFIABLE`.

For a stable disagreement, expert and candidate branches start as independent
fresh roots from the same validated exact hidden replay state. Both use the
same frozen D0 continuation only through the hero turn or terminal state, and
repeat agreement is required. RNG or hidden-deck work, public-state/actor
misalignment, or unsafe continuation fails closed. No hidden field is shown to
the candidate.

The comparison covers terminal result, prizes, productive/Festival attacks,
central and first-hit KOs, current/replacement readiness, Festival, usable
Thwackey, Do the Wave output, retained core/tutor resources, and fragile Bench
exposure. Every row is classified as `EQUIVALENT`, `AGENT_DOMINATES`,
`EXPERT_DOMINATES`, `INCOMPARABLE`, or `UNCERTIFIABLE`. Expert outcomes
componentwise at least as good everywhere and strictly better somewhere yield
`EXPERT_DOMINATES`; the reverse yields `AGENT_DOMINATES`; conflicting
advantages yield `INCOMPARABLE`. Statistical intervals bootstrap episodes,
not correlated decisions.

### S1 frozen-validation result

All 50 episodes and all 1,145 frozen record IDs were covered with zero proposal
errors.

| Classification | Decisions | Episode-weighted rate | Episode bootstrap 95% |
|---|---:|---:|---:|
| Equivalent | 658 | 56.93% | 53.75–60.05% |
| Uncertifiable | 444 | 39.49% | 36.37–42.74% |
| Expert dominates | 17 | 1.42% | 0.67–2.25% |
| Incomparable | 16 | 1.33% | 0.67–2.17% |
| Agent dominates | 10 | 0.83% | 0.33–1.42% |

The high uncertifiable rate is a deliberate consequence of the hidden/RNG
gate and limits power. The artifact is
`artifacts/general_strength/replay/validation_regret_s1.json`, SHA-256
`9f1205b2b282b2da37bc284054f51a3ebce7214507da7da4fa75309d5870e87d`.

## One measured S2 hypothesis

Frozen validation contained a repeated premature-attack cluster: S1 sometimes
selected immediate Do the Wave before one deterministic setup action, even
though exact completed-turn comparison preserved the tactical outcome and
strictly improved the resulting attack output. The broad cluster covered nine
decisions/eight episodes. The strict proof-compatible subset covered five
decisions/four episodes, balanced two actual-first and two actual-second; four
decisions/three episodes directly used the exact S1 deck.

S2 implements exactly one mechanism. Before baseline Do the Wave it may admit
one deterministic Brave Bangle attachment to the Active Dipplin or one exact-
deck Basic play only when **every** compatible public-belief world:

- completes safely without RNG/hidden-deck touch;
- preserves the first five tactical metrics exactly;
- is componentwise non-regressive across all 13 comparison fields;
- strictly raises end-of-turn Do the Wave output; and
- identifies the same unique winner.

Evolution, Energy, Festival, promotion/switch, generic setup-before-attack, and
opponent-identity rules are excluded. The source implementation is gated by
`PTCG_DIPPLIN_S2=1` and defaults off; only the dedicated candidate package
forces it on.

| S2 identity | Identity / digest |
|---|---|
| Implementation source commit | `9d365ccdaae90379e0e9d8ce05a17a5e1a587c74` |
| Hypothesis | `aa2c5a070052ed9b706c20de548b5ad38ca48949156411fb62ff9a5dd39d4f87` |
| Archive | `813fab9efd432738856e7d7b784809c7b0c5aef51b3c677d7205f203490d1510` |
| Manifest | `4801239bc3d328909bbd4e5461b84b140dd8931e3b581636ecbc662a97bad1bc` |
| Extracted tree | `c822bb76fa40a138a6bb07fcfd6e6cc58f8ade0dd65c49425bc703f3170da922` |
| Runtime-source tree | `b4290fff9b4fa3374f1bc14b7eefd6e9309dc13f3dcbebb2d9e4ea167650189f` |

The package double-build was deterministic, sterile import passed, its deck is
unchanged, and it was not uploaded.

## Staged S2 evaluation

### Stage 0 — mechanics and default-off behavior

On 2026-08-13, the canonical public-board mechanics suite passed 15/15 with
zero failures, errors, or skips:

```text
.venv/bin/pytest -q tests/test_dipplin_meta_mechanics.py \
  --junitxml=artifacts/general_strength/mechanics/dipplin_meta_mechanics.junit.xml
```

The JUnit artifact SHA-256 is
`23fea3d6466a3bb0ff36a5d181c720d3b26d62a27bbbbcfaf36d3ba49770e0fe`;
the test-file SHA-256 is
`a3f15a089520857bfe8ee29af98b10b47c0bbcea4a394bca0d33bacf2936919d`.
The focused S2 search and packaging suites separately passed 28/28. These are
part of a broader final dashboard/replay/stage/qualification/search/package/
meta-mechanics regression set that passed 172/172. These are working-tree tests
plus sterile package-build checks, not a claim that every test executed from
the release archive on every target platform.

The final fail-closed dashboard spec is
`data/dipplin_general_strength/s2_dashboard_spec.json` (SHA-256
`2d11d5f1caf8df433b4b3ddf19a2e35795dee6e0f2608d92ea0430c367ef31f1`).
Its portable JSON and Markdown outputs are
`artifacts/general_strength/final/s2_dashboard.json` (SHA-256
`c65e26bec5ca857eeb00870f3161bfdfa05a1c83a4f08b589a6afe4e9c7c2f0f`)
and `artifacts/general_strength/final/s2_dashboard.md` (SHA-256
`627497b6e8f616d866be65bcbd9a5e143d9159efa17b5a1a97b654833db052a5`).

### Stage 1 — 100 actual-second games per strong anchor

| Opponent | S1 | S2 | Delta |
|---|---:|---:|---:|
| A2 | 51/100 | 51/100 | 0pp |
| d842 | 48/100 | 54/100 | +6pp |
| Alakazam 2.4a | 33/100 | 49/100 | +16pp |
| Alakazam 2.7 | 39/100 | 39/100 | 0pp |
| **Pooled** | **171/400 (42.75%)** | **193/400 (48.25%)** | **+5.50pp** |

The unpaired Newcombe interval for the pooled difference is -1.395 to
+12.322pp. `STRONG` here means the candidate crossed the predeclared +5pp
screening threshold; it is not a claim of statistically conclusive
superiority. There were zero failures, policy errors, illegal actions, fatal
telemetry, or unknown contexts. The proof performed 15,399 checks, admitted 64
lines, and produced 50 overrides in 48/400 games.

Across 20,613 candidate decisions, weighted mean latency was 127.23ms; the
worst-cell p95/p99 were 653.99/659.43ms and the maximum was 785.68ms. Forty-
three D1 engine/node-budget abstentions and 903 D1 timeouts safely fell back to
the deterministic baseline and are reported separately from policy failures.

### Stage 2 — 300 actual-second games per strong anchor

| Opponent | S1 (Wilson 95%) | S2 (Wilson 95%) | Delta | Unpaired Newcombe 95% |
|---|---:|---:|---:|---:|
| A2 | 149/300, 49.67% (44.05–55.29%) | 143/300, 47.67% (42.08–53.31%) | -2.00pp | -9.93 to +5.96pp |
| d842 | 160/300, 53.33% (47.68–58.90%) | 140/300, 46.67% (41.10–52.32%) | -6.67pp | -14.54 to +1.33pp |
| Alakazam 2.4a | 106/300, 35.33% (30.14–40.90%) | 122/300, 40.67% (35.26–46.31%) | +5.33pp | -2.42 to +13.00pp |
| Alakazam 2.7 | 121/300, 40.33% (34.94–45.97%) | 126/300, 42.00% (36.55–47.65%) | +1.67pp | -6.18 to +9.48pp |
| **Pooled / macro** | **536/1,200, 44.67% (41.88–47.49%)** | **531/1,200, 44.25% (41.46–47.07%)** | **-0.42pp** | **-4.39 to +3.55pp** |

Pooled and macro rates coincide here because all four cells contain 300 games.
The candidate missed both the predeclared 50% pooled/macro floor and the
non-negative pooled-delta requirement. No opponent cell crossed the -10pp
catastrophic-regression boundary, but that could not rescue the failed primary
gates. The difference interval spans zero: this is a frozen-target and
non-negative-point-gate failure, not statistically clear evidence that S2 is
worse. The Stage 2 verdict was therefore `KILL`.

All 2,400 arm-games completed with zero failures, policy errors, illegal
actions, unknown contexts, or fatal operational telemetry. Across the S2 arm,
the new proof performed 44,604 checks, admitted 257 lines, and produced 204
overrides in 181/1,200 games. Candidate latency covered 62,229 decisions, with
a 140.87ms weighted mean, 654.83/660.63ms worst-cell p95/p99, and 860.58ms
maximum. D1 search safely fell back on 102 engine/node-budget errors and 4,027
timeouts; those abstentions are not policy failures.

Frozen rejected-evaluation artifacts:

- pre-result gate freeze commit
  `2d590f47986aada043d2a1c6e5d8287407eaa2c3` (then-spec SHA-256
  `7e95fd1e722b73fcc54814dbf661afc2b483e2d490c95b3d1bace44aa0f088db`);
- `data/dipplin_general_strength/s2_stage_evaluation_spec.json`, SHA-256
  `47d9326c637387f59bf259b608efb1601ca3d3285b53d2a7096dc369cddc6f3b`;
- raw game evaluator SHA-256
  `01e450c3425b86c586b6b51e50a28f58ae482545382e4ffa6715e3f21a27d114`;
- portable report verifier/reaggregator
  `scripts/evaluate_dipplin_s2_stages.py`, SHA-256
  `bdc73fbc2376cd4b587ed7ad7a9585edb5cd7e3626c01b83fc5a153e2aac8416`;
- `artifacts/general_strength/s2_stage2/stage2_evaluation.json`, SHA-256
  `82f33fd41aadea811bff43d5365b7af8fc622c30b2267336ade90a7cb4b9f04f`.

### Stages 3–6

The sequential gate made every later stage
`INADMISSIBLE_PRECEDING_STAGE_KILL`. No S2 actual-first screen, S2-versus-S1
same-deck evaluation, S2 replay-regret validation, S2 Linux certification,
qualification receipt, or final-holdout evaluation was run. In particular,
the 30-episode sealed holdout remains uninspected at action level and no
one-shot receipt was consumed.

Before any future one-shot Stage 6 result, the dashboard now freezes an
additional promotion veto: zero candidate proposal/policy/action-instability
errors, at most 50% combined uncertifiable/incomparable decisions, and an
expert-dominates episode rate no greater than the agent-dominates episode
rate. This contract is dormant and reported `NOT_APPLICABLE` for the present
Stage 2 `KILL`; it cannot be relaxed after seeing the sealed aggregate. It is
a conservative pre-look promotion-eligibility veto, not a strength estimate
or an assertion of exact expert imitation.

## Operational coverage

Across the eight current-tree S1 anchor cells, 76,154 decisions had a
count-weighted mean latency of 131.11ms, a maximum-of-cell p95/p99 ceiling of
655.48/674.72ms, and a maximum of 899.21ms. Quantiles were not pooled across
raw decisions. All anchor failure, policy-error, illegal-action, and unknown-
context counters were zero.

The S1 archive completed one actual-first and one actual-second game under
Linux x86_64 using packaged `libcg.so` SHA-256
`d16244a3157fc55c3314f08dcc7c5179168697d78c105b95c7debd556b764bb7`.
Both games completed with 112 total decisions, zero failures, policy errors,
illegal actions, or archive mutations. The 0/2 game outcome is not strength
evidence. Certification artifact SHA-256 is
`3a97fa74dd67727dd1c0e5ad03eee0ea39f7393b437426c4c1d6a79615082446`.

S2 Linux certification is `NOT_RUN` because S2 did not qualify.

No weak-clone game was run in this sprint. Lucario, Crustle/Kangaskhan,
Ogerpon, Bellibolt, Starmie/Froslass, Dragapult, Cynthia's Garchomp, and
Lopunny are therefore `NOT_RUN` (legacy artifact availability only); their
current-sprint failure, policy-error, illegal-action, unknown-context, and
mechanic-exposure counts are `NOT_MEASURABLE`. Every clone win rate remains
**CEILINGED — EXCLUDED FROM STRENGTH** and none enters an anchor, macro, or
promotion decision.

## Generalization limitations

- Exact live-strength opponents remain limited to two Grimmsnarl and two
  Alakazam packages; the fresh replay evaluator broadens state coverage but is
  not a full-game opponent.
- The 21pp same-deck initiative split is robust evidence of structural order
  advantage, not proof of an immutable ceiling.
- The bucket ranking is observational and its apparent Grookey mechanism was
  not reproduced as a broad actionable setup error.
- Replay decisions within an episode are correlated; only episode-level rates
  and bootstraps are inferential.
- Approximately 39.5% of S1 validation decisions are uncertifiable because the
  evaluator refuses unsafe RNG/hidden-deck continuations.
- Stage 1's positive S2 screen was noisy and its difference interval included
  zero; the larger Stage 2 result reversed the point estimate.
- The final holdout has intentionally not been evaluated. `NOT_RUN` must not be
  interpreted as a zero failure or regret rate.

## Final verdict

`KEEP_S1`

S2 was a narrowly causal experiment with zero observed mechanical or
operational regressions in the completed tests and game screens, but it did not
clear the serious actual-second strength gate. The immutable S1 archive remains
the selected general pilot. S2 stays default-off and is not promoted or
uploaded.
