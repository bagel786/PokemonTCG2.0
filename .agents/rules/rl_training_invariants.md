# Rule 1: The Dual-Anchor Principle for League & Sparring

## 1. Context & Root Cause
Analysis of the 975 Elo 5k Grimmsnarl model (`grim_selected.npz`) vs. regressed longer runs (10k–20k games) revealed:
- **Elite Pretraining Value**: 468,506 elite human tournament decisions (4,710 high-tier matches) gave the model 72.49% exact action prediction accuracy.
- **Anchor Necessity**: Unconstrained RL or RL with low/zero Behavioral Cloning (BC) weight quickly washes away these tournament-grade macro priors, causing agents to exploit narrow simulator bugs and overfit to bot artifacts.
- **Intransitive Policy Cycling**: Training 100% against a single bot opponent causes policies to specialize in non-generalizable counter-strategies ("cheese" lines) that fail against the general ladder population.

---

## 2. Invariants

### Invariant 1.1: Human Prior Anchor (`bc_weight >= 0.05`)
- Every PPO fine-tuning run MUST include at least one representative elite BC shard (`--bc-shard`) and a positive BC regularization weight (`bc_weight >= 0.05`, default `0.50`).
- Unanchored training (`bc_weight = 0.0` or missing `--bc-shard`) is strictly prohibited for competitive production models, and is only permitted for diagnostic ablation tests via the explicit `--allow-unanchored-training` flag.

### Invariant 1.2: Meta Anchor Distribution (>= 30–40%)
- No learner may be trained with 100% of its rollouts concentrated against a single opponent.
- Every sparring or league configuration MUST maintain at least 30–40% games allocated across:
  1. Diverse meta archetypes (`team_rockets_mewtwo_ex`, `kangaskhan_crustle`, `dragapult_ex`, `cynthias_garchomp_ex`, etc.).
  2. Frozen historical elite submissions (`alakazam_2_7`, `alakazam_2_4a`).

### Invariant 1.3: Conservative Trust Region Bounds
- PPO updates must enforce strict KL divergence limits:
  - `target_kl <= 0.02` (step target)
  - `hard_kl <= 0.04` (rollback boundary)
  - `clip_ratio <= 0.20`
  - Max epochs per iteration: 2–3 epochs.

### Invariant 1.4: Going-Second (Seat 1) Over-Sampling & Turn-1 Defensive Benching
- For Stage-2 setup archetypes (such as Grimmsnarl), rollout collection must sample Going-Second (Seat 1) at **60% frequency** (`--seat-1-ratio 0.60`) to overcome the natural tempo deficit.
- An auxiliary reward bonus (+0.05) must be attached to opening trajectories when $\ge 2$ Basic Pokémon are benched by Turn 1 to prevent early bench extinctions (the cause of ~50% of losses).

### Invariant 1.5: Asymmetric Sparring Allocation
- In multi-archetype co-evolution rounds, allocate **50% of the rollout compute directly to the primary champion** (e.g. 10,000 games) and split the remaining 50% across secondary sparring bots (2,000 games each) so secondary bots continuously evolve without diluting hero training volume.

### Invariant 1.6: Policy Penalty Isolation (Anti-Value Poisoning)
- Do NOT apply negative environment rewards to state-value targets for bad intra-turn action sequences or self-damage moves.
- Penalties for suboptimal card combinations (e.g. playing retreat cost reduction without retreating, or self-destructive damage) MUST be implemented as policy loss penalty terms $\mathcal{L}_{penalty}$, preserving unbiased $V(s)$ baseline estimates.

### Invariant 1.7: Intra-Turn Atomic Credit Assignment
- For multi-step atomic action sequences without intermediate board mutations, apply undiscounted TD targets ($\gamma = 1.0$) across all sub-actions, assigning the full terminal compound outcome uniformly to each atomic choice.

### Invariant 1.8: Dual-Track Competition Strategy (Data-Centric vs. Co-Evolutionary)
The competitive pipeline must maintain two distinct, parallel development tracks:

1. **Track A (Data-Centric Elite Distillation)**:
   - **Base Model**: Initialized directly from the proven `grimmsnarl_5k_reference.npz`.
   - **Data Ingestion**: Ingest fresh daily top-tier episode datasets (`scripts/fetch_public_data.py`), extract model-ready decisions from top leaderboard teams, and refresh `elite_prior.json`.
   - **Training Objective**: Supervised fine-tuning / high-anchor PPO ($c_{\text{bc}} \ge 0.35 - 0.50$) prioritizing general ladder consistency and zero policy drift.

2. **Track B (Co-Evolutionary Adversarial RL)**:
   - **Base Model**: Evolving generation champions (`artifacts/coevo_run_XX/`).
   - **Environment**: Multi-agent league cross-play with asymmetric allocation (10,000 games on champion, 2,000 on meta archetypes).
   - **Training Objective**: Invariant 1.6 blunder suppression ($\mathcal{L}_{\text{penalty}} = 0.10$), Invariant 1.7 intra-turn credit ($\gamma_{\text{intra}} = 1.0$), and Seat-1 over-sampling (60%).

3. **Fleet Deployment**:
   - Maintain active ladder slots for both Track A and Track B to hedge against meta variance and capture distinct win profiles.

