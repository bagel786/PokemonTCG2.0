# Fresh A2 on-policy terminal-Q screen

## Result

Fresh on-policy collection found real local corrections, but only three robust labels across three
source games. That is far below the predeclared minimum of 20 labels across 10 games, so no model
was trained and no policy was packaged.

The source was 16 seeded exact-Grim mirror games with deployed, shielded A2 as hero and byte-exact
d842 as the fixed opponent. Forty-eight consequential single-choice states were selected from 948
eligible A2-reached boundaries across 15 games, without using rollout outcomes. Alternatives came
from d842, the strongest temporal continuation, the A2 network ranking, and exhaustive semantic
choices when there were at most six legal options.

Successive halving used disjoint terminal-rollout schedules:

- Phase 1: 11/48 alternatives had positive mean advantage in four paired worlds; 12 advanced.
- Phase 2: 7/12 remained positive in 12 fresh paired worlds; seven advanced.
- Phase 3: 3/7 met the prespecified robustness rule in 32 fresh paired worlds.

Individual negative worlds were allowed. A robust label required positive fresh mean advantage,
positive bootstrap two-sided and normal one-sided 95% lower bounds, and both sign-test and
normal-mean Benjamini-Hochberg q-values at most 0.10.

## Robust labels

| Prompt | A2 choice | Alternate | Fresh better / worse / equal | Mean delta | Bootstrap 95% interval |
|---|---|---|---:|---:|---:|
| `TO_ACTIVE` | Grimmsnarl ex, 310/320 HP, 1 Darkness | Grimmsnarl ex, 300/320 HP, 2 Darkness | 11 / 0 / 21 | +0.6875 | [+0.3750, +1.0000] |
| `SWITCH` (Boss) | Opposing Munkidori, 90/110 HP, 0 Energy | Opposing Munkidori, 100/110 HP, 1 Darkness | 12 / 1 / 19 | +0.6875 | [+0.3125, +1.0625] |
| `SWITCH` (Boss) | Opposing Munkidori, 40/110 HP, 1 Darkness | Opposing Munkidori, 100/110 HP, 1 Darkness | 9 / 0 / 23 | +0.53125 | [+0.2500, +0.84375] |

Terminal arm scores are `-1`, `0`, or `+1`, so paired deltas range from `-2` to `+2`. Each label
was positive in the four-, twelve-, and thirty-two-world schedules.

## Cross-state pattern audit

The two Boss labels point in the same direction: among opposing Munkidori, the better outcome came
from choosing a strictly healthier target whose attached Energy count was no worse. The other three
screened Boss states do not justify broadening this into a rule:

- two alternatives gave up an attached Energy; one was neutral in four worlds and the other became
  negative in the fresh twelve-world stage;
- one alternative traded lower HP for an attached Energy and was neutral in four worlds.

The four `TO_ACTIVE` states are compatible with a lexicographic hypothesis among same-species
Grimmsnarl ex: prefer attached Energy first, then remaining HP. The robust state favored two Energy
over one despite a 10-HP cost, while a different equal-Energy choice of a 280-HP Grimmsnarl over a
310-HP one was negative in phase 1. The two other promotion states involved different evolution
stages and were neutral.

These are useful collection hypotheses, not a defensible generalized rail. Each pattern has only
two directly applicable fresh states, and no selection-independent gameplay test. Encoding them now
would be exactly the kind of narrow, post-hoc rule that made strategic v2 brittle.

## Search coverage edge case

An initial version selected seven `ATTACH_FROM` boundaries. Every world at all seven failed before
scoring because the public-state hidden-pool determinizer was exactly one card short. This is a
mid-effect prompt: one transient card is not represented in the zones counted by the current
determinizer. The final screen excluded this prompt and then completed with zero rollout errors.

This does not affect deployed A2 because search is disabled. It does mean a future search agent
cannot claim universal prompt coverage until `ATTACH_FROM` is modeled or explicitly gated; otherwise
search will fail and fall back precisely at these attachment decisions.

## Reproducibility

- Manifest: `artifacts/fresh_a2_onpolicy_q_screen/manifest.json`
  (`4791DB53A09835876540313D9FA3885809348A4AB9929590DB6CD523E143BA80`)
- Robust rows: `artifacts/fresh_a2_onpolicy_q_screen/robust_fresh_labels.jsonl.gz`
  (`7CE45835A155A048DFD774F1A49F428FA8F2E0DFCA3BC25C841B65E328549037`)
- Source rows: `artifacts/fresh_a2_onpolicy_q_screen/fresh_source_boundaries.jsonl.gz`
  (`BD3C5C1446C0B1658925D15EB5DBD550A3F92DD547B1672295BB012FBA4E5B3C`)
- Reproduction script: `scripts/run_fresh_a2_onpolicy_q_screen.py`
  (`FCBD2E470CE1532E87D370F438B78D71888F7A89401264DA7204876269C13881`)
- Evaluation engine: `artifacts/deterministic_q_engine/bin/cg.dll`
  (`5CBF19DBD5D75891DA50599548716A0C3530D6159C303CB2F49C8B11C706A6B7`)
- Production engine was preserved at
  `EAE88634E26DC31D94150A4D8202FC9D32596B8C688EF67E14CB4088CD4D5771`.

This is a controlled local-source-engine, exact-Grim development result. It does not establish
cross-matchup generalization or byte identity with the competition engine.
