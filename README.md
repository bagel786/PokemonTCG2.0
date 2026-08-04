# Pokemon TCG AI — clean-room competition agent

This repository is the implementation workspace for the Kaggle Pokémon TCG AI Battle
simulation competition. The official engine, card data, and reference deck lists live in
`freshstart/`; all agent code in this repository is new.

The repository now contains three layers that share one competition runtime:

1. deterministic Grimmsnarl and Garchomp heuristics for a legal, dependable floor;
2. hidden-information-safe behavior cloning from public elite replays;
3. self-play collection and PPO-style policy refinement, guarded by head-to-head promotion gates.

**Compute policy:** run all RL game simulation—including self-play, PPO rollout
collection, co-evolution, and league-training simulations—on Azure. Use local
hardware only for development and small smoke checks unless explicitly
overridden. See `docs/OPERATIONS.md` for the Azure workflow.

The current best neural challenger is a Garchomp behavior-cloning policy. It beat its
matching heuristic 55.6% to 44.4% over 1,000 local games, but remains a candidate until
we expand its elite replay sample. The Grimmsnarl model and initial RL sample were rejected
by the promotion gates rather than automatically shipped.

## Quick checks

```bash
PYTHONPATH=vendor:. python3 -m unittest discover -s tests -v
PYTHONPATH=vendor:. python3 scripts/run_local.py --games 20
python3 scripts/package_submission.py --deck grimmsnarl
```

The packaged archive is written to `artifacts/` and always contains `main.py`, `deck.csv`,
the `ptcg_ai` package, and the synced official `cg` package at its root. See
`docs/OPERATIONS.md` for the daily workflow and `docs/EXPERIMENTS.md` for measured results
and artifact status.
