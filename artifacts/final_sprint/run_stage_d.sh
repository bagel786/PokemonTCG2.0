#!/usr/bin/env bash
# final_sprint stage D — EXP-23 confirmation battery.
set -u
ROOT="/Users/safiullahbaig/Projects/pokemonTCG2.0"
cd "$ROOT" || exit 1
PY=/Users/safiullahbaig/Projects/pokemonTCG2.0/.venv/bin/python
ENGINE=artifacts/deterministic_engine/bin/libcg_seeded.dylib
PROD=vendor/cg/libcg.dylib
OUT=artifacts/final_sprint
WINNER=artifacts/grim_damage_conversion/winner/extracted
EXP23=$OUT/exp23_identity_trained
B0=artifacts/grim_variance_floor/candidates/B0
M1=artifacts/grim_damage_conversion/opponents/master_v1
RR=artifacts/grim_damage_conversion/opponents/replay_refresh
AZ24=$OUT/../sprint_870/opponents/alakazam_2_4a
AZ27=$OUT/../sprint_870/opponents/alakazam_2_7
STAR=$OUT/../sprint_870/opponents/starmie_v2_boss_atk
NOS='{"NO_SEARCH":"1"}'

run() {
  local name=$1 cand=$2 ctl=$3 opp=$4 seed=$5 pairs=$6 oppenv=${7:-'{}'} order=${8:-both}
  local f=$OUT/${name}.json
  if [ -f "$f" ]; then echo "[skip] $name"; return; fi
  echo "[run] $name pairs=$pairs seed=$seed"
  $PY training/evaluate_deterministic_crn.py paired \
    --engine "$ENGINE" --production-engine "$PROD" \
    --candidate "$cand" --control "$ctl" --opponent "$opp" \
    --opponent-env "$oppenv" --actual-order "$order" \
    --output "$f" --base-seed "$seed" --pairs-per-order "$pairs" \
    --workers 8 || echo "[FAIL] $name"
}

run exp23_vs_ctl_B0_p1200b  $EXP23 $WINNER $B0 202608170200 600
run exp23_vs_ctl_m1_p800   $EXP23 $WINNER $M1 202608170300 400
run exp23_vs_ctl_rr_p800   $EXP23 $WINNER $RR 202608170400 400
run exp23_vs_az24_p400     $EXP23 $WINNER $AZ24 202608170500 200 "$NOS"
run exp23_vs_az27_p400     $EXP23 $WINNER $AZ27 202608170600 200 "$NOS"
run exp23_vs_starmie_p400  $EXP23 $WINNER $STAR 202608170700 200 '{}'
echo DONE
