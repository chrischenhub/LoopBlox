# Current Controller API

This document maps the definitions in [loop.md](loop.md) to the implemented API.
[AGENTS.md](AGENTS.md) owns engineering and episode policy. Each episode exposes
frozen copies as `controller-api.md` and `loop.md`, alongside `experiment.json`
and a derived `components.json`. Only the episode catalog authorizes calls.

This guide describes the implemented host API. [experiment.md](experiment.md)
owns the current continuous research policy on one benchmark. The retained study
and search launchers implement older protocols; API availability does not make
those launchers a supported continuous workflow. Inside a frozen episode, its
task instructions and tool declarations own the admitted operations and limits.

A candidate is one Python file defining `run(env)`: a complete Loop definition.
It composes exposed behavioral components using ordinary functions, conditions,
and loops. All current task Loops directly compose the exposed subcomponents.
Python remains the canonical definition; there is no graph language or mandatory
work-loop component.

## Concepts and researcher scope

- A **Loop** defines the whole control process triggered by one primary user
  input until control returns. A **task run / trial** is one concrete execution.
  This runtime starts every task in a fresh worker; it has no steering or sessions.
  The local `loopblox.chat` playground carries conversation messages between fresh
  task runs outside the runtime; it does not resume workers or Python continuations.
- A **Component** has a defined responsibility, visible state, outputs/effects,
  internal capabilities/options, and return/failure conditions. An **invocation**
  is one actual call. Current component invocations are direct controller calls;
  their model attempts and tool actions retain their owning invocation IDs.
- **Loop level** describes macro organization; **loop exec level** describes
  expanded internals, which may have further nesting. Neither fixes call count.
- The caller owns invocation timing and the next transition. Approved component
  code owns internal behavior. Host permissions, limits, and scoring remain fixed.
- Component return passes control to its caller. Only the outermost `run(env)`
  returning ends the task normally. This does not certify success.

Read `experiment.json`, `component-contracts.md`, and this guide before writing a
candidate; `components.json` contains exact schemas and fixed prompts. The
experiment freezes its question and **root composition boundary**:
which components the candidate can call directly, and which discrete parameter
choices are allowed. An empty options object exposes the component's existing
parameter contract. Options narrow each component's catalog enums independently. If an excluded default
is removed, that parameter becomes required; omission cannot bypass the boundary.

The host enforces this boundary for baseline, development, and holdout runs.
Changing local `env.components`, adding a Python wrapper, or seeing an internal
call in a trace does not authorize it. Family membership grants no access to
sibling components. Implementations and fixed framing stay fixed throughout the
episode. Exposed Judge calls may carry caller-defined typed questions and criteria;
other component prompts stay fixed. Proposals cannot change an active library.

The current boundary permits root Python composition: order, branches, repetition,
local computation, and return decisions. It does **not** enforce a fixed outer
workflow or expose arbitrary edit positions inside approved source. All candidates
use the same direct composition interface. Fixing an outer workflow for a future
internal-only experiment needs an explicit enforceable experiment contract.

Complete task runs are the evaluation unit. If both composition and internal
options change, their joint result does not isolate either cause. A macro-only
comparison must freeze the internal options as well as component code.

## Supplied baseline and composition choices

The host supplies the exact baseline source and evaluates it before research.
The shared source is `controllers/reactive.py`:

```python
def run(env):
    while True:
        context = env.component("context_full")
        decision = env.component("decide", context=context["id"])
        if decision["value"]["kind"] == "completion_proposed":
            return decision["value"]["response"]
        execution = env.component("execute", decision=decision["id"])
        env.component("observe_full", execution=execution["id"])
```

Its defaults use full context, full observations and one selected action per
decision. Each iteration makes one joint decision request, followed by execution
and observation when an action is selected. The outer controller returns on the
completion proposal. The environment supplies the policies and tools. This is a
minimal LoopBlox model/tool Loop.

