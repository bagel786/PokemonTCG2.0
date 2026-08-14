# Final Grimmsnarl Sprint Plan
**Date:** August 14, 2026
**Target:** Marnie's Grimmsnarl ex / Froslass (33.3% Top 50 Meta Share)

## Objective
With the submission deadline approaching and Dragapult proving unviable, we are committing fully to defeating the dominant leaderboard deck: **Marnie's Grimmsnarl ex / Froslass**. Our primary agent must reliably survive Grimmsnarl's energy disruption and Froslass's bench chip damage.

## Context & Meta State
*   Based on our live leaderboard survey (`data/meta/rank_bands.json`), Grimmsnarl accounts for **33.3% of the Top 50 teams** and **42 of the Top 150**.
*   We cannot pivot archetypes this late. We must patch our existing core model (`master_v1` / `a2`) to handle this specific matchup flawlessly.

## Phase 1: Baseline Evaluation (Morning)
1.  **Generate Ground Truth:** Run the `master_v1` (or current final candidate) directly against the `grim_proxy_gate` or `run_azure_direct_adversary_screen.py` focusing strictly on Grimmsnarl replays.
2.  **Measure Variance:** We need a minimum of 400 games to measure our exact baseline win-rate and prize differential. 
3.  **Identify Failure Modes:** Does the model lose to:
    *   Getting locked out of energy attachments (Marnie disruption)?
    *   Losing support Pokémon to Froslass ability chip damage?
    *   Failing to close the last 2 prizes?

## Phase 2: Directed Fixes (Afternoon)
Depending on the Phase 1 diagnostics, we will execute one of the following:

*   **Option A (Behavioral Cloning Correction):** If the model is making blatant strategic errors (e.g., misusing Boss's Orders, failing to attach energy from the discard, mismanaging bench slots), we will isolate 1,000 elite human replays where the human defeats Grimmsnarl using our archetype. We will then run a targeted finetuning/BC sprint on these specific states.
*   **Option B (Context Gate / Empirical Router):** If our main model is structurally weak against Grimmsnarl but an older checkpoint or specialized agent (like `a2_damage_value_search`) performs better, we will update the empirical policy router (`scripts/package_empirical_policy_router.py`) to swap models specifically when Grimmsnarl is detected across the table.
*   **Option C (RL / PPO Tuning):** If time permits and the infrastructure is warm, resume `run_azure_order_ppo.py` with the reward function heavily skewed toward surviving energy droughts and protecting bench targets.

## Phase 3: Final Validation & Package
1.  Run the updated agent through the `comprehensive_sandbox_audit.py` to ensure patching Grimmsnarl didn't severely regress our Alakazam or Lopunny matchups (the next two most popular decks).
2.  Package for submission.
