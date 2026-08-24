# Paired Evaluation Validity Ladder synthetic testbed

This directory is a standalone, standard-library-only implementation of five
synthetic coupling-validation modes. It contains no restricted game engine,
card data, opponent package, policy weight, replay, or other case-study asset.

## Run

From this directory:

```bash
python pevl_synthetic.py generate
python pevl_synthetic.py verify
```

Use `--output-dir PATH` to write or verify another directory. The checked-in
`results/` directory contains:

- `pevl_results.json`: complete evidence, trace hashes, detection levels,
  statistical-admission decisions, and the draw-shift remediation;
- `pevl_results.schema.json`: Draft 2020-12 schema for the result document;
- `pevl_matrix.csv`: one row per failure mode and PEVL level;
- `MANIFEST.sha256`: exact SHA-256 hashes of the JSON, schema, and CSV files.

Generation and verification reject symbolic links rather than following them.

## What the modes establish

| Mode | Intended detection |
| --- | --- |
| Clean deterministic | Levels 1--7 pass; Level 8 admits the scoped event-aligned claim |
| Stateful draw shift | Level 7 detects misalignment; Level 8 downgrades to seed-matched-only wording |
| Wall-clock search | Levels 4--6 detect trace, worker-profile, and source-audit failures |
| Process-global state | Levels 4--6 detect trace, worker-reuse, and source-audit failures |
| `uint32` seed conversion | Level 2 detects a converted-seed collision |

For deterministic artifacts, the wall-clock mode uses an injected clock
profile and the process-state mode uses an injected worker counter. They retain
the causal structures being tested without depending on host timing or prior
process history.

The stateful draw-shift example shows why repeatability is not event-level
coupling: both arms reproduce exactly, but an intervention's extra PRNG draw
shifts every later shared event. The white-box remediation computes each random
quantity from `SHA256(seed_uint32, semantic_event_key)`, so unrelated events can
be inserted without shifting shared quantities.

Levels 1--7 are evidence gates with `pass`, `fail`, and `blocked` statuses.
Level 8 is instead reported as `admit`, `downgrade`, or `suppress`, matching its
role as the prespecified claim-admission decision. The included artifact hashes
and execution records are synthetic fixtures illustrating the required evidence
shape, not identities for any external study artifact.

This executable counterexample suite illustrates the validation method; it does
not by itself validate any external agent, simulator, or statistical claim.
