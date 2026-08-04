# Claude handoff: Grimmsnarl cold-start weakness, Lucario, and Iono/Bellibolt

Date: 2026-08-03 (America/Chicago)

## Objective and authorization boundary

The practical objective is to make the Grimmsnarl agent survive the front-loaded lower ladder bands, especially against newer Lucario and Iono-family opponents, without destroying its previously demonstrated general strength.

The user explicitly authorized:

- acquiring and auditing exact adversary data;
- training and evaluating Lucario and Iono/Bellibolt adversaries;
- Azure compute for bounded experiments;
- trying generic rollout search, MCTS, heuristic search, and value-based agents instead of relying only on behavioral cloning and RL.

Do **not** train or modify Grimmsnarl, package a submission, or submit to Kaggle without a new explicit approval. No such action has occurred. Always deallocate the Azure VM after substantial work.

## Safe checkpoint

- Azure resource group: `ptcg-train-south-rg`
- Azure VM: `ptcg-train`
- Current power state at handoff: `PowerState/deallocated`
- No Grim training, package creation, or submission occurred.
- The newest exhaustive run attempted to auto-expand Bellibolt from 100 to 1,000 games because it crossed the old 15% screen floor. A watchdog copied the completed reports and killed the 1,000-game process immediately.
- Consequently, `artifacts/exhaustive_search_qualification_20260803/azure_run.json` says `status: failed`. This is an intentional controlled stop, not evidence that either completed 100-game report is invalid.
- That run consumed about 0.464 Azure hours and records an estimated retail compute cost of $0.2246.

## Why the sudden ladder drop remains plausible

The current evidence supports a mixture of opponent-distribution shift and run variance, rather than a proven global collapse of the older Grim agent:

- Submission `55171235` went 41-24 (63.1%), climbed from 600 to 966.3, and peaked at 1005.1. It was 24-7 below 900 (77.4%). It encountered **zero** Mega Lucario ex decks.
- The two newer pure-5k controls (`55198084`, 56 games; `55198075`, 46 games) collectively went 9-16 against Mega Lucario ex (36%). The identical-model runs differed substantially: 20% versus 46.7% in that matchup, so run-to-run noise is material.
- Their weakness was broader than Lucario: the 600-700 and 700-800 bands were only 47.6% and 44.7%. There were no games above 900, so no claim about current higher-band strength can be tested from those runs.
- Of 47 recent losses, 23 were board wipes and 19 were ordinary lost prize races. They were real gameplay losses, not timeout or engine-status artifacts.
- The older run's absence of Lucario and the newer run's 25 Lucario encounters are consistent with a newer or newly prevalent matchup hole. They do not prove Lucario alone caused the cold starts. Iono-family, Alakazam, Dragapult, unknown archetypes, and ordinary sampling variance remain plausible contributors.
- Front-loaded MMR makes an unlucky early opponent mixture unusually damaging: a model can fail to reach the bands where it previously performed acceptably.

## Completed adversary work

### Exact Iono/Bellibolt deck and audited data

Deck:

- `freshstart/decklists/iono_bellibolt_ex.deck.csv`

Five exact seed episodes were found: `89479193`, `89491209`, `89635007`, `89627072`, and `89764669`.

The expanded audited corpus is:

- `artifacts/bellibolt_bootstrap_20260803/data/bellibolt_audited.jsonl.gz`
- `artifacts/bellibolt_bootstrap_20260803/data/manifest.json`
- 107 episode-seats and 14,602 decisions.
- Train: 51 games / 7,109 decisions / 21 wins.
- Validation: 4 / 578 / 2 wins.
- Unseen team: 26 / 3,489 / 12 wins.
- Temporal: 26 / 3,426 / 9 wins.
- Four duplicate dual episode seats were removed.
- Split teams are disjoint, but there are only four identities/groups: Yuta Goda and kotakota1234 for training, Nishanth Rajan for validation, festivallead for unseen-team, and Kazuhiro O for temporal.

Twenty-three historical episode downloads were unavailable (22 from an older source submission and one from another); this is recorded in the acquisition artifact.

### Bellibolt behavioral cloning

Six BC candidates were trained: three fresh and three initialized from `artifacts/grimmsnarl_5k_reference.npz`.

Candidate manifest:

- `artifacts/bellibolt_bootstrap_20260803/bc/candidate_manifest.json`

All six passed imitation/fidelity checks. The initialized models achieved roughly 74-77% exact imitation and 92-94% top-three accuracy across held-out partitions. This did **not** translate into gameplay strength.

Direct 100-game results against the frozen Grim reference:

