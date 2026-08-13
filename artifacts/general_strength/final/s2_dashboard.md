# Dipplin general-strength dashboard

Candidate: Dipplin S1
Source: `a73f2fbf31494ebd97bc2e9357600388fe0805d5`
Package SHA-256: `ec74efe096473c58a2057cabfee93bf337bc18848c202a6e3d36bcba802db171`
Verified tree SHA-256: `940654489ea1f286982226f1f0cba4dd7340378b997a3f88ab6915c5d67f6c98`
Runtime tree SHA-256: `d5aaefab29b5850b298810c21dc628880822381c05bdbad5ecea1716bcef4241`

## Strong anchors

| Opponent | First | Second | Overall |
|---|---:|---:|---:|
| A2 Grimmsnarl (exact) | 50.00% | 51.00% | 50.50% |
| Alakazam 2.4a (authentic) | 59.00% | 33.00% | 46.00% |
| Alakazam 2.7 (authentic) | 48.00% | 39.00% | 43.50% |
| d842 Grimmsnarl (exact) | 60.00% | 48.00% | 54.00% |

Anchor macro: 48.50%; first: 54.25%; second: 42.75%; robust min: 42.75%.

## Same-deck and replay evidence

- Stages: stage1=STRONG, stage2=KILL.
- s1_vs_s1_first: 60.40%
- s1_vs_s1_second: 39.40%
- candidate_vs_s1_first: not run
- candidate_vs_s1_second: not run
- replay_validation: 50 episodes; expert dominates 1.42%; agent dominates 0.83%.
  - EQUIVALENT: 56.93%
  - AGENT_DOMINATES: 0.83%
  - EXPERT_DOMINATES: 1.42%
  - INCOMPARABLE: 1.33%
  - UNCERTIFIABLE: 39.49%
- sealed_replay_holdout: 0 episodes; expert dominates n/a; agent dominates n/a.
- frozen validation manifest: 50 episodes; input status FROZEN_INPUT.
- frozen final_holdout manifest: 30 episodes; input status FROZEN_INPUT.

## Actual-second traced buckets

Eligible traced games: 400; wins: 171; win rate: 42.75%.
Top outcome-independent opportunity bucket: grookey_active. Aggregate-only context sources: 8; not merged as per-game evidence.
Setup-choice causal audit: 5000 aggregate actual-second openings; Grookey had selectable Volbeat in 2.38%; diagnostic only, excluded from strength.

## Safety and operations

Failures: 0; policy errors: 0; illegal actions: 0; unknown contexts: 0.
Latency mean: 131.11496295067866 ms; p95 ceiling: 655.4782485502074 ms; p99 ceiling: 674.718723888509 ms; max: 899.2070420063101 ms.
Mechanics: PASS (15 passed, 0 failed).

## Frozen provenance

Qualification: NOT_APPLICABLE_AFTER_S2_REJECTION; sealed receipt: NOT_RUN_NOT_APPLICABLE_AFTER_S2_REJECTION.
Precommitted Stage6 promotion gate: NOT_APPLICABLE_AFTER_S2_REJECTION. A future promotion requires zero candidate proposal/policy/action-instability errors, <=50% combined uncertifiable/incomparable decisions, and expert-dominates episode rate no greater than agent-dominates. This is a conservative pre-look eligibility veto, not a strength estimate.
Weak clones: Mega Lucario (NOT_RUN_UNAVAILABLE_NO_CURRENT_CANDIDATE_EXECUTION), Crustle / Kangaskhan (NOT_RUN_UNAVAILABLE_NO_CURRENT_CANDIDATE_EXECUTION), Teal Mask Ogerpon (NOT_RUN_UNAVAILABLE_NO_CURRENT_CANDIDATE_EXECUTION), Bellibolt (NOT_RUN_UNAVAILABLE_NO_CURRENT_CANDIDATE_EXECUTION), Starmie / Froslass (NOT_RUN_UNAVAILABLE_NO_CURRENT_CANDIDATE_EXECUTION), Dragapult (NOT_RUN_UNAVAILABLE_NO_CURRENT_CANDIDATE_EXECUTION), Mega Lopunny (NOT_RUN_UNAVAILABLE_NO_CURRENT_CANDIDATE_EXECUTION), Garchomp (NOT_RUN_UNAVAILABLE_NO_CURRENT_CANDIDATE_EXECUTION).
- linux_x86_64_complete_game: PASS; 2 complete games; tree `940654489ea1f286982226f1f0cba4dd7340378b997a3f88ab6915c5d67f6c98`.
- s2_linux_x86_64: NOT_APPLICABLE_AFTER_S2_REJECTION; None complete games; tree `None`.

No composite magic score is computed. Weak-clone win rates are ceilinged and excluded from strength evidence.

Final verdict: **KEEP_S1**.
