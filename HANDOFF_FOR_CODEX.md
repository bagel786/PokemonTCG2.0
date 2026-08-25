# HANDOFF — continue APS submission closeout here

Date: 2026-08-25. Written by the closeout agent that performed Phases 0–25.
**Nothing below is fabricated.** Read `HUMAN_ACTIONS_FINAL.md` first — every
remaining blocker is a human action; the science is done.

## 1. Where you are

- Repo: `/Users/safiullahbaig/Projects/pokemonTCG2.0` (GitHub `bagel786/PokemonTCG2.0`)
- Branch: **`paper/apsos-submission-closeout-20260825`** (create everything here; do NOT rebase/rewrite)
- Article: APS Open Science Protocol Article — "A Protocol for Validating Pairing
  Assumptions in Seed-Matched Evaluations of Black-Box Game-Playing Agents"
- Manuscript dir: `paper/final_protocol/`
- Last 12 commits listed below; working tree currently has `REPRODUCTION_REPORT.json` + `.sha256` dirty at **RUNNING** status — residue from an aborted pipeline run. **First action: rerun the pipeline (Section 3) to regenerate them; do not commit the RUNNING state.**

## 2. What is DONE (verified, committed)

- **STARTING_CLOSEOUT_STATE.json** (phase snapshot; `STARTING_STATE.json` re-chained to this branch).
- **HUMAN_CLOSEOUT_FORM.md** — the single human questionnaire (authorship, affiliation, contact, CRediT, funding, conflicts, acknowledgments, overlap, AI use, release rights, D03, scientific signoff). All answers PENDING.
- **D03 partially recovered**: acting-side first-divergence counts (`{opponent: 99}`) and per-profile timing summaries recovered from the hash-pinned stress summary and added to the release with `recovered_secondary_outputs_provenance`. Positions were never recorded → documented as deviation; register stays UNSIGNED until human disposition.
- **Chronology fixed** in prose + `CHRONOLOGY_AUDIT.json`: frozen protocol (commit `803257f1`) already contained the full 8-stage ladder + binary gates; only generic claim-class taxonomy, descriptive relabeling, and byte-count extension are post-acquisition.
- **"outcome independent" → "independent of candidate-effect magnitude, direction, or favorability"**; generic map keeps "result independent" backed by `test_result_independence_replaces_all_result_values` (release tests).
- **Stage 4/5**: renamed "within-artifact fresh-process repeatability"; nesting in Stage 5 documented; machine-checkable certificate fields added (`required_profiles`, `compared_record_fields`, `record_binding`); launch provenance declared an external trust anchor.
- **Stage 6**: machine-readable `protocol/stage6_source_audit_rules.json` + `pevl_bench/stage6_rules.py` + generated `docs/STAGE6_DECISION_RULES.md` + 11 tests. Outcomes CONTROLLED/RESIDUAL/ESTIMAND_CHANGING/UNAVAILABLE/UNRESOLVED.
- **Level 6/7 narrowed (Option B)** explicitly in manuscript.
- **Abstract rewritten** (185 words, required 8-sentence arc). **Adoption paragraph** for adjacent computational sciences added. **Cover letter rewritten** (factorial = 1 sentence). **DAS rewritten** (Public/Restricted, editorial-risk flagged). **Defense guide V2** (29 questions × short/technical/source/failure-mode). **CLAIM_LEDGER_HUMAN_SIGNOFF.md** (33 curated + bulk automatic attestation). **RELEASE_OWNERSHIP_MATRIX.csv** (all approvals PENDING). **EQUATION_AUDIT_V2.md** (Eq. 3 equal-weight-of-stratum-means clarification). **NOVELTY_AUDIT_V2.md + NOVELTY_SEARCH_LOG_V2.json** + 2 new close works added to `references.bib`, `REFERENCE_AUDIT.csv/V2`, `NOVELTY_MATRIX.csv` (Kaliyev & Maryanskyy noise-floor protocol; Zhang & Lee protocol cards — both verified against camera-ready PDFs + workshop site; non-archival, never described as peer-reviewed).
- **Desk review V2** (`DESK_REVIEW_SIMULATION_V2.json` + `reviews_v2/`): A=BORDERLINE(scope-only), B/C/D/E=SEND_TO_REVIEW → **SCIENTIFIC_DESK_GATE = PASS**; **SUBMISSION_COMPLETENESS_GATE = BLOCKED_BY_HUMAN_ACTIONS**.
- **OXFORD_FAILURE_MODE_AUDIT.md** written; **HUMAN_ACTIONS_FINAL.md** written.
- **Clean env**: `.venv-clean` (CPython 3.11.5 + numpy 2.4.6, matplotlib 3.10.5, pytest 9.1.1) → 60/60 release tests + generate/verify/report/verify_release PASS; `CLEAN_ENV_REPRODUCTION.json` written; `reproduce_all.environment_record()` now reads it. **NOTE: `.venv-clean` is gitignored? — check; recreate if missing.**
- **`ADMITTED_SEED_MATCHED`** retained as `legacy_acquisition_status`; `final_reporting_status=ADMITTED_FIXED_BATTERY_DESCRIPTIVE` added and surfaced in CLI.
- Release bundle rebuilt with new trust anchor (`EXPECTED_PROTOCOL_BUNDLE_SHA256 = 25291c7e6b132db1148d9ea3a87648a2bf992af095abeae473844258bcae17c3` in `admission.py` — evidence.py change; update together if you ever change evidence.py again).

