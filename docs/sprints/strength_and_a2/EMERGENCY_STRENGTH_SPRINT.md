# Emergency strength sprint

## Result

**STRONGER THAN A2 - PACKAGE THIS.** The selected candidate is
`empirical_router_v2_broad`. It preserves authentic A2 exactly when moving
first and makes seven outcome-selected A2/temporal policy substitutions when
moving second. No rule searches hidden information, no runtime search is
enabled, and all invalid/error paths fail closed to A2.

The archive is:

`artifacts/elite_policy_candidates/empirical_router_v2_broad/package/empirical_policy_router.tar.gz`

Archive SHA-256:
`CC567C0AD1787C39D1186075F85041DAFB9EC50D664F478C800682032C5EDC6D`

This is the first candidate in the sprint with a repeatable, statistically
positive direct-A2 result. It is not honest to promise a particular public
rating: no local test has a calibrated mapping from paired win-rate lift to a
Kaggle score, and the population expansion is positive but inconclusive. The
evidence does support replacing A2 with this package for the next submission.
Update, 2026-08-11: the user subsequently authorized an upload. The exact
archive above was accepted as Kaggle submission **55434964** with description
`empirical-router-v2-broad-a2-second-20260811`; its local SHA-256 remained the
recorded value. Kaggle reported `COMPLETE`. The submission ledger is stored at
`artifacts/elite_policy_candidates/empirical_router_v2_broad/submission_ledger.json`.
At 2026-08-11 15:01:25.912 UTC its still-early public rating was **587.7**, while
the active A2 reship was **822.5**. This is strong evidence that the local
outcome-selected population was not ladder-predictive despite being internally
deterministic; the empirical router should not replace A2 on present evidence.

## Why strategic v2 performed badly

V2 was firing. It changed 617/10,000 audited replay decisions (6.17%) and
scored 213/360 versus A2's 244/360 in the contemporaneous population screen,
a -8.61 point gap. Its failure was caused by operational logic and concrete
implementation mistakes, not dormant code:

| Mechanism | What went wrong |
|---|---|
| Support-Energy prohibition | A speculative preference became a hard ban. It caused 185/617 replay changes, including 168 proactive Darkness attachments to Munkidori, which needs that Energy. |
| Build/count controller | Every extra Impidimp, Poffin target, or Punk Up Energy was treated as compulsory. It overrode 1,182/2,365 gameplay decisions and erased A2's learned sequencing. |
| Crustle pressure | Broad Crustle pressure was restored despite the brief excluding it. It occupied 1,271/3,422 Crustle decisions. |
| Evolution denial | A visible pre-evolution plus Boss was enough; no verified current-turn KO or clock change was required. |
| Retreat logic | Attack deficit was used as a retreat-cost proxy, and the staged subgoal could terminate merely because the original Active became attack-ready. |
| Nested prompts | Targets could be hijacked even when A2, rather than the controller, initiated the parent action. |

The supposedly matchup-specific benefits mostly did not drive behavior:
damage conversion, one-Prize preservation, and spread management changed zero
audited decisions; Stadium denial changed seven. Generic compulsory rules
dominated instead.

V2.1 corrected those errors: it removed the Energy ban and broad Crustle rule,
disabled universal build/count control, required a verified KO for evolution
denial, tightened pressure/retreat gates, and stopped hijacking nested prompts.
It still scored only 277/600 against an unpaired A2 self-control of 322/600.
The remaining problem was the premise: brittle human preconditions threw away
too much of A2's latent turn-sequencing knowledge.

## Why the old benchmarks looked convincing

The old evaluator could detect v2's large regression, but it could not resolve
one-to-three-point improvements:

- the Windows engine used `std::random_device`, so supplied seeds did not
  reproduce shuffles, random selections, or coins;
- candidate and control were unpaired, often only 30 games per matchup, and
  candidates were repeatedly selected on the same noisy screens;
- the Alakazam screen forced `NO_SEARCH=1`, so it was not the claimed authentic
  search agent;
