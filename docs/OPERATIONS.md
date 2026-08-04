# Competition operations

## Azure training host

> **Compute policy:** All reinforcement-learning game simulation must run on
> Azure. This includes self-play/rollout collection, PPO generations,
> co-evolution rounds, league training, and large simulation jobs that feed an
> RL update. Local execution is limited to implementation, static/data checks,
> and small smoke tests unless the user explicitly overrides this policy.
> Deallocate Azure workers promptly after artifacts and metrics are synchronized.

The Azure CLI is installed locally but must be authenticated interactively before provisioning:

```bash
az login
az account show
export PTCG_AZURE_SSH_SOURCE="YOUR.PUBLIC.IP/32"
export PTCG_AZURE_SSH_KEY="$HOME/.ssh/id_ed25519.pub"
bash infra/provision_azure.sh
```

The default is a Spot `Standard_D16ds_v5`. The script restricts SSH to the supplied CIDR,
uses delete-on-eviction, and configures daily auto-shutdown. Check the quoted price, available
credit, and quota in the Azure portal before leaving the machine running. Do not upload Kaggle
credentials into the repository; configure them directly on the VM with `kaggle auth login`.

Fresh/student subscriptions may begin with only three Spot vCPUs and four regular vCPUs. In that
case, use the quota-safe regular fallback while a Spot quota increase is pending:

```bash
export PTCG_AZURE_PRIORITY=Regular
export PTCG_AZURE_SIZE=Standard_D4s_v5
bash infra/provision_azure.sh
```

`D4s_v5` has no temporary data disk, so `/mnt/ptcg` resides on the provisioned 64-GB OS disk.

The training data belongs on `/mnt/ptcg`. On SKUs without a temporary data disk—including the
current `D8s_v6`—this directory resides on the 64-GB OS disk. Treat the worker as disposable:
copy promoted `.npz` weights and metrics back locally before deleting or rebuilding the VM.

### Current worker

- Resource group: `ptcg-train-south-rg`
- VM: `ptcg-train`
- Region and size: South Central US, regular `Standard_D8s_v6` (8 vCPU / 32 GB)
- Project: `/mnt/ptcg/repo`
- Training Python: `/opt/ptcg-venv/bin/python`
- OAuth-compatible Kaggle Python: `/mnt/ptcg/kaggle-venv/bin/python`
- Auto-shutdown: 15:00 UTC for the 2026-07-30 overnight recovery; explicitly
  deallocate sooner after artifacts are synchronized

The public IP is intentionally not treated as stable documentation. Retrieve it with:

```bash
az vm show -d -g ptcg-train-south-rg -n ptcg-train --query publicIps -o tsv
```

## Replay and training sequence

```bash
python scripts/fetch_top_teams.py --limit 100
python scripts/fetch_public_data.py --date 2026-07-28 --limit 0 --workers 8
python scripts/sync_engine.py
PYTHONPATH=vendor:. python scripts/extract_replays.py \
  data/replays/2026-07-28 --teams data/top_teams.txt \
  --output data/processed/elite-2026-07-28.jsonl.gz

python training/train_bc.py data/processed/elite-*.jsonl.gz \
  --require-card 648 --epochs 3 --output artifacts/grimmsnarl-bc.npz
python training/train_bc.py data/processed/elite-*.jsonl.gz \
  --require-card 381 --epochs 3 --output artifacts/garchomp-bc.npz
```

Use `collect_selfplay.py` and `train_ppo.py` only after a BC checkpoint passes held-out
agreement and local head-to-head gates. PPO output is a challenger, never an automatic replacement.

### Lucario sparring curriculum

The two-variant Lucario curriculum builds its audited replay view, selects a BC
anchor, runs staged PPO, and emits recommendation-only qualification and Grim
handoff reports. Heavy runs are Azure-only:

```bash
python scripts/run_azure_lucario.py \
  --bc-shard artifacts/lucario_gap_20260803/data/lucario_expanded_raw.jsonl.gz \
  --stage-games 5000 --max-games 20000 --games-per-eval 500 --resume
```

The runner performs the 512-record/200-game Azure smoke first, applies the
adaptive 20% continuation and 35% per-variant qualification gates, and launches
matched Grim recovery only after Lucario qualifies. It enforces a $30 retail
compute ceiling and deallocates the VM on completion or failure.

