# Provenance and evidence audit

Audit date: 2026-08-23 (America/Chicago). This companion audit records what was
actually present in the working repository and reachable local Git history when
the paper package was assembled. It is an evidence map, not a reconstruction of
files that no longer survive.

The labels used below are deliberately strict:

- **RAW-VERIFIED**: row-level or world-level records survive, their hashes were
  checked, and the stated aggregate was recomputed from those records.
- **HASH/CODE-VERIFIED**: the relevant package bytes or implementation survive
  and were inspected or hashed, but the item is not itself an empirical result.
- **SUMMARY-ONLY**: a historical prose/table report survives, but the underlying
  records needed to recompute it do not.
- **CONFLICT**: surviving sources or their arithmetic cannot all describe the
  same estimand.
- **MISSING**: a referenced artifact was absent from the checkout and from the
  local Git object-path search. This does not prove that no external copy exists.

## Repository and branch lineage

The requested evidence branch name, `Matched-5k-variance-floor`, is not a local
branch ref. The repository instead contains
`archive/Matched-5k-variance-floor` at
`576a1dc32bafdd6ca96693baf66effedf3ac173c`. This is a branch-name discrepancy,
not permission to silently substitute one history for another.

The paper branch is `paper/aps-open-science-202608`. Its frozen confirmation
protocol states that the branch was based at
`ee567ed5b75029b3785c3b44725c5d55f94f9abd`. The protocol was committed as
`c17434252deb8fdc3b42b2c12a58f18ca646215e` before fresh-result files were
opened. These protocols were prospectively committed locally; they were not
deposited in an external registry. A few frozen protocol references use
“preregistered” as internal shorthand, but the manuscript deliberately makes
the narrower local-commitment claim. The frozen protocol text is preserved
unchanged after result access. Likewise, the ablation protocol's “attributable”
and “encoder effect after training” phrases are frozen shorthand: C3 and C4 were
fitted separately under their respective encoders, so the warranted C4--C3 label
is “trained-pipeline identity-versus-blind contrast,” not a controlled encoder
toggle at fixed weights. The separate historical branch
`final/overnight-20260816` resolves to
`de532fa52f41d6bb4dece2c3af41175fed15e952` in the audited repository. Two
historical reports used in this audit are branch-only:

- `docs/sprints/final_overnight/FINAL_DECISION_PACKET_20260816.md`, last changed
  at `d79d478d3e7bea1c8e12abbb721a073eaff00d40` on that branch; and
- `docs/sprints/final_overnight/EXP23_LIVE_LOSS_ANALYSIS_20260816.md`, last
  changed at `de532fa52f41d6bb4dece2c3af41175fed15e952`.

The decision packet says that its evidence set included uncommitted evaluation
outputs. That statement is consistent with the raw-artifact gaps documented
below; a prose reference in that packet is not evidence that the corresponding
file entered Git history.

## Frozen subjects and evaluation software

All digests in this section are SHA-256. Package-tree digests use the directory
algorithm in `training/evaluate_deterministic_crn.py::sha256_path` (sorted
relative paths and file digests, excluding `__pycache__` and `.pyc`), and are
therefore not interchangeable with archive-file digests.

| Item | Path | Verified digest | Status |
|---|---|---|---|
| C0 package tree (A2 + Damage V0) | `artifacts/Matched_damage_conversion/winner/extracted` | `13426288358d597ead809e45c364c7f7b9274a6eebf55ddd942142e3326535c3` | HASH/CODE-VERIFIED; ignored local tree |
| C0 archive | `artifacts/Matched_damage_conversion/winner/Matched_a2_damage_v0.tar.gz` | `a44b676f5ca135747b5d4d6923c7fb350a66369d188315b6ac0f291d23ca69e7` | HASH-VERIFIED; ignored local file |
| C0 first and second model, each | `policy_first.npz`, `policy_second.npz` in the C0 tree | `b19871a9f1499c2460ae266e58194acab1d8c90b390fa5cf24ed94b9a2b6bda8` | HASH-VERIFIED |
| EXP23 package tree | `artifacts/final_sprint/exp23_identity_trained` | `83489e0c80c631763c65375d2a7a34d28d6aa9fbb1d11e89d130c83b1e27f1c0` | HASH/CODE-VERIFIED |
| EXP23 archive | `artifacts/final_sprint/exp23_identity_trained.tar.gz` | `0734b60c089eea9c2e40550b8e9c6dc3983957210794ba245c4c00bd9d4e7096` | HASH-VERIFIED |
| EXP23 first and second model, each | `policy_first.npz`, `policy_second.npz` in the EXP23 tree | `cefe61189bc6f4e316212b19c99450e4b91ff1e5493f4467a95041c30fd96984` | HASH-VERIFIED |
| Seeded evaluation engine | `artifacts/deterministic_engine/bin/libcg_seeded.dylib` | `867e3f9bb87e0b48889a44b5d4b04f5d2d434b2a0788d1b2bcfe0caebcb5ab78` | HASH-VERIFIED; ignored binary |
| Production-engine integrity sentinel | `vendor/cg/libcg.dylib` | `7a157f045d333f99d1996d49c12bdbdd148072a619af246385c7295518776e30` | HASH-VERIFIED |
| Paired evaluator | `training/evaluate_deterministic_crn.py` | `fa60021b0906401aeb2c7c33e0f65f586eff256d83d689d688a86a40480e1341` | CODE-VERIFIED |

