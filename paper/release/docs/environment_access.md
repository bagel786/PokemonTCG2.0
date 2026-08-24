# Restricted environment access

The engine used for the manuscript was supplied under competition-specific
terms. The local license states that it is not open source, limits use to the
competition, prohibits redistribution and out-of-scope use, requires deletion
after the competition, and defers to the binding competition rules. This
companion package therefore contains no engine source, binary, derivative
binding, rule table, card database, or executable opponent package.

To attempt an authorized engine-level reproduction:

1. Contact the competition organizer and rights holders rather than the paper
   authors to request lawful access under the applicable terms.
2. Verify the received engine executable against the SHA-256 listed in the
   manuscript protocol. A mismatched build is a different environment.
3. Implement `src/abstract_engine.py::AuthorizedEngineAdapter` without copying
   restricted implementation material into this package.
4. Verify candidate, control, and opponent package digests separately and obtain
   any needed permissions from their owners.
5. Run the frozen seed/order/seat schedule in the included protocols. Preserve
   incomplete pairs and fail closed on errors or digest drift.
6. Export only the minimal processed row schema used by
   `evaluation/verify_processed.py`, after conducting privacy and rights review.

The authors cannot guarantee that organizer access remains available. Processed
result reproduction and engine-trajectory reproduction are therefore distinct
levels of reproducibility.
