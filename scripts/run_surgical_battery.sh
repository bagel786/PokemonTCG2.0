#!/usr/bin/env bash
set -u
cd /Users/safiullahbaig/Projects/pokemonTCG2.0-anti-meta || exit 1
PY=python3
ENGINE=/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/deterministic_engine/bin/libcg_seeded.dylib
PROD=/Users/safiullahbaig/Projects/pokemonTCG2.0/vendor/cg/libcg.dylib
OUT=artifacts/anti_meta_20260816/eval
mkdir -p "$OUT"
E23=/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/final_sprint/exp23_identity_trained
P=artifacts/anti_meta_20260816/packages
D1=/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/sprint_870/opponents/dipplin_d1
D0=$P/dip_d0
B0=/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/grim_variance_floor/candidates/B0
AZ=/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/sprint_870/opponents/alakazam_2_4a
run() {
  local name=$1 opp=$2 pairs=$3 seed=$4 heroenv=$5 oppenv=${6:-'{}'}
  local f=$OUT/$name.json
  if [ -f "$f" ]; then echo "[skip] $name"; return; fi
  echo "[run] $name pairs=$pairs seed=$seed"
  $PY training/evaluate_deterministic_crn.py paired \
    --engine "$ENGINE" --production-engine "$PROD" \
    --candidate "$P/router_surg" --control "$E23" --opponent "$opp" \
    --hero-env "$heroenv" --opponent-env "$oppenv" \
    --actual-order both --output "$f" --base-seed "$seed" \
    --pairs-per-order "$pairs" --workers 6 || echo "[FAIL] $name"
}
run s_dip_a_d1 "$D1" 60 2026081691 '{"PTCG_TARGET_ROUTE":"force_dipplin","PTCG_SURGICAL":"dip_a"}'
run s_dip_a_d0 "$D0" 60 2026081692 '{"PTCG_TARGET_ROUTE":"force_dipplin","PTCG_SURGICAL":"dip_a"}'
run s_dip_b_d1 "$D1" 60 2026081693 '{"PTCG_TARGET_ROUTE":"force_dipplin","PTCG_SURGICAL":"dip_b"}'
run s_dip_b_d0 "$D0" 60 2026081694 '{"PTCG_TARGET_ROUTE":"force_dipplin","PTCG_SURGICAL":"dip_b"}'
run s_parity_b0 "$B0" 60 2026081695 '{"PTCG_SURGICAL":"dip_a,dip_b"}'
run s_parity_az "$AZ" 60 2026081696 '{"PTCG_SURGICAL":"dip_a,dip_b"}' '{"NO_SEARCH":"1"}'
echo SURG_BATTERY_DONE
