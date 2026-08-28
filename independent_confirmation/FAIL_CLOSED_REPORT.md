# Fail-closed report

Final status: `NOT_READY_NOVELTY_FAILURE`

This is a complete stop record, not a completed confirmatory study and not a manuscript package. The mandatory novelty gate failed before implementation, a new prospective freeze, confirmatory acquisition, statistical analysis, venue selection, or manuscript generation. Continuing those phases would spend resources on a circular benchmark without a defensible central scientific contribution.

## Repository and lineage

- Private repository: `bagel786/PokemonTCG2.0`
- New branch: `paper/claim-specific-independent-confirmation-20260828`
- Exact starting SHA: `91ad7fa9571ee0ca10200fd7fe7b589589e8b794`
- Prior branch and remote tip at audit: `paper/claim-specific-prospective-repair-20260827` at the same SHA
- Divergence from the supplied audited SHA: 0 ahead and 0 behind
- Initial directory supplied to the agent: a different repository, inspected read-only and left untouched
- One unrelated untracked file in the original target worktree: preserved untouched with its path, byte count, and SHA-256 in `REPOSITORY_AUDIT.json`

The prior campaign remains under `prospective_repair/`. New records are under `independent_confirmation/` because overwriting the old campaign directory would violate the instruction to preserve the failed prospective campaign. A tree comparison against the branch base is part of `verify_stop_record.py`.

## Preserved failed campaign

- Recorded status: `NOT_READY_DO_NOT_SUBMIT`
- Freeze-input SHA: `cfeef395ed708ef640ff8e7322b8f2e1ec7550cb`
- Freeze-record commit and peeled tag target: `2bf3cea7a8a31b8e06dda814200ae83c20a163a0`
- Annotated tag: `claim-specific-prospective-repair-freeze-20260827`
- Tag-object SHA: `cb88ce6f27739bc71c2aa434e9c3a5d602bd2de3`
- Frozen path/hash checks: 27 of 27 matched
- Preserved raw holdout: 125,600 rows; uncompressed SHA-256 `792b6fd0a830c0c1b357becb0e7be661a8ceb9147b3a6ec2faadf604c5e447b1`
- Preserved cost bank: 4,800 rows; uncompressed SHA-256 `17c1f296bf6821ea5638109e329e0122f6e40fc3528c04f56935c9fb4a2e8237`

The freeze was a private Git-timestamped record, not a public preregistration. D-R1, D-R2, the unsuccessful results, machine gates, old manuscript, raw archives, and post-outcome integrity failures remain intact. They are not repaired, reinterpreted as a clean negative result, or reused as new confirmatory evidence.

## Defect disposition

`DEFECT_LEDGER.csv` registers all 55 defects: 41 supplied by the takeover brief, five D-R2 deviations, one primary-audit contradiction, and eight additional failures found by a clean-context inventory and independently verified by the primary auditor. Fifty-one are `PRESERVED_OPEN_IN_FAILED_CAMPAIGN`; four are `PRESERVED_INTEGRITY_FAILURE`. No repair or regression test was attempted because the novelty gate precedes implementation. For the four post-outcome/freeze-invalidating defects, retroactive repair is expressly forbidden.

The additional integrity findings include a material post-outcome rewrite of frozen `analysis/analyze.py`, omission of the central evidence-bundle builder from freeze coverage, a post-outcome gate generator, a claimed but absent conclusion-change output, a no-op schema assertion, a protocol/final construction-count conflict, a weak preservation test, and manuscript-label truncation. The CSV is the authoritative one-row-per-defect account of consequence, repair disposition, regression-test status, repair commit, and outcome-exposure timing.

## Novelty decision

Thirteen primary or official sources were inspected at the relevant sections or pages. The source ledger resolves the exact works behind Sabot, the older ASMR-Bench label, MLE-Sabotage, and entrapment-FDR.

No central contribution survived:

- computational replay, scientific correctness, purpose-specific validation, ordinary statistical pairing, CRN construction and efficiency, and event alignment are established distinctions;
- criterion-specific comparisons of rigor-checking tools already address applicability, differing operational definitions, combinations, runtime, and cost;
- planted or known-false cases already benchmark auditors and validators in ML codebases, agent pipelines, proteomics, and scientific software;
- the proposed router is a deterministic encoding of the evidence contract, while G01-G19 and the planned synthetic replacements derive truth from that same contract;
- AI role separation changes the construction process but does not create an independent truth source;
- the only surviving difference is application to paired stochastic-evaluation claims, which the takeover brief identifies as insufficient.

The one permitted narrow reframe—an externally sourced software-quality corpus with blind independent or human adjudication—was considered. The repository contains no such corpus. Creating more rule-derived synthetic fixtures would preserve the circularity, while the benchmark architecture itself is prior art. The exact surviving contribution is therefore `NONE`.

## Confirmatory design and results

No new claim semantics, router, baseline, fault bank, truth bank, seed bank, estimand, statistical plan, cost design, CRN-benefit design, acquisition guard, environment lock, freeze record, or freeze tag was created. Confirmatory constructions: 0. Confirmatory rows: 0. New outcomes created or viewed: no. Primary results, intervals, p-values, negative results, costs, and CRN findings: `NOT_APPLICABLE` because the campaign stopped before acquisition.

The prior exposed outcomes are preserved only as failed-campaign records. They are not reported as findings of this campaign.

## Readiness gates

| Gate | Result | Basis |
| --- | --- | --- |
| Repository lineage | PASS | Local/remote/base/tag/raw identities resolved |
| Failed-campaign preservation | PASS | Old tree unchanged from the branch base |
| Novelty | FAIL | No contribution survives the documented kill conditions |
| Independence/separation | NOT_REACHED | No confirmatory corpus was built |
| New-campaign integrity | NOT_REACHED | No freeze or outcome-bearing run occurred |
| Statistical | NOT_REACHED | No design or data were authorized |
| Reproduction | PASS_STOP_RECORD_ONLY | Machine checks and clean-checkout report cover only the stop record |
| Manuscript | NOT_REACHED | Generating a research manuscript after novelty failure would misstate readiness |
| Venue and ethics | NOT_REACHED | No contribution exists to route to a venue |

No venue or backup was selected. Fees, official timing metrics, AI policy, and submission requirements were not audited because the venue phase was not reached. No manuscript, figures, cover letter, submission-form content, or figure-review PDF was created. `HUMAN_PORTAL/FIGURE_REVIEW_NOT_APPLICABLE.md` records why a placeholder PDF would be misleading.

## Reproduction and accountability

Run `python independent_confirmation/verify_stop_record.py` from the repository root. It validates the status, literature and defect ledgers, preserved raw archives, tag identity, absence of new outcomes/freezes, blank human checkboxes, and the unchanged failed-campaign tree. `CLEAN_REPRODUCTION.md` records execution in a clean detached worktree after the final package is committed.

AI use is fully described in `AI_USE_LOG.md`. The hostile-novelty subagent produced no usable report; no finding from it was accepted. The primary agent directly verified every source used in the novelty verdict. These activities are AI-assisted audit work, not independent peer review or human scientific verification.

## External-action confirmation

No journal submission or submission portal was accessed. No editor or reviewer was contacted. No registry entry, DOI, public release, public repository conversion, external upload, fee payment, open-access purchase, or publishing-term acceptance occurred. The only authorized external write was pushing the audit branch to the existing private origin.

The remaining human work is limited to checking this stop record and deciding whether to end the publication plan or authorize a materially different future project. The human portal leaves every approval and checklist item blank.
