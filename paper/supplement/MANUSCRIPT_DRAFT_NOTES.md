# Manuscript draft notes

Working title: **Representation Repair under Distribution Shift in a Partially Observable Card Game**

These notes are source-grounded prose for adaptation into `paper/main.tex`. They are not an independent numerical source. Every placeholder below must resolve through generated `results.tex` macros backed by the claim ledger. A sentence must be removed if its macro is unavailable or its claim is not `VERIFIED` or `VERIFIED_WITH_CAVEAT`.

## Suggested macro vocabulary

Use generated macros rather than transcribing numerical results into the manuscript:

- Fresh confirmation: `\FreshPairs`, `\FreshCandidateWins`, `\FreshControlWins`, `\FreshEffectPP`, `\FreshCILowPP`, `\FreshCIHighPP`, `\FreshCandidateOnly`, `\FreshControlOnly`, `\FreshMcNemarP`, `\FreshFirstEffectPP`, `\FreshSecondEffectPP`, `\FreshGrimEffectPP`, and `\FreshOtherEffectPP`.
- Representation audit: `\CorpusDecisions`, `\OrdinaryPlayOptions`, `\UnresolvedPlayOptions`, `\UnresolvedPlayFraction`, `\MultiIdentityStates`, `\MultiIdentityFraction`, `\CollisionPlayOptions`, `\CollisionPlayFraction`, `\HeadDisagreementAll`, `\HeadDisagreementMulti`, and `\HeadDisagreementOther`.
- Held-out replay comparison: `\HeldoutEpisodes`, `\HeldoutCandidateApproved`, `\HeldoutControlApproved`, `\HeldoutAbstain`, `\HeldoutDecisive`, `\HeldoutApproval`, `\HeldoutCILow`, `\HeldoutCIHigh`, and `\HeldoutTeamBalancedApproval`.
- Four-cell ablation: `\AblationPairsPerCell`, `\CtwoEffectPP`, `\CthreeEffectPP`, `\CfourEffectPP`, `\CfourMinusCtwoPP`, `\CfourMinusCthreePP`, `\InteractionEffectPP`, and corresponding interval macros.
- Negative experiments: `\TemporalPairs`, `\TemporalEffectPP`, `\TemporalCILowPP`, `\TemporalCIHighPP`, `\SequenceWorlds`, `\SequenceRoots`, `\SequenceEffectPP`, `\SequenceCILowPP`, and `\SequenceCIHighPP`.

The manuscript should use percentage points for paired win-rate differences, not percentages. The held-out approval quantity is a conditional proportion among decisive disagreements, not an accuracy or win rate.

## Abstract

Sequential policies with variable legal-action sets can fail for a mundane reason: distinct legal actions may be mapped to the same policy input. We study one such identity-aliasing defect in a partially observable, stochastic card-game simulator. The historical feature encoder represented ordinary PLAY options without binding each option to the hand card it selected. We repaired that binding and fine-tuned only the policy heads of a frozen competent baseline on recent expert replay decisions while retaining a distillation anchor to the baseline. We then compared the resulting policy with the frozen baseline using a preregistered common-random-number design over seven fixed opponent policies and both actual turn orders. The primary paired win-rate difference was `\FreshEffectPP` percentage points (95% stratified paired-bootstrap interval [`\FreshCILowPP`, `\FreshCIHighPP`]; `\FreshPairs` pairs). **Choose exactly one result sentence after the generated analysis is final:** (i) *The interval excluded zero, providing evidence of improvement within this frozen opponent population*; or (ii) *The interval included zero, so the experiment did not demonstrate improvement within this frozen opponent population.* Effects were `\FreshGrimEffectPP` points in the matched Grim-family policies and `\FreshOtherEffectPP` points in the other frozen policies; these are secondary subgroup summaries. In an episode-clustered held-out replay comparison, the candidate was preferred on `\HeldoutApproval` of decisive baseline--candidate disagreements (95% interval [`\HeldoutCILow`, `\HeldoutCIHigh`]), showing that paired gameplay and expert-action agreement need not rank policies alike under distribution shift. Matched four-cell ablations and two retained negative experiments delimit the mechanism: neither identity activation nor retraining should be interpreted outside its tested combination, and bounded temporal or sequence interventions showed intervals spanning zero. The result is a case study in separating representation validity, imitation agreement, paired gameplay performance, and population robustness. It is not evidence of universal improvement, superhuman play, or superiority over unevaluated opponents.

