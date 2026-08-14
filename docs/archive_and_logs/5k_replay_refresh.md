# 5k elite-replay refresh experiment

`training.replay_refresh` is an experiment-only behavioral-cloning pipeline.
It verifies the deployed archive and model hashes before training, freezes the
shared model, and updates only the option, score, count, and value heads.

Run the reduced real-data smoke test first:

```bash
.venv/bin/python -m training.replay_refresh \
  --output-dir artifacts/5k_replay_refresh_20260802/smoke \
  --candidate-limit 1 --epochs 1 --batch-size 128 \
  --max-train-records 512 --max-evaluation-records 256 \
  --shuffle-buffer 512 --skip-matches
```

Run the locked nine-candidate experiment on CPU:

```bash
.venv/bin/python -m training.replay_refresh \
  --output-dir artifacts/5k_replay_refresh_20260802/full \
  --split-manifest artifacts/5k_replay_refresh_20260802/smoke2/split_manifest.json \
  --device cpu --resume
```

CPU is explicit for this workload because its many small ragged policy-KL
operations benchmark substantially faster than MPS. `--device auto` still
implements the general CUDA, MPS, CPU preference order.

The runner cannot create archives or submit agents. Every final report carries
`experiment_only: true`, `submitted: false`, and `package_created: false`.
Interrupted candidate training/evaluation can be resumed with `--resume`;
existing checkpoints are reused only after their recorded hashes verify.