The frozen inventory is
`artifacts/overnight_20260816/frozen_hashes.json` (file digest
`0dcd77c2a1f257730996cde774bfbd3cc3a67a69e39e6ac4aa133be2e115a7a8`),
committed at `b7ce5ba7578b125e9fc6fa25b57c33a91c00dddf`. The EXP23 archive and
several surviving EXP23-versus-C0 raw files entered history at
`05657c656c04d88b0352bb0db6f9e2a5dce4b234`. The C0 package, its weights,
the retained feature corpus, and several opponent/engine trees are ignored
local artifacts rather than Git objects. Their hashes pin the audited bytes but
do not provide durable repository provenance.

## Evaluation coupling audit and invalidated four-cell analysis

**RAW/CODE-VERIFIED DESIGN FAILURE.** The paired evaluator builds candidate and
control games as separate tasks and dispatches them through
`multiprocessing.Pool.imap_unordered` (`training/evaluate_deterministic_crn.py`,
digest `fa60021b0906401aeb2c7c33e0f65f586eff256d83d689d688a86a40480e1341`).
The two arms share the scheduled gameplay-engine seed, opponent package, actual
order, and physical seat, but distinct tasks are not guaranteed to run in the
same worker and do not share a realized opponent-search trajectory. Native
`cg.api` search state and RNG are process-local and can persist within an
evaluator worker.

Two of the seven opponents contain explicit timing dependence:

- Broader1 search sets a 3.0-second `time.monotonic()` deadline and stops
  determinization, branch, and rollout work against it
  (`artifacts/sprint_870/opponents/Broader1/agent/search.py`, digest
  `658ed0280ed70bad423d39b35a19a79491518fbbf2a82996ac9ac00d90204b6a`).
- Broader2 search uses a monotonic clock to set soft and hard search deadlines
  (`artifacts/sprint_870/opponents/Broader2/ptcg_ai/Broader2/search.py`, digest
  `14fdb20b672aa16a6f7d02a1b923f4194d44c26f082ddddb288e729f64c2c291`).

The prospectively frozen analyzer gate committed before C2/C3 gameplay at
`63ea3135709646c41feb892e863a8bc00e758ed3` required the C1 record repeated
alongside C2, C3, and C4 to agree on every seed-condition unit. Reaggregation
of all 2,800 units found 210 with a differing C1 win/draw/error outcome record:
191 against Broader1 (82 actual-first and 109 actual-second) and 19 against
Broader2 (10 first and 9 second). When recorded decision count is included, 458
units differ (377 Broader1 and 81 Broader2). The other five opponents—Matched1, Matched2,
master v1, replay refresh, and Broader3—have identical available serialized C1
summaries across the three executions; trace capture was disabled.

The planned seven-opponent four-cell contrasts, paired intervals, McNemar tests,
and interaction are therefore **NOT ESTIMABLE UNDER THE FROZEN VALIDATION**.
Mismatched units are preserved rather than deleted. Within-run C2-versus-own-C1
and C3-versus-own-C1 values are process-sensitive descriptions without
intervals or tests. Selecting the five opponents whose available serialized
control summaries happened to match changes the target population after
inspection; traces were not captured. Accordingly, that subset is post hoc and
descriptive only. The C4--C1 primary rows still
support a prespecified realized schedule comparison, but its interval
conditions on one execution and omits opponent-search, scheduler, and
process-local runtime-state variation. It is not a validated
common-random-number variance-reduction experiment.

