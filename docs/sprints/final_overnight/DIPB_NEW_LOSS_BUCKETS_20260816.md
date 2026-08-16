# DIP_B NEW LOSS BUCKETS — 2026-08-16 (17:35 CDT)

Fresh fetch of `55562629` (DIP_B): 29 episodes total (was 18 at 16:55 CDT).
All 29 replays synced locally to
`PokemonTCG2.0-overnight/data/replays/55562629/`.

## 1. Overall record

- **16W-13L (55.2%)** over 29 games.
- Trajectory: 8-1 through 93747403 (21:30 UTC), then **7-12** over the last
  19 games. DIP_B is the flopping submission of the active pair.
- EXP23 (55556726) unchanged at 33 games, 19W-14L — stable.

## 2. Loss buckets (13 losses)

| bucket | record | losses (end prizes, first Grim) |
|---|---|---|
| Grimmsnarl mirror | 2W-5L (1 win = self-match) | 93743797 (6v1 blowout, t4), 93746552 (3v2, t3), 93748360 (2v1, t7), 93752006 (3v3, t8), 93758218 (4v2, t6) |
| Alakazam | 8W-3L | 93756544 (3v2, t4), 93753793 (1v2, t5), 93751091 (1v1, t7) |
| Dragapult | 0W-2L | 93745631 (2v1, t7), 93755661 (2v2, t7) |
| Crustle/Kangaskhan | 1W-2L | 93744693 (5v1 blowout, t8), 93750153 (2v2, t4) |
| Other | 5W-1L | 93761111 (5v1, t4) vs **Teal Mask Ogerpon ex / Pinsir** |

## 3. Router verification on the 9 new losses

Replayed all 9 post-certification losses through the certified DIP_B package
(`exp23_dip_surgical`, anti-meta worktree) with the existing route-audit
harness (same method as commit `3bad90f`):

- `ep93748360/93750153/93751091/93752006/93753793/93755661/93756544/93758218/93761111`:
  **route=`None`, surgical fires=0, errors=0** in every game.

Conclusion: every new loss is exact EXP23 base behavior. No Dipplin misroute,
no detector misfire, no surgical-rule contamination. The slide is policy
strength/variance, not a routing bug.

## 4. Signals (no action taken)

- **Mirror is now the largest DIP_B loss bucket** (5 losses; 1W-5L against
  real opponents). All normal-tempo, one 0-prize blowout. EXP23's own mirror
  stays 6-3. Locked guidance (do not optimize against the mirror cell) still
  applies; flagged only as the dominant bucket.
- **93750153** is the first non-structural (close race, grim t4) Crustle loss.
  Prior Crustle loss was a t8 blowout. Still n=1 causal evidence per the
  locked Crustle gate — no rule.
- **93755661** is a third normal-tempo close Dragapult loss (2v2). Consistent
  with the Dragapult causal sprint result (`KILL_NO_REPEATED_CAUSAL_PATTERN`,
  commit `f0364ef`) — no new lever identified.
- **93761111** vs Ogerpon ex/Pinsir repeats the known Ogerpon weakness
  (field-wide 1-3; EXP23 also 0-1).

## 5. Files

- Machine-readable rows: `artifacts/dragapult_causal_20260816/dipb_full_29g.json`
  (local only, artifacts/ is gitignored).
- Transcript tool used for inspection: `scripts/dragapult_transcript.py`.

## 6. Recommendation

Keep the active pair EXP23 + DIP_B. No submission action from these buckets;
mirror slide is being watched but is not a causal routing defect.
