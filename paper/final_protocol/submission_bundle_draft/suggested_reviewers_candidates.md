# Suggested reviewer candidates

**Status: CANDIDATES ONLY — not approved, not contacted.** The human author
must select from (or decline all of) these, verify no conflicts from their own
knowledge, and record the selection in `human_answers.yaml`
(`suggested_reviewers.approved_candidates`). Emails are included only where
they appear verbatim on an official institutional page fetched 2026-08-25;
otherwise they are marked EMAIL_UNVERIFIED and must not be used.

---

## 1. Barry L. Nelson — simulation methodology / common random numbers

- Institution: Walter P. Murphy Professor Emeritus, Industrial Engineering & Management Sciences, Northwestern University.
- Email: nelsonb@northwestern.edu (verbatim on official McCormick profile).
- Expertise: design/analysis of simulation experiments; variance reduction; CRN validity; ranking-and-selection inference; input-model risk.
- Relevance-establishing paper: Nelson & Matejcik, "Using Common Random Numbers for Indifference-Zone Selection and Multiple Comparisons in Simulation," Management Science 41(12), 1995.
- Why appropriate: the paper's core question — when same-seed runs may support paired comparisons — is exactly CRN validity analysis; he can judge the boundary-seed and admission machinery.
- Conflict screen: no Kaggle involvement found; no recent co-authorship with other candidates (disclosed: a >15-year-old WSC panel co-authorship with candidate 2). Human must confirm.

## 2. Pierre L'Ecuyer — random-number generation / streams

- Institution: Professeur associé/honoraire, DIRO, Université de Montréal.
- Email: pierre.l.ecuyer@umontreal.ca (verbatim on official UdeM directory page).
- Expertise: RNG streams/substreams, parallel reproducible stochastic simulation, quasi-Monte Carlo.
- Relevance-establishing paper: L'Ecuyer et al., "An Object-Oriented Random-Number Package with Many Long Streams and Substreams," Operations Research 50(6), 2002 (cited in the manuscript).
- Why appropriate: directly evaluates the stochastic-source audit and stream-level assumptions behind boundary-seed evidence.
- Conflict screen: cited author (prior art), but not a competing protocol paper; human confirms.

## 3. Philip S. Thomas — RL evaluation with statistical guarantees

- Institution: Associate Professor, Manning College of Information & Computer Sciences, UMass Amherst.
- Email: EMAIL_UNVERIFIED (obfuscated on official page).
- Expertise: high-confidence off-policy evaluation; Seldonian algorithms; statistical safety guarantees for learned behavior.
- Relevance-establishing paper: Thomas et al., "Preventing undesirable behavior of intelligent machines," Science 366(6468), 2019.
- Why appropriate: fail-closed claim admission mirrors his guarantee-first evaluation philosophy; strong referee for admissibility logic.
- Conflict screen: none found; human confirms.

## 4. Julian Togelius — game-agent benchmarking methodology

- Institution: Professor, Computer Science & Engineering, NYU Tandon; Director, NYU Game Innovation Lab.
- Email: EMAIL_UNVERIFIED (obfuscated on official page).
- Expertise: game-playing AI benchmarks, generalization of game agents, procedural generation.
- Relevance-establishing paper: Yannakakis & Togelius, Artificial Intelligence and Games, Springer 2018; plus his 2026 perspective on evaluating agents on unseen games.
- Why appropriate: best placed to judge whether the restricted-engine case study generalizes as claimed and where seed/engine-specific overclaims arise.
- Conflict screen: industry roles (modl.ai, Unity AI Council) should be disclosed to editors; runs non-Kaggle competitions; human confirms.

## 5. Tsong Yueh Chen — software testing / metamorphic testing

- Institution: Professor of Software Engineering, Swinburne University of Technology.
- Email: EMAIL_UNVERIFIED (institutional profile JS-gated at check time).
- Expertise: metamorphic testing, oracle problem, adaptive random testing.
- Relevance-establishing paper: Chen et al., "Metamorphic Testing: A Review of Challenges and Opportunities," ACM Computing Surveys 51(1), 2018.
- Why appropriate: the protocol's schedule-parity/trace-invariant checks function as oracle-free metamorphic relations; he can assess their sufficiency.
- Conflict screen: none found; human confirms.

---

## Screen notes applying to all five

- None is an author of the five closest works (Rollout Cards, Trace Assurance, AEVAL, event-keyed CRN, paired noise-floor) except L'Ecuyer's classic streams paper, which is prior-art infrastructure rather than a competing protocol.
- No involvement found with the Kaggle competition underlying the case study (light web screen only — human verifies).
- Nobody here is mentioned in the acknowledgments or has any known personal relationship to the author (author confirms).
