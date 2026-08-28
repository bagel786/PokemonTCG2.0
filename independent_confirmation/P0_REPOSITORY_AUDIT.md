# Repository lineage and preservation audit

Audit time: 2026-08-28T00:31:30Z

Status: PASS for lineage resolution; the prior campaign remains failed and immutable.

## Repository authority

- Repository: `bagel786/PokemonTCG2.0`
- Remote URL: `https://github.com/bagel786/PokemonTCG2.0.git`
- GitHub visibility, queried with authenticated `gh repo view`: `PRIVATE`
- Audited local checkout: `/Users/safiullahbaig/Projects/pokemonTCG2.0`
- Audited local branch: `paper/claim-specific-prospective-repair-20260827`
- Local SHA before branching: `91ad7fa9571ee0ca10200fd7fe7b589589e8b794`
- Remote branch SHA after `git fetch origin --tags`: `91ad7fa9571ee0ca10200fd7fe7b589589e8b794`
- Divergence from the previously audited head: `0` commits ahead, `0` commits behind
- Base tree: `2da5dc0a0d9de11c042ee252fecaa88f7faf177c`

The initially supplied working directory, `/Users/safiullahbaig/Projects/pokemon_research`, is a different repository (`bagel786/vgc-team-completion`). It was inspected read-only, then left untouched. The requested repository was found at the case-sensitive sibling path above.

## Applicable instructions

No `AGENTS.md` exists in the target repository or an applicable parent directory. Repository-local protocol and preservation instructions under `prospective_repair/` were inspected. The takeover brief is the controlling campaign specification.

## Working trees and branches

The audited original worktree contained one unrelated untracked file:

- `resource_envelope_study/runs/smoke_local/raw_cases.jsonl`
- size: 2,898,342 bytes
- SHA-256: `fbd14392f6dd852b0d456291c6cb376df386ab48e231fee810a71a2b85138dba`

It was not opened as evidence, modified, staged, moved, or deleted. To avoid disturbing it, the new branch was created in a separate worktree:

- New branch: `paper/claim-specific-independent-confirmation-20260828`
- Exact base SHA: `91ad7fa9571ee0ca10200fd7fe7b589589e8b794`
- New worktree: `/Users/safiullahbaig/Projects/PokemonTCG2.0-independent-confirmation-20260828`
- Initial new-worktree status: clean

## Tags and freeze history

The repository contains seven historical backup tags and one claim-specific freeze tag. The relevant annotated tag resolves on the private origin as:

- tag ref object: `cb88ce6f27739bc71c2aa434e9c3a5d602bd2de3`
- tag: `claim-specific-prospective-repair-freeze-20260827`
- peeled commit: `2bf3cea7a8a31b8e06dda814200ae83c20a163a0`
- freeze-input ancestor recorded by the freeze record: `cfeef395ed708ef640ff8e7322b8f2e1ec7550cb`

All 27 path/hash pairs in `prospective_repair/protocol/FREEZE_RECORD.json` were recomputed from the freeze-input commit using `git show` and SHA-256. All 27 matched. The tag and peeled target also matched `git ls-remote` on origin. The record correctly describes a private Git-timestamped freeze, not a public preregistration.

## Raw-data preservation

- Prior raw holdout rows: 125,600
- Prior uncompressed raw holdout SHA-256: `792b6fd0a830c0c1b357becb0e7be661a8ceb9147b3a6ec2faadf604c5e447b1`
- Prior cost-bank rows: 4,800
- Prior uncompressed cost-bank SHA-256: `17c1f296bf6821ea5638109e329e0122f6e40fc3528c04f56935c9fb4a2e8237`
- Tracked compressed raw archive SHA-256, from the integrity record: `b22ad70dfe9732990184e0a8ee117193bb385dca92388f2ea236c8092b04919b`
- Tracked compressed cost archive SHA-256, from the integrity record: `e1cf7efaaa3cb14abdeef3bed05e81d9fe720c8f3aefac857aa2d741ef11589b`

The local uncompressed files matched the recorded hashes, and both tracked XZ archives passed `xz -t`. No raw file was changed.

## Prior campaign disposition

The first prospective-repair campaign is preserved at the base commit with D-R1 and D-R2 intact. Its machine status is `NOT_READY_DO_NOT_SUBMIT`. The following already-exposed facts are preserved only as failed-campaign evidence:

- B7 strict detection: 3,720/4,320 (`0.861111...`)
- B7 false suppression: 747/6,000 (`0.1245`)
- post-outcome evidence-contract defects affecting Branch C, Branch D, and Branch E

The takeover audit independently confirmed additional contradictions in the failed package: `results/final/run_meta.json` records `freeze_sha: null`; the manuscript contains effects outside `[-1,1]`; the cost table is empty; the CRN-benefit section has no eligible cells; and the five-row claim ledger is incomplete. These facts must not be reinterpreted as a valid negative result about the proposed framework.

## Integrity conclusion

Repository lineage, remote authority, freeze ancestry, tag identity, and raw-data hashes are resolved. The new campaign may therefore record a novelty decision without altering the failed campaign. No confirmatory outcome for a new campaign exists or was accessed.
