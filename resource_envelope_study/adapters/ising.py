"""Open 2D ferromagnetic Ising companion with auditable Metropolis sweeps."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import product
from typing import Any

import numpy as np

from ..canonical import hash_json
from ..telemetry import WorkCounters


ISING_TC = 2.0 / math.log(1.0 + math.sqrt(2.0))


@dataclass(frozen=True)
class IsingConfig:
    lattice_size: int = 16
    temperature: float = ISING_TC
    coupling_j: float = 1.0
    burn_in_sweeps: int = 200

    def validate(self) -> None:
        if self.lattice_size < 2:
            raise ValueError("lattice_size must be at least 2")
        if not math.isfinite(self.temperature) or self.temperature <= 0:
            raise ValueError("temperature must be finite and positive")
        if not math.isfinite(self.coupling_j) or self.coupling_j <= 0:
            raise ValueError("coupling_j must be finite and positive")
        if self.burn_in_sweeps < 0:
            raise ValueError("burn_in_sweeps cannot be negative")


class IsingLattice:
    """Square periodic lattice with ``J/k_B = coupling_j``.

    One declared sweep is exactly ``L**2`` sequential single-spin Metropolis
    proposals.  The proposal site is sampled uniformly with replacement, a
    standard random-scan convention frozen in the protocol.
    """

    def __init__(self, config: IsingConfig, seed: int):
        config.validate()
        self.config = config
        self.rng = np.random.Generator(np.random.PCG64(int(seed)))
        self.spins = self.rng.choice(np.asarray([-1, 1], dtype=np.int8), size=(config.lattice_size, config.lattice_size))
        self.attempted_flips = 0
        self.accepted_flips = 0
        self.completed_sweeps = 0

    def sweep(self) -> None:
        size = self.config.lattice_size
        temperature = self.config.temperature
        coupling = self.config.coupling_j
        for _ in range(size * size):
            row = int(self.rng.integers(0, size))
            column = int(self.rng.integers(0, size))
            spin = int(self.spins[row, column])
            neighbor_sum = int(
                self.spins[(row - 1) % size, column]
                + self.spins[(row + 1) % size, column]
                + self.spins[row, (column - 1) % size]
                + self.spins[row, (column + 1) % size]
            )
            delta_energy = 2.0 * coupling * spin * neighbor_sum
            self.attempted_flips += 1
            if delta_energy <= 0.0 or float(self.rng.random()) < math.exp(-delta_energy / temperature):
                self.spins[row, column] = -spin
                self.accepted_flips += 1
        self.completed_sweeps += 1

    def magnetization_per_spin(self) -> float:
        return float(np.sum(self.spins, dtype=np.int64)) / float(self.spins.size)

    def energy_per_spin(self) -> float:
        horizontal = np.sum(self.spins * np.roll(self.spins, -1, axis=1), dtype=np.int64)
        vertical = np.sum(self.spins * np.roll(self.spins, -1, axis=0), dtype=np.int64)
        return -self.config.coupling_j * float(horizontal + vertical) / float(self.spins.size)

    def state_hash(self) -> str:
        return hash_json(
            {
                "config": {
                    "lattice_size": self.config.lattice_size,
                    "temperature": self.config.temperature,
                    "coupling_j": self.config.coupling_j,
                    "burn_in_sweeps": self.config.burn_in_sweeps,
                },
                "spins": self.spins.astype(int).tolist(),
            }
        )


@dataclass
class IsingSearchAdapter:
    """Expose one Metropolis sweep as one resource-envelope work unit."""

    agent_id: str = "ising_metropolis_random_scan"

    def configure_instrumentation(self, enabled: bool) -> None:
        self._instrumentation_enabled = bool(enabled)

    def reset_case(self, state: Any, agent_seed: int) -> None:
        config = IsingConfig(
            lattice_size=int(state["lattice_size"]),
            temperature=float(state["temperature"]),
            coupling_j=float(state.get("coupling_j", 1.0)),
            burn_in_sweeps=int(state.get("burn_in_sweeps", 200)),
        )
        self.lattice = IsingLattice(config, int(agent_seed))
        self._initial_hash = self.lattice.state_hash()

    def prepare(self) -> None:
        # Burn-in is deliberately outside the measurement budget.
        for _ in range(self.lattice.config.burn_in_sweeps):
            self.lattice.sweep()
        self._measurement_start_sweeps = self.lattice.completed_sweeps
        self._measurement_start_attempts = self.lattice.attempted_flips

    def perform_unit(self) -> WorkCounters | None:
        self.lattice.sweep()
        if not self._instrumentation_enabled:
            return None
        return WorkCounters(
            work_units=1,
            sweeps=1,
            forward_model_calls=self.lattice.spins.size,
        )

    def select_action(self) -> tuple[list[int], list[float], str]:
        magnetization = self.lattice.magnetization_per_spin()
        energy = self.lattice.energy_per_spin()
        return [], [magnetization, abs(magnetization), energy], ""

    def cleanup(self) -> None:
        return None

    def state_hash(self) -> str:
        # The comparison state is the pre-burn-in independently seeded lattice.
        return self._initial_hash


def exact_expectations(lattice_size: int, temperature: float, coupling_j: float = 1.0) -> dict[str, float]:
    """Enumerate a tiny torus exactly; intended for L<=4 correctness tests."""

    if lattice_size < 2 or lattice_size > 4:
        raise ValueError("exact enumeration is restricted to 2 <= L <= 4")
    if temperature <= 0:
        raise ValueError("temperature must be positive")
    energies: list[float] = []
    absolute_magnetizations: list[float] = []
    for flat in product((-1, 1), repeat=lattice_size * lattice_size):
        spins = np.asarray(flat, dtype=np.int8).reshape(lattice_size, lattice_size)
        horizontal = np.sum(spins * np.roll(spins, -1, axis=1), dtype=np.int64)
        vertical = np.sum(spins * np.roll(spins, -1, axis=0), dtype=np.int64)
        energy_total = -coupling_j * float(horizontal + vertical)
        energies.append(energy_total)
        absolute_magnetizations.append(abs(float(np.sum(spins))) / spins.size)
    energy_array = np.asarray(energies, dtype=np.float64)
    log_weights = -energy_array / temperature
    log_weights -= float(np.max(log_weights))
    weights = np.exp(log_weights)
    weights /= float(np.sum(weights))
    return {
        "mean_energy_per_spin": float(np.sum(weights * energy_array)) / (lattice_size * lattice_size),
        "mean_absolute_magnetization": float(
            np.sum(weights * np.asarray(absolute_magnetizations, dtype=np.float64))
        ),
    }


def sample_independent_chains(
    config: IsingConfig,
    seeds: list[int],
    measured_sweeps: int,
) -> dict[str, np.ndarray]:
    """Return per-chain observables for convergence/reference checks."""

    if len(set(map(int, seeds))) != len(seeds):
        raise ValueError("each Ising chain requires a distinct seed")
    if measured_sweeps <= 1:
        raise ValueError("measured_sweeps must exceed one")
    magnetization = np.empty((len(seeds), measured_sweeps), dtype=np.float64)
    energy = np.empty_like(magnetization)
    for chain_index, seed in enumerate(seeds):
        lattice = IsingLattice(config, seed)
        for _ in range(config.burn_in_sweeps):
            lattice.sweep()
        for sweep_index in range(measured_sweeps):
            lattice.sweep()
            magnetization[chain_index, sweep_index] = abs(lattice.magnetization_per_spin())
            energy[chain_index, sweep_index] = lattice.energy_per_spin()
    return {"absolute_magnetization": magnetization, "energy_per_spin": energy}


def split_r_hat(chains: np.ndarray) -> float:
    """Split-chain Gelman-Rubin R-hat for a 2D ``chain x draw`` array."""

    values = np.asarray(chains, dtype=np.float64)
    if values.ndim != 2 or values.shape[0] < 2 or values.shape[1] < 4:
        raise ValueError("R-hat needs at least two chains and four draws")
    half = values.shape[1] // 2
    split = np.concatenate((values[:, :half], values[:, -half:]), axis=0)
    draws = split.shape[1]
    within = float(np.mean(np.var(split, axis=1, ddof=1)))
    between = draws * float(np.var(np.mean(split, axis=1), ddof=1))
    if within == 0.0:
        return 1.0 if between == 0.0 else math.inf
    variance = ((draws - 1) / draws) * within + between / draws
    return math.sqrt(max(0.0, variance / within))


def effective_sample_size(chains: np.ndarray) -> float:
    """Conservative initial-positive-sequence ESS for auditable pilot gating."""

    values = np.asarray(chains, dtype=np.float64)
    if values.ndim != 2 or values.shape[0] < 2 or values.shape[1] < 4:
        raise ValueError("ESS needs at least two chains and four draws")
    chain_count, draws = values.shape
    centered = values - np.mean(values, axis=1, keepdims=True)
    variance = float(np.mean(np.sum(centered * centered, axis=1) / (draws - 1)))
    if variance == 0.0:
        return float(chain_count * draws)
    rho_sum = 0.0
    previous_pair = math.inf
    lag = 1
    while lag + 1 < draws:
        correlations: list[float] = []
        for current_lag in (lag, lag + 1):
            covariance = float(
                np.mean(
                    np.sum(
                        centered[:, : draws - current_lag] * centered[:, current_lag:],
                        axis=1,
                    )
                    / (draws - current_lag)
                )
            )
            correlations.append(covariance / variance)
        pair = correlations[0] + correlations[1]
        if pair < 0:
            break
        pair = min(pair, previous_pair)
        previous_pair = pair
        rho_sum += pair
        lag += 2
    return min(float(chain_count * draws), float(chain_count * draws) / max(1.0, 1.0 + 2.0 * rho_sum))
