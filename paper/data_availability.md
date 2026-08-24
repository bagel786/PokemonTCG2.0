# Data Availability Statement

The companion package under `paper/release/` is designed to preserve the
evidence needed to inspect the Paired Evaluation Validity Ladder (PEVL) and to
regenerate the manuscript's processed results, tables, and figures. It contains
the self-contained synthetic simulator and fixtures; frozen protocols; artifact
and seed-namespace records; bounded stochastic-source audits; processed
historical repeated-control records; prospective preflight, timed-search, and
factorial analysis outputs; analysis and verification programs; and a
cryptographic manifest. The release verifier checks the frozen inventories,
row schedules, aggregate counts, admission status, and the conditional presence
or absence of factorial effect artifacts. The synthetic component is prepared
for redistribution but remains under a no-license placeholder until ownership
and licensing are approved by the authors.

The restricted case-study artifacts are not sufficient for independent
end-to-end gameplay replay. The tournament engine and source, engine binaries,
card database, decks, private replay observations, full restricted traces,
third-party opponent packages, and policy packages are excluded because of
organizer terms, third-party rights, privacy constraints, or unresolved release
authority. Exact gameplay regeneration therefore requires separately authorized
access to the engine and packages identified by the SHA-256 records in the
protocols. Restricted full traces used for local diagnostic localization are
not redistributed; the companion package retains only safe processed summaries
and digests.

The retained identity-feature corpus and original policy packages also remain
local pending rights review. Their digests, sizes, transformations, and derived
aggregates are documented. Some original historical replay observations no
longer survive, so feature extraction from those observations cannot be
reconstructed even with authorized engine access; this limitation is stated in
the manuscript and provenance audit.

Repository DOI, archival location, version, creators, maintainer contact,
approved license, and any controlled-access request procedure must be supplied
by the corresponding author before submission. Once those facts are available,
the archived software/data object must receive a formal reference-list citation
and the final manuscript and submission form must point to that persistent
record. Until then, `paper/release/LICENSE` grants no redistribution rights.
