# PROTOCOL DEVIATIONS — FINAL DRAFT for human signature (D01–D03)

**Status: FINAL DRAFT — UNSIGNED. Machine-prepared 2026-08-25 on branch
`paper/apsos-machine-finalization-20260826`. Nothing in this file is an
approval, amendment, or signature until a human author initials and dates it.
Machine tooling must not fill any signature field.**

Article: *A Protocol for Validating Pairing Assumptions in Seed-Matched
Evaluations of Black-Box Game-Playing Agents* (APS Open Science Protocol
Article).

This register distinguishes, for every deviation, whether an item is
**(a) recovered and pending approval** or **(b) never recorded**. These are
different facts and require different human dispositions.

---

## D01 — Post-acquisition taxonomy and descriptive relabeling

- **Frozen plan (commit `803257f1`, `paper/protocol/PEVL_PROSPECTIVE_PROTOCOL.md`):**
  binary acquisition/suppression gates; on a pass, finite-population paired
  percentile bootstrap intervals (100,000 draws within ten strata) and secondary
  exact two-sided McNemar inference.
- **Later treatment:** generic claim-class taxonomy and executable rule bundle
  formalized after acquisition; the resampling output relabeled as fixed-battery
  empirical reweighting; the McNemar value retained only as a numerical audit,
  never admitted inference.
- **Effect:** narrows reported claims; does not alter the contrast or the
  resampling arithmetic; cannot retroactively validate the taxonomy.
- **Human disposition required:** confirm this disclosure; no amendment of the
  frozen protocol is asserted.

## D02 — Stress-endpoint integrity hardening

- **Frozen endpoint:** equality of four complete trace digests per cluster.
- **Later extension:** ordered `(digest, byte_count)` comparison, so a
  byte-count-only difference also fails.
- **Observed effect:** none on the primary count — 99/200 digest disagreements;
  96 byte-count disagreement clusters contained within them; 99/200 under the
  combined rule.
- **Human disposition required:** confirm this disclosure.

## D03 — Stress localization, actor, and timing outputs *(the open deviation)*

**Frozen promise (protocol commit):** the public package would contain digests,
first-divergence positions and acting sides, decision counts, terminal outcomes,
errors, and timing summaries.

**Machine-verified state at finalization (2026-08-25):**

| Promised output | State | Evidence |
|---|---|---|
| First-divergence positions | **NEVER RECORDED** — absent from every retained artifact; raw trace payloads remain restricted, so position-level localization can be neither released nor independently verified | Repository-wide closeout search; `first_divergence_position_included=false` |
| Acting side at first divergence | **RECOVERED — redistribution PENDING human approval** | `paper/data/pevl/timed_search_stress_summary.json` sha256 `40b9f5e17a424742ad8a05739646fe56843b8f3a432b124bfc33f9aed1ab5a4b`, field `first_divergence_actor_counts` = `{opponent: 99}` (all 99 disagreeing clusters localized to the opponent side) |
| Timing summaries | **RECOVERED — redistribution PENDING human approval** | Same hash-pinned source, fields `timing_summaries` per opponent × four execution profiles |

**Sanitized processed copies** exist as nonpublic candidate material in
`release/data/processed/timed_search_stress.json` with
`recovered_secondary_outputs_provenance` binding the source SHA-256 above.
They are **not marked public or distributable**; `RELEASE_STATUS.json` remains
`BUILT_FOR_REVIEW_NOT_AUTHORIZED_FOR_PUBLICATION` until you approve.

**Claims boundary while unsigned:** no position-level claim may be made;
actor-side and timing observations may not be represented as independently
reproducible until redistribution is approved. The primary 99/200
digest-disagreement result is unaffected by this reporting/access departure.

### Human sign-off block (complete, initial, and date)

1. I confirm first-divergence positions were never recorded at acquisition time
   (or correct the record): `[CONFIRM / CORRECT — explain]` Initials: ______
2. I confirm the recovered acting-side counts (`{opponent: 99}`) accurately
   reflect retained evidence: `[CONFIRM / CORRECT]` Initials: ______
3. I confirm the recovered timing aggregates accurately reflect retained
   evidence: `[CONFIRM / CORRECT]` Initials: ______
4. Redistribution of the recovered aggregates as processed release data:
   `[APPROVE / DENY]` Initials: ______
5. Disposition of this deviation record (D03 text above):
   `[APPROVE AS WRITTEN / REQUEST CHANGES — specify]` Initials: ______
6. Date of disposition: `[YYYY-MM-DD]`

Signature: ________________________________

---

**After signing:** commit the signed file (or hand it back for transcription),
then run the one-command post-human workflow (`HUMAN_MINIMUM_ACTIONS.md`);
every machine gate re-executes before submission.
