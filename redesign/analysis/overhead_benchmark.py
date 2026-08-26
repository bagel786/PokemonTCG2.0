"""Frozen Analysis Plan M11: 50-run instrumented-versus-bare benchmark."""

import json
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmark.adapters import HoldemAdapter, IsingAdapter


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/final/aggregates/overhead.json"
RUNS = 50


def percentile(values, q):
    return float(np.percentile(np.asarray(values, dtype=float), q))


def bare_holdem(seed):
    import rlcard
    env = rlcard.make("limit-holdem", config={"seed": int(seed) & 0xFFFFFFFF})
    rng = np.random.default_rng(seed)
    total = 0.0
    for _ in range(10):
        env.reset()
        while not env.is_over():
            player = env.get_player_id()
            state = env.get_state(player)
            actions = [int(x) for x in state["legal_actions"].keys()]
            env.step(actions[int(rng.integers(0, len(actions)))])
        total += float(env.get_payoffs()[0])
    return total


def bare_ising(seed):
    from ising_toolkit.models import Ising2D
    from ising_toolkit.samplers import MetropolisSampler
    model = Ising2D(size=20, temperature=2.269, use_numba=False)
    model.set_seed(int(seed))
    sampler = MetropolisSampler(model, seed=int(seed))
    value = 0.0
    for sweep in range(110):
        sampler.step()
        if sweep >= 20 and (sweep - 20) % 10 == 0:
            value += abs(float(model.get_magnetization()))
    return value / 9


def time_call(fn, *args):
    start = time.perf_counter()
    fn(*args)
    return time.perf_counter() - start


def main():
    seed_rng = np.random.default_rng(917_202_608_26)
    seeds = [int(x) for x in seed_rng.integers(2**20, 2**31, size=RUNS)]
    results = []
    for system in ("holdem", "ising"):
        instrumented, bare = [], []
        if system == "holdem":
            adapter = HoldemAdapter(num_hands=10)
            for seed in seeds:
                instrumented.append(time_call(adapter.run_arm, seed, "random"))
                bare.append(time_call(bare_holdem, seed))
        else:
            adapter = IsingAdapter(size=20, sweeps=90, equilibration=20)
            for seed in seeds:
                instrumented.append(time_call(adapter.run_arm, seed, 2.269))
                bare.append(time_call(bare_ising, seed))
        med_i = percentile(instrumented, 50)
        med_b = percentile(bare, 50)
        fraction = (med_i - med_b) / med_b if med_b else math.nan
        results.append({
            "system": system, "runs": RUNS,
            "instrumented_median_s": med_i,
            "instrumented_p95_s": percentile(instrumented, 95),
            "bare_median_s": med_b,
            "bare_p95_s": percentile(bare, 95),
            "trace_overhead_fraction": fraction,
            "trace_overhead_percent": 100 * fraction,
            "seed_bank": "analysis-only RNG seed 91720260826; disjoint from pilot/final",
            "interpretation": "microbenchmark of wrapper instrumentation path; not per-method runtime",
        })
    OUT.write_text(json.dumps({"kind": "M11_TRACE_OVERHEAD", "results": results},
                              indent=2, sort_keys=True) + "\n")
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