## Representation defect and repair

**HASH/CODE-VERIFIED.** In C0,
`artifacts/Matched_damage_conversion/winner/extracted/ptcg_ai/features.py:207`
calls `option_source_card(obs, option)`. That helper resolves a card only through
`option.area` and `option.index`. For an ordinary `PLAY` option with no raw area,
the result is `None`; `features.py:212` then falls back to `option.cardId or 0`.
For the affected ordinary PLAY prompts, this omits the selected hand-card
identity from the option-level source coordinate. The v2 model still receives a
normalized hand index and pooled hand-identity tokens, but no binding between
them; this is relational underspecification rather than proof of identical full
inputs.

EXP23 adds a gated repair at
`artifacts/final_sprint/exp23_identity_trained/ptcg_ai/features.py:207`: when the
source is unresolved and the option type is `PLAY`, it binds the source to
`current.players[yourIndex].hand[option.index]`, with an in-range check. The
default remains off in the module, and
`artifacts/final_sprint/exp23_identity_trained/main.py:8` explicitly enables it.
C0's `main.py` does not. This is a narrowly identified representation change;
it does not establish by itself that downstream play improves.

The retained-row audit in `paper/data/representation_audit.json`, generated by
`paper/scripts/audit_representation.py`,
found 37,199 ordinary PLAY option instances in 47,653 retained decision rows.
The baseline resolution was missing for all 37,199, while identity binding
resolved all 37,199. Of 15,728 states containing an ordinary PLAY option, 9,776
contained at least two PLAY identities. An exact within-state audit including
the normalized hand-index coordinate found zero cross-identity full option-input
collisions. An earlier 17-group/99.7% calculation pooled local signatures across
unrelated observations and was rejected during red-team review. These counts are a feature-row/code
diagnostic, not an engine-game endpoint; the audit explicitly omits runtime
shields. The older ledger statement that the source was zero in “100% of
110,966 training rows” is therefore retained only as a historical summary, not
used as the verified denominator in the paper.

## Retained corpus, split, and realized training stream

The retained identity corpus is
`artifacts/final_sprint/identity_train/merged_decisions.jsonl.gz`, digest
`a3d28e9c3ab650a1ec3c1cf708fc7684dc5258a86469d622871e7efe25dcdc40`.
Its split manifest is
`artifacts/final_sprint/identity_train/train_manifest.json`, digest
`8c13a5de5b34c3deec5909948fb8c03117048f0295140c48a0325550a9a1a774`.
The manifest assigns the 47,653 fresh rows as follows:

| Split | Rows | Episodes | Use |
|---|---:|---:|---|
| Training | 38,254 | 378 | Gradient updates |
| Internal validation | 3,361 | 33 | Validation/checkpoint selection |
| Team holdout | 6,038 | 61 | Excluded from gradients and internal validation |

Every retained row has positive reward, source label `daily_top_episode`, and a
null observation field. The corpus is therefore winner/top-episode selected;
demonstrator optimality is not independently established, and the source binding
cannot be re-resolved from these rows. The manifest also identifies 41,615
eligible rehearsal records after excluding the held-out teams. The historical
training configuration was A2 initialization
and teacher; seed `20260816`; CPU; feature version 2; updates to the option
projection plus score, count, and value heads (`option_linear`, `score`, `count`,
and `value`); the A2-weight teacher was evaluated under the cell's encoder;
AdamW learning rate `1e-4`;
weight decay `1e-5`; batch size 256; three epochs; distillation weight 0.5; and
configured fresh weight 0.999.

**CONFLICT between configured and realized mixture.** The surviving log
`artifacts/final_sprint/identity_train/train/train.log` (digest
`d56523e715a632bf22c1f79316e0664624c3d70ac49d72376eaa973796efa194`)
records, in every epoch, `fresh_records=38254`, `fresh_fraction=1.0`, and
`rehearsal_records=0`. The mixer in `training/Matched4.py:297` rounds the
per-batch rehearsal target; at fresh weight 0.999 and batch size 256 that target
rounds to zero. Thus the truthful description is “configured for 99.9% fresh,
realized 100% fresh and 0% rehearsal.” Any description of EXP23 as protected by
realized rehearsal mixing is false. Its conservative components were the frozen
trunk and teacher-distillation term.

