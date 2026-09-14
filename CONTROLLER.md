# Current Controller API

This document maps the definitions in [loop.md](loop.md) to the implemented API.
[AGENTS.md](AGENTS.md) owns engineering and episode policy. Each episode exposes
frozen copies as `controller-api.md` and `loop.md`, alongside `experiment.json`
and a derived `components.json`. Only the episode catalog authorizes calls.

A candidate is one Python file defining `run(env)`: a complete Loop definition.
It composes exposed behavioral components using ordinary functions, conditions,
and loops. All current task Loops directly compose the exposed subcomponents.
Python remains the canonical definition; there is no graph language or mandatory
work-loop component.

## Concepts and researcher scope

- A **Loop** defines the whole control process triggered by one primary user
  input until control returns. A **task run / trial** is one concrete execution.
  This runtime starts every task in a fresh worker; it has no steering or sessions.
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
sibling components. Implementations and prompts are fixed throughout the episode;
proposals cannot change an active one.

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
Standard τ² studies use `loopblox.experiments.study.BASELINE_CONTROLLER`, pointing to
`controllers/reactive.py`:

```python
def run(env):
    while True:
        context = env.component("context_full")
        decision = env.component("think_decide", context=context["id"])
        if decision["value"]["kind"] == "completion_proposed":
            return decision["value"]["response"]
        execution = env.component("execute", decision=decision["id"])
        env.component("observe_full", execution=execution["id"])
```

Its defaults use full context, full observations and one selected action per
decision. Each iteration makes one joint decision request, followed by execution
and observation when an action is selected. The outer controller returns on the
completion proposal. The environment supplies the policies and tools. This is a
minimal LoopBlox model/tool Loop, not an execution of a native coding harness.

The baseline is a comparison reference, not a required structure for alternatives.
The current episode's `experiment.json` alone determines available components and
options. You may compose exposed subcomponents directly, remove stages, change
invocation triggers, evidence flow or allowed options, and
choose continuation and return conditions. No component sequence is preferred.
Existing components' internals remain fixed; their composition belongs to your
Python controller. A component's whole-task scope does not create an independent
subgoal, session or worker. Consult its generated contract for actual behavior.

If API syntax examples are useful, read the frozen `examples/index.md`, then the
referenced Python files with `read_artifact`. These are optional source snapshots
from `controllers/`, not an exhaustive search space or a recommended sequence.
They are not included in the default research instructions. Check their component
and option requirements against the episode catalog before using them.

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
`ref<decision>`. Think, Decompose, Plan,
Critique and Reflect return `ref<analysis_result>`. These are API types, not
family IDs or Harness layers. Model-response contracts,
including tool argument schemas, remain enforced by the existing gateway.

Tools may declare `preserve_observation_fields`: top-level result fields retained
in full by `observe_brief`. This host-owned declaration is disclosed with the tool
and recorded in the trace; editing `env.tools` does not change it. The component
catalog defines the representation and character bound for the remaining content.

When proposing an experiment, distinguish changing which component is called,
changing a caller-owned trigger or branch, and changing an allowed component option.
Keep the other choices fixed for an isolated comparison. A full/recent context may
already include earlier analysis results without an explicit input reference;
removing an input ID alone does not prove the model no longer sees that result.

Every context includes the task and is frozen when created. Create another view
to include later events. Explicit inputs can supplement it with existing results
from analysis components or Observation. They cannot inject new instructions. Raw
tool outcomes remain in factual history when an observation shortens them. Model
turns and observations remain available through normal context views.

Critique requires `target=<invocation ID>` for the one analysis result or decision
being reviewed, including a decision that proposes completion. The host sends that target's ID, component,
category and original value explicitly, even when the same result is already in
context. `context` and optional `inputs` supply background evidence; they do not
select the review target. Choosing plan A instead of plan B changes the explicit
target without removing either plan from background context. Missing or invalid
target references fail before a model request. `accept` remains a model judgment,
not authoritative verification or permission to end the enclosing Loop.

## Decisions and termination

`decide` and `think_decide` share the contract from
`loopblox/runtime/components.py::decision_schema`:

| Meaning | Returned value |
| --- | --- |
| ActionsSelected | `{"kind": "actions", "actions": [...]}` |
| CompletionProposed | `{"kind": "completion_proposed", "response": "..."}` |

The decision parameter `tool_filter` selects disclosed tool kinds:
`all`, `inspect`, `inspect_test`, `inspect_mutate`, or `test`.
`inspect_mutate` includes inspection and mutation tools. All choices retain the
same whole-task completion target; the component catalog defines their exact mappings.

