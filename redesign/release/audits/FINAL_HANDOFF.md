# Final handoff

Generated: 2026-08-26
Decision: **NOT_READY_DO_NOT_SUBMIT**

This is the fail-closed handoff for the prospective claim-specific validation study. It records what was completed, what the data support, and why the package cannot be submitted without a new frozen repair-and-rerun cycle.

1. **Branch and commit.** Branch: `paper/claim-specific-prospective-redesign-20260826`. The protocol freeze is commit `62ad878`. The closeout commit is the commit containing this file; resolve it with `git rev-parse HEAD` after checkout.
2. **Old manuscript status.** The old manuscript was not polished into a submission. Historical material was used only as explicitly labeled motivating or retrospective evidence.
3. **Feasibility.** Feasibility and smoke checks passed before the prospective run; see `FEASIBILITY_REPORT.md` and `BENCHMARK_REPORT.md`. Passing feasibility did not validate the later scenario implementations.
4. **Systems and licenses.** RLCard 1.2.0 limit hold'em and the local Ising toolkit are both MIT-licensed. The final-system RLCard license was corrected from a stale candidate-system Apache annotation under deviation D007.
5. **Framework.** The framework separates claim requirements into Branches A–E instead of treating replay strength as a cumulative ladder. The implementation nevertheless contradicts that separation for one Branch-B downgrade rule; this is disclosed as K001.
6. **Freeze.** The protocol, scenario plan, sample-size rationale, and statistical design were pushed in commit `62ad878` before outcome acquisition.
7. **Methods.** Eight methods were evaluated: B0 schedule-only, B1 outcome A/A, B2 trace A/A, B3 within-seed repetitions, B4 unpaired, B5 cluster/hierarchical, B6 event-keyed coupling, and B7 full CSVF.
8. **Scenarios.** S0–S10 were run for both systems. S7 deliberately retained 27 of 40 seeds per system. The Ising S4/S8 clock-residual mechanics were not injected as intended, and hold'em S3 collapsed the arm contrast; these are benchmark defects, not scientific results.
9. **Sample size.** The frozen target was 40 seeds per system-scenario cell, with the predeclared S7 drop rule. The target was justified before acquisition; no post-outcome enlargement was made.
10. **Raw data.** `results/final/raw/decisions_and_pairs.jsonl` contains 35,014 rows: 34,160 decision rows and 854 outcome-pair rows. SHA-256: `ead6dd392c61767c914f9bb1956b7a82213c5889f3e95faf15c4a3f3ec5d2540`. Structural integrity checks pass.
11. **Principal result.** B7 does not pass the predeclared worth-recommending gate. Its pooled hard-invalid detection is 89.3901%, and its pooled false-suppression rate is 14.5636%.
12. **Detection.** B7 detection by claim branch is A 100.00%, B 100.00%, C 48.75%, D 99.25%, and E 100.00%. Branch C fails the 95% threshold.
13. **False suppression.** B7's pooled false suppression is 14.5636%. Branch-B false suppression is 37.50%; Branch-D false suppression is 41.1894%. Both exceed the 5% threshold.
14. **M4–M6.** Confirmatory M4 coverage and M5 type-I error are not estimable. M6 power is a partial post-freeze diagnostic only. The runner did not retain the promised known-zero A/A banks, construction-fixed effects, or sufficient N=80 samples.
15. **Variance reduction.** Six of eight variance-ratio point estimates are below 1, but no nondegenerate 95% interval excludes 1. Hold'em S3's exact zero is a collapsed-arm implementation artifact and must not be interpreted as perfect variance reduction.
16. **Costs.** Median pair acquisition time/storage are 0.006447 s/1,694 bytes for hold'em and 1.163642 s/29,009 bytes for Ising. The separate 50-run wrapper microbenchmark estimates logging-path overhead at 32.94% and 92.25%, respectively; it is not per-method runtime.
17. **Cross-system findings.** B7 detection/false suppression are 99.11%/0% in hold'em and 79.67%/29.13% in Ising. Method tradeoff ordering has Kendall tau-b 0.80829 across the two systems; this is an ordering descriptor, not a probability or utility.
18. **Manuscript PDF.** `HUMAN_PORTAL/FINAL_MANUSCRIPT_FOR_REVIEW.pdf` is a 10-page, 19-section review draft generated from machine-readable aggregates. It is labeled not ready and requires human authorship review.
19. **Public release path.** The assembled source/data/reproducibility package is `release/`; the portable archive is generated under `dist/` by the closeout workflow.
20. **DOI/archive status.** No DOI, OSF registration, or external archive upload was created. Human owner metadata and explicit upload authorization are required.
21. **Novelty audit.** The prospective novelty gate passed narrowly for the evaluation object. A manuscript-stage recheck found close work but no verified full overlap. This does not cure the empirical defects or make the paper submission-ready.
22. **Equation/statistical audit.** The Wilson interval implementation was corrected and tested against an independent implementation; the stale toy interval and a late-discovered protocol transcription were corrected under deviations D005 and D008. M4–M6 remain explicitly non-confirmatory or unavailable.
23. **Reference audit.** Current closest-work metadata was rechecked against canonical sources. Older or inaccessible full-text support remains flagged for human verification before any submission.
24. **Author-defense status.** `AUTHOR_DEFENSE_GUIDE.md` contains 20 adversarial questions and draft answers. All scientific, authorship, citation, and venue judgments still require named human signoff.
25. **Venue recommendation.** Do not submit now. After a new frozen repair and rerun, Simulation Modelling Practice and Theory is the first conditional target; APS Open Science is the strongest physics-led negative/null or methods alternative.
26. **Final go/no-go.** **NO-GO.** Repair the Branch-B implementation contradiction, Ising S4/S8, hold'em S3, and the missing M4–M6 acquisition contract; freeze the repaired protocol before acquiring new outcomes; rerun; independently audit; then repeat venue selection.

## Required human decision

The human owner must either (a) authorize and own a new frozen repair-and-rerun cycle, or (b) archive this package as a transparent negative validation record. Neither path authorizes submission of the current manuscript.
