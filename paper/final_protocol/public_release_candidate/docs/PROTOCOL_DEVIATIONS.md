# Protocol deviations

Status: `PENDING_HUMAN_SIGNOFF_UNSIGNED_POSITIONS_UNRECOVERED`

This record is unsigned. It must remain pending until a human author reviews and
signs off on the reporting and access deviation below.

## Frozen commitment

The frozen timed-search stress protocol said that full restricted traces would
be retained locally and that the review package would contain trace digests,
first-divergence positions and actors, decision counts, terminal outcomes,
errors, and timing summaries. First-divergence position and acting side were
prespecified secondary endpoints.

## Released scope and residual deviation

This package contains the primary complete-trace digest-disagreement indicator,
the retained decision-count, terminal-outcome, and error-disagreement summaries,
and two recovered secondary outputs added from hash-pinned retained evidence:

- acting-side counts at first divergence (`first_divergence_actor_counts`):
  all 99 disagreeing clusters had their earliest divergence on the opponent side;
- per-opponent, per-profile wall-clock timing summaries (`timing_summaries`).

First-divergence **positions** were never recorded in the retained artifacts,
and raw trace payloads are restricted and not redistributed. Raw trace lines are
absent from the package, so position-level localization remains unverifiable at
release scope. No position-localization claim is admitted or made from this
package, and the omitted field must not be reconstructed or asserted without
verifiable source evidence.

The omission does not change the primary digest-mismatch count of 99 among 200
stress clusters. It is nevertheless a reporting/access deviation from the frozen
protocol and remains pending human signoff.

Human decision: `PENDING`

Human signer: `PENDING`

Date: `PENDING`
