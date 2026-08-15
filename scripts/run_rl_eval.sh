#!/bin/bash
set -e

RL_CANDIDATE="trace_rl_pilot/rl_candidate.npz"
OPPONENT="artifacts/a2_damage_v0"

# We package the RL candidate into a temporary directory so we can run CompetitionAgent on it
rm -rf trace_rl_pilot/eval_pkg
cp -r artifacts/dragapult_eval trace_rl_pilot/eval_pkg
cp "$RL_CANDIDATE" trace_rl_pilot/eval_pkg/direct_policy.npz

echo "Evaluating RL Candidate vs A2+Damage V0 (100 games)..."
.venv/bin/python3 training/evaluate.py \
    --deck-a trace_rl_pilot/eval_pkg/deck.csv \
    --submission-a trace_rl_pilot/eval_pkg \
    --deck-b "$OPPONENT/deck.csv" \
    --submission-b "$OPPONENT" \
    --games 100 \
    --workers 8 \
    --output "trace_rl_pilot/eval_rl_vs_a2.json"

echo "Evaluation Complete."
