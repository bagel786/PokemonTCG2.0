from __future__ import annotations

import math

import numpy as np

from resource_envelope_study.adapters.ising import (
    ISING_TC,
    IsingConfig,
    IsingLattice,
    effective_sample_size,
    exact_expectations,
    sample_independent_chains,
    split_r_hat,
)


def test_ising_sweep_count_observable_units_and_seed_replay() -> None:
    config = IsingConfig(lattice_size=4, temperature=ISING_TC, burn_in_sweeps=0)
    first = IsingLattice(config, 901)
    second = IsingLattice(config, 901)
    for _ in range(17):
        first.sweep()
        second.sweep()
    assert first.completed_sweeps == second.completed_sweeps == 17
    assert first.attempted_flips == second.attempted_flips == 17 * 16
    np.testing.assert_array_equal(first.spins, second.spins)
    assert -1.0 <= first.magnetization_per_spin() <= 1.0
    assert -2.0 <= first.energy_per_spin() <= 2.0


def test_ising_tiny_lattice_reference_and_convergence_diagnostics() -> None:
    low = exact_expectations(2, temperature=0.2)
    high = exact_expectations(2, temperature=100.0)
    assert low["mean_energy_per_spin"] < -1.99
    assert low["mean_absolute_magnetization"] > 0.99
    assert abs(high["mean_energy_per_spin"]) < 0.1
    assert 0.35 < high["mean_absolute_magnetization"] < 0.45

    chains = sample_independent_chains(
        IsingConfig(lattice_size=2, temperature=3.5, burn_in_sweeps=300),
        seeds=[11, 22, 33, 44],
        measured_sweeps=800,
    )
    assert math.isfinite(split_r_hat(chains["energy_per_spin"]))
    assert split_r_hat(chains["energy_per_spin"]) < 1.10
    assert effective_sample_size(chains["energy_per_spin"]) > 20
