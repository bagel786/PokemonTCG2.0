#!/usr/bin/env bash
# sprint_870 stage N — final cells: exp15 + punk_target tournament.
set -u
ROOT="/Users/safiullahbaig/Projects/pokemonTCG2.0"
cd "$ROOT" || exit 1
PY=/Users/safiullahbaig/Projects/pokemonTCG2.0/.venv/bin/python
ENGINE=artifacts/deterministic_engine/bin/libcg_seeded.dylib
PROD=vendor/cg/libcg.dylib
OUT=artifacts/sprint_870
WINNER=artifacts/grim_damage_conversion/winner/extracted
EXP15=$OUT/exp15_punk_ct_second
EXP11B=$OUT/exp11b_punk_target
B0=artifacts/grim_variance_floor/candidates/B0
M1=artifacts/grim_damage_conversion/opponents/master_v1
RR=artifacts/grim_damage_conversion/opponents/replay_refresh
AZ24=$OUT/opponents/alakazam_2_4a
NOS='{"NO_SEARCH":"1"}'

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

# exp15 (punk_ct second-arm only) final word
run exp15_vs_ctl_B0_p600  $EXP15 $WINNER $B0 202608156600 300
# punk_target tournament (the best rail)
run exp11b_vs_ctl_m1_p600 $EXP11B $WINNER $M1 202608156700 300
run exp11b_vs_ctl_rr_p600 $EXP11B $WINNER $RR 202608156800 300
run exp11b_vs_az24_p400  $EXP11B $WINNER $AZ24 202608156900 200 "$NOS"
echo DONE
