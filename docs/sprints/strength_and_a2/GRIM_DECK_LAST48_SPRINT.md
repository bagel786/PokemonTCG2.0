# Grim deck last-48-hours strength sprint

Date: 2026-08-14
Status: **REJECTED at hard gate; exact A2+Damage V0 retained**

## Decision

The Enhanced Hammer substitution failed the frozen opponent-stratum floor and
is rejected. Against `master_v1`, it won 316/600 schedules while the canonical
deck won 336/600: **-3.33 percentage points**, paired 95% CI **[-7.90, +1.24]**.
The actual-second result was **-8.33 pp**, paired 95% CI **[-15.04, -1.63]**.

The preceding exact-A2+Damage mirror stratum was only +0.50 pp (306 versus 303),
paired 95% CI [-4.36, +5.36]. The `master_v1` overall result breached the
preregistered -1.0 pp matchup floor, so the remaining confirmation strata were
stopped without reinterpretation. The candidate had zero policy errors and the
production engine remained hash-identical; this is a strength failure, not a
runtime failure.

## Scope

The competition build must remain Marnie's Grimmsnarl. Exact A2+Damage V0 is
the immutable fallback; its code, weights, and canonical deck are not edited by
this sprint. The only candidate change is the submitted 60-card list while the
entire A2+Damage policy remains byte-identical.

This surface had not previously been tested: all archived Grim policy,
guardrail, recovery, and search experiments used the same canonical deck
multiset (`92B92BAC9F9163ECFF933B3DC39294D2CC154C8684F3C8497877661419EBC59D`).

## Discovery

Twenty bounded one- or two-card variants were generated from the canonical
list. Fifteen changed counts only among incumbent cards; five tested narrow
tech substitutions. Every list retained exactly
60 cards and legal multiplicities.

The common-seed discovery screen used 30 pairs per actual order against exact
A2+Damage V0. Ten nonnegative or mechanism-specific candidates then faced the
documented Alakazam 2.7 direct-policy/no-search mode on the same discovery
budget. These results were used only for selection.

The top three candidates advanced to new seeds, 100 pairs per order, against
`master_v1`, `replay_refresh`, and Alakazam 2.7:

| Candidate | master_v1 | replay_refresh | Alakazam | Pooled |
|---|---:|---:|---:|---:|
| +Snorunt / -Tool Scrapper | -0.5 pp | -5.0 pp | +2.5 pp | -1.0 pp |
| Risky Ruins / -Spikemuth | +1.0 pp | +0.5 pp | -1.0 pp | +0.17 pp |
| **Enhanced Hammer / -Tool Scrapper** | **-2.5 pp** | **+4.5 pp** | **+2.5 pp** | **+1.5 pp** |

All arms had zero policy errors. Snorunt is rejected. Risky Ruins is neutral.
Enhanced Hammer is the sole confirmation candidate; its pooled signal is
positive but heterogeneous and is not yet an accepted improvement.

## Frozen decisive gate

The candidate is exactly one substitution:

- remove one Tool Scrapper (`1137`)
- add one Enhanced Hammer (`1081`)

No policy, runtime, threshold, opponent, or other deck count may change.

Run 300 fresh common-random-number pairs per actual order in each stratum:

1. exact A2+Damage V0 mirror;
2. `master_v1` Grim policy;
3. `replay_refresh` Grim policy;
4. Alakazam 2.7 in documented `NO_SEARCH=1`, `NO_LETHAL=1` mode.

For the primary estimate, normalize the latest measured meta shares across the
covered archetypes: Grim mirror 30.9 / 49.3 = 0.626775 and Alakazam 18.4 / 49.3
= 0.373225. Split the mirror weight equally across its three policy strata, so
each mirror stratum has weight 0.208925.

Promote only if all conditions hold:

1. zero candidate policy errors, illegal selections, non-finite results, or
   engine errors;
2. production engine hash preserved;
3. normalized meta-weighted paired delta is greater than zero and its
   one-sided 95% lower confidence bound is greater than zero;
4. no opponent-stratum paired delta is below -1.0 percentage point;
5. neither normalized actual-order delta is below -0.5 percentage point.

Any failure rejects the deck candidate and retains exact A2+Damage V0.

## Confirmation result

| Stratum | Candidate | Canonical | Delta | Paired 95% CI | First | Second | Decision |
|---|---:|---:|---:|---:|---:|---:|---|
| exact A2+Damage | 306/600 | 303/600 | +0.50 pp | [-4.36, +5.36] | -1.67 pp | +2.67 pp | Continue |
| master_v1 | 316/600 | 336/600 | **-3.33 pp** | [-7.90, +1.24] | +1.67 pp | **-8.33 pp** | **Hard-gate failure** |
| replay_refresh | not run | not run | - | - | - | - | Stopped |
| Alakazam 2.7 | not run | not run | - | - | - | - | Stopped |

Final decision: **do not change the deck.** The twenty-variant deck search found
no reproducible promotion candidate. Ship exact A2+Damage V0 with the canonical
Grimmsnarl list.

## Immutable fallback

- A2 policy SHA-256:
  `B19871A9F1499C2460AE266E58194ACAB1D8C90B390FA5CF24ED94B9A2B6BDA8`
- A2+Damage V0 winner archive SHA-256:
  `A44B676F5CA135747B5D4D6923C7FB350A66369D188315B6AC0F291D23CA69E7`
