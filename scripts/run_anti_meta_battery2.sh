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
STAR=/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/sprint_870/opponents/starmie_v2_boss_atk
AZ=/Users/safiullahbaig/Projects/pokemonTCG2.0/artifacts/sprint_870/opponents/alakazam_2_4a
run() {
  local name=$1 cand=$2 opp=$3 pairs=$4 seed=$5 heroenv=${6:-'{}'} oppenv=${7:-'{}'} ctl=${8:-$E23}
  local f=$OUT/$name.json
  if [ -f "$f" ]; then echo "[skip] $name"; return; fi
  echo "[run] $name pairs=$pairs seed=$seed"
  $PY training/evaluate_deterministic_crn.py paired \
    --engine "$ENGINE" --production-engine "$PROD" \
    --candidate "$cand" --control "$ctl" --opponent "$opp" \
    --hero-env "$heroenv" --opponent-env "$oppenv" \
    --actual-order both --output "$f" --base-seed "$seed" \
    --pairs-per-order "$pairs" --workers 6 || echo "[FAIL] $name"
}
run a_dip_v2_d1   $P/router_dip_e23v2 "$D1" 60 2026081685 '{"PTCG_TARGET_ROUTE":"force_dipplin"}'
run a_dip_v2_d0   $P/router_dip_e23v2 "$D0" 60 2026081686 '{"PTCG_TARGET_ROUTE":"force_dipplin"}'
run a_dip_c0_d1   $P/router_dip_c0 "$D1" 60 2026081687 '{"PTCG_TARGET_ROUTE":"force_dipplin"}'
run p_parity_starmie $P/router_dip_e23 "$STAR" 60 2026081679
run p_parity_az_nos  $P/router_dip_e23 "$AZ"   60 2026081680 '{}' '{"NO_SEARCH":"1"}'
run p_parity_luc_star $P/router_luc_e23 "$STAR" 60 2026081682
echo BATTERY2_DONE
