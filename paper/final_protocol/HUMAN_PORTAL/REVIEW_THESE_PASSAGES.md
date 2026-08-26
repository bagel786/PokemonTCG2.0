# Review These Passages

These are the only parts of the paper where your personal voice and judgment
matter most. For each: read **CURRENT TEXT** and the plain-English meaning,
then tick **one** box. You do not need to read the code, audits, or the rest
of the repository. (Full manuscript is in
`FINAL_MANUSCRIPT_FOR_REVIEW.pdf` if you want it.)

---

## 1. Abstract (opening)

**CURRENT TEXT**
> When two game-playing agents are evaluated under the same recorded seed, the shared value names a matched schedule; it does not by itself establish repeatable execution or equal random quantities for the same semantic events.

**WHY YOU SHOULD READ THIS:** these are the first words every editor and
reviewer sees; they should sound like you.

**PLAIN-ENGLISH MEANING:** writing the same seed on two score sheets does not
mean the two games actually played out the same way.

**OPTIONAL SIMPLIFIED VERSION**
> Two agents evaluated under the same recorded seed share a schedule on paper, but that alone does not guarantee they executed the same random events.

**HUMAN DECISION:**
[ ] Keep  [ ] Use simplified version  [ ] I want to rewrite it  [ ] I do not understand this

---

## 2. Contribution statement (Introduction, closing)

**CURRENT TEXT**
> Prior work supplies conditional CRN theory, structured random streams, trace preservation, deterministic testing, and event-keyed randomness. This work integrates those components into an executable protocol that maps recorded evidence to the paired claim it permits. The restricted game environment is a case study, not the title-level contribution, and no competitive-strength claim is made.

**WHY YOU SHOULD READ THIS:** this is the novelty claim; you must personally
own it (integration, not invention of the components).

**PLAIN-ENGLISH MEANING:** none of the ingredients is new; what's new is
packaging them into a procedure that decides which statistical comparison the
evidence actually supports. The game is only the test case.

**OPTIONAL SIMPLIFIED VERSION**
> None of those ingredients is new here. What this protocol adds is their integration into an executable procedure that decides which paired comparison the recorded evidence supports. The game engine is only a case study; no agent-strength claim is made.

**HUMAN DECISION:**
[ ] Keep  [ ] Use simplified version  [ ] I want to rewrite it  [ ] I do not understand this

---

## 3. What was frozen before vs. added after the data (chronology)

**CURRENT TEXT** (excerpt)
> The experiment-specific protocol content first appears at commit 803257f1, and the retained result artifacts appear in descendant commits; repository history establishes only that Git ordering, not when a human inspected uncommitted files. … None of these later additions is attributed to that commit, and the completed case does not prospectively validate them; future users should freeze them before collecting outcomes.

**WHY YOU SHOULD READ THIS:** this is the honesty core of the paper — what
was promised before the data and what was added after. Only you know what you
actually saw and when.

**PLAIN-ENGLISH MEANING:** the rulebook was committed before the results in
the repository history, but Git can't prove when a human actually read
unfinished results; the generic claim-classification rules came later and are
disclosed as later additions.

**OPTIONAL SIMPLIFIED VERSION**
> Commit ordering shows the frozen rulebook predates the retained results, but it cannot show when a human read uncommitted outputs. The generic claim taxonomy, the descriptive relabeling, and the byte-count check came later; they narrow what is claimed and were never validated in advance in this study.

**HUMAN DECISION:**
[ ] Keep  [ ] Use simplified version  [ ] I want to rewrite it  [ ] I do not understand this

---

## 4. The suppressed historical comparison

**CURRENT TEXT** (excerpt)
> That audit rule was frozen only for retrospective reanalysis after the historical outcomes already existed. Its rule consumes only repeated control-arm records, so it is independent of candidate-effect magnitude, direction, or favorability, but it is not outcome blind in a literal sense, and the exercise is not evidence of prospective blinding or pre-acquisition specification.

**WHY YOU SHOULD READ THIS:** a favorable comparison was suppressed by a rule
written down after the outcomes existed. This is the paper's most sensitive
honesty statement.

**PLAIN-ENGLISH MEANING:** the audit only reads control-arm records, so it
cannot favor any candidate — but it also isn't a blind test, because it was
written after the data existed.

