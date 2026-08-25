# APS Open Science desk-fit audit

Audit date: 2026-08-24  
Target: APS Open Science, Protocol Article  
Frozen title for this assessment: **A Protocol for Validating Pairing Assumptions in Seed-Matched Evaluations of Black-Box Game-Playing Agents**  
Decision: **NOT READY — DO NOT SUBMIT.** The methodological desk-fit gates pass at review-package scope, but rights/public-release authorization is an explicit hard failure.

Scores are independent 0--5 judgments; they are not averaged. A score is not permission to submit.

## Current official APS requirements

- APS Open Science publishes physics and adjacent-field work, including technical and methodological advances. Its current scope explicitly lists Artificial Intelligence, Complex Systems and Networks, Computational and Data-Intensive Science, Interdisciplinary Research, Scientific Machine Learning, and Statistical Physics and Thermodynamics: <https://journals.aps.org/apsos/scope>.
- The journal's acceptance criteria require appropriate methods and rigor; technically correct execution yielding valid, reliable, useful results; a meaningful addition to knowledge in physics or a related field; and enough transparency for verification: <https://journals.aps.org/apsos/about>.
- APS defines a Protocol Article as a step-by-step description of an experimental procedure, measurement technique, or computational method that has proved effective and enables reproducibility and adoption: <https://journals.aps.org/apsos/authors>.
- The same author guidance requires writing for a broad research readership, contextualizing related literature, and including titles for all APS Open Science references. It also encourages integration of new state-of-the-art work rather than a late “Note Added”: <https://journals.aps.org/apsos/authors>.
- Every published article requires a Data Availability Statement describing relevant data and software. Public FAIR sharing is strongly encouraged; public artifacts must be cited; if material cannot be public, the statement must explain why and APS expects private sharing on reasonable request: <https://journals.aps.org/authors/data-availability-statements>.
- APS's current AI policy requires substantive use to be recorded and disclosed in the paper. Research use belongs with Methods; other substantive assistance belongs in Acknowledgments; disclosures identify the tool and version, how it assisted, and how humans directed and verified it. AI is not an author. Authors must also check tool terms, privacy, data protection, intellectual property, and figure rights: <https://journals.aps.org/authors/appropriate-use-ai-tools>.
- APS style guidance requires accurate and complete bibliographic information and advises using published primary records in preference to e-prints when a version of record exists: <https://journals.aps.org/authors/style-basics>.

## Twelve desk scores

| Dimension | Score | Evidence and disposition |
|---|---:|---|
| 1. Scope | **3/5** | The work fits the journal's explicit AI, computational/data-intensive science, complex-systems, and methodological categories. The game case is not itself physics, and the manuscript must foreground experimental design for stochastic computation across adjacent sciences. A pre-submission scope inquiry is prudent. |
| 2. Article-type fit | **5/5** | The article is organized as a stepwise computational protocol with declared evidence layers, a claim map, tests, a conformance suite, and an empirical application. This is materially closer to APS's Protocol definition than to a regular game-AI performance article or a Negative/Null article. |
| 3. Novelty | **4/5** | The integration boundary survives the fatal primary-source test, and the current manuscript cites and contrasts Rollout Cards, Trace Assurance, AEVAL, Event-Keyed CRN, and current agent-stochasticity work. Event-keyed repair, paired-seed analysis, traces, A/A, and metamorphic testing remain explicitly treated as prior art. See `NOVELTY_AUDIT.md`. |
| 4. Usefulness | **4/5** | The evidence-to-claim decision is actionable for researchers who can seed but cannot inspect a simulator. The claim map and suppression behavior are more useful than a checklist alone. Utility depends on the runnable admission interface and clear adaptation guidance. |
| 5. Validation | **5/5** | Five controlled synthetic failure modes, event-keyed repair, manifest tampering, a retrospectively frozen historical failed-gate suppression, deterministic preflight, timed-search context stress, and processed factorial reaggregation exercise both pass and fail behavior. The historical rule is not evidence of prospective blinding, and claims remain bounded to the recorded projection and tested contexts. |
| 6. Generalizability | **4/5** | The protocol is engine-agnostic at the level of evidence interfaces and claim classes. Empirical evidence is one restricted game engine and fixed artifact set, so prevalence and external-performance generalization are explicitly unavailable. |
| 7. Reproducibility | **4/5** | The engine-free review package regenerates and verifies the synthetic suite, evaluates and explains admission evidence, prints the decision table, and independently reaggregates processed evidence without the restricted engine. The rebuilt release commands `verify`, `admit`, `explain`, `report --decision-table`, and `scripts/verify_release.py` passed in this audit. Restricted trajectories cannot be replayed. |
| 8. Open-science readiness | **3/5** | Data/software boundaries and unavailable restricted material are described honestly, and a sanitized package exists. No public archive, DOI, approved creators, maintainer contact, or lawful redistribution license exists. APS permits reasoned unavailability, but the current inability to offer restricted inputs even on reasonable request limits openness. |
| 9. Technical correctness | **4/5** | Schemas, hashes, row-level reaggregation, equation tests, cluster-level resampling, tests, compilation, and page checks support correctness. Intervals are properly scoped as empirical stability summaries; causal timing and semantic-alignment overclaims are rejected. The canonical 25-step pre-review reproduction passed; a final review-bound rerun remains required. |
| 10. Readability | **4/5** | The schedule/repeatability/alignment/admission distinctions are explicit and the title foregrounds the actual question. The 207-word abstract passes the mechanical audit, and all 13 deterministic PDF pages were individually inspected with no clipping, unresolved markers, or unreadable figures or tables. Human general-reader signoff remains pending. |
| 11. Ethical and AI compliance | **3/5** | The manuscript names OpenAI Codex, describes substantive research and writing uses, human direction, verification, and non-authorship in Methods and Acknowledgments, with a machine-readable activity log. A human must confirm completeness of historical AI use and tool/version, terms, confidentiality, privacy, and intellectual-property compliance. |
| 12. Rights and publication readiness | **1/5 — FAIL** | `release/LICENSE` grants no license; `release/RELEASE_STATUS.json` says `BUILT_FOR_REVIEW_NOT_AUTHORIZED_FOR_PUBLICATION`, has no DOI, and records `NO_LICENSE_GRANTED_PENDING_HUMAN_CONFIRMATION`. Ownership, redistribution authority, third-party terms, archive creators, and permissions remain unresolved. |