The original Aug. 14--15 replay observations used to mine the retained feature
rows do not survive, and the purported temporal material consists of eight empty
stub files. Training can be replayed from retained feature rows, but feature
extraction and the temporal split cannot be reconstructed from original
observations.

## Stale package metadata and hash conflicts

Two historical metadata defects are material:

1. The pre-evaluation copy of
   `docs/sprints/final_overnight/OVERNIGHT_CERT_20260816.md` at commit
   `9d974bb9ae7c57dad08d4742c8ad4503e1a681c0` lists EXP23's tree as
   `9f12a4058aa4f8895a4b2f5f9d3724fd9c771a10c7979a1087b316e100aba87e`.
   Commit `dab404afe5e04cbf0fdcb5e489bef8fe62429178` on
   `final/overnight-20260816` marks that value as a clerical error and replaces
   it with `83489e0c...e27f1c0`. The corrected value agrees with the frozen hash
   inventory, current package bytes, and surviving evaluation JSON. It is the
   authoritative tree digest.
2. `artifacts/final_sprint/exp23_identity_trained/order_policy_manifest.json`
   (file digest
   `30a47b38393ce5563b6ef35425cfdf16118bca2468645b54e759b57266ce28d7`)
   still labels the package `CONTROLLED_LADDER_PROBE` and declares A2 digest
   `b19871a9...b6bda8` for both order arms. The archive members actually hash to
   EXP23 digest `cefe6118...96984`, and `main.py` enables PLAY identity. The
   manifest is stale and must not be used to identify the runtime policy.

These records were preserved rather than rewritten. Archive-member bytes,
frozen inventories, and evaluator-recorded package hashes take precedence over
the stale labels.

## Historical EXP23 gameplay aggregate

Nine committed `artifacts/final_sprint/exp23_vs_*.json` files contain surviving
row-level direct evaluations of EXP23 against C0. They are development/history
artifacts, not the paper's prospectively specified fresh confirmation.

The historical claim “Matched-family pooled approximately +4.5 percentage points
over approximately 3,600 pairs” is **CONFLICTED**. The four named positive
confirmation files that sum to exactly 3,600 pairs give different arithmetic:

| Raw file | File digest | Last path commit | Pairs | EXP23 minus C0 wins | Raw paired effect |
|---|---|---|---:|---:|---:|
| `artifacts/final_sprint/exp23_vs_ctl_Matched1_p1200b.json` | `7fd48c4f0d81ad48baecb98860e578637479943d790cf9ed2e4110ee3a45a551` | `05657c656c04d88b0352bb0db6f9e2a5dce4b234` | 1,200 | +50 | +4.1667 pp |
| `artifacts/final_sprint/exp23_vs_ctl_Matched3_p800.json` | `fc7870569ec45bc33d2c0ca0c9888339af45febc8f9b9fa1e1577b2358769b79` | `05657c656c04d88b0352bb0db6f9e2a5dce4b234` | 800 | +51 | +6.3750 pp |
| `artifacts/final_sprint/exp23_vs_ctl_Matched3_p800_fresh.json` | `653eb29775a101228c4fa2a55ca15168dc7fa41430f33f86ddfab5cf468270a4` | `accf274d1594381a0b36768afaea18ea74b74e4c` | 800 | +46 | +5.7500 pp |
| `artifacts/final_sprint/exp23_vs_ctl_Matched4_p800.json` | `ee1f09a26acc58b4ea1cd78f0f04663f60cb523f8d39a5fafb9e39a4b787c160` | `05657c656c04d88b0352bb0db6f9e2a5dce4b234` | 800 | +50 | +6.2500 pp |
| **Unadjusted total** |  |  | **3,600** | **+197** | **+5.4722 pp** |

The decision packet's same sentence also names an older Matched1 file and a Matched2
400-pair cell. Including all six named cells would yield 4,800 nominal pairs,
not 3,600. Moreover,
`exp23_vs_ctl_Matched1_p800.json` (base seed `202608170100`) and
`exp23_vs_ctl_Matched1_p1200b.json` (base seed `202608170200`) share 600 paired seeds.
For all 1,200 overlapping candidate/control rows, win, draw, decision, error,
physical-seat, and trace-digest fields match exactly. They cannot be naively
pooled as independent pairs. The row-level Matched2 400-pair artifact cited in the
packet does not survive.