## 1. Introduction

Imperfect-information games are useful environments for studying sequential decision making because an agent must act from a partial view of a stochastic process while anticipating other policies. Poker systems such as DeepStack and Pluribus illustrate the scientific difficulty of this class, but they do not provide a performance comparator for the card-game agent studied here \cite{moravcik2017deepstack,brown2019pluribus}. Our focus is narrower: whether repairing a concrete legal-action representation defect changes what can be learned from recent replay data, and whether offline imitation metrics predict paired simulated outcomes.

The case is motivated by a recurring separation in applied policy learning. An input representation may be more faithful to the available observation without producing higher agreement with a held-out demonstrator. Conversely, a policy may win more often against a defined opponent family even when it agrees less often with historical expert actions. Sequential imitation learning is especially exposed to distribution shift because a learned policy changes the states it visits \cite{ross2011dagger}. The present study does not implement DAgger and claims none of its guarantees; the citation establishes only why held-out action agreement and on-policy outcomes answer different questions.

Legal-action interfaces create an additional representation problem. Masking invalid actions controls which outputs can be selected, but it does not guarantee that two valid outputs are distinguishable to the policy \cite{huang2022invalidmasking}. Set-based and relational models provide one general vocabulary for preserving item identity in variable collections \cite{zaheer2017deepsets}. Here the defect is more specific: an ordinary PLAY option carried an index into the observed hand, yet the historical feature encoder deliberately left its source-card field at zero. Multiple legal card plays could therefore share the same relevant option representation even though they invoked different cards.

We make four contributions. First, we audit the prevalence of this identity aliasing in the retained replay-derived feature corpus. Second, we evaluate an identity-aware repair coupled to a deliberately restricted, heads-only update from a frozen baseline. Third, we compare the update with the baseline in paired common-random-number games across frozen opponents and actual turn order, with uncertainty computed at the paired unit rather than the individual game. Fourth, we report the disagreement between gameplay and episode-clustered held-out expert agreement together with retained negative experiments. This framing follows calls for uncertainty-aware aggregate evaluation and explicit artifact provenance \cite{agarwal2021statistical,pineau2021reproducibility}.

The scope is intentionally bounded. The opponents are a fixed local population, not a random sample of all agents. A public competition rating is neither the endpoint nor treated as calibrated Elo. The experiments do not establish that planning, reinforcement learning, or temporal policies are ineffective in general, and they make no direct empirical comparison with poker systems.

## 2. Formal problem setting

Model the environment as a finite-horizon partially observable stochastic game. At engine step $t$, the agent receives observation $o_t$, a legal-action collection $A_t=\{a_{t1},\ldots,a_{tK_t}\}$, and the observable interaction history available through the interface. A policy assigns scores $s_\theta(o_t,a_{tj})$ and selects only from $A_t$. Because $K_t$ varies, each action is encoded separately and combined with observation features before scoring.

Let $\phi(o_t,a)$ denote the historical option encoder. An action-identity collision occurs when two distinct legal actions $a\ne a'$ satisfy $\phi(o_t,a)=\phi(o_t,a')$ on the option information used to distinguish them. The defect studied here concerns ordinary PLAY actions whose engine options refer to different hand entries. Under the historical v2 contract, their selected card was not bound to `source_card`; under the repair, the encoder resolves the legal option's hand index and binds the corresponding observed card identity. This is a representational distinction, not a claim that every remaining feature collision is eliminated.

