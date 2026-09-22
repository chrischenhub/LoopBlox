# Jev in task Loops and the research workflow

Jev has two separate roles. The optional `judge` component runs inside a task Loop:
the researcher defines Noul/Choice questions and classification criteria, Jev
judges the current public evidence, and Python decides what to do next. Its
reference type is `analysis_result`. See the [Judge API and question-design
guide](../CONTROLLER.md#judge-online-typed-judgments).

Judge's calls consume task and ancestor research budgets and are recorded under
their component invocation IDs in `trace.json`, including actual questions, state,
responses and usage. Its host reservation scales with the answer structure; the
generated [component contract](../COMPONENTS.md#judge) owns the exact rule. The
runtime records the pinned model, SDK version and transport settings on first use.
It cannot read future events, private evaluator/simulator state or post-run analysis.
Question definitions travel with answers into subsequent component context.
Changing prompts, categories or triggers changes the candidate; adding Judge to a
library requires a new frozen episode. Historical runs remain unchanged.

Separately, post-run Jev analysis is a fixed part of development evaluation. There
is no A/B switch for that analysis:

```text
Run a candidate Loop on a task and close its worker
    → record the task result and public trace
    → analyze the trace with Jev
    → return outcomes, Jev measurements and evidence links to the researcher
```

`ResearchSession.run_evaluation` applies this sequence to the supplied baseline,
every evaluated candidate, including ordinary failures and
budget-exhausted runs. It completes each run's analysis before starting the next
task or returning the evaluation. Opening feedback is analyzed before the research
agent starts. Infrastructure and verifier faults still stop research immediately.
Final holdout feedback never returns to a researcher.

## Fixed input and questions

`loopblox/analysis/segments.py` owns `segment-semantics-v8` and the segment sizes.
Each segment groups four observation-delimited cycles without overlapping executed
steps. A cycle ends at the first completed observation of a distinct execution.
Additional pages or a full reread remain supplementary evidence, not new cycles.
They remain in `evidence_reads` and do not replace the latest user message or the
starting observation for the next segment; rereading an earlier execution cannot
move the task's recorded conversational state backwards.
The last partial group is retained: 13 observed cycles produce 4, 4, 4 and 1.
Following completion claims, denied calls or unobserved executions remain in
separate tail groups. Each tail group contains at most four reasoning or decision
invocations: Decide, ThinkDecide, Think, Plan, Decompose, Critique, Reflect, Choose or Judge,
including failed invocations. Other calls remain in their original order exactly
once. This count bound prevents an indefinitely repeated completion-review loop
from becoming one analysis request; it does not impose a token bound on an
individual invocation. Evidence is never truncated. Tail groups may share an
observation-step cursor; their segment indices and invocation IDs distinguish them.
Every segment, including these tails, receives Jev progress and recovery judgments
regardless of whether it has a new observed outcome.

The input includes the initial public request, the latest public user message
before the segment, its starting observation, every attempted action and every
intermediate observed outcome. Matching `step` numbers preserve order. Recorded
reasoning and supplementary reads are retained. Failed and interrupted component
calls retain their invocation IDs, component names, arguments, statuses and exact
public errors in `component_failures`; a failed Reflect is not an empty reasoning
result. The last segment also includes the public controller status and stop reason
in `task_stop`, never the verifier's score. Actions come from host tool-request
records, including rule execution; unexecuted proposals are reasoning evidence.
All completion proposals retain their invocation IDs, steps, component names and
complete values in `completion_proposals`; later proposals do not overwrite earlier
ones. A proposal does not establish completion, and recorded Choose results retain
any selection among proposals.
Execution and action IDs link attempts to observations. Observed outcomes retain
their originating request even when the attempt occurred in an earlier segment.
The analysis code does not further truncate observations or reasoning. A brief
observation remains the representation the agent saw. No final score, evaluator
data or private simulator scenario is sent to Jev.

The judgments cover the whole segment, not its last cycle or a per-cycle average.
Progress and recovery are always requested. Action effectiveness is requested only
when the segment has a new observed outcome; its absence is recorded as
`unobserved_actions` or `no_attempted_actions`, not a zero or a skipped segment.
Progress has four levels; action effectiveness has three:

| Level | Progress (0–3) | Action effectiveness (0–2) |
| --- | --- | --- |
| 0 | No observable new progress toward the public request. | Intended immediate effects were not achieved. |
| 1 | New relevant information, with preparation or verification still incomplete and no requested outcome delivered. | Intended immediate effects were partly achieved. |
| 2 | A required preparation or verification completed, but no requested outcome delivered. | Intended immediate effects were fully achieved; other task steps may remain. |
| 3 | Evidence confirms delivery of at least one explicitly requested outcome. | — |

For a requested exchange, verifying replacement stock can earn progress 2 and
effectiveness 2; carrying out the exchange can earn progress 3 and effectiveness 2.
If the user asked for information, delivering a supported answer can earn progress
3. Merely retrieving it or answering an intermediate clarification does not qualify.
Progress 3 does not mean every goal in a multi-goal task is complete, and a promise
or unsupported completion claim is not evidence of delivery. Progress is not a
percentage of task completion. The returned Scores may lie between rubric levels.

Recovery need is a Noul probability from 0 to 1. It considers public component
failures and controller stop evidence as well as outcomes and reasoning. A denied
reference can require correction without an environment outcome; planning or an
unobserved action alone does not establish failure. Planning, rereading and a
completion proposal alone do not establish new task progress. Action effectiveness
considers only actions with observed results, not unobserved attempts.
There is no extra rolling-history window or generated goal summary. Exact-repeat
and duplicate-action facts are computed in code. Jev judgments are diagnostic
evidence, not task rewards or verified explanations of failure.

Version 8 includes online Judge definitions and answers as reasoning claims and
counts Judge invocations toward the existing four-call tail bound. It leaves the
post-run questions and scales unchanged. Version 7 traces without Judge receive
the same segmentation and questions; their stored artifacts are not rewritten.
Version 6 removed the whole-segment outcome gate, added public failure evidence and
broadened the recovery question. Version 7 retains its judgments and scales, splits
only the trailing calls into groups of at most four reasoning/decision invocations,
and preserves every completion proposal. Regular four-observation groups are
unchanged. Frozen earlier records retain their original questions, schema and
scores, including version 5's N/A tails and version 6's unsplit tails.
Earlier effectiveness scores on 0–3 must not be compared directly with the current
0–2 scores or silently rescaled. Reports exclude missing values separately for each
metric and correlate only jointly measured pairs; additional tail measurements
also change aggregate coverage, so cross-version averages are not directly comparable.

## Evidence and accounting

Each episode freezes model, SDK version, question definitions, schema, segment
size and request settings in `public/jev-config.json` and its private setup.
Each development run writes `jev.json` beside its public `trace.json`. That record
contains the source-trace hash, segments and invocation IDs, exact inputs,
responses, statuses, attempts and usage. The full evaluation's `runs[].jev` joins
these existing judgments to public execution facts. It retains measurements,
confidence and missingness, and adds the following navigation:

- `artifact`, `trace_artifact` and `source_trace_sha256` locate the exact analysis
  and its source. Each segment's `evidence_pointer` is a JSON Pointer within
  `artifact`, not a separate filename. `invocation_ids` locate the actual calls in
  the linked trace. Segment indices distinguish tails that share a step cursor.
- `execution.components` and `execution.tools` derive from the same
  `summarize_trace` implementation as the run's `summary.json`, restricted to the
  segment's owned invocations. Component statuses and counts show actual
  participation, including failed calls. They do not show that a component helped.
- `execution.agent_usage` derives from owned model attempts using the existing
  usage accounting. It includes retries and preserves unknown usage. It excludes
  simulated-user and post-run Jev calls; online Judge calls are owned agent
  attempts and are included. Whole-task usage remains in the run record. The
  top-level `jev.usage` is post-run Jev's separate share of the research ledger.
- `summary` contains segment status counts, measured/missing counts and observed
  ranges for each judgment, plus actual component invocation counts. It introduces
  no score threshold, automatic diagnosis, ranking or cross-schema average.

The opening and `evaluate` receipts provide compact evaluation coverage and the
full evaluation path. Coverage groups analyses by their frozen `schema_version`;
each group counts runs and their statuses, segments and their statuses, and
measured/missing values and observed ranges per judgment. Schemas are never pooled.
Detailed segment rows stay in the evaluation artifact for search
and computation with `research_shell`; `read_artifact` can also open individual
records. These are derived views, not a new source of judgments. Existing frozen
records remain exact: older evaluations may lack this navigation view, while their
`jev.json` still contains segment `ids`, `shape`, `state` and exact responses.
Checkpoints retain these public records as evidence for subsequent iterations in
the same campaign.

Both roles reuse `loopblox/runtime/jev.py`, using `jev-1.13.0` through the existing bounded process runner and shared model
gateway. SDK retries are disabled; the gateway owns retry decisions and records
every actual attempt. Post-run Jev calls and reported tokens consume the shared research
budget after the task has closed. They do not consume that task's finished limits.
The run's original task status, verification and task usage remain intact.

The host reserves 256 output tokens before each post-run Jev request. This is an accounting
reservation, not an API output-limit parameter: Jev exposes no such parameter.
Reported usage replaces the reservation; unknown usage retains it. A response
exceeding the reservation is retained and charged, then stops research. The existing
gateway's charged-time and timeout rules also apply. Per-run Jev usage is a view of
the shared ledger, not an additional charge. Analysis failure or insufficient
research budget preserves partial evidence and stops feedback release; it cannot
silently skip Jev or become a low task score.

## Using the judgments in research

Jev provides a trajectory to investigate, including inside successful runs. Its
judgments do not distinguish model errors from harness errors. Apply the research
guidance in [CONTROLLER.md](../CONTROLLER.md): inspect the actual model input,
output and controller behavior, preserve uncertain attribution, and identify an
editable Loop mechanism before proposing a failure-driven change. Model errors
themselves remain outside the editable scope.

Start from a concrete research question and combine judgments with public evidence:

- **Are actions working toward the request?** Compare effectiveness with progress
  along one run. Effective actions with little progress can indicate useful
  preparation, repeated work or an irrelevant direction. Read the request and
  outcomes before choosing among these explanations.
- **What happened after an apparent need for correction?** Inspect a segment's
  recovery judgment, the subsequent actual decisions and actions, and later
  judgments. A Reflect call appearing afterward is a fact; whether it changed the
  approach, and whether the change helped, require evidence from its output and
  later outcomes. Absence of a new observation leaves effectiveness unknown.
- **Did the proposed mechanism participate?** Locate the changed component or
  branch in invocation records before attributing an improvement to it. Inspect
  failures as well as completed calls. A high progress score cannot establish that
  an uncalled Critique or Reflect improved the run.
- **Where did a successful run spend effort?** Join segment measurements with
  owned agent attempts and tokens to find expensive reasoning, preparation,
  rereading or recovery worth examining. Costs are recorded facts; an apparently
  low-progress segment is not automatically removable work.
- **What changed on paired tasks?** Use the evaluation's host draw and repeat to
  pair candidates, then follow each run's own actions and public milestones.
  Segment 3 in one candidate need not describe the same work as segment 3 in
  another. Compare official outcomes and total cost alongside the trajectories;
  stronger Jev judgments alone do not select a better candidate.

For example, a workspace analysis can print a run's measured trajectory and actual
component participation without reading its entire transcript into model context:

```python
import json
from pathlib import Path

evaluation = json.loads(Path("/evidence/evaluations/e0000/result.json").read_text())
for run in evaluation["runs"]:
    evidence = run.get("jev")
    if evidence is None:
        continue
    print(run["candidate_id"], run["task_id"], run["draw"], run["repeat"],
          run.get("verification_verdict"), evidence["schema_version"])
    for segment in evidence["segments"]:
        print(segment["index"], segment["progress"],
              segment["action_effectiveness"], segment["recovery_needed"],
              segment["execution"]["agent_usage"],
              list(segment["execution"]["components"]),
              evidence["artifact"], segment["evidence_pointer"])
```

This example uses the new evaluation navigation fields. Use the exact responses
and frozen rubric in `jev.json` when inspecting uncertainty or older records.
Never turn missing measurements into zeros. Keep schemas separate when comparing
values or coverage. A subsequent improvement and an earlier diagnostic signal
support a hypothesis to test; they do not establish causality. Record the relevant
run, segment and invocation references with the hypothesis and revisit it after
evaluation. The researcher chooses this investigation freely; these questions do
not impose a fixed sequence or grant access to private evidence.

## Setup and offline inspection

Install `typesafe-sdk==0.7.0` in a host Python environment. Set `TYPESAFE_API_KEY`
in `.env` or the process environment. If the benchmark environment does not contain
the SDK, set `LOOPBLOX_JEV_PYTHON` to the absolute path of an interpreter that does,
for example `/path/to/loopGym/.venv/bin/python`. Otherwise the current host interpreter
is used. Keep the virtualenv entry-point path without resolving its symlink.
Research checks the key and SDK import before dispatching development tasks.
Online Judge uses the same setup; standalone Loops that never call Judge do not
initialize Jev. Dependencies and credentials stay on the host, outside the worker.

Normal research commands now perform the analysis automatically. To inspect an
existing evaluation separately, from the source root:

```sh
python3 -B -m loopblox.analysis.segments path/to/campaign \
  --evaluation path/to/campaign/public/evaluations/e0000 --dry-run

python3 -B -m loopblox.analysis.segments path/to/campaign \
  --evaluation path/to/campaign/public/evaluations/e0000 \
  --out-dir .artifacts/analysis/jev-new
```

The first command makes no model requests. The second uses the same analysis and
accounting path, with an uncapped offline ledger in the new output directory; it
copies public traces and preserves all source campaign records. A new analysis is
a new set of calls. Existing frozen campaigns retain their original implementation.
