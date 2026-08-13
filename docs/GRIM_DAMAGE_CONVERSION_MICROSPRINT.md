# Grim damage-conversion microsprint

## Decision

**PROMOTE FOR POSSIBLE LIVE PROBE.** Package only `A2 + damage V0`. Do not
promote Punk-only, do not build the Punk/damage combination, and do not build
V1 from the present evidence. No upload was performed.

The decision is supported by all three required kinds of evidence: authentic
A2 reached public states with exact damage regret; V0 changed only 27/4,659
replayed decisions (0.580%), all inside the two intended target prompts; and a
fresh 600-pair exact-d842 expansion was positive at 330-323, +1.17 percentage
points, paired 95% CI [+0.09, +2.25], with no actual-order collapse or policy
errors.

## Branch and authentic control

- Starting branch: `grim-5k-variance-floor`
- Starting and current base commit: `dea8e124760b0e63512d2cf902b6b3fcc148d686`
- Microsprint branch: `grim-damage-conversion-microsprint`
- Authentic ordered A2 archive: `artifacts/emergency_d842/grim_a2_ordered.tar.gz`
- Archive SHA-256: `E0F3C7CFF1AACD6884442B6E9C44E3712FA305183D839B8F89E5BF2DC2738BC4`
- A2 model SHA-256, identical in `policy_weights.npz`, `policy_first.npz`, and
  `policy_second.npz`: `B19871A9F1499C2460AE266E58194ACAB1D8C90B390FA5CF24ED94B9A2B6BDA8`
- Deck SHA-256: `92B92BAC9F9163ECFF933B3DC39294D2CC154C8684F3C8497877661419EBC59D`
- Extracted control tree SHA-256: `D98EA31D2AF792E7E93D2D343E115E8D5051E5207D76D14A7FA010F459E7D904`

The runtime path is `main.py -> ActualOrderAgent -> policy_first/policy_second`.
Both actual-order policies are the exact A2 model. The exact d842 model is used
only as fail-closed fallback after an exception or invalid router state. The
authentic tactical shield is applied once inside the A2 model. Runtime search
is absent/structurally disabled.

Before this sprint, Wave1 was not installed in the ordered A2 package. Punk-Up
rails and the existing Wave1 Munk source preference were therefore inactive.
The new V0 leaves A2's source and count selections untouched and acts only at
Munkidori destination and Shadow Bullet Bench-target prompts.

## No-code replay damage-regret audit

The audit reconstructed exact shielded A2 from 50 authentic live A2 replays in
`data/replays/55399728`. All 4,659 reconstructed decisions matched the recorded
semantic action. It observed 261 Munk sources, 248 Munk counts, 261 Munk
destinations, and 155 Shadow targets.

There were 416 Munk/Shadow target decisions, 376 with at least two meaningful
targets. Exact public arithmetic found 20 strict improvements, including 16
clear Prize, KO, or same-turn breakpoint conversions. This passed the prompt's
opportunity gate before any damage-solver code was written.

Mechanism totals:

| Metric | Count |
|---|---:|
| Decisions gaining guaranteed Prizes | 3 |
| Additional guaranteed Prizes across those decisions | 5 |
| Decisions gaining a guaranteed KO | 3 |
| Same-turn Shadow Bullet breakpoint improvements | 14 |
| Waste/overkill reductions | 9 |
| Munk count regrets | 0 |
| Multi-Munk spread turns | 11 |
| Spread turns with a missed concentration KO/breakpoint | 1 |
| Protected targets selected by A2 | 4 |

The strongest example was episode 91577273, step 140. A2 put 30 counters on a
10-HP benched Cynthia's Roserade. Moving them to the 210-HP Active Cynthia's
Garchomp ex instead set up Shadow Bullet for the Active KO while its 30 Bench
damage still KOed Roserade: three guaranteed Prizes rather than one.

### Fifteen representative arithmetic corrections

`bp` means a legal same-turn Shadow Bullet KO breakpoint and `waste` is
overkill. These are public-state projections, not archetype rules.

