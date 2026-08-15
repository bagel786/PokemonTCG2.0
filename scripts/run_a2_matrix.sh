#!/bin/bash
set -e

mkdir -p artifacts/dragapult_eval/ptcg_ai
cp -r freshstart/decklists/dragapult_ex.deck.csv artifacts/dragapult_eval/deck.csv

for model in artifacts/dragapult_emergency/*.npz; do
    echo "==============================================="
    echo "Evaluating $model vs A2+Damage V0 (50 games)"
    echo "==============================================="
    ln -sf "$(realpath "$model")" artifacts/dragapult_eval/direct_policy.npz
    
    .venv/bin/python3 training/evaluate.py \
      --deck-a artifacts/dragapult_eval/deck.csv \
      --submission-a artifacts/dragapult_eval \
      --deck-b freshstart/decklists/grimmsnarl_marnie.deck.csv \
      --model-b artifacts/overnight_grim_20260730/grim_selected.npz \
      --games 50 --workers 8
done
