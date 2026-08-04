# Rule 3: Kaggle Fleet Management & Control Arm Deployment

## 1. Context & Invariants
- **Two-Active Submission Limit**: Kaggle Simulations only matches games and updates leaderboard Elo for the **two most recent active submissions**. All earlier submissions are frozen and receive no new evaluation games.
- **Independent Rating Drift**: If a new challenger is submitted in isolation while the reference model is inactive, their ratings cannot be directly compared under changing ladder distributions.

---

## 2. Mandatory Fleet Operations

### Invariant 2.1: Paired Control Submission
- When deploying any new challenger candidate to Kaggle for live ladder evaluation, the frozen 5k reference control (`artifacts/overnight_grim_20260730/grim_selected.npz`) MUST be submitted in the same active pair (alongside or immediately following the challenger).
- Use `python scripts/package_submission.py --deck grimmsnarl --model artifacts/.../challenger.npz --paired-control` to generate matched archives.

### Invariant 2.2: Dual Promotion Gate Pre-requisite (Rule 2)
Before any package is submitted to Kaggle, it MUST pass `training/promotion_gate.py` with:
1. **5k Baseline Mirror Parity**: 48.0%–52.0% head-to-head win rate against `grim_selected.npz` (500+ seat-balanced games).
2. **Meta Gauntlet Dominance**: $\ge 80.0\%$ aggregate meta-weighted win rate across `training/meta_league.json`.
3. **No Historical Regressions**: $\ge 50.0\%$ win rate against all earlier generation snapshots.

### Invariant 2.3: Cleanroom Archive Audit
- All archives must be validated with `python scripts/validate_submission.py <archive.tar.gz>`.
- The engine `libcg.so` SHA-256 hash must match `scripts/sync_engine.py` official Linux build.
