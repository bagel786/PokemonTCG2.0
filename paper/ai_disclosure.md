# Artificial-intelligence assistance disclosure

OpenAI Codex, operating with a GPT-5-family model whose exact deployed snapshot
identifier was not exposed in the session, provided substantive assistance in
August 2026. Under the human author's direction it helped audit repository
artifacts; draft and review Python, LaTeX, and release-package files; implement
statistical checks and visualizations; locate and verify bibliographic metadata;
and draft and edit manuscript prose. Multiple Codex worker agents performed
bounded evidence and literature audits. Codex did not make authorship,
submission, or scientific-readiness decisions.

Every numerical result admitted to the manuscript was required to trace to a
surviving raw artifact or a newly run frozen protocol, and regenerated
quantities must pass checked-in validation. Package and source identities were
checked by SHA-256, and analyses were syntax-checked and rerun. AI assistance
also helped identify that two opponent implementations use wall-clock-bounded
search and that the planned ablation failed its repeated-control gate; those
findings were verified against source and retained outcomes rather than accepted
from model output. Before submission, the final PDF must be compiled, every page
rendered, and the rendering visually inspected. AI-generated prose and code
remain the responsibility of the human authors. No generative-image model was
used: figures are deterministic plots and schematics produced by the disclosed
analysis code.

The corresponding author must verify the tool name/version against the final
submission platform, add any substantive AI assistance used earlier in the
project that is not recoverable from the repository history, and confirm that
all AI use complied with applicable terms, privacy duties, and intellectual-
property and data-access rights.