- Fresh seeds: 1%, 1%, and 0%.
- Initialized seeds: 7%, 9%, and 5%.
- Best model: `artifacts/bellibolt_bootstrap_20260803/bc/initialized_seed20260804/policy_weights.npz` at 9-91.
- Report: `artifacts/bellibolt_bootstrap_20260803/direct_screen/final_report.json`

The BC Azure run was deallocated and cost about $0.0339.

### Lucario BC/PPO background

An expanded Lucario corpus contained 39,263 audited decisions. Six BC seeds were tried; the best direct result was approximately 5.5%. A 5,000-game PPO phase improved the adversary only to about 7%. More ordinary BC/PPO on the same representation and reward setup has therefore already shown poor returns.

The strongest available Lucario prior used by search is:

- `artifacts/lucario_pilot/lucario_ppo2.npz`

### Generic rollout search

Implementation:

- `training/search_teacher.py`
- `training/evaluate_search_teacher.py`

The teacher determinizes hidden information from exact registered decks, generates legal candidates, forward-simulates with the engine, and uses frozen neural policies during rollout. No card-specific tactical rules are embedded.

Prior-limited search (`max_candidates` 6/8) results:

- Lucario: screen 22/100, then 161/1,000 = 16.1%; seats 16.4% and 15.8%; zero runtime errors. This is the best statistically stable Lucario adversary result so far, but it failed the 25% qualification gate.
- Bellibolt using the wrong Lucario prior: 2/100. This result should not be treated as a serious Bellibolt attempt.
- Reports: `artifacts/search_teacher_qualification_20260803/`

Root-exhaustive search (up to 512 legal candidates, one determinization) results:

- Lucario: 12/100, Wilson 95% interval 7.0%-19.8%; seats 14% and 10%; 30,574 rollouts; zero errors.
- Iono/Bellibolt with its best BC prior: 17/100, Wilson 95% interval 10.9%-25.5%; seats 20% and 14%; first/second 20.4% and 13.7%; 94,204 rollouts; zero errors.
- Reports: `artifacts/exhaustive_search_qualification_20260803/`

Bellibolt improved from 9% direct to 17% with exhaustive root search. That is worthwhile evidence that action selection matters, but 17% is still below the 25% adversary qualification target. Exhaustive search hurt Lucario relative to the prior-limited search, suggesting that weak rollout evaluation cannot reliably rank every legal root action.

### Generic information-set MCTS

Implementation:

- `training/mcts_teacher.py`
- `tests/test_mcts_teacher.py`

Features:

- determinized PUCT;
- adversarial opponent nodes that minimize root-player value;
- exhaustive bounded root enumeration and prior-limited internal nodes;
- forced evidence for every bounded root action;
- frozen neural value estimates;
- optional rollout/value blending;
- generic logic with no card/deck-specific tactics.

Evaluator support is in `training/evaluate_search_teacher.py` via `--agent-kind mcts`.

Smoke evidence only:

- Lucario: two local games, zero errors, 2,319 simulations, 0-2.
- Bellibolt: two local games, zero errors, 4,966 simulations and 5,156 nodes, 0-2.

These four losses are not a strength estimate. They establish only that MCTS is stable and fast enough for a bounded Azure screen.

### Azure runner safeguard

`scripts/run_azure_search_qualification.py` was updated locally to support:

- `--agent-kind mcts`;
- MCTS configuration arguments;
- `--screen-only`, which prevents automatic 1,000-game expansion.

It compiles and its CLI help was checked. The latest focused test runs were 8/8 passing for search/MCTS, while an earlier broader focused suite had 31 passing tests.

Before the next Azure run, add `tests/test_mcts_teacher.py` to the runner's remote pytest command. The runner syncs the test directory, but its current explicit remote test list predates MCTS.

## Weaknesses and limitations of the current Lucario/Iono approach

### 1. We do not yet have faithful *and strong* adversaries

This is the most important limitation. Bellibolt BC imitates recorded decisions well but wins only 9% against the frozen Grim reference. Lucario BC/PPO is similarly weak. A high action-imitation score is not a gameplay-strength certificate: small compounding errors, missed long-horizon setup, and wrong behavior in rare critical states can destroy win rate.

Because the ladder Grim actually lost to Lucario and Iono-family opponents while the constructed adversaries lose heavily to the frozen Grim, these adversaries are not yet reliable proxies for the ladder threat. Training Grim against them now risks teaching it to beat weak caricatures.

### 2. Objective mismatch in behavioral cloning

BC minimizes per-decision imitation error. Winning requires coherent sequences over an entire game. The dataset is dominated by easy or forced decisions, so excellent aggregate accuracy can hide failure on the few branching decisions that determine setup, prize mapping, switching, resource conservation, or recovery after disruption.

