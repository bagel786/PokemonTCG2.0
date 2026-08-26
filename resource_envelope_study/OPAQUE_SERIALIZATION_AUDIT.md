# Opaque `search_begin_input` serialization audit

## Status and scope

**RESOLVED FOR PRE-FREEZE IMPLEMENTATION; BINDING REPLAY GATE REMAINS `STOP`-ON-MISMATCH.**

This audit resolves how the study treats the evaluation engine's opaque
`search_begin_input`. It does not establish a portable serialization format,
change engine or production code, authorize scientific acquisition, or weaken
the frozen-state repeatability gate.

## Observed Azure Linux behavior

Two clean-process captures used the same seeded source-game inputs and reached
the same public decision state. Their opaque strings did not have the same
SHA-256. After reversing the engine's custom base64/run encoding, the comparison
reported one differing byte at `22331/22336` (differing decoded-buffer offset /
decoded-buffer length). Public semantic state and source history agreed.

The unequal digest values themselves were observed during the Azure audit but
were not retained in the study record. That evidence-recording omission is not
papered over with invented values. It is the reason every future capture audit
must preserve the original opaque bytes, opaque byte count, opaque-byte SHA-256,
embedded captured-state hash, and complete artifact-file SHA-256.

The Azure replay audit then exercised all three study agents across five agent
seeds each at fixed `N=8` (15 agent/seed cases per artifact). Across the two
independent recaptures, the public semantic state hash, semantic selected-action
hash, eight completed work units, terminal status, and cleanup status agreed in
all 15 cases. This supports semantic recapture equivalence for that audited
state; it does **not** make the two opaque strings interchangeable.

The locked regression matrix uses agents `one_ply_value_v1`,
`flat_rollout_v1`, and `puct_tree_v1`; seeds `778899` through `778903`; and
fixed `N=8`.

## Source evidence for raw-memory-derived bytes

The checked-in evaluation-engine source explains why raw-byte identity is a
stronger and less portable condition than public semantic identity:

- `ApiGetBattleData` copies the engine `State`, erases hidden player data, calls
  `State::serialize`, and then applies the custom base64 encoding
  (`freshstart/engine/ptcgProgram/Api.h`, `ApiGetBattleData`).
- `State::serialize` writes the contiguous address range from `&turn` to
  `&options` and then writes vector storage
  (`freshstart/engine/ptcgProgram/State.h`, `State::serialize`).
- `BinaryWriter::set(const void *, size_t)` copies bytes directly, while its
  vector overload writes `sizeof(T) * list.size()` bytes
  (`freshstart/engine/ptcgProgram/Binary.h`, `BinaryWriter`).

Thus the opaque payload includes native object-representation bytes, potentially
including padding or other nonsemantic representation details. Padding is a
plausible explanation for the observed tail-byte variance, not a proven causal
diagnosis. The study does not edit the engine, infer meaning from the differing
byte, or normalize/mask any part of the payload.

## Binding capture and replay contract

For each admitted frozen state:

1. Capture `search_begin_input` once.
2. Encode its original ASCII string in the canonical captured-state artifact
   without decoding or transformation.
3. Record its exact byte count and SHA-256 over the original ASCII bytes.
4. Bind the complete state, including the unchanged raw string, with an embedded
   captured-state hash.
5. Write canonical JSON and record the complete file SHA-256.
6. Require that file SHA-256 on every scientific load. Reject a changed digest,
   noncanonical JSON bytes, wrapper/state hash mismatch, opaque count/hash
   mismatch, or non-ASCII opaque input.
7. Reuse that same verified `raw_state` byte-for-byte for every panel replay.

An independent recapture is audit evidence only. It may be compared on exact
source identifiers, public state, deterministic history, and the fixed-work
output matrix. It must be retained under its own hashes and may never silently
replace the frozen artifact.

## Strict admission gate

The same frozen artifact must be replayed in at least two clean processes. For
each of the 3 agents x 5 seeds at fixed `N=8`, the following fields must agree:

- public/adapter state hash;
- semantic selected-action hash;
- completed work (`8` exactly);
- terminal status (`ok`); and
- cleanup status (`true`).

The artifact file digest, embedded captured-state hash, opaque SHA-256, and
opaque byte count must also remain unchanged. Any mismatch is unexplained by
definition and produces `STOP`; no frozen-state panel acquisition may begin, and
no same-state action-divergence claim may be made.

## Regression evidence

`resource_envelope_study/tests/test_native_integration.py` now:

- freezes one capture and replays that same verified file in two clean
  processes over the full 3 x 5 x `N=8` matrix;
- separately compares independent recaptures using public semantics and the
  fixed-work output matrix, without requiring or discarding opaque differences;
- proves with a synthetic regression that two semantically equal captures with
  different opaque strings pass only the independent-recapture predicate and
  fail the strict same-artifact predicate; and
- rejects whitespace/key-order rewrites as noncanonical even when a caller does
  not supply an expected file digest.

These are native smoke/audit tests, not scientific acquisition. The focused
test command is:

```text
pytest -q resource_envelope_study/tests/test_native_integration.py
```
