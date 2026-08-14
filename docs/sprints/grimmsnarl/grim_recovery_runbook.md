# Grimmsnarl recovery runbook

All commands run from the repository root with `vendor` and the root on `PYTHONPATH`.
No upload command is part of training or evaluation.

## A-probe shipment

1. Crawl certified daily data:

   `python scripts/crawl_grim_daily.py --start-date 2026-08-06 --feature-version 3 --workers 8`

2. Build immutable probes and exact control:

   `python scripts/build_recovery_probes.py`

3. Replay audit:

   `python scripts/audit_recovery_probes.py`

4. Run final Azure mirror and authentic phases:

   `python scripts/run_azure_recovery_farm.py --phase probes`

   `python scripts/run_azure_recovery_farm.py --phase authentic`

5. Build preflight and immutable promotion manifests:

   `python scripts/build_probe_preflight.py`

   `python scripts/build_authentic_probe_manifest.py`

   `python scripts/decide_recovery_probe.py --authentic-manifest artifacts/recovery_probes/authentic_manifest.json --preflight-manifest artifacts/recovery_probes/preflight_manifest.json`

6. Inspect `promotion_manifest.json`. Uploading is a separate, authenticated action:

   `python scripts/upload_recovery_probe.py`

The uploader verifies every archive hash and forces challenger-then-control order. If
no challenger passes, it uploads only exact d842. It refuses planned uploads after
August 11 Central Time.

## B-family program

1. Create behavior-preserving schema 3:

   `python scripts/pad_d842_schema3.py`

2. Mine conservative loss corrections after the certified split exists:

   `python -m training.mine_recovery_corrections --max-rows 5000 --recent-days 7 --determinizations 8 --rollout-steps 96 --max-alternatives 2`

3. Assemble the observation-free bounded training streams:

   `python -m training.train_recovery_candidates --assemble-only --recent-winner-cap 200000 --legacy-rehearsal-cap 20000`

4. Train B1 and B2 over the three configured seeds on the Azure pool:

   `python scripts/run_azure_recovery_training.py`

5. Package all six candidates and build/verify the authentic opponent population:

   `python scripts/train_behavior_clones.py --input-dir data/grim_daily_v3/behavior_shards`

   `python scripts/build_recovery_candidates.py`

   `python scripts/build_recovery_opponents.py`

   `python scripts/verify_recovery_opponents.py`

6. Screen seeds, then run the resumable full population gate:

   `python scripts/run_azure_recovery_final.py --phase screen`

   `python scripts/run_azure_recovery_final.py --phase full`

7. Build the exact shard map and apply the final promotion gate:

   `python scripts/build_final_gate_config.py`

   `python scripts/decide_final_candidate.py --config artifacts/recovery_final/final_gate_config.json`

8. Only after inspecting a `passed` manifest, upload the selected finalist:

   `python scripts/upload_final_candidate.py --mode selected`

   The contingency command is permitted only after a ladder hard-fail and uploads
   the already-qualified contingency followed by exact d842:

   `python scripts/upload_final_candidate.py --mode contingency`

## Ladder and Azure controls

- `training.ladder_policy.assess_ladder` implements the 20/40/75-game rules and
  the 1025 checkpoint plus continuous 48-hour hold above 1000.
- `python scripts/monitor_recovery_ladder.py` appends Kaggle rating snapshots and
  remains in `observe` state until certified per-game evidence is placed at
  `artifacts/recovery_ladder/games/<submission_id>.json`.
- Azure execution uses regular on-demand workers, a conservative $0.50 per-worker
  hourly accounting rate, and a hard $140 projected-spend ceiling.
- Run `python scripts/cleanup_recovery_azure.py` for a dry run, then add `--execute`
  on or before August 10 to delete only the named ephemeral recovery groups.

## Schema-5 breakthrough program (M0 then D1)

The schema-5 program is intentionally fail-closed. A training manifest is not a
promotion result, and neither packaging nor a good replay-agreement score authorizes
an upload.

### Certified inputs

- The causal August 6 stream is under `data/grim_daily_v5_causal`. Follow-up CARD
  selections bind the effect card as their source and the chosen instance as their
  target. Earlier schema-5 exports without this property are invalid.
- `python scripts/build_schema5_breakthrough_corpus.py` creates whole-episode
  training/validation streams and untouched clone qualification streams.
- flg team `16380946`, submission `55290684`, contributes 179 usable public games.
  It is a two-card exact-list variant and is isolated in `flg_variant_only`.
- `python scripts/build_schema5_policy_identity_holdout.py` creates the untouched
  Ajay/Treecko cross-policy screen. It is never training-eligible.
- `python scripts/build_schema5_mirror_bank.py <validation streams...>` creates the
  turn-two Munkidori, Adrena-Brain, Shadow Bullet, search, and sequencing slices.

### M0 execution

1. `python scripts/run_azure_schema5_training.py` trains six deterministic seeds
   for every candidate family and three seeds for each of four independent clones.
2. Reject teacher-specific models that fail the untouched policy-identity screen.
   A model must beat R0 by eight complete-action agreement points on branching
   decisions; its own-source validation score is not sufficient.
3. Clone qualification requires the frozen category agreement thresholds, sequence
   distribution checks, zero errors, and 2,000 balanced-order games against exact A2.
4. Package a screen survivor with
   `python scripts/package_schema5_breakthrough.py --mode m0 --model MODEL --output ARCHIVE`.
   This preserves R0 outside a strict, publicly confirmed exact-Grim route.
5. Run the 2,000-game kill screens, followed by the frozen 12,000-game M0 gate.
   Only an explicit passed promotion manifest can authorize an upload.

### D1 implementation

D1 is a global direct policy, not another A2 residual. The direct model consumes
stable card/slot entities, attached HP/Energy/tool/evolution state, complete legal
actions, actual order, and a causal 16-event current-turn stream. Its loss is
autoregressive Plackett-Luce likelihood for the teacher's ordered complete action
plus a masked count loss. Certified alternatives add a pairwise complete-action
ranking term; there is no scalar value policy.

1. Enable tracing with `PTCG_TRACE_DIR` while rolling the strongest qualified M0
   family against the four independent clones. Traces contain only live-visible
   schema-5 state and the candidate's complete action.
2. Use `scripts/label_schema5_consensus.py` to query four hash-distinct clones.
   Admit an on-policy imitation label only when at least three clones choose the
   same complete action.
3. Complete-turn counterfactual mining supplies preferred and rejected complete
   actions only when coverage, terminal completion, and confidence checks pass.
   Truncated or unequal-coverage comparisons are discarded.
4. `scripts/build_d1_schema5_corpus.py` assembles an episode-balanced mixture:
   65% strongest teacher/M0 family, 20% on-policy consensus, 10% certified pairwise
   corrections, and at most 5% R0 rehearsal. Episode IDs are exclusive across
   training and validation.
5. Initialize D1 from the strongest coherent M0 seed and train multiple seeds.
   Selection is based on cross-policy gameplay, critical-state adoption, and the
   worse actual-order stratum—not training loss.
6. Create `direct_runtime.json` only after held-out context regression analysis.
   It is bound to the model SHA-256 and lists enabled and disqualified contexts.
   Unrepresented contexts, load/inference errors, and non-finite scores fall back
   to R0 and are counted in telemetry.
7. Package with
   `python scripts/package_schema5_breakthrough.py --mode d1 --model MODEL --runtime RUNTIME --output ARCHIVE`.
   Run the frozen 20,000-game-per-arm population gate before upload.

S1 complete-turn search starts only after a D1 model passes. It never scores an
unfinished turn and cannot delay or replace the model-only D1 confirmation.
