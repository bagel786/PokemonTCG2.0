#!/usr/bin/env bash
# sprint_870 stage L — EXP-10 confirmations + remaining tournament cells.
set -u
ROOT="/Users/safiullahbaig/Projects/pokemonTCG2.0"
cd "$ROOT" || exit 1
PY=/Users/safiullahbaig/Projects/pokemonTCG2.0/.venv/bin/python
ENGINE=artifacts/deterministic_engine/bin/libcg_seeded.dylib
PROD=vendor/cg/libcg.dylib
OUT=artifacts/sprint_870
WINNER=artifacts/grim_damage_conversion/winner/extracted
EXP10=$OUT/exp10_mirror_specialist
EXP8=$OUT/exp8_playid_second_only
EXP7=$OUT/exp7_a2_damage_punk_playid
B0=artifacts/grim_variance_floor/candidates/B0
M1=artifacts/grim_damage_conversion/opponents/master_v1
AZ24=$OUT/opponents/alakazam_2_4a
STAR=$OUT/opponents/starmie_v2_boss_atk

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

# EXP-10 vs master_v1 (strongest mirror opponent) - both orders
run exp10_vs_ctl_m1_p600    $EXP10 $WINNER $M1 202608155400 300 '{}'
# EXP-10 vs B0 fresh seeds (confirmation)
run exp10_vs_ctl_B0_p800b   $EXP10 $WINNER $B0 202608155500 400 '{}'
# EXP-8 (playid second-only) vs EXP-7
run exp8_vs_exp7_B0_p600    $EXP8 $EXP7 $B0 202608155600 300 '{}'
# Starmie 100 pairs
run exp7_vs_starmie_p200    $EXP7 $WINNER $STAR 202608155700 100 '{}'
# Authentic Alakazam with search, 100 pairs
run exp7_vs_az24_auth_p200  $EXP7 $WINNER $AZ24 202608155800 100 '{}'
echo DONE
