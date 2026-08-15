#!/usr/bin/env bash
# final_sprint stage B — setup-tier confirmations + regression cells.
set -u
ROOT="/Users/safiullahbaig/Projects/pokemonTCG2.0"
cd "$ROOT" || exit 1
PY=/Users/safiullahbaig/Projects/pokemonTCG2.0/.venv/bin/python
ENGINE=artifacts/deterministic_engine/bin/libcg_seeded.dylib
PROD=vendor/cg/libcg.dylib
OUT=artifacts/final_sprint
WINNER=artifacts/grim_damage_conversion/winner/extracted
B0=artifacts/grim_variance_floor/candidates/B0
M1=artifacts/grim_damage_conversion/opponents/master_v1
RR=artifacts/grim_damage_conversion/opponents/replay_refresh
EXP17=$OUT/exp17_setup_tier
AZ24=$OUT/../sprint_870/opponents/alakazam_2_4a
AZ27=$OUT/../sprint_870/opponents/alakazam_2_7
DIP=$OUT/../sprint_870/opponents/dipplin_d1
STAR=$OUT/../sprint_870/opponents/starmie_v2_boss_atk
NOS='{"NO_SEARCH":"1"}'

run() {
  local name=$1 cand=$2 ctl=$3 opp=$4 seed=$5 pairs=$6 oppenv=${7:-'{}'}
  local f=$OUT/${name}.json
  if [ -f "$f" ]; then echo "[skip] $name"; return; fi
  echo "[run] $name pairs=$pairs seed=$seed"
  $PY training/evaluate_deterministic_crn.py paired \
    --engine "$ENGINE" --production-engine "$PROD" \
    --candidate "$cand" --control "$ctl" --opponent "$opp" \
    --opponent-env "$oppenv" --actual-order both \
    --output "$f" --base-seed "$seed" --pairs-per-order "$pairs" \
    --workers 8 || echo "[FAIL] $name"
}

# fresh-seed confirmations
run exp17_vs_ctl_B0_p1000  $EXP17 $WINNER $B0 202608160600 500
run exp17_vs_ctl_m1_p800   $EXP17 $WINNER $M1 202608160700 400
# regression cells (only meaningful if confirmations pass, but cheap enough to queue)
run exp17_vs_ctl_rr_p800   $EXP17 $WINNER $RR 202608160800 400
run exp17_vs_az24_p400     $EXP17 $WINNER $AZ24 202608160900 200 "$NOS"
run exp17_vs_az27_p400     $EXP17 $WINNER $AZ27 202608161000 200 "$NOS"
echo DONE