For paired evaluation, define $W^{(1)}_{ci}$ and $W^{(0)}_{ci}$ as candidate and control win indicators for paired unit $i$ in frozen opponent-by-order cell $c$. Losses and draws both map to zero for the primary endpoint. The paired difference is $D_{ci}=W^{(1)}_{ci}-W^{(0)}_{ci}$, and the primary estimand is the unweighted mean of the 14 cell means. Because cell sizes are equal by design, this equals the overall mean paired difference after complete execution. The estimand pertains only to the seven named opponent policies, their frozen packages, and the two actual-order conditions.

The held-out replay estimand is different. At a recorded decision where the candidate and control choose different actions, the historical action may approve the candidate, approve the control, or approve neither. Approval is the candidate-approved count divided by candidate-approved plus control-approved; neither-approved decisions are abstentions. Resampling is by episode because decisions within an episode are dependent \cite{field2007clustered}. This conditional comparison is not an estimate of gameplay value.

## 3. Environment and frozen baseline

Experiments use a third-party competition engine for a two-player, partially observable card game. The interface exposes the acting player's observation and legal actions, including actual turn order. The engine, rule implementation, deck material, and opponent packages are not claimed as original scientific contributions. Descriptions in the paper should remain abstract and should not reproduce card text, artwork, deck lists, or other restricted content.

The frozen control, C0, is the A2 policy package with the Damage V0 runtime layer. Its first- and second-order neural model files both have SHA-256 `b19871a9f1499c2460ae266e58194acab1d8c90b390fa5cf24ed94b9a2b6bda8`. The candidate, EXP23, retains the same surrounding runtime structure while enabling identity binding and loading trained head weights with SHA-256 `cefe61189bc6f4e316212b19c99450e4b91ff1e5493f4467a95041c30fd96984`. Its archived package has SHA-256 `0734b60c089eea9c2e40550b8e9c6dc3983957210794ba245c4c00bd9d4e7096`. Full directory and engine digests belong in the methods table or supplement, not the narrative.

One archived EXP23 order-policy manifest names stale baseline model hashes even though the packaged model bytes hash to the EXP23 value. Package bytes, the frozen hash inventory, and evaluation outputs agree; the stale manifest must be described as a provenance defect and must not be used to identify the active model.

## 4. Representation defect

The v2 encoder's ordinary PLAY branch set the selected source to `None` whenever the engine option had no explicit area. Consequently, the encoded `source_card` defaulted to zero rather than resolving the option index into the acting player's observed hand. The repair is a small, testable change: when identity binding is enabled for such an option, it checks that the index is in range and binds `hand[option.index]` as the selected source. The repair uses only information already present in the agent's observation and legal-action object; it does not reveal hidden opponent information.

In the retained replay-derived corpus, the audit found `\CorpusDecisions` decisions and `\OrdinaryPlayOptions` ordinary PLAY option instances. Under the historical encoder, `\UnresolvedPlayOptions` of those instances (`\UnresolvedPlayFraction`) had unresolved source identity. `\MultiIdentityStates` decision states (`\MultiIdentityFraction` of states containing PLAY) exposed at least two distinct legal PLAY-card identities. A blind-signature audit placed `\CollisionPlayOptions` option instances (`\CollisionPlayFraction`) in signature groups containing more than one source identity. These counts characterize the retained corpus, not all states that the simulator can generate.

A head-only diagnostic found baseline--candidate choice disagreement of `\HeadDisagreementMulti` in multi-identity states and `\HeadDisagreementOther` elsewhere. This diagnostic applies neural heads directly to retained feature rows and uses index-exact actions without runtime safety layers. It therefore shows where the learned scorers differ; it is neither a gameplay estimate nor a causal decomposition of the production policy.

## 5. Identity-aware intervention