The baseline is a comparison reference, not a required structure for alternatives.
The current episode's `experiment.json` alone determines available components and
options. You may compose exposed subcomponents directly, remove stages, change
invocation triggers, evidence flow or allowed options, and
choose continuation and return conditions. No component sequence is preferred.
Existing components' internals remain fixed; their composition belongs to your
Python controller. A Plan step can scope a decision without creating a session,
worker, or separate budget. Consult its generated contract for actual behavior.

The supplied baseline is the only predefined complete Loop in the research
materials. Candidate sources and evidence accumulate within this campaign.
Repository examples for human readers are not exported to the researcher.

## Capability families and subcomponents

The four directory families are **Context / Evidence**, **Propose**, **Assess**,
and **Act**. Their definitions and membership come from `loopblox/runtime/components.py`; the
frozen `component-contracts.md` groups only this episode's exposed subcomponents.
Each `env.components[name]["family"]` contains `id`, `label`, and `description`.
For example, a controller can inspect the available proposal components with:

```python
proposals = [name for name, spec in env.components.items()
             if spec["family"]["id"] == "propose"]
```

Call a concrete subcomponent, such as `env.component("plan", context=context_id)`.
Families themselves are not callable, do not have shared mode arguments and do
not impose stages. Subcomponent parameters and allowed values remain in each
spec's `parameters`. Local edits to family metadata cannot grant capabilities.
`family` describes directory membership; `category` still describes the returned
reference type. Neither replaces the fixed component contract. Current Assess
components produce model judgments; real checks require approved tools and their
observations, never the hidden evaluator.

## Library reference

`env.component(name, **arguments)` returns `{"id": "b0001", "value": ...}`.
Pass IDs to later components. The host resolves stored originals, not local edits.
`env.components` and public `components.json` contain the episode's exposed
catalog, including family metadata, narrowed parameter contracts, reference categories, fixed
prompts and a `contract` describing surfaces, scope, internal behavior, calls,
state effects, return semantics and failures. `component-contracts.md` is generated
from that same filtered catalog for reading; it cannot introduce additional options.
The full library is recorded
privately in setup and in run traces for explanation; visibility does not grant
call permission. `loopblox/runtime/components.py` owns family definitions and membership, prompts,
schemas, and component behavior. The repository's `COMPONENTS.md` is the generated
full-library reference, not an allowlist for every experiment. Parameter
`reference_categories` are enforced by the host against completed invocation
results. The catalog's returned reference type is derived from each component's
`category`: `execute` returns `ref<execution>`, while `observe_full` returns
`ref<observation>` despite having the same value shape. A Decide completion is
`ref<decision>`. Plan returns `ref<plan>`; Think, Critique, Reflect and Judge return
`ref<analysis_result>`. Choose returns a selection of an existing decision ID,
not a new executable proposal. These are API types, not
family IDs or Harness layers. Model-response contracts,
including tool argument schemas, remain enforced by the existing gateway.

Tools may declare `preserve_observation_fields`: top-level result fields retained
in full on each `observe_brief` page. This host-owned declaration is disclosed with
the tool and recorded in the trace; editing `env.tools` does not change it.
`observe_brief(execution=id, offset=0)` reads a 1,200-character page of the remaining
serialized content. Each outcome reports `next_offset`, or `null` when no further
page remains. A later call can read another offset without executing the tool
again. Each offset can be observed once per execution and applies to all outcomes;
an outcome with no content at that offset returns an empty page. An execution can
also receive one `observe_full` after its brief pages;
after full observation, no further observation of that execution is allowed.
Action IDs, statuses, effects, and error codes remain factual host records.

When proposing an experiment, distinguish changing which component is called,
changing a caller-owned trigger or branch, and changing an allowed component option.
Keep the other choices fixed for an isolated comparison. A full/recent context may
already include earlier analysis results without an explicit input reference;
removing an input ID alone does not prove the model no longer sees that result.

Every context includes the task and is frozen when created. Its result contains
`records` and `through`, an exclusive history cursor. `context_full()` selects
current model turns and explicit observations, excluding summary model turns.
`context_full(base=context_id)` retains the supplied view and adds evidence
recorded after that view's cursor. `context_summary(context=context_id)` compresses
the selected records into a new view while retaining the input's cursor, so a
later full view can combine the summary with new evidence instead of rereading
the original history.

