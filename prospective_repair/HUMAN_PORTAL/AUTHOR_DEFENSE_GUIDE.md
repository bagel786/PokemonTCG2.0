# AUTHOR DEFENSE GUIDE — 20 adversarial questions (repair campaign)

1. **Why isn't this the old cumulative checklist again?** Branches A–E are
   independent claim classes; B never consumes C/D/E unless its declared model
   does (`framework/classifier.py`, tests `test_branch_b_independence.py`).
2. **What's genuinely new?** Only the evaluation object: claim-classed,
   planted-truth benchmark with false-suppression/abstention/cost accounting.
   CRN theory, streams, event-keying, replay are cited, not claimed.
3. **Isn't Sabot the same thing?** It plants faults in LLM agent pipelines and
   scores their own checks; it has no seed-matched inference semantics, no B–E
   branches, no replay/CRN/event distinction, no cross-domain simulation arm.
4. **How are labels known?** Mechanically derived from mechanism composition
   rules (FAULT_GRAMMAR TRUTH_RULES); implementation-labeled mismatch was
   itself a V1 defect we refuse to repeat.
5. **Why trust the wrappers?** Mechanics-presence gates (pilot 304/304, dev
   228/228) plus unit/integration tests down to draw-count proof that the
   Ising sampler really consumes keyed RNGs.
6. **What did "development vs confirmation" change?** All V1 outcomes became
   regression targets only; confirmation uses fresh disjoint banks post-push.
7. **Shared seed alone insufficient for pairing?** Demonstrated:
   `test_shared_seed_alone_without_paired_design_suppresses_pairing`.
8. **Doesn't exact replay underpin all paired claims?** No — G07/G11 show
   timing-corrupted contexts while paired estimates remain valid; the trap is
   scored so suppression of those VALID cells costs you.
9. **What exactly is false suppression here?** DOWNGRADE/SUPPRESS on cells
   whose construction says the claim, as worded, is sound; abstention excluded.
10. **Pseudoreplication handling?** Unit must be cluster-respecting (G12
    detects decision-unit deception); case-level aggregation prevents seed
    inflation from masquerading as independent failures.
11. **Why sign-flip permutation instead of z-tests?** Methods score identical
    matched cells ⇒ dependence; independent-proportion z-tests were V1's own
    audited flaw and are now schema-forbidden.
12. **CRN benefit interval honesty?** Joint seed-cluster bootstrap; zero-variance
    rows flagged DEGENERATE_NOT_BENEFIT (G19 regression).
13. **Costs measured how?** Dedicated bank, randomized orderings, per-method
    marginal acquisition counts + wall/CPU/bytes medians+p95+spread.
14. **Could thresholds be gamed for B7?** Gates fixed pre-outcomes in frozen
    file; dominance check includes coverage & cost axes; if a simpler method
    wins, that IS the reported conclusion.
15. **Worst limitation?** Author overlap: benchmark author = framework author.
    Mitigations: holdout separation, mechanical truth rules, mutation tests,
    independent reaggregation — but not elimination; stated plainly in §8.
16. **AI role?** Everything logged; you cannot claim human-only origination;
    disclosure file requires your signature to that effect.
17. **Two systems enough?** No — transferability is bounded; that's why strong
    cross-system ranking claims were dropped.
18. **Why keep M4–M6 out?** They need dedicated known-truth banks; running
    them off reused outcomes would repeat V1's unlabeled-proxy mistake.
19. **Public preregistration?** No — private-remote timestamped freeze; any
    public claim waits for an authorized deposit.
20. **If B5 dominates B7 what do I say?** Exactly that, prominently; the paper
    evaluates strategies, it doesn't sell one.
