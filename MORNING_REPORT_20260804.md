# Morning report — 2026-08-04 overnight runs

## Bottom line

**Nothing was shipped.** Both overnight candidates failed gates, for opposite reasons, and together they close the book on this training recipe. Your Kaggle slots are unchanged (active: 55228869 refresh-challenger at 726.8, 55222011 5k-reference at 835.4). VM is deallocated. Total overnight Azure spend ≈ $3–4.

## What ran

Both runs: PPO from the replay-refresh anchor on 5,000 rollout games vs the high-band league (45% mirror across 4 strong Grim pilots, 18% authentic Alakazam, 23% meta, 14% Lucario/Iono), 65% of games going second, turn-1 bench reward 0.05, BC anchor = elite shard + 3,217 mined anti-Lucario/Iono demonstration decisions.

### Run 1 — conservative (lr 1e-5, KL 0.01/0.02): FLAT
- approx_kl 0.0018 — update ~10× under budget, behaviorally a no-op.
- Mirror seat-1: 48.1% vs 47.9% baseline (+0.2, noise). Seat-0: 51.6% vs 54.2%.
- Lucario 89.3 vs 89.4 (flat). Authentic Alakazam 2_4a held (72.5 vs 73.5); 2_7 dipped 74.0→65.5 at n=200 (failed 3% tolerance, wide CI).
- Full report: `artifacts/highband_20260804/final_report.json`

### Run 2 — aggressive (lr 1e-4, KL 0.03/0.05, 2 epochs): REGRESSED
- Epoch 1 completed at approx_kl 0.030 (a real update); epoch 2 hit the hard-KL wall and rolled back to end-of-epoch-1.
- Mirror vs anchor: **46.5%** overall (control 51.1) — worse both seats (47.5/45.4).
- vs Lucario: **77.1%** vs 89.4 baseline — 12-point regression.
- Killed remaining gates early (verdict determined); partials in `artifacts/highband_aggressive_20260804/`.

## The conclusion these two runs force

The two KL regimes bracket the recipe:
- **Tiny updates change nothing** (two independent runs, kl ≈ 0.0015–0.0018, all gates flat).
- **Real updates make it worse** (kl 0.030 → mirror and Lucario both regress).

PPO on this league from this anchor has no good direction to move: the rollout signal (mostly mirror games between near-identical strong pilots + knockoff opponents) doesn't encode a better policy than the anchor already has. The replay-refresh anchor sits at a local optimum for the training signal we can currently generate.

## What actually has headroom (recommended next moves, in order)

1. **Demonstration mining at scale.** The one lever with a proven mechanism (replay-refresh itself came from elite replays). Use the daily Kaggle top-episodes dataset (kaggle.com/datasets/kaggle/pokemon-tcg-ai-battle-episodes-index) to build a large fresh elite shard — especially Grim-mirror games from top teams (fixes seat-1 by imitation of players who are good at going second) and wins vs Lucario/Iono/Alakazam. Then a **BC refresh** (targeted_refresh pipeline, not PPO). Infrastructure exists: `scripts/mine_anti_archetype.py` pattern + `training/replay_refresh.py` / `training/targeted_refresh.py`.
2. **Ship-nothing is a valid ladder move today**: 55222011 (5k ref) at 835 is still active and climbing territory; consider whether the 04:09 refresh-challenger (726.8, early-game variance band) should keep its slot or be replaced by a fresh 5k-reference resubmit for another cold-start sample.
3. Drop: more PPO variants on the current league (both regimes now refuted), exposure vs weak recreations (refuted yesterday), MCTS adversary (parked; too slow for the deadline).

## Assets from tonight (reusable)

- 5,000-game rollout corpus vs the high-band league: `artifacts/highband_20260804/rollouts/`
- Anti-archetype demonstration shard (35 games/3,217 decisions): `artifacts/anti_archetype_20260804/`
- Miner: `scripts/mine_anti_archetype.py` (generalizes to any deck/archetype)
- Driver with full knob set: `training/run_lowband_exposure.py` (seat ratio, bench reward, extra BC shards, KL/epochs/lr all CLI)
- Kaggle CLI re-authed (safm1rza).

## Gate evidence (aggressive run, why no-ship was mandatory)

| Gate | Anchor | Aggressive candidate |
|---|---|---|
| Mirror overall | 51.1% | 46.5% |
| Mirror seat-0 / seat-1 | 54.2 / 47.9 | 47.5 / 45.4 |
| vs Lucario | 89.4% | 77.1% |

Zero engine/policy errors in every match; the numbers are real, not artifacts.