Initialized Bellibolt models inherit useful generic behavior from Grim, explaining their much higher imitation metrics, but that initialization can also inject the wrong deck-specific value assumptions.

### 3. Lucario PPO did not solve exploration or credit assignment

Five thousand PPO games moved Lucario only to about 7%. Sparse terminal rewards, a very weak starting policy, long games, and off-policy/importance corrections make it difficult to discover coherent winning lines. More PPO with the same opponent, features, and reward is unlikely to be cost-effective without better state values, curricula, or search-generated targets.

### 4. Rollout search is only as good as its rollout policies

The rollout teacher uses weak learned policies after each candidate action. Root-exhaustive search therefore evaluates many moves through a biased continuation model. Lucario falling from 16.1% with prior-limited search to 12% with exhaustive search is direct evidence that exploring more actions can worsen choices when the evaluator is poorly calibrated.

The 320-step rollout limit may truncate strategically decisive lines or substitute a noisy heuristic/partial outcome for the true terminal value.

### 5. Hidden-information treatment is shallow

The 100-game exhaustive screens used one determinization per decision. Pokemon TCG has hidden hands, deck order, and prizes; one sampled world can make a move look artificially good or bad. More determinizations reduce this noise but multiply an already high compute cost.

### 6. Bellibolt has a severe action-space tail

Observed unordered legal-candidate counts for Bellibolt had mean 12.83, p90 17, p99 45, and maximum 16,663. About 0.7% exceeded 64 candidates and 0.226% exceeded 512. Thus “exhaustive” with a cap of 512 is exhaustive for most decisions, not all of them. Forced root coverage in MCTS also means nominal simulation counts can be exceeded when there are many root actions, causing highly variable runtime.

Lucario is smaller on average (mean 8.2) but still reached 299 candidates.

### 7. The MCTS value function is unqualified and likely out-of-distribution

MCTS currently uses the frozen policy checkpoint's scalar value head. That value was not proven calibrated for deep determinized Lucario/Bellibolt states. PUCT can amplify systematic value error with confidence. The two-game smoke tests prove stability, not useful search quality.

Generic MCTS also lacks a separately trained board evaluator or domain-shaped features for prize pressure, board extinction, energy/resource tempo, and recovery capacity. Adding card-specific heuristics would improve focus but introduces maintenance and overfitting risks; generic board-level heuristics are preferable if pursued.

### 8. Evaluation covers one frozen Grim and one exact deck signature at a time

All adversary screens target `artifacts/grimmsnarl_5k_reference.npz`, not the full distribution of Grim seeds/submissions or ladder opponents. Strength found against this one model may exploit it rather than reproduce real archetype strength.

The Bellibolt findings apply to `iono_bellibolt_ex.deck.csv`; they must not be generalized to every deck containing Iono. Likewise, the Lucario findings cover the registered Mega Lucario list, not every Lucario variant. Alakazam, Dragapult, and the large “unknown archetype” bucket have not been addressed by this work.

### 9. The datasets are not as independent as their decision counts suggest

Bellibolt has 14,602 decisions but only 107 episode-seats and four split identities/groups. Validation contains only four games. Thousands of correlated decisions from the same games and players do not provide thousands of independent strategic examples. Historical source unavailability also leaves gaps.

### 10. Current game estimates still have sampling and exposure limitations

At 17/100, Bellibolt's Wilson interval is 10.9%-25.5%, so it could be near the threshold but is not demonstrated to clear it. Lucario exhaustive is more clearly weak at 12/100, while the 1,000-game prior-search result is stable at 16.1%.

Seat balance is enforced, but first-player exposure is not balanced. In the Lucario exhaustive screen the hero was classified first in only 5/100 games; the 1,000-game prior-search run was 112/888 first/second. This may reflect setup-policy choice rather than an evaluator bug, but it means Lucario's performance when going first is poorly estimated. Investigate before treating turn-order slices causally.

The engine uses unpaired randomness, so candidate comparisons do not share identical deals. Paired-deal evaluation would reduce variance if the engine can support it safely.

### 11. A strong adversary is necessary but not sufficient to fix ladder MMR

No Grim curriculum has been run. Even if MCTS creates stronger Lucario/Bellibolt opponents, training against them could cause catastrophic forgetting against the older low-band field. A future Grim phase needs a mixture of these counters, historical control opponents, seats/turn orders, and strict regression gates.

Synthetic head-to-head improvement also does not prove improved cold-start ladder rating. Final evidence must come from multiple independent submissions or an equivalent broad held-out opponent suite.

## Recommended next experiment

