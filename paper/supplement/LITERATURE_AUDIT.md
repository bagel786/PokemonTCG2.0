# Literature audit

This bibliography audit was completed on 2026-08-23. Metadata were checked against publisher or proceedings records; DOI-bearing records were also checked against the DOI registry. The links below point to the primary publication record rather than a secondary citation index. The “use” notes delimit what each source can support in this manuscript.

| BibTeX key | Primary verification record | Supported contextual use |
|---|---|---|
| `moravcik2017deepstack` | [Science DOI record](https://www.science.org/doi/10.1126/science.aam6960); DOI `10.1126/science.aam6960` | Prior work on expert-level decision making in heads-up imperfect-information poker. It does not validate this paper's game engine, policy, or empirical results. |
| `brown2019pluribus` | [Science DOI record](https://www.science.org/doi/10.1126/science.aay2400); DOI `10.1126/science.aay2400` | Prior work on superhuman decision making in multiplayer imperfect-information poker. It supplies broad game-playing context only. |
| `ross2011dagger` | [PMLR article record](https://proceedings.mlr.press/v15/ross11a.html) | Motivation for sequential imitation-learning methods that address learner-induced distribution shift. It is not evidence that the training procedure in this paper is DAgger or inherits DAgger guarantees. |
| `laroche2019spibb` | [PMLR article record](https://proceedings.mlr.press/v97/laroche19a.html) | Context for conservative offline policy improvement that retains a baseline in uncertain regions. It does not establish a safety guarantee for this paper's update. |
| `zaheer2017deepsets` | [NeurIPS proceedings record](https://proceedings.neurips.cc/paper/2017/hash/f22e4747da1aa27e363d86d40ff442fe-Abstract.html) | Context for permutation-invariant models over sets and for representation designs that preserve item identity. It is not an evaluation of this paper's representation. |
| `huang2022invalidmasking` | [FLAIRS proceedings record](https://journals.flvc.org/FLAIRS/article/view/130584); DOI `10.32473/flairs.v35i.130584` | Theory and empirical context for masking invalid actions in policy-gradient algorithms. It supports discussion of legal-action masking, not claims about identity aliasing or the efficacy of this paper's policy. |
| `agarwal2021statistical` | [NeurIPS proceedings record](https://proceedings.neurips.cc/paper_files/paper/2021/hash/f514cec81cb148559cf475e7426eed5e-Abstract.html) | Motivation for reporting uncertainty and robust aggregate evaluation in reinforcement learning. It does not prescribe this paper's paired estimator or establish its coverage. |
| `glasserman1992crn` | [INFORMS article record](https://pubsonline.informs.org/doi/10.1287/mnsc.38.6.884); DOI `10.1287/mnsc.38.6.884` | Statistical context for common-random-number comparisons and the conditions under which they can reduce variance. It does not by itself prove variance reduction for this implementation. |
| `field2007clustered` | [JRSS B article record](https://academic.oup.com/jrsssb/article-abstract/69/3/369/7109361); DOI `10.1111/j.1467-9868.2007.00593.x` | General justification for resampling at the cluster level when observations within clusters are dependent. The manuscript must still define and justify its own clustering unit. |
| `pineau2021reproducibility` | [JMLR article record](https://jmlr.org/papers/v22/20-303.html) | Context for reproducibility checklists, code release, and transparent empirical reporting. It is not an independent reproduction of this work. |
| `gebru2021datasheets` | [ACM article record](https://dl.acm.org/doi/10.1145/3458723); DOI `10.1145/3458723` | Context for documenting dataset motivation, composition, collection, uses, distribution, and maintenance. It does not certify that this paper's data package is complete. |

## Metadata caveats

- The PMLR, NeurIPS, and JMLR primary records above do not publish article DOIs; none were added.
- The official NeurIPS BibTeX record for *Deep Sets* leaves the page field empty, so this bibliography also omits pages rather than substituting a value from a secondary index.
- The FLAIRS primary record has volume 35 but no conventional page range in its DOI metadata; no page or article number was inferred.
- Accented author names are encoded in LaTeX in `references.bib`. PMLR's citation exports render several given names without accents; the keys and publication identities are unaffected.
