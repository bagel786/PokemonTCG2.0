# Strategic playbook v2

## Result and recommendation

The v2 artifact is a valid, deterministic, submission-ready experimental package. It implements a persistent public-information controller over full A2, keeps exact d842 only as fail-closed fallback, preserves the frozen v1 archive byte-for-byte, and does not upload or replace any live submission.

It should **not replace A2 or v1 in a live slot**. In the final 1,080-game comparison, v2 was strategically active but materially weaker: 59.17% raw and 66.31% meta-weighted, versus A2 at 67.78% / 75.28% and v1 at 67.50% / 72.70%. The result identifies a credible controller architecture and concrete harmful objectives, but not a promotion candidate.

## Architecture

`ptcg_ai/strategic_playbook.py` adds three persistent decision layers above A2:

1. `PublicStrategicRouter` accumulates only public Active, Bench, public pre-evolution, and discard identities. It adds verified Archaludon IDs and a provisional `kangaskhan_generic` route that refines to Ogerpon or Crustle when stronger public evidence appears.
2. `GamePlanState` stores route/confidence, phase, objective, enforcement, own-turn selection/expiry, stable `TargetRef`, reason, subgoals, last semantic action, transition count, and fallback count.
3. `StrategicPolicy` selects an objective once per own turn, preserves it through nested prompts, and can keep an exact target commitment for one additional own turn. A2 ranks within objective-consistent actions. Mechanical impossibilities are always last; HARD sequences are lexicographic; COMMIT sequences use objective-specific confidence margins before overriding A2; PREFERENCE objectives use a bounded soft margin. The tactical shield and sanitizer each run exactly once.

Stable targets resolve by exact public serial, then public family/role. Raw prompt-local option indices are never persisted. A target disappearance terminates and reselects the objective cleanly.

The controller uses only live/public state. It does not inspect opposing hand identities, deck identities, prizes, replay labels, handshake deck contents, or hidden engine state.

## Phases and objectives

The phases are `SETUP`, `STABILIZE`, `PRESSURE`, `RECOVERY`, and `CLOSEOUT`.

Implemented objectives are:

- `DEFAULT_A2`
- `CLOSEOUT_PRIZE_ROUTE`
- `ESCAPE_DEAD_ACTIVE`
- `BUILD_FIRST_ATTACKER`
- `BUILD_REPLACEMENT_ATTACKER`
- `DENY_STADIUM_ENGINE`
- `DENY_EVOLUTION_ENGINE`
- `DENY_SUPPORT_ENGINE`
- `PRESSURE_PRIMARY_ATTACKER`
- `CONVERT_DAMAGE_BREAKPOINT`
- `PRESERVE_ONE_PRIZE_ATTACKER`
- `MANAGE_SPREAD_LIABILITY`
- `MANAGE_HAND_SIZE`

`PRESERVE_ONE_PRIZE_ATTACKER` is implemented but disabled in the packaged configuration because the Morgrem lines against Crustle and Dipplin were not engine-certified strongly enough. `CONVERT_DAMAGE_BREAKPOINT`, `DENY_STADIUM_ENGINE`, and `MANAGE_SPREAD_LIABILITY` remain public-precondition gated; they passed focused checks but did not activate in the audited 10,000-decision slice. No activation is forced merely to increase disagreement.

Objective priority is closeout, verified dead-Active escape, urgent Stadium denial, first attacker, replacement attacker, damage conversion, evolution denial, lethal committed Boss/target pressure, causal support denial, spread/hand management, then A2. Immediate wins and verified escape sequences interrupt an existing objective. Milestones, target disappearance, impossibility, expiry, or a shorter public closeout terminate it.

## Route plans

Active route configurations are Grim mirror, Alakazam/Dudunsparce, Mega Lopunny, Dragapult, Archaludon, Crustle, Ogerpon/Kangaskhan toolbox, provisional generic Kangaskhan, Mega Lucario, Dipplin/Thwackey, Garchomp, Mewtwo, Bellibolt, Starmie/Mega Froslass, and unknown.

