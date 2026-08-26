# Independent worked admission example

This minimal example does not use the restricted game engine. It supplies five
synthetic artifact files, a configuration file, a two-arm paired schedule,
and three declared execution profiles per arm. Its canonical
`admission_evidence_sha256` binds the gate evidence and declared trace projection.
The verifier rejects undeclared files in the dedicated examples/evidence/
support tree, checks every declared regular single-link file against its SHA-256,
checks trace byte counts, and derives the first five gate states from cross-profile
record comparisons. The control trace changes only in the worker profile, so
`repeat_and_worker_parity` is `fail`. The bundle truthfully marks the missing
bounded stochastic-source audit `unavailable` and semantic event alignment
`not_applicable`; this format cannot claim those gates passed.

The apparently favorable material under `result_data` is neither hashed nor
read. Replacing it leaves the admission decision byte-for-byte unchanged.

This is an internal-consistency demonstration, not scientific authentication.
The verifier does not parse engine-specific trace semantics or prove that a
declared role or profile arose from a particular acquisition. Decisions therefore
record external_scientific_provenance_verified as false and identify the
self-asserted trust boundary. A real use requires an independently controlled
acquisition manifest or equivalent external provenance anchor.
Verification also assumes that the local bundle is quiescent while it is read;
it is not a synchronization primitive against a concurrent filesystem writer.

From the release directory, run:

```bash
python -B -m pevl_bench admit examples/example_evidence.json
python -B -m pevl_bench explain examples/example_evidence.json
python -B -m pevl_bench report
python -B -m pevl_bench report --decision-table
```

The expected permitted class is `schedule_matched`. The required wording says
only that declared schedule fields matched. It forbids execution-repeatability,
paired-effect, shared-random-event, and event-alignment wording. The first
blocking gate is Level 5, repeat-and-worker parity. To seek a stronger claim, the
researcher must resolve the trace disagreement, reacquire all profiles required
by the frozen design, complete the stochastic-source audit, and rerun admission.

The JSON rule bundle is explicitly a post-acquisition executable formalization.
It does not claim to have existed at the frozen protocol commit, and it cannot
override an experiment-specific suppression rule in the frozen protocol. The
frozen case-study plan's finite-population paired-bootstrap intervals and
secondary exact McNemar inference remain visible in the protocol transcriptions;
the current Level-6 descriptive-only restriction is a later conservative
reporting rule, not prospective validation. Future adopters must freeze that
taxonomy and its uncertainty rules before acquisition. The
separate `classify-trusted` interface is a pure classifier for callers that have
already validated their own states; its output explicitly says that evidence
was not machine verified.