Current interfaces use these names as of 2026-09-12. AgentWork and the `work`
reference type have been removed; completion review targets the decision ID. Reproduce historical episodes
with their frozen implementation and contracts. Moving an older controller to the
current library requires updating its API usage and evaluating it under the new
library condition; historical source and result records remain unchanged.

Actions must be nonempty. The host registers immutable requests and adds action
IDs; the caller chooses when to execute them. Empty actions are not completion.
The decision component returns the completion variant; its controller decides
whether to review that decision, continue, or return. All current decisions concern the entire task;
there is no independent subgoal completion API. No fixed round count is required.

Actual tool effects, task termination, and hidden verification remain distinct.
The worker closes before sealed scoring; no evaluator feedback reaches that
completed controller. An ordinary failed tool can prompt recovery. The fixed
model gateway allows one exact retry of recognized transient failures with no
effects; every attempt costs budget. If the remaining budget cannot admit that
retry, the original operational failure remains the outcome. Exhaustion before
any attempt remains budget exhaustion. Controller recovery issues new decisions or
fresh rule actions, never replays an attempted model action ID.
The complete HTTP request has a wall-clock deadline. A timed-out attempt retains
unknown usage and its reserved allowance; it is not assumed to be free.

## Environment and traces

`env.task`, `env.tools`, `env.history`, and `env.remaining` expose public facts,
tool descriptions, history, and remaining limits. Local copies cannot mutate host
state. Python computation and control flow are permitted. Model calls, context
views, observations, and task effects pass through approved components. There is
no generic model instruction API, custom output schema, or component registration.
The worker has no network, credentials, host mount, task checkout, or evaluator.

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
branches or prove native harness equivalence. Model request/tool timing is
recorded, but the current engine still uses sequential decisions and execution.
Report depth labels derive from the actual call tree: D0 is the complete run,
D1 its direct component calls, and deeper positions expand component internals.
Component and mechanism record types are shown separately; depth is not a fixed
Harness layer or a permanent property of a component.
Interrupted records survive; an abrupt host termination may leave JSON without
an HTML report. Render recorded traces with `python3 loopblox/report.py <trace.json>`.

## Research and proposals

The researcher can save immutable Python candidates, evaluate host-sampled
development tasks, inspect public files, write notes, select evaluated
candidates, and propose components in any order. The supplied baseline is
initially selected. The last selection survives research exhaustion and is
frozen before holdout; final feedback never returns to the researcher. Research
and development model calls share accounting; holdout has a separate budget.
The study preallocates the full holdout comparison across baseline and selected
Loops, then rotates candidate order by task index. Its comparison rows and ledger
own final results and costs; episode final summaries are derived views of that
comparison and must not be added to its usage again.
The host may instead configure a research-only episode with no holdout and call
only the research phase. Such an episode cannot run final evaluation. Any later
comparison on its development tasks remains training evidence, not a holdout score.
An inheritance campaign starts a fresh researcher each round. The unchanged unified
baseline remains available. A supplied `starting_source` is saved as a separate
candidate (or reuses the baseline ID for identical bytes); the opening shared draw
evaluates both sources and charges both runs. The inherited candidate becomes the
initial selection after a scored opening trial. Previous evaluation scores and
rationales are not supplied in the Loop-only condition.

When `experience_index` is supplied, `experience_overview` includes that index's
host-derived candidate counts, paired outcomes and paths to public files directly in the
initial task. Its frozen directory contains development evidence from the same
lineage: candidate sources/rationales, paired evaluation records, public summaries/
traces, notes and submission reasons. Historical candidates use readable references
such as `loop_memory-r01/c0003`. A local ID such as `c0001` can identify different
source in another episode. `starting_candidate_history` lists historical references
whose source exactly matches the current starting candidate; it does not transfer
their scores to the current episode. The task's `episode` names the current scope.
Evaluation and selection tools still take current local IDs, not historical references.

Every path in the overview and `evidence.json` is relative to the current public
file root and can be passed directly to `read_artifact`. Reading a directory
lists exact paths; reading a file returns its canonical path alongside paginated
text. Raw historical evaluation/trace files remain exact snapshots, with local IDs
and paths interpreted inside their named historical episode. Use the overview and
evidence links to navigate them. Notes and submission reasons remain unverified
researcher claims. No private simulator data, evaluator internals, researcher model
history, or final scores are inherited.
Experience is research input, never task-agent input or new component authority.
Keep research history and scores out of candidate source comments as well.