`context_recent()` takes no arguments. Its window covers the last four distinct
executions, counted when each is first observed, and includes their original
requesting decisions. With more than four observed executions, its history starts
at the oldest selected execution's first observation; otherwise it keeps all
eligible history. Analysis calls and further pages do not consume another window
slot. It excludes summary model turns; use `context_full(base=summary_id)` when a
summary should remain available. Neither context
selector drops failed results. A newly created view keeps full observation in
place of all brief pages of the same execution; existing views remain unchanged.
Raw tool outcomes remain in factual history regardless of their current view.
Explicit result inputs supplement a view with host-resolved evidence; they cannot
inject replacement messages. Judge questions use its separate `questions` argument. The generated catalog owns the accepted reference types.

Plan returns a nonempty `steps` list. Each step has an `objective` string and a
nonempty `done_when` list of requirements. These are model proposals, not verified
facts or permissions.
A revised Plan is another immutable invocation. The controller selects a step
using its Plan ID and zero-based index; it does not copy or edit the step text.

Critique requires `target=<invocation ID>` for one analysis result, Plan, or decision,
including a completion proposal. The host supplies that target's identity and
original value even if it is already in context. `context` and optional `inputs`
are background evidence; they do not select another target. The response contains
`assessments`, each with `requirement`, `verdict`, `evidence_refs`, and `detail`.
Verdicts are `supported`, `contradicted`, or `unknown`. The host derives the overall
`verdict`: any contradicted requirement makes it contradicted; otherwise any unknown
requirement makes it unknown; otherwise it is supported. Evidence references name
only the disclosed task or model-visible invocation IDs, and supported or
contradicted assessments require at least one reference. Missing evidence remains
unknown. This is a
model assessment of the visible evidence, not hidden verification or permission
to end the Loop. There is no separate `accept` flag.
Action review assesses preconditions, policy compliance and relevance before execution;
it does not require evidence of future effects. A blocker report is assessed for the
truth of the blocker and reported task status, without treating unfinished work as success.

`choose(context=context_id, candidates=[decision_id, ...])` compares at least two
distinct completed decisions concerning the same scope. Action candidates with an
already-attempted action are rejected before comparison. It returns `selected_ref`
and `reason`, using an original candidate ID or `null` to decline all candidates.
The controller may execute or review the selected decision, or make new proposals.
Choose does not rewrite actions or execute tools.

Model components other than Summary receive tool definitions as read-only context;
only Decide registers model actions. When Critique reviews a decision, it uses
that decision's original tool filter and selection setting. A scoped completion
is assessed against its selected step, with the whole task's requirements still
binding. Tool definitions
explain what proposed actions can do; they are not permission to execute them.

## Judge: online typed judgments

When `judge` is exposed, the researcher may define semantic questions, classification
labels and descriptions in the candidate's Python source. Jev returns typed
judgments instead of generated explanations. Python owns their interpretation and
the next action. This is an explicit editable question interface; it does not open
other components' prompts or allow arbitrary output schemas.

The following shows the call and result syntax. The candidate supplies
`context_id`, question text and category descriptions, and decides how to use
the returned judgments.

```python
judgment = env.component("judge", context=context_id, questions={
    "check": {
        "type": "noul",
        "instructions": noul_question,
    },
    "classification": {
        "type": "choice",
        "instructions": choice_question,
        "criteria": category_descriptions,
    },
})
answers = judgment["value"]["answers"]
probability = answers["check"]["noul"]
category = answers["classification"]["choice"]
```

`questions` is a nonempty map of question IDs to definitions. Question IDs route
answers back to code; Jev does not see those IDs, so put the complete question in
`instructions`. Instructions and criterion descriptions are nonempty strings.
Noul optionally accepts `criteria={"true": "...", "false": "..."}`. Choice requires
2–255 named criteria. Only `noul` and `choice` are currently exposed; Score and
arbitrary JSON schemas are not part of this component.

