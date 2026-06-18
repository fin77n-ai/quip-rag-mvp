# Product Case Study

## Context

Five years of video-production issue logs had accumulated in semi-structured
tables. Each period followed roughly the same workflow, but schemas and category
language changed incrementally. Project managers could inspect one project at a
time, yet could not reliably compare patterns across time.

## Product Question

How might we turn inconsistent historical logs into a trustworthy decision tool
without asking project managers to learn a new data discipline first?

## User And Job

**Primary user:** project manager.

**Job to be done:** when planning or following up a delivery, understand which
issues repeat, where they concentrate, who owns the next action, and what source
evidence supports the conclusion.

## Scope

The MVP includes four connected capabilities:

1. schema normalization for changing table structures;
2. row-level AI classification with confidence and review state;
3. trend analysis across sprint, vendor, locale, and issue type;
4. RAG answers with grouped evidence and answer QC.

The MVP deliberately does not include authentication, collaboration, notification
rules, or automatic writes back to source systems. Those features depend on
workflow validation and would distract from the core risk: trust in normalized
data and AI-supported conclusions.

## Why AI

Rules handle known column aliases and deterministic cleanup. AI is reserved for
tasks where language varies: issue summarization, category suggestion, similarity
grouping, and question answering. Low-confidence classifications enter a human
review queue instead of flowing directly into analytics.

This division matters. The product is not "AI everywhere"; it uses deterministic
logic where certainty is available and reviewable inference where it is not.

## Trust Model

- Every issue retains a source document, row key, sprint, and owner.
- Every answer shows representative and supporting evidence.
- Classification confidence is visible and actionable.
- Reviewer corrections can be distilled into future tagging guidance.
- Answer QC checks citation coverage before presenting a result as grounded.

## Validation Plan

Run a two-week pilot with project managers using a representative historical
sample. Compare the MVP against the current document-search workflow.

| Hypothesis | Signal |
| --- | --- |
| Cross-project questions become faster | Median time from question to verified answer |
| Evidence improves trust | Citation open rate and verified-answer rate |
| Review is focused enough to sustain | Queue precision and median handling time |
| Trends lead to action | Percentage of surfaced patterns assigned an owner |

## Public Demo Note

All data in the public demo is synthetic. Counts illustrate product behavior and
must not be interpreted as results from a production deployment.
