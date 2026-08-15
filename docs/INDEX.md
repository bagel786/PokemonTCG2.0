# Pokemon TCG AI Battle - Documentation Index

This directory contains research, logs, and sprint plans for the project. The files have been reorganized by category to help agents and developers quickly find relevant context.

## Directory Structure

### `/core`
Core project architecture, experimental findings, and high-level strategy documents.
*   `PROJECT_SUMMARY.md` - Overall system overview and agent pipeline.
*   `OPERATIONS.md` - Runbooks for cloud/Azure tasks and general ops.
*   `KAGGLE_API_RATE_LIMITS.md` - READ BEFORE any Kaggle API work: rate-limit forensics, safe endpoints, rules (429 handling, daily-dataset bulk path).
*   `EXPERIMENTS.md` - Running log of major experimental setups and results.
*   `RL_PLAN.md` - Reinforcement learning strategy and architecture.

### `/sprints/grimmsnarl` (ACTIVE FOCUS)
Documents related to evaluating and improving performance against the current meta-dominant Grimmsnarl ex / Froslass archetype.
*   **`GRIMMSNARL_FINAL_SPRINT.md` - (CURRENT SPRINT)** The active plan for addressing the Grimmsnarl matchup.
*   `grim_recovery_analysis.md`
*   `grim_recovery_runbook.md`

### `/sprints/dragapult` (ABANDONED)
Documents from the recently abandoned Dragapult behavioral cloning emergency sprint.
*   `DRAGAPULT_EMERGENCY_SPRINT.md`
*   `DRAGAPULT_EMERGENCY_FEASIBILITY.md`

### `/sprints/dipplin`
Documents from the evaluation and optimization sprints for the Dipplin archetype.
*   `DIPPLIN_EXPERT_POLICY_AUDIT.md`
*   `DIPPLIN_GENERAL_STRENGTH_SPRINT.md`
*   `DIPPLIN_PROMPT_AUDIT.md`
*   `DIPPLIN_SECOND_ORDER_GENERALITY.md`
*   `DIPPLIN_STRATEGY_MODEL.md`
*   `DIPPLIN_STRENGTH_AND_HELDOUT_EVAL.md`

### `/sprints/strength_and_a2`
Documents evaluating overall agent strength, ladder comparisons, and the A2 (Alakazam) model branch.
*   `EMERGENCY_OVERALL_STRENGTH_PLAN.md`
*   `EMERGENCY_STRENGTH_SPRINT.md`
*   `LIVE_LADDER_D842_VS_A2.md`
*   `A2_SHIELDED_OUTCOME_PPO_AUDIT.md`
*   `FRESH_A2_ONPOLICY_Q_SCREEN.md`

### `/playbooks`
Strategic playbooks and router implementations for handling multi-archetype environments.
*   `STRATEGIC_PLAYBOOK_V2.md`
*   `STRATEGIC_PLAYBOOK_V2_FOCUSED.md`
*   `MATCHUP_PLAYBOOK_IMPLEMENTATION.md`

### `/archive_and_logs`
Older evaluation logs, overnight run reports, and early data refresh results.
*   `5k_early_ladder_variance_20260802.md`
*   `5k_replay_refresh.md`
*   `DETERMINISTIC_CRN_EVALUATION.md`
*   `OVERNIGHT_2026-07-30.md`
*   `SEEDED_Q_EXPECTED_ADVANTAGE_AUDIT.md`
*   `SEEDED_Q_PILOT.md`

### `/strategy`
(Legacy directory containing specific tactical or deck strategy documentation)