The intervention combines the identity binding with a restricted imitation update. It initializes from A2, freezes all parameters outside the option-scoring, count, score, and value heads, and trains the allowed modules against replay-derived expert decisions. A frozen A2 teacher supplies a KL distillation term. This baseline anchor is related in motivation, but not in guarantees, to conservative policy-improvement methods that constrain changes in uncertain regions \cite{laroche2019spibb}. We use “conservative” descriptively for limited parameter scope and distillation; we do not assert a monotonic-improvement or safety theorem.

The four-cell ablation separates encoder and training factors: C1 is blind v2 with original A2; C2 activates identity-aware v2 with original A2; C3 is blind v2 with the matched heads-only update; and C4 is identity-aware v2 with the matched update (EXP23). C2 is mechanistic rather than a production candidate because it supplies a previously zero embedding coordinate to weights that were not trained for that coordinate. C3 is likewise diagnostic. Only matched contrasts from the frozen ablation protocol support statements about the encoder, retraining, or their interaction.

## 6. Replay data and training

The retained feature corpus contains 47,653 decisions: 38,254 training decisions, 3,361 internal-validation decisions, and 6,038 held-out-team decisions. Splits are defined by the retained manifest, including episode-level allocation and held-out team identity. These are feature rows mined from replay observations, not independent and identically distributed examples from the eventual gameplay test population. The original replay observations used to create all retained rows are not fully preserved, so feature extraction cannot be reconstructed end to end; the retained rows and their hashes are the available training source.

EXP23 was initialized from A2 and trained for three epochs on CPU with AdamW, learning rate $10^{-4}$, weight decay $10^{-5}$, batch size 256, seed 20260816, gradient clipping at 1.0, and distillation weight 0.5. The trainable module prefixes were `option_linear`, `score`, `count`, and `value`; the implementation verified that frozen parameters were unchanged before export. The configured fresh-data weight was 0.999. Because the historical mixer rounded the implied rehearsal target to zero, every epoch log records 38,254 fresh rows, zero rehearsal rows, and a realized fresh fraction of 1.0. The manuscript must not describe the realized update as containing rehearsal examples. Its conservative elements are frozen parameters, initialization from A2, and the distillation anchor.

The internal validation split served training selection, whereas the held-out-team split was reserved for the offline comparison. Neither split supplies a gameplay outcome. Dataset documentation should follow the release data card and should distinguish retained processed features from unavailable source replays, consistent with the documentation goals of datasheets \cite{gebru2021datasheets}.

## 7. Evaluation protocol

The fresh confirmation was frozen and committed before result files were opened. It fixes C0 and EXP23 package hashes, a seeded engine digest, seven opponent package digests, actual-first and actual-second conditions, disjoint seed ranges, physical-seat alternation, and 200 candidate--control pairs in each of 14 cells. Each pair uses the same engine seed, opponent, actual order, physical seat, and opponent environment for candidate and control. This common-random-number design is intended to reduce nuisance variation while preserving the paired comparison; its validity depends on the implemented coupling and is not implied by citation alone \cite{glasserman1992crn}.

The complete schedule contains `\FreshPairs` paired units. The primary outcome codes wins as one and losses or draws as zero. Draw counts and a win/draw/loss utility sensitivity are secondary. An engine or policy error, nonterminal truncation, illegal action, incomplete pair, digest drift, or seed/seat mismatch invalidates the affected frozen cell rather than being silently excluded or imputed.

The primary interval is a 100,000-replicate percentile bootstrap that resamples complete candidate--control pairs independently within each opponent-by-order stratum and then averages the 14 resampled cell means. The exact two-sided McNemar test conditions on candidate-only plus control-only wins. Fourteen cell-level McNemar tests are secondary and Holm-adjusted together. Opponent, order, family, utility, and latency summaries are secondary. No historical meta-weighted aggregate is analyzed because the referenced frozen weight file is absent.