No unique interpretation of “+4.5 pp / 3,600 pairs” is supported by the surviving
files. The historical aggregate is therefore omitted rather than silently
reweighted or deduplicated post hoc.

## Missing CERT-B, field-wave, and meta-weight evidence

The final decision packet references the following as raw evidence, but they
were not present under the named paths and no matching path was found in
reachable local Git objects:

- `artifacts/overnight_20260816/cert_exp23_vs_c0.json` and its rows file;
- `artifacts/overnight_20260816/cert_exp23_0813.json` and its rows file;
- `artifacts/overnight_20260816/calib_Matched2_vs_c0.json`;
- `artifacts/overnight_20260816/calib_exp20_vs_c0.json`;
- `artifacts/overnight_20260816/field/exp23_vs_vs_*_p100.json`;
- `artifacts/overnight_20260816/meta_weights.json`; and
- `artifacts/overnight_20260816/late_divergence_diagnostic.jsonl.gz`.

Consequently, the historical seven-policy macro `+1.8 pp`, the claimed
meta-weighted `approximately +2.0 pp` at `54%` coverage, the calibration ratios,
and the historical CERT-B intervals are **SUMMARY-ONLY** and are not exact paper
evidence.

The CERT-B prose is also internally inconsistent. The frozen classifier defines
“decisive” as candidate-approved plus C0-approved and treats an elite third action
as abstention. Yet the packet calls 529 rows decisive. Its per-team denominators
sum to 398 binary decisive rows, and the reported ratio is consistent with
175 candidate approvals and 223 C0 approvals (`175/398 = 0.43970`); the remaining
131 rows are abstentions. The reported late breakdown similarly totals 233 as
48 candidate-approved, 112 C0-approved, and 73 abstentions. Without the missing
rows the clustered interval cannot be reproduced. In addition, the frozen
protocol specifies 10,000 bootstrap iterations while
`scripts/overnight_20260816/replay_disagreement.py` defaults to 20,000. These
facts require the historical CERT-B result to remain summary-only/conflicted,
not to be promoted to a verified primary outcome.

The local directory
`artifacts/overnight_20260816/episodes_0813_holdout_teams/` contains retained
Aug. 13 replay files. The paper's newly labeled reanalysis is recorded in
`paper/data/heldout_0813_summary.json` and the claim ledger. It is a new result;
it does not recover the absent historical CERT-B JSON, rows, or bootstrap
execution.

## Negative and null evidence

### Raw-verified results

The paper reaggregation in `paper/data/negative_results.json` uses only surviving
raw records.

**Two-turn temporal takeover.** Three 400-pair actual-second confirmations were
committed at `816f537548d7733642e32c7ffa59c48151a4e3ce`:

- `artifacts/Matched_b_final_confirmation_vs_Matched2_second_400pairs.json`, digest
  `e6e223e1f0651098eb8e72b40a2b5ffb1a8a3b075baa49e5bfd417c8eb9fc8a5`;
- `artifacts/Matched_b_final_confirmation_vs_Matched3_second_400pairs.json`,
  digest
  `ca7aedc06d2d9e96d3e351d07975c2917fecc739dd5dbe0877ad725a6843ce3d`;
  and
- `artifacts/Matched_b_final_confirmation_vs_Matched4_second_400pairs.json`,
  digest
  `b099ca4b94c77375256408b1b4c3987cd1130d7ee114a9b24939b0ee67534550`.

Reaggregation gives 597 candidate wins and 596 control wins over 1,200 pairs,
with 81 candidate-only and 80 control-only wins, zero recorded errors, and a
paired effect of +0.0833 pp. A 100,000-draw bootstrap stratified by the three
opponents gives a 95% interval of [-2.0000, +2.1667] pp. This is evidence that
the bounded intervention did not demonstrate a benefit, not evidence that all
temporal policies fail.