## 3. What remains (exact order)

1. **Rerun the full pipeline to green** (the ONE blocking machine item):
   ```
   .venv-clean/bin/python paper/final_protocol/scripts/reproduce_all.py
   ```
   Wait for `{"status": "PASS"}`. It requires a CLEAN worktree (report envelope excluded) and runs ~20–40 min. Iterate on any audit failures (readability thresholds: ≤55-word sentences, ≤220-word paragraphs; visual attestation binds main.tex/main.pdf hashes — if you touch prose, recompile via `tectonic main.tex`, re-render 150dpi PNGs, and rewrite `supplement/PDF_VISUAL_AUDIT.json` exactly per schema with `human_submission_signoff: "PENDING"`). Then commit the report + sidecar.
2. **Commit** the regenerated `REPRODUCTION_REPORT.json` + `.sha256` (schema v2).
3. **Push**: `git push -u origin paper/apsos-submission-closeout-20260825` (user asked for push; safe — new branch, no history rewrite).
4. **Hand back to the human** with `HUMAN_ACTIONS_FINAL.md`: they must fill `HUMAN_CLOSEOUT_FORM.md`, sign D03, approve license/DOI, sign signoffs. Then re-run pipeline and submit via APS (human uploads; tooling must not submit).

## 4. Gotchas / binding constraints

- **Do not** overwrite `paper/data/pevl/*`, `paper/data/ablation/*`, `paper/protocol/*` (hash-pinned inputs in `build_final_release.py` `PINNED_INPUTS`).
- **Do not** delete audit evidence or rewrite history.
- **Do not** fabricate: author metadata, signatures, licenses, DOI, CRediT, conflicts, AI-use completeness, ownership. All live in `HUMAN_CLOSEOUT_FORM.md` → `HUMAN_ACTIONS_FINAL.md`.
- Manuscript edits: keep the machine-checked disclosure patterns intact (`audit_contradictions.check_protocol_reporting_provenance`; `verify_research_audits` requires CSV `manuscript_sentence_supported` to exist verbatim in main.tex canonical prose — if you split/rewrite a bound sentence, update `REFERENCE_AUDIT.csv`, `REFERENCE_AUDIT_V2.csv`, `NOVELTY_MATRIX.csv` rows to a surviving contiguous sentence).
- After ANY main.tex or script change: regenerate claim ledger (`.venv/bin/python scripts/build_claim_ledger.py`), readability (`audit_readability.py`), research audits (`verify_research_audits.py`), then pipeline.
- TeX: use `tectonic` (PATH `/opt/homebrew/bin/tectonic`); TinyTeX at `~/Library/TinyTeX/bin/universal-darwin` has revtex4-2 installed if you need pdflatex.
- Report runs inside `.venv-clean` so `environment_record()` observes declared versions; `.venv` (drifted: numpy 2.4.6/pytest 9.1.1 — matches lockfiles) also works, but `.venv-clean` is the attested clean env.

## 5. Key files

- Human gate: `paper/final_protocol/HUMAN_ACTIONS_FINAL.md`, `HUMAN_CLOSEOUT_FORM.md`
- Science gate: `DESK_REVIEW_SIMULATION_V2.json`, `OXFORD_FAILURE_MODE_AUDIT.md`, `NOVELTY_AUDIT_V2.md`, `EQUATION_AUDIT_V2.md`, `CHRONOLOGY_AUDIT.json`
- Release: `release/` (built), `release_templates/` (source of truth)
- Report: `REPRODUCTION_REPORT.json` + `.sha256` (schema v2, currently RUNNING)