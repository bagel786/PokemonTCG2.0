# Pokémon TCG AI Competitive Guardrails & Empirical Standards

## 1. No Heuristic Loss-Bucket Upweighting
- Never apply arbitrary scalar multipliers to loss episodes during behavioral cloning.
- All trajectory weighting must be grounded in empirical Advantage-Filtered Behavioral Cloning (AFBC):
  $$A(s, a^*) = Q(s, a^*) - Q(s, a_{\text{incumbent}}) \ge \delta$$
  where $\delta \ge +0.50$ selects only counterfactual moves that provably improve expected match value.

## 2. Selective 1-Ply Forward Search
- In ambiguous decision states ($\Delta \text{logit} < 0.35$), forward search must simulate deterministic actions (Energy attachment, Evolution, Bench Basic, Retreat, Abilities).
- Always ensure native C++ memory cleanliness (`search_release` and `search_end` inside strict `try...finally` blocks).
- Fast-path fallback when opponent archetype Jaccard match is $< 0.35$.

## 3. Replay Regression Testing
- Every candidate release must be tested against extracted historic blunder positions (`tests/test_live_mirror_forensics.py`) to verify that passive drift or energy hoarding is actively overridden.

## 4. Tiered Statistical Gating Invariants
- **Tier 1 (Fast Sanity Screen)**: $n=200$ games ($p < 0.05$, $>50\%$ WR vs standard archetypes).
- **Tier 2 (Meta Gauntlet)**: $n=1,000$ games across top 5 meta decks ($>52\%$ WR, $p < 0.05$).
- **Tier 3 (Deep Mirror Validation)**: $n=5,000$ games ($>53\%$ WR vs incumbent control).
