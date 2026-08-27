# Phase 0 — Forensic Repository Audit (prospective repair campaign)

**Date:** 2026-08-27
**Auditor:** DeepSeek V4 (AI-assisted; human direction per campaign specification; see AI_USE_LOG in final release)
**Starting point (verified):** branch `paper/claim-specific-prospective-redesign-20260826`, HEAD `9103df7b5e4f673a1358c30644b451344dc9ec9f` ("Complete prospective validation closeout package", pushed to origin). New working branch: `paper/claim-specific-prospective-repair-20260827`, created from exactly that SHA.
**Historical protocol freeze:** `62ad87893da926d0a67e9dc8ea9b99f81261b7ed` ("PROTOCOL FREEZE: …").
**Stopped line, not used:** `paper/claim-specific-validation-v2-20260826` @ `af1504c149d462c152eec18472661a844b58988a`. No code, data, or results from that branch are imported anywhere under `prospective_repair/`.
**Preservation invariant:** the entire `redesign/` tree is treated as immutable historical development evidence. This audit *reads* it; nothing under `redesign/` is modified by this campaign. A dedicated test (`tests/test_redesign_untouched.py`) enforces this going forward.
**Untracked material observed:** `redesign_v2/` and `resource_envelope_study/` directories exist in the worktree but are NOT tracked at the starting HEAD (`git ls-files | grep -cE '^(redesign_v2|resource_envelope_study)/'` = 0). They belong to other work; they will not be added, read as evidence, or depended upon.

---

## 1. Verification of the starting state

| Check | Command/result |
|---|---|
| Remote | `origin = https://github.com/bagel786/PokemonTCG2.0.git` (private) |
| Fetch/prune | executed; no surprises reported |
| Worktree status before checkout | clean (`git status --short` empty) |
| Required branch tip | `origin/paper/claim-specific-prospective-redesign-20260826 = 9103df7b5e4f673a1358c30644b451344dc9ec9f` (verified equal) |
| Required HEAD message | "Complete prospective validation closeout package" — verified |
| New branch creation | `git checkout -b paper/claim-specific-prospective-repair-20260827` from that SHA — verified `git rev-parse HEAD = 9103df7…` |

Expected local worktree `/Users/safiullahbaig/Projects/PokemonTCG2.0-overnight` does **not exist** on this machine; the live worktree `/Users/safiullahbaig/Projects/pokemonTCG2.0` satisfies every content precondition (same repository, same branches, exact required SHA reachable), so the campaign proceeds here. No user changes were present at start; none were stashed/d reset/discarded.

---

## 2. Verified defect inventory (with exact file/line anchors)

Every defect below was re-verified directly against source on the starting commit. Line numbers refer to the files at `9103df7…`.

### D-R1. Baselines default unsupported branches to ADMIT (structural bias)
- `redesign/benchmark/baselines.py:11–13` `_b_decisions(a="ADMIT", b="ADMIT", c="ADMIT", d="ADMIT", e="ADMIT")`.
- Consequences: B0 (L16–22) ADMITs Branches C/D/E without any replay/coupling/event evidence; B1 (L25–31) and B2/B3 emit `DOWNGRADE` for C regardless of mechanism detail or full ADMIT for D/E with no evidence view; no baseline ever abstains. Detection denominators are thus polluted: "detecting" an invalid cell by default-admitting everything cannot count as detection, and false-suppression of valid cells is compared against methods that never suppress anything outside their narrow scope.
- B1 receives `aa_outcome_variance=None` via the lambda at L99, so its A/A check (L27 `ok = aa_outcome_variance is None or …`) always passes **without consuming any A/A evidence**.
- B4 contains dead unconditional logic: L58–59 `if bundle["independent_seeds_declared"] or True: pass`.
- B6 ADMITs Branch B unconditionally for any non-independent-seeds row (L91) — outside its declared scope (event-keyed coupling).
- Verdict: **no comparative headline from the old campaign survives** (matches claim-ledger status caveats). Old B-vs-B7 contrasts must not be presented as valid evidence about competent alternatives.

