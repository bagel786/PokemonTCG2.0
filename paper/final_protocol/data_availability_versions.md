# Data Availability Statement — candidate versions

Exactly one version is applied by `apply_human_answers.py` based on
`data_availability_version` in `human_answers.yaml`. Version A is selectable
ONLY when ownership, license, archive authorization, and a live DOI all exist.
Until then the manuscript ships with Version B content (its current
"Public (with submission, pending rights approval)" + "Restricted." blocks).

---

## VERSION A — PUBLIC COMPANION APPROVED

**Data Availability Statement.** The computational companion for this article
is publicly available at [REPOSITORY NAME/URL] under DOI [DOI] (code: MIT;
processed data, documentation, and figure source data: CC BY 4.0). It contains
the synthetic protocol conformance implementation with expected fixtures, the
executable admission engine with generated decision tables including the
Stage-6 source-audit rules, processed historical, preflight, stress, and
factorial diagnostics — including recovered acting-side first-divergence
counts and timing aggregates with source-digest provenance — analysis and
verification scripts, sanitized protocol transcriptions, figures with source
data, schemas, manifests, tests, environment declarations, and one-command
reproduction instructions. The companion is computationally self-contained for
the synthetic and processed analyses and does not require the game engine.

The restricted materials cannot be shared: the tournament engine and source,
engine binaries, third-party opponent packages, game assets and metadata,
private replay observations, policy packages and weights, and raw restricted
traces are unavailable because of organizer terms, third-party rights,
privacy constraints, and unresolved release authority. They are not offered on
request; their identities appear only as approved digests and bounded
processed summaries.

---

## VERSION B — PUBLIC COMPANION NOT APPROVED

**Data Availability Statement.** For review, the manuscript is accompanied by
an engine-independent computational companion containing the synthetic
protocol implementation and fixtures with expected outputs, the executable
admission engine with generated decision tables (including Stage-6
source-audit rules), processed historical, preflight, stress, and factorial
diagnostics — including recovered acting-side first-divergence counts and
timing aggregates pending redistribution approval — analysis and verification
scripts, protocol transcriptions, figures with source data, schemas, hashes,
tests, environment declarations, and reproduction instructions. It runs
without the game engine. Public archival availability is not yet established:
ownership, an approved software/data license, archive creators, maintainer
contact, and a DOI await explicit human authorization, so this statement does
not describe the package as public and no later release is promised here.

The tournament engine and source, engine binaries, third-party opponent
packages, game assets and metadata, private replay observations, policy
packages, and restricted raw traces are unavailable because of organizer
terms, third-party rights, privacy constraints, and unresolved release
authority. They are not offered on request because no legal authority or
controlled-access mechanism is established; this limitation is flagged as an
editorial-risk item rather than resolved by wording. Their identities are
represented only by approved digests and bounded processed summaries, and
exact restricted gameplay regeneration requires separately authorized access
this article cannot provide.

---

### Selection rule (enforced by validate_human_answers.py)

Version A requires ALL of: code_redistribution_approved=true ·
processed_data_redistribution_approved=true · archive_authorized=true ·
live DOI present in release_rights.doi. Any unmet prerequisite forces Version
B. No invented or reserved-but-not-live DOI may be inserted.
