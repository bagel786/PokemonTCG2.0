# Corrected focused strategic v2

## Outcome

The focused v2 is implemented, packaged, and validated. It fixes the original
controller's code-level mistakes and expresses different public-information
targeting plans for the requested archetypes, but it does **not** demonstrate a
meaningful strength gain. The final-package screen is 238 wins versus A2's 235
over 420 actual-second paired games: +0.71 percentage points, 95% CI
[-1.80, +3.23]. This is inconclusive and far below the evidence needed for a
900+ or 1000-rated claim. The package was not uploaded.

The already-authorized empirical router was submitted separately as Kaggle
submission 55434964. It is `COMPLETE`, but at 2026-08-11 15:01:25.912 UTC its
still-early rating was 587.7 versus 822.5 for the active A2 reship. No later
upload occurred. This is direct evidence that the deterministic local
population was useful for controlled comparisons but was poorly calibrated to
the live ladder.

## What "duplicate-aware semantic" means

The engine can offer multiple option indices that represent the same strategic
move, such as playing either indistinguishable copy of the same card. A raw
top-1 metric calls the prediction wrong if it picks the equivalent copy at a
different index. The duplicate-aware semantic metric collapses options with the
same action type, prompt context, source card, target card, attack, zone, and
non-transient values before scoring them. It is a fairer imitation diagnostic,
but it is easier than choosing the uniquely best game action.

On the broad held-out elite set, the empirical router's semantic top-1 was
83.493% versus A2's 83.442%: only +0.051 points. Raw top-1 moved from 75.208% to
75.230%. The larger numbers discussed earlier were local paired gameplay:
+1.17 points under the balanced order assumption and +2.33 points when actually
second. Those gains were modest, and the public score shows they did not
transfer to the ladder.

Elite replay agreement also cannot establish a best move. The label is one move
an elite agent chose in a won game, not a counterfactual proof that alternatives
lose. Top-k remains a regression diagnostic, not a rating predictor.

## Why the original v2 was weak

The original architecture did fire--it changed 617 of 10,000 audited decisions--
but several broad rules were operationally wrong:

- it changed actual-first play even though the requested opportunity was going
  second;
- it globally overrode A2's build sequencing and count choices;
- it turned speculative support-Energy preferences into a hard prohibition,
  including useful proactive Darkness attachments to Munkidori;
- it hijacked nested target prompts even when A2, not the controller, initiated
  the parent action;
- it started evolution denial from visibility alone, without proving a
  current-turn KO;
- it used attack deficit as a retreat-cost proxy;
- it restored broad Crustle pressure that the prior evidence did not support;
- its exception fallback was d842 instead of the requested authentic A2.

So the answer is not simply "the strategies were bad." The broad v2 combined
implementation defects with unvalidated strategic assumptions, and those
mistakes erased A2's learned sequencing value.

## Corrected architecture

The focused profile is `actual_second_public_matchup_target_overlay_over_full_a2`:

- exact A2 owns all actual-first, pre-order-latch, unknown, disabled-route, and
  ordinary low-level decisions;
- strategy begins only at a MAIN prompt in a supported public route;
- the controller may make at most one non-HARD root override per own turn;
- strategic target control owns a nested prompt only after it changed the
  parent root action; hard mechanical safety may still intervene independently;
- A2 retains counts, setup width, attachments, support timing, retreat timing,
  attack sequencing, and general build/replacement logic;
- immediate winning attacks outrank Boss or an existing plan;
- evolution denial requires a reachable target and a verified current-turn KO;
- support Energy is not treated as mechanically forbidden;
- errors fail closed to full A2;
- the tactical shield and sanitizer each run once.

Active route/objective matrix:

| Public route | Enabled objectives |
|---|---|
| Grim mirror | closeout; verified evolution denial |
| Alakazam | closeout; verified evolution denial; invested-primary pressure |
| Lopunny | closeout; invested three-Prize-primary pressure |
| Dragapult | closeout; verified evolution denial; invested-primary pressure |
| Crustle | closeout; Stadium denial; verified Dwebble denial |
| generic Kangaskhan | closeout; conservative invested-primary pressure |

Global first-attacker/replacement construction, count overrides, generic
support denial, spread/hand heuristics, one-Prize hypotheses, dead-Active
attach sequencing, and general search remain disabled. Their previous versions
were either incorrectly specified or lacked direct evidence.

