# Generative-AI use disclosure

Status: **PRE-FREEZE; HUMAN REVIEW REQUIRED**
Recorded: 2026-08-26 (America/Chicago)

## System identification

OpenAI Codex, described to the agent by the application as an agent based on
the GPT-5 family, assisted in this research sprint. The application did not
expose an immutable serving snapshot or a request-level API model identifier
to the agent. It would therefore be inaccurate to invent a more specific
snapshot name. This limitation is material because OpenAI distinguishes model
aliases from snapshots and recommends snapshots when an exact version must be
locked; see the [official OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model).

The session also used bounded Codex subagents for read-only repository,
literature, statistical-design, and implementation review, followed by scoped
implementation tasks. They were not treated as independent scientific
reviewers or authors.

## What Codex assisted with

Codex assisted with repository inspection; protocol and novelty-matrix
drafting; study-owned Python code; unit and smoke tests; schedule and schema
design; statistical-design criticism; acquisition safety checks; literature
retrieval and summarization; and manuscript scaffolding. It also executed
local commands and, only after the human explicitly authorized Azure use,
prepared for bounded cloud pilot execution.

Codex did not choose the research question autonomously, approve the protocol,
authorize final data acquisition, interpret final findings on the human's
behalf, make an authorship claim, submit a manuscript, publish data, or upload
an artifact.

## Human direction and mandatory verification

The human supplied the scientific question, claim boundaries, minimum design,
pilot kill gates, venue constraints, cloud boundary, required deliverables,
and mandatory pre-final approval stop. Codex was instructed to return a
negative decision when evidence is inadequate.

Every substantive AI-assisted output is subject to the following verification:

1. Literature claims are checked against an inspected primary paper or
   official paper page; citations are not accepted from model memory.
2. Scientific code is reviewed against the frozen protocol, executed through
   automated tests, and smoke-tested on non-final seeds.
3. Schedules, inputs, raw records, software, and machine records are hashed and
   validated before analysis.
4. Headline point estimates must reproduce through an independent program that
   does not import the main analysis module.
5. Figures must be generated only from frozen analysis outputs.
6. The human author must personally approve the question, protocol freeze,
   final acquisition, interpretation, complete manuscript, disclosure, and
   any submission.

## Proposed manuscript wording

> OpenAI Codex, an agent described by the application as based on the GPT-5
> family (exact serving snapshot not exposed), assisted with repository
> inspection, code and test drafting, protocol and manuscript scaffolding,
> literature retrieval, and statistical-design criticism. The human author
> specified the research question and decision gates, reviewed the frozen
> protocol, and is responsible for verifying the source literature, code,
> analyses, figures, interpretation, and manuscript. Codex is not an author.

This wording remains provisional until the human verifies it against the
submission venue's policy and approves the final manuscript.