The four-cell ablation reuses the same opponents, orders, engine, seeds, seats, pair counts, and C0 comparator. Its five simple binary contrasts receive Holm adjustment, while the difference-in-differences interaction is descriptive with a paired-bootstrap interval. The held-out replay comparison resamples episodes, not decision rows, and reports candidate-approved, control-approved, abstain, decisive count, overall approval, team-balanced approval, and prespecified splits.

## 8. Primary results

Across the frozen population, EXP23 won `\FreshCandidateWins` paired games and C0 won `\FreshControlWins`; because both policies can win or fail to win in the same pair, these marginal totals do not replace the paired analysis. The primary paired effect was `\FreshEffectPP` percentage points (95% interval `[`\FreshCILowPP`, `\FreshCIHighPP`]). Discordant outcomes comprised `\FreshCandidateOnly` candidate-only wins and `\FreshControlOnly` control-only wins; the exact two-sided McNemar value was `\FreshMcNemarP`.

**Inference guard:** if and only if the generated interval excludes zero, write that the experiment demonstrated an improvement *within the frozen seven-policy population*. If it spans zero, write that the experiment did not demonstrate improvement, even when the point estimate is positive. Do not use “significant” unless the manuscript names the test, analysis unit, null, and multiplicity status.

Actual-first and actual-second effects were `\FreshFirstEffectPP` and `\FreshSecondEffectPP` points, respectively. The Grim-family and Other-family aggregates were `\FreshGrimEffectPP` and `\FreshOtherEffectPP` points. These estimates describe fixed subgroups and do not authorize inference to unseen opponents. Report individual cells in the forest plot and table with Holm-adjusted values, but avoid narrating isolated favorable cells as separate discoveries.

The four-cell results should be stated as contrasts, not four unrelated scores. C2--C1 (`\CtwoEffectPP` points) measures inference-time identity activation with original A2; C3--C1 (`\CthreeEffectPP` points) measures matched retraining under blind encoding; C4--C2 (`\CfourMinusCtwoPP` points) measures training within the identity-aware encoding; C4--C3 (`\CfourMinusCthreePP` points) measures the encoder contrast after matched training; and the interaction was `\InteractionEffectPP` points. A mechanistic attribution requires the relevant interval and interaction to support it. If those intervals include zero, describe the pattern as unresolved rather than asserting synergy or causation.

## 9. Generalization and held-out disagreement

The opponent-family split is the principal robustness check, but “generalization” here means transfer across the seven frozen local policy packages, not a statistical claim about a larger population. The manuscript should foreground the contrast between `\FreshGrimEffectPP` points for the matched Grim-family group and `\FreshOtherEffectPP` points for the other group, together with both intervals. A smaller or null Other-family estimate is evidence of population sensitivity, not proof of overfitting to a named opponent architecture.

In the held-out replay comparison, the candidate was approved on `\HeldoutCandidateApproved` decisive disagreements, the control on `\HeldoutControlApproved`, and neither on `\HeldoutAbstain`. Thus `\HeldoutDecisive` decisive disagreements yield candidate approval `\HeldoutApproval` (episode-bootstrap 95% interval `[`\HeldoutCILow`, `\HeldoutCIHigh`]); the team-balanced value was `\HeldoutTeamBalancedApproval`. If the interval includes 0.5, do not describe expert preference in either direction. If it lies below 0.5, state that the retained held-out actions favored C0 among decisive disagreements; do not say that EXP23 was less accurate overall because agreement is conditioned on policy disagreement and abstentions are excluded from the denominator.

The gameplay and replay results need not agree. The replay quantity asks which policy reproduces one historical action conditional on disagreement. It assigns no credit to alternative actions that lead to equal or better downstream states, and its state distribution was generated by historical agents. Paired gameplay instead measures terminal outcomes on trajectories induced by each tested policy against a frozen opponent. The estimands differ in state distribution, conditioning, outcome horizon, and unit of analysis. Their disagreement therefore diagnoses metric dependence under distribution shift; it does not show that expert data are poor, that imitation is generally harmful, or that gameplay simulation is unbiased.

