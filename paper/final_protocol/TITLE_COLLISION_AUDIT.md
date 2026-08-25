# Title-collision audit

Audit date: 2026-08-24  
Sources admitted: publisher/proceedings records, arXiv, and OpenReview.  
Result: **freeze title B**.

Exact-title searches were run with quotation marks, followed by searches for the distinctive fragments `trace-based validation protocol`, `validating pairing assumptions`, `seed-matched evaluations`, `seed-matched agent evaluation`, and combinations with `black-box`, `agent`, `stochastic`, `trace`, and `common random numbers`. No exact authoritative record was found for A, B, or C. This is a dated bibliographic result, not a guarantee against an unindexed, private, or later work.

| Candidate | Exact collision | Near-collision assessment | Decision |
|---|---:|---|---|
| **A. _A Trace-Based Validation Protocol for Seed-Matched Evaluations of Black-Box Game-Playing Agents_** | None found | High avoidable confusion with Paduraru, Bouruc, and Stefanescu, _A Trace-Based Assurance Framework for Agentic AI Orchestration: Contracts, Testing, and Governance_ (ENASE 2026; DOI [10.5220/0014840300004015](https://doi.org/10.5220/0014840300004015)). Both lead with “A Trace-Based,” concern agent evaluation/assurance, and frame a trace-centered framework/protocol. | Do not freeze. |
| **B. _A Protocol for Validating Pairing Assumptions in Seed-Matched Evaluations of Black-Box Game-Playing Agents_** | None found | No near-exact authoritative title found. “Pairing assumptions” identifies the actual admission problem and separates the paper from trace-assurance and rollout-documentation work. Sharma's _When Does Pairing Seeds Reduce Variance?_ is a close topic, not a title collision. | **Preferred and bibliographically safe as of the audit date.** |
| **C. _Validating Pairing Assumptions in Seed-Matched Agent Evaluation_** | None found | No near-exact authoritative title found. It is concise and collision-resistant, but drops “protocol,” “black-box,” and “game-playing,” making the scope less explicit and more likely to read as a general validation claim. | Safe fallback, weaker scope signaling. |

## Frozen recommendation

**A Protocol for Validating Pairing Assumptions in Seed-Matched Evaluations of Black-Box Game-Playing Agents**

The recommendation is evidence-supported because it foregrounds the remaining contribution (validation of an assumed pairing), retains the black-box and game-playing limits, avoids implying that traces themselves are the novelty, and reduces confusion with the ENASE trace-assurance paper. It does not claim that the protocol proves a valid coupling in all systems.

Canonical near-neighbor records checked:

- <https://doi.org/10.5220/0014840300004015>
- <https://arxiv.org/abs/2603.18096>
- <https://arxiv.org/abs/2512.24145>
- <https://arxiv.org/abs/2603.11084>
- <https://arxiv.org/abs/2605.12131>
- <https://arxiv.org/abs/2607.16345>

If a title search is rerun after the audit date and a new authoritative collision appears, fail closed and re-evaluate B before submission.