- opponent errors were not always fatal, provenance hashed the wrong platform
  engine, and first-index telemetry missed count/tail changes;
- the repository default omitted A2's authentic tactical shield.

This explains swings such as 333/600 followed by 999/2,000 for the temporal
model, while an A2 self-control itself scored 1,052/2,000. Those were noisy
unpaired samples, not evidence that the policy had moved by five points.

The replacement evaluation-only DLL exposes `BattleStartSeeded` and leaves the
production DLL untouched. Its SHA-256 is
`11662D6D96FEBB8ACA8F500BDFDE520AE0F1686AB3959EEF90AA16C958E68188`;
the preserved production DLL is
`EAE88634E26DC31D94150A4D8202FC9D32596B8C688EF67E14CB4088CD4D5771`.
Repeated single-worker and parallel runs produced byte-identical public
observation/action/outcome traces. Pairing is certified only for deterministic
opponents; the authentic `v2_2` and Alakazam 2.4a agents failed that proof, so
their paired numbers are excluded.

## The materially different policy mechanism

The breakthrough was single-decision gameplay intervention rather than replay
imitation or hand-authored strategy:

1. Run deployed A2 against A2 on a seeded schedule.
2. At an A2/temporal semantic disagreement, replay the same game with exactly
   that one choice changed, then return immediately to A2.
3. Measure the terminal win difference and aggregate only public categorical
   cells.
4. Gameplay-screen those cells and retain only the replicated winner.
5. Collect a second intervention corpus on-policy under that winner and make
   one further routing iteration.

The first corpus completed 1,871 interventions with zero errors. An initial
second-order context router for contexts 7, 16, and 21 then won 985 versus 943
over 2,000 fresh paired games: +2.10 points, 95% CI [+0.56, +3.64]. A new
2,000-task on-policy corpus under that router identified four additional
action-type cells. The broad v2 router added those cells and beat its
conservative sibling on the selection screen. Adding three more cells from the
older A2 corpus produced only +0.20 points on a fresh 500-pair screen, so that
expanded version was rejected.

The deployed router uses temporal only when all of these are true:

- the agent is moving second;
- both policies return one legal action;
- their choices differ semantically; and
- the public prompt/action-type cell matches one of the seven frozen routes.

Otherwise it is exactly shielded A2. The router contains no opponent hand/deck
features, future information, matchup labels, or search.

The temporal proposal policy is the schema-3 continuation checkpoint: all A2
weights were fine-tuned on exact-deck elite winner trajectories with option and
count behavior cloning plus A2 KL anchoring at weight 0.5. A2 itself remains
the rehearsal/anchor policy at runtime. The router is not trained on replay
agreement; its cells come from terminal-outcome intervention advantages. The
candidate generator deliberately spans both A2's action and the temporal
policy's alternative, so it can select moves outside A2's greedy choice while
remaining bounded.

As a behavior diagnostic, the stateless model-level router reconstruction
selected temporal on 373/57,672 held-out rows (0.647%). Low change rate is not
the objective, but it confirms
that the measured lift came from a concentrated set of decisions rather than
broad policy replacement. The strongest on-policy improvement pattern was A2
ABILITY -> temporal PLAY (+13 terminal wins across 381 single interventions);
PLAY -> ATTACH and PLAY -> EVOLVE were also positive. Known regression evidence
was retained: context 21 was -1 on the on-policy intervention corpus, the hard
top-20 semantic top-1 metric slipped 0.038 points versus A2, and the expanded
ten-route version failed its fresh gameplay screen. Those are why the shipped
router stops at the seven frozen cells.

## Direct A2 evidence

The broad v2 router was selected on a 500-pair screen, then evaluated on two
fresh post-selection schedules:

| Schedule | Actual order | Candidate | A2 | Paired delta, 95% CI |
|---|---|---:|---:|---:|
| Selection screen | second | 253/500 | 233/500 | +4.00 pp [+0.34, +7.66] |
| Independent confirmation | second | 1,014/2,000 | 953/2,000 | +3.05 pp [+1.17, +4.93] |
| Final fresh balanced gate | first | 515/1,000 | 515/1,000 | 0.00 pp [0, 0] |
| Final fresh balanced gate | second | 473/1,000 | 464/1,000 | +0.90 pp [-1.80, +3.60] |

Pooling only the two post-selection actual-second confirmations gives 1,487
wins versus 1,417 over 3,000 pairs: **+2.33 points, 95% CI [+0.79, +3.87]**,
with 314 candidate-only and 244 A2-only wins. Since first-order behavior is
exactly A2, a 50/50 order mixture implies +1.17 points overall, with the paired
interval scaled to approximately [+0.40, +1.94]. All 8,000 engine games in
these confirmation arms completed with zero candidate, control, or opponent
policy errors.

The final balanced batch alone was positive but inconclusive (+0.45 points
overall). That smaller batch is not hidden; the promotion is based on the
predeclared larger confirmation plus consistent pooled post-selection
evidence, not on claiming every random batch must be significant.

## Population and matchup expansion

All figures below are actual-second paired screens. First-order behavior is A2.
The basic opponents passed repeat/parallel determinism proofs.

| Opponent | Candidate | A2 | Delta |
|---|---:|---:|---:|
| Authentic d842 | 143/300 | 141/300 | +0.67 pp |
| Authentic master_v1 | 144/300 | 138/300 | +2.00 pp |
| Authentic replay_refresh | 149/300 | 136/300 | +4.33 pp |
| Bellibolt proxy | 187/200 | 192/200 | -2.50 pp |
| Crustle proxy | 126/200 | 132/200 | -3.00 pp |
| Lucario proxy | 159/200 | 157/200 | +1.00 pp |
| Ogerpon proxy | 49/200 | 41/200 | +4.00 pp |
| Starmie/Froslass proxy | 187/200 | 187/200 | 0.00 pp |

The three deterministic authentic Grim variants pool to +2.33 points, 95% CI
[-0.38, +5.04]. The five proxies pool to -0.10 points, 95% CI [-1.99, +1.79].
This is reassuring against a broad collapse, but it is not a calibrated ladder
estimate.

Pooling the three high-confidence Grim variants with both deterministic
Alakazam 2.7 screens gives 536 wins versus 512 over 1,050 actual-second pairs:
+2.29 points, 95% CI [-0.16, +4.73]. This is an unweighted high-confidence
population summary, not a meta-weighted rating estimate; current live matchup
weights and a calibrated score transform are unavailable, so inventing a
"900+ estimate" would be misleading.

Authentic full-search Alakazam 2.7 passed single/parallel determinism proofs on
two independent seeds per order. Its first
50-pair screen favored the candidate 33-30 (+6 points); the independent
100-pair confirmation tied 67-67. Pooled, the candidate leads 100-97 over 150
pairs: +2.00 points, 95% CI [-3.40, +7.40], with zero errors. This is
non-regression evidence, not proof of an Alakazam gain. Alakazam 2.4a was
nondeterministic and is excluded.

## Held-out elite top-1/top-3

The Aug-6 holdout contains 57,672 decisions from 561 episode-seat trajectories
and has zero episode overlap with Aug-4/5 training. The hard rank-1-to-20
subset contains 17,030 decisions. These are model-level replay-agreement
diagnostics; tactical-shield stateful behavior and gameplay strength are
separate gates.

| Policy / holdout | Raw top-1 | Raw top-3 | Semantic top-1 | Semantic top-3 |
|---|---:|---:|---:|---:|
| A2, broad | 75.208% | 94.113% | 83.442% | 98.924% |
| Selected router, broad | 75.230% | 94.120% | 83.493% | 98.926% |
| Selected router, hard top-20 | 70.640% | 92.234% | 79.675% | 98.269% |