Report collision-state held-out splits only as secondary diagnostics. Similar approval inside and outside a collision bucket would caution against attributing the aggregate replay result solely to the repaired field. Different approval rates would remain observational because collision states differ in other ways.

## 10. Negative and null experiments

Two negative experiments retain raw artifacts sufficient for exact recomputation. A two-turn temporal-takeover confirmation covered `\TemporalPairs` actual-second paired units across three fixed internal opponents. Its pooled paired effect was `\TemporalEffectPP` percentage points with interval `[`\TemporalCILowPP`, `\TemporalCIHighPP`], which spans zero. The result does not demonstrate benefit for that frozen takeover policy and schedule. It does not show that temporal policies are ineffective generally; the earlier candidate-selection screen was not an independent confirmation.

A bounded sequence oracle evaluated `\SequenceWorlds` confirmation worlds clustered within `\SequenceRoots` retained roots, against three fixed opponents and at most two deviations. Its effect was `\SequenceEffectPP` points with root-clustered interval `[`\SequenceCILowPP`, `\SequenceCIHighPP`], which spans zero and did not clear its prespecified practical gate. This is evidence about one bounded proposal-and-confirmation procedure, not a test of planning as a class.

Historical reports also describe PPO, expected-Q, and an older Turn Director, but their underlying row-level artifacts are absent from the present repository. Their exact effect estimates and intervals must therefore be omitted from the evidentiary results. They may be listed in a provenance appendix as summary-only experiments that could not be independently recomputed, with no inferential claim. This distinction prevents surviving prose summaries from being given the status of raw results.

## 11. Discussion

The central lesson is that four quantities should not be collapsed into one: representational validity, held-out imitation agreement, paired gameplay value, and robustness across opponent populations. Binding an action to the observed object it selects repairs a factual defect in the policy input. That repair does not logically imply that the inherited embedding is calibrated, that a small offline update improves every downstream action, or that one demonstrator action is the unique valuable move.

The restricted update offers a practical design pattern for auditing an already competent policy. Freezing most parameters and retaining a baseline-distillation term reduces the dimensions in which training can move, making the intervention easier to compare and reproduce. It still has no formal safe-improvement guarantee, especially because the realized training stream contained no rehearsal records and the replay state distribution differs from the gameplay evaluation distribution.

Paired common-random-number evaluation is particularly useful in stochastic simulators when policy comparisons can share seeds and exogenous conditions. Pairing does not make results universal: the opponent population, actual-order strata, engine build, decks, and runtime safety layers remain part of the estimand. Likewise, a narrow interval around a small population mean cannot justify claims about unevaluated policy families.

The negative results matter for interpretation. They show that additional temporal or bounded sequence machinery did not automatically convert into a detectable gain under their frozen tests. Including them reduces selective reporting and clarifies why the final study centers on representation and metric disagreement rather than presenting a sequence of only favorable candidates.

## 12. Limitations

First, the seven opponents are a deliberately frozen convenience population assembled during agent development. They do not constitute a random or exhaustive sample, and several are related policy variants. Family aggregates are descriptive.

Second, the environment is a restricted third-party engine. Engine source and binaries, game assets, card data, deck lists, private replay material, and other teams' code cannot be redistributed in the sanitized artifact. Exact end-to-end replay therefore requires lawful access from the organizer under separate terms. The public release can regenerate statistics and figures from processed outcomes but cannot recreate engine trajectories by itself.

Third, original replay observations used for feature extraction were not fully retained. Training can be reproduced only from the preserved feature rows, subject to rights review; the transformation from source replay to every row cannot be independently rerun.

