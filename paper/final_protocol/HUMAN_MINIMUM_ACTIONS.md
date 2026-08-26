# Your minimum remaining actions (human-only)

Everything machine-resolvable has been done and verified. What is left
requires **you** — legally, scientifically, or per APS policy — and nothing
else.

## 1. Fill one file (~45–60 min)

Copy `paper/final_protocol/human_answers.template.yaml` to
`paper/final_protocol/human_answers.yaml` and complete every section:
authorship/affiliation/ORCID, CRediT, funding, conflicts, acknowledgments,
overlap disclosure language, AI-use confirmations, release rights + licenses,
D03 disposition, the ten scientific signoff booleans, prose-passage decisions,
reviewer selections, DAS version choice.
Then:

```bash
python3 paper/final_protocol/scripts/validate_human_answers.py
```

Fix anything it reports until it prints `"status": "PASS"`. It never infers an
answer for you; it only checks what you wrote.

## 2. Review at most eight prose passages (~20 min)

`paper/final_protocol/HUMAN_PROSE_REVIEW.md` — mark ACCEPT / REWRITE / DISCUSS
per passage (also mirrored in the YAML `prose_review` section). You do not need
to reread the whole manuscript beyond this packet plus your global signoff.

## 3. Approve license/archive and D03 (~10 min)

In the YAML: confirm code/data licenses (MIT / CC BY 4.0 are pre-staged as
*recommendations*), approve redistribution of processed diagnostics and of the
recovered D03 aggregates if you choose, authorize archive deposit, and
sign/date the D03 block (`supplement/PROTOCOL_DEVIATIONS_FINAL_DRAFT.md`).
Until you do: `LICENSE` files stay `.proposed`, status stays
`CANDIDATE_NOT_AUTHORIZED`, DOI stays blank. Nothing is published by the
machine.

## 4. Run one command

```bash
python3 paper/final_protocol/scripts/apply_human_answers.py --diff   # preview
python3 paper/final_protocol/scripts/apply_human_answers.py --apply  # execute
python3 paper/final_protocol/scripts/reproduce_all.py                # full re-verification
git add -A && git commit -m "Apply human closeout answers"           # commit S'
python3 paper/final_protocol/scripts/reproduce_all.py && git add paper/final_protocol/REPRODUCTION_REPORT.json paper/final_protocol/REPRODUCTION_REPORT.sha256 && git commit -m "Final reproduction report" # commit E'
python3 paper/final_protocol/scripts/verify_reproduction_report.py   # verify E' chain
```

This re-runs every gate: raw-hash verification, reaggregation, independent
statistics, synthetic suite, admission properties, tables/figures/macros,
claim ledger, novelty/reference audits, chronology audit, contradiction audit,
release rebuild, clean-environment checks, REVTeX compile, page renders,
visual audit binding, submission-bundle refresh, desk simulation.

## 5. Inspect the final PDF (~10 min)

Open `paper/final_protocol/main.pdf`; check your name/affiliation render
correctly and skim `supplement/PDF_VISUAL_AUDIT.json` (automated page checks
PASS; your visual signoff completes it).

## 6. Submit manually

Upload `submission_bundle_draft/manuscript.pdf` (+ separate Supplemental PDF
only if you opted in), paste metadata from
`submission_bundle_draft/submission_metadata.yaml`, attach
`cover_letter_final_draft.txt`, answer APS's DAS/AI questionnaire per
`APS_REQUIREMENTS_CURRENT.md`, star your PhySH terms, and submit via the APS
system yourself. The machine never uploads or submits.

**Estimated total human time: ~1.5–2 hours** (plus APS form-filling time).

### Hard stops that remain yours alone

byline order · CRediT · conflicts/funding truth · AI-use completeness ·
license choice · archive/DOI authorization · D03 signature · final manuscript
approval · submission authorization.
