# Hostile novelty search log

Search date: 2026-08-27 America/Chicago (continued into 2026-08-28 UTC)

Purpose: attempt to disconfirm the proposed contribution before any new benchmark construction, freeze, or confirmatory acquisition.

## Evidence policy

- Search results and snippets were used only for discovery.
- A source entered the novelty matrix only after its publisher page, official report, full paper, proceedings PDF, or primary repository specification was opened.
- Metadata/title conflicts were resolved in favor of the current full text and recorded explicitly.
- Search absence is not evidence of priority.
- No source supports a `first`, `novel`, `unprecedented`, `proves`, or `state of the art` claim for this project.

## Search families and executed queries

### Exact flagged names

- `site:arxiv.org "ASMR-Bench" sabotage ML research codebases`
- `site:github.com/Jott2121/sabot OR site:github.com "Sabot" "pre-registered" LangGraph CrewAI AutoGen`
- `site:arxiv.org "MLE-Sabotage" OR "CTRL-ALT-DECEIT"`
- `site:nature.com entrapment FDR tandem MS Wen Kall Noble Keich 2025`

Findings:

- `Sabot` is a real public GitHub fault-injection scoreboard/specification. It compares pipeline checks on planted faults, retains clean controls, reports detection and recovery-without-detection, and uses frozen specifications. It is not peer reviewed.
- The flagged `ASMR-Bench` identifier resolves to arXiv:2604.16286. The current PDF title is **Auditing Sabotage Bench: A Benchmark for Detecting and Fixing Research Sabotage in ML Codebases**, not the older abstract-page title. It uses existing ML codebases, sabotaged variants, auditor evaluation, AUROC, and fix rates.
- `MLE-Sabotage` is not a separate publication title. It is the 20-task benchmark introduced inside **CTRL-ALT-DECEIT: Sabotage Evaluations for Automated AI R&D**, arXiv:2511.09904 / NeurIPS 2025 paper.
- The entrapment-FDR item is **Assessment of false discovery rate control in tandem mass spectrometry analysis using entrapment**, Nature Methods 22, 1454-1463 (2025), DOI 10.1038/s41592-025-02719-x.

### Paired inference, CRN, and event alignment

- `site:arxiv.org stochastic evaluation paired seeds deterministic replay common random numbers benchmark validation`
- `site:arxiv.org "Realizing Common Random Numbers" event-keyed hashing causally valid stochastic models`
- `site:pubsonline.informs.org "Some Guidelines and Guarantees for Common Random Numbers"`
- `site:informs-sim.org "common random numbers" synchronization simulation semantic events random streams`
- `site:dl.acm.org "event keyed" random number generation simulation`

Findings:

- Classical CRN theory and simulation practice already separate construction assumptions, synchronization, and variance benefit.
- The 2014 common-patient paper explicitly shows why a shared model-level seed loses synchronization after control-flow differences and prescribes separate event streams.
- The 2026 event-keyed paper explicitly formalizes stable event identity/exogenous-noise mapping for counterfactual simulations.
- arXiv:2512.24145's current PDF title is **When Does Pairing Seeds Reduce Variance? Evidence from a Multi-Agent Economic Simulation**, not the older abstract metadata title. Section 5 states that paired inference remains statistically valid regardless of the sign of correlation; efficiency benefit is separate.

### Simulation V&V, reproducibility, and claim-purpose matching

- `verification validation stochastic simulation model claim validity taxonomy evidence`
- `simulation validation intended use claim-specific evidence credibility framework context of use`
- `official standard repeatability replicability reproducibility computational results definitions ACM artifact review`
- `National Academies reproducibility replicability science definitions computational reproducibility statistical inference`
- `paired inference does not require deterministic replay statistical paired design random effects source`

Findings:

- Sargent's simulation V&V tutorial states that validity is purpose-specific and, when a model answers several questions, validity must be assessed for each question.
- ASME V&V 40/FDA materials require credibility evidence to be commensurate with the decision/context of use.
- The National Academies separates computational reproducibility from replicability and explicitly warns that exact reproducibility does not guarantee correctness.

### Validator/tool benchmarking, mutation, and scientific-pipeline faults

- `software benchmark fault injection scientific analysis pipeline validation claims mutation testing statistical software`
- `benchmark validating scientific claims software analysis pipeline faults reproducibility`
- `metamorphic testing stochastic simulation software oracle benchmark mutation operators`
- `site:dl.acm.org stochastic software testing statistical oracle metamorphic testing scientific software fault injection benchmark`
- `site:ieeexplore.ieee.org stochastic simulation software verification validation reproducibility random seeds pairing common random numbers`
- `site:proceedings.mlr.press reinforcement learning evaluation random seeds paired statistical tests reproducibility`
- `"Use as directed? A comparison of software tools intended to check rigor and transparency of published work"`

Findings:

- Eckmann et al. compare 11 automated rigor tools across nine criteria, treat differing operational definitions and input modalities explicitly, use criterion-specific gold standards, evaluate combinations, and identify runtime/cost/applicability as decision dimensions.
- Auditing Sabotage Bench, MLE-Sabotage, Sabot, entrapment-FDR, and differential scientific-software fault injection establish planted/known-false cases as a way to evaluate auditors, monitors, validation strategies, and transformed scientific software.
- The novelty threat is therefore not one source duplicating the proposed project verbatim. It is that every asserted contribution is an established component, while the proposed integration is a deterministic rule engine tested on a grammar written from the same rules.

## Search conclusion

The disconfirmation search found no defensible central contribution that exceeds packaging established distinctions and applying established validator-benchmark methodology to another domain. The one allowed narrow reframe—an externally sourced, independently adjudicated software-quality benchmark of claim authorization—would require a new gold-standard corpus and genuine independent/human truth construction. It is not present in the repository, and adding a rule-derived synthetic bank would reproduce the circularity rather than cure it.

No new confirmatory outcome was generated or viewed. The required stop status is `NOT_READY_NOVELTY_FAILURE`.
