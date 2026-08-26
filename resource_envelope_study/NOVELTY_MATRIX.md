# Claim-by-claim novelty and collision matrix

Status: **primary sources inspected; seven-paper starting set, not exhaustive**.

`D` means direct/strong prior art, `P` partial or conceptual overlap, and `—`
not studied in the inspected paper.

| Source | Same-deadline resources → work | Work/resources → behavior | Outcome/rank sensitivity | Lifecycle | Matched fixed-work attenuation | Paired/cluster design | Exact combined factorial |
|---|---:|---:|---:|---:|---:|---:|---:|
| Nelson 2016 | P | P | P | — | P | P | — |
| Pérez-Liébana et al. 2019 | P | P | P | — | P | P | — |
| Patterson et al. 2024 | — | — | — | — | P | D | — |
| Mytkowicz et al. 2009 | P | — | D | — | — | D | — |
| Georges et al. 2007 | P | — | D | D | — | D | — |
| Barrett et al. 2017 | P | — | P | D | — | D | — |
| Kalibera and Jones 2013 | P | — | D | D | — | D | — |

## Strongest collision

Nelson explicitly replaced wall-clock limits with MCTS iteration caps because
millisecond limits are comparable only when hardware, system load, and related
conditions are held constant. The paper also shows that compute budget changes
win rate and qualitative failure mode. Therefore this study does **not** claim
novelty for time-versus-fixed-work, resource dependence in principle, fixed-work
reproducibility as an idea, or compute-dependent gameplay.

The plausibly distinct object in this starting set is the combined assigned
CPU-contention × bounded-process-lifecycle × stopping-mode design, linked from
completed work to paired same-state semantic action divergence and game score,
with separately calibrated fixed work used to estimate attenuation. This is a
defensible study target, not a priority claim.

## Source-specific scope

### Nelson 2016

Mark J. Nelson, “Investigating Vanilla MCTS Scaling on the GVG-AI Game Corpus,”
*CIG 2016*. [DOI](https://doi.org/10.1109/CIG.2016.7860443),
[institutional record](https://repository.falmouth.ac.uk/2302/),
[accepted paper](https://repository.falmouth.ac.uk/2302/1/MCTSScaling_CIG16.pdf).

Inspected study: fixed iteration counts 1–1024 for vanilla MCTS across 62 public
GVG-AI games, with bootstrap intervals. It directly motivates iteration limits
for reproducibility, notes that time limits require identical hardware/load,
and finds budget-dependent win and timeout/loss behavior. It does not assign
CPU contention, manipulate lifecycle, compare matched time/work effects, or
measure paired same-state actions.

### Pérez-Liébana et al. 2019

Diego Pérez-Liébana et al., “General Video Game AI: A Multitrack Framework for
Evaluating Agents, Games, and Content Generation Algorithms,” *IEEE Transactions
on Games* 11(3), 2019. [DOI](https://doi.org/10.1109/TG.2019.2901021),
[author project](https://diego-perez.net/projects/gvgai/),
[author paper](https://diego-perez.net/assets/pdf/papers/GVGAI_Survey.pdf).

Inspected study: survey/framework history documenting the 40 ms tick budget,
timeout penalties, forward-model-call caps, action/value telemetry, and rank
sensitivity in GVGAI work. It is not a controlled contention/lifecycle
experiment and does not estimate fixed-work attenuation.

### Patterson et al. 2024

Andrew Patterson, Samuel Neumann, Martha White, and Adam White, “Empirical
Design in Reinforcement Learning,” *JMLR* 25(318), 2024.
[Official article](https://jmlr.org/papers/v25/23-0183.html),
[version of record](https://jmlr.org/papers/volume25/23-0183/23-0183.pdf).

Inspected study: empirical-design guidance on estimands, fully specified agents,
paired differences, separate RNGs, baselines, bootstrap intervals, failures,
and sufficient independent runs. It does not study hardware/resource envelopes,
but its design principles directly constrain this protocol.

### Mytkowicz et al. 2009

Todd Mytkowicz, Amer Diwan, Matthias Hauswirth, and Peter F. Sweeney,
“Producing Wrong Data Without Doing Anything Obviously Wrong!,” *ASPLOS 2009*.
[DOI](https://doi.org/10.1145/1508244.1508275),
[IBM Research record](https://research.ibm.com/publications/producing-wrong-data-without-doing-anything-obviously-wrong).

Inspected study: ostensibly irrelevant environment size and link order altered
SPEC performance and could reverse an apparent optimization effect. It is
direct prior art for environment-conditioned effect magnitude/sign, setup
randomization, and causal intervention—not for bounded search actions or matched
fixed-work attenuation.

### Georges et al. 2007

Andy Georges, Dries Buytaert, and Lieven Eeckhout, “Statistically Rigorous Java
Performance Evaluation,” *OOPSLA 2007*.
[DOI](https://doi.org/10.1145/1297027.1297033),
[institutional paper](https://users.elis.ugent.be/~leeckhou/papers/oopsla07-stat.pdf).

Inspected study: multiple VM invocations and in-process iterations under JIT,
GC, scheduling, and system variation, with interval/ANOVA guidance. Process
invocation as a higher independent level and lifecycle-dependent conclusions
are direct prior art. Lifecycle is not crossed with assigned contention and
search stop mode.

### Barrett et al. 2017

Edd Barrett et al., “Virtual Machine Warmup Blows Hot and Cold,” *PACMPL*
1(OOPSLA), Article 52, 2017.
[DOI](https://doi.org/10.1145/3133876),
[author full text](https://soft-dev.org/pubs/html/barrett_bolz-tereick_killick_mount_tratt__virtual_machine_warmup_blows_hot_and_cold_v6/).

Inspected study: 2,000 in-process iterations in 30 fresh executions across
systems, with tightly controlled machine state and changepoint classification.
It shows that persistent execution is not synonymous with a stable peak state.
External load was controlled away, not assigned; there is no search/action or
fixed-work attenuation study.

### Kalibera and Jones 2013

Tomas Kalibera and Richard E. Jones, “Rigorous Benchmarking in Reasonable Time,”
*ISMM 2013*. [DOI](https://doi.org/10.1145/2464157.2464160),
[Kent record](https://kar.kent.ac.uk/33611/),
[corrected institutional paper](https://kar.kent.ac.uk/33611/45/p63-kaliber.pdf).

Inspected study: hierarchical repetition at iteration, execution, and build
levels; pilot dimensioning; cost-aware allocation; and effect-size intervals.
It directly requires repetition at the highest random level and warns that
lower-level rows cannot replace independent process/batch units. It does not
study search policies or assigned load.

## Defensible contribution wording

> On a specified platform, under pre-specified CPU-contention interventions and
> bounded process-lifecycle regimes, otherwise matched wall-clock-limited search
> executions differed in completed work and, in some settings, selected actions
> and game performance. A separately calibrated fixed-work condition quantified
> how much this sensitivity was reduced when completed work was held
> approximately constant.

Use “reduced,” “attenuated,” or “consistent with completed-work differences.”
Do not use “mediated” or universal fairness/reproducibility language.

## Access/version caveats

IEEE/ACM automated access was intermittently blocked, so DOI/official metadata
was cross-checked with author or institutional full text. Nelson and
Pérez-Liébana were read from author/institutional copies. Mytkowicz details were
read from a complete paper copy cross-checked against IBM/DOI metadata. Barrett
was read from the author-rendered full version. Kent labels its Kalibera–Jones
copy corrected/updated; formula-level use must disclose that basis. Patterson
was read from the official JMLR version of record.
