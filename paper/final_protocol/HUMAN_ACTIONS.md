# Human actions required before submission

Status: **OPEN — the manuscript must not be submitted.** Machine checks cannot
resolve or infer any item below. Record names, decisions, dates, and signatures
only after the responsible humans have confirmed them.

## Authorship and disclosure

- Confirm every author’s identity, order, eligibility, affiliation, complete
  postal address, corresponding-author email, ORCID choice, and CRediT roles.
- Confirm funding and grant identifiers or approve an accurate no-funding
  statement.
- Collect and approve all financial and nonfinancial conflicts.
- Approve acknowledgments and permissions to name people or organizations, or
  confirm that none are needed.
- Have every author approve the final manuscript and submission.

## Rights, release, and archive

- Identify the creator and owner of every proposed release component and obtain
  qualified review of competition terms, derived records, privacy, and
  third-party rights.
- Decide exactly which code, processed data, protocols, figures, and metadata
  may be redistributed. Approve suitable software/data licenses or preserve an
  explicit restriction.
- Confirm that neutralized records do not expose protected participants,
  packages, observations, or confidential information.
- If public release is authorized, approve the final `CITATION.cff`, maintainer
  contact, versioned archive deposit, license files, and DOI. Do not add a DOI
  or call the package public before the deposit exists.

## Scientific comprehension and verification

- Sign every generated row of `claim_ledger.csv`; its row count is computed by
  the ledger builder and contradiction audit rather than copied into this
  checklist. Blocked claim statuses may not be converted by prose alone.
- Sign all 4 items in `EQUATION_AUDIT.md`, all 17 items in
  `METHOD_ASSUMPTION_AUDIT.md`, and all 29 questions in
  `AUTHOR_DEFENSE_GUIDE.md` after independently explaining the method,
  assumptions, analysis unit, and limitation.
- Confirm the final novelty boundary and the two-sentence contribution
  statement against the cited primary sources.

## AI-use confirmation

- Confirm that `supplement/AI_USE_LOG.csv` covers all substantive AI use in the
  research and manuscript, including uses not recoverable from Git history.
- Confirm compliance with applicable tool terms, privacy/confidentiality,
  intellectual-property, data-access, and usage-limit obligations.

## Final authorization

- After all items above are complete, rerun the one-command reproduction and
  review the newly rendered PDF, release manifest, contradiction audit,
  claim-scope audit, report SHA-256 sidecar, read-only report verification, and
  desk-review gate.
- The corresponding author must explicitly authorize any APS upload and
  submission. Codex is not authorized to upload or submit.

Until every applicable item is resolved and the machine gate is rerun, the
decision is `NOT_READY_DO_NOT_SUBMIT`.