**OPTIONAL SIMPLIFIED VERSION**
> This audit rule was written down only after the historical outcomes existed. Because it reads only repeated control-arm records it cannot favor any candidate effect — but it is therefore also not literally outcome blind, and it does not demonstrate blinding.

**HUMAN DECISION:**
[ ] Keep  [ ] Use simplified version  [ ] I want to rewrite it  [ ] I do not understand this

---

## 5. What the timed-search failure means

**CURRENT TEXT** (excerpt)
> This rejects exact repeatability for at least one exercised seed condition and identifies plausible clock or process mechanisms; it does not prove a unique cause.

**WHY YOU SHOULD READ THIS:** this is the headline failure result (99/200)
and the sentence that stops it from being overclaimed.

**PLAIN-ENGLISH MEANING:** at least some same-seed runs definitely diverged
when timing/worker conditions differed; we can point to plausible causes but
cannot pin every divergence on one cause.

**OPTIONAL SIMPLIFIED VERSION**
> Same-seed runs definitely diverged under different timing/worker conditions, and the audit points to plausible clock and process causes — but no single cause is proven.

**HUMAN DECISION:**
[ ] Keep  [ ] Use simplified version  [ ] I want to rewrite it  [ ] I do not understand this

---

## 6. Main limitations (opening)

**CURRENT TEXT** (excerpt)
> The reported reweighting quantiles are therefore descriptive sensitivities for the realized batteries, not confidence intervals, and do not generalize to a competition field, hardware population, new seed population, or new training run.

**WHY YOU SHOULD READ THIS:** this sentence prevents anyone from quoting the
−2.05 to +3.15 range as if it were a confidence interval.

**PLAIN-ENGLISH MEANING:** the ranges describe only the exact games we ran;
they are not statements about all possible opponents, hardware, or seeds.

**OPTIONAL SIMPLIFIED VERSION**
> The reported ranges describe only the exact games we ran; they are not confidence intervals and say nothing about other opponents, hardware, seeds, or training runs.

**HUMAN DECISION:**
[ ] Keep  [ ] Use simplified version  [ ] I want to rewrite it  [ ] I do not understand this

---

## 7. AI disclosure

**CURRENT TEXT** (excerpt)
> OpenAI Codex, using a GPT-5-family model for which the exact deployed snapshot was not exposed, provided substantive research assistance under human direction. Recorded tasks included protocol reasoning, literature synthesis, code generation and debugging, simulation orchestration, statistical-analysis code, deterministic visualization, and adversarial auditing. The human author set the scientific question, froze the acquisition protocol, retained authority over experiments and claims, and must approve the final paper. … No generative-image system was used.

**WHY YOU SHOULD READ THIS:** APS requires this disclosure; you are
confirming it is complete and accurate.

**PLAIN-ENGLISH MEANING:** AI did real work under your direction; you set the
questions, checked the outputs, and no AI is an author; no AI-generated
images were used.

**OPTIONAL SIMPLIFIED VERSION**
> OpenAI Codex (GPT-5-family; exact version not exposed to us) assisted with reasoning, literature work, code, statistics, figures, and adversarial review, always under human direction and verification. The author set the scientific question and owns every claim; no AI system is an author and no AI-generated images were used.

**HUMAN DECISION:**
[ ] Keep  [ ] Use simplified version  [ ] I want to rewrite it  [ ] I do not understand this

---

## 8. Data availability / public-release statement

**CURRENT TEXT** (excerpt)
> Public archival availability is not yet established: ownership, an approved software/data license, archive creators, maintainer contact, and a DOI await explicit human authorization, so this manuscript does not describe the package as public or promise a later release. … They are not offered on request because the repository does not establish legal authority or a practical controlled-access mechanism.

**WHY YOU SHOULD READ THIS:** this is where your release decisions (questions
13–17 of the questionnaire) become the public wording.

**PLAIN-ENGLISH MEANING:** the sanitized companion exists but is not called
"public" until you approve a license and an archive; the restricted game
materials cannot be shared and we say so plainly instead of promising
"available on request".

**OPTIONAL SIMPLIFIED VERSION**
> The sanitized companion package exists but is not described as public until ownership, a license, and an archive decision are made. The restricted engine, opponents, and game materials cannot be shared under current rights, so they are not offered "on request"; we flag this openly as an editorial risk.

**HUMAN DECISION:**
[ ] Keep  [ ] Use simplified version  [ ] I want to rewrite it  [ ] I do not understand this
