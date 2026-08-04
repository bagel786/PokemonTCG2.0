# Grimmsnarl Low-Tier Meta Research Handoff

Date: 2026-08-03  
Workspace: `/Users/safiullahbaig/Projects/pokemonTCG2.0`

## Assignment for the New Chat

Research how to improve Grimmsnarl against underrepresented decks encountered around the 600–700 ladder band, especially Mega Lucario ex, without degrading its strong top-meta play.

This is a research and diagnosis task first. Inspect the repository, current ladder replays, public episode sources, and relevant primary technical literature. Do not train, package, upload, retire, or modify a ladder submission until the user approves a concrete experiment. Return a short, evidence-based recommendation with an estimated runtime and explicit stop conditions.

## Current Live Pair

- Pure 5k control: submission `55198084`, current observed score `716.1`.
- Replay-refresh challenger: submission `55218277`, status `COMPLETE`, initial score `600.0` with no meaningful game sample yet.
- The challenger archive is `grimmsnarl_replay_refresh_challenger.tar.gz` in the project root.
- Do not submit another control: the current pair is already correctly configured.
- Ladder ratings are noisy, matchmaking is unpaired, and identical code has previously ranged from the 600s to 969.7.

## Established Model Evidence

### Pure 5k

- Archive SHA-256: `3ecb0bbf119e23c31905e39e19eca8f6145104aaeffc0a5675d2fe03855bb458`
- Model SHA-256: `d842f85abfc44af9f41979f91795e22c92c179b62e04d5a0a2f9c734e70af1c3`
- This model must remain unchanged as the control.

### Replay-refresh challenger

- Model SHA-256: `1482f3490c7444a29b63512be988e55bf7eae5685f76211e5941b3fe0d7d320a`
- Beat pure 5k in 50,000 local games: `50.734%`, Wilson 95% interval `[50.296%, 51.172%]`.
- Positive lift from both seat/turn-order strata and zero policy errors.
- Authentic Alakazam checks improved from `71.4%` to `73.0%` against 2.4a and from `66.8%` to `70.0%` against 2.7.
- Cleanroom package test: 20 games, 4,050 decisions, zero errors, p99 `0.42 ms`, maximum `11.4 ms`.
- Primary report: `artifacts/5k_improvement_20260802/final_recommendation.json`.

## Rating-Band and Lucario Evidence

Current locally downloaded samples from the two recent pure-5k submissions:

| Segment | Wins | Games | Win rate |
|---|---:|---:|---:|
| Opponent rating 600–700 | 20 | 42 | 47.6% |
| Opponent rating 700–850 | 18 | 40 | 45.0% |
| Exact audited Lucario variants | 8 | 20 | 40.0% |

The working hypothesis is broader than Lucario: mid-rated opponents use decks and tactical lines absent from the top-elite replay distribution used for training. Research should identify the complete underrepresented-deck cohort rather than assuming Lucario explains every loss.

## Failed Lucario Work

### Lucario sparring bot

- Expanded corpus: 39,263 audited Lucario decisions from 577 games after split and mirror cleanup.
- Six BC candidates reached roughly 51% action agreement but only about 5–6% game win rate against pure 5k.
- A 5,000-game conservative PPO stage reached only 7.4% and 6.6% for the two variants.
- It failed the 20% continuation gate and was never used to train Grim.
- Report: `artifacts/lucario_gap_20260803/final_report.json`.

This discrepancy between offline imitation accuracy and game strength is a central research question. Likely causes include exposure bias, incompatible source-policy pooling, insufficient state/action representation, and weak sequential credit assignment.

### Grim Lucario specialist

- A public-information router was implemented. It activates after public Riolu (`677`) or Mega Lucario ex (`678`) detection and otherwise leaves the base policy untouched.
- It detected all 44 authentic local Lucario games and covered 94% of Grim decisions after detection.
- Authentic data contained 1,864 winning Grim decisions and 1,694 loss-state teacher anchors.
- Only **21 winning actions differed from pure 5k**, all from the older Gen4 checkpoint.
- Three Azure BC specialists all failed held-out evaluation. Best exact-selection lift was `−1.64` points; count accuracy was unchanged.
- No PPO, router package, or ladder submission followed.
- Report: `artifacts/grim_lucario_router_20260803/final_report.json`.