Fourth, the configured training mix and realized mix differ. Although the fresh weight was set to 0.999, rounding produced no rehearsal rows. The label “conservative” must rest on freezing and distillation, not rehearsal.

Fifth, held-out expert agreement is a selective proxy. It conditions on policy disagreement, depends on one historical action, contains abstentions, and is clustered within a modest number of episodes and teams. It is neither an independent reward label nor an on-policy value estimate.

Sixth, the mechanistic representation audit is performed on retained feature rows, and head-only disagreement omits production runtime shields. Corpus collision frequencies and scorer disagreements need not equal collision exposure or action changes in fresh games.

Seventh, several favorable historical aggregates cannot be reconstructed. Surviving prose conflicts with or lacks the raw artifacts needed for the reported historical Grim pooled effect, seven-policy macro, frozen meta-weighted result, and CERT-B confidence interval. Those values are excluded rather than reconciled in favor of the larger estimate.

Finally, all claims are specific to the frozen packages, engine, seed schedules, and analysis code. No claim is made of superhuman performance, calibrated rating improvement, universal robustness, or the ineffectiveness of planning or reinforcement learning.

## 13. Conclusion

This study isolates a concrete failure mode in a variable legal-action interface: distinct observed card plays were legal yet not identity-distinguishable to the historical encoder. We repaired the binding, applied a restricted baseline-anchored update, and evaluated the resulting policy with paired simulation and episode-clustered replay diagnostics. The findings show that a more faithful representation, agreement with held-out expert actions, terminal gameplay outcomes, and robustness across opponent families are distinct empirical questions. Any positive gameplay conclusion must remain restricted to the frozen population and its interval; any held-out disagreement must remain restricted to decisive replay disagreements. The broader methodological recommendation is to audit action identity explicitly, match ablations across representation and training, pair stochastic evaluations at their natural unit, and preserve negative results and provenance conflicts alongside favorable findings.

## 14. Acknowledgments

Placeholder only: identify the competition organizer, engine provider, data contributors, compute providers, and human reviewers whose acknowledgment is authorized. Do not name individuals, teams, or institutions without confirmation. State that third-party trademarks and game materials belong to their respective owners if counsel or journal guidance recommends it. Funding and grant identifiers require author confirmation.

## 15. AI-use disclosure

Use the audited disclosure in `paper/ai_disclosure.md`, not a shortened invented list. A manuscript-ready form should name OpenAI Codex and the model/version information actually exposed to the authors; describe its assistance with repository auditing, code generation and debugging, protocol and analysis review, literature discovery, figure and table generation, and manuscript drafting; state that the human authors directed the tasks; and explain hash checks, deterministic reruns, source inspection, automated tests, claim-ledger review, citation verification, and rendered-PDF inspection. AI systems are not authors. Historical AI tools or versions not recoverable from the repository must be confirmed by the human authors before submission.

## 16. Author contributions

Do not infer CRediT roles from Git history. Insert author-confirmed names and roles for conceptualization, methodology, software, validation, formal analysis, investigation, data curation, visualization, writing--original draft, writing--review and editing, supervision, project administration, and funding acquisition. The corresponding author must confirm responsibility for the integrity of the work and complete ORCID metadata.

## 17. Data Availability Statement

Processed paired outcomes, machine-readable summaries, analysis scripts, generated tables and figures, protocols, and artifact manifests are included in the sanitized release, subject to final rights review. The third-party competition engine and its binaries, game assets and proprietary card data, deck lists, private replay data, credentials, and other teams' code are not redistributed. Researchers seeking to repeat engine-level evaluation must obtain lawful access from the competition organizer under the organizer's terms and implement the documented abstract adapter. The release supports recomputation of reported statistics and graphics from processed outcomes; it does not by itself reproduce gameplay trajectories or feature mining from unavailable source replays. The final statement must match the files actually present in `release/` and must not imply an open license until ownership and licensing are confirmed.

## Appendix A. Encoder audit details

