# SPRINT-870 EXPERIMENT LEDGER

Baseline (C0): exact A2+Damage V0
- archive sha256: A44B676F5CA135747B5D4D6923C7FB350A66369D188315B6AC0F291D23CA69E7
- tree sha256:    13426288358D597EAD809E45C364C7F7B9274A6EEBF55DDD942142E3326535C3
- model sha256:   B19871A9F1499C2460AE266E58194ACAB1D8C90B390FA5CF24ED94B9A2B6BDA8
- deck sha256:    92B92BAC9F9163ECFF933B3DC39294D2CC154C8684F3C8497877661419EBC59D
- engine (production): 7a157f045d333f99d1996d49c12bdbdd148072a619af246385c7295518776e30 (libcg.dylib)
- seeded eval engine: 867e3f9bb87e0b48889a44b5d4b04f5d2d434b2a0788d1b2bcfe0caebcb5ab78

## EXP-1: A2+Damage + Punk Up rail (punk_only)
Hypothesis: deterministic Punk activation/count/target selection adds on top of damage solver.
Mechanism: wave1_rails punk rules reorder legal options; disjoint prompt family from damage solver.
Built from: winner extracted + wave1_rails.py (punk variant) + additive card_ids + model.py wiring.
- Stage B (400 pairs vs B0): +5.75pp [CI +1.2..+10.3] first +8.0 / second +3.5
- Stage C (1200 pairs vs B0): +1.33pp [CI -1.3..+3.9], first +1.83, second +0.83, err 0
- vs master_v1 (400 pairs): PENDING
- vs replay_refresh (400 pairs): PENDING
- vs a2_control (400 pairs): PENDING
VERDICT: WEAK (point estimate +1.3pp, ns). Keep as combination base; not promotable alone.

## EXP-2: EXP-1 + Munkidori heal source/count rail (punk_munk)
Hypothesis: choosing which damaged own-pokemon to heal (lethal checkup first) is orthogonal to punk.
- vs EXP-1 (B0): PENDING
- vs EXP-1 (m1): PENDING

## EXP-3: A2+Damage + tempo rail (full wave1 development rules)
Hypothesis: early development family (poffin/gym/petrel/candy/bench basics) has more mass.
Risk: designed for d842-era mistakes; A2 may already fix them.
- vs EXP-1 (B0): PENDING
- vs EXP-1 (m1): PENDING
- vs C0 (B0): PENDING

## EXP-4: A2+Damage + GrimGuardrailDirector (setup roles, shadow over retreat/Boss)
Hypothesis: certified d842-era guardrails (replay-proven beneficial) never shipped in A2 lineage.
- screens: PENDING

## EXP-5: EXP-1 + manual energy attach tier (punk_attach)
Hypothesis: hand-energy ATTACH target choice has mass; Grim-line capacity tier beats model's pick.
- screens: PENDING

## KILLED / CLOSED (do not rerun without new predicate)
- B2b dead-support attach→retreat: -1.20pp (500 pairs vs C0 per team records)
- P0.81 outcome-RL, logit soups, phase routers, TurnDirector

## Evaluation pool
- Grim: B0 (d842 exact), master_v1, replay_refresh, a2_control (A2 ordered = prior live)
- Alakazam: 2.4a, 2.7 (freshstart/elite_submissions + extracted in sprint_870/opponents)
- Dipplin: dipplin_d1 (submission.tar.gz), dipplin_d1_incumbent
- Starmie: starmie_v2_boss_atk (extracted sprint_870/opponents)
- Others: dragapult_eval (weak)

## EXP-1 screens complete
- vs B0 (1200p): +1.33pp [CI -1.3..+3.9]
- vs master_v1 (800p): +1.00pp [CI -2.1..+4.1]
- vs replay_refresh (800p): +2.88pp [CI -0.3..+6.1]
- vs A2-ordered (800p): -0.63pp [CI -3.9..+2.6]
VERDICT: WEAK component. Helps vs older lineages, neutral vs A2. Champion remains C0.

## EXP-2 KILLED
- vs EXP-1 (B0, 800p): -4.37pp [CI -7.3..-1.5]
- vs EXP-1 (m1, 600p): -4.33pp [CI -7.5..-1.2]
Mechanism: munk heal-source override. Model's own source choice is better. CLOSED unless new predicate.

## EXP-7 built: damage+punk+PLAY-identity binding
Confirmed: shipped v2 features encode source_card=0 for ALL PLAY options (no area/cardId in option JSON; resolve_area_card returns None). Model cannot see trainer identity at inference OR training time. Probe binds hand[index]. Screens PENDING.

