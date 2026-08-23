# Fresh C0-versus-EXP23 confirmation protocol

Frozen on 2026-08-23 (America/Chicago), on branch
`paper/aps-open-science-202608`, before any result file under
`paper/data/fresh_confirmation/raw/` was created or opened.

This protocol confirms two already frozen policies. It is not a candidate search,
hyperparameter screen, or stopping-rule experiment. No component may be changed in
response to results. The repository worktree was based at
`ee567ed5b75029b3785c3b44725c5d55f94f9abd` when this protocol was written.

## 1. Frozen subjects and software

All hexadecimal digests are SHA-256. Directory digests use
`training/evaluate_deterministic_crn.py::sha256_path`: sorted relative file names
and file digests, excluding `__pycache__` directories and `.pyc` files.

| Role | Repository path | Frozen digest |
|---|---|---|
| Candidate (EXP23) tree | `artifacts/final_sprint/exp23_identity_trained` | `83489e0c80c631763c65375d2a7a34d28d6aa9fbb1d11e89d130c83b1e27f1c0` |
| Candidate archive | `artifacts/final_sprint/exp23_identity_trained.tar.gz` | `0734b60c089eea9c2e40550b8e9c6dc3983957210794ba245c4c00bd9d4e7096` |
| Candidate first/second model (each) | `policy_first.npz`, `policy_second.npz` in candidate tree | `cefe61189bc6f4e316212b19c99450e4b91ff1e5493f4467a95041c30fd96984` |
| Control (C0=A2+Damage V0) tree | `artifacts/grim_damage_conversion/winner/extracted` | `13426288358d597ead809e45c364c7f7b9274a6eebf55ddd942142e3326535c3` |
| Control archive | `artifacts/grim_damage_conversion/winner/grim_a2_damage_v0.tar.gz` | `a44b676f5ca135747b5d4d6923c7fb350a66369d188315b6ac0f291d23ca69e7` |
| Control first/second model (each) | `policy_first.npz`, `policy_second.npz` in control tree | `b19871a9f1499c2460ae266e58194acab1d8c90b390fa5cf24ed94b9a2b6bda8` |
| Seeded evaluation engine | `artifacts/deterministic_engine/bin/libcg_seeded.dylib` | `867e3f9bb87e0b48889a44b5d4b04f5d2d434b2a0788d1b2bcfe0caebcb5ab78` |
| Production engine, integrity sentinel only | `vendor/cg/libcg.dylib` | `7a157f045d333f99d1996d49c12bdbdd148072a619af246385c7295518776e30` |
| Paired runner | `training/evaluate_deterministic_crn.py` | `fa60021b0906401aeb2c7c33e0f65f586eff256d83d689d688a86a40480e1341` |

The EXP23 package and raw earlier evaluation files entered history at commit
`05657c656c04d88b0352bb0db6f9e2a5dce4b234`. Large engine and opponent
package trees are ignored by Git. Their bytes are therefore fixed by the digests
above and below, but their absence from Git is a provenance limitation that must be
reported.

## 2. Frozen opponent population

The target population is exactly these seven local policy packages. It is a
defined test population, not a sample permitting inference to all card-game agents
or all competition opponents.

| Label | Repository path | Directory digest | Family | Base seed |
|---|---|---|---|---:|
| `grim_b0` | `artifacts/grim_variance_floor/candidates/B0` | `0c15b56adf3b09c654505a152309fdc9f8401579a495da714347d98ae735003c` | Grim | 202608230000 |
| `grim_d842_runtime` | `artifacts/overnight_20260816/d842_runtime` | `7db753d6610930d8bd9694b4b9bece5ac48733b825422a3e399c18077b55e64e` | Grim | 202608231000 |
| `grim_master_v1` | `artifacts/grim_damage_conversion/opponents/master_v1` | `8a06ebab47cc60ed981dfada85972eb8a62e732e349f01c2a3085262079f06e8` | Grim | 202608232000 |
| `grim_replay_refresh` | `artifacts/grim_damage_conversion/opponents/replay_refresh` | `30e45955b67893514c8ee077cac15d46fc207efe781cbce1b94242defda4cbdc` | Grim | 202608233000 |
| `starmie_v2_boss_atk` | `artifacts/sprint_870/opponents/starmie_v2_boss_atk` | `1b73779da7dcc93c8f121090bb0f1ae2d9b10b798ca4c70447b0ce1d6d01c0db` | Other | 202608234000 |
| `dipplin_d1` | `artifacts/sprint_870/opponents/dipplin_d1` | `076ae8de12d2d6c4a170b47b2d2f9cf538c1d318a05bb2e81f13da9be2cd2026` | Other | 202608235000 |
| `alakazam_2_4a_no_search` | `artifacts/sprint_870/opponents/alakazam_2_4a` | `5d44338891094988ca15f0c26d5187316549facd64a7bfbac04aa0048424e8c7` | Other | 202608236000 |

