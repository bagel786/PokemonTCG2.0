# Claim ledger — human signoff worksheet

**Instruction to the human author:** the machine claim ledger
(`claim_ledger.csv`) is regenerated on every pipeline run and currently pairs
33 curated claims with an automatically generated set of remaining prose rows
(the live count is printed by `scripts/build_claim_ledger.py` and recorded in
`source_data/claim_scope_audit.json`, so it stays correct as the manuscript
evolves). Signing every row individually is impractical and would produce
rubber-stamp signatures rather than verification. This worksheet replaces
per-row signing with a two-part workflow. It does **not** delete or weaken the
ledger; the ledger continues to be regenerated and machine-audited on every
pipeline run, and this amendment is recorded here transparently.

Amendment record: prior gate required one human signature per row. Closeout
gate requires (A) sentence-by-sentence signoff of all 33 curated claims below
and (B) one explicit attestation covering every automatic row (current count
per `claim_ledger.csv`) plus their coverage script. Status of this amendment:
**PENDING HUMAN SIGNATURE**.

---

## Part A — Curated claims (33)

For each claim: initial the box only if you personally verify the sentence,
its number(s), its source, its allowed reading, and its forbidden readings.

| # | Type | Sentence (abbreviated) | Exact numbers to verify | Allowed | Forbidden | ✓/initials |
|---|------|------------------------|-------------------------|---------|-----------|------------|
| 1 | prior_work | CRN theory makes gain conditional on construction, structure, event timing | — | conditional CRN theory citation | claiming seed reuse suffices | |
| 2 | prior_work | Streams/substreams organize synchronized simulation | — | stream-design citation | claiming novelty of streams | |
| 3 | contribution | Integrates components into executable pairing-assumption protocol | — | integration claim | any component-priority claim | |
| 4 | contribution | Prior work supplies ingredients; this work maps evidence→claim | — | boundary statement | "first/novel" language | |
| 5 | publication_status | Sharma & Buffalo are arXiv preprints, not verified peer-reviewed | — | accurate status | citing them as peer reviewed | |
| 6 | prior_work | A/A diagnostics established in online experimentation | — | diagnostic lineage claim | importing sampled-user inference | |
| 7 | prior_work | Rollout Cards preserves rollouts/views/rules/manifests | — | capability attribution | claiming it validates coupling | |
| 8 | prior_work | Trace assurance uses Message–Action Traces for contracts/replay/governance | — | capability attribution | same as above | |
| 9 | prior_work | AEVAL turns workflow changes into deterministic contract tests | — | capability attribution | same as above | |
| 10 | procedural | Implementation compares SHA-256 digest **and byte count** of recorded projection | digest+bytes definition | current verifier behavior | calling byte-count frozen endpoint | |
| 11 | limitation | Restricted engine lacks event identifiers ⇒ cannot establish alignment | — | scope limitation | any event-alignment claim for engine | |
| 12 | procedural | Generic taxonomy did not exist at protocol commit; not prospective validation | commit ordering | post-acquisition disclosure | prospective-freeze implication | |
| 13 | artifact | Suite writes JSON evidence, CSV, JSON Schema, SHA-256 manifest | file inventory | artifact description | prevalence claims | |
| 14 | quantitative | Draw-shift fixture aligns 1 of 5 shared events after extra draw | 1/5 | fixture fact | real-engine generalization | |
| 15 | quantitative | Event-keyed repair aligns all 5 logged events (declared ontology) | 5/5 | ontology-scoped fix | universal repair claim | |
| 16 | limitation | Historical files lack Stage-3 fields and trace projection | — | honest scope | retrospective full-pass claim | |
| 17 | quantitative | Source audit verified 13 artifact digests; scan applied to \SourceAssessedPackageTrees{} trees | 13; tree count | audit coverage | determinism proof | |
| 18 | limitation | \SourceUnassessedBinaries{} binaries hash-checked but not source-assessed | binary count | uninspected-boundary disclosure | source-level claims on binaries | |
| 19 | quantitative | Historical projection disagreed \HistoricalOutcomeMismatch{}/\HistoricalUnits{} (win/draw) and \HistoricalAvailableRecordMismatch{}/\HistoricalUnits{} (with decision count) | both counts + unit total | retrospective audit result | prospective blinding; causal timing proof | |
| 20 | comparative | Both mismatch sets confined to two timed-search opponents | opponent count | observed confinement | population inference | |
| 21 | admission_decision | Favorable estimate failed retrospective control gate → suppressed | suppression event | fail-closed demonstration | framing as bias-free proof | |
| 22 | quantitative | Preflight: \PreflightUnits{} units, \PreflightExecutions{} executions, \PreflightMismatches{} mismatches | 1000 / 3000 / 0 | pass scoped to artifacts+contexts+projection | universal repeatability | |
| 23 | quantitative | Boundary-seed audit: all values in range/distinct; no namespace overlap | audit outcome | seed-integrity fact | internal-consumption claim | |
| 24 | quantitative | Stress: \StressTraceMismatch{}/\StressClusters{} clusters disagreed (\StressTracePct\%) | 99/200/49.5% | exact-repeatability rejection on exercised seeds | unique-cause proof | |
| 25 | quantitative | Outcomes disagreed in \StressOutcomeMismatch{}, decisions in \StressDecisionMismatch{}, errors in \StressErrorMismatch{} | 47 / 93 / 0 | secondary counts | treating error-0 as pass | |
| 26 | procedural | Factorial rows were NOT trace repeated; no digests/event ids recorded | field inventory | design disclosure | trace-parity description of factorial gate | |
| 27 | admission_decision | Frozen rule authorized planned estimates/intervals/McNemar after gate pass | plan content | historical-plan disclosure | admitting McNemar as reported inference | |
| 28 | admission_decision | Gate commit precedes results; replacing outcomes leaves decision unchanged | Git ordering | functional invariance | human-blinding claim | |
| 29 | quantitative | Total fixed-battery contrast = \PrimaryEstimatePP{} pp | +0.55 pp | descriptive contrast | causal/inferential/equivalence wording | |
| 30 | quantitative | R/G/J contrasts and quantiles span zero | see Table IV | descriptive sensitivity | equality/superiority/no-effect proofs | |
| 31 | AI_transparency | No generative-image system used; figures are deterministic plots | — | tool-scope statement | completeness without human confirmation | |
| 32 | rights | Public archival availability NOT established (no license/DOI confirmed) | — | honest restriction | public-package claim | |
| 33 | rights | Engine/opponents/assets/traces unavailable under established rights | — | restricted list | reasonable-request promise | |

## Part B — Automatic coverage attestation (every remaining automatic row)

The remaining rows were added mechanically by `scripts/build_claim_ledger.py`
(deterministic prose-scope pass). Each binds an exact manuscript sentence to
hash-verified evidence-file identities with allowed/forbidden wording columns.

By signing here I attest that:

- [ ] I have reviewed the coverage script's classification rules and run it;
- [ ] every automatic row is bound to a machine-verified source category
      (evidence-file SHA-256 identity), and spot-checked at least ten rows;
- [ ] I accept author responsibility for all remaining manuscript prose,
      including sentences outside the ledger's keyword classes;
- [ ] I understand blocked statuses cannot be converted by prose alone.

Signature: ____________________ Date: `[YYYY-MM-DD]`

Initials/date after each Part A row: recorded in the table above.
