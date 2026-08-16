# FINAL INCREMENTAL CAUSAL GATE — 2026-08-16 (~17:50 CDT)

- **verdict:** `KILL_NO_NEW_CAUSAL_PATTERN`
- **branch:** `final/last-causal-gate-20260816`
- **starting SHA:** `1333272cbe442a78359db3d645f9c1e9b58220e9`
- **final SHA:** (see git log after push)
- **elapsed time:** ~10 minutes (hard stop respected)
- **93755661 decisive-turn summary:**
  - T7: Grimmsnarl ex attacks Shadow Bullet (180) into active Dragapult ex[320]
    (320->140 confirmed T9 board); splash 30 correctly placed on benched
    Dreepy 70->40 (legal, non-Tera target). No Tera-splash waste.
  - T9: Shadow Bullet KO on active Dragapult ex[140] (2 prizes) + splash 30
    onto Drakloak[30] = KO (1 prize). Correct KO arithmetic; 3 prizes in one
    turn, 5->2.
  - T9 ability: Munkidori/Froslass counters (NUM:2) placed on benched Dragapult
    ex — ability counters, not Tera-blocked; not a wasted-damage family.
  - T11: promoted Morgrem, 4x {D} attach, evolved -> Grimmsnarl ex (second
    attacker line online); second Grimmsnarl ex evolved T14.
  - No promotion of low-HP utility when a survivable attacker was available
    (Morgrem promoted over Snorunt/Munkidori both times). No dominated Boss
    target. No provably wasted attachment to a disappearing Pokémon with a
    strictly better legal target.
  - End state: 2v2; OP act Dragapult ex[290] + Fez[190] + Meowth ex[160];
    hero act Grimmsnarl ex[100] 0E + fresh Grimmsnarl ex[320] 0E on bench.
- **repeated pattern found:** NO
- **affected losses:** none (93755661 shares none of the 7 mechanical failure
  families with any prior normal-tempo Dragapult loss)
- **win-control occurrences:** n/a (nothing found to compare)
- **exact causal chain:** n/a
- **rule name:** `NONE`
- **secondary Crustle/Ogerpon result:** KILL both.
  - 93750153 (Crustle/Kangaskhan, close 2v2): no mechanically dominated action
    matching the allowed families; n=1 in its bucket anyway (prior Crustle loss
    was a t8 structural blowout) -> fails "two losses" requirement.
  - 93761111 (Ogerpon ex/Pinsir): 5v1 structural blowout, not a close race;
    n=1 -> fails gate.
- **implementation made:** NO
- **package built:** NO
- **Kaggle submitted:** NO
- **recommendation:** `KEEP_EXP23_DIP_B`

---

## 1. Method (incremental, not broad)

- Read prior sprint corpus (DRAGAPULT_CAUSAL_SPRINT_20260816.md +
  dragapult_case_table_20260816.csv + DIPB_NEW_LOSS_BUCKETS_20260816.md +
  MATCHUP_INTELLIGENCE_20260816.md; note: DRAGAPULT_MATCHUP_REPORT_20260816.md
  does not exist in repo — the case table CSV is the match artifact).
- Decoded 93755661 (DIP_B = hero, seat 1, sub 0) turn-by-turn with
  `scripts/dragapult_transcript.py` plus raw-observation hand/board dumps.
- Checked the 7 causal families from the gate against every hero decision.

## 2. Why every family fails for 93755661

1. **Second Grim prep:** second Grimmsnarl ex line prepared and evolved by T14
   (Morgrem energized x4 at T11 -> evolved; second Morgrem evolved T14).
2. **Low-HP utility promotion:** hero promoted Morgrem[100] after each KO,
   never a damaged utility over a survivable setup target.
3. **Dominated Boss/attack target:** every Shadow Bullet main-damage target
   was the active 2-prize threat; splash targets (Dreepy t7, Drakloak t9) were
   legal, non-Tera, and the t9 splash took a prize.
4. **Damage movement missing a KO / self-KO:** ability counters went to
   opponent mons (Drakloak 80->50 at T13); no self-KO or missed lethal found.
5. **Tera-immune benched target for attack damage:** absent — splash never
   selected on the benched Tera Dragapult ex in this game (the exact rejected
   candidate from the prior sprint is NOT repeated).
6. **Wasted attachment to a guaranteed-to-die Pokémon:** no attachment could
   be proven wasted with a strictly better legal alternative in hand.
7. **Decisive Phantom Dive bench gift:** opponent's KO sequence was
   Grimmsnarl ex[120] (2) + Munkidori; no unnecessary bench play caused it.

## 3. Gate check (all conditions)

1. Same semantic pattern in 93755661 AND >=1 prior normal-tempo loss: **FAIL**
   (none found).
2-8. n/a — condition 1 fails, so candidate does not exist.

The previously rejected generic Tera-splash rule does NOT qualify: the new
game shows the policy correctly targeting legal non-Tera benched Pokémon with
the splash (Dreepy t7, Drakloak t9 for a prize), i.e. no new prize/tempo
causal chain evidence for that rule — opposite evidence.

## 4. Explicitly not done

- No overlay, no archetype detector, no replay-audit harness run (nothing
  implemented — nothing to audit).
- No package, no Kaggle submission, no training, no PPO, no EXP23 resubmit,
  no mirror-policy changes.

## 5. Limitations

- 93755661 raw-observation energy snapshots in late-game stored steps show
  both Grimmsnarl ex at 0E in terminal state; energy accounting in the final
  T13/T14 selections (ctx21 ACT+BENCH pair) not fully resolved before the hard
  stop. This affects nothing in the 7 families — no candidate depended on it.
- Phase B was a 2-minute triage on last-turn transcripts only, not full
  turn-by-turn forensics (gate required a second matching loss anyway).

## 6. Commands run

```
git checkout 1333272cbe442a78359db3d645f9c1e9b58220e9
git checkout -b final/last-causal-gate-20260816
python3 scripts/dragapult_transcript.py \
  <...>/55562629/episode-93755661-replay.json 0 1
python3 - <<EOF  (hand/board dumps T9+ for 93755661)
```
