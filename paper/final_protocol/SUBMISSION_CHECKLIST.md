# APS Open Science Protocol Article submission checklist

Current decision: **NOT_READY_DO_NOT_SUBMIT**.

This checklist fails closed. An unchecked item is a blocker unless explicitly
marked “not applicable” by the corresponding author with a reason. Machine
completion cannot satisfy a human-confirmation item.

## Fixed article identity

- [x] Article type is **APS Open Science Protocol Article**.
- [x] Title is **“A Protocol for Validating Pairing Assumptions in Seed-Matched
  Evaluations of Black-Box Game-Playing Agents.”**
- [x] Work is isolated on branch
  `paper/apsos-submission-closeout-20260825`.
- [x] Historical branches and immutable raw result rows were not rewritten by
  the finalization workflow.
- [x] No new outcome-driven policy experiment was authorized for this
  finalization.
- [ ] Corresponding author confirms that the article is not simultaneously
  under consideration elsewhere and that all overlapping reports, preprints,
  competition materials, and public writeups are disclosed.

## Scientific and statistical gates

- [ ] Final claim ledger contains every quantitative, comparative, novelty,
  procedural, rights, and contribution-boundary sentence identified by the
  deterministic claim-scope audit; every excluded prose sentence has a recorded
  mechanical outside-scope reason, and no `PENDING`, `CONFLICT`, or
  `UNSUPPORTED` claim remains in evidentiary prose.
- [ ] Final source hashes, protocol commit, schemas, row counts, strata,
  analysis units, and admission statuses pass the one-command reproduction run.
- [ ] Historical mismatch counts independently reaggregate to 210/2,800 for the
  available-outcome (win/draw) projection and 458/2,800 after decision count is
  added.
- [ ] Deterministic preflight independently verifies 1,000 arm–seed-condition
  units, 3,000 executions, and zero required mismatches.
- [ ] Timed-search stress analysis independently verifies 99/200 trace-
  disagreement clusters, 47 outcome disagreements, 93 decision-count
  disagreements, zero error-record disagreements, and the 42.5%–56.5%
  empirical interval from 100,000 whole-cluster resamples.
- [ ] Factorial analysis independently verifies 2,000 units per cell, 12,000
  engine games, zero repeated-control available-record mismatches, all four
  cell rates and contrasts, and the secondary McNemar result.
- [ ] Factorial rows with `trace_mode=none` are never described as having zero
  trace mismatches; absent trace data are shown as unavailable.
- [ ] Manuscript avoids equivalence, superiority, universal reliability,
  unique-cause, full-CRN, counterfactual-coupling, state-of-the-art, and external-
  generalization claims.
- [ ] Human author has confirmed all 17 method entries in
  `METHOD_ASSUMPTION_AUDIT.md`.
- [ ] Human author has confirmed all 4 equations, including every symbol, unit,
  sign, index, and interpretation, in `EQUATION_AUDIT.md`.

## References and contribution boundary

- [x] `REFERENCE_AUDIT.csv` contains 21 audited and verified records, matching
  all 21 retained bibliography entries and cited keys.
- [x] The unresolved “Silent Unpairing” record was removed rather than cited or
  used to support manuscript wording.
- [ ] Every final bibliography entry and sentence-level use is rechecked against
  a primary publisher, proceedings, arXiv, or OpenReview record after the final
  manuscript edit.
- [ ] Corresponding author approves the boundary that CRN, streams/substreams,
  paired seeds, event-keyed randomness, A/A and metamorphic testing, simulation
  verification, RL reproducibility, and time/work search budgets are prior art.
- [ ] Prohibited priority language (`first`, `novel`, `to our knowledge`,
  `unprecedented`, `groundbreaking`) is absent unless separately justified and
  explicitly approved; no such approval is currently recorded.

## Reproducibility package

- [ ] `python -m pevl_bench generate` passes from the final release.
- [ ] `python -m pevl_bench verify` passes from the final release.
- [ ] `python -m pevl_bench report` passes from the final release.
- [ ] `python -m pevl_bench admit examples/example_evidence.json` and
  `python -m pevl_bench explain examples/example_evidence.json` pass from the
  final release and enforce the generated decision table.
- [ ] `python paper/final_protocol/scripts/reproduce_all.py` verifies hashes and
  schemas, validates protocol IDs, rebuilds statistics/macros/tables/figures,
  runs tests and contradiction checks, compiles the paper, and writes
  `REPRODUCTION_REPORT.json` with `PASS`.
- [ ] `REPRODUCTION_REPORT.sha256` verifies the exact report bytes, and
  `python paper/final_protocol/scripts/verify_reproduction_report.py` performs a
  read-only check of the report, bound inputs, canonical subject digest, output
  hashes, and preserved `NOT_READY_DO_NOT_SUBMIT` decision.
- [ ] The report records exact observed Python, direct declared package,
  Tectonic, Poppler, operating-system, and architecture versions and states that
  `requirements-lock.txt` is a direct dependency declaration, not a transitive
  lock or proof of a fresh environment.
- [ ] The report binds the current Git `HEAD` and tree while separately binding
  relevant dirty and untracked package bytes through the canonical subject
  digest; it does not describe a dirty workspace as a clean checkout.
- [ ] The reproduction run records and rejects unexpected tracked-file drift
  outside its explicit generated-output allowlist.
