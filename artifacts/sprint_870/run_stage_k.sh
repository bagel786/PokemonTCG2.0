#!/usr/bin/env bash
# sprint_870 stage K — punk-component ablation screens vs C0.
set -u
ROOT="/Users/safiullahbaig/Projects/pokemonTCG2.0"
cd "$ROOT" || exit 1
PY=/Users/safiullahbaig/Projects/pokemonTCG2.0/.venv/bin/python
ENGINE=artifacts/deterministic_engine/bin/libcg_seeded.dylib
PROD=vendor/cg/libcg.dylib
OUT=artifacts/sprint_870
WINNER=artifacts/grim_damage_conversion/winner/extracted
B0=artifacts/grim_variance_floor/candidates/B0

run() {
  local name=$1 cand=$2 seed=$3
  local f=$OUT/${name}.json
  if [ -f "$f" ]; then echo "[skip] $name"; return; fi
  echo "[run] $name seed=$seed"
  $PY training/evaluate_deterministic_crn.py paired \
    --engine "$ENGINE" --production-engine "$PROD" \
    --candidate "$cand" --control "$WINNER" --opponent "$B0" \
    --actual-order both \
    --output "$f" --base-seed "$seed" --pairs-per-order 300 \
    --workers 8 || echo "[FAIL] $name"
}

# wait for the exp10 screen to finish first
while [ ! -f $OUT/exp10_vs_ctl_B0_p600.json ]; do sleep 10; done

run exp11a_vs_ctl_B0 $OUT/exp11a_punk_ac     202608155100
run exp11b_vs_ctl_B0 $OUT/exp11b_punk_target 202608155200
run exp11c_vs_ctl_B0 $OUT/exp11c_punk_count  202608155300
echo DONE
