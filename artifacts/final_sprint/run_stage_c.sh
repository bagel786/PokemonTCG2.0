#!/usr/bin/env bash
# final_sprint stage C — EXP-20 (punk first-arm only) first-order screens.
set -u
ROOT="/Users/safiullahbaig/Projects/pokemonTCG2.0"
cd "$ROOT" || exit 1
PY=/Users/safiullahbaig/Projects/pokemonTCG2.0/.venv/bin/python
ENGINE=artifacts/deterministic_engine/bin/libcg_seeded.dylib
PROD=vendor/cg/libcg.dylib
OUT=artifacts/final_sprint
WINNER=artifacts/grim_damage_conversion/winner/extracted
B0=artifacts/grim_variance_floor/candidates/B0
M1=artifacts/grim_damage_conversion/opponents/master_v1
RR=artifacts/grim_damage_conversion/opponents/replay_refresh
EXP20=$OUT/exp20_punk_first_only

run() {
  local name=$1 cand=$2 ctl=$3 opp=$4 seed=$5 pairs=$6 order=$7
  local f=$OUT/${name}.json
  if [ -f "$f" ]; then echo "[skip] $name"; return; fi
  echo "[run] $name pairs=$pairs seed=$seed order=$order"
  $PY training/evaluate_deterministic_crn.py paired \
    --engine "$ENGINE" --production-engine "$PROD" \
    --candidate "$cand" --control "$ctl" --opponent "$opp" \
    --actual-order "$order" \
    --output "$f" --base-seed "$seed" --pairs-per-order "$pairs" \
    --workers 8 || echo "[FAIL] $name"
}

run exp20_vs_ctl_B0_first_p800  $EXP20 $WINNER $B0 202608161200 400 first
run exp20_vs_ctl_m1_first_p600  $EXP20 $WINNER $M1 202608161300 300 first
run exp20_vs_ctl_rr_first_p600  $EXP20 $WINNER $RR 202608161400 300 first
# second-order control (expect exactly 0: second arm identical)
run exp20_vs_ctl_B0_second_p400 $EXP20 $WINNER $B0 202608161500 200 second
echo DONE
