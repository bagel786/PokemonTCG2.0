# Seeded exact-Grim terminal-Q pilot

## Outcome

The Q-label path is now mechanically valid, but the useful signal is too sparse to train.
Across 92 A2 disagreement boundaries, one label survived two independent eight-world schedules
under the strict combined rule. No model was trained or packaged from that single label.

## Why the original pilot was invalid

The earlier blocked run had two RNG problems:

1. `AgentStart` seeded its search `Game` from `std::random_device`, so nominally identical repeats
   began from different streams.
2. More importantly, sibling search states reference the same owning `ApiData::game`. Rolling the
   A2 baseline first advanced that shared RNG before the candidate branch was evaluated. A single
   root therefore did not provide matched post-divergence counterfactuals.

The evaluation-only engine adds `SearchSetSeed`. Each arm now clears the search arena, resets the
shared RNG to the same literal `uint32_t` seed, reconstructs an independent root with the identical
hidden-zone determinization, applies its own first action, and rolls the resulting divergent branch
to a terminal result. Automatic coins use the seeded game RNG (`manual_coin=false`). Continuation
is seat-routed: deployed shielded A2 controls the root player and byte-exact d842 controls only the
opponent.

## Results

- Primary schedule (`20260811`): 92/92 complete, zero errors, four strict labels.
- Independent schedule (`20260812`): 92/92 complete, zero errors, one strict label.
- Combined confirmation: 1/92 survives all 16 worlds, with 9 strictly better, 7 equal, 0 worse,
  and mean terminal advantage `+1.125` on the `[-1, 0, +1]` outcome scale per arm.
- The surviving boundary changes a damage-counter target from the opponent's Bench to its Active.
- Forty-three of 92 proposed changes lost in at least one combined world; 37 were outcome-neutral
  in all 16 worlds. This explains why unfiltered disagreement imitation is unsafe.

The combined hash-bound manifest is
`artifacts/a2_rebased_mirror_q_pilot_seeded/combined_independent_confirmation.json`.
The two raw run manifests and row-level terminal outcomes remain in
`artifacts/a2_rebased_mirror_q_pilot_seeded/` and
`artifacts/a2_rebased_mirror_q_pilot_seeded_confirm/`.

## Isolation and verification

- Q engine: `artifacts/deterministic_q_engine/bin/cg.dll`, SHA-256
  `5CBF19DBD5D75891DA50599548716A0C3530D6159C303CB2F49C8B11C706A6B7`.
- Existing deterministic gameplay engine remained
  `11662D6D96FEBB8ACA8F500BDFDE520AE0F1686AB3959EEF90AA16C958E68188`.
- Production engine remained
  `EAE88634E26DC31D94150A4D8202FC9D32596B8C688EF67E14CB4088CD4D5771`.
- Focused tests: `pytest -q tests/test_build_a2_rebased_mirror_q_pilot.py tests/test_deterministic_crn.py`
  passed 11 tests.

This is a controlled local-source-engine result, not proof that the fresh-start DLL is byte-identical
to the competition runtime. The rows are development-only exact-Grim states and do not establish
cross-matchup generalization.
