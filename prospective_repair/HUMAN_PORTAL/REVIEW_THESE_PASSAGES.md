# REVIEW THESE PASSAGES FIRST

Passages below are the highest-stakes sentences a reviewer (or you) will be
held to. Verify each against its cited source before signing anything.

1. **Freeze wording (protocol §0 / REGISTRATION_STATUS.md).**
   "Timestamped commit pushed to the private origin remote BEFORE outcome
   acquisition; NOT public preregistration." Check: no document claims public
   preregistration, registration benefits, or a DOI.

2. **V1 quarantine (manuscript §7.6).** The old campaign's 37.5% Branch-B
   false suppression, 48.8% Branch-C detection, S3 zero-variance "benefit,"
   and 0.0 s runtime medians are reported as defects of that UNREPAIRED
   implementation — never as properties of the framework or as confirmation
   of anything here. Check: nowhere do those numbers stand beside new results
   without the quarantine label.

3. **Abstention semantics (BASELINE_SPECS rules 1–4).** An unsupported-branch
   method returns ABSTAIN_NOT_EVALUATED; abstention counts only toward
   coverage. Check: no table scores abstention as detection/suppression.

4. **Statistics unit (ANALYSIS_PLAN A/B).** Case = system×construction;
   seeds nested; contrasts are case-level sign-flip permutations with cluster
   bootstrap CIs; z-tests forbidden by schema validator. Check: any p-value
   you read maps to that procedure, not a two-proportion z.

5. **CRN benefit label (stats.py/variance_ratio_benefit).** Exploratory-only,
   joint seed-cluster bootstrap; zero-variance rows flagged
   DEGENERATE_NOT_BENEFIT. Check: no independence-based interval survives.

6. **Gates separation (METRICS_AND_GATES).** Integrity-failure ⇒
   NOT_READY_DO_NOT_SUBMIT; recommendation-gate failure alone leaves a
   technically ready negative-result package; submission stays human-pending.
   Check FINAL_GO_NO_GO.md separates these rather than conflating again.
