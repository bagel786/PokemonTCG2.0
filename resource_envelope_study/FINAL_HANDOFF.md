# Research checkpoint handoff

## Current decision

`STOP_BEFORE_AZURE` — implementation checkpoint only.

No Azure pilot or final acquisition was run, no scientific outcomes were
generated, and the Azure VM was left deallocated. `FREEZE_MANIFEST.json` is
still `NOT_FROZEN`, so final acquisition remains forbidden.

## Completed at this checkpoint

- Work is isolated on `paper/resource-envelope-search-20260826` from exact base
  `af1504c149d462c152eec18472661a844b58988a`; production search/submission code
  is untouched.
- Deterministic full-game, frozen-state, instrumentation, and open Ising study
  paths are implemented with immutable manifests, exact row/result binding,
  versioned schemas, atomic commits, and fail-closed resume validation.
- Worker and co-runner cleanup uses tested terminate-then-hard-kill escalation.
  Scientific child targets arm Linux parent-death `SIGKILL` protection.
- Completed halves of paired load batches are written as crash-durable period
  journals; an orphan journal forbids in-place continuation.
- The freeze inventory binds each top-level digest to a unique logical role and
  repository path, confines expected outputs below the study run directory,
  and requires structured post-freeze approval metadata.
- The locked analysis path defines exactly ten confirmatory estimands, uses a
  common resampling hierarchy and 99.5% family members, independently
  reaggregates every point/count, and permits plots only from the frozen
  summary.
- The current score-only power simulation explicitly cannot authorize the
  ten-endpoint family (`NARROW_OR_EXTEND`).
- Local verification at handoff: **161 passed, 2 skipped**. The skips are the
  expected Linux-only parent-death integration tests on macOS. All Python files
  compile and all JSON schemas meta-validate.

## Blocking items before any Azure pilot

1. Integrate the new one-shot `run_lease.py` authorization/host/output/time/
   worker-budget contract and bounded signal-cleanup registry at the outer edge
   of every scientific executor. The primitives and adversarial tests exist,
   but this wiring is intentionally incomplete at this stopping checkpoint.
2. Harden Ising authorization to exact JSON types and finite numbers, and
   recheck expiration before every batch, period, instrumentation pair, and
   diagnostic panel.
3. Complete the temporal Git approval proof: the protocol commit must strictly
   precede a mandatory tracked human attestation/approval commit, the current
   commit must strictly descend from both, and the upstream must be a remote-
   tracking branch at the exact pushed commit.
4. Close the state-panel resume gaps: reconcile episode status/test mode with
   the scientific commit/runtime, bind resource-profile hashes to scheduled
   periods, and fully revalidate warmup plus worker/episode evidence on resume.
5. Reject untracked and executable ignored inputs in final clean-tree checks,
   enforce exact base/fork ancestry, and require Azure at direct scientific API
   entry points as well as CLIs.
6. Run a bounded native Azure instrumentation/calibration pilot and freeze a
   joint endpoint power design. The present power result deliberately blocks a
   full-family GO decision.

Any failure in these gates means stop, preserve the evidence, deallocate Azure,
and use newly frozen reserve IDs rather than repairing or replacing outcomes in
place.
