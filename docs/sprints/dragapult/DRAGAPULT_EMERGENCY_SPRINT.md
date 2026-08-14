# Dragapult Emergency Sprint - Final Report

## Summary of Work Done
- Evaluated `bc_combined_grim3.npz` (6 epochs, grim-weighted) against Grimmsnarl A2+Damage V0: 13.5% win rate (27/200 games).
- Evaluated `bc_combined_8ep.npz` (8 epochs, unweighted) against Grimmsnarl A2+Damage V0: 18.0% win rate (36/200 games).

## Analysis
Both longer training (8 epochs) and targeted data upweighting (Grimmsnarl row ×3 weight) failed to significantly improve the behavior clone's win rate against the primary gating opponent, Grimmsnarl A2+Damage V0. The win rate remained stuck under the 20% failure threshold (13.5% and 18.0%, respectively), failing to reach the ~40% required for a recovery signal.

Since both variants are catastrophically weak in the critical A2+Damage bucket—a bucket the actual human teachers win ~90% of the time—the BC approach on the current dataset surface is insufficient to produce a robust final candidate without deep architectural or strategic changes that exceed the emergency timeline.

## Verdict
DRAGAPULT_BC_WEAK