| Replay:step | Prompt | A2 target -> exact target | A2 route -> exact route | Provable improvement |
|---|---|---|---|---|
| 91577273:140 | Munk | Roserade Bench, 10 HP -> Garchomp ex Active, 210 HP | 1P/1KO -> 3P/2KO | +2 Prizes, +1 KO |
| 91582865:143 | Munk | Abra Bench, 20 HP -> Abra Bench, 50 HP | 2P/2KO/bp0 -> 2P/2KO/bp1 | breakpoint |
| 91585677:171 | Munk | Relicanth Bench, 10 HP -> Cinderace Bench, 40 HP | 1P/1KO/bp0 -> 1P/1KO/bp1 | breakpoint |
| 91587528:87 | Munk | Abra Bench, 10 HP -> Kadabra Bench, 50 HP | 1P/1KO/bp0/waste10 -> 1P/1KO/bp1/waste0 | breakpoint, 10 less waste |
| 91587528:112 | Munk | Kadabra Bench, 10 HP -> Dunsparce Bench, 60 HP | 1P/1KO/bp0/waste20 -> 1P/1KO/bp1/waste0 | breakpoint, 20 less waste |
| 91590295:85 | Munk | Riolu Bench, 20 HP -> Lunatone Bench, 60 HP | 1P/1KO/bp0/waste10 -> 1P/1KO/bp1/waste0 | breakpoint, 10 less waste |
| 91598681:131 | Munk | Munkidori Bench, 30 HP -> Munkidori Bench, 60 HP | 1P/1KO/bp0 -> 1P/1KO/bp1 | breakpoint |
| 91599598:100 | Munk | Abra Bench, 50 HP -> Dunsparce Bench, 60 HP | 2P/2KO/bp1/waste10 -> 2P/2KO/bp1/waste0 | 10 less waste |
| 91599598:104 | Munk | Abra Bench, 20 HP -> Dunsparce Bench, 60 HP | 2P/2KO/bp0/waste10 -> 2P/2KO/bp1/waste0 | breakpoint, 10 less waste |
| 91599598:133 | Munk | Abra Bench, 20 HP -> Abra Bench, 50 HP | 2P/2KO/bp0 -> 2P/2KO/bp1 | breakpoint |
| 91602167:105 | Shadow | Kangaskhan ex Bench, 60 HP -> Crustle Bench, 30 HP | 0P/0KO -> 1P/1KO | +1 Prize, +1 KO |
| 91637381:154 | Munk | Abra Bench, 20 HP -> Abra Bench, 50 HP | 2P/2KO/bp0 -> 2P/2KO/bp1 | breakpoint |
| 91658842:108 | Munk | Dunsparce Bench, 30 HP -> Dunsparce Bench, 60 HP | 2P/2KO/bp0 -> 2P/2KO/bp1 | breakpoint |
| 91701353:71 | Munk | Fezandipiti ex Bench, 20 HP -> Abra Bench, 50 HP | 3P/2KO/waste20 -> 3P/2KO/waste10 | 10 less waste |
| 91701353:134 | Munk | Abra Bench, 20 HP -> Dunsparce Bench, 40 HP | 2P/2KO/bp0 -> 2P/2KO/bp1 | breakpoint |

## Candidate behavior

V0 uses only public board state and stable Pokémon serials. Its lexicographic
ordering is terminal win, guaranteed Prizes this turn, guaranteed KOs,
same-turn Shadow breakpoint, overkill, then remaining flexible damage. It
models Darkness weakness/resistance, Tera Bench protection, Battle Cage, and
the existing attack-prevention table. It abstains if a pre-attack Active KO
would require guessing the opponent's promotion. It never persists prompt
option indices, never changes Munk count, and fails closed to A2 on missing or
malformed state.

On the same replay slice, the packaged solver changed 27/4,659 decisions
(0.5795%): 24 Munk destinations and 3 Shadow targets. All 27 were inside the
allowed contexts; changes outside scope, illegal actions, candidate errors,
and control errors were all zero. The difference from the audit's 20 strict
regrets comes from V0 implementing the full objective, including protected
target avoidance and flexible-damage/overkill tie-breaks.

Focused mechanics and runtime tests: 41 passed and 2 platform-dependent parity
tests skipped. Full repository collection was not used as a gate because this
environment lacks PyTorch; no unrelated dependency work was undertaken.

## Successive-halving results

All figures are deterministic common-random-number pairs. `C-only` and
`A2-only` count discordant pair wins. Percentages are paired candidate minus
control win indicators.

### Punk-only

