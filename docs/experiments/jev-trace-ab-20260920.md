# Jev trace-label pilot — September 20, 2026

## Result

**Inconclusive for mutation quality.** Neither researcher produced a changed Loop.
A explicitly returned with the baseline. B requested the identical baseline and
then repeated completion notes without returning; the host manually interrupted
that loop. The study is interrupted, not complete. None of the nine planned
paired evaluation runs started, so there is no measured mutation improvement or
final success comparison.

## Frozen condition

- Main model: FreeInference `deepseek-v4-flash`, temperature 0.
- Jev: `jev-1.13.0`; the existing four predicates, with no predicate redesign.
- Tasks: official retail training IDs `0`, `1`, `2`, in frozen order. These include
  related variants and are not three independent task families. No test feedback
  was disclosed.
- One shared opening batch: **3/3 pass**, 42 observation-delimited segments.
- A: factual summaries, segment index, identical raw-segment/full-trace access.
- B: the same materials plus per-segment Jev measurements. This tests adding
  labels, not replacing raw evidence with a compressed-only condition.
- One local mutation maximum; baseline retention permitted. A then B, as frozen
  by seed 20260920; no independent researcher repeats or counterbalanced order.
- The user removed researcher time, call, action and cumulative token caps for
  both arms. Per-request deadlines/output allowances and identical task evaluation
  limits remained fixed. The opening trace batch and Jev labels were reused exactly.

## Observed researchers

| Measure | A: factual evidence | B: factual evidence + Jev |
| --- | ---: | ---: |
| New candidate sources | 0 | 0 |
| Distinct raw segments opened | 38/42 | 31/42 |
| Raw characters disclosed | 529,468 | 417,378 |
| Full-trace reads | 0 | 0 |
| Total model calls | 40 | 69 |
| Total input tokens | 3,837,213 | 8,021,971 |
| Total output tokens | 2,145 | 4,305 |
| Wall / charged seconds | 156.18 / 156.18 | 238.31 / 238.31 |
| End state | Completed; baseline retained | Interrupted; baseline-retention claim |

Both source-save attempts were exact duplicates of baseline `c0000`, so no new
source or rationale artifact replaced the original baseline record. Retention
explanations are visible in the actual tool requests and A's final response.
Counts above come from recorded successful evidence reads, not the researchers'
claims that they inspected all segments.

B requested `write_notes` 37 times; its last exact note appeared
34 times. The text explicitly said research was
complete and the baseline should be retained. These notes did not terminate the
worker. The interruption preserved recorded calls and usage; there were no
unknown-usage calls in either final researcher ledger.

## What the labels may have helped with

Before its first baseline-retention save request, A used 39 calls and
3,659,771 input tokens; B used
32 calls and 2,587,584 input tokens.
B opened 18.4% fewer distinct segments and used 29.3% fewer
input tokens up to that intermediate decision. Its rationale explicitly cited
progress and recovery measurements. These are descriptive observations from one
pair, not evidence of better mutation quality or lower end-to-end research cost.
The pre-retention cutoff is a post hoc diagnostic, not the frozen primary metric.
B's subsequent failure to return made its total input cost higher than A's.

Jev labeled all 42 segments successfully, using 45,973 input
and 3,066 output tokens. Dollar costs were not measured.
Raw disclosure is reported in characters, not guessed tokenizer counts; model
input/output totals use provider-reported usage.

## Limits and next experiment

The 3/3 passing opening created little pressure for a justified failure-driven
mutation. Both researchers chose retention, so the pilot did not obtain the
changed candidate pair needed to answer whether labels improve modification
quality. A single pair also cannot isolate a reliable causal effect from model
variation, arm order, or timing. The B termination failure must not be presented
as proof that Jev causes nontermination.

The mutable implementation now supplies an explicit `finish_proposal` receipt
that makes the fixed researcher controller return before later batched actions.
The proposal-only toolset omits `write_notes`. A local isolated-worker check
verified this behavior and confirmed that it does not select an unscored research
winner. **This repair was made after the run and was not tested by another live
A/B. Frozen campaign files were not changed.**

A follow-up quality experiment should freeze an official-training evidence batch
with real improvement opportunities before either researcher starts, use the
explicit proposal-closing interface in both arms, and evaluate any changed
sources on identical frozen tasks only after both researchers close.

## Provenance and accounting

Canonical raw root: `.artifacts/tau2/jev-trace-ab-20260920-04/`.

- `protocol.json`: design, task IDs, limits, frozen source hashes and recovery lineage.
- `analysis.json`: derived counts and actual read paths used for this report.
- `opening/public/evaluations/e0000/`: three scored opening runs and public traces.
- `opening/private/research-usage.json`: shared opening cost, counted once.
- `semantic/`: original Jev requests, answers, model identity, usage and schema.
- `A/private/research-trace.json`, `B/private/research-trace.json`: actual researcher behavior.
- `A/private/research-usage.json`, `B/private/research-usage.json`: final researcher usage.
- `private/prior-research/A/`: the preserved earlier 24-call attempt, never injected
  into either new researcher. Its 1,464,564 input tokens
  remain included in total spend, outside the new arm comparison.

Attempt 01 completed the opening, then failed before Jev inference because the
configured interpreter symlink had discarded the SDK virtualenv. Attempt 02
completed Jev labeling, then stopped when its original 24-call A exhausted the
budget. Attempt 03 was prepared but never dispatched. Attempt 04 followed the
user's explicit unlimited-budget revision and restarted both researchers from
identical evidence. Its B worker was manually interrupted after repeated
completion notes. No candidate task comparison was dispatched in any attempt.

Counting shared and preserved records once, total main-model spend across these
attempts is **195 calls, 13,687,913 input tokens,
12,413 output tokens**. Jev usage is separate above.
