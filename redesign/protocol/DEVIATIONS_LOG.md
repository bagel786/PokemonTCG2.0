# Deviations Log

## D001 — Analysis implementation repair

- **Date:** 2026-08-26
- **Stage:** P13, before any aggregate was produced
- **Trigger:** The prospectively written `analysis/analyze.py` raised a `TypeError`
  while sorting decision-metric cells because a dead sentinel entry used a string
  key among tuple keys.
- **Correction:** Removed the unused sentinel and two other unused local
  assignments. No row selection, estimand, threshold, uncertainty procedure, or
  reporting rule changed.
- **Outcome access:** The failure occurred after JSONL parsing but before metric
  aggregation. No aggregate result was emitted or inspected.
- **Scope:** Software-only repair required to execute frozen Analysis Plan §A.
- **Integrity consequence:** Preserve the original failure in the command log;
  independently reaggregate all headline counts from raw rows.

## D002 — Wilson implementation repair

- **Date:** 2026-08-26
- **Stage:** P13, before any aggregate was produced
- **Trigger:** After D001, the prewritten Wilson helper raised a domain error.
  Inspection showed that its half-width divided by `(n + z²)` even though the
  frozen equation requires division by `(1 + z²/n)`.
- **Correction:** Implemented the exact formula frozen in
  `STATISTICAL_DESIGN.md` §1 and added an invariant requiring `0 ≤ x ≤ n`.
- **Outcome access:** No aggregate result was emitted or inspected.
- **Scope:** Equation implementation repair; no estimand, input, threshold, or
  reporting rule changed.
- **Integrity consequence:** Check the fixture x=38, n=40 independently and list
  the implementation in `EQUATION_AUDIT.md`.

## D003 — M3 numerator/denominator repair

- **Date:** 2026-08-26
- **Stage:** P13, before any aggregate was produced
- **Trigger:** The new Wilson invariant exposed `x=227, n=80`. The prewritten
  code pooled missed `DOWNGRADE` cases into the numerator for hard `INVALID`
  cases but used only hard-invalid cases in the denominator.
- **Correction:** Separated `downgrade_missed` from hard-invalid `missed` and
  emitted each denominator explicitly. This implements the frozen distinction
  between hard missed failures and caveat-blind/downgrade behavior.
- **Outcome access:** The exception exposed only the invalid count pair; no
  aggregate file or comparative result was produced.
- **Scope:** Denominator correctness; no classification, threshold, or scenario
  label changed.
- **Integrity consequence:** Validate every aggregate numerator is bounded by
  its stated denominator and independently reproduce cell counts from JSONL.

## D004 — Missing confirmatory statistical banks and method-cost fields

- **Date:** 2026-08-26
- **Stage:** P13, after the repaired frozen script emitted its first aggregates
- **Trigger:** Output-coverage audit against `ANALYSIS_PLAN.md` found that the
  runner retained neither the promised holdem mirror/equal-temperature A/A
  banks nor S8 repeat outcomes. It also retained no per-method time or evidence-
  bundle byte fields. The frozen script substituted a centered sign-flip proxy
  without marking that loss of estimability.
- **Correction:** No missing outcomes are reconstructed or reacquired. M4 and M5
  are marked `NOT_ESTIMABLE_AS_PREDECLARED`; M6 is diagnostic-only; M9 and M10
  are marked partial/not estimable as applicable. Centered/bootstrap analyses
  are emitted only as `POST_FREEZE_DIAGNOSTIC_NOT_CONFIRMATORY`. The manuscript
  may not call those results calibration, confirmatory Type-I error, or
  confirmatory power.
- **Outcome access:** Branch-B headline aggregates had been inspected before
  this gap was identified. No thresholds, labels, methods, or reporting gates
  were changed in response.
- **Scope:** Reporting and estimability correction; no replacement outcome run
  is authorized because doing so after result inspection would compromise the
  frozen campaign.
- **Integrity consequence:** This gap blocks `FULL_EMPIRICAL_METHODS_PAPER_READY`
  and must appear in the abstract, limitations, claim ledger, and handoff.

## D005 — Wilson toy-example correction

- **Date:** 2026-08-26
- **Stage:** P13 equation-fixture audit
- **Trigger:** Independent evaluation of the frozen Wilson equation for x=38,
  n=40 gives [0.835, 0.986], not the prose fixture [0.840, 0.988].
- **Correction:** Corrected only the toy numbers; the frozen equation, confidence
  level, production implementation, estimand, and all data-derived intervals are
  unchanged.
- **Outcome access:** Unrelated to study outcomes.
- **Integrity consequence:** Production and independent fixture must agree to
  at least 1e-6 for every reported interval.

## D006 — Quarantine of prospectively written unlabeled proxy output

- **Date:** 2026-08-26
- **Stage:** Release assembly
- **Trigger:** The repaired `analyze.py` emitted `typeI_power.json` using centered
  sign-flip behavior without the absent A/A banks and without a diagnostic-only
  status field.
- **Correction:** Renamed the file
  `typeI_power_SUPERSEDED_UNLABELED_PROXY.json` and excluded it from the public
  release. The transparent replacement is `statistical_diagnostics.json`, whose
  rows are labeled `POST_FREEZE_DIAGNOSTIC_NOT_CONFIRMATORY`.
- **Outcome access:** The unlabeled proxy had been generated before the missing-
  bank audit; no confirmatory prose uses it.
- **Integrity consequence:** Release and manuscript scans must reject any
  unqualified Type-I, coverage, or power claim.

## D007 — RLCard license-label correction

- **Date:** 2026-08-26
- **Stage:** P16 release rights audit
- **Trigger:** The installed `rlcard==1.2.0` distribution contains an MIT license
  file, while the frozen system manifest incorrectly labeled RLCard Apache-2.0.
- **Correction:** Corrected the manifest, protocol annotation, selection matrix,
  notices, system card, systems table source, and manuscript to MIT. Preserved a
  verbatim copy of the installed license in `release/LICENSES/RLCARD_MIT.md`.
- **Outcome access:** License metadata is unrelated to acquired outcomes.
- **Scope:** Rights/provenance metadata only; system version, code, seeds, and
  analyses are unchanged. MIT remains compatible with this release's MIT terms.
- **Integrity consequence:** Rights audit must compare notice labels with actual
  copied license texts, not only package metadata or an earlier selection sheet.

## D008 — Wilson protocol-equation transcription correction

- **Date:** 2026-08-26
- **Stage:** P21 final equation audit, after outcomes and manuscript generation
- **Trigger:** A final side-by-side review found that `STATISTICAL_DESIGN.md`
  still divided the Wilson half-width by `(n + z²)`. The production code,
  independent fixture, `EQUATION_AUDIT.md`, and corrected toy interval all used
  the standard denominator `q = 1 + z²/n`. D002 had incorrectly described the
  protocol transcription as already correct.
- **Correction:** Rewrote the protocol equation in explicit `q` form. No code,
  inputs, estimand, thresholds, counts, intervals, figures, or conclusions
  changed.
- **Outcome access:** Final results had been inspected. This is therefore logged
  as a post-outcome protocol-document correction, not silently folded into the
  freeze record.
- **Scope:** Equation transcription and audit-trail accuracy only.
- **Integrity consequence:** The release must bind this deviations log, the
  corrected design document, the two implementations, and the independent
  fixture in its manifest.