| Opponent | Pairs | Punk | A2 | C-only / A2-only | Delta, paired 95% CI | First / second delta |
|---|---:|---:|---:|---:|---|---|
| exact d842 | 200 | 102 | 100 | 16 / 14 | +1.0 pp [-4.38, +6.38] | +2 / 0 pp |
| master-v1 | 200 | 101 | 102 | 20 / 21 | -0.5 pp [-6.79, +5.79] | +5 / **-6** pp |
| replay-refresh | 200 | 104 | 104 | 25 / 25 | 0.0 pp [-6.95, +6.95] | -2 / +2 pp |

Punk-only passed the cheap d842 screen but failed Stage 2 on negative overall
delta and severe actual-second regression against master-v1. It was rejected.

### Damage V0

| Stage / opponent | Pairs | V0 | A2 | C-only / A2-only | Delta, paired 95% CI | First / second delta |
|---|---:|---:|---:|---:|---|---|
| Stage 1 exact d842 | 200 | 103 | 99 | 6 / 2 | +2.0 pp [-0.76, +4.76] | +2 / +2 pp |
| Stage 2 master-v1 | 200 | 97 | 97 | 1 / 1 | 0.0 pp [-1.39, +1.39] | 0 / 0 pp |
| Stage 2 replay-refresh | 200 | 103 | 102 | 2 / 1 | +0.5 pp [-1.20, +2.20] | +1 / 0 pp |
| Stage 2 Alakazam 2.7 full-search | 40 | 27 | 28 | 0 / 1 | -2.5 pp [-7.40, +2.40] | -5 / 0 pp |
| Stage 3 fresh exact d842 | 600 | 330 | 323 | 9 / 2 | **+1.17 pp [+0.09, +2.25]** | +2.33 / 0 pp |

The Alakazam cell was deliberately only 20 pairs per order because full search
took about ten minutes for 40 pairs. It re-passed single/repeat/parallel trace
determinism before evaluation, was not modified, had zero errors, and is a
small non-conclusive sanity cell rather than a strength claim.

Pooling the two independent exact-d842 schedules gives 433-422 over 800 pairs,
15 candidate-only versus 4 A2-only, +1.38 pp, paired 95% CI [+0.31, +2.44].
Pooling the three authentic Grim variants gives 633-621 over 1,200 pairs,
+1.00 pp, paired 95% CI [+0.20, +1.80]. Including the small Alakazam cell gives
660-649 over 1,240 pairs, +0.89 pp, paired 95% CI [+0.10, +1.68]. These pooled
summaries are unweighted diagnostics, not a ladder-rating estimate.

V1 was not run: only one of 11 multi-Munk spread turns exposed a missed
concentration breakpoint, insufficient opportunity for more state and risk.
The combined Punk + damage arm was not built because Punk failed independently.

## Winner package and validation

Exactly one winner archive was built; no experimental loser was archived for
submission.

| Item | Value |
|---|---|
| Archive | `artifacts/grim_damage_conversion/winner/grim_a2_damage_v0.tar.gz` |
| Archive SHA-256 | `A44B676F5CA135747B5D4D6923C7FB350A66369D188315B6AC0F291D23CA69E7` |
| Archive size | 12,735,381 bytes |
| Extracted tree SHA-256 | `13426288358D597EAD809E45C364C7F7B9274A6EEBF55DDD942142E3326535C3` |
| Manifest SHA-256 | `AFCAB8295B0C906F238D55CFEC5DFDCF2E88C09CEDFB230328A71B73AC69CB40` |
| Deterministic double build | passed, byte-identical |
| Sterile validation | clean extraction, isolated import, 60-card handshake passed |
| Model/deck preservation | all three A2 models and exact deck hashes passed |
| Complete-game package smoke | 40 games, 3,902 winner decisions, zero policy/opponent errors |
| Packaged replay scope | 4,659 decisions, zero illegal/out-of-scope actions or errors |
| Packaged latency | p50 0.855 ms, p95 1.902 ms, p99 2.839 ms, max 51.119 ms |
| Upload | **not performed** |

## IS GRIM WORTH ANY MORE DEVELOPMENT?

**YES — narrowly.** The exact damage solver found real public tactical regret,
changed less than 0.6% of decisions, and produced a fresh statistically
positive d842 expansion without an order collapse. The next justified action
is one possible live probe of the packaged V0, not broader architecture,
training, benchmarking, V1 planning, or additional Punk work. If that live
probe does not transfer, keep A2 and move development time elsewhere.
