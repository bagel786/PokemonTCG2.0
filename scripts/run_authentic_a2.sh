#!/bin/bash
set -e

mkdir -p artifacts/dragapult_eval/ptcg_ai
cp -r freshstart/decklists/dragapult_ex.deck.csv artifacts/dragapult_eval/deck.csv
cp submission/main.py artifacts/dragapult_eval/main.py

MODELS=(
    "artifacts/dragapult_emergency/bc_combined_8ep.npz"
    "artifacts/dragapult_emergency/bc_combined_grim3.npz"
    "artifacts/dragapult_emergency/bc_combined_sem.npz"
    "artifacts/dragapult_emergency/bc_flg_full.npz"
)

# Smoke test
echo "Running 10-game smoke tests vs authentic A2+Damage V0..."
for model in "${MODELS[@]}"; do
    echo "==============================================="
    echo "Smoke testing $model"
    echo "==============================================="
    ln -sf "$(realpath "$model")" artifacts/dragapult_eval/direct_policy.npz
    
    .venv/bin/python3 training/evaluate.py \
      --deck-a artifacts/dragapult_eval/deck.csv \
      --submission-a artifacts/dragapult_eval \
      --deck-b artifacts/a2_damage_v0/deck.csv \
      --submission-b artifacts/a2_damage_v0 \
      --games 10 --workers 4 \
      --output "eval_smoke_$(basename "$model" .npz).json"
done

# Full 100 games
echo "Running 100-game matrix vs authentic A2+Damage V0..."
for model in "${MODELS[@]}"; do
    echo "==============================================="
    echo "Evaluating $model vs A2+Damage V0 (100 games)"
    echo "==============================================="
    ln -sf "$(realpath "$model")" artifacts/dragapult_eval/direct_policy.npz
    
    .venv/bin/python3 training/evaluate.py \
      --deck-a artifacts/dragapult_eval/deck.csv \
      --submission-a artifacts/dragapult_eval \
      --deck-b artifacts/a2_damage_v0/deck.csv \
      --submission-b artifacts/a2_damage_v0 \
      --games 100 --workers 8 \
      --output "eval_authentic100_$(basename "$model" .npz).json"
done
