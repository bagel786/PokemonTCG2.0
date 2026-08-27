# Deviations Log (prospective repair campaign)

Format: D-R# / date / stage / trigger / correction / outcome-access / scope / integrity consequence.

| id | date | stage | trigger | correction | outcome access | scope |
|----|------|-------|---------|------------|----------------|-------|

Entries appear above this line as appended rows/sections. Empty at protocol authoring; must remain deviation-free through freeze for a clean freeze record.

## D-R1 — Post-freeze guard machinery patch

- **Date:** 2026-08-27 (before any holdout outcome existed)
- **Trigger:** freeze_guard initially required a fully clean worktree; an
  unrelated top-level untracked directory (`resource_envelope_study/`,
  belonging to another workstream) tripped it. The first final-runner launch
  raced past the refusal via shell backgrounding and was killed within a
  minute; no rows were written.
- **Correction:** guard cleanliness scoped to prospective_repair/** plus all
  tracked files; machinery patches allowed ONLY via an explicit
  `machinery_patch_log` inside FREEZE_RECORD.json naming file+reason+new hash;
  scientific inputs remain pinned to their frozen hashes from cfeef39.
- **Outcome access:** none — zero outcome rows existed at patch time
  (results/final/raw_rows.jsonl still absent).

## D-R2 — Post-outcome evidence-contract defects discovered; campaign fails closed

- **Date:** 2026-08-27 (after holdout outcomes were visible in analysis)
- **Trigger:** anomaly review of B7's official aggregates: (a) BRANCH_C strict
  detection missed exactly G08/G09/G18 on BOTH systems (160 cells each);
  (b) BRANCH_E false suppression = 100% of VALID-E holdem cells; (c) Ising
  BRANCH_D fs 454/560 concentrated with `sync_verified_stateful=False` across
  every valid-coupling construction.
- **Root causes (with anchors):**
  1. `runner/acquire.py run_pair`: reused-worker contamination rebuilt ctx
     records ONLY under `module_cache_contam_b`; queue-tax divergence reached
     replicas but the *claimed* cross-context scope was never propagated into
     `replay_scope_claimed` for decision-time routing of G08/G09/G18-type rows
     (bundle carried context divergence while classifier saw
     `within_artifact`).
  2. `runner/bundle_builder.py`: matched/unmatched event coverage included
     POLICY-SCOPED action keys (`|act`, step-dependent `acc|k`) in the shared
     ontology denominator, contradicting FAULT_GRAMMAR's exogenous/chance
     event semantics → G02 Guaranteed unmatched>0 whenever policies take
     different numbers of steps.
  3. Ising stateful synchronization check compared POSITIONS across mixed
     model/acceptance log streams whose interleaving legitimately diverges
     after the first differing acceptance, converting correct coupling into
     SUPPRESS despite `context_desync_of_coupled_stream=False`.
- **Classification:** output/evidence-contract defects, NOT mechanics or
  label errors; the mechanics-presence gate had correctly PASSED because
  mechanisms themselves fired as labeled.
- **Outcome access:** outcomes WERE visible when identified.
- **Disposition mandated by frozen protocol:** fail closed. No patched rerun
  may be described as confirmatory. Affected headline cells are marked
  DEFECT_AFFECTED; machine overall status becomes NOT_READY_DO_NOT_SUBMIT;
  the corrected evidence contract may be pursued ONLY as a NEW frozen
  campaign with fresh banks. Raw holdout (sha256
  792b6fd0a830c0c1b357becb0e7be661a8ceb9147b3a6ec2faadf604c5e447b1) is
  preserved untouched as the primary artifact for the eventual repair cycle.
