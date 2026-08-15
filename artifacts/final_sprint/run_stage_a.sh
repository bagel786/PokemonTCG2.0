#!/usr/bin/env bash
# final_sprint stage A — exp17/exp18 discovery screens + punk_target fresh confirmation.
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
EXP17=$OUT/exp17_setup_tier
EXP18=$OUT/exp18_candy_t2
EXP11B=$OUT/../sprint_870/exp11b_punk_target

run() {
  local name=$1 cand=$2 ctl=$3 opp=$4 seed=$5 pairs=$6 oppenv=${7:-'{}'}
  local f=$OUT/${name}.json
  if [ -f "$f" ]; then echo "[skip] $name"; return; fi
  echo "[run] $name pairs=$pairs seed=$seed"
  $PY training/evaluate_deterministic_crn.py paired \
    --engine "$ENGINE" --production-engine "$PROD" \
    --candidate "$cand" --control "$ctl" --opponent "$opp" \
    --opponent-env "$oppenv" --actual-order both \
    --output "$f" --base-seed "$seed" --pairs-per-order "$pairs" \
    --workers 8 || echo "[FAIL] $name"
}

run exp17_vs_ctl_B0_p600  $EXP17 $WINNER $B0 202608160200 300
run exp18_vs_ctl_B0_p600  $EXP18 $WINNER $B0 202608160300 300
# punk_target fresh-seed confirmation (bigger, both grim opponents)
run punk_vs_ctl_B0_p1000b $EXP11B $WINNER $B0 202608160400 500
run punk_vs_ctl_m1_p1000b $EXP11B $WINNER $M1 202608160500 500
echo DONE
