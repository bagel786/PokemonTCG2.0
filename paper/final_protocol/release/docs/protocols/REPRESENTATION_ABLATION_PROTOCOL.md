> **Review-package transcription.** Restricted labels and local paths are neutralized. The statistical plan and identifiers are preserved, but these bytes are not the frozen source artifact. Statements about noninspection are protocol conditions; Git proves commit ordering, not when a human inspected uncommitted files.

# Frozen representation-by-training ablation protocol

Frozen before training or evaluating the missing cell. This secondary
mechanistic experiment asks whether the observed behavior is attributable to
the PLAY-source representation, head retraining, or their interaction.

Protocol amendment (before any corpus derivation, training batch, or gameplay
evaluation): the first invocation at commit `a976a2b` exited at import time with
`ModuleNotFoundError: training`. The runner was amended only to prepend the
repository root to `sys.path`. No data, seed, package, training setting, endpoint,
or analysis rule changed; the failed invocation produced no result file.

Analysis clarification (after C3 training but before any C2/C3 gameplay): the
contrast list now explicitly includes the separately preregistered C4-C1 result,
and states that Holm adjustment covers the five binary contrasts. The originally
written phrase “four simple C1-relative” was internally inconsistent with the
listed contrasts. No gameplay result had been generated or inspected when this
wording was corrected.

Packaging amendment (before any C3 gameplay): inspection found that copying C0
also copied its non-executable order-policy manifest, whose policy hashes still
named A2. The training driver was amended to rewrite that manifest with the
already produced C3 policy hashes and a mechanistic-cell label, then rerun from
the frozen corpus and seed. The manifest is not read by `main.py` or the order
router; this prevents a new stale-provenance record without changing policy
code, weights, data, hyperparameters, endpoints, or the gameplay schedule. C2
gameplay already in progress is unaffected and uses a separate frozen package.

## Four cells

| Cell | Encoder | Policy weights | Frozen package/model evidence |
|---|---|---|---|
| C1 | historical blind v2 | original A2 | C0 tree `13426288358d597ead809e45c364c7f7b9274a6eebf55ddd942142e3326535c3`; A2 `b19871a9f1499c2460ae266e58194acab1d8c90b390fa5cf24ed94b9a2b6bda8` |
| C2 | identity-aware v2 | original A2 | P0 tree `36e804ae6c593db57b595bfca9fd48592da10957f0e5f840a7e390edbeb39b63`; A2 unchanged |
| C3 | historical blind v2 | same training as intervention | missing cell, to be created by `paper/scripts/train_blind_ablation.py` |
| C4 | identity-aware v2 | intervention trained heads | intervention tree `83489e0c80c631763c65375d2a7a34d28d6aa9fbb1d11e89d130c83b1e27f1c0`; model `cefe61189bc6f4e316212b19c99450e4b91ff1e5493f4467a95041c30fd96984` |

C2 is a mechanistic intervention, not a production candidate: enabling a new
feature against weights trained when that feature was always zero is
out-of-distribution. C3 is likewise diagnostic.

## C3 corpus and training

The retained identity corpus is
`restricted/path`, SHA-256
`a3d28e9c3ab650a1ec3c1cf708fc7684dc5258a86469d622871e7efe25dcdc40`.
The split manifest SHA-256 is
`8c13a5de5b34c3deec5909948fb8c03117048f0295140c48a0325550a9a1a774`.
For C3 only, every ordinary PLAY option (option type 7 with no raw area) has
`source_card` deterministically replaced by zero. All other bytes represented
by the decoded row are unchanged. The transformed gzip uses `mtime=0`; its
hash and counts are recorded before training.

Training invokes the same `train_candidate` implementation and realized intervention
settings: A2 initialization and teacher; seed 20260816; CPU; feature v2; AdamW
learning rate `1e-4`, weight decay `1e-5`; batch 256; three epochs; patience
three; distillation weight 0.5; gradient clipping 1.0; and trainable modules
`option_linear`, `score`, `count`, and `value`. The configured fresh weight is
0.999. The historical batch-rounding implementation is deliberately preserved,
so the expected realized mix is 100% fresh and zero rehearsal rows. Any nonzero
rehearsal count, changed frozen parameter, non-finite loss, missing epoch, or
model/package hash inconsistency invalidates C3.

## Matched gameplay evaluation

The primary ablation endpoint reuses the exact FRESH_CONFIRMATION_PROTOCOL
opponents, engine, orders, seeds, seats, pair count, and C0 comparator. C2 and
C3 each receive 200 candidate-control pairs per actual order against each of
the seven opponents (2,800 pairs/5,600 games per cell). C4 uses the already
preregistered fresh-confirmation rows; C1 is the within-pair control arm. Runs
stop only after every scheduled pair has completed or an invalidating error
occurs. No opponent, seed, package, or endpoint may be changed after results are
inspected.

The primary contrasts are C2-C1 (encoder only), C3-C1 (training under blind
encoding), C4-C1 (the separately preregistered fresh confirmation), C4-C2
(training under identity encoding), C4-C3 (encoder effect after training), and
the difference-in-differences interaction
`C4 - C3 - C2 + C1`. Each is the equal-weight mean of the 14 opponent-by-order
cells. Ninety-five-percent intervals use 100,000 paired, within-cell bootstrap
draws with seed 20260824. Exact two-sided McNemar tests and Holm adjustment
across the five simple binary contrasts are secondary. The interaction is
descriptive with its paired bootstrap interval because it is not a binary
McNemar contrast.
Draws count as non-wins. Policy or opponent errors, incomplete pairs, package
hash drift, production-engine mutation, or seed/seat mismatch invalidate the
affected run and are reported rather than silently excluded.

Head-only disagreement and held-out expert-action agreement are secondary
mechanistic diagnostics. They are never described as gameplay outcomes and do
not substitute for the four-cell matched evaluation.

## Known reproducibility limits

The source corpus and P0/C0 packages are ignored local artifacts and must be
hashed into every output. Original replay observations used to mine the corpus
were deleted by the historical pipeline, and no original environment lock was
retained. Therefore this protocol can reproduce training from retained feature
rows, but cannot reproduce feature extraction from original replay files.
