# Historical Jev trace-label A/B pilot

The A/B pilot is retired. The adopted [Jev workflow](../jev.md) analyzes every development task run before researcher feedback. The active A/B launcher has been removed; frozen campaign implementations and the dated reports remain unchanged. The design below describes those historical pilots.

The pilot freezes three official retail training tasks before dispatch. The default
is the first three in suite order; explicit task IDs may instead select historical
baseline failures. In that case, the protocol records the source evaluations and
their hashes, and preparation verifies the baseline source and every chosen task's
failure. Such selection is not representative sampling; fresh opening outcomes
are never used to replace tasks. One shared
reactive-baseline rollout batch supplies identical factual summaries, segment
boundaries, raw segment files, and full traces to both arms. Only B additionally
receives Jev scores and probabilities. Both researchers have the same model,
prompt, component boundary and limits: 900 charged seconds, 24 model calls, and
65,536 output tokens. The arm order is frozen from seed 20260920. The current
four-level Scores range from 0 to 3; Noul probabilities range from 0 to 1.

## Proposal comparison and recovery

On the user's explicit request, `--unlimited-research` freezes null time, action,
model-call and cumulative output-token limits for both researchers. Host accounting
continues unchanged; individual model request deadlines/output allowances and the
identical per-task evaluation limits remain in force. When replacing a budgeted
pilot, start both researchers fresh, retain earlier research privately, and report
that prior spend separately. Reuse exact shared opening traces and Jev labels.

Each researcher may save at most one new source and rationale. These are
**unscored proposals**, not selected candidates or completed research submissions.
Neither researcher can evaluate, select or submit during proposal generation.
`finish_proposal(candidate_id, reason)` supplies an explicit closing receipt;
the fixed researcher controller returns before any later batched action. It does
not change scored selection. The proposal-only toolset omits `write_notes`.
Both isolated workers must close before the host runs a fresh baseline, proposal
A and proposal B on all three tasks, rotating candidate order by task. A retained
baseline is still evaluated in that arm. The primary comparison is paired pass
count; report token usage, model calls, wall and charged time, source changes,
evidence reads, failures and missing scores alongside it. A budget-exhausted
researcher retains the scored baseline as a separately labeled fallback; it is
not rerun and does not count as a completed proposal.

This design isolates the addition of labels. It does not test replacing full
evidence access with semantic-only disclosure, use official test feedback, or
establish an effect across independent researchers. All three tasks are training
tasks; related variants are not independent task families. Identical seeds do not
guarantee identical model or simulated-user responses.

Prepare with the benchmark's frozen Python environment, then execute the saved
module from the new campaign's `implementation/` source root. Load local API
credentials into the process environment before changing directories. The Jev
SDK runs in its separate configured virtualenv; preserve its entry-point path
instead of resolving its interpreter symlink. Preparation checks that SDK import.

Raw records belong under `.artifacts/tau2/`. `protocol.json` freezes the design,
models, tasks, source hashes and budgets; `result.json` and the usage ledgers own
outcomes and costs; `report.md` is a derived view. Infrastructure/verifier failures
stop dispatch. Explicit recovery may use `--prior` to copy a matching completed
opening and closed baseline-fallback arms exactly into a new campaign and count
their cost once. Reuse requires an unchanged segment implementation; a new input
design starts a fresh experiment. Such recovery does not repeat their tasks, labels or researcher
attempts. Historical campaign files remain unchanged.

The September 20 unlimited pilot predates this explicit closing tool. A retained
the baseline and returned; B requested the same source, then repeatedly wrote
completion notes without returning. B was manually interrupted, and paired
evaluation did not begin. See the dated results report for the complete limits,
measurements, prior spend and lack of a mutation-quality result.

The [v2 follow-up](jev-trace-ab-v2-20260920.md) used the revised inputs, historical
failure-based task selection, fresh opening traces and explicit proposal receipts.
It completed all nine comparisons. B retained baseline and passed 2/3; A proposed
an imperfect guard and passed 1/3; separate baseline executions passed 0/3.
Because B and baseline were identical, the score difference does not establish
source improvement. B's lower evidence-reading cost is a descriptive single-pair
finding. The report also records incomplete budget-tail measurements and both
researchers' failure to read component contracts.
