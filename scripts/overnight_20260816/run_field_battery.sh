#!/usr/bin/env bash
# Overnight field battery (Phase 2) — paired CRN, fresh seed blocks.
# Wave 1: EXP-23 full vs C0, screen 100 pairs/order/cell.
# Wave 2: H23-S vs C0, same panel.
set -u
W=/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight
cd "$W" || exit 1
PY="$W/.venv/bin/python"
R=/Users/safiullahbaig/Projects/pokemonTCG2.0
ENGINE=$R/artifacts/deterministic_engine/bin/libcg_seeded.dylib
PROD=$R/vendor/cg/libcg.dylib
OUT=$W/artifacts/overnight_20260816/field
mkdir -p "$OUT"
C0=$R/artifacts/grim_damage_conversion/winner/extracted
EXP23=$R/artifacts/final_sprint/exp23_identity_trained
H23S=$R/artifacts/overnight_20260816/h23s
D842=$R/artifacts/overnight_20260816/d842_runtime
B0=$R/artifacts/grim_variance_floor/candidates/B0
M1=$R/artifacts/grim_damage_conversion/opponents/master_v1
RR=$R/artifacts/grim_damage_conversion/opponents/replay_refresh
AZ24=$R/artifacts/sprint_870/opponents/alakazam_2_4a
DIP=$R/artifacts/sprint_870/opponents/dipplin_d1
STAR=$R/artifacts/sprint_870/opponents/starmie_v2_boss_atk
NOS='{"NO_SEARCH":"1"}'

WAVE=${1:-1}
PAIRS=${2:-100}
WORKERS=${3:-6}
case $WAVE in
  1) CAND=$EXP23; TAG=exp23;;
  2) CAND=$H23S; TAG=h23s;;
  *) echo "unknown wave"; exit 1;;
esac

run() {
  local name=$1 opp=$2 seed=$3 pairs=$4 oppenv=${5:-'{}'}
  local f=$OUT/${TAG}_vs_${name}.json
  if [ -f "$f" ]; then echo "[skip] $f"; return; fi
  echo "[run] $f pairs=$pairs seed=$seed"
  $PY training/evaluate_deterministic_crn.py paired \
    --engine "$ENGINE" --production-engine "$PROD" \
    --candidate "$CAND" --control "$C0" --opponent "$opp" \
    --opponent-env "$oppenv" --actual-order both \
    --output "$f" --base-seed "$seed" --pairs-per-order "$pairs" \
    --workers "$WORKERS" || echo "[FAIL] $name"
}

B=$((202608180100 + WAVE * 1000))
run vs_B0_p${PAIRS}    "$B0"    $((B+0))  $PAIRS
run vs_m1_p${PAIRS}    "$M1"    $((B+1))  $PAIRS
run vs_rr_p${PAIRS}    "$RR"    $((B+2))  $PAIRS
run vs_d842_p${PAIRS}  "$D842"  $((B+3))  $PAIRS
run vs_az24nos_p${PAIRS} "$AZ24" $((B+4))  $PAIRS "$NOS"
run vs_starmie_p${PAIRS} "$STAR" $((B+5))  $PAIRS
run vs_dipplin_p${PAIRS} "$DIP"  $((B+6))  $PAIRS
echo DONE
