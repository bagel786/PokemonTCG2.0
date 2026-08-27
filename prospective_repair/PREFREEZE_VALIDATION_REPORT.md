# PREFREEZE VALIDATION REPORT — prospective repair campaign

Date: 2026-08-27 · Status: **ALL GATES GREEN — ready for verified remote freeze**
Interpreter note: campaign reuses the verified pinned dependency environment
`redesign/.venv` (python 3.11.5; rlcard==1.2.0; ising-monte-carlo-toolkit==0.1.0;
numpy/scipy per installed lock). Tests bootstrap that site-packages via
`tests/conftest.py`; nothing was reinstalled or unpinned.

## 1. Test battery

| layer | command | result |
|---|---|---|
| unit/property/integration suite | `python3 -m pytest prospective_repair/tests/ -q` | **47 passed** |
| analysis-pipeline fixtures | included above (`tests/test_analysis_pipeline.py`) | 4 passed |

Coverage highlights enforced by named tests: Branch-B independence (6 required
regressions incl. shared-seed-alone suppression + unknown-evidence fail-closed),
expected-table↔grammar consistency (185 cells), monotonicity under evidence
removal (I2), fail-closed missing evidence (I3), projection scoping (I4),
process determinism (I5), result-exclusion of decisions from outcome values,
baseline capability honesty + typed-view leakage + mutation degradation +
real-A/A consumption for B1 + B4 dead-code absence, hold'em same-policy
reproducibility / cross-policy divergence / G19-by-design collapse / real
timings, ising sampler-actually-consumes-keyed-RNG draw-count proof /
clock-residual repeat divergence / cache & queue analogs / shared-namespace
collisions, event-key order invariance + substream independence + marginal
flatness, genuine cross-process replica separation, schema rejection of
z-test columns & zero timings, redesign/** byte-preservation vs HEAD,
documentation-reference resolution, registration-wording discipline.

## 2. Result-excluded bank validations (acquired pre-freeze)

| bank | rows | sha256(raw) | crashes | mechanics gate |
|---|---|---|---|---|
| pilot_mechanics (16 seeds × both systems) | 25,120 | `77dbdba945035a1c98eed083405692687cee33479b2c96fed70d910c90ab9ddf` | 0 | **PASS 304/304** |
| dev (12 seeds × both systems) | 18,840 | `4e0a012c5ef9f6804d312738658c6984a32333702ae36323570209ee870c4955` | 0 | **PASS 228/228** |
| cost smoke (3 seeds × 3 reps × {G01,G07} × both systems × 8 methods) | 288 cost rows | local-only | 0 | n/a (timing/schema only) |

Mechanics gate inspected ONLY crash records, schema legality, timing
positivity, and injected-mechanism presence (digest divergence classes, key
collisions, cross-process pid/digest, truncation effective seeds, policy
contrast preserved/collapsed-as-labeled). No detection rates, effects,
rankings, or variance ratios were computed or viewed from any bank.
Command: `python3 prospective_repair/analysis/check_mechanics.py <bank_dir>`.
Bank raw JSONL/state files remain LOCAL under `results/**` (gitignored);
their hashes are recorded here and will be superseded by final acquisition.

Two implementation defects found AND fixed by this gate before freeze:
persistence-offset arm scoping (G15) and holdem shared-namespace collision
counters (G16); plus checker expectation fixes (repeat-id parsing). History in
git log on `paper/claim-specific-prospective-repair-20260827`.

## 3. Expected-decision table consistency

`protocol/EXPECTED_DECISION_TABLE.json` regenerated mechanically from the
frozen grammar + repaired classifier/baselines: **B7 agrees with grammar truth
on all 185 decision cells** (script:
`runner/gen_expected_table.py`; assertion lives in
`tests/test_classifier_semantics.py`).

## 4. Known limitations carried into the frozen run

- Think-budget wall-clock dependence: consumption has a rank-determined
  deterministic minimum plus a deadline-bound tail (documented in grammar
  mechanism text); deadline tails make trajectories scheduler-sensitive BY
  DESIGN under G07/G11 (that is the fault being modeled).
- perf_counter/process_time granularity: floor-guarded (a zero duration
  raises instead of being recorded).
- Holdem collision namespace produces duplicate ids within arm B's keyed log;
  value-level comparison then intentionally finds unequal values on collided
  ids — the labeled D/E-suppressing mechanism.

## 5. Freeze readiness checklist

- [x] all protocol artifacts complete under `prospective_repair/protocol/`
- [x] seed banks generated once, regeneration-stable, pairwise disjoint, and
      disjoint from ALL V1 seeds (`runner/seeds_gen.py` exit-checked)
- [x] final runner hard-gates on remote-freeze verification (`runner/freeze_guard.py`)
- [x] output schemas forbid M4–M6-style outputs and legacy z-test columns
- [x] `redesign/` untouched (test-enforced each run)
- [x] registration wording discipline tests green (private-remote language)

Next step: commit protocol/code/test state → record FREEZE SHA → write
FREEZE_RECORD.json (ancestor semantics) → annotated tag
`claim-specific-prospective-repair-freeze-20260827` → push branch+tag →
remote verification → ONLY THEN launch final holdout + full cost bank.
