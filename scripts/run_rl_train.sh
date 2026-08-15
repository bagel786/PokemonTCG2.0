#!/bin/bash
set -e

ACTOR="artifacts/dragapult_emergency/bc_combined_8ep.npz"
ROLLOUTS="trace_rl_pilot/rollouts.jsonl.gz"
OUT="trace_rl_pilot/rl_candidate.npz"

echo "Training Dragapult Outcome RL Pilot..."
.venv/bin/python3 training/outcome_rl.py \
    --initial-actor "$ACTOR" \
    --rollouts "$ROLLOUTS" \
    --output-actor "$OUT" \
    --output-critic "trace_rl_pilot/rl_critic.pt" \
    --manifest "trace_rl_pilot/rl_manifest.json" \
    --allow-local-smoke \
    --epochs 1 \
    --actor-lr 2e-6 \
    --critic-lr 2e-4 \
    --clip-ratio 0.10 \
    --entropy-weight 0 \
    --auxiliary-weight 0 \
    --hard-kl 0.01 \
    --temperature 0.15 \
    --seed 2026080901