**Bounded sequence oracle.** The raw package was committed at
`def0c62a6cb804d8991df5c91a541037afc50cde`. Its manifest is
`artifacts/Matched_sequence_oracle_v0/manifest.json`, digest
`d5e66f88878591d7f2a6d0270c9949aa9f4e591bb44b2855f8e072c57bed6846`;
the 60 roots file has digest
`fd98f2792f349e75a77917fb94c380b26409c604cdfb04de2622d3a418765032`;
the raw result file has digest
`4fed0067e8a2c04533428459379d0b25abc07f4e9fadd08ff03ca3a5f389d953`;
and the manifest pins the seeded engine as
`c257a121c07943c13b81cd276cfd6a88e035820e1678c64701a38692183b172e`.
Across 960 confirmation worlds, the bounded oracle won 513 and baseline won
510, with 56 oracle-only and 53 baseline-only wins and zero recorded errors.
The effect was +0.3125 pp; a 100,000-draw root-cluster bootstrap interval was
[-1.4583, +1.9792] pp. Only three independent two-deviation rescue roots were
observed, below a historically reported +3 pp / five-to-six-state gate. The
report, gate-bearing implementation, manifest, roots, and results first entered
reachable Git history together at the commit above, so advance specification of
that gate cannot be independently established. The warranted claim is bounded
and inconclusive.

### Summary-only negative results

| Experiment | Surviving report | Historical summary | Why it is not raw-verified |
|---|---|---|---|
| Shielded outcome PPO | `docs/sprints/strength_and_a2/A2_SHIELDED_OUTCOME_PPO_AUDIT.md` (last path change `63a9587efdfd778f27c9cc3a5eb7a8fe4fce483f`) | 2,000 actual-second pairs; 997 versus 994 wins; +0.15 pp; reported 95% interval [-1.294, +1.594] pp; 110/107 discordants; zero errors; claimed result digest `364f4a10...50d` | The result rows/file identified by that digest do not survive. Exact estimates are attributable only to the report. |
| Seeded expected-Q audit | `docs/archive_and_logs/SEEDED_Q_EXPECTED_ADVANTAGE_AUDIT.md` (last path change `63a9587efdfd778f27c9cc3a5eb7a8fe4fce483f`) | 92 boundaries, 22 screened candidates, 704 fresh worlds, and three stable labels from three episodes; no model packaged | The report's manifest, raw outcomes (`b797849f...44d`), and label file (`dc2c1076...8b7`) are absent. |
| Turn Director | `docs/strategy/POSTMORTEM_SEARCH_V1.md` (last change `d78a00d428d6845fd0177fdfda5f7eea14f2377e`) | Independent, unpaired 2,000-game arms; 52.95% treatment versus 54.35% control; -1.40 pp; one-sided lower bound -3.99 pp; zero errors | `artifacts/turn_director/confirmation/kill_screen.json` and game rows are absent. The result must not be described as paired, independently recomputed, or causally definitive. |

These summary-only experiments may be cited as historical audit outcomes with
explicit attribution, but their exact numerical estimates are excluded from the
paper's verified statistical tables and figures.

## Engine rights and sanitized-release boundary

The official engine source is tracked under `freshstart/engine/ptcgProgram`.
Its governing local notice is
`freshstart/engine/ptcgProgram/LICENSES/LicenseRef-PTCG-ABC-Competition-Use-Only.txt`,
committed at `5933e9ab3b7ab3b91f16fc1ff9ff812ad28e9e1d`. The notice says that the engine
is not open source, limits use to building and testing competition entries while
the competition is running, prohibits redistribution and outside use, requires
deletion after the competition, and says derived work is deemed “Pokémon
Elements” under the binding competition rules. This companion audit reports the
local notice and is not legal advice; the corresponding author must obtain a
rights determination from the organizer or counsel.

The sanitized release must therefore exclude at least:

- official engine source and all engine binaries, including those embedded in
  historical package archives;
- card databases, card names/text, deck files or lists, and copyrighted visual
  assets;
- private replay observations, player/team identifiers, and raw feature rows
  that expose card identifiers;
- third-party opponent packages or implementations; and
- deployable C0/EXP23 package trees and archives pending a specific rights
  review.

Cryptographic digests, aggregate/processed numerical outcomes, generic
statistics scripts, and an abstract engine-adapter interface can document the
study without redistributing restricted bytes, subject to privacy and rights
review. There is no repository-level license granting rights to the authors'
remaining code. A companion release must not imply an open-source license until
ownership and the competition's derivative-work clause are resolved; the
conservative interim statement is that no license is granted.

Exact end-to-end gameplay regeneration consequently requires separately
authorized access to the organizer's engine and equivalent opponent packages.
The private-review release is designed to reproduce tables and figures from
sanitized processed data if rights approval and deposit later permit publication,
but it cannot make the restricted environment or private replay pipeline
independently available. This is a substantive reproducibility and submission
constraint, not merely a packaging inconvenience.
