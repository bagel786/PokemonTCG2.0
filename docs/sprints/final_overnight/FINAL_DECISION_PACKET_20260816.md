# FINAL-DAY DECISION PACKET — 2026-08-16

**Compiled for the ~4:43 PM CDT higher-reasoning review. Updated as evidence arrives.**
Branch: `final/overnight-20260816` @ `9d974bb` (+ today's uncommitted eval outputs).

---

## TOP SECTION — READ THIS FIRST

- **Current time:** ~12:35 CDT (updates below).
- **Submissions used today:** 1 (EXP23). **Remaining:** 4.
- **Current active two (newest first):** `55556726` EXP23 (884.4) + `55537754` C0 (723.9).
  - Both already live. Producing this exact pair requires ZERO further submissions.

### C0 — known status
- Archive A44B676F…, tree 13426288…, model B19871A9…, deck 92B92BAC… (verified on disk today).
- Frozen champion; ladder TrueSkill has reverted (both C0 copies ~580–735 band; variance, not decay).

### EXP23 — full identity-trained (SUBMITTED 15:23 UTC, ref 55556726)
- **Archive SHA256:** `0734B60C089EEA9C2E40550B8E9C6DC3983957210794BA245C4C00BD9D4E7096`
- **Model SHA256 (both arms):** `CEFE6118…` — verified inside the submitted tar today.
- **CERT-B (5 teams, 40 eps, 529 decisive): 0.440 [0.389, 0.488]** → FAILS the frozen
  55% pass bar; in the "<49% red flag" band.
  - first 0.403 [0.321,0.483], second 0.475 [0.425,0.530]
  - early 0.57 / mid 0.52 / **late 0.30** ← dominant signature
  - per team: Dreamer 0.29(7) GrimmsnaRL 0.48(113) Mint120 0.40(96) TMTA 0.42(12) lollipop947 0.45(170)
  - zero policy errors on both packages
- **CERT-B(0813) secondary (16 units, 169 decisive): 0.455 [0.354, 0.566]** — replicates the
  verdict on data NEITHER model trained on (strongly weakens any C0 home-field confound;
  note EXP23's fresh corpus is temporally closer to CERT-B than to 0813, yet results are
  near-identical: 0.440 vs 0.455).
  - **late 0.304 replicated**; early 0.54, mid 0.58; **first 0.455 = second 0.455 (NO order asymmetry)**
  - only 2 of 5 teams present (GrimmsnaRL n=94, TMTA n=38) — honest power caveat
- **Calibration:** metric ranks correctly — d842 0.431, EXP20 0.211 (both below C0).
- **Field (paired CRN, fresh seeds, zero errors everywhere):**
  - Grim mirrors big-N: B0-fresh +4.17 SIG, m1 +6.38 SIG, m1-fresh +5.75 SIG, rr +6.25 SIG, B0 +3.38 ns, d842 400p +2.5 ns → Grim-family pooled ≈ +4.5pp (~3,600 pairs)
  - Non-Grim: az24nos pooled 800p ≈ **-1.6pp ns** (Alakazam = 19% meta), az24 search-on -2.0 ns (100p), starmie +1.7 (600p), dipplin +1.0 (400p)
  - Wave-1 7-cell macro (100p/order): **+1.8pp**; meta-weighted (renormalized, 54% coverage): **≈ +2.0pp**
  - Both arms positive on Grim mirrors at big N (first +2.5…+6.8, second +2.0…+9.0)
- **Live (14:00 CDT):** 27 games vs real opponents, **17W-10L (63%)**, score ~840 band.
  Zero errors; self-parity byte-identical on all fetched replays.
  - **Matchup ledger:**
    - Grim mirror: **5W-1L (83%)** — field's +4.5pp mirror gain REPRODUCED LIVE
    - Alakazam: **6W-0L** — local az24 proxy (-1.6pp) under-predicted; live very beatable
    - Dragapult: **1W-4L (20%)** — live weak spot (deck-level 40% elite baseline; see
      DRAGAPULT_SURGICAL_HANDOFF — no safe policy fix found, mostly structural/tempo)
    - Dipplin 0-1, other 5-4
  - Loss causes: tempo (first Grim ≥ t8) in 3, close prize races in 6, Munk-clutter
    co-occurring in 6. No policy blunders or mechanism failures identified.
  - Full detail: `docs/sprints/final_overnight/EXP23_LIVE_LOSS_ANALYSIS_20260816.md`
- **Late-game divergence anatomy (233 CERT-B late decisive rows):**
  - c0_approved 112: elite+C0 agree on ABILITY activations (Munkidori 44, Spikemuth 18), attacks, energy
  - cand_approved 48: EXP23 matches elite on plays (Night Stretcher, Spikemuth, Rare Candy)
  - abstain 73: EXP23 plays basics/supporters late (Impidimp 8, Petrel 7, Snorunt 6, Froslass 6) that BOTH elite and C0 avoid
- **Verdict: KEEP, but as challenger — not champion.** Field says +5pp vs Grim mirrors
  (33% of ladder), ~neutral-negative vs Alakazam (19%), unknown vs 37% unsupported field;
  held-out identity metric fails on both cert layers. Hedge with C0.

### H23-S — NOT BUILT
- CERT-B(0813) shows **no first/second asymmetry** (0.455 = 0.455); big-N field shows BOTH arms
  positive on Grim mirrors. Order-shield rationale is dead. Skipped per predeclared gates.
- CERT-C (matsurih, 21 eps / 2,042 rows) remains SEALED per frozen protocol.

### Other candidates
- None. EXP20 is neutralized (0.211 on calibration); no new builds today.

---

## FINALISTS RANKED
1. **EXP23 full** (55556726) — best field evidence ever recorded for this project; failed held-out identity bar; live = clean mechanism.
2. **C0** (55537754) — frozen champion, safe, live-reverted rating but proven.
3. (reserve) byte-identical EXP23 duplicate — only if Saf wants a variance hedge and accepts dropping C0.

## RECOMMENDED ACTIVE PAIR
**EXP23 + C0** (current state). Zero submissions needed. Keeps 4 in reserve for
emergency/re-push or a late switch.

## SEQUENCE NEEDED
None — 55556726 + 55537754 are already the newest two. If later evidence (live blunders/
errors) demands dropping EXP23: submit C0 copy once → active becomes C0+C0.
If Saf wants EXP23+EXP23: submit one byte-identical EXP23 tar (same file, sha 0734B60C…) →
active becomes EXP23+EXP23. Do NOT do both.

## DECISION RULES (applied at ~4:43 review, after live update)
- **Default: DO NOTHING.** EXP23+C0 already active; keeps all 4 submissions in reserve.
- Switch to **EXP23+EXP23** (1 submission) only if live EXP23 shows ≥ ~15 games, score
  clearly ≥ ~800, zero errors/blunders, AND Saf accepts dropping the C0 hedge.
- Switch to **C0+C0** (1 submission) only if live EXP23 develops errors or collapses
  below the C0 band (≈580–725) with ≥ ~15 games.
- Anything else (new candidates) is out of scope today.

---

## RAW EVIDENCE (linked)
- CERT-B: `artifacts/overnight_20260816/cert_exp23_vs_c0.json` (+ `.rows.jsonl.gz`)
- CERT-B(0813): `artifacts/overnight_20260816/cert_exp23_0813.json` (+ rows); raw episodes `heldout_raw/2026-08-13/` (104 files, re-downloaded today, deleted 20GB temp)
- Calibration: `calib_d842_vs_c0.json`, `calib_exp20_vs_c0.json`
- Field wave-1: `field/exp23_vs_vs_*_p100.json`; big-N: `artifacts/final_sprint/exp23_vs_*_p*.json`
- Live replay bank + parity: `data/replays/55556726/`, `scripts/overnight_20260816/live_parity_check.py`
- Late-game diagnostic: `artifacts/overnight_20260816/late_divergence_diagnostic.jsonl.gz`
- Protocol: `docs/sprints/final_overnight/OVERNIGHT_CERT_20260816.md`
- Clerical fix today: EXP23 package-tree hash in cert doc corrected 9F12…→83489… (frozen_hashes.json authoritative). Archive's order_policy_manifest.json still shows stale B198/CONTROLLED_LADDER_PROBE labels — NOT rebuilt by directive; runtime loads policy_first/second.npz (CEFE6118…) with PLAY_IDENTITY_ENABLED=True, verified inside tar.
