#!/usr/bin/env bash
# sprint_870 stage F — EXP-7 confirmations + tournament cells (fast env proxies).
set -u
ROOT="/Users/safiullahbaig/Projects/pokemonTCG2.0"
cd "$ROOT" || exit 1
ENGINE=artifacts/deterministic_engine/bin/libcg_seeded.dylib
PROD=vendor/cg/libcg.dylib
OUT=artifacts/sprint_870
WINNER=artifacts/grim_damage_conversion/winner/extracted
EXP1=$OUT/exp1_a2_damage_punk
EXP7=$OUT/exp7_a2_damage_punk_playid
B0=artifacts/grim_variance_floor/candidates/B0
M1=artifacts/grim_damage_conversion/opponents/master_v1
RR=artifacts/grim_damage_conversion/opponents/replay_refresh
AZ24=$OUT/opponents/alakazam_2_4a
AZ27=$OUT/opponents/alakazam_2_7
DIP=$OUT/opponents/dipplin_d1
STAR=$OUT/opponents/starmie_v2_boss_atk
NOS='{"NO_SEARCH":"1"}'

run() {
  local name=$1 cand=$2 ctl=$3 opp=$4 seed=$5 pairs=$6 oppenv=$7
  local f=$OUT/${name}.json
  if [ -f "$f" ]; then echo "[skip] $name"; return; fi
  echo "[run] $name pairs=$pairs seed=$seed"
  /Users/safiullahbaig/Projects/pokemonTCG2.0/.venv/bin/python training/evaluate_deterministic_crn.py paired \
    --engine "$ENGINE" --production-engine "$PROD" \
    --candidate "$cand" --control "$ctl" --opponent "$opp" \
    --opponent-env "$oppenv" \
    --output "$f" --base-seed "$seed" --pairs-per-order "$pairs" \
    --actual-order both --workers 8 || echo "[FAIL] $name"
}

# EXP-7 confirmation, fresh seeds (fast grim opponents)
run exp7_vs_exp1_B0_p800b $EXP7 $EXP1 $B0 202608152000 400 '{}'
run exp7_vs_exp1_m1_p600  $EXP7 $EXP1 $M1 202608152100 300 '{}'
run exp7_vs_exp1_rr_p600  $EXP7 $EXP1 $RR 202608152200 300 '{}'
# EXP-7 total effect vs C0
run exp7_vs_ctl_B0_p600   $EXP7 $WINNER $B0 202608152300 300 '{}'
# Tournament: C0+EXP7 vs Alakazam (NO_SEARCH proxies, like dipplin screens)
run exp7_vs_az24_p400     $EXP7 $EXP1 $AZ24 202608152400 200 "$NOS"
run exp7_vs_az27_p400     $EXP7 $EXP1 $AZ27 202608152500 200 "$NOS"
# Tournament: Dipplin D1 + Starmie
run exp7_vs_dipplin_p400  $EXP7 $EXP1 $DIP  202608152600 200 '{}'
run exp7_vs_starmie_p400  $EXP7 $EXP1 $STAR 202608152700 200 '{}'
echo DONE