## Stage D results
- EXP-3 tempo: KILLED. vs C0 (B0,600p) -6.33pp [CI -11.1..-1.6]; vs EXP-1 (600p) -5.33pp [CI -9.9..-0.8].
- EXP-4 guardrails: KILLED. vs C0 (B0,600p) -1.83pp [CI -5.0..+1.4], first -4.3; vs EXP-1 -0.33pp.
- EXP-6 boss solver: INERT. 0 interventions in 600 pairs (probe: solver rejects all prompts; A2's top pick already optimal / shadow_ready fails). KILL (dead code).
- EXP-5 attach tier: first build had silent patch bug (mode not registered) - fixed; screens in stage E.
- EXP-7 play identity: screens in stage E.

## Current best-known components
C0 = exact A2+Damage V0 (champion).
C0+punk = +1.0..+2.9 vs d842-era grim opponents, ~0 vs A2-ordered. Not promotable alone.

## Stage E results
- EXP-5 attach tier: KILLED HARD. -24.17pp vs EXP-1 (B0, 600p, CI [-28.6,-19.7]), disc 37/182.
  The model's attach choices are far better than a blind tier. ATTACH family CLOSED.
- EXP-7 play identity: +3.17pp vs EXP-1 (B0, 600p, CI [-1.9,+8.3]); first +0.7, second +5.7 (disc 67/50).
  CONFIRMED: training data has ALL PLAY options source_card=0 (110,966 options); model is identity-blind for trainers.
  Confirmation screens in stage F.
- Alakazam authentic-search cells too slow (~4.5s/game). Standardized tournament on NO_SEARCH proxies (like dipplin screens).
- Infra fix: evaluator now supports --hero-env/--opponent-env (additive patch, training/evaluate_deterministic_crn.py).
- Infra note: scripts must use .venv/bin/python explicitly (homebrew python3 lacks numpy).

## Open questions
1. Is EXP-7 (+3.2pp) real? Stage F confirmation (fresh seeds 800p B0 + 600p m1/rr + total vs C0).
2. If real: stack punk? EXP-7 includes punk already. Promote EXP-7 as C1, then tournament.
3. If false: C0 remains champion; remaining levers = seat-1 finetune (747k local decisions, v2 features) or accept C0.

## Stage G/H/I results
- EXP-8 (playid second-only) vs EXP-7: -2.2pp overall; first-seat removal of playid cost -4.3pp (disc 38/51), second identical. => playid is a FIRST-seat component.
- EXP-9 seat-1 winner-BC second arm: KILLED HARD (B0 -2.75, m1 -7.33 sig, rr -4.0; first-order control exactly 0). Winner-only BC covariate shift confirmed again.
- Zoo second-arm sweep (vs C0, B0, 300p second): master_v1 +0.3, temporal -1.0, lowband -2.0, rr -4.0, 5kported -8.3, 5kaug -13.3, bcv3marnie -34.7, bcv2ctl -38.0, bcv3 -39.3. No zoo model beats A2 as second arm.
- EXP-10 mirror specialist (mirror-only heads finetune + public-card latch): B0 +1.33 first cell, fresh-B0 800p -0.4, m1 -2.0 => KILL (matchup-fragile, net ~0).
- EXP-11 punk ablations vs C0 (B0, 600p): 11a activate+count -2.2pp (second -4.0); 11b target-only +1.67pp (disc 20/10, both orders positive); 11c count-only +1.2pp (ns).
  => punk TARGET tier is the valuable component; forced YES activate is harmful.
- EXP-7 vs Starmie v2 (200p): +2.0pp (C0 baseline 66.5%).
- az24 authentic-search cell: FAILED (BrokenPipe, too slow). NO_SEARCH proxies used for the matrix instead.

## Best components (all reorder-only, zero errors)
1. punk_target (tier on Punk Up ATTACH_FROM): +1.7pp vs B0 (600p, disc 20/10)
2. punk_count (count=min(max,capacity)): +1.2pp (ns)
3. playid (PLAY option identity binding): +1.1 pooled vs grim (2000p); -3.5 vs Dipplin (ns); strongest first-seat
4. damage solver v0 = baseline C0 component (+1.2 from team stage3)

## Stage M/N final results
- EXP-12 damage v1 (Froslass checkup-chip breakpoints): -0.3pp (2 discordant pairs). KILL - v0 is right.
- EXP-13 punk_ct (count+target): B0 -2.2, m1 -0.5, rr -1.2, az24 +2.3, az27 +0.3. First-seat regressions -5 to -5.7 on B0/m1. KILL.
- EXP-14 punk_ct+playid: B0 -2.0. KILL.
- EXP-15 punk_ct second-arm only: -0.3pp (second -0.7; first exactly 0). KILL - m1 second-seat +4.7 was noise.
- EXP-11b punk_target TOURNAMENT vs C0:
    B0 600p: +1.67pp [CI -0.1..+3.5] (first +2.3, second +1.0; disc 20/10)
    m1 600p: -1.17pp (ns; disc 13/20)
    rr 600p: +2.17pp [CI +0.4..+3.9] SIGNIFICANT (first +3.0, second +1.3; disc 21/8)
    az24 400p: -0.5pp (~0)
    Pooled grim-family: ~+0.9pp. Alakazam: ~0. dipplin: pending.
    => best repeatable rail found, but below the +2pp promotion bar.
