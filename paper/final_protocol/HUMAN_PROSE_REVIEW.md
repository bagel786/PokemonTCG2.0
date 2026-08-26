# Human prose-review packet

**Purpose.** The machine pass performed one conservative scientific edit
(~3–4% main-text reduction; deeper cuts would have removed qualifications you
must keep). You do **not** need to reread every line. Review only the eight
passages below — chosen because personal understanding must be evident there,
the wording is unusually dense, AI-authorship questions could plausibly arise,
or chronology/contribution is central — then mark each checkbox
(`ACCEPT` / `REWRITE` / `DISCUSS`). Everything else in the manuscript is covered
by your global signoff in `human_answers.template.yaml`
(`scientific_signoff.final_manuscript`) plus the claim-ledger worksheet.

Article: *A Protocol for Validating Pairing Assumptions in Seed-Matched
Evaluations of Black-Box Game-Playing Agents* (APS Open Science Protocol
Article). Manuscript: `paper/final_protocol/main.tex`.

---

## Passage 1 — Abstract, opening problem statement

**Location:** Abstract, sentences 1–2.

**Current text:**
> When two game-playing agents are evaluated under the same recorded seed, the shared value names a matched schedule; it does not by itself establish repeatable execution or equal random quantities for the same semantic events.

**Why human review matters:** These are the first words every editor and
reviewer reads; they must sound like your own framing of the problem.

**Suggested simplified text (meaning-equivalent):**
> Two agents evaluated under the same recorded seed share a schedule, but that alone does not guarantee they executed the same random events.

**Exact meaning that must not change:** a recorded seed ⇒ matched *schedule*
only; repeatability and per-event equality of random quantities are separate,
unproven properties.

**Your decision:** [ ] ACCEPT  [ ] REWRITE  [ ] DISCUSS

---

## Passage 2 — Contribution boundary (Introduction, closing paragraph)

**Location:** Introduction, final paragraph.

**Current text:**
> Prior work supplies conditional CRN theory, structured random streams, trace preservation, deterministic testing, and event-keyed randomness. This work integrates those components into an executable protocol that maps recorded evidence to the paired claim it permits. The restricted game environment is a case study, not the title-level contribution, and no competitive-strength claim is made.

**Why human review matters:** This is the novelty claim. You must personally
own the boundary (integration, not component invention) — an AI-sounding or
overreaching version here invites both integrity and referee problems.

**Suggested simplified text:**
> None of those components is new here. What this protocol adds is their integration into an executable procedure that decides which paired claim the recorded evidence supports. The game engine is only a case study; no agent-strength claim is made.

**Exact meaning that must not change:** integration-only contribution;
executable evidence-to-claim mapping; case-study status of the game
environment; explicit absence of strength claims; no priority language
("first/novel") anywhere.

**Your decision:** [ ] ACCEPT  [ ] REWRITE  [ ] DISCUSS

---

## Passage 3 — Stage 6 outcome taxonomy

**Location:** Section "Pairing-assumption validation protocol", Stage 6 paragraph (the five outcomes).

**Current text:**
> Every audit resolves to exactly one of five outcomes. Controlled: … Unresolved: a hit exists without sufficient evidence, and no automatic pass exists.

**Why human review matters:** Densest methodological passage; you may be asked
to defend it orally (defense guide Q6/Q15).

**Suggested simplified text:**
> Each source audit ends in exactly one of five labeled states, from fully controlled mechanisms through residual risk, estimand-changing findings, unavailable black-box sources, and unresolved hits; only the first licenses stronger wording, and every state carries a required next step defined by machine-readable rules.

**Exact meaning that must not change:** five mutually exclusive outcomes;
residual ⇒ downgrade; estimand-changing ⇒ suppression of paired mechanistic
wording; unavailable blocks source-level claims; unresolved has no automatic
pass; remediations are rule-generated, not ad hoc.

**Your decision:** [ ] ACCEPT  [ ] REWRITE  [ ] DISCUSS

---

## Passage 4 — Admission-map result independence

**Location:** Section "Executable admission map and formal properties", proposition paragraph.

**Current text:**
> For any structurally valid evidence record, the implemented admission map is result independent, prerequisite monotone, failure dominant, projection scoped, statelessly deterministic, and fail closed for unknown states.

**Why human review matters:** Central formal claim; if you cannot restate it
in your own words, that is exactly what the comprehension signoff is for.

**Suggested simplified text:**
> Whatever outcomes a record contains, the admission decision depends only on the gate evidence: better results never improve a claim, weaker evidence never strengthens one, decisions are confined to the declared fields, identical records always produce identical decisions, and anything unrecognized fails closed.

**Exact meaning that must not change:** all six named properties + strict claim
ordering; property tests enumerate six states × seven gates; tampering
rejected.