For a local end-to-end plumbing check, use no more than 200 games and pass
`--allow-local-smoke` directly to `python -m training.run_lucario_curriculum`.
The controller never packages or submits an agent.

### Resumable Grimmsnarl recovery generation

The active 5,000-game run is ten atomic shards. Re-running the same command keeps
valid completed shards and regenerates only missing/corrupt ones:

```bash
python training/collect_sharded.py \
  --model artifacts/overnight_grim_20260730/grim_bc_best.npz \
  --hero-deck decks/grimmsnarl.csv \
  --league training/overnight_grim_league.json \
  --games 5000 --shard-size 500 --workers 8 \
  --temperature 0.70 --gae-lambda 0.95 --seed 20260730 \
  --output-dir artifacts/overnight_grim_20260730/rl_5k

python scripts/summarize_rollouts.py \
  artifacts/overnight_grim_20260730/rl_5k/rollouts.jsonl.gz \
  --output artifacts/overnight_grim_20260730/rl_5k/summary.json
```

The phase/PID manifest is
`artifacts/overnight_grim_20260730/run.json`. Never interpret collection win rate
as promotion evidence: the hero explores stochastically while several regression
opponents are intentionally weak or frozen.

## Systemic Guardrails & Rules

### Rule 1: The Dual-Anchor Principle for League & Sparring
Never train any learner with a 100% single-opponent distribution or `bc_weight < 0.05`:
- **Meta Anchor**: Minimum 30–40% games allocated to diverse meta archetypes / historical elite bots (`alakazam_2_7`, `alakazam_2_4a`).
- **Human Prior Anchor**: Mandatory `bc_weight >= 0.05` (default `0.50`) and valid `--bc-shard` in `training/train_ppo.py` to preserve tournament-grade macro play.
- **Trust Region Bounds**: `target_kl <= 0.02`, `hard_kl <= 0.04`.

### Rule 2: Paired Ladder Benchmark & Promotion Invariant
Every challenger candidate must be evaluated through `training/promotion_gate.py` across five criteria:
1. **Head-to-Head**: Beating the incumbent it would replace (`win_rate >= 0.52`).
2. **Snapshot Regressions**: Beating all historical generation checkpoints (`win_rate >= 0.50`).
3. **5k Baseline Parity**: Maintaining 48.0%–52.0% mirror parity against `artifacts/overnight_grim_20260730/grim_selected.npz`.
4. **Meta Gauntlet Dominance**: Achieving $\ge 80.0\%$ aggregate meta-weighted win rate against `training/meta_league.json`.
5. **Held-Out Anchor**: Evaluating against frozen external submissions.

```bash
python training/promotion_gate.py \
  --learner grimmsnarl \
  --challenger artifacts/challenger.npz \
  --incumbent artifacts/incumbent.npz \
  --baseline-5k artifacts/overnight_grim_20260730/grim_selected.npz \
  --meta-league training/meta_league.json \
  --output-dir artifacts/eval_promotion
```

### Rule 3: Kaggle Fleet Management & Paired Control Deployment
- **Two-Active Submission Limit**: Kaggle only calculates active leaderboard scores and pairs matchmaking games for the **2 most recent submissions**. Older submissions become frozen.
- **Paired Deployment**: When uploading a new challenger to Kaggle, submit both the challenger and the 5k reference control (`grim_selected.npz`) using `--paired-control` so they occupy the 2 active queue slots simultaneously.

## Promotion and packaging

```bash
# Package challenger alongside 5k reference control
python scripts/package_submission.py \
  --deck grimmsnarl \
  --model artifacts/promoted.npz \
  --name grimmsnarl-promoted \
  --paired-control

# Validate both archives
python scripts/validate_submission.py artifacts/grimmsnarl-promoted.tar.gz
python scripts/validate_submission.py artifacts/grimmsnarl-5k-control-baseline.tar.gz
```

Never submit the files named `*-sample-not-promoted*`. Before any Kaggle upload, refresh the
official `cg/` directory with `scripts/sync_engine.py`, rebuild the archive, and compare its
`libcg.so` hash with the package manifest.
