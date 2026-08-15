#!/usr/bin/env bash
# sprint_870 stage D — ladder screens for EXP-2..EXP-6 vs EXP-1/C0.
set -u
ROOT="/Users/safiullahbaig/Projects/pokemonTCG2.0"
cd "$ROOT" || exit 1
ENGINE=artifacts/deterministic_engine/bin/libcg_seeded.dylib
PROD=vendor/cg/libcg.dylib
OUT=artifacts/sprint_870
WINNER=artifacts/grim_damage_conversion/winner/extracted
EXP1=$OUT/exp1_a2_damage_punk
EXP2=$OUT/exp2_a2_damage_punk_munk
EXP3=$OUT/exp3_a2_damage_tempo
EXP4=$OUT/exp4_a2_damage_guardrails
EXP5=$OUT/exp5_a2_damage_punk_attach
EXP6=$OUT/exp6_a2_damage_punk_boss
B0=artifacts/grim_variance_floor/candidates/B0
M1=artifacts/grim_damage_conversion/opponents/master_v1

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

# EXP-3 (tempo) total effect and ladder vs EXP-1
run exp3_vs_ctl_B0_p600   $EXP3 $WINNER $B0 202608151100 300
run exp3_vs_exp1_B0_p600  $EXP3 $EXP1   $B0 202608150900 300
run exp3_vs_exp1_m1_p400  $EXP3 $EXP1   $M1 202608151000 200
# EXP-4 (guardrails) total effect vs C0 and ladder vs EXP-1
run exp4_vs_ctl_B0_p600   $EXP4 $WINNER $B0 202608151200 300
run exp4_vs_exp1_B0_p600  $EXP4 $EXP1   $B0 202608151300 300
# EXP-5 (punk+attach) ladder vs EXP-1
run exp5_vs_exp1_B0_p600  $EXP5 $EXP1   $B0 202608151400 300
run exp5_vs_exp1_m1_p400  $EXP5 $EXP1   $M1 202608151500 200
# EXP-6 (punk+boss) ladder vs EXP-1
run exp6_vs_exp1_B0_p600  $EXP6 $EXP1   $B0 202608151600 300
echo DONE
