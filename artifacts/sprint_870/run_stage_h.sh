#!/usr/bin/env bash
# sprint_870 stage H — EXP-9 (seat-1 finetuned second arm) vs C0.
set -u
ROOT="/Users/safiullahbaig/Projects/pokemonTCG2.0"
cd "$ROOT" || exit 1
PY=/Users/safiullahbaig/Projects/pokemonTCG2.0/.venv/bin/python
ENGINE=artifacts/deterministic_engine/bin/libcg_seeded.dylib
PROD=vendor/cg/libcg.dylib
OUT=artifacts/sprint_870
WINNER=artifacts/grim_damage_conversion/winner/extracted
EXP9=$OUT/exp9_seat1_second
B0=artifacts/grim_variance_floor/candidates/B0
M1=artifacts/grim_damage_conversion/opponents/master_v1
RR=artifacts/grim_damage_conversion/opponents/replay_refresh
AZ24=$OUT/opponents/alakazam_2_4a

run() {
  local name=$1 cand=$2 ctl=$3 opp=$4 seed=$5 pairs=$6 oppenv=$7 order=$8
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

# Second-order (the actual change)
run exp9_vs_ctl_B0_second_p800  $EXP9 $WINNER $B0 202608153100 400 '{}' second
run exp9_vs_ctl_m1_second_p600  $EXP9 $WINNER $M1 202608153200 300 '{}' second
run exp9_vs_ctl_rr_second_p600  $EXP9 $WINNER $RR 202608153300 300 '{}' second
# First-order control (expect ~0 delta: first arm unchanged)
run exp9_vs_ctl_B0_first_p400   $EXP9 $WINNER $B0 202608153400 200 '{}' first
echo DONE
