# Rule 4: DeNA Production TCG Reinforcement Learning Architecture

## 1. Context & Architectural Overview
Reinforcement Learning in the Pokémon Trading Card Game environment operates under imperfect information, non-deterministic mechanics (coin flips, random deck draws), and high-dimensional combinatorial action spaces.

To achieve robust training without exponential complexity explosion or state evaluation distortion, the following architectural invariants (derived from DeNA CEDEC engineering principles) MUST be adhered to across model design, rollout collection, and training pipelines.

---

## 2. Invariants

### Invariant 4.1: Atomic Action Builder Decomposition
- **Compound Action Decomposition**: All multi-step gameplay decisions (e.g. *Evolution: choose action $\to$ select target Basic Pokémon $\to$ select evolution form card*; or *Trainer card: play card $\to$ select target Pokémon $\to$ discard energy*) MUST be decomposed into sequential single-decision **atomic actions**.
- **Action Builder Intermediary**: An `Action Builder` abstraction must mediate between the RL policy and the underlying game simulator. The policy outputs atomic decisions sequentially; once the Action Builder confirms the composite decision is complete, it dispatches the bundled action to the game engine in a single execution step.
- **Forced Move / Singleton Bypass**: When only 1 legal atomic action is available in a given state, the simulation environment MUST automatically execute the action without invoking neural network inference. This:
  1. Accelerates rollout episode generation.
  2. Reduces inference computation.
  3. Eliminates trivial singleton transitions from training replay buffers.
  4. Effectively extends the temporal credit lookahead (TD steps).

### Invariant 4.2: Field State Encoder & Action Selection Decoupling
- The battle AI architecture MUST structurally separate:
  1. **Field State Representation Backbone**: A shared encoder (e.g. Transformer / dense network) that processes global field state, card attributes, energy pools, and hand/bench configurations.
  2. **Atomic Action Selection Head**: A lightweight policy head that scores available legal atomic actions given the field representation.
- **Intra-Turn Embedding Reuse**: Within a single turn's sequential atomic choices where the underlying field state has not mutated, the computed field embedding MUST be cached and reused across sub-actions rather than recomputed.

### Invariant 4.3: Intra-Turn Credit Assignment & Zero-Discounting
- **Sub-Evaluation Resolution**: Because intermediate atomic actions do not mutate the board state ($\Delta V(s) = 0$), assigning standard per-step TD error to intermediate steps produces zero or misleading gradient signals.
- **Uniform Target Feedback**: When the final atomic action completes and the game board updates, the total evaluation improvement $\Delta V$ must be broadcast as identical target feedback across all constituent atomic actions that formed the compound move.
- **Zero Discounting Across Intra-Turn Steps**: For transitions between intra-turn atomic steps where board state is static, the discount parameters MUST be fixed to $\gamma = 1.0, \lambda = 1.0$ (no discount rate decay across atomic sub-decisions).

### Invariant 4.4: Policy Penalty Terms vs. State-Value Poisoning
- **Problem**: When agents make suboptimal card usage errors (e.g. playing retreat energy reduction like *Speed Up* without retreating, or attacking with self-damaging moves when HP is critical), applying a direct negative environment reward causes the value network $V(s)$ to perceive the mere presence of the card or Pokémon on the board as inherently negative.
- **Invariant**: Suboptimal card-usage penalties MUST be applied as an auxiliary policy loss penalty term ($\mathcal{L}_{penalty}$ / loss regularizer) targeting the action probability $\pi(a|s)$ rather than polluting the environmental state reward $R(s, a)$ or value baseline $V(s)$.
- **Auxiliary Condition Features**: The observation feature vector MUST expose explicit binary status flags (e.g. `retreat_cost_reduced_this_turn`, `energy_attached_this_turn`) so the policy has direct visibility over active intra-turn constraints.

### Invariant 4.5: Hierarchical Synergy-Tree Deck Generation & Targeted Over-Sampling
- **Synergy Candidates**: Synthetic and procedural deck generation for self-play training must treat Basic Pokémon and their evolution forms as unified candidate units rather than disjoint random cards.
- **Parent-Child Dependency Trees**: Cards with strict prerequisites (e.g. cards requiring a specific Pokémon ex on field or specific energy types) must be configured in a parent-child dependency tree so child cards only enter the candidate sampling pool when their parent prerequisite is present in the deck.
- **Targeted Over-Sampling for Complex Cards**: Cards with complex conditional mechanics, high energy requirements, or risk-reward trade-offs (e.g. retreat accelerators, self-damaging moves) MUST have their sampling probability upweighted during training deck generation. This guarantees the RL agent experiences sufficient positive and negative trials to balance credit assignment.
