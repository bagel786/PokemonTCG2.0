# System Card: 2D Ising Metropolis Monte Carlo

- Role: open scientific/physical simulator
- Upstream: <https://github.com/ddsyasas/ising-monte-carlo-toolkit>
- Version: v0.1.0; commit `93515592d4942af757808a88ce527076cd0706c4`
- License: MIT
- Adapter: `code/benchmark/adapters.py` (`IsingAdapter`)
- Lattice: 20 x 20; 20 equilibration plus 90 measurement sweeps
- Arms: T=2.269 versus T=2.9
- Outcome: mean absolute magnetization over every tenth post-equilibration sweep
- Random sources: site selection and Metropolis acceptance
- Trace projection: magnetization-trajectory hash, terminal absolute
  magnetization, and measurement count

Limitations: pure Python is used for draw transparency; critical slowing down
limits equilibrium claims; S4/S8 do not inject the intended clock-residual
mechanics in this wrapper; results concern fixed-budget observables rather than
equilibrium thermodynamics. The young upstream package is pinned exactly.