The requested >90% top-3 threshold passes. Raw top-1 does **not** reach 80%.
Duplicate-aware semantic top-1 does exceed 80% on the broad holdout, but A2
already did that while rated only in the mid-800s. The labels are actions from
elite wins, not counterfactually proven best moves. The aggressive imitation
model improved these offline metrics and then scored only 267/600 against A2,
so top-k is useful for regression detection but cannot certify 900+.

## Other candidate families

Successive halving also screened and rejected:

| Family | Decisive reason |
|---|---|
| Full and aggressive elite fine-tunes | 283/600 and 267/600 versus A2; better imitation did not transfer. |
| Schema-5 relational model | Catastrophic 145/600. |
| Corrected strategic v2.1 | 277/600. |
| Temporal continuation | One +2.70-point paired batch, then -0.15; pooled CI crossed zero. |
| Public learned context gate | Exact tie, 197/400 each. |
| Shielded terminal-outcome PPO | +0.15 points over 2,000 actual-second pairs, CI crossing zero. |
| Terminal-Q / expected-Q | Only three robust labels; training would overfit. |
| Public value + one-ply search | Early-game AUC 0.515 and structural/latency audit failure. |
| Independent-root value search | Branch-order fixed, then significantly worse by 1.0 point over 2,000 pairs. |
| First-order precision routes | Best two 200-pair pilots were only +0.50 points with intervals crossing zero; keep exact A2 first. |
| Expanded ten-cell empirical router | +0.20 points over 500 fresh pairs; rejected in favor of the frozen seven-cell winner. |

These failures are retained rather than rewritten as wins. The selected router
is materially different because it is trained from controlled terminal-outcome
interventions and was iterated once on its own reached states.

## Package and runtime validation

| Item | Value |
|---|---|
| Archive | `artifacts/elite_policy_candidates/empirical_router_v2_broad/package/empirical_policy_router.tar.gz` |
| Archive size | 10,050,335 bytes |
| Archive SHA-256 | `CC567C0AD1787C39D1186075F85041DAFB9EC50D664F478C800682032C5EDC6D` |
| Promotion manifest SHA-256 | `A71B2B27EBFD7F347F57F6DF7E879005297511F397E336540EBDEC76E108D71A` |
| Extracted tree SHA-256 | `FA4741B0D502C1D9B80A5673944655AF20A87C85BD1C6A99974CADDA1026158B` |
| Authentic A2 source archive | `0958BD8847266EFBC38658D62B9AC4DCD62A9AAED3D1098F093A677AFCBFED4C` |
| Authentic A2 runtime source tree | `A25F9F0FEE304C6DE8811BB3E268D0A1BB7E5F60C961C3AAA005C590E51CEA12` |
| A2 schema-3 model | `80A0EF14D00256F2718D23E8323544B2901A7DF1A9CAAFD5070ED0B4B9779ACC` |
| Temporal model | `D4EFD8A8EEF1F617109DB80E74BB7EF667C74184BD3D579A3EFFFAD00B9BAB31` |
| Router config | `1359C557033EE05DF32E5D874DF47B4CD902C98FE6A2E13691B765DB61F1A54D` |
| Router runtime source | `CB2EDE021534C2162935B90BCDDDE112DF4215DCD2E0966939063D1A354F1682` |
| Controls | temperature 0, search off, tactical shield on |

Two sterile builds produced identical archive and tree hashes. A 20-game
isolated package validation completed 3,687 decisions with zero errors and
latency p50 0.875 ms, p95 2.106 ms, p99 2.952 ms, max 18.652 ms. The complete
test suite is 452 passing with two known pre-existing
`GrimFloorController` failures unrelated to this candidate.

## Recommendation

Use `empirical_router_v2_broad` for the next submission. It is a bounded,
public-only, deterministic improvement over authentic A2 with a statistically
positive post-selection direct-A2 result and no detected population collapse.
Do not submit strategic v2, v2.1, the pure temporal model, the expanded router,
outcome PPO, or the value-search wrappers. Do not claim that the local evidence
guarantees a score above 900; only a live submission can answer that calibrated
rating question.