**Your decision:** [ ] ACCEPT  [ ] REWRITE  [ ] DISCUSS

---

## Passage 5 — Chronology of frozen vs. post-acquisition rules

**Location:** Section "Prospective validation results", opening paragraph.

**Current text:**
> The experiment-specific protocol content first appears at commit 803257f1, and the retained result artifacts appear in descendant commits; repository history establishes only that Git ordering, not when a human inspected uncommitted files. … None of these later additions is attributed to that commit, and the completed case does not prospectively validate them; future users should freeze them before collecting outcomes.

**Why human review matters:** This is the honesty core of the paper's
chronology claim; reviewers hostile to "Git-as-preregistration" will probe it,
and only you know what you actually saw and when.

**Suggested simplified text:**
> Commit ordering shows the frozen protocol predates the retained results, but it cannot show when a human read uncommitted outputs. The generic claim taxonomy, descriptive relabeling, and digest-plus-byte check came later; they narrow what is claimed and were never validated prospectively in this study, so future users should freeze them before collecting data.

**Exact meaning that must not change:** Git proves ordering only; three named
post-acquisition additions; narrowing not validating; freeze-before-acquisition
recommendation.

**Your decision:** [ ] ACCEPT  [ ] REWRITE  [ ] DISCUSS

---

## Passage 6 — Historical suppression paragraph

**Location:** Section "Restricted game-agent case study", historical-audit paragraph.

**Current text:**
> That audit rule was frozen only for retrospective reanalysis after the historical outcomes already existed. Its rule consumes only repeated control-arm records, so it is independent of candidate-effect magnitude, direction, or favorability, but it is not outcome blind in a literal sense, and the exercise is not evidence of prospective blinding or pre-acquisition specification.

**Why human review matters:** The paper's most sensitive honesty statement:
a favorable comparison was suppressed by a retrospectively frozen rule. Your
personal understanding here anchors the integrity narrative.

**Suggested simplified text:**
> This audit rule was written down only after the historical outcomes existed. Because it reads only repeated control-arm records, it cannot favor any candidate effect — but it is therefore also not literally outcome blind, and it does not demonstrate prospective blinding.

**Exact meaning that must not change:** retrospective freezing; control-record
input only; independence from magnitude/direction/favorability; not literal
outcome blindness; not evidence of prospective blinding; 210/2,800 and
458/2,800 counts unchanged; suppression consequence preserved.

**Your decision:** [ ] ACCEPT  [ ] REWRITE  [ ] DISCUSS

---

## Passage 7 — Unresolved factorial contrast

**Location:** Section "Claim-admission consequence", second paragraph.

**Current text:**
> The total fixed-package contrast on that battery was +0.55 percentage points. The 2.5th and 97.5th percentiles from the prespecified stratified paired-unit resampling algorithm, relabeled as descriptive empirical reweighting, were [−2.05, +3.15]. They span both signs; no null test, population effect, or equivalence conclusion is drawn.

**Why human review matters:** The one quantitative result readers will quote;
you must be able to say precisely why it settles nothing.

**Suggested simplified text:**
> The battery-level difference was +0.55 percentage points, and resampling the same fixed battery gave a descriptive range of −2.05 to +3.15 percentage points. Because the interval spans zero and describes only this battery, it supports no conclusion about nullness, equivalence, superiority, or any population.

**Exact meaning that must not change:** quantiles are empirical reweighting /
descriptive sensitivity — never confidence intervals or tests; fixed-battery
scope; no inference in either direction; McNemar value stays out of admitted
inference.

**Your decision:** [ ] ACCEPT  [ ] REWRITE  [ ] DISCUSS

---

## Passage 8 — Conclusion

**Location:** Section "Conclusion".

**Current text:**
> A seed schedule, a repeatable execution, and an event-aligned stochastic coupling are different scientific objects. The protocol connects each object to observable evidence and to a fail-closed reporting consequence that future users must freeze before acquisition. …

**Why human review matters:** Last impression; should read as the author's own
takeaway, not a compliance summary.

**Suggested simplified text:**
> Sharing a seed, rerunning identically, and aligning random events are three different achievements. This protocol says which observable checks distinguish them and what claim each level of evidence buys — and it refuses to buy a claim when required evidence is missing.

**Exact meaning that must not change:** the three-object distinction; evidence
ladder → claim mapping; fail-closed suppression; freeze-before-acquisition
recommendation.

**Your decision:** [ ] ACCEPT  [ ] REWRITE  [ ] DISCUSS

---

**Return path:** mark decisions above (or edit `human_answers.template.yaml`
section `prose_review.passage_decisions`), then run
`python paper/final_protocol/scripts/apply_human_answers.py --diff` followed by
execution after inspection; the reproduction pipeline revalidates everything.