## Hard gates

Required thresholds from the final-desk brief are article fit, novelty, usefulness, validation, technical correctness, reproducibility, and readability at least 4/5, with scope at least 3/5.

| Gate | Result | Required action |
|---|---|---|
| Scope at least 3 | **PASS, boundary score** | Keep the experimental-design and adjacent-science framing; send the inquiry below before submission if editorial fit remains uncertain. |
| Protocol Article fit at least 4 | **PASS (5)** | Preserve stepwise adoption instructions and make the executable claim map central. |
| Novelty at least 4 | **PASS (4)** | Retain the current close-work contrasts and do not add a component-priority claim. |
| Usefulness at least 4 | **PASS (4)** | Keep concrete outputs, schemas, commands, interpretations, and failure consequences. |
| Validation at least 4 | **PASS (5)** | Preserve both controlled failure fixtures and the genuinely suppressed historical comparison. |
| Technical correctness at least 4 | **PASS (4)** | The pre-review build passed; preserve the same result through the final review-bound evidence commit. |
| Reproducibility at least 4 | **PASS (4)** | The current review package exposes and passes verification, admission, explanation, reporting, and independent processed-data reaggregation. Preserve these interfaces and the manifest through the final build. |
| Readability at least 4 | **PASS (4)** | The current 13-page PDF was rendered at 150 dpi and every page was inspected; human comprehension signoff is still required. |
| Rights resolved | **FAIL — FATAL** | A human rights holder must establish ownership, third-party redistribution authority, appropriate software/data licenses, archive metadata, and any necessary permissions. Do not publish the review directory under its current no-license placeholder. |
| Public/review implementation runs independently | **PASS AT DECLARED REVIEW SCOPE** | The engine-free synthetic and processed analyses, admission, explanation, decision table, and independent verifier run without the restricted engine. Full restricted trajectory replay remains unavailable and is accurately disclosed. This does not cure the separate public-rights failure. |
| Contribution distinct in two sentences | **PASS** | Use: “Prior work separately establishes conditional CRN theory, streams and substreams, paired-seed precision analysis, event-keyed white-box repair, trace-contract assurance, and preserved rollout records. This work integrates them into an executable black-box protocol that audits observable boundary seeds and complete declared traces across execution contexts, separates within-arm repeatability from cross-arm alignment, exercises controlled failures, and maps evidence to claims; its generic completed-case taxonomy is a post-acquisition conservative formalization for future prospective freezing, not a frozen feature of this case.” |
| Abstract does not make factorial null primary | **PASS** | The abstract leads with the protocol, clean-condition acceptance, failure detection, and suppression; it gives no factorial estimate or test statistic and says only that the later admitted effect remained unresolved. |
| AI-use policy complete | **FAIL pending human confirmation** | Confirm all substantive historical uses, best available tool/version information, human verification, tool terms, privacy/confidentiality, and rights. Keep research uses in Methods and other substantive uses in Acknowledgments. |
| DAS accurate and compliant | **ACCURATE BUT NOT PUBLICATION-READY** | The DAS correctly says the package is a review artifact, not public, and explains restricted inputs. Resolve lawful public access or obtain editorial agreement on a reasoned exception; add a real software/data citation only after an archive exists. |
| Reference titles and metadata | **PASS for audited bibliography** | `references.bib` contains titles; `REFERENCE_AUDIT.csv` resolves every retained record to a primary source; the close sources are cited in the current manuscript. |

### Current blockers, in order

1. Rights, ownership, licensing, third-party terms, archive authorization, and public-release status.
2. Human author identity, affiliation, authorship/CRediT, funding, conflicts, permissions, and AI-use confirmation.
3. Final hash-bound five-review aggregation and the post-review reproduction evidence commit.

No submission, archive upload, DOI claim, public license, or editor contact is authorized by this audit.

## Unsent scope inquiry (150 words; do not send)

**Subject: Scope inquiry—Protocol Article on validating pairing assumptions in stochastic agent evaluation**

Dear Editors,

Would APS Open Science consider a Protocol Article presenting an executable method for deciding when same-seed evaluations of black-box stochastic agents support paired statistical claims? The protocol separates schedule matching, within-arm execution repeatability, and cross-arm semantic event alignment. It checks artifact and boundary-seed identity, schedules, repeated trace projections across process, worker, and enqueue contexts, bounded stochastic-source audits, and a result-independent admission rule that downgrades or suppresses unsupported paired wording. A synthetic conformance suite exercises seed conversion, stateful draw shifts, timing and process-state instability, event-keyed repair, and manifest tampering. In a restricted game-simulation case study, deterministic conditions pass without mismatches, timed-search conditions expose trace disagreements, and a historical favorable-looking comparison is suppressed. The contribution concerns computational experimental design rather than game performance. Because the journal's scope includes artificial intelligence, computational and data-intensive science, scientific machine learning, and methodological advances, would this topic and validation package be suitable for a Protocol Article?

Sincerely,  
[Corresponding author; not yet confirmed]