The failure means that successful pure-5k trajectories mostly reproduce actions the deterministic 5k already takes. More copies of those decisions do not teach a new response.

## Questions the Research Must Answer

1. Which deck signatures and archetypes account for the largest share of losses between opponent ratings 550 and 800?
2. How underrepresented is each matchup in the July 28 and July 30–31 training shards compared with its ladder frequency?
3. Are losses caused by unfamiliar archetypes, opponent rating/matchmaking effects, seat/turn order, or a small number of tactical decision contexts?
4. What do the 21 successful Gen4 disagreements reveal? Cluster them by context and inspect the surrounding turns rather than treating them as independent labels.
5. Can public replays supply substantially more authentic Grim-versus-Lucario or Grim-versus-mid-meta trajectories from other teams?
6. Would a small interpretable matchup override, a conditional residual adapter, source-specific behavioral clones, DAgger-style data collection, or conservative offline RL be the safest next method?
7. How can improvement be evaluated when individual submissions are unlikely to receive 30–50 Lucario matches? Consider pooling identical-code submissions, hierarchical/Bayesian matchup estimates, public replay aggregation, and broader underrepresented-archetype cohorts.
8. What is the smallest experiment likely to produce new information within three hours?

## Methodological Constraints

- Do not globally fine-tune 5k on a small matchup corpus.
- Do not train Grim against the existing weak Lucario bot.
- Do not infer that high offline action agreement means game strength.
- Do not treat every action in a lost game as a negative label.
- Preserve episode/team/time separation and deduplicate by `(episode_id, seat, step)`.
- Keep the pure 5k control hashes unchanged.
- All substantial training and all game simulation must run on Azure. Local work is limited to analysis, development, and tiny smoke tests.
- Keep future work timeboxed. Avoid another long funnel unless an early stage passes a meaningful information or strength gate.
- No packaging, upload, live-slot change, or submission retirement without explicit user approval.

## Recommended Research Sequence

1. Refresh and classify the newest control/challenger episodes by exact deck signature, rating band, seat, and outcome.
2. Measure ladder frequency versus training-corpus coverage for every archetype in the 550–800 band.
3. Perform turn-level forensics on Lucario losses and the 21 Gen4 disagreements, looking for repeated tactical mechanisms.
4. Search public episode sources for more exact Grim-versus-underrepresented-deck games and quantify the attainable sample before proposing training.
5. Compare three bounded interventions on paper:
   - Lucario/mid-meta tactical rules behind the public-state router.
   - A small conditional residual adapter trained only on genuinely novel successful actions.
   - Source-clustered opponent modeling followed by conservative Azure RL, only if the opponent reaches a credible game-strength gate.
6. Recommend one experiment with success criteria, a hard runtime cap, estimated Azure cost, and a reason it provides information even if it fails.

## Useful Entry Points

- `artifacts/grim_lucario_router_20260803/final_report.json`
- `artifacts/5k_improvement_20260802/final_recommendation.json`
- `artifacts/lucario_gap_20260803/final_report.json`
- `training/grim_lucario_router.py`
- `training/replay_refresh.py`
- `ptcg_ai/agent.py`
- `data/replays/55198084/`
- `data/replays/55198075/`
- `data/processed/elite-2026-07-28-v3.jsonl.gz`
- `data/processed/elite-2026-07-30-31-v2ctl.jsonl.gz`

## Expected Deliverable

Return:

1. A ranked list of the actual underrepresented matchup gaps with evidence.
2. A diagnosis of why prior Lucario BC and specialist training failed.
3. The best next intervention and why it is safer than global retraining.
4. A compact, decision-complete experiment plan capped at three hours for its first informative result.
5. Any remaining questions that materially change the recommendation.