The routes specialize primary targets, exposed evolution targets, causally relevant support, Stadium denial, useful setup width, spread liability, and hand-size danger. Notable behaviors include exact Lucario/Lopunny damage commitments, Duraludon denial before Archaludon, Festival Grounds/Area Zero/Battle Cage replacement, no protected Tera Bench damage, Crustle nullification safety, the public Ogerpon 180+30 breakpoint, and Froslass hand-size management.

Pinned CSV verification established these current identities/mechanics:

- Duraludon: 169, 839, 992
- Archaludon: 170, 190, 840
- Relicanth: 57
- Mega Kangaskhan ex: 756
- Festival Grounds / Area Zero / Spikemuth / Battle Cage: 1245 / 1250 / 1259 / 1264

## Behavior audit

The final audit used 10,000 public replay decisions from `artifacts/live_grim_corpus_v5/replays` and compared the packaged v2 action to full A2 and frozen v1.

| Metric | Result |
|---|---:|
| Change versus A2 | 617 / 10,000 (6.17%) |
| Change versus v1 | 581 / 10,000 (5.81%) |
| Actual-first change | 273 / 4,900 (5.57%) |
| Actual-second change | 344 / 5,100 (6.75%) |
| Complete own turns observed | 785 |
| Complete own turns changed | 364 |
| Cross-turn commitments | 95 |
| Mean objective duration | 1.098 own turns |
| Milestone terminations | 172 |
| Target-disappearance terminations | 20 |

Route-specific changes versus A2:

| Route | Decisions | Changes |
|---|---:|---:|
| Alakazam | 1,092 | 5.86% |
| Archaludon | 564 | 4.61% |
| Crustle | 776 | 6.31% |
| Dragapult | 157 | 10.83% |
| Garchomp | 106 | 3.77% |
| Grim | 4,947 | 5.76% |
| generic Kangaskhan | 34 | 14.71% |
| Lopunny | 330 | 9.70% |
| Lucario | 625 | 6.88% |
| Ogerpon | 172 | 6.98% |
| Starmie/Froslass | 149 | 11.41% |
| Unknown | 1,048 | 6.01% |

Decision occupancy by objective was: first attacker 4,491; primary pressure 2,677; replacement attacker 1,504; evolution denial 556; A2 fallback 412; dead-Active escape 157; closeout 117; support denial 25; hand size 14. Phase occupancy was setup 3,741; stabilize 2,556; pressure 2,492; closeout 662; recovery 502. Forty-seven opening decisions precede a meaningful phase/objective record.

Representative audited complete-turn traces are stored in `artifacts/strategic_playbook/final_behavior_audit_10k.json`. Examples:

- Episode 90543754, own turn 2: `BUILD_FIRST_ATTACKER` persisted through 34 prompts; it selected Rare Candy ahead of A2 and requested three useful Punk Up Energy rather than A2's five.
- Episode 90543754, own turn 4: the same objective selected Grimmsnarl evolution on the committed Marnie line instead of A2's top option.
- Episode 90544519, own turn 2: actual-second setup kept the turn objective across five prompts and redirected the attachment to the evolving Morgrem line.

Focused regression checks additionally cover the complete dead-Active attach/retreat/promote/attack sequence; Lucario serial commitment over Solrock; Festival Grounds replacement before attack; protected Tera Bench damage; Crustle nullification; Ogerpon 180+30; Froslass hand lethal; closeout interruption; target disappearance; and Archaludon evolution denial.

## Gameplay evaluation

The final comparison used the same 12-opponent population for A2, frozen v1, and v2: 30 games per arm/opponent, 360 games per arm, balanced 180/180 actual first/second. Engine RNG is unpaired. Authentic Grim and Alakazam agents are separated from proxy stress tests; proxies are not exact ladder claims.

| Policy | Games | Raw | Weighted | Actual first | Actual second | Grim group | Alakazam | Other proxies | Errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A2 | 360 | **67.78%** | **75.28%** | **72.78%** | 62.78% | 52.67% | 85.00% | **76.00%** | 0 |
| frozen v1 | 360 | 67.50% | 72.70% | 66.11% | **68.89%** | **55.33%** | **86.67%** | 72.00% | 0 |
| strategic v2 | 360 | 59.17% | 66.31% | 59.44% | 58.89% | 42.67% | 78.33% | 68.00% | 0 |

