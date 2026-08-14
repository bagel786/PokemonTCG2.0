# Seeded Q expected-advantage audit

## Result

Relaxing the original rule was correct, but it does not unlock enough labels to train a policy.
The original rule required every sampled world to be nonnegative. This audit instead allows an
alternate action to lose some worlds and asks whether its paired *mean terminal outcome* is
reliably positive.

The two frozen eight-world schedules were used only for selection. Of 92 boundaries, 22 had a
nonnegative mean in each schedule and a positive combined mean. Those 22 were evaluated on a
fresh, independent 32-world schedule (`20260813`): 704 paired terminal worlds, complete terminal
coverage, zero scoring errors, and a repeat-stable fixed-boundary determinism check. The fresh
rollout cap was 512 steps; no truncation was converted to a draw.

Fifteen of 22 selected boundaries retained a positive mean, three were exactly neutral, and four
became negative. Only three met the prespecified stability rule: positive fresh mean, positive
bootstrap and normal-approximation 95% lower bounds, and both paired-sign and mean-test
Benjamini-Hochberg q-values at most 0.10 across all 22 tests.

| Boundary | Change | Fresh worlds (better / worse / equal) | Fresh mean delta | Bootstrap 95% interval |
|---|---|---:|---:|---:|
| `91137173:0:155` | Attack 937 instead of retreat | 16 / 0 / 16 | +1.0000 | [+0.6250, +1.3750] |
| `91117786:0:47` | Search Rare Candy instead of Unfair Stamp | 11 / 1 / 20 | +0.6250 | [+0.2500, +1.0000] |
| `91090742:1:141` | Move Munkidori counters to Active Grimmsnarl ex instead of Benched Impidimp | 9 / 0 / 23 | +0.5625 | [+0.2500, +0.8750] |

Terminal score is `-1`, `0`, or `+1` per arm, so the paired delta ranges from `-2` to `+2`.
The three labels span only three episodes, three candidate semantics, and two prompt types. That
is nowhere near enough independent support for a neural update, and encoding three exact replay
states as rules would be replay overfitting. No model was trained or packaged.

## What this says about the earlier Q benchmark

The all-worlds-nonnegative rule was too severe: expected-advantage confirmation found two robust
labels beyond the one it retained. It was not, however, hiding a large correction corpus. Across
all 92 original boundaries, only 23 had a positive combined mean, 41 were neutral, and 28 were
negative. The two eight-world schedule means had Pearson correlation `0.493`, so rank ordering at
that sample size is noisy. Even after a permissive two-schedule screen, 7/22 candidates failed to
remain positive on fresh worlds. The sensible interpretation is sparse real signal plus substantial
winner's-curse noise, not a missed high-volume training path.

The strongest three actions may be useful as hypotheses for future on-policy state collection, but
they are not a defensible standalone policy family or evidence for a major rating improvement.

## Reproducibility

- Analysis manifest: `artifacts/a2_rebased_mirror_q_expected_resample/manifest.json`
  (`BB2F41C138D15930C4DDA30F9128A580528604CC13349D18EC10701E041820D6`)
- Fresh row-level outcomes: `artifacts/a2_rebased_mirror_q_expected_resample/confirmation_candidates.jsonl.gz`
  (`B797849FC52F4C06B82B0BC7DB6B40B628FCD8693EA2F6FA0280B191FA04744D`)
- Stable labels: `artifacts/a2_rebased_mirror_q_expected_resample/stable_labels.jsonl.gz`
  (`DC2C1076053C226A4D37B3479372CB0EBF7FB5020B0A837ECA7C07C3F61888B7`)
- Evaluation engine: `artifacts/deterministic_q_engine/bin/cg.dll`
  (`5CBF19DBD5D75891DA50599548716A0C3530D6159C303CB2F49C8B11C706A6B7`)
- Reproduction script: `scripts/resample_seeded_q_expected_advantage.py`

This remains a controlled local-source-engine, exact-Grim development result. It is not a claim
of cross-matchup generalization or competition-engine byte identity.
