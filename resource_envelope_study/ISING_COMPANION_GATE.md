# Ising companion implementation and gate

Current status: **APS_NO_GO pending real pilot evidence**. This status does not
change, rescue, or qualify any Pokemon result.

## Frozen implementation contract

- Model: zero-field, ferromagnetic, square-periodic two-dimensional Ising model
  with `J/k_B = 1`.
- Main lattice: `L = 16` by default; every manifest records `L` explicitly.
- Temperatures: `1.5`, exact Onsager
  `Tc = 2 / log(1 + sqrt(2))`, and `3.5`.
- Update: uniformly sampled, with-replacement, single-spin random-scan
  Metropolis proposals.
- Work unit: one sweep, exactly `L^2` attempted proposals.
- Burn-in: completed before the measured stop policy starts.
- Observables: magnetization per spin, absolute magnetization per spin, and
  energy per spin.
- Independent unit: an independently seeded chain block. Its seed is replayed
  across the four matched budget/load cells, but no two chain IDs reuse a seed.
- Load schedule: at least 20 paired batches with exact AB/BA load-period
  balance. Condition order and within-period execution order are derived from
  canonical SHA-256 streams.

`ising_experiment.py` owns the numerical case payload and deterministic
manifest. Fixed sweeps use `FixedWorkStop`; clocks are sampled only for
telemetry and cannot affect fixed-work control flow. Adversarial clock streams
produce identical sweep counts and scientific fingerprints in tests.

`ising_acquire.py` is the executable acquisition path. It does not provision or
start Azure. On an already-authorized Azure Linux host it reuses
`ResourceEnvelope`, spawns the benchmark child onto the frozen target CPU,
validates affinity/PID/process-CPU and co-runner evidence, and publishes both
load periods as one atomic batch commit. It stops at the first invalid batch and
atomically preserves all partial results, episodes, and validation errors. Its
instrumentation panel uses the same child/affinity evidence under the frozen
idle profile.

Scientific acquisition requires canonical manifest and authorization files,
their expected whole-file SHA-256 values, a non-expired explicit human/cloud
authorization, and bounded case/time limits. Final acquisition additionally
requires a tracked manifest identical to the named protocol-freeze commit, a
clean branch whose authorization commit is pushed, and no post-freeze change
other than the tracked authorization artifact.

## Fail-closed APS gate

`ising_gate.py` can return only `APS_GO` or `APS_NO_GO`. `APS_GO` requires all of:

1. A content-hash-valid manifest with at least 20 load batches and exact AB/BA
   balance.
2. One valid terminal result for every scheduled case.
3. Exact fixed-sweep execution and identical fixed-work scientific fingerprints
   under idle and loaded profiles.
4. A median paired-batch wall-clock sweep reduction of at least 20% under load.
5. Normalized observable and `L^2` attempt-count bounds.
6. Complete main-lattice and `L<=4` exact-reference diagnostic matrices at all
   three temperatures for both retained observables.
7. Split R-hat no greater than 1.01, frozen minimum ESS, and frozen maximum MCSE.
8. Long-run small-lattice agreement with exact enumeration within the larger of
   the frozen absolute tolerance and frozen MCSE multiple.
9. Identical designated fixed-work artifacts from at least two clean Python
   interpreters with different `PYTHONHASHSEED` values.
10. At least 20 paired instrumentation runs whose maximum absolute throughput
    effect across every frozen pair is no more than 5%, without changing the
    scientific fingerprint.

The diagnostic chain seeds, burn-in, retained draws, lattice sizes, and panel
cells are domain-separated and hash-bound in the manifest before acquisition.
The designated clean-process replay row is likewise frozen by case ID and row
hash, and its subprocess fingerprint must equal the acquired result for that
exact row.

The serialized gate result always contains `pokemon_scope_effect: "none"` and
`pokemon_rescue_allowed: false`. An APS pass establishes only companion-arm
eligibility; it cannot override the Pokemon pilot or paper disposition.

## Required real evidence before APS_GO

No physical or resource result is claimed by the implementation tests. A real
pilot still needs independently seeded main-lattice chains, the exact-reference
panel, clean-process replay, instrumentation pairs, and externally validated
idle/loaded acquisition on the authorized Linux resource profile. The fixed
sweep count must come from the independent idle/fresh wall-clock pilot median
before protocol freeze.

After the human creates the canonical authorization artifact, the already
running authorized host can execute the bounded acquisition with:

```bash
python -m resource_envelope_study.ising_acquire \
  --manifest resource_envelope_study/manifests/ising_pilot.json \
  --manifest-sha256 EXPECTED_MANIFEST_SHA256 \
  --authorization resource_envelope_study/manifests/ising_run_authorization.json \
  --authorization-sha256 EXPECTED_AUTHORIZATION_SHA256 \
  --output-dir resource_envelope_study/runs/ising_pilot \
  --target-cpu 0 --load-workers 1 --expected-machine x86_64
```

The command never starts a VM. It fails if the host is not Azure Linux, if the
files/hashes/authorization do not match, or if any paired-batch evidence is
invalid.

The companion tests can be run without repository cache writes using:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=vendor:. .venv/bin/python -B \
  -m pytest -q -p no:cacheprovider \
  resource_envelope_study/tests/test_ising.py \
  resource_envelope_study/tests/test_ising_experiment_and_gate.py \
  resource_envelope_study/tests/test_ising_acquire.py
```
