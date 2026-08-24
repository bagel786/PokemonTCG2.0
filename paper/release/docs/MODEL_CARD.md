# Model card: C0, EXP23, and mechanistic ablation cells

## Models

- **C0:** frozen A2 policy with deterministic Damage V0 runtime logic. Both
  actual-order arms use byte-identical A2 weights.
- **EXP23:** the PLAY-source binding is enabled and only the option projection
  plus score, count, and value heads are retrained. All three packaged policy files are
  byte-identical; the trunk and embeddings remain frozen.
- **C2 diagnostic:** identity binding enabled with unchanged A2 weights. This is
  an out-of-distribution mechanistic probe, not a recommended deployed policy.
- **C3 diagnostic:** blind encoding with the same retained examples and labels
  after the prespecified deterministic source-field transform, plus the same
  seed, training implementation, and hyperparameters as EXP23.

Exact model and package SHA-256 digests appear in the protocols and claim
ledger. A stale historical EXP23 manifest lists the A2 model hash, but archive
member bytes, the frozen hash inventory, and evaluation records agree on the
EXP23 model digest; the stale manifest is not used as authority.

## Intended use

These policies support bounded research on missing option--item binding and paired
evaluation in the specified private tournament engine. They are not safety
certified, not guaranteed to improve against unsampled opponents, and not
licensed here for commercial deployment or redistribution.

## Training and evaluation

EXP23 and C3 initialize from A2, train one seed for three epochs on outcome-selected
retained feature rows, use AdamW and KL distillation, and freeze all but four
output-side modules. The frozen A2-weight teacher is evaluated under each cell's
encoder, so its identity-aware output is not identical to blind C0 behavior. The
configured 99.9% fresh weight realized as 100% fresh because per-batch rehearsal
rounding produced zero rows. Evaluation matches gameplay-engine seed, actual
order, physical seat, engine build, and opponent package within each
candidate-control schedule pair. Candidate and control games run as separate
process-pool tasks; the match does not couple every source of opponent behavior.

The prospectively frozen analyzer invalidated the planned seven-opponent
four-cell analysis. Repeated C1
outcomes disagreed on 210 of 2,800 seed-condition units, all against Broader1 and
Broader2. Those opponents use wall-clock-bounded search. Planned cross-cell
contrasts and their paired inference are therefore not estimable; within-run
mechanistic summaries are descriptive. The five-opponent subset with matching
available serialized control summaries is post hoc; traces were not captured.

## Limitations and risks

The opponent battery is fixed and nonrandom; source data are selective and
private; original mining replays and an original environment lock are missing;
latency and process scheduling are unavailable; and the engine/card ecosystem
cannot be redistributed. The primary bootstrap interval conditions on one
execution and omits run-to-run opponent-search/runtime-state variation. Model
behavior may depend on runtime shields not represented in output-module
diagnostics. The intended release is limited to processed results and methods,
not deployable packages.
