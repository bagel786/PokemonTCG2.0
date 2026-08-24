# Paired Evaluation Validity Ladder synthetic testbed

This fully inspectable, standard-library-only testbed demonstrates why a
matched seed schedule is not by itself evidence of a valid stochastic
coupling. It accompanies the Paired Evaluation Validity Ladder (PEVL) without
using the restricted game engine, card data, opponent packages, policy weights,
or any other case-study asset.

The standalone implementation is shipped in
[`../release/synthetic/pevl_synthetic.py`](../release/synthetic/pevl_synthetic.py).
The local `pevl_synthetic.py` launcher exposes the same API and writes to this
directory's `results/` folder by default.

## Demonstrated modes

| Mode | Intended detection |
| --- | --- |
| Clean deterministic | Levels 1--7 pass; Level 8 admits the scoped event-aligned claim |
| Stateful draw shift | Level 7 detects misalignment; Level 8 downgrades to seed-matched-only wording |
| Wall-clock search | Levels 4--6 detect trace, worker-profile, and source-audit failures |
| Process-global state | Levels 4--6 detect trace, worker-reuse, and source-audit failures |
| `uint32` seed conversion | Level 2 detects a converted-seed collision |

The wall-clock fixture uses an **injected monotonic-clock profile**, not live
timing. This preserves the mechanism—available time changes search depth and
the selected action—while keeping every published byte reproducible. The
process-global fixture similarly injects a worker's starting counter rather
than relying on the host process history.

The draw-shift fixture is deliberately subtler. Each stateful-PRNG arm repeats
perfectly, so identical-arm and worker-parity checks pass. The treatment
consumes an additional draw, however, and later random quantities refer to
different modeled events. Level 7 catches the misalignment. The included
white-box remediation derives each quantity as
`SHA256(seed_uint32, semantic_event_key)`, which restores alignment for all
shared events even when one arm adds an unrelated event.

## Generate and verify

Run from the repository root:

```bash
python paper/synthetic/pevl_synthetic.py generate
python paper/synthetic/pevl_synthetic.py verify
```

The generator writes:

- `results/pevl_results.json`: complete audit evidence, trace digests, caught
  levels, admission decisions, and remediation evidence;
- `results/pevl_results.schema.json`: a Draft 2020-12 JSON Schema for the
  report structure;
- `results/pevl_matrix.csv`: one machine-readable row per mode and PEVL level;
- `results/MANIFEST.sha256`: deterministic SHA-256 hashes for all three data
  and schema files.

Use `--output-dir PATH` with either command to target a temporary or external
directory. `verify` rebuilds all artifacts in memory, compares exact bytes, and
rejects missing, modified, or unexpected files or directories. Level statuses
are deliberately typed: Levels 1--7 use `pass`, `fail`, or `blocked`; Level 8
uses `admit`, `downgrade`, or `suppress` because it is a claim-admission
decision, not another evidence gate. Symbolic links are rejected rather than
followed during generation or verification.

## Interpretation boundary

This is an executable counterexample suite, not evidence that any particular
external simulator contains these defects. A passing synthetic mode also does
not validate an external experiment. The testbed documents the observations
each PEVL rung can and cannot establish so that a real protocol can fail closed.
Artifact hashes and execution records in this package are synthetic fixtures;
they illustrate the minimum evidence shape and do not identify external study
artifacts.
