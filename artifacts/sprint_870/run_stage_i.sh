#!/usr/bin/env bash
# sprint_870 stage I — model-zoo second-arm sweep vs C0 (B0, second order).
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
  local name=$1 cand=$2 seed=$3 pairs=$4
  local f=$OUT/${name}.json
  if [ -f "$f" ]; then echo "[skip] $name"; return; fi
  echo "[run] $name pairs=$pairs seed=$seed"
  $PY training/evaluate_deterministic_crn.py paired \
    --engine "$ENGINE" --production-engine "$PROD" \
    --candidate "$cand" --control "$WINNER" --opponent "$B0" \
    --actual-order second \
    --output "$f" --base-seed "$seed" --pairs-per-order "$pairs" \
    --workers 8 || echo "[FAIL] $name"
}

run zoo_5kaug_second_B0    $OUT/zoo/z_5kaug        202608154000 300
run zoo_lowband_second_B0  $OUT/zoo/z_lowband      202608154100 300
run zoo_masterv1_second_B0 $OUT/zoo/z_masterv1     202608154200 300
run zoo_rr_second_B0       $OUT/zoo/z_replayrefresh 202608154300 300
run zoo_bcv2ctl_second_B0  $OUT/zoo/z_bcv2ctl      202608154400 300
run zoo_bcv3_second_B0     $OUT/zoo/z_bcv3         202608154500 300
run zoo_bcv3marnie_second_B0 $OUT/zoo/z_bcv3marnie 202608154600 300
run zoo_5kported_second_B0 $OUT/zoo/z_5kported     202608154700 300
run zoo_temporal_second_B0 $OUT/zoo/z_temporal     202608154800 300
echo DONE
