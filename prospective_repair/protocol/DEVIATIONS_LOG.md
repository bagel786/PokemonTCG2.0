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