Run a **screen-only 25-game value-only MCTS test** for both exact adversaries. Do not run 100 or 1,000 games automatically.

First patch the runner's remote pytest list to include `tests/test_mcts_teacher.py`, then run:

```bash
.venv/bin/python scripts/run_azure_search_qualification.py \
  --output-dir artifacts/mcts_value_screen_20260803 \
  --agent-kind mcts \
  --screen-only \
  --screen-games 25 \
  --workers 8 \
  --cost-cap 2 \
  --screen-max-candidates 64 \
  --mcts-simulations 24 \
  --mcts-max-depth 32 \
  --mcts-puct-c 1.5 \
  --mcts-tree-max-candidates 6 \
  --mcts-leaf-rollout-steps 0 \
  --mcts-rollout-weight 0 \
  --lucario-model artifacts/lucario_pilot/lucario_ppo2.npz \
  --bellibolt-model artifacts/bellibolt_bootstrap_20260803/bc/initialized_seed20260804/policy_weights.npz \
  --seed 20260803
```

Decision rule after inspecting the reports:

- Require zero teacher/opponent runtime errors.
- If a deck scores fewer than 4/25, do not expand that configuration.
- If it scores at least 4/25, run a separate **screen-only** 100-game evaluation; inspect it before any larger run.
- Do not launch 1,000 games merely because the old 15% screen threshold is crossed.
- Only call an adversary qualified if the 100+ game evidence is at least 25% overall, at least 20% in both seats, and error-free. Prefer confirmation with a second seed/configuration.

If value-only MCTS is close but not qualified, one bounded alternative is a 25-game shallow hybrid using a small leaf rollout and partial value blend (for example 80 rollout steps and 0.5 rollout weight). Do not grid-search many settings: the weak continuation/value models are the bottleneck, and broad tuning will burn compute without addressing it.

If MCTS is also clearly below 25%, stop treating the current adversary-generation path as ready for Grim training. The next higher-value work would be:

1. Audit critical decisions rather than aggregate imitation accuracy: compare wins versus losses and high-branch states, and identify where BC/search diverges from recorded strong play.
2. Train a matchup-specific value model from terminal outcomes and search states, with game-level splits and calibration checks, instead of reusing the generic policy value head blindly.
3. Consider generic board heuristics for prize pressure, extinction risk, tempo, and recovery as an auxiliary leaf evaluator—not card-ID scripts.
4. Obtain more exact, recent, winning Lucario/Iono variants and more independent teams if available.
5. Add paired-deal or common-random-number evaluation if supported by the engine.

Only after a faithful adversary clears the gates should Claude propose a Grim curriculum. That proposal should preserve older low-band control opponents, oversample Lucario/Iono early to match front-loaded MMR risk, evaluate both seats/turn-order behavior, and require explicit user approval before execution.

## Important files

Core implementations:

- `training/search_teacher.py`
- `training/mcts_teacher.py`
- `training/evaluate_search_teacher.py`
- `training/lucario_data.py`
- `training/train_adversary_bc.py`
- `training/collect_selfplay.py`
- `training/train_ppo.py`

Runners:

- `scripts/run_azure_search_qualification.py`
- `scripts/run_azure_adversary_bc.py`
- `scripts/run_azure_direct_adversary_screen.py`

Tests:

- `tests/test_search_teacher.py`
- `tests/test_mcts_teacher.py`
- `tests/test_adversary_bc.py`
- `tests/test_lucario_curriculum.py`

Key artifacts:

- `artifacts/exhaustive_search_qualification_20260803/lucario_screen.json`
- `artifacts/exhaustive_search_qualification_20260803/bellibolt_screen.json`
- `artifacts/exhaustive_search_qualification_20260803/azure_run.json`
- `artifacts/search_teacher_qualification_20260803/lucario_qualification.json`
- `artifacts/bellibolt_bootstrap_20260803/data/manifest.json`
- `artifacts/bellibolt_bootstrap_20260803/bc/candidate_manifest.json`
- `artifacts/bellibolt_bootstrap_20260803/direct_screen/final_report.json`

## Bottom line

The work was worthwhile as diagnosis and infrastructure, but it has **not** yet produced a qualified Lucario or Iono/Bellibolt teacher. It ruled out straightforward “more BC/PPO” as an adequate answer, showed that search can improve Bellibolt from 9% to 17%, showed that indiscriminate exhaustive search can hurt Lucario, and delivered a stable generic MCTS path with hard screen-only safeguards.

The immediate next question is narrow: can value-guided MCTS clear a 25-game screen strongly enough to justify 100 games? Until that answer is yes and then confirmed, do not train Grim on these opponents.