### D-R2. Classifier contradicts the non-cumulative framework for Branch B
- `redesign/benchmark/classifier.py:151–173`. Any bundle whose pairing is justified only by design declarations (`justified`) lands on `DOWNGRADE` unless coupling sync evidence exists and passes (L164–173). Stateful-sync + context instability downgrades B (L167–169) even when the statistical paired estimator itself is unaffected.
- Old-campaign consequence (retained): Branch-B false suppression for B7 = 37.5% (120/320) — a classifier defect measured as if it were a framework property. The measured number stands as a fact about the old implementation; it must never again be attributed to the conceptual framework.
- Additional predicate mismatch: `has_hierarchical_model = "hierarchical_model" in model_family` (L108) vs stored value `"hierarchical"` (`benchmark/runner.py:299`) → the hierarchical predicate can never fire from real runner output.

### D-R3. Artifact identity conflates arm identity with system identity
- `classifier.py:92–96`: identity requires equal system/adapter_version/adapter_hash between arms. It records neither each arm's agent/policy/configuration nor allowed differences; two genuinely different policies (the whole point of arms A vs B) would be indistinguishable from a mislabeled same-agent pair at the evidence level (policy travels on the artifact object, `adapters.py:184`, but is absent from the bundle).

### D-R4. Hold'em S3 collapses the intended policy contrast
- `benchmark/adapters.py:198–202` `_eventkeyed_action(ek, st, key)` ignores `policy`; dispatch at L160–163 routes BOTH arms through it when `event_keyed=True`. The requested random vs conservative contrast never exists, so S3's exact-zero paired variance (`analysis/complete_analysis.py:variance_outputs`; zero with corr=1.0) is a degenerate implementation artifact, not variance-reduction evidence.
- Also dead code: `_holdem_budget_action` defined at `benchmark/runner.py:36–46` is never called.

### D-R5. Ising fault mechanics not implemented as labeled
- `adapters.py:251–283` `IsingAdapter.run_arm` accepts `clock_budget_ms` but never uses it; there is no S4 clock injection, no S5 worker-state contamination, no S6 queue-order draw tax on the Ising path. `runner.py:IsingSystem.run_pair` (L204–225) ignores ctx/mechanics entirely for those scenarios while the frozen GT labels say replay INVALID for S4/S5/S6/S8. Labels describe intent, not implementation — exactly the forbidden direction.
- Event-keyed hook order: `sampler = MetropolisSampler(model, seed=None)` is constructed BEFORE `model._rng = _KeyedModelRNG(...)` (L266–267); whether the sampler consumes the replaced RNG depends on toolkit internals and was never tested. Same ordering issue for the logging wrapper path (L269–274).
- Contexts for cross-context replay claims are two calls in ONE interpreter (`runner.py:220–224`), so the "cross-context" evidence does not involve separate processes/environments even where the claim implies them.

### D-R6. Placeholder timing retained in raw data
- `runner.py:174` writes `runtime_s=0.0` for every budgeted holdem run (S4/S8); 80 outcome-pair rows carry 0.0 and propagate into published `costs.csv` medians/p95. The frozen M9/M10 cost claims are therefore partially void (already flagged `NOT_ESTIMABLE_FROM_RAW_SCHEMA` in `estimability.json`).
- Per-method runtime and per-method evidence-bundle bytes do not exist anywhere in the raw schema (decision rows carry no timing field at all).

### D-R7. Invalid inferential procedure for method contrasts
- `analysis/complete_analysis.py:224–231, 258–290`: two-proportion z-tests + Holm over pooled proportions where **every method scores the identical cell bank** (matched/clustered data treated as independent binomials). Self-flagged limitation string exists (test_note) but the procedure remained in primary tables. EQUATION_AUDIT E3 records "FORMULA PASS; SAMPLING ASSUMPTION CAVEAT" — insufficient for paired clustered decisions. Exact McNemar / cluster-aware paired permutation was required instead.