A missing-file read returns `status=failed`, with an `artifact_not_found` result,
the canonical missing path and available paths in the nearest public directory.
Correct the path or list that directory. The fixed researcher controller stops
with a recorded controller error if the same canonical path fails again, including
after interleaved actions. A later successful read of a newly created file is allowed.
Such a stop is not an explicit submission: the last selection is retained for audit,
and its unfinished research cannot be inherited. Other tool failures retain their
normal recovery behavior.

`evidence.json` and evaluation receipts provide cumulative host-derived counts for
the current episode. These totals retain failures and distinguish unstarted runs;
different candidate totals may cover different draws. Use the recorded paired
comparisons for performance claims. Rejecting related variants does not exhaust
other mechanisms; an early submission should explain the remaining uncertainty
and why further search is or is not worth its cost. There is no novelty quota.
When the environment uses a simulated user, its model calls also consume these
budgets and the per-task model/time limits. They are environment calls, not
additional candidate-controlled components. Their private prompts and tools do
not become public evidence merely because they are charged.

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
behavioral equivalence. Reuse candidate IDs when requesting more draws or repeats.
Use `write_notes` for revised hypotheses or reasons to gather further evidence;
resaving identical code does not create a new design or reset its evaluation record.

Let evidence guide whether to inspect a trace, change a mechanism, simplify,
repeat a comparison, abandon a hypothesis or finish. There is no required sequence
or quota of novel candidates. Read relevant run summaries before attributing a
failure to a mechanism, and inspect the trace where context is needed. Neither
scores nor firing counts alone establish a cause. When changes repeatedly fail to
help, reconsider the explanation and the available design choices. Additional
components and more varied designs are useful only if results justify them.

`evaluate(candidate_ids, n, repeats=1)` freezes every listed candidate before the
host draws a complete batch of `n` tasks uniformly with replacement. The first
candidate is the control. Every candidate runs on every draw and repeat in a
fresh environment and worker; order rotates by draw plus repeat. The request
requires `len(candidate_ids) * n * repeats` remaining development runs. A singleton
list evaluates one candidate through the same path. The initial baseline trial
uses one development run. Candidate IDs must be unique.

For example, `evaluate(candidate_ids=["c0000", "c0001"], n=2, repeats=2)` requests
eight runs and returns four paired comparisons. Pairing uses draw and repeat;
duplicate draws cannot overwrite earlier results. Repeats measure variability,
not additional independent scenarios. Identical task seeds do not guarantee
identical model or simulated-user behavior. Failed, interrupted and unscored
runs remain in the records; missing outcomes are not losses or wins. Unknown
costs remain unknown. Check both paired success and total agent + user cost.
An infrastructure or verifier fault in any development evaluation stops the
researcher and study before further actions or holdout. The failed attempt and
all unstarted rows remain recorded; this stop is not a budget fallback.

Each `evaluations/<id>/result.json` stores the shared draws, execution order,
source snapshots/hashes, planned and attempted runs, per-candidate summaries and
paired outcome/cost differences. Each run's `summary.json` derives component
invocation IDs/statuses, owned model attempts, tool outcomes/effects and consecutive
identical action/result streaks from its public `trace.json`. Model costs belong
to actual requests and are not counted again on parent components. This summary
does not judge progress or infer causality: a proposed mechanism that did not fire
cannot explain that run's improvement. Inspect the referenced trace for context.

Use `select(candidate_id)` for an interim choice. To conclude, call
`finish(candidate_id, reason)` with a candidate that has at least one scored
development result (`pass` or `fail`) and a nonempty reason (up to 16000 characters)
covering evidence and uncertainty; retaining the baseline is valid. On a successful
receipt, the fixed `controllers/research.py` observes that result and its outer
`run(env)` returns without another model call or later batched action. The tool
itself neither terminates the worker nor starts holdout. The host freezes selection
only after worker closure. A failed submission is observable and recoverable.
A normal completion proposal can still end research; exhaustion retains the last
selection with its distinct status. `select` has the same scored-result requirement;
an unscored attempt alone does not qualify. Notes do not submit a conclusion.

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
concrete environments to the same host-side `ResearchSession` and study runner.
The τ² study freezes retail, telecom and mixed-domain selections before running
any holdout; mixed search receives the sum of the specialist search budgets.
SpreadsheetBench 2, Terminal-Bench and native four-harness evaluations are not
integrated yet. The obsolete SWE-bench placeholder and launcher have been removed.
