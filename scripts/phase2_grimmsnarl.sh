#!/usr/bin/env bash
# Phase 2: grimmsnarl-only PPO warm-started from the submitted 5k, against the
# population phase 1 strengthened.
#
# Phase 1 rebuilds every learner from a BC prior, which for grimmsnarl means
# starting ~15% win rate against our own submission. Phase 2 instead keeps the
# 5k's training and gives it the strong opponents it lacked last night, when
# warm-starting failed only because every opponent was weaker than it.
set -euo pipefail
cd /mnt/ptcg/repo

P1=artifacts/coevo_p1
OUT=artifacts/coevo_p2
INCUMBENT=artifacts/bc_v3/grimmsnarl_5k_ported.npz
PY=/opt/ptcg-venv/bin/python
export PYTHONPATH=.:vendor

# Wait for phase 1 to finish.
while pgrep -f "[r]un_league.py" >/dev/null; do sleep 60; done

LAST=$(ls -d $P1/round_* 2>/dev/null | sort | tail -1)
[ -n "$LAST" ] || { echo "phase1 produced no rounds; aborting"; exit 1; }
echo "phase1 final round: $LAST"

mkdir -p $OUT
# League where every learner slot points at phase 1's strongest checkpoints.
$PY - "$LAST" "$OUT" <<'EOF'
import json,sys,glob,os
last,out=sys.argv[1],sys.argv[2]
league=json.load(open('training/coevolution_league.json'))
learners={l['name']:l for l in json.load(open('training/learners.json'))['learners']}
for e in league['opponents']:
    ck=os.path.join(last,"%s_challenger.npz"%e['name'])
    if e['name'] in learners and os.path.exists(ck):
        e['model']=os.path.abspath(ck)
json.dump(league,open(os.path.join(out,'league.json'),'w'),indent=2)
print("phase2 league written, learned slots:",sum(1 for e in league['opponents'] if e.get('model')))
EOF

# Collect with the incumbent itself, then one PPO step off those rollouts.
$PY training/collect_selfplay.py \
  --model $INCUMBENT \
  --hero-deck freshstart/decklists/grimmsnarl_marnie.deck.csv \
  --league $OUT/league.json \
  --games 3000 --workers 8 --temperature 0.65 --seed 20260732 \
  --output $OUT/rollouts.jsonl.gz

# bc-weight low: anchoring a 5k-trained policy to a much weaker BC prior drags it down.
$PY training/train_ppo.py \
  --initial-model $INCUMBENT \
  --rollouts $OUT/rollouts.jsonl.gz \
  --output $OUT/grimmsnarl_challenger.npz \
  --epochs 2 --learning-rate 1e-4 --bc-weight 0.05 --require-card 648 --seed 20260733 \
  --bc-shard data/processed/elite-2026-07-28-v3.jsonl.gz

$PY training/promotion_gate.py \
  --learner grimmsnarl_marnie \
  --challenger $OUT/grimmsnarl_challenger.npz \
  --incumbent $INCUMBENT \
  --snapshot artifacts/bc_v3/grimmsnarl_marnie.npz \
  --games 500 --workers 8 \
  --output-dir $OUT/gate

echo "PHASE2 COMPLETE"