- [ ] Release works without the restricted game engine.
- [ ] Manifest covers every released file and verifies from a clean copy.
- [ ] Release contains the synthetic suite and expected outputs, processed
  historical and prospective diagnostics, sufficient processed factorial rows,
  protocols, analysis/table/figure code, tests, dependency information, source
  data, notices, citation metadata, and exact commands.
- [ ] Release excludes engine source/binaries, game assets or metadata, private
  opponent packages, policy weights, private replay observations, raw restricted
  traces, credentials, absolute local paths, archives, and unapproved third-
  party files.
- [ ] Final contradiction audit reports no unresolved contradiction in title,
  type, sample sizes, counts, hashes, estimates, intervals, claims, availability,
  disclosures, and artifact inventory.
- [ ] Five independent desk-review simulations are bound to the final artifact
  hashes and their fail-closed aggregate is recorded in
  `DESK_REVIEW_SIMULATION.json`.

## Manuscript and visual audit

- [ ] `main.pdf` is freshly compiled from the final `main.tex` and generated
  artifacts.
- [ ] Every PDF page is rendered to an image and inspected for title, author
  placeholders, abstract, equations, minus signs, intervals, tables, captions,
  labels, references, links, page breaks, blank pages, clipping, tiny fonts,
  unresolved macros, and stale figures.
- [ ] Final PDF hash is recorded after the last source change.
- [ ] Abstract is one paragraph, under 500 words, citation-free, and contains
  only supported central results and one major limitation.
- [ ] Main narrative uses neutral policy and context labels and contains no game
  strategy, card names, leaderboard rank, or development chronology.
- [ ] Every figure is code-generated with source data and contains no
  copyrighted game art or AI-generated decorative image.
- [ ] Figure count, table count, captions, and source-data references agree
  across manuscript, release README, and contradiction audit.

## Data, software, rights, and archive blockers

- [ ] **Ownership:** human author identifies who owns each release code and data
  component.
- [ ] **Redistribution authority:** human author confirms that every included
  component may legally be redistributed.
- [ ] **License:** rights holders approve a specific software/data license and
  its exact scope. Current no-license status grants no redistribution rights.
- [ ] **Third-party notices:** all included dependencies and content receive
  approved notices.
- [ ] **Archive:** corresponding author approves archive creation, version,
  creators, maintainer contact, and persistent location.
- [ ] **DOI:** an actual DOI is minted and verified before it appears in the
  manuscript, cover letter, citation metadata, or submission forms. No DOI is
  currently established.
- [ ] **Restricted-list approval:** human author confirms the engine, engine
  binaries/source, third-party opponent packages, game assets and metadata,
  private replay observations, policy packages, and raw restricted traces are
  accurately excluded.
- [ ] **No-on-request check:** restricted materials are not described as
  “available on request” unless legal authority and a practical access mechanism
  are documented; neither is currently established.
- [ ] **Naming permissions:** author confirms whether organizations, competition
  operators, opponents, packages, or individuals may be identified.

## AI-use disclosure blockers

- [ ] Human author confirms the complete history of substantive AI assistance,
  including any use predating the recorded finalization sessions.
- [ ] Tool name and model/version are reported only to the precision actually
  exposed; the exact GPT-5-family snapshot remains unavailable.
- [ ] Research-conduct uses appear in Methods; other substantive assistance
  appears in the disclosure/acknowledgment.
- [ ] `supplement/AI_USE_LOG.csv` is reviewed row by row and corrected or
  extended by the human author.
- [ ] Human author confirms confidentiality, privacy, intellectual-property,
  data-access, and applicable tool-term compliance.
- [ ] Human author confirms no AI system is listed as an author and no AI-
  generated figure was used.

## Human metadata blocker checklist

- [ ] Final author names and formatting.
- [ ] Author order and coauthor eligibility.
- [ ] Affiliations and complete postal addresses.
- [ ] Corresponding-author name and email.
- [ ] ORCIDs, or explicit confirmation that an author has none/declines where
  permitted.
- [ ] CRediT roles for every author.
- [ ] Funding sources and grant identifiers, or a confirmed “no funding”
  statement.
- [ ] Financial and nonfinancial competing interests, or an approved “none”
  statement.
- [ ] Acknowledgments and permission to name acknowledged people or
  organizations, or a confirmed “none” statement.
- [ ] Author approval of the title, abstract, manuscript, supplement, cover
  letter, availability statement, AI disclosure, contributions, and conflict
  statement.
- [ ] Corresponding author confirms originality and all required overlap
  disclosures.
- [ ] Suggested-reviewer names, affiliations, expertise, and emails, if requested
  by the submission system.
- [ ] Excluded reviewers and reasons, or explicit confirmation of none.
- [ ] Every author confirms responsibility for the final content and that no
  contribution was inferred from Git history.
- [ ] Human author demonstrates comprehension of all 29 questions in
  `AUTHOR_DEFENSE_GUIDE.md` and completes its sign-off table.

## Submission controls

- [ ] APS author instructions, ethics declarations, AI policy, data/software
  fields, and required forms are checked again on the actual submission date.
- [ ] Corresponding author approves the final readiness decision.
- [ ] A human, not an automated agent, performs the submission.

**Fail-closed decision:** Until every required item above is checked and
evidenced, retain `NOT_READY_DO_NOT_SUBMIT`.
