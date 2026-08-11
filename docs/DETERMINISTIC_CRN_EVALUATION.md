# Deterministic local engine and CRN evaluation

This is an evaluation-only engine build. It does not replace or package the production engine.

## Minimal engine seam

`freshstart/engine/ptcgProgram/Api.h` now factors battle creation through
`ApiBattleStartConfigured(cards, seed, deviceRand)`. The existing `BattleStart` path retains its
original random-device behavior. `Export.cpp` adds one local-only C export:

```text
BattleStartSeeded(int* cards, uint32_t seed)
```

That path sets `deviceRand=false` and initializes `Game::rng` directly from the supplied seed,
including a literal seed of zero. The existing conditional gameplay randomness in `CardMove.h`,
`EffectInstant.h`, and `SelectProc.h` therefore uses `Game::rng`; the other random-selection and
shuffle paths already use `Game::rng` directly.

The DLL was built from the fresh-start project into the isolated
`artifacts/deterministic_engine/bin/` directory. The project pins an obsolete SDK, so the build
overrode only the SDK and output/intermediate directories:

```powershell
$buildRoot = Join-Path (Resolve-Path '.').Path 'artifacts\deterministic_engine'
$msbuild = 'C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe'
& $msbuild freshstart\engine\ptcgProgram\game.vcxproj /m /t:Build `
  /p:Configuration=Release /p:Platform=x64 /p:WindowsTargetPlatformVersion=10.0.26100.0 `
  "/p:OutDir=$buildRoot\bin\" "/p:IntDir=$buildRoot\obj\"
```

Build provenance:

- Local seeded DLL SHA-256: `11662d6d96febb8aca8f500bdfde520ae0f1686ab3959eef90aa16c958e68188`
- Production `vendor/cg/cg.dll` SHA-256 before and after evaluation:
  `eae88634e26dc31d94150a4d8202fc9d32596b8c688ef67e14cb4088cd4d5771`
- Temporal schema-3 package tree:
  `5d203ad31c339a00a0389edcf9a7e51c2119f1ea9443b524ea201f70efd0afc2`
- Authentic A2 package tree:
  `854d8d016f545635711cb0722820b2997e19c4a160797c70e6415bcccf0bd1ae`

The local source build and production DLL return byte-identical `AllCard` and `AllAttack`
metadata. The production DLL was not edited, and no battle start/state/select call was directed to
it. Importing the vendor `cg.api` dataclasses does load that DLL and initialize its metadata tables;
all evaluated battle pointers and transitions still come exclusively from the isolated DLL.

## Determinism proof

`training/evaluate_deterministic_crn.py prove` ran 16 distinct games covering both actual orders
and both physical seats. Each task was run twice with one spawned worker and once with eight
spawned workers. All 16 public-state/action/outcome JSONL traces were byte-identical across all
three runs, with zero mismatches.

The proof deliberately excludes `search_begin_input`. That field is an opaque raw-struct search
snapshot and is not byte-stable across fresh process starts even when gameplay JSON, actions, and
outcomes are identical. Both evaluated agents explicitly disable search. A future evaluation of a
search-using agent needs a separate semantic snapshot test and cannot inherit this proof.

Proof artifact: `artifacts/deterministic_engine/determinism_proof.json`.

## Paired temporal schema-3 result

For every pair, the candidate arm replaced the hero with temporal schema-3 while the control arm
used A2 as hero; authentic A2 remained the fixed opponent. The two arms used the same native seed,
actual order, physical seat, and identical deck. Physical seats alternate within each order. This
is a paired policy-arm comparison, not an assumption that trajectories remain identical after the
policies choose different actions.

There were 500 independent seed pairs per actual order (2,000 total games):

| Actual order | Candidate | Control | Paired delta | Two-sided 95% CI |
|---|---:|---:|---:|---:|
| First | 265/500 (53.0%) | 248/500 (49.6%) | +3.4 pp | [-1.3, +8.1] pp |
| Second | 257/500 (51.4%) | 250/500 (50.0%) | +1.4 pp | [-3.6, +6.4] pp |
| Combined | 522/1000 (52.2%) | 498/1000 (49.8%) | +2.4 pp | [-1.0, +5.8] pp |

All candidate, control, and opponent policy-error counts were zero. The interval is the normal
large-sample interval for within-seed win-indicator differences in `{-1, 0, 1}`. The common random
numbers reduce variance but do not make diverged policy trajectories identical.

The result is compatible with a modest temporal-policy improvement, but none of the per-order or
combined intervals excludes zero. It does not support treating the older unpaired 59%/52% read as
evidence of a large policy jump.

Result artifact:
`artifacts/deterministic_engine/paired_temporal_schema3_vs_a2_500_per_order.json`.

## Scope and caveats

- Metadata parity and API smoke tests do not prove every transition in this fresh-start source is
  semantically identical to the shipped production binary. The result is a controlled local-engine
  benchmark, not a byte-identical reconstruction of Kaggle's runtime.
- Determinism is established for this exact Windows DLL/toolchain. `std::shuffle` ordering is a
  standard-library implementation detail, so seed outcomes should not be assumed portable to a
  differently compiled engine.
- The legacy `BattleStart` and `AgentStart` exports retain random-device behavior. Only
  `BattleStartSeeded` is certified, and the evaluated policies disable search.
- Common seeds couple the random streams only until policy-dependent control flow consumes them
  differently. Pairing reduces sampling variance; it does not create identical counterfactual
  worlds after trajectories diverge.
- Confidence intervals treat the distinct deterministic seeds as representative independent game
  draws. They quantify seed-schedule sampling uncertainty, not source/runtime uncertainty.
- Nothing under `vendor/cg/`, a submission package, or the production archive was written, and no
  artifact was uploaded.

## Focused verification

`tests/test_deterministic_crn.py` covers literal/repeatable seeds (including zero), different-seed
state changes, source/production card-metadata parity, paired arithmetic, and schedule mismatch
rejection.
