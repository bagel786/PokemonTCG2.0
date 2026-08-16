#!/usr/bin/env bash
# Final-day live monitor: fetch EXP23 games, report W/L + score + parity.
set -u
W=/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight
cd "$W" || exit 1
echo "=== $(date '+%H:%M:%S %Z') ==="
$W/.venv/bin/python scripts/fetch_submission_games.py --submission 55556726 2>&1 | tail -2
kaggle competitions submissions pokemon-tcg-ai-battle 2>/dev/null | head -4
$W/.venv/bin/python scripts/overnight_20260816/live_parity_check.py 2>&1 | tail -2
