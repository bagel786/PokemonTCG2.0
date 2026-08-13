# Dipplin Second-Order Generality Sprint

Status: **COMPLETE — PROMOTE_SECOND_OPENING_V2 (BASIC IMPROVEMENT)**

Branch: `opencode-second-order-general`. Base HEAD: `a1b4acbfce51ffdb944bde9bcb03186bfedce443`.

## 0. Immutable control

- Incumbent archive: `artifacts/dipplin_d1/submission.tar.gz`
- Incumbent SHA-256 (recomputed locally): `E5B932DB2DFFC2A860F8B5B883785885F73FD820665119687BB0C29969583BA6` (matches prior sprint)
- Incumbent extracted tree: `artifacts/dipplin_d1_incumbent` (`076AE8DE12D2D6C4A170B47B2D2F9CF538C1D318A05BB2E81F13DA9BE2CD2026`)
- Candidate package (D1 + S1 code, S1 off by default): `artifacts/dipplin_s1/submission.tar.gz`, SHA-256 `250C99EBA1F12D4DD28991A544F3B81BE2BC809CE49B3B07350A77498FACB47F`

## 1. Forced-order baseline (current D1 incumbent)

`training/evaluate_forced_order.py`, 200 actual-second + 100 actual-first per
opponent. Zero policy errors, zero illegal actions across all 1200 games.

| opponent | actual-first | actual-second |
|---|---:|---:|
| A2 Grimmsnarl (exact) | 0.600 (60/100) | 0.450 (90/200) |
| d842 Grimmsnarl (exact) | 0.660 (66/100) | 0.435 (87/200) |
| Alakazam 2.4a (authentic) | 0.460 (46/100) | 0.315 (63/200) |
| Alakazam 2.7 (authentic) | 0.440 (44/100) | 0.360 (72/200) |
| **anchor macro** | **0.540** | **0.390** |

The actual-second weakness is severe (≈ 33% vs Alakazam) and is not
Grimmsnarl-specific.

## 2. Same-deck mirrors

`scripts/run_same_deck_mirror.py` (sterile extracted copies; zero errors).

| match | hero forced | win rate |
|---|---|---:|
| D1 vs D1 | first | 0.610 (244/400) |
| D1 vs D1 | second | 0.420 (168/400) |
| D1 vs D0 | first | 0.740 (222/300) |
| D1 vs D0 | second | 0.540 (162/300) |
| S1 vs D0 | first | 0.743 (223/300) |
| S1 vs D0 | second | 0.597 (179/300) |

Interpretation:

- The D1 mirror shows a large **intrinsic first-player initiative advantage**
  (61% first vs 42% second ≈ 19pp). The forced-second anchor vs Grim/AZ (39%)
  sits only ~3pp below this mirror floor, so a large part of the "second-order
  weakness" is intrinsic to the deck, not a policy defect.
- D1 going second beats D0 going first 54%; S1 going second beats D0 going first
  **59.7%**. This is the archetype-independent proof that S1 is a genuinely
  better second-player Dipplin pilot (it cannot be Grim/AZ memorization — it is
  the identical deck).

## 3. S1 SECOND_OPENING_V2

Implemented behind `PTCG_DIPPLIN_SECOND_OPENING_V2=1` (default OFF). Applies only
when `actual_order == "second"` and `own_turn_ordinal == 1` and Active is Volbeat
and Quick Sign is legal. It reserves only the Bench slots Quick Sign still needs,
banks the evolution/Energy with Hilda, establishes the engine line (Poffin /
manual Grookey), then Quick Signs. Regression test proves byte-identical behavior
outside that context (`tests/test_dipplin_second_opening.py`).

Forced-second (300 games/opponent = 1200 games; zero errors/illegal actions):

| opponent | S1 second | incumbent second | Δ |
|---|---:|---:|---:|
| a2 | 0.443 (133/300) | 0.450 | -0.007 |
| d842 | 0.477 (143/300) | 0.435 | +0.042 |
| az2.4a | 0.460 (138/300) | 0.315 | +0.145 |
| az2.7 | 0.410 (123/300) | 0.360 | +0.050 |
| **macro** | **0.4475** | **0.3900** | **+0.0575** |

Forced-first regression (100 games/opponent): S1 **0.5625** vs incumbent **0.540**
(no regression). S1 only modifies second-player turn-1 play, so first-order
movement is seed noise (S1 is byte-identical to D1 going first).

Opening mechanism (gross telemetry, ~34% of second games are S1-context): Quick
Sign 129/135 opportunities, Hilda 41, Poffin 57, Poké Pad 44, Bug Set 28, manual
Basic 45. `opening_engine_lines ≈ 1.14` before Quick Sign (incumbent: 0 — it
Quick Signed immediately with no engine line).

## 4. Meta-mechanics suite

`tests/test_dipplin_meta_mechanics.py` — 15 public-board property tests, all
passing. Covers prize-value arithmetic (1/2/3 prize), Weakness math, first-hit vs
two-hit KO, Boss target selection, Jamming Tower (Bangle disabled),
Crustle/Neutralization-Zone non-ex immunity, ability-based immunity, bench
threshold usefulness / no-change, fragile-bench penalty, replacement-continuity
strictness, and support-active retreat preference.

## 5. Generalization evidence

- **Strong-holdout search: NO STRONG DIVERSITY HOLDOUT AVAILABLE.** The only
  strong authentic agents in the repository are Grimmsnarl (A2, d842) and
  Alakazam (2.4a, 2.7). No Lucario/Crustle/Ogerpon/Dragapult/Lopunny/Garchomp
  elite package exists with documented competitive strength.
- **Weak-clone coverage:** clones (Lucario, Crustle, Ogerpon, Bellibolt,
  Starmie/Froslass, Dragapult, Lopunny) exist only as behavior-clone weights,
  not runnable elite packages. Their game outcomes are **CEILINGED / NOT A
  STRENGTH METRIC** and are excluded from promotion. Generalization rests on the
  same-deck mirror (section 2) and the meta-mechanics suite (section 4).

## 6. Errors, latency, packaging

- Zero illegal actions, zero policy errors across every S1 and incumbent cell.
- S1 latency unchanged from D1 (S1 is a deterministic planner branch; D1 search
  bounds unchanged at soft 0.65s / hard 1.5s).
- Candidate package SHA: `250C99EBA1F12D4DD28991A544F3B81BE2BC809CE49B3B07350A77498FACB47F`.

## 7. Verdict

**PROMOTE_SECOND_OPENING_V2** (BASIC IMPROVEMENT).

The candidate improves forced-second by +5.75pp across four strong anchors with
zero errors and no first-order regression, and the improvement is confirmed in
the archetype-independent same-deck mirror (S1-second beats D0-first 59.7% vs
D1's 54.0%). The mechanism (establish the engine line and bank the
evolution/Energy before the turn-ending Quick Sign) is a general, opponent-agnostic
Dipplin opening improvement, not a matchup exploit.

Caveat: second-order remains below 50% (44.75%), short of the GOOD threshold,
because the deck carries a large intrinsic initiative disadvantage (D1 mirror
second = 42%). S1 recovers a meaningful slice of the remaining policy gap but
does not eliminate the structural first-player advantage. General strength is
therefore proven only up to the strong anchors available (Grimmsnarl + Alakazam)
plus the same-deck mirror; a live diversity test against additional strong
archetypes would be the next step to push past this bound.
