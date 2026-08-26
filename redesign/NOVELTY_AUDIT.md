# Novelty Audit

**Date:** 2026-08-26
**Auditor:** redesign pass (AI-assisted; see AI_USE_LOG)
**Method:** fresh web searches across CRN/paired-seed evaluation, deterministic replay of agent systems, metamorphic/statistical-oracle testing, A/A diagnostics, event-keyed randomness, adversarial validation pipelines, and stochastic-simulation V&V. Searches performed 2026-08-26; key sources archived in `redesign/references/` at protocol freeze.

## Purpose

Determine whether prior work already supplies **substantially all** of seven required elements. If yes → stop full-paper path (`NARROW_SOFTWARE_PAPER_ONLY`). The seven elements:

| # | Element | Supplied by prior work? |
|---|---------|------------------------|
| 1 | Claim-specific branching by inferential objective | **No** |
| 2 | Prospective comparison against simpler validation strategies | **No** |
| 3 | Known-ground-truth coupling failures | **Partial** |
| 4 | False-suppression measurement | **Emerging/partial** |
| 5 | Calibration or coverage analysis | **Yes (in other contexts)** |
| 6 | Open cross-domain validation | **No** |
| 7 | Cost/benefit evaluation | **Partial** |

**Gate verdict: NOT FATAL.** No single work, and no identified combination, supplies substantially all seven. Elements 1, 2, and 6 are absent from every examined source; element 4 exists only as an unmeasured side observation in one adjacent system. The redesigned study therefore has a defensible novelty core **provided it is framed as an empirical evaluation of validation strategies, not as new statistical theory or new tooling**.

## Closest prior work (what each does and does not do)

### N1. Paired-seed evaluation as CRN — Sharma, arXiv:2512.24145 (2025)
Formalizes paired seed evaluation as a common-random-numbers estimator for learning-based multi-agent economic simulation; proves strict variance reduction under positive seed-level correlation; demonstrates power gains.
- **Covers:** Branch B/D statistical theory; when pairing helps vs. hurts; variance-reduction measurement.
- **Does not cover:** no failure injection, no validity branching by claim type, no false-suppression concept, no replay/event-alignment dimensions, single domain.

### N2. Event-keyed hashing for causally valid CRN — arXiv:2603.11084 (2026)
Shows stateful PRNG draw-index misalignment breaks SCM-valid counterfactuals; proposes counter-based PRNGs keyed by stable semantic event identifiers (Philox/Threefry + event IDs).
- **Covers:** Branch E construction theory; diagnosis of the S2-style draw-shift problem; marginal-preservation argument.
- **Does not cover:** no benchmark of detection methods, no baselines comparison, no false-suppression/cost measurement, black-box settings out of scope (requires white-box RNG replacement).

### N3. Adversarial validation of causal research pipelines (ARA) — arXiv:2607.21173 (2026)
LLM-generated analysis code validated against synthetic SCMs with planted assumption violations; explicitly observes a shift toward "conservative" outputs (validity-driven withholding of intervals).
- **Covers:** known-ground-truth planted violations (element 3 analog); qualitative false-withholding observation (emerging element 4); coverage-type thinking.
- **Does not cover:** nothing about seeds/schedules/replay/CRN/event alignment; no claim taxonomy; no per-strategy detection/false-suppression rates; domain is LLM code generation, not stochastic-system evaluation.

### N4. Rollout cards — arXiv:2605.12131 (2026)
Publication bundles preserving rollout records with declared views/reporting rules/drops manifests; audits 50 repos; shows reporting rules can shift scores by up to 20.9 points.
- **Covers:** trace assurance, reporting-rule transparency (Branch A evidence culture), drops manifests (S7 territory).
- **Does not cover:** no statistical-validity gating, no pairing semantics, no injected-failure benchmark, no cost/benefit evaluation of validation depth.

### N5. Deterministic replay systems — agrepl arXiv:2607.16200; TraceCore; verifiable RL benchmarks (Müller-Brockhausen et al., IEEE CoG 2022); UVS spec
Record/replay infrastructures proving determinism invariants for agent runs; replay traces for reviewer verification.
- **Covers:** Branch C mechanics; trace projections; replay contracts.
- **Does not cover:** these are capabilities, not evaluated claims; none measure what replay evidence adds over simpler checks, nor its false-suppression cost.

### N6. Metamorphic & statistical-oracle testing of stochastic simulations — Patrick et al., ICST 2017; Guderlei & Mayer 2007; Raunak/Olsen; MIA (Facebook, ICSE-SEIP 2021)
Statistical oracles detect injected faults in stochastic simulations; MT validates ABM/DES/hybrid models.
- **Covers:** fault-injection testing methodology; error-detection sensitivity claims ("detect errors ≥3× smaller than tolerance thresholds").
- **Does not cover:** seed-matched pairing semantics; no suppression metric; no claim-class framework; domains are simulation V&V not agent comparison.

### N7. A/A testing practice — experimentation-platform literature (Kohavi lineage; 2026 practitioner references)
A/A null tests calibrate false-positive behavior of experiment platforms; p-value uniformity checks; SRM checks.
- **Covers:** element 5 within platform QA; noise-floor estimation.
- **Does not cover:** pairing validity questions; schedule integrity; coupling evidence; treated as practice folklore rather than a studied strategy against alternatives.

### N8. Classic foundations — PEGASUS (Ng & Jordan 2000); Strens JMLR 2003; CRN-MCTS (NeurIPS); variance-reduction surveys; "How Many Random Seeds?" (Agarwal et al. 1806.08295); simulation V&V (Sargent)
Established CRN theory, paired policy search, seed-count guidance.
- **Covers:** theory substrate we build on; we claim zero novelty here.
- **Does not cover:** any evaluation-of-validation-framework question.

### N9. Analysis validation advocacy — Lotterhos et al., PLOS Biology 2019
Argues for known-truth simulation validation of analysis methods with reproducible comparisons.
- **Covers:** method-level endorsement of our *approach shape*.
- **Does not cover:** any specific framework for seed-matched claims; supports feasibility, weakens "nobody ever does this" framing — must cite honestly.

## Where the redesigned contribution sits

The novel object is **not** any single technique. It is:

1. **A claim-specific decision framework** (branches A–E) that attaches evidence requirements to inferential objectives instead of a cumulative ladder — absent from all examined sources.
2. **A prospective, labeled benchmark** (S0–S10) spanning six claim dimensions with ground truth by construction — no comparable benchmark exists for seed-matched evaluation.
3. **False-suppression rate as a first-class metric** for validation protocols — emerging only qualitatively in N3; never measured for pairing/replay protocols.
4. **Head-to-head prospective comparison** of the framework against eight simpler strategies (B0–B7) on identical scenarios with costs — absent everywhere.
5. **Cross-domain execution** on fully open systems (game + Monte Carlo physics) — absent everywhere.

## Honest novelty threats

- If a reviewer reads N1+N2+N4 together, they may argue the pieces exist. Our defense: none of them evaluates whether such procedures improve conclusions relative to simpler ones, and none defines which claims require which evidence. We must cite all three prominently and frame the paper as *evaluation science*, not technique invention.
- The Ising/Monte Carlo arm must produce genuinely transferable results (same failure classes, same method ranking logic), otherwise the cross-domain claim collapses to two disconnected case studies.
- N3's existence means "false suppression" cannot be presented as an unheard-of idea — only as an unmeasured one outside LLM-code contexts.

## Gate decision

Proceed to **full-paper path** with the framing above. Re-run this audit at manuscript stage against any 2026 publications citing N1–N3.