The result contains the original `questions` and matching `answers`:

- Noul: `{"type": "noul", "noul": 0.9}`. This is the probability of yes; a value
  near 0.5 means uncertainty, not medium intensity. There is no separate confidence.
- Choice: `{"type": "choice", "choice": "label_a", "confidence": 0.7,
  "probabilities": {"label_a": 0.8, "label_b": 0.1,
  "label_c": 0.05, "label_d": 0.05}}`. Labels come from the candidate's
  category descriptions. The selected label must be a maximum;
  probabilities cover exactly the supplied labels and sum approximately to one.
  Confidence describes distribution concentration, not verified correctness.

Host-built Jev state has `instruction` (fixed evidence framing), `task`, `evidence`
(ordered public model turns and explicit observations) and `capabilities` (tool
definitions). The task is always present. `context` and optional `inputs` use the
same frozen views and reference categories as Reflect. Raw execution IDs are not
observations, and a stale context will not acquire newer evidence automatically.
There is no caller-provided state or access to simulator internals, evaluator data,
future observations or post-run Jev measurements. Prior model outputs and judgments
remain claims. A returned Judge reference can feed Decide, Reflect, Plan or Critique;
its definitions travel with the answers, and later full/recent views can include it.

Design one coherent judgment per question. Give categories distinct meanings,
specify precedence where needed, and include an uncertainty/no-match category when
the alternatives may not cover the evidence. Use multiple Nouls when several
conditions may hold together. Independent questions over the same evidence can
share one invocation; they cannot read each other's answers. Related answers are
not automatically statistically independent. Keep exact counting and threshold
logic in Python, and evaluate thresholds, false triggers, missed triggers, latency
and complete-task outcomes on public development evidence.

