#!/usr/bin/env bash
# sprint_870 staged screens — sequential cells, one evaluator at a time (8 workers).
set -u
ROOT="/Users/safiullahbaig/Projects/pokemonTCG2.0"
cd "$ROOT" || exit 1
ENGINE=artifacts/deterministic_engine/bin/libcg_seeded.dylib
PROD=vendor/cg/libcg.dylib
OUT=artifacts/sprint_870
WINNER=artifacts/grim_damage_conversion/winner/extracted
EXP1=$OUT/exp1_a2_damage_punk
EXP2=$OUT/exp2_a2_damage_punk_munk
B0=artifacts/grim_variance_floor/candidates/B0
M1=artifacts/grim_damage_conversion/opponents/master_v1
RR=artifacts/grim_damage_conversion/opponents/replay_refresh
A2CTL=artifacts/grim_damage_conversion/candidates/a2_control

run() {
  local name=$1 cand=$2 ctl=$3 opp=$4 seed=$5 pairs=$6
  local f=$OUT/${name}.json
  if [ -f "$f" ]; then echo "[skip] $name"; return; fi
  echo "[run] $name pairs=$pairs seed=$seed"
  python3 training/evaluate_deterministic_crn.py paired \
    --engine "$ENGINE" --production-engine "$PROD" \
    --candidate "$cand" --control "$ctl" --opponent "$opp" \
    --output "$f" --base-seed "$seed" --pairs-per-order "$pairs" \
    --actual-order both --workers 8 || echo "[FAIL] $name"
}

# Stage C confirmation of EXP-1 vs winner
run exp1_vs_ctl_B0_p1200  $EXP1 $WINNER $B0    202608150200 600
run exp1_vs_ctl_m1_p800   $EXP1 $WINNER $M1    202608150300 400
run exp1_vs_ctl_rr_p800   $EXP1 $WINNER $RR    202608150400 400
run exp1_vs_a2ctl_p800    $EXP1 $A2CTL $B0     202608150500 400
# EXP-2 (punk+munk) vs EXP-1
run exp2_vs_exp1_B0_p800  $EXP2 $EXP1   $B0    202608150600 400
run exp2_vs_exp1_m1_p600  $EXP2 $EXP1   $M1    202608150700 300
echo DONE
