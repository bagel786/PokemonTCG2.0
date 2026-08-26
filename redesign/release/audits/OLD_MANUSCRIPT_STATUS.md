# Old Manuscript Status

**Date:** 2026-08-26
**Branch of record for the redesign:** `paper/claim-specific-prospective-redesign-20260826`
**Frozen prior branch:** `paper/apsos-machine-finalization-20260826` at commit `e07b868bf17d4928e6dc0aa11db5056aff89a168` (preserved, unmodified)

## Status: RETAINED AS INTERNAL TECHNICAL REPORT — NOT SUBMITTED

The existing manuscript ("A Protocol for Validating Pairing Assumptions in Seed-Matched Evaluations of Black-Box Game-Playing Agents", working ladder title "A Validity Ladder for Seed-Matched Evaluation of Game-Playing Agents") is **retained as an internal technical report only**.

1. **It is not being submitted in its current form.** No journal submission has occurred or will occur from this branch.
2. **Its engineering evidence remains useful.** The synthetic failure suite (seed-conversion, stateful draw-shift, timing, process-state), the deterministic preflight result (3,000/3,000 executions, zero required mismatches), and the restricted-engine case results (99/200 timed-search trace-projection disagreements; 210/2,800 outcome-record and 458/2,800 available-record disagreements in one suppressed historical comparison; 458/2,800 in a later frozen-rule comparison) are preserved as historical engineering evidence and motivating material.
3. **Why the redesign exists — external-review concerns addressed:**
   - **Novelty:** the old manuscript integrated known techniques (CRN theory, streams/substreams, paired-seed evaluation, event-keyed repair, trace assurance, protocol cards) into an executable protocol; integration alone is a weak novelty claim.
   - **Universality:** the old "validity ladder" imposed a cumulative ordering that over-requires evidence; exact replay is not necessary for every legitimate paired statistical claim.
   - **Recursive validation:** the framework itself was never prospectively validated against simpler alternatives with known ground truth.
   - **Comparison against simpler methods:** no prospective comparison against schedule-matching-only, A/A controls, extra replication, or honest unpaired/hierarchical analyses was performed.
   - **Incomplete real-system exercise:** the only real system was a restricted engine without redistributable materials, semantic event identifiers, or factorial candidate traces; it cannot establish cross-domain usefulness.
4. **Disposition:** the redesign replaces the cumulative-ladder framing with a claim-specific five-branch framework, adds a fully open known-ground-truth benchmark across at least two open systems (including one scientific/physical stochastic simulator), and measures detection, false suppression, statistical validity, and cost prospectively against simpler baselines. The historical Pokémon case may remain only as a supplementary stress example; it does not validate the redesigned framework.
5. **Historical numbers** (99/200; 210/2,800; 458/2,800) are not discarded. They are used cautiously and separately from any prospective open-system evidence.
