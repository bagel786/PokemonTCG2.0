# DRAGAPULT MATCHUP REPORT — 2026-08-16 (~13:10 CDT)

Live EXP23 vs Dragapult: **1W-3L** (n=4). C0 same-day bank vs Dragapult: 2W-0L (n=2, weak).
Elite control (0815 dump, exact Grim deck, any team): **70W-105L (40%)** over 175 games.

## The four EXP23 games

| Ep | Result | Opp | We went | Turns | First Grim ex | Notes |
|---|---|---|---|---|---|---|
| 93671387 | L | tellurium_rrr (55556789) | 2nd | ~10 | t6 | Prize lead 4-1 at truncation; game adjudicated against us (no recorded KO of final state; opp board Dragapult ex + Drakloak + Latias + Fezandipiti) |
| 93673237 | L | Shelgon (55537036) | 1st | ~11 | t5 | Opp burst 6→5→2 prizes (3 in one turn, Phantom Dive spread + chain); we lost race 4-5, still had Grimmsnarl active at end |
| 93679642 | W | ゼミ費ください (55553813) | 1st | ~9 | t7 | Fast win: 5 prizes in 5 turns; opponent never stabilized (final board: no active, only Dragapult ex + Drakloak on bench) |
| 93685951 | L | tellurium_rrr (55556789) | 1st | ~15 | t11 | Slowest start; attacker exhaustion — final board Munkidori active, bench Munkidori/Froslass/Munkidori/Snorunt/Impidimp, ZERO Grimmsnarl left; opp burst 4→1 prizes t13-14 |

## Elite patterns vs Dragapult (0815 dump, 175 games)

- **It's a tempo race.** First Grimmsnarl ex on turn 3 → **83% win** (10/12); t4 41%, t5 44%,
  t6 56%, t7 42%, t8+ collapses (26/17/11/0%); never got Grimmsnarl → 0/12.
- Mid-game bench development matters: min bench (turns 3-8) of 5 → 69% win, 4 → 56%,
  3 → 40%, 2 → 24%, 0-1 → ≤43% (tiny n at 0).
- Even the best human teams (Gemini ch., Dries @ Tufa Labs, Shang Bo, kurigen, tennogh)
  lose ~60% of these matchups with the exact 60-card Grim deck. **The weakness is
  deck-level, not policy-level.**

## Connection to CERT-B late-game divergence

EXP23's CERT-B signature = playing extra basics/supporters late-game (Impidimp/Petrel/
Snorunt/Froslass) where elite+C0 prefer abilities/attacks. Late bench bodies are
Phantom Dive spread + Dusknoir Cursed Blast fodder. The ep93685951 final board
(Munkidori/Froslass/Snorunt/Impidimp bench, no attacker) is consistent with this —
but with n=4 and a 40% deck-level baseline, this is a hypothesis, not a verdict.

## Specialist-route feasibility assessment

- Detection is easy and public: opponent basics (Dreepy/Duskull/Budew) are visible in
  observations from turn 1-2.
- What a specialist could change: max-aggression setup (candy→Grimmsnarl rush), early
  Boss-priority on Dreepy/Drakloak, no late bench basics. Elite evidence supports the
  tempo lever (83% at t3).
- BUT: the matchup ceiling is set by the DECK (40% elite), not the policy; any policy
  delta is a small edge on a bad baseline.
- Cost: build + parity-proof + field-test + package + 1 of 4 submissions, inside a
  hard 4:15 PM CDT engineering freeze (~3h away). High risk to the final fleet.
- A parallel agent is already running `train_target_specialist.py` (CPU-active since
  ~11:50). Duplicating that work is wasteful.

**Recommendation: do NOT build a Dragapult specialist today.** Keep EXP23+C0 active.
If the parallel specialist finishes, is parity-proven, and passes gates BEFORE 4:15,
raise it at the 4:43 review as an optional third finalist — otherwise skip.
