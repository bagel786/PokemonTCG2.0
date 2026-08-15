#!/bin/bash
set -e

ACTOR="artifacts/dragapult_emergency/bc_combined_8ep.npz"
DECK="freshstart/decklists/dragapult_ex.deck.csv"
OPPONENT="artifacts/a2_damage_v0"
mkdir -p trace_rl_pilot

echo "Collecting 250 games for Dragapult RL Pilot vs A2+Damage V0 using 5 workers..."

for i in {0..4}; do
    SEED=$((20260814 + i * 50))
    .venv/bin/python3 training/collect_outcome_rl.py \
        --actor "$ACTOR" \
        --deck "$DECK" \
        --opponent "$OPPONENT" \
        --games 50 \
        --temperature 0.15 \
        --q-compare-rate 0 \
        --seed $SEED \
        --output "trace_rl_pilot/rollout_$i.jsonl.gz" &
done

wait

echo "Rollouts Complete. Merging..."
cat trace_rl_pilot/rollout_*.jsonl.gz > trace_rl_pilot/rollouts.jsonl.gz

echo "Done."
