#!/usr/bin/env bash
# sprint_870 stage M — damage v1, punk_ct, punk_ct+playid screens + tournament.
set -u
ROOT="/Users/safiullahbaig/Projects/pokemonTCG2.0"
cd "$ROOT" || exit 1
PY=/Users/safiullahbaig/Projects/pokemonTCG2.0/.venv/bin/python
ENGINE=artifacts/deterministic_engine/bin/libcg_seeded.dylib
PROD=vendor/cg/libcg.dylib
OUT=artifacts/sprint_870
WINNER=artifacts/grim_damage_conversion/winner/extracted
EXP12=$OUT/exp12_damage_v1
EXP13=$OUT/exp13_punk_ct
EXP14=$OUT/exp14_punk_ct_playid
B0=artifacts/grim_variance_floor/candidates/B0
M1=artifacts/grim_damage_conversion/opponents/master_v1
RR=artifacts/grim_damage_conversion/opponents/replay_refresh
AZ24=$OUT/opponents/alakazam_2_4a
AZ27=$OUT/opponents/alakazam_2_7
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

# wait for stage L to finish
while pgrep -f "evaluate_deterministic_crn" > /dev/null; do sleep 15; done

# damage solver v1 (chip breakpoints)
run exp12_vs_ctl_B0_p600  $EXP12 $WINNER $B0 202608155900 300
# punk count+target combo
run exp13_vs_ctl_B0_p600  $EXP13 $WINNER $B0 202608156000 300
run exp13_vs_ctl_m1_p600  $EXP13 $WINNER $M1 202608156100 300
run exp13_vs_ctl_rr_p600  $EXP13 $WINNER $RR 202608156200 300
# punk_ct + playid combo
run exp14_vs_ctl_B0_p600  $EXP14 $WINNER $B0 202608156300 300
# tournament for the winner(s)
run exp13_vs_az24_p400    $EXP13 $WINNER $AZ24 202608156400 200 "$NOS"
run exp13_vs_az27_p400    $EXP13 $WINNER $AZ27 202608156500 200 "$NOS"
echo DONE