Specify the exact code branch for ordinary PLAY options, the identity-enabled branch, in-range index check, and handling of missing cards. Define blind signatures and collision groups operationally. Report corpus, manifest, script, control-model, and candidate-model SHA-256 digests. Tabulate counts by decision context and source-card family only where the processed release may lawfully expose those group labels; otherwise use abstract identifiers. Clarify that the audit does not inspect hidden state.

## Appendix B. Training and split provenance

Include the split rule, episode counts, decision counts, deduplication key, held-out precedence, model initialization, optimizer settings, loss composition, trainable parameter names, epoch logs, realized source mix, frozen-parameter check, export digest, and the stale order-manifest discrepancy. Distinguish the configured fresh weight from the realized 100% fresh batches.

## Appendix C. Statistical estimators

Give pseudocode for within-cell paired resampling, the exact McNemar calculation, Holm adjustment, episode-clustered replay resampling, and root-clustered sequence-oracle resampling. State every bootstrap seed and replicate count from generated metadata. Define treatment of draws and errors. Note that cell-level and family analyses are secondary and that the absent historical meta-weight file precludes a meta-weighted estimate.

## Appendix D. Four-cell ablation

Provide package/model hashes for C1--C4, transformed-corpus digest for C3, training parity checks, matched gameplay schedule, all prespecified contrasts, and the difference-in-differences estimator. Explicitly label C2 and C3 as mechanistic diagnostics. Avoid attributing the C4 result to identity repair alone unless the matched contrast and interaction support that statement.

## Appendix E. Negative-experiment provenance

List the raw hashes and frozen scope for the temporal takeover and bounded sequence oracle. Separate those recomputable results from PPO, expected-Q, and Turn Director summaries whose raw rows are unavailable. Do not reproduce unsupported exact values in the evidentiary table.

## Appendix F. Reproducibility and rights boundary

Describe the canonical tidy schema, generated-results workflow, claim-ledger gate, clean-build procedure, release manifest, and restricted adapter boundary. Report that the source branch requested as `grim-5k-variance-floor` was available locally only as `archive/grim-5k-variance-floor`, if that remains true at release time. Document every unavailable artifact that constrains reconstruction. Make clear that reproducibility from processed outcomes and reproducibility of engine-level trajectories are different levels of access.

## Source-conflict language for the supplement

The following paragraph can be adapted nearly verbatim:

> We applied a prespecified source hierarchy in which raw paired-game rows outranked prose summaries. Several historical headline quantities did not pass this audit. The archived Grim-family aggregate was inconsistent with the surviving named raw runs and involved an overlapping seed schedule under one possible reconstruction. The raw rows and frozen weights needed to reproduce the reported seven-policy macro and meta-weighted aggregates were absent. The historical CERT-B prose conflated all policy disagreements with binary decisive approvals, while its row-level file was absent. We therefore excluded these historical values from the evidentiary manuscript rather than selecting a favorable reconstruction. A stale package manifest also named baseline model hashes although the packaged candidate bytes and evaluation inventories consistently identified the EXP23 model; we use the verified bytes and report the manifest defect. These exclusions narrow the claims but preserve a reproducible connection between every included number and a retained artifact.

## Final editorial guards

- Never call the candidate “better” without naming the evaluated population and interval.
- Never call the held-out quantity accuracy; call it candidate approval among decisive disagreements.
- Never imply that a confidence interval spanning zero demonstrates improvement.
- Never pool historical screens with the fresh confirmation.
- Never cite competition rank as a primary outcome or calibrated Elo.
- Never describe C2 identity activation as a deployable fair comparison.
- Never infer a causal effect from collision-state subgroup statistics alone.
- Never generalize negative temporal or sequence findings to all planning or reinforcement learning.
- Never promise redistribution of restricted engine material or an open license before rights review.
- Keep DeepStack and Pluribus as contextual examples, not empirical comparators.
