# Draft cover letter — APS Open Science

Dear Editors,

We submit “Representation Repair under Distribution Shift in a Partially
Observable Card Game” for consideration as a Regular Article in *APS Open
Science*.

The manuscript reports a bounded representation failure in a tournament
card-game policy: option-level hand indices were not relationally bound to the
selected observed card/template ID (the source-card type ID). We isolate the
repair, update only four output-side modules—the option projection plus score,
count, and value heads—on outcome-selected, winner-only recorded actions
from a frozen baseline, and compare the resulting policy with its control on an
engine-seed-, order-, and seat-matched schedule prospectively specified in a
locally committed protocol before result access, against seven fixed opponents.
The observed equal-weight difference in that one execution was +2.786 percentage
points (95% conditional empirical interval from stratified paired resampling
[+0.679, +4.929]).
The interval is conditional on the realized execution: two opponent packages
use wall-clock-bounded search, and candidate and control games were separate
process-pool tasks.

The planned seven-opponent four-cell analysis was invalidated by its
prospectively frozen analyzer gate. C1 outcomes differed across executions on 210 of 2,800
seed-condition units (191 against Starmie and 19 against Dipplin), so the
planned cross-cell C4–C2, C4–C3, and interaction contrasts are not estimable.
Within-run mechanistic summaries and any five-opponent available-record-parity
subset are labeled descriptive and post hoc, respectively; neither is presented
as an independent primary confirmation.
The paper also reports retained null results, missing-artifact conflicts, and
legal limits on end-to-end redistribution rather than presenting unsupported
historical aggregates.

The intended submission package includes a Data Availability Statement,
substantive AI-use disclosure, claim ledger, protocols, processed paired
outcomes, deterministic analysis scripts, six code-generated figures, a
companion repository provenance audit, and a sanitized private-review companion
package pending final build verification and rights approval.
Third-party engine and replay materials are
not redistributed; hashes and access constraints are stated explicitly.

**This cover letter must not be sent in its present form.** Before submission,
the authors must either complete a timing-robust evaluation that resolves the
opponent nondeterminism or affirm that the manuscript's one-execution,
conditional primary claim is scientifically sufficient and remove any
mechanistic interpretation of the invalidated ablation.

The work is original and is not under consideration elsewhere. **The
corresponding author must confirm this sentence, identify any related competition
reports or public writeups, explain overlap, and supply citations/URLs before
submission.** All authors, affiliations, ORCIDs, contributions, conflicts,
funding, and suggested/excluded reviewers likewise require human completion.

Sincerely,

**[Corresponding author name, affiliation, postal address, email, and ORCID]**
