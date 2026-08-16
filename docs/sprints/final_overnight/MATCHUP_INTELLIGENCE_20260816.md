# MATCHUP INTELLIGENCE — 2026-08-16 (16:45 CDT)

# PRO TL;DR

- **Best matchup to target: DRAGAPULT** — EXP23 is 1-5 live, the only current
  matchup with a clearly negative record and 5 replays to mine.
- **But the forensic split matters:** 2 of 5 EXP23 Dragapult losses are
  tempo-structural (first Grim at turn 11 and turn 14 — lost before policy
  could matter). The other 3 have normal tempo (Grim t4/t5/t6) and end as close
  prize races (2v1, 2v1, 1v1 remaining) — THOSE are the policy-relevant pool.
- **Best concrete state family: NONE FOUND.** The policy zoo (c0+d842 vs
  EXP23 on our own game states) shows consensus disagreements at 7.7% of loss
  decisions vs 8.4% of win decisions - the old-policy consensus does NOT
  enrich in losses. No cheap matchup residual exists.
- Old-policy consensus: measured directly on our loss states (section 3).
- Estimated risk of any new Dragapult rule: HIGH (prior broad Dragapult
  surgery already failed; 40% elite-deck ceiling).
- **Recommended next experiment: NO IMPLEMENTATION. KEEP DIP_B + EXP23.**
  The only remaining defensible lane is a manual expert-bank semantic study
  (Task B) if Pro has time, not a rule.

---

## 1. Forensic table — EXP23 (55556726) losses, n=14

| episode | archetype | order | first Grim | munk | fros | bench | end prizes (us v them) |
|---|---|---|---|---|---|---|---|
| 93730597 | dragapult | second | t4 | 3 | 1 | 5 | 2v1 |
| 93699067 | dragapult | second | **t14** | 2 | 2 | 5 | 2v1 |
| 93685951 | dragapult | first | **t11** | 4 | 1 | 5 | 1v1 |
| 93673237 | dragapult | first | t5 | 2 | 1 | 3 | 2v1 |
| 93671387 | dragapult | second | t6 | 2 | 2 | 5 | 2v5 |
| 93665757 | grimmsnarl | first | t3 | 3 | 0 | 5 | 5v1 |
| 93715535 | grimmsnarl | first | t5 | 2 | 0 | 4 | 3v2 |
| 93680533 | grimmsnarl | first | t5 | 3 | 0 | 5 | 3v2 |
| 93736000 | alakazam | second | t4 | 2 | 1 | 5 | 2v2 |
| 93674154 | bellibolt | second | t6 | 2 | 0 | 4 | 4v1 |
| 93670440 | lucario | first | t9 | 3 | 2 | 5 | 4v1 |
| 93693193 | other | first | t5 | 2 | 0 | 4 | 4v1 |
| 93677628 | other | first | t5 | 4 | 2 | 5 | 2v1 |
| 93668609 | other | first | t5 | 4 | 1 | 5 | 5v1 |

Notes:
- Mirror losses are NOT tempo losses (t3/t5/t5) — two close prize races (3v2)
  and one blowout. No repeated structural signature.
- Dragapult: 2 structural (t11/t14), 3 normal-tempo close races → candidate
  policy-error pool.
- end-prize counts are from the last stored observation; treat as approximate.

## 2. Forensic table — DIP_B (55562629) losses, n=4

| episode | archetype | order | first Grim | munk | fros | bench | end prizes |
|---|---|---|---|---|---|---|---|
| 93746552 | grimmsnarl | first | t3 | 3 | 0 | 5 | 3v2 |
| 93743797 | grimmsnarl | second | t4 | 3 | 0 | 5 | 6v1 |
| 93745631 | dragapult | first | t7 | 4 | 2 | 5 | 2v1 |
| 93744693 | crustle | second | t8 | 4 | 0 | 5 | 5v1 |

- Mirror: one close race (3v2), one blowout (6v1, zero prizes taken) — sample
  too small to distinguish policy from variance; EXP23's 6-3 mirror record
  remains the stronger signal.
- Crustle loss: slow start (Grim t8) + dominated 5v1 → mostly structural;
  cannot yet support a Crustle rule.

## 3. Policy zoo (c0/d842 consensus vs EXP23 on loss states)

Method: walked EXP23's own 14 losses + 6 matched wins with c0 (A2) and d842
(5k) policies; counted decisions where c0 == d842 != EXP23's recorded action
(excluding forced decisions).

| population | decisions | consensus disagreements | rate |
|---|---|---|---|
| losses (14 games) | 1169 | 90 | 7.7% |
| wins (6 games) | 605 | 51 | 8.4% |

- Context: MAIN dominates (80/90 in losses; 45/51 in wins); small counts in
  DAMAGE(13), TO_HAND(7) contexts - all at background rates.
- Band: loss consensus splits early 36 / mid 44 / late 10.
- VERDICT: no loss enrichment - no old-policy-consensus residual. KILL.

Script: scripts/policy_zoo_flat.py; output:
artifacts/global_swing_20260816/policy_zoo_exp23.json

## 4. Expert replay bank — NOT built this sprint

Top-Grim expert games vs Dragapult/Crustle from Aug 13-16 corpora were not
collected before the time cap. The policy zoo on our own loss states is the
substitute. Local corpus dirs available for Pro:
anti-meta worktree artifacts/anti_meta_20260816/raw_20260813/14/15 (+rawneg),
overnight worktree artifacts/overnight_20260816/heldout_raw/2026-08-13/14/15.

## 5. Top-5 opportunity queue (preliminary)

1. DRAGAPULT close-race states: 3 normal-tempo close losses exist, but the
   policy zoo shows NO consensus/loss enrichment and prior broad surgery
   failed. VERDICT: KILL (no actionable state family).
2. CRUSTLE ex-damage-immunity exact states (Munkidori bypass / Boss escape):
   only 1 live loss, structural. Historical 4-6. VERDICT: NEED MORE DATA.
3. GRIM MIRROR close races: EXP23 already 6-3; DIP_B 1-2 sample is too small.
   VERDICT: KILL (do not change a winning bucket).
4. OGERPON/other tail: n=1 each. VERDICT: KILL.
5. BELLIBOLT: n=1. VERDICT: KILL.

Negative evidence is the default: prior sprint already KILLED global Munk
priority, late-support freeze, broad tempo rails, and Dragapult surgery.
