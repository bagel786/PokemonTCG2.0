#!/usr/bin/env bash
# sprint_870 stage G — EXP-8 (second-seat-only playid) + authentic Alakazam cell.
set -u
ROOT="/Users/safiullahbaig/Projects/pokemonTCG2.0"
cd "$ROOT" || exit 1
PY=/Users/safiullahbaig/Projects/pokemonTCG2.0/.venv/bin/python
ENGINE=artifacts/deterministic_engine/bin/libcg_seeded.dylib
PROD=vendor/cg/libcg.dylib
OUT=artifacts/sprint_870
EXP7=$OUT/exp7_a2_damage_punk_playid
EXP8=$OUT/exp8_playid_second_only
B0=artifacts/grim_variance_floor/candidates/B0
M1=artifacts/grim_damage_conversion/opponents/master_v1
AZ24=$OUT/opponents/alakazam_2_4a
WINNER=artifacts/grim_damage_conversion/winner/extracted

run() {
  local name=$1 cand=$2 ctl=$3 opp=$4 seed=$5 pairs=$6 oppenv=$7 order=${8:-both}
  local f=$OUT/${name}.json
  if [ -f "$f" ]; then echo "[skip] $name"; return; fi
  echo "[run] $name pairs=$pairs seed=$seed order=$order"
  $PY training/evaluate_deterministic_crn.py paired \
    --engine "$ENGINE" --production-engine "$PROD" \
    --candidate "$cand" --control "$ctl" --opponent "$opp" \
    --opponent-env "$oppenv" --actual-order "$order" \
    --output "$f" --base-seed "$seed" --pairs-per-order "$pairs" \
    --workers 8 || echo "[FAIL] $name"
}

# EXP-8 vs EXP-7 (removes first-seat playid; second seat identical)
run exp8_vs_exp7_B0_p600  $EXP8 $EXP7 $B0 202608152800 300 '{}'
run exp8_vs_exp7_m1_p600  $EXP8 $EXP7 $M1 202608152900 300 '{}'
# Authentic Alakazam 2.4a WITH search, 100 pairs (slow but real)
run exp7_vs_az24_auth_p200 $EXP7 $WINNER $AZ24 202608153000 100 '{}'
echo DONE
