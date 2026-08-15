#!/usr/bin/env bash
# sprint_870 stage E — EXP-5/EXP-7 screens + tournament cells for C0.
set -u
ROOT="/Users/safiullahbaig/Projects/pokemonTCG2.0"
cd "$ROOT" || exit 1
ENGINE=artifacts/deterministic_engine/bin/libcg_seeded.dylib
PROD=vendor/cg/libcg.dylib
OUT=artifacts/sprint_870
WINNER=artifacts/grim_damage_conversion/winner/extracted
EXP1=$OUT/exp1_a2_damage_punk
EXP5=$OUT/exp5_a2_damage_punk_attach
EXP7=$OUT/exp7_a2_damage_punk_playid
B0=artifacts/grim_variance_floor/candidates/B0
M1=artifacts/grim_damage_conversion/opponents/master_v1
AZ24=$OUT/opponents/alakazam_2_4a
AZ27=$OUT/opponents/alakazam_2_7

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

# EXP-5 (punk+attach) ladder vs EXP-1
run exp5_vs_exp1_B0_p600  $EXP5 $EXP1 $B0 202608151400 300
run exp5_vs_exp1_m1_p400  $EXP5 $EXP1 $M1 202608151500 200
# EXP-7 (play identity) vs EXP-1
run exp7_vs_exp1_B0_p600  $EXP7 $EXP1 $B0 202608151700 300
# Tournament: EXP-1 (+punk) vs Alakazam authentic agents, control=winner
run exp1_vs_az24_p400     $EXP1 $WINNER $AZ24 202608151800 200
run exp1_vs_az27_p400     $EXP1 $WINNER $AZ27 202608151900 200
echo DONE
