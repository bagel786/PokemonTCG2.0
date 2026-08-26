# Cover letter — final draft

**Status: READY FOR HUMAN SIGNOFF.** Corresponding-author identity, ORCID,
overlap-disclosure sentence(s), and reviewer selections arrive from
`human_answers.yaml`; the letter itself carries no internal file names, hashes,
or unresolved claims.

Dear Editors,

We seek consideration of "A Protocol for Validating Pairing Assumptions in Seed-Matched Evaluations of Black-Box Game-Playing Agents" as an **APS Open Science Protocol Article**.

When two stochastic agents are evaluated under the same recorded seed, the shared value names a matched schedule. It does not establish repeatable execution, nor that the same semantic random events received the same quantities after the agents' paths diverge. Deciding when a seed-matched result may legitimately be analyzed as a paired comparison is therefore an open methodological problem across simulation, machine learning, and adjacent computational sciences.

The article contributes an executable, fail-closed protocol that answers this question with observable evidence: artifact identity, the exact integer passed at the engine boundary, row-level schedule parity, identical-arm repetition of a declared trace projection across fresh-process and worker contexts, a bounded audit of stochastic sources, semantic event alignment where an event ontology exists, and a statistical admission step that downgrades or suppresses paired wording whenever required evidence is absent. Missing evidence can never be repaired by a favorable estimate.

Validation combines two elements. A self-contained synthetic suite reproduces clean determinism, seed conversion, stateful draw shift, clock-budget and process-state dependence, demonstrates event-keyed repair inside its declared ontology, and rejects schema or manifest tampering. In a restricted black-box game-engine case study, a deterministic preflight showed zero required mismatches across 3,000 executions, while 99 of 200 fixed timed-search seed-condition clusters disagreed on the recorded trace projection. One apparently favorable historical comparison was suppressed by a repeated-control audit rule frozen retrospectively after those outcomes existed - a rule-application example, not prospective blinding. A later four-cell comparison (2,000 paired units per cell) is reported descriptively, with its contrast left explicitly unresolved. Admission tracked evidence, not favorability.

Prior work supplies common-random-number theory, streams and substreams, counter-based generators, event-keyed repair, rollout preservation, trace contracts, deterministic workflow tests, protocol cards, and paired noise-floor analysis. None of these works validates seed-to-execution coupling through within-arm trace repetition across execution contexts while mapping failed coupling evidence to automatic suppression of the paired claim; this integration is the contribution boundary we claim, and we claim no component as new.

The engine-independent companion package contains the synthetic implementation, admission rules and decision tables, worked example, tests, processed diagnostics, analysis code, protocols, figure source data, and integrity manifests. It excludes the tournament engine and source, engine binaries, third-party opponent packages, game assets and metadata, policy packages and weights, private replay observations, and raw restricted traces; these cannot be shared under presently established rights, and the package is not represented as publicly available until ownership, license, archive, and DOI decisions are made.

OpenAI Codex, using a GPT-5-family model whose exact deployed snapshot was not exposed, assisted under human direction with literature synthesis, protocol reasoning, code and test generation, statistical checking, drafting, and adversarial review; verification procedures and limits are stated in the manuscript, no AI system is an author, and no generative-image system was used.

Overlap disclosure: [exact approved sentence(s) transcribed from human_answers.yaml at apply time].
Suggested reviewers: [human-approved candidates or 'omitted' — transcribed from human_answers.yaml at apply time].

Sincerely,

**[Corresponding-author name, email, and ORCID transcribed from human_answers.yaml]**