## One repair cycle

The initial focused screen used a pre-repair package and finished 200-202 over
360 pairs (-0.56 points, 95% CI [-2.28, +1.17]). Trace inspection found that
four of the six control-only wins began with the new rule Bossing an opposing
Grim primary without an exact KO. That rule sounded strategically coherent,
but it spent Boss and changed the Active at the wrong time. It was removed only
from the Grim mirror route.

With the final package, the four Grim populations are exactly tied: 122-122
over 220 pairs, with five candidate-only and five control-only wins. The
remaining Grim interventions are verified evolution-denial or immediate
closeout lines.

Crustle illustrates benchmark variance especially clearly. Two fresh 100-pair
batches on the exact final package were +7 points (60-53) and -4 points (56-60).
Pooled, they are 116-113 (+1.50 points, 95% CI [-2.78, +5.78]). A single batch
would have supported opposite conclusions; the pooled evidence supports
neither.

| Final-package population | Pairs | Focused v2 | A2 | Paired delta | 95% CI |
|---|---:|---:|---:|---:|---:|
| Grim opponents | 220 | 122 | 122 | 0.00% | [-2.82%, +2.82%] |
| Crustle proxy | 200 | 116 | 113 | +1.50% | [-2.78%, +5.78%] |
| Pooled strength screen | 420 | 238 | 235 | +0.71% | [-1.80%, +3.23%] |

Authentic Alakazam 2.7 is expensive: a four-pair smoke tied 3-3 with zero
errors and is not included in the strength pool. There are no trustworthy
deterministic Lopunny or Dragapult opponent packages, so those routes have
focused synthetic coverage but no gameplay-strength claim.

## Behavior and validation

On 10,000 public replay prompts, the final controller changed 42 decisions
(0.42%) versus A2. It changed 0/4,900 actual-first prompts and 42/5,100
actual-second prompts (0.824%), spanning 21 complete own turns and five
cross-turn commitments. Route changes were Grim 35/4,947, Alakazam 4/1,092,
Crustle 3/776, and zero in the sampled Dragapult, Lopunny, or generic
Kangaskhan states because their strict initiation conditions were not met.

That low rate is intentional after removing the unsupported broad controller;
it also means this artifact is a thin, high-confidence matchup overlay rather
than the dramatic policy improvement required to reach 1000.

Validation status:

- focused/deterministic tests: 24 passed;
- Python compilation: passed;
- final actual-first parity: 10/10 paired outcomes with equal 1,969-decision
  counts; a separate replay audit observed 0/4,900 actual-first action changes;
- deterministic proof: repeat and four-worker traces identical for two seeds
  per order;
- sterile archive smoke: one complete game, 172 decisions, zero policy errors;
- latency: p50 0.675 ms, p95 1.956 ms, p99 9.964 ms, max 18.778 ms;
- all 424 strength/smoke pairs had zero hero, control, and opponent policy
  errors, and preserved the production engine binary.

## Artifact

- archive: `artifacts/strategic_playbook_focused_v2/grimmsnarl_strategic_v2_focused.tar.gz`
- archive SHA-256: `9337FB3EFA9E6508AB610D6F61988F853C26EF84CD16D8C78494B11053567C44`
- archive size: 10,066,011 bytes
- runtime SHA-256: `7286728DFD1018DAC0A68A6DEF3760D98CEA4C86437F3358BF088D81FEAA3A74`
- config SHA-256: `4DC48586060E407CBD0F36A4B0B84D317E2E563E6729D808A5A7F889127E3ED1`
- A2 model SHA-256: `B19871A9F1499C2460AE266E58194ACAB1D8C90B390FA5CF24ED94B9A2B6BDA8`
- deck SHA-256: `92B92BAC9F9163ECFF933B3DC39294D2CC154C8684F3C8497877661419EBC59D`
- exact base archive SHA-256: `0958BD8847266EFBC38658D62B9AC4DCD62A9AAED3D1098F093A677AFCBFED4C`

Recommendation: retain A2. Keep the focused v2 as an experimental route
overlay, but do not submit it or claim it solves the 900/1000 gap. The strongest
conclusion from this run is that the previous v2 was partly misimplemented,
yet implementing the defensible matchup logic correctly still produced only
neutral-to-small local effects. The next large improvement must come from a
better learned policy/data objective or a ladder-calibrated evaluation
population, not more unvalidated hand-written rules.
