#!/usr/bin/env bash
set -euo pipefail

PTCG_DATE="${1:?usage: run_remote_cycle.sh YYYY-MM-DD [--skip-fetch]}"
PTCG_MODE="${2:-}"
PTCG_ROOT="${PTCG_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PTCG_KAGGLE_PYTHON="${PTCG_KAGGLE_PYTHON:-python3}"
PTCG_TRAIN_PYTHON="${PTCG_TRAIN_PYTHON:-python3}"
PTCG_WORKERS="${PTCG_WORKERS:-8}"
PTCG_BASE_SHARD="${PTCG_BASE_SHARD:-data/processed/elite-2026-07-28-500.jsonl.gz}"
PTCG_NEW_SHARD="data/processed/elite-${PTCG_DATE}.jsonl.gz"
PTCG_MODEL="artifacts/garchomp-bc-${PTCG_DATE}.npz"

cd "$PTCG_ROOT"

if [[ "$PTCG_MODE" != "--skip-fetch" ]]; then
  "$PTCG_KAGGLE_PYTHON" scripts/fetch_public_data.py \
    --date "$PTCG_DATE" --limit 0 --workers "$PTCG_WORKERS"
fi

PYTHONPATH=vendor:. "$PTCG_TRAIN_PYTHON" scripts/extract_replays.py \
  "data/replays/${PTCG_DATE}" \
  --teams data/top_teams.txt \
  --output "$PTCG_NEW_SHARD"

"$PTCG_TRAIN_PYTHON" training/train_bc.py \
  "$PTCG_BASE_SHARD" "$PTCG_NEW_SHARD" \
  --require-card 381 --epochs 8 --output "$PTCG_MODEL"

PYTHONPATH=vendor:. "$PTCG_TRAIN_PYTHON" training/evaluate.py \
  --deck-a decks/garchomp.csv --model-a "$PTCG_MODEL" \
  --deck-b decks/garchomp.csv \
  --games 2000 --workers "$PTCG_WORKERS"

PYTHONPATH=vendor:. "$PTCG_TRAIN_PYTHON" training/evaluate.py \
  --deck-a decks/garchomp.csv --model-a "$PTCG_MODEL" \
  --deck-b decks/grimmsnarl.csv \
  --games 2000 --workers "$PTCG_WORKERS"