### D-R8. Pseudoreplication risk embedded in design and analysis
- Frozen analysis unit = (system × scenario × seed × method × branch) cell, with scenarios repeated across seeds; M1/M2 pool across seeds treating repeated constructed scenarios as independent failure-mode draws. `METRICS_PREDECLARED.md` (old) acknowledges limits but pooling persisted; Kendall tau-b tradeoff score pools across ALL branches (complete_analysis.py L481–493).

### D-R9. Missing banks make M4–M6 impossible (documented post-freeze)
- Runner never retained: holdem mirror/equal-temperature A/A null banks, fixed-effect alternative bank, repeated S8 outcomes (S8 asked repeats_per_seed=3; runner computed `repeats=2` extra runs of arm A only — `runner.py:312–313` — and Ising S8 had no jitter or repeats at all). N=80 subsampling without replacement from ≤40 retained outcomes is arithmetically impossible; the frozen power grid nevertheless included N=80.

### D-R10. Secondary/test-artifact defects
- Claimed five test files (`tests/test_result_exclusion.py`, `test_monotone.py`, `test_fail_closed.py`, `test_projection_scope.py`, `test_determinism.py` per `protocol/FORMAL_CONTENT_DECISION.md`) DO NOT EXIST; only `redesign/tests/test_release_invariants.py` (97 lines, 5 tests) ships, and monotonicity/projection-scope/process-determinism properties are untested.
- `FINAL_HANDOFF.md:10` cites `BENCHMARK_REPORT.md`, which does not exist anywhere in the tree (broken handoff reference).
- Dead/degraded analysis code: `analyze.py` typeI_power dead residual block L144–160; legacy hand-rolled tau-a (no tie correction) coexists with production tau-b.

### D-R11. False visibility claim in manuscript wording
- `redesign/manuscript/manuscript.md` lines ~5 and ~45: "The protocol was frozen in public git history…" — false in current conditions: origin is a **private** GitHub repository. Correct characterization: a timestamped remote Git freeze whose history is auditable by anyone granted access; it is NOT public preregistration and confers no public registration benefits. Manuscript-stage documents may only use public language after an authorized public deposit exists.

### D-R12. Readiness-gate conflation
- Old machine decision treated recommendation-threshold failure and missing-bank estimability uniformly inside one `NOT_READY_DO_NOT_SUBMIT`. These must be separated: benchmark-integrity gate vs method-recommendation gate vs human submission gate.

### D-R13. Provenance gaps in raw retention
- Decision rows retain only method/branch/decision/gt/score_class; the underlying evidence predicates (bundle fields) are NOT retained per row, so independent auditors cannot reconstruct WHY a method decided what it did without re-running classification. Repeats/contexts/traces/event coverage views also transient. Repaired schema must persist predicate-level provenance per decision row.

---

## 3. Hostile novelty and methods recheck (primary sources, searched 2026-08-27)

Method: fresh targeted web searches against primary sources (arXiv records opened where possible; GitHub benchmark repos inspected). Search absence is NOT proof of novelty; conclusions below are bounded to identified sources.

New closest-prior-art identified this pass (must be cited; none supplies substantially all fatal-gate elements):