For Alakazam, the environment is frozen to `NO_SEARCH=1`. All other opponent
environment dictionaries are empty. The second-order stratum adds exactly
1,000,000 to the listed base seed. Each stratum uses offsets 0 through 199.
Thus all 14 seed ranges are disjoint. Physical seat alternates by offset parity,
beginning with seat 0.

## 3. Schedule and actual-order balancing

Run 200 candidate-control pairs in each of the 14 opponent-by-actual-order cells:

- seven opponents;
- actual-first and actual-second for each opponent;
- 2,800 paired units and 5,600 engine games total;
- identical engine seed, actual order, physical seat, opponent, and opponent
  environment within each candidate-control pair;
- a maximum of 2,000 engine decisions per game;
- eight workers for B0, d842, master-v1, replay-refresh, and Alakazam, and four
  workers for Starmie and Dipplin.

The full fixed schedule is run once. There is no interim analysis and no sample-size
expansion. Runtime differences affect only wall time, not the stop rule.

## 4. Outcomes and failure handling

For the primary binary outcome, a win is 1 and a loss or draw is 0. Draw counts are
also reported separately. A secondary utility sensitivity assigns win=1, draw=0,
loss=-1.

No game or pair may be silently deleted or replaced. An engine exception,
nonterminal truncation at 2,000 decisions, crash, illegal action, candidate/control
policy error, opponent policy error, digest mismatch, or production-engine sentinel
change invalidates the affected opponent cell. The runner is stopped for diagnosis;
the failure and partial row count are retained. A cell may be restarted from its
entire frozen seed range only after a purely infrastructural cause is documented,
without changing policy, engine, seeds, sample size, or analysis. If a policy or
engine defect caused the failure, the primary endpoint is reported as not estimable;
no failure is imputed as a win or loss.

## 5. Primary endpoint and uncertainty

For paired unit i in cell c, define

`d_ci = I(EXP23 wins) - I(C0 wins)`.

The primary endpoint is the unweighted mean of the 14 cell means. Because every
cell has the same scheduled sample size, this also equals the mean across all 2,800
paired differences when the battery completes.

The two-sided 95% interval is a stratified paired percentile bootstrap with 100,000
replicates and analysis seed 20260823. Each replicate resamples the 200 complete
candidate-control paired units with replacement independently within every frozen
cell, then averages the 14 resampled cell means. Candidate and control outcomes are
never resampled separately.

The confirmatory null is that the primary paired win-indicator difference is zero.
An exact two-sided McNemar test is computed from all candidate-only and control-only
wins: conditional on their total under the null, candidate-only wins are
Binomial(n_discordant, 0.5). This is reported alongside the bootstrap interval.
The bootstrap interval is the main uncertainty summary; no claim of demonstrated
improvement is permitted if it includes zero.

## 6. Secondary endpoints and multiplicity

Secondary summaries are:

1. each of the 14 opponent-by-order cell effects;
2. seven opponent effects averaged over actual order;
3. actual-first and actual-second macro effects averaged over opponents;
4. Grim-family and Other-family equal-policy aggregates;
5. win/draw/loss utility sensitivity;
6. discordant counts, error counts, decision counts, and per-game wall-clock
   latency if and only if the runner records it.

Exact two-sided McNemar p-values for the 14 individual cells are adjusted together
by Holm's method at familywise alpha 0.05. All other p-values and intervals are
descriptive and labeled secondary. No post hoc subgroup is confirmatory.

The historical `meta_weights.json` file referenced by the overnight protocol is not
present in the committed repository. Therefore no meta-weighted endpoint is part of
this fresh confirmation. A historical meta-weighted claim may be reported only as
unverified or if the exact preregistered weight artifact is recovered.

## 7. Stop condition and result access

The experiment stops after all 5,600 scheduled games complete, or immediately on a
failure listed in Section 4. Result files may be opened only after the protocol is
committed. All seven raw JSON files, the protocol commit, runner digest, package
digests, and analysis-script digest will be recorded in the claim ledger.

No policy selection, retuning, opponent substitution, seed extension, or wording
change to the primary claim is permitted after result access.
