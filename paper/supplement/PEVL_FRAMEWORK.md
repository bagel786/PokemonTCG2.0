# Paired Evaluation Validity Ladder (PEVL)

## Purpose and status

The Paired Evaluation Validity Ladder (PEVL) is a proposed evidence-and-claim framework for seed-matched evaluation of game-playing agents. Its purpose is to prevent a matched schedule from being mistaken for reproducible execution or for event-aligned stochastic coupling:

> same schedule ≠ reproducible executions ≠ event-aligned coupling.

PEVL is designed for restricted or black-box settings in which researchers may be able to hash a simulator and its agents, schedule seeds, execute identical-arm controls, and record public traces, but may be unable to replace the engine RNG or inspect every third-party opponent. The ladder is cumulative for Levels 1--7. Level 8 is the mandatory admission decision applied to the evidence actually achieved; it does not manufacture a missing lower-level guarantee.

The framework must not be presented as the discovery that identical seeds can be insufficient. Classical common-random-number (CRN) results already depend on structural and event-timing conditions [Glasserman and Yao (1992)](https://pubsonline.informs.org/doi/10.1287/mnsc.38.6.884). Multiple streams and substreams have long been used to support synchronization and independent replications [L'Ecuyer et al. (2002)](https://pubsonline.informs.org/doi/10.1287/opre.50.6.1073.358). Recent preprints separately show the potential precision benefit of seed pairing when seed-level outcomes are positively correlated [Sharma (2025, v3 revised 2026)](https://arxiv.org/abs/2512.24145) and the causal event-misalignment problem created by stateful PRNG draw shifts [Buffalo, Pearson, and Klein (2026)](https://arxiv.org/abs/2603.11084).

The defensible proposed novelty is **operational black-box, fail-closed validation**: PEVL assembles provenance, exact seed-namespace checks, schedule parity, identical-arm controls, execution-context trace tests, stochastic-source auditing, event-alignment evidence where available, and a prespecified rule that admits or suppresses each paired claim. It is a way to decide what the available evidence permits researchers to say, especially when the strongest white-box remedy cannot be implemented.

## The eight levels

“Pass” is always scoped to the tested artifacts, seeds, trajectories, fields, execution environments, and target population. Passing a lower level never implies a higher one.

| Level | Required evidence | Evidence admitted | Evidence not admitted | Fail-closed response |
|---|---|---|---|---|
| **1. Artifact identity** | Cryptographic hashes for engine, control, candidate, opponents, and policy packages; code commit; protocol ID; configuration, environment, decision budget, and worker settings. | The evaluated bytes and declared configuration are identifiable and can be compared with a future run. | Seed equivalence, deterministic behavior, schedule matching, or stochastic coupling. | Reject or quarantine records with missing identity, hash drift, or configuration drift; do not merge them into the planned analysis. |
| **2. Seed-namespace integrity** | Record both the scheduled seed and the exact value consumed by the engine after narrowing or conversion; record the conversion rule and RNG/stream identifier; assert no unintended collisions over the full schedule. | The same engine-level seed value was supplied where claimed, and distinct scheduled units remain distinct in the engine namespace. | Identical random draws, semantic event alignment, or execution repeatability. | Correct the schedule or adapter and rerun. Do not relabel a large host-language integer as the engine seed when the engine consumed a narrowed value. |
| **3. Schedule parity** | Pair-level equality of opponent, actual order, physical seat, engine seed, initial-state controls, environment, maximum decisions, search configuration, and all other prespecified conditions; complete expected cells and an auditable schedule fingerprint. | The study attempted a matched comparison under the declared schedule. | That the paired executions remained identical before treatment divergence, that either arm is repeatable, or that random events stayed aligned. | Reject incomplete or unequal pairs. Resolve schedule bugs prospectively; never silently drop unmatched rows after inspecting outcomes. |
| **4. Identical-arm record parity** | Byte-identical A/A or repeated-control executions on the matched schedule. Compare terminal outcome, errors, decision count, action sequence, public-state sequence, and a complete public-state/action trace digest. | Repeatability of exactly the fields compared, on the observed identical-arm trajectories and tested execution setting. A full trace match is stronger evidence than an outcome match. | Reproducibility on untested trajectories or arms, robustness to concurrency, or cross-arm event alignment after actions diverge. | Suppress the affected paired mechanistic contrast when required parity fails. Report the parity failure as a result; do not restore significance by deleting divergent opponents post hoc. |
| **5. Repeat and worker parity** | Prespecified repeated serial executions, fresh-process repeats, serial-versus-parallel tests, relevant worker counts, enqueue orders, and process-pool lifecycles. Test every treatment arm on a frozen trace subset, not the control alone. | Within-arm trace reproducibility across the tested execution contexts and seeds. | Determinism on other hardware, loads, worker settings, or newly reached states; event-level equivalence between different arms. | Either freeze a prospectively validated execution context and limit inference to it, or abandon the matched contrast and model execution-level variability with repeated or independent evaluation. |
| **6. Stochastic-source audit** | Enumerate and, where possible, instrument engine, Python, NumPy, native, opponent, and process-global RNGs; wall-clock termination; thread scheduling; process reuse; native pointers/state; hardware-dependent numerics; and external state. | A source-supported account of plausible divergence mechanisms, known controls, and residual risks. Controlled interventions can strengthen causal attribution. | Proof that an observed association identifies the sole source of divergence, or proof that hidden sources are harmless. | Downgrade mechanistic wording to “consistent with” or “associated with.” If an unrecorded source can alter the estimand, stop the affected analysis or redesign it. |
| **7. Cross-arm event alignment** | Stable modeled-event identifiers and evidence that every shared exogenous event receives the same random value across arms, using event-keyed counter-based randomness, synchronized event-specific streams, logged event/value pairs, or a demonstrably equivalent construction. Check alignment after treatment-induced branching. | An event-aligned CRN or counterfactual interpretation within the explicitly covered event set and model boundary. | Alignment inside inaccessible components or for unlogged event classes; universal causal validity outside the tested model. Identical-arm parity alone never establishes this level. | Retain, at most, bounded “seed-matched” language if Levels 1--6 and Level 8 otherwise support it. Do not call the design event-aligned or claim that exogenous stochastic events were held fixed. |
| **8. Statistical admission** | A frozen rule maps achieved levels and failures to the estimand, analysis unit, interval/test, target population, and exact permitted wording. It accounts for reused seeds, repeated executions, clustering, and run-level variation and forbids optional stopping or outcome-driven population changes. | Only the claim class prespecified for the validated evidence: provenance, schedule-matched description, seed-matched performance comparison, or event-aligned CRN/counterfactual comparison. | Any stronger interpretation than the weakest required gate supports. Statistical significance cannot repair a failed validity gate. | Automatically suppress or downgrade the contrast. A redesigned target population or independent/repeated evaluation must be frozen and executed as a new analysis, not used as a post hoc rescue. |

## Claim-admission rules

1. **Levels 1--3 only:** report provenance and the attempted matched schedule. Do not describe the comparison as validated pairing.
2. **Levels 1--6 plus a prespecified Level-8 rule:** a seed-matched paired performance contrast may be reported for the exact target seed and execution population, with implementation-conditional wording and uncertainty that respects execution-level clustering. This does not support an event-aligned counterfactual interpretation.
3. **Levels 1--7 plus a prespecified Level-8 rule:** stronger event-aligned CRN language may be used only for the modeled event classes actually validated.
4. **Failure at Levels 1--3:** the affected records are inadmissible for the matched analysis.
5. **Failure at Levels 4--5:** suppress the affected paired mechanistic contrast. The alternatives are a prospectively redesigned deterministic target population or repeated/independent evaluation that treats execution variation as part of the data-generating process.
6. **An unresolved Level-6 mechanism:** report the observed divergence and bounded association, not a unique causal explanation.
7. **Unavailable Level 7:** explicitly say that same-seed scheduling and identical-arm reproducibility do not prove semantic event alignment across different policies.
8. **No frozen Level-8 mapping:** label the analysis exploratory or descriptive even if its numerical result is favorable.

## Strength of parity evidence

Parity is not a single binary label. The report must name the strongest compared record:

1. terminal outcome;
2. error record;
3. decision count;
4. action sequence;
5. public-state sequence;
6. complete public-state/action trace digest.

Agreement at one step does not imply agreement at a later step. Two executions may take different actions or traverse different public states and still reach the same winner. Conversely, a digest mismatch must be resolvable to a human-auditable first divergence on a trace subset so that hash or serialization bugs are not mistaken for simulator nondeterminism.

## Minimum evidence record

Each result row, or a cryptographically linked run manifest, should identify:

- protocol ID, protocol commit, run UUID, and schedule fingerprint;
- engine, policy/arm, control, and opponent hashes;
- scheduled seed, exact engine-consumed seed, conversion rule, and RNG/stream identifier when available;
- opponent, actual order, physical seat, relevant initial-state controls, and maximum decisions;
- environment and search configuration;
- worker count, process start method, enqueue position, process/worker identifier, and process-pool lifecycle;
- outcome, errors, decision count, elapsed wall time, and public trace digest;
- for Level 7, modeled-event identifiers and the corresponding random values or counter keys.

The manifest is part of the evidence, not merely documentation added after analysis.

## Literature and novelty map

| Established contribution | Boundary it places on PEVL |
|---|---|
| CRN can reduce comparison variance under structural conditions, with event timing central to some guarantees [Glasserman and Yao (1992)](https://pubsonline.informs.org/doi/10.1287/mnsc.38.6.884). | Do not claim discovery that reusing random numbers or seeds requires assumptions. |
| Streams and substreams can support synchronization and independent simulation replications [L'Ecuyer et al. (2002)](https://pubsonline.informs.org/doi/10.1287/opre.50.6.1073.358). | Do not claim invention of separated RNG streams; treat them as one possible white-box implementation. |
| Paired seeds can improve precision when seed-level correlation is favorable [Sharma (2025, current v3)](https://arxiv.org/abs/2512.24145). | The message is not “seeds are useless.” PEVL validates when paired-seed wording and analysis are admissible. |
| Stateful PRNG draw shifts can destroy semantic event alignment; event-keyed hashing with counter-based generators is a proposed remedy [Buffalo, Pearson, and Klein (2026)](https://arxiv.org/abs/2603.11084). | PEVL must distinguish identical-arm reproducibility from cross-arm event alignment and must not present control parity as proof of coupling. |
| Reproducible methods do not by themselves establish reproducible findings, and essential variation must be studied [Bouthillier et al. (2019)](https://proceedings.mlr.press/v97/bouthillier19a.html). | PEVL's serial/parallel and repeated-execution tests are an operational audit, not a new general theory of reproducibility. |
| RL comparisons require explicit statistical assumptions, variation analysis, prespecification, and control of experimenter bias [Patterson et al. (2024)](https://jmlr.org/papers/v25/23-0183.html). | PEVL complements rather than replaces standard empirical design and uncertainty analysis. |
| Time allocation changes Monte Carlo tree-search behavior and performance [Baier and Winands (2016)](https://doi.org/10.1109/TCIAIG.2015.2443123). | Wall-clock search is a scientifically relevant audit target, but this citation does not prove that timing caused a particular observed mismatch. |
| Pointer architectures explicitly select input elements [Vinyals et al. (2015)](https://proceedings.neurips.cc/paper_files/paper/2015/hash/29921001f2f04bd3baee84a12e98098f-Abstract.html), and learned action representations exploit structure in large finite action sets [Chandak et al. (2019)](https://proceedings.mlr.press/v97/chandak19a.html). | These works motivate explicit action identity in the case study; they do not establish PEVL or validate the representation intervention. |

Accordingly, the manuscript's narrow contribution statement should be:

> We propose an operational, fail-closed validity ladder for paired evaluation of black-box game-playing agents. The ladder separates artifact and schedule matching, within-arm execution reproducibility, and cross-arm event alignment; it prespecifies which paired claims are admitted or suppressed when each class of evidence passes or fails.

Avoid “the first,” “we discovered that seeds are insufficient,” and “control parity proves coupling.” A targeted primary-source audit supports the boundary above, but not an absolute priority claim.

## Citation keys

- `glasserman1992crn`
- `lecuyer2002streams`
- `sharma2025pairedseeds`
- `buffalo2026eventkeyed`
- `bouthillier2019reproducible`
- `patterson2024empirical`
- `baier2016timemanagement`
- `vinyals2015pointer`
- `chandak2019actionrepresentations`