1. **Sabot** (`github.com/Jott2121/sabot`, 2026-07): pre-registered spec + harness planting controlled faults in LangGraph/CrewAI/AutoGen pipelines and scoring whether pipelines' OWN checks detect them; publishes hard-detection rates, clean-baseline false-anchor base rates, strict floors, cluster-bootstrap uncertainty, publish-regardless commitment. Structural analog in spirit (planted faults, pre-registration, negative-result prominence). Does NOT cover: seed-matched stochastic-evaluation semantics, claim-class branching (paired-inference validity vs replay vs CRN benefit vs event alignment), false SUPPRESSION of valid analyses as a first-class metric over validation strategies, game+physics cross-domain execution, or comparison against simpler validation strategies such as B1–B5-style checks.
2. **ASMR-Bench** (arXiv:2604.16286): sabotaged ML research codebases; auditor AUROC; humans+LLMs. Research-code sabotage auditing, not stochastic-evaluation claim validation; no suppression/cost tradeoff surface.
3. **MLE-Sabotage / CTRL-ALT-DECEIT** (arXiv:2511.09904) and Anthropic sabotage evals (2410.21514): agent-sabotage detection monitors; different unit of analysis entirely.
4. **Proteomics entrapment-FDR line** (Nat. Methods 2025 entrapment assessment; Nat. Comm. 2022 DIA benchmarking; bioRxiv 2026 ground-truth FDR/power): evaluates error control of statistical pipelines against known-truth decoy banks. Spiritually adjacent (validation-of-validation with planted truth and false-rate accounting) but domain-specific to peptide identification; no seed-matched pairing/replay/CRN/event-alignment claims.
5. Replays/noise line (e.g., arXiv:2606.15621 re-feed vs resume replay noise; 2608.08239 replay gap; 2608.19760 replay credit audit): measure replay/execution nondeterminism consequences — relevant motivation for Branch C/D semantics; none benchmarks claim-validation strategies or false suppression.
6. Established CRN/RNG substrate reconfirmed (Glasserman & Yao 1992; L'Ecuyer streams/CBRNG WSC papers; Buffalo et al. arXiv:2603.11084 event-keyed SCM construction; Sharma arXiv:2512.24145 v3 paired-seed theory). Zero novelty claimed on these.

**Gate verdict:** NO-GO condition NOT triggered. No identified open benchmark evaluates substantially the same object: claim-specific branching for seed-matched evaluations × planted known-truth failures × false-suppression measurement × competent-baseline comparison × cost accounting × two open systems. Contribution remains defensible ONLY as evaluation science with all six prior-art families above cited prominently. Human full-text verification of newly cited items remains pending and is tracked in the risk register.

---

## 4. Feasibility verdict for August 30

Rough compute projection for the repaired campaign (details frozen in Phase 1): pilot ≈ minutes; final holdout dominated by Ising (~0.6–1.5 s/arm-run): ≈ 80 seeds × ~10 constructions × 2 systems incl. repeat/cost banks ⇒ order 1–2 CPU-hours — within the frozen budget envelope and executable well before Aug 30. The binding constraint is engineering correctness (new wrappers, banks, tests, freeze discipline), not wall-clock. Decision: **proceed**, with explicit fail-closed fallback — if any scientific gate (freeze-before-outcomes, mechanics-match-labels audits) cannot be met honestly, deliver the best reproducible repair checkpoint plus a no-go handoff rather than a simulated completion.

## 5. Development-vs-confirmation ruling

All old S0–S10 outcomes remain development evidence: usable to write regression tests and motivate repairs; NEVER presentable as confirmation of the repaired framework. The repaired campaign acquires new confirmatory data from new constructions/banks after a verified freeze push.

## 6. Phase-0 commitments carried into Phase 1+

- Traceability matrix: `REVIEWER_TO_REPAIR_TRACEABILITY.csv` (every reviewer criticism ↔ artifact anchor ↔ repair ↔ falsifying test ↔ change class ↔ old-outcome influence ↔ resolution evidence).
- Risk register: `SCIENTIFIC_RISK_REGISTER.md`.
- Result-exclusion, mechanics-test, documentation-link, redesign-untouched, and mutation tests are REQUIRED test layers before freeze (enforced via prefreeze gate script).
- Private-remote freeze wording rule: "timestamped freeze pushed to the private origin remote; not public preregistration."
