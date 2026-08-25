# Protocol deviations

Status: `PENDING_HUMAN_SIGNOFF_UNSIGNED`

This record is unsigned. It must remain pending until a human author reviews and
signs off on the reporting/access deviation below.

## Frozen commitment

The frozen timed-search stress protocol said that full restricted traces would
be retained locally and that the review package would contain trace digests,
first-divergence positions and actors, decision counts, terminal outcomes,
errors, and timing summaries. First-divergence position and acting side were
prespecified secondary endpoints.

## Released scope and deviation

This package contains the primary complete-trace digest-disagreement indicator
and the retained decision-count, terminal-outcome, and error-disagreement
summaries. It omits first-divergence localization and timing summaries. Raw
trace lines are absent, so earliest-event and actor localization is unverifiable
at release scope. No localization or timing claim is admitted or made from this
package, and the omitted fields must not be reconstructed or asserted without
verifiable source evidence.

The omission does not change the primary digest-mismatch count of 99 among 200
stress clusters. It is nevertheless a reporting/access deviation from the
frozen protocol and remains pending human signoff.

Human decision: `PENDING`

Human signer: `PENDING`

Date: `PENDING`