The [TypeSafe Noul](https://docs.typesafe.ai/primitives/noul),
[Choice](https://docs.typesafe.ai/primitives/choice) and
[confidence](https://docs.typesafe.ai/confidence) guides explain these primitives.
This component deliberately exposes text instructions and descriptions, rather
than every input format or question type supported by the provider.

Every invocation records its actual state, questions, raw response and owned model
attempts. Online Judge consumes task and ancestor research budgets. Its pinned Jev
model, SDK metadata and request settings are recorded in `trace.json` under
`judge_configuration` on first use; it shares the bounded transport with post-run
analysis. The generated component contract owns reservation and failure details.
Missing setup, exhausted budgets and provider failures do not become a neutral
judgment. See [Jev setup](docs/jev.md#setup-and-offline-inspection).

Changing questions, categories or branching changes the candidate design. Freeze
that source and evaluate the whole Loop; a gain does not isolate the classifier
from its surrounding policy. Existing frozen campaigns do not gain Judge access.

## Decisions and termination

`decide` reasons about the task and selects actions in one model call. Its contract comes from
`loopblox/runtime/components.py::decision_schema`:

| Meaning | Returned value |
| --- | --- |
| ActionsSelected | `{"kind": "actions", "actions": [...]}` |
| CompletionProposed | `{"kind": "completion_proposed", "response": "..."}` |
| Scoped completion | `{"kind": "scope_done_proposed", "response": "..."}` |
| Scoped blockage | `{"kind": "scope_blocked", "response": "..."}` |

Omit `scope` for whole-task actions or completion. Pass
`scope={"plan": plan_id, "step": index}` to focus on an original Plan step. In that
scope, Decide returns actions, local completion, or local blockage; it cannot
propose whole-task completion. Python owns step iteration, recovery, replanning,
and returning to whole-task decisions. Neither local result ends the worker or
advances the Plan automatically. The full task remains visible, and scope does
not create a new worker, separate allowance, or additional tool access.

The decision parameter `tool_filter` selects disclosed tool kinds:
`all`, `inspect`, `inspect_test`, `inspect_mutate`, or `test`.
`inspect_mutate` includes inspection and mutation tools. The filter changes tool
disclosure, not the selected scope; the component catalog defines the exact mappings.

Current interfaces use these names; this guide was checked on 2026-09-20. `decide`
now owns joint reasoning and selection; `think_decide` and `decompose` are not
current components. Plan owns structured task decomposition. AgentWork and the
`work` reference type are absent; completion review targets the decision ID. Reproduce historical episodes
with their frozen implementation and contracts. Moving an older controller to the
current library requires updating its API usage and evaluating it under the new
library condition; historical source and result records remain unchanged.

Actions must be nonempty. The host registers immutable requests and adds action
IDs; the caller chooses when to execute them. Empty actions are not completion.
The decision component returns the completion variant; its controller decides
whether to review that decision, continue, or return. A selected Plan step can
contain many decision/tool iterations. No fixed round count is required.

Actual tool effects, task termination, and hidden verification remain distinct.
The worker closes before sealed scoring; no evaluator feedback reaches that
completed controller. An ordinary failed tool can prompt recovery. The fixed
model gateway permits at most three exact retries per logical request (four
attempts total), within the charged-time, model-call and output budgets.
`concurrency_limit_exceeded` waits 60 seconds; other recognized transient faults
wait two seconds. Exhaustion preserves the operational error for infra diagnosis.
Recognized no-effect timeout attempts and their retry waits
are excluded from task and research time, with their actual duration retained in
the ledger. Successful requests and other work still consume time.
Only failures with no effects qualify; retries other than concurrency limits wait two seconds;
every attempt consumes model-call and output budget. If the remaining budget cannot admit that
retry, the original operational failure remains the outcome. Exhaustion before
any attempt remains budget exhaustion. Controller recovery issues new decisions or
fresh rule actions, never replays an attempted model action ID.
The complete HTTP request has its own deadline, even when less charged task time
remains. Streaming Chat Completions renew this deadline on generation deltas,
including reasoning; heartbeats do not renew it. A successful response that exhausts charged time is recorded
but not delivered. A timed-out attempt retains unknown usage and its reserved
allowance; excluding its wait does not refund calls or tokens.

Online Judge provider input-size rejection raises a catchable `RuntimeError`
prefixed `judge_input_limit`. It creates no judgment and does not cancel dispatch.
The Loop may select smaller evidence or questions; an uncaught error produces a
candidate error for official scoring and researcher feedback.

## Environment and traces

`env.task`, `env.tools`, `env.history`, and `env.remaining` expose public facts,
tool descriptions, history, and remaining limits. Local copies cannot mutate host
state. Python computation and control flow are permitted. Model calls, context
views, observations, and task effects pass through approved components. There is
no generic model instruction API, custom output schema, or component registration.
The worker has no network, credentials, host mount, task checkout, or evaluator.

A host may explicitly freeze an unlimited allowance as `null` in its JSON limits
(`None` in Python). The corresponding `env.remaining` value is also `None`;
accounting continues and any finite parent allowance still applies. Each task and
research allowance is frozen independently. Continuous campaigns use the accepted
telecom per-task limits in `loopblox/research/campaign.py::TASK_LIMITS` and no shared
research cap, as specified in [experiment.md](experiment.md). Unlimited budgets do not
remove individual model request deadlines or requested output allowances.

Invocations record their effective parameters, output, status and timing. Current
subcomponents are direct controller calls with parent_id=null; ordinary Python
helpers and directory families do not create invocation boundaries. Input
references express data use, not parent-child calls. Actual requests, retries and
tool effects are charged once. Environment model calls retain the active
component ID in their private ledger.

Each settled run writes `trace.json` and a read-only expandable `trace.html`.
The report derives family labels and actual calls from the frozen catalog and
trace. Historical nested calls and their frozen composite source remain readable;
they do not create current runtime capabilities. Reports cannot reveal unexecuted
branches. Model request/tool timing is
recorded, but the current engine still uses sequential decisions and execution.
Report depth labels derive from the actual call tree: D0 is the complete run,
D1 its direct component calls, and deeper positions expand component internals.
Component and mechanism record types are shown separately; depth is not a fixed
Harness layer or a permanent property of a component.
Interrupted records survive; an abrupt host termination may leave JSON without
an HTML report. Render recorded traces from the repository root with
`python3 -B -m loopblox.report <trace.json>`.

## Research and proposals

The researcher saves immutable Python candidates, evaluates the fixed development
tasks, analyzes public evidence, writes notes and proposes components. The host
runs the supplied baseline once on the whole task list before research begins.
It selects the best fully evaluated Loop by official successes, then known agent
input tokens, then agent model calls; a full tie keeps the incumbent. Missing
scores cannot qualify a candidate, and unknown cost never becomes zero.

One iteration saves one new source by default, at most two. Duplicate saves reuse
the existing ID and rationale. Evaluate the new sources, inspect their outcomes,
then call `checkpoint(notes)` with the hypothesis, evidence, failed approaches and
next direction. It preserves the iteration and continues research. `progress.json`
records the incumbent, pending candidates and completed iteration count. There is
no researcher `select` or `finish` tool; the user owns stopping.

Development agent, simulated-user and Jev calls share an uncapped gateway ledger.
Native usage is recorded separately with its coverage limitations. Per-task limits
still apply. Research runs on one frozen benchmark; test tasks and final feedback
are unavailable. New campaigns import no historical candidates or notes. Recovery
of this same logical campaign preserves completed batches and checkpoints under
[experiment.md](experiment.md#stopping-and-recovery), with a fresh native researcher.

The initial task's `initial_selection` identifies the incumbent after opening or
recovery. `episode` names the current public scope; evaluation tools take local
candidate IDs.

Paths in `evidence.json` are relative to the current public file root and can be
passed directly to `read_artifact`. Reading a directory lists exact paths;
reading a file returns its canonical path alongside paginated text. Host records
own task outcomes and spend. Notes and rationales remain researcher claims. Keep research history and scores out of candidate source comments and
task-agent input. Private simulator data, evaluator internals and final scores
remain unavailable to the researcher.

A missing-file read returns `status=failed`, with an `artifact_not_found` result,
the canonical missing path and available paths in the nearest public directory.
Correct the path or list that directory. Codex receives the failed host receipt
in its next invocation and can choose another request. A later successful read
of a newly created file is allowed. A failed or interrupted researcher has not
completed another iteration; its last fully evaluated incumbent remains available for audit.

`evidence.json` provides cumulative host-derived counts for the current episode;
evaluation receipts provide compact batch summaries and links to the complete records.
These totals retain failures and distinguish unstarted runs. Every completed
candidate covers the same fixed tasks. Results remain training evidence; a better
score alone does not isolate its cause. The full protocol is in
[experiment.md](experiment.md).
When the environment uses a simulated user, its model calls also consume these
budgets and the per-task model/time limits. They are environment calls, not
additional candidate-controlled components. Their private prompts and tools do
not become public evidence merely because they are charged.

### Public evidence workspace

`research_shell(command, timeout_seconds=30)` executes shell or Python analysis.
Its working directory is `/work`, a writable scratch directory retained across
commands in this episode. `/evidence` is the read-only public artifact root,
including the completed evidence retained within this campaign. Python's
standard library and `sh` are available; additional programs are not assumed.
The initial task links to this guide, the component contracts, `jev-guide.md`,
`jev-config.json` and `research-workspace.json` instead of injecting their full
contents. Read the relevant files before designing a candidate.

Research tools run serially. Analysis commands and their background processes
close before evaluation starts; the next researcher request runs only after the
whole evaluation and mandatory Jev analysis finish. Saved candidates, notes and
retained command output are available when their tool receipts return, including
output from recoverable command failures. A successful `checkpoint` preserves an
iteration and starts a new native conversation for the next iteration; other
requests continue the same conversation, as defined in [experiment.md](experiment.md#selection-and-checkpoints).

Use the workspace to search text, parse JSON, compute paired differences, follow
invocation IDs and save reusable analysis scripts. For example:

```sh
python - <<'PY'
import json
from pathlib import Path

for path in sorted(Path('/evidence/evaluations').glob('*/result.json')):
    evaluation = json.loads(path.read_text())
    for run in evaluation['runs']:
        print(evaluation['evaluation_id'], run['candidate_id'], run['task_id'],
              run['draw'], run['repeat'], run['status'],
              run.get('verification_verdict'), run.get('trace_summary'))
PY
```

The tool returns an exit code, bounded output preview and paths to the exact
command, captured output and execution record under `analysis/`. Paths are
relative to `/evidence` and also work with `read_artifact`. Large output is stopped
at the frozen capture limit and marked truncated, not silently treated as complete.
An ordinary script error, command timeout or output limit is observable; inspect
the result and refine the analysis. Keep useful scripts in `/work` and record
conclusions with evidence references in `notes.md` or candidate rationale.

Each command uses a fresh container; background processes end with it. Only
scratch files persist, not a Python session or environment variables. The command
has no network, provider credentials, private simulator/evaluator files or task
dispatch interface. `save_candidate`, `evaluate` and `checkpoint` own their existing
operations. Command duration, process memory and captured output are bounded;
`research-workspace.json` freezes the limits. Scratch has no filesystem quota.
Commands consume research time through the existing tool gateway. They make no
model calls and consume no development task runs.

Scratch and analysis output are researcher-produced material, not verified task
facts. They do not become host-verified evidence. Public source
records remain authoritative and read-only. A new episode gets a new workspace.

`save_candidate(source, rationale)` stores a complete Python Loop and a brief
research rationale. State the observed evidence or explicitly untested hypothesis,
the change, expected outcome and how to check it. Cite the development records you
actually used; do not present a presumed cause as an observed fact. The host checks
that the rationale is nonempty and at most 16000 characters; it does not certify
the reasoning or require a fixed research sequence.

The receipt returns `candidate_id`, `path`, `rationale_path` and `created`.
`candidates/<id>.py` owns the source; `candidates/<id>.json` stores its original
rationale and a source hash. Both are immutable and readable with `read_artifact`.
The host-supplied baseline is documented through the same interface. Rationale
text stays in the research record and is not passed to task-solving controllers.

Saving exactly the same source text returns its existing ID with `created=false`;
the original source and rationale are retained. This checks exact text, not
behavioral equivalence. Reuse the existing evidence for an evaluated source;
another evaluation of the same source is rejected.
Use `write_notes` for revised hypotheses or reasons to gather further evidence;
resaving identical code does not create a new design or reset its evaluation record.

The shared research task supplies a flexible reasoning cycle: choose a worthwhile,
in-scope problem or opportunity; assess its possible causes and scope; form a
hypothesis; decide what evidence would support or weaken it; implement and compare;
then update the explanation and candidate selection using complete-task outcomes
and cost. Successful runs can expose avoidable work too. Inspect more evidence,
revise or abandon a hypothesis, then record the next direction. These reasoning
instructions do not prescribe which mechanism to try. A failed hypothesis does
not stop research; only the user or an infrastructure interruption does.

Distinguish model errors from harness errors. Inspect the exact model-visible
context and instructions, the recorded response, and how the controller used it.
Evidence present elsewhere in a trace may not have reached that model request.
Errors in the fixed model's reasoning, knowledge or instruction following are
outside the editable scope. A wrong answer, failed task, component firing count
or Jev judgment alone does not establish a harness defect.

A harness hypothesis must identify a specific editable policy and its predicted
effect. For example, an incorrect completion proposal is model output; whether
the Loop should perform an approved check before returning is a separate research
question. Do not assume that adding checks or repeated calls is warranted for
every model error. Even if a candidate corrects the outcome, that does not by
itself prove the original harness was defective or the model's capability changed.
Keep model-origin errors visible, retain mixed or uncertain attribution, and
compare the mechanism's outcomes and cost, marking untested assumptions explicitly.
If no defensible in-scope mechanism can be identified, record the model limitation
and pursue another question. Infrastructure
and verifier faults retain their separate stop rules.

`evaluate(candidate_ids)` freezes the requested source snapshots before dispatch.
Every candidate runs once on all ten frozen tasks, in their fixed order, with
fresh environments and workers. When evaluating two new candidates together,
execution order rotates by task index. Candidate IDs must be unique and belong
to the current iteration. An already evaluated source cannot be dispatched again;
inspect its recorded results. There are no task-sampling or repeat arguments.

The host releases feedback only after all task runs and mandatory Jev analysis
complete. Only complete batches participate in ranking. Infrastructure or verifier
faults stop the attempt and retain all attempted and unstarted rows. Ordinary task
failures remain valid scores. Missing scores are neither losses nor wins. Unknown
cost remains unknown. Check complete task success, model input/output usage and
agent/user cost when investigating an observed difference.

Each `evaluations/<id>/result.json` stores the shared draws, execution order,
source snapshots/hashes, planned and attempted runs, per-candidate summaries and
paired outcome/cost differences. Each run's `summary.json` derives component
invocation IDs/statuses, owned model attempts, tool outcomes/effects and consecutive
identical action/result streaks from its public `trace.json`. Model costs belong
to actual requests and are not counted again on parent components. This summary
does not judge progress or infer causality: a proposed mechanism that did not fire
cannot explain that run's improvement. Inspect the referenced trace for context.

The tool receipt returns aggregate candidate and paired outcome summaries, budget
usage, a Jev overview grouped by measurement schema, and `artifact`/`evidence_path`
navigation. Detailed pairs, individual runs and Jev segments stay in `result.json`.
Use the workspace to select relevant evidence without loading the whole evaluation
into model context. Jev segment navigation connects judgments, confidence and
missingness to actual components, owned agent cost and exact input/response
pointers. `jev-guide.md` explains how to investigate trajectories and compare
paired runs; these judgments guide research and never replace task scoring.

`checkpoint(notes)` requires every candidate saved in this iteration to have a
complete scored and analyzed batch. It writes `checkpoints/iteration-NNNN.json`
with candidate IDs, ranking, incumbent, previous incumbent, notes and cumulative
gateway spend, then admits the next iteration. `write_notes(text)` can update work
in progress; completed checkpoint notes remain unchanged. Checkpoints never end
native research. There is no fixed iteration count or shared research cap.

The host handles a user stop, closes active workers, persists partial attempts and
retains the last fully evaluated incumbent. A native CLI exit alone only yields
its next host request. Invalid or failed native execution is an infrastructure
failure, not a completed campaign. Recovery opens a new output directory and
counts all previous attempts, keeping completed batches and restarting unfinished
ones with fresh workers. Incomplete prior batch evidence remains private.

For τ² tasks, read the disclosed domain policy and agent tool schemas. Use
`respond_to_user` for every customer-facing question, confirmation or reply.
The returned `conversation_done` is a lifecycle signal, not a success score.
The outer controller still owns final return, and that return is not sent as a
message to the customer. No final evaluator feedback arrives during the task.

`propose_component` requires name, purpose, inputs, outputs, behavior,
why_existing_insufficient, and example_composition. Optional implementation is
stored as text in `proposals/`, never executed or installed. Human review and a
new approved library condition are required before use in another episode.
Use purpose to identify scope/surfaces and behavior to specify calls, state effects,
return/failure conditions, fixed internals and options, following the current
generated contracts. Trigger conditions and post-return transitions belong to the
caller unless explicitly encapsulated by the proposed component.

Use `read_artifact` to read `evaluations/<id>/result.json` and a run's
`summary.json` first, then inspect its `trace.json` when needed. `start` is a
character offset (default 0); `limit` is a character count (default 32000, maximum
128000), not a line or token count. Use returned `next_start` to paginate.
Unknown usage stays unknown; incurred costs, failed
attempts, and interruptions are retained. Every episode uses a new directory;
Python continuations are not resumed. `loopblox/benchmarks/run_tau2.py` connects
concrete environments to the host task runner. `ResearchSession` owns research
operations. SpreadsheetBench 2 and Terminal-Bench are not integrated yet.