V2 proxy results were Lucario 83.33%, Ogerpon 33.33%, Crustle 40.00%, Bellibolt 90.00%, and Starmie/Froslass 93.33%. These are stress-test results only. The full comparison took 153.99 seconds and covered 178,949 hero/opponent decisions with zero hero policy errors.

The initial main screen exposed severe over-commitment (29.79% raw, 5.5% Grim group). The single repair cycle limited COMMIT overrides to verified executable actions, stopped pressure objectives from prematurely forcing attacks, required Boss to convert into a public KO, restored causally justified Munkidori Energy, and calibrated actual-second/build/target margins. This recovered v2 to 59.17%, but not to promotion quality.

The loss is concentrated in first-attacker interventions and committed targeting: v2 is coherent and materially different, but its hand-authored objective preconditions still discard too much of A2's learned sequencing value. Actual-second did not improve (58.89% versus A2 62.78% and v1 68.89%).

## Disabled hypotheses and safety boundaries

The packaged configuration keeps these disabled:

- speculative Morgrem one-Prize preservation against Crustle/Dipplin;
- broad Crustle target pressure;
- generic support targeting without a public causal link;
- speculative mobility denial;
- a general search tree or hidden-information inference;
- any A2/d842 blend as the primary intervention.

Hard behavior remains limited to immediate wins, verified dead-Active escape steps, nullified attacks, protected Tera Bench damage, Battle Cage counter prevention, and exact selections inside a committed sequence. Exact d842 is called only when the v2 runtime raises an exception.

## Package and validation

- archive: `artifacts/strategic_playbook/grimmsnarl_strategic_playbook.tar.gz`
- archive SHA-256: `B604EED897BC772DD890336BD38552E99F663C9163AB3E2B496F1EC063C63A2C`
- size: 10,064,045 bytes
- deck SHA-256: `92B92BAC9F9163ECFF933B3DC39294D2CC154C8684F3C8497877661419EBC59D`
- A2 SHA-256: `B19871A9F1499C2460AE266E58194ACAB1D8C90B390FA5CF24ED94B9A2B6BDA8`
- d842 SHA-256: `D842F85ABFC44AF9F41979F91795E22C92C179B62E04D5A0A2F9C734E70AF1C3`
- strategic runtime SHA-256: `88A1E5491AC900AEFC5DDF647417CAE7AD1B91EA852AE035559E73781A77A6FE`
- router runtime SHA-256: `01FF95556E9171D77AB2A2A26DA9F12AD1DD85CCA3AC019BC1FF6BCEC0DB4B72`
- configuration SHA-256: `45E088D0ECF94C28B48B4130CF4B5C9F88EA139E49E2651A48AD601C33C4F9CF`
- entry point SHA-256: `8A5A29C6A4D8C2D69F6B57568FD2D21A66973E54AC3BA0DB5A138258141C434D`
- deterministic base SHA-256: `0958BD8847266EFBC38658D62B9AC4DCD62A9AAED3D1098F093A677AFCBFED4C`

The builder produced byte-identical archives in-process. The final archive passed no-`__file__` execution, conventional isolated import, unchanged 60-card deck return, legal-action sanitization, fail-closed loading, and 60 complete self-play games / 10,537 decisions with zero policy errors. Latency was p50 0.777 ms, p95 1.670 ms, p99 2.228 ms, and max 18.840 ms.

Focused v2/shield tests passed 18/18. The repository-wide run passed 379 tests and failed two untouched `GrimFloorController` synthetic tests whose fixtures omit `SelectType.MAIN`; the new runtime and package do not use or modify that controller.

The frozen v1 archive remains unchanged at `79A76075E70D3A924BD9D835382FE37F8EE31A32DA66A60C8E6FE019C15BAE59`.

No upload, eviction, or live-slot mutation was performed.
