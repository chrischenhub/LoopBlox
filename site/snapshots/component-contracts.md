# Component contracts

Generated from `loopblox/runtime/components.py`; do not edit this document independently. Regenerate the repository reference with `python3 -B -m loopblox.runtime.components --markdown > COMPONENTS.md`. Episode copies are generated from that episode's exposed, narrowed catalog.

These are current executable contracts, not a universal Harness taxonomy. Concepts and composition boundaries are defined in `loop.md`. The JSON catalog retains the exact schemas and fixed prompts; the shapes below are reading aids, not executable syntax.

## Shared invocation rules

- Call `env.component(name, **arguments)`; normal return is `{'id': ..., 'value': ...}`. Each output below describes `value`. References use the invocation ID and resolve the host's original result within this run. Local dictionary edits cannot change it.
- Each callable subcomponent has a `family` with an ID, label and description. Families organize the catalog; they are not callable stages, reference types or permission groups. The controller can mix, skip and repeat exposed subcomponents in ordinary Python. Parameters belong to each subcomponent; there is no family-level mode dispatcher or mandatory work-loop component.
- The parameter schema owns accepted reference categories; each component's category owns its returned reference type, shown in the catalog. Equal value shapes do not make reference types interchangeable. These categories are API result types, not Harness surfaces or expansion levels. Optional fields have `?`; omitted inputs mean no supplemental result references. Only listed arguments and approved options are accepted.
- A standard model request sees the task, its frozen context records, optional input references, the fixed component instruction and remaining limits. Think, Plan, Reflect and Choose receive current tool definitions; Decide receives filtered tools. Critique receives its target's identity and stored original, using the original filtered tools and selection limit for a decision target, otherwise current tools. ContextSummary receives no tool definitions. These definitions do not authorize tool execution. Judge uses Jev with caller-defined Noul/Choice questions and host-resolved evidence; its fixed framing and output protocol remain in the catalog. Other components do not accept replacement prompts or schemas.
- All invocations are recorded. Non-summary model turns become eligible for later context views; raw tool results require Observation. Analysis results are not private by default: later full context may include them even without explicit inputs. Summaries enter through explicit context/base references. Existing context snapshots never grow automatically. A through value is an exclusive history cursor; summary views retain their input view's cursor. Full observations replace selected brief pages in new automatic context views without changing earlier snapshots.
- Model-call counts describe logical requests when execution reaches them. Invalid input, exhaustion or interruption may stop earlier. Exact model retries are host-owned and budget-bound; every attempt is charged. Work performed inside an environment tool follows that tool's own contract.
- A normal component return is not task termination or verified success. An execution can return value.status=failed while its invocation status is completed. Exceptions instead mark the invocation failed/interrupted and propagate; incurred costs and effects remain recorded.
- The caller owns trigger conditions, repetition, branches and final return. Components have no permanent D-level. Implementations stay fixed even when visible; an episode may expose only a subset of components and narrow their options. Only the episode catalog grants root-call access.

## Component families

Only the supplied catalog's subcomponents appear below. Family membership does not expose siblings or change argument/reference validation.

### Context / Evidence (`context`)

Select, summarize and publish task evidence for later model calls. Views and observations retain the host's original records.

| Subcomponent | Returned reference type | Surfaces |
| --- | --- | --- |
| [context_full](#context_full) | `ref<context>` | State / Context |
| [context_recent](#context_recent) | `ref<context>` | State / Context |
| [context_summary](#context_summary) | `ref<context>` | State / Context |
| [observe_full](#observe_full) | `ref<observation>` | State / Context |
| [observe_brief](#observe_brief) | `ref<observation>` | State / Context |

### Propose (`propose`)

Produce analysis, hypotheses, scoped plans or action/completion proposals. Proposals do not execute tools or end the controller.

| Subcomponent | Returned reference type | Surfaces |
| --- | --- | --- |
| [think](#think) | `ref<analysis_result>` | Turn Control |
| [plan](#plan) | `ref<plan>` | Turn Control |
| [decide](#decide) | `ref<decision>` | Turn Control |

### Assess (`assess`)

Judge evidence, review a selected target, choose among existing decisions or diagnose observed failures. Members return model judgments, not verified facts; tool-based checks use Act and observed evidence.

| Subcomponent | Returned reference type | Surfaces |
| --- | --- | --- |
| [critique](#critique) | `ref<analysis_result>` | Turn Control |
| [choose](#choose) | `ref<selection>` | Turn Control |
| [judge](#judge) | `ref<analysis_result>` | Turn Control |
| [reflect](#reflect) | `ref<analysis_result>` | Turn Control |

### Act (`act`)

Execute approved tools from model-selected actions or explicit controller requests. Record actual results and effects; the controller owns observation and recovery.

| Subcomponent | Returned reference type | Surfaces |
| --- | --- | --- |
| [execute](#execute) | `ref<execution>` | Action Runtime |
| [execute_rule](#execute_rule) | `ref<execution>` | Action Runtime |

## context_full

Freeze task evidence, or extend an existing view with new evidence; always include the task.

**Family:** Context / Evidence (`context`).

**Scope:** One immutable view of the current task history.

**Internal behavior:** Without base, select every non-summary model_turn and explicit observation. With base, retain that view's records, including an explicitly supplied summary, and select new eligible records from its through cursor onward. If a selected execution has a full observation, select that full observation instead of its brief pages. Raw tool events are not selected. The task is supplied separately in every model request.

**Calls:** Zero model or tool calls.

**State and effects:** Stores the view as an invocation result; adds no history entry.

**Return and caller responsibility:** Returns records (history indices) and through, the exclusive history cursor at creation. Later events require a new view; the base and all earlier views remain unchanged.

**Failure contract:** Unexpected arguments are candidate errors. Time limits and host interruption propagate.

**Inputs and allowed options:**

- `base` — `ref<context>`; optional. Optional frozen view to retain and extend with records from its exclusive through cursor onward.

**Returned value:**

```text
{records: [integer (min 0)], through: integer (min 0)}
```

## context_recent

Freeze evidence around the last 4 observed executions; always include the task.

**Family:** Context / Evidence (`context`).

**Scope:** One immutable recent-history view within the current task.

**Internal behavior:** Locate the last 4 distinct executions in order of their first observation. When earlier executions exist, select non-summary model turns and observations from the first observation of the oldest selected execution onward; otherwise retain all eligible history. Also retain the original requesting decisions for selected executions, even when older. Analysis calls do not advance the window, and more pages or a full observation of the same execution do not count as another execution. For a selected execution, its full observation replaces selected brief pages. The task is always supplied separately.

**Calls:** Zero model or tool calls.

**State and effects:** Stores a view without deleting or changing history.

**Return and caller responsibility:** Returns records (history indices) and through, the exclusive history cursor at creation. Explicit analysis_result, plan and observation inputs may supplement the view.

**Failure contract:** Unexpected arguments are candidate errors. Time limits and host interruption propagate.

**Inputs:** none.

**Returned value:**

```text
{records: [integer (min 0)], through: integer (min 0)}
```

## context_summary

Summarize a frozen view in one model call; retain original factual records.

**Family:** Context / Evidence (`context`).

**Scope:** The supplied frozen context view, within the current task.

**Internal behavior:** Send the task and selected context records to the fixed summarizer. Return a new view whose only history index points to that summary model turn. A supplied summary view is summarized again; this component never selects a compression threshold. No tool definitions are disclosed to the summarizer.

**Calls:** One logical model request; no tool calls. Every invocation summarizes, including empty views.

**State and effects:** Appends the summary model_turn and stores the new view. Original records remain. Ordinary full/recent views exclude summary turns; a summary enters through explicit context or base references.

**Return and caller responsibility:** Returns records, summary text and the input view's through cursor. Passing this context ID uses the summary plus the task; context_full(base=...) adds evidence after the original input boundary. It does not automatically include the original selected records.

**Failure contract:** Invalid arguments or result references are candidate errors. Invalid model output is an operational failure, retained with its cost; there is no automatic format-repair call. The fixed gateway retries model timeouts and concurrency-limit faults within the remaining budgets, waiting two and sixty seconds respectively; only timeout attempts and their waits are excluded from charged time. Other recognized transient request faults permit one retry after two seconds. Retries require no effects and use the identical request. Limits, interruption and host failures propagate; they do not produce a successful result.

**Inputs and allowed options:**

- `context` — `ref<context>`; required. ID of a completed component invocation in this task run; the host reads its stored original.

**Returned value:**

```text
{records: [integer (min 0)], through: integer (min 0), summary: string}
```

## think

Analyze the current evidence without selecting executable actions.

**Family:** Propose (`propose`).

**Scope:** Analysis of the whole task through the supplied evidence.

**Internal behavior:** Separate observations, hypotheses and unknowns. No action registration or implicit subsequent Decide. This is an observable analysis result, not access to hidden model reasoning.

**Calls:** One logical model request; no tool calls. Transport attempts are counted separately.

**State and effects:** Appends a model_turn to host history, eligible for later context views. Existing views do not change. The output is recorded evidence, not a mutation of the plan, workspace or controller policy.

**Return and caller responsibility:** Returns observations, hypotheses and unknowns as text lists. The caller decides how to use them.

**Failure contract:** Invalid arguments or result references are candidate errors. Invalid model output is an operational failure, retained with its cost; there is no automatic format-repair call. The fixed gateway retries model timeouts and concurrency-limit faults within the remaining budgets, waiting two and sixty seconds respectively; only timeout attempts and their waits are excluded from charged time. Other recognized transient request faults permit one retry after two seconds. Retries require no effects and use the identical request. Limits, interruption and host failures propagate; they do not produce a successful result.

**Inputs and allowed options:**

- `context` — `ref<context>`; required. ID of a completed component invocation in this task run; the host reads its stored original.
- `inputs` — `[ref<analysis_result/plan/observation>]`; optional. Optional existing background evidence appended to the context view; omission is an empty list. No new text, raw execution IDs or context IDs. Decision scope uses a separate plan-step reference.

**Returned value:**

```text
{observations: [string], hypotheses: [string], unknowns: [string]}
```

## plan

Write ordered objectives with explicit completion conditions for scoped decisions.

**Family:** Propose (`propose`).

**Scope:** Planning for the remaining whole task.

**Internal behavior:** Produce a nonempty ordered list of objectives and concrete done_when conditions grounded in the task, evidence and tool definitions. The caller can reference a step by its zero-based index as a decision scope. Does not register actions, run checks or mutate an earlier plan. A revised plan is another immutable invocation result.

**Calls:** One logical model request; no tool calls. Transport attempts are counted separately.

**State and effects:** Appends a model_turn to host history, eligible for later context views. Existing views do not change. The output is recorded evidence, not a mutation of the plan, workspace or controller policy.

**Return and caller responsibility:** Returns steps containing objective and nonempty done_when lists. Conditions are proposals, not verified facts or hidden evaluator criteria. The caller owns step selection and progress.

**Failure contract:** Invalid arguments or result references are candidate errors. Invalid model output is an operational failure, retained with its cost; there is no automatic format-repair call. The fixed gateway retries model timeouts and concurrency-limit faults within the remaining budgets, waiting two and sixty seconds respectively; only timeout attempts and their waits are excluded from charged time. Other recognized transient request faults permit one retry after two seconds. Retries require no effects and use the identical request. Limits, interruption and host failures propagate; they do not produce a successful result.

**Inputs and allowed options:**

- `context` — `ref<context>`; required. ID of a completed component invocation in this task run; the host reads its stored original.
- `inputs` — `[ref<analysis_result/plan/observation>]`; optional. Optional existing background evidence appended to the context view; omission is an empty list. No new text, raw execution IDs or context IDs. Decision scope uses a separate plan-step reference.

**Returned value:**

```text
{steps: [{objective: string, done_when: [string] (min 1)}] (min 1)}
```

## critique

Assess one plan, analysis result or decision against requirements using cited public evidence.

**Family:** Assess (`assess`).

**Scope:** Review of one target against its stated scope and the whole task's requirements and policy.

**Internal behavior:** The required target reference selects the object being judged. The host includes its identity and stored value even if it is already in context or absent from that view. Context and optional inputs are background evidence, not alternative targets. Selecting a target does not hide other analysis results in context. When reviewing a decision, disclose its original filtered tools and selection limit; other targets receive current task tool definitions. A scoped decision is judged against its selected objective and done_when conditions, under the whole task's constraints; scope_done_proposed does not claim completion of the whole task. Action proposals are reviewed for supported preconditions, policy compliance and relevance, not evidence of future effects. A response reporting a blocker is reviewed for the truth of the blocker and reported task status. Return exactly one assessment for each distinct material requirement relevant to the target, as supported, contradicted or unknown. Do not duplicate requirements or restate unrelated policy. Keep detail concise and explain how the cited evidence supports the verdict. Evidence references must use the disclosed task ID or component invocation IDs from the model-visible records; supported and contradicted assessments require at least one. No tools or hidden verifier are called.

**Calls:** One logical model request; no tool calls. Transport attempts are counted separately.

**State and effects:** Appends a model_turn to host history, eligible for later context views. Existing views do not change. The output is recorded evidence, not a mutation of the plan, workspace or controller policy.

**Return and caller responsibility:** Returns nonempty assessments with requirement, verdict, evidence_refs and detail. The host derives the overall verdict: contradicted if any assessment is contradicted, otherwise unknown if any is unknown, otherwise supported. These are model judgments, not verified success or a termination signal. The caller owns evidence collection, acceptance, revision and repetition.

**Failure contract:** Invalid arguments or result references are candidate errors. Invalid model output is an operational failure, retained with its cost; there is no automatic format-repair call. The fixed gateway retries model timeouts and concurrency-limit faults within the remaining budgets, waiting two and sixty seconds respectively; only timeout attempts and their waits are excluded from charged time. Other recognized transient request faults permit one retry after two seconds. Retries require no effects and use the identical request. Limits, interruption and host failures propagate; they do not produce a successful result.

**Inputs and allowed options:**

- `context` — `ref<context>`; required. ID of a completed component invocation in this task run; the host reads its stored original.
- `inputs` — `[ref<analysis_result/plan/observation>]`; optional. Optional existing background evidence appended to the context view; omission is an empty list. No new text, raw execution IDs or context IDs. Decision scope uses a separate plan-step reference.
- `target` — `ref<plan/analysis_result/decision>`; required. Required review target: one completed plan, analysis result or decision. The host supplies its ID, component, category and original value separately from background evidence.

**Returned value:**

```text
{assessments: [{requirement: string, verdict: "supported" | "contradicted" | "unknown", evidence_refs: [string], detail: string}] (min 1), verdict: "supported" | "contradicted" | "unknown"}
```

## choose

Select one existing decision, or reject all, without rewriting or executing it.

**Family:** Assess (`assess`).

**Scope:** Comparison of at least two distinct decisions with the same scope.

**Internal behavior:** Use the task, frozen context, current tool definitions and candidates' stored originals to select one existing decision. Every candidate must have the same whole-task or plan-step scope. Reject action candidates if any registered action has already been attempted. Return null if none is suitable. The host limits selected_ref to the supplied IDs or null; selection does not change action arguments, register new actions or execute a candidate.

**Calls:** One logical model request; no tool calls. Transport attempts are counted separately.

**State and effects:** Appends a model_turn to host history, eligible for later context views. Existing views do not change. The output is recorded evidence, not a mutation of the plan, workspace or controller policy.

**Return and caller responsibility:** Returns selected_ref and reason. The caller resolves the selected decision, controls execution and may create more alternatives when no candidate is selected.

**Failure contract:** Invalid arguments or result references are candidate errors. Invalid model output is an operational failure, retained with its cost; there is no automatic format-repair call. The fixed gateway retries model timeouts and concurrency-limit faults within the remaining budgets, waiting two and sixty seconds respectively; only timeout attempts and their waits are excluded from charged time. Other recognized transient request faults permit one retry after two seconds. Retries require no effects and use the identical request. Limits, interruption and host failures propagate; they do not produce a successful result.

**Inputs and allowed options:**

- `context` — `ref<context>`; required. ID of a completed component invocation in this task run; the host reads its stored original.
- `candidates` — `[ref<decision>] (min 2) (distinct)`; required. At least two distinct existing decisions; the host supplies their stored originals. They must have matching scopes.

**Returned value:**

```text
{selected_ref: string | null, reason: string}
```

## judge

Ask Jev caller-defined yes/no or classification questions about visible task evidence.

**Family:** Assess (`assess`).

**Scope:** Typed judgments over one supplied frozen view and supplemental evidence.

**Internal behavior:** Resolve context and optional inputs from host originals. Supply task, ordered evidence, current tool definitions and the fixed evidence instruction as Jev state. Send all questions together; they share state but cannot read each other's answers. The caller may define Noul instructions and optional true/false criteria, or Choice instructions, labels and descriptions. No caller-provided state, replacement task, general output schema or free-text model response. No tool execution, action registration, automatic reflection or task termination.

**Calls:** One logical Jev request using the pinned host transport; no tool calls. Exact retries use the shared gateway. Task and ancestor budgets charge every attempt. Before dispatch reserve 256 output tokens per question plus the UTF-8 byte length of its JSON-encoded question ID and, for Choice, serialized labels twice and 32 tokens per label. Jev has no output-limit parameter: this is a host reservation, retained on unknown usage; actual usage is charged.

**State and effects:** Appends a model_turn containing the question definitions and answers. Later context views and explicit analysis_result inputs can include it. Earlier views stay frozen.

**Return and caller responsibility:** Returns questions unchanged and answers keyed by exactly those question IDs. Noul has type and noul (probability of yes). Choice has type, choice (one supplied label), confidence and probabilities for every supplied label. Values are finite in [0,1]; Choice probabilities sum approximately to one and choice is a maximum. Judgments are claims, not verified facts. The caller owns thresholds, uncertainty handling, triggers and subsequent control flow.

**Failure contract:** Invalid arguments or result references are candidate errors. Invalid model output is an operational failure, retained with its cost; there is no automatic format-repair call. The fixed gateway retries model timeouts and concurrency-limit faults within the remaining budgets, waiting two and sixty seconds respectively; only timeout attempts and their waits are excluded from charged time. Other recognized transient request faults permit one retry after two seconds. Retries require no effects and use the identical request. Limits, interruption and host failures propagate; they do not produce a successful result. Missing Jev credentials/SDK are host faults; insufficient output reservation prevents dispatch. Malformed responses retain their usage and raw evidence.

**Inputs and allowed options:**

- `context` — `ref<context>`; required. ID of a completed component invocation in this task run; the host reads its stored original.
- `inputs` — `[ref<analysis_result/plan/observation>]`; optional. Optional existing background evidence appended to the context view; omission is an empty list. No new text, raw execution IDs or context IDs. Decision scope uses a separate plan-step reference.
- `questions` — `{name: {type: "noul", instructions: string, criteria?: {true?: string, false?: string}} | {type: "choice", instructions: string, criteria: {name: string}}}`; required. Named Noul or Choice questions. The caller may edit instructions and criteria as nonempty text. Choice criteria map 2–255 labels to descriptions. Question IDs are routing keys, not model-visible instructions.

**Returned value:**

```text
{questions: {name: {type: "noul", instructions: string, criteria?: {true?: string, false?: string}} | {type: "choice", instructions: string, criteria: {name: string}}}, answers: {name: {type: "noul", noul: number} | {type: "choice", choice: string, confidence: number, probabilities: {name: number}}}}
```

## reflect

Diagnose observed failures and propose changes to the approach.

**Family:** Assess (`assess`).

**Scope:** Diagnosis of failures present in the supplied whole-task evidence.

**Internal behavior:** Propose causes and adjustments. The caller supplies relevant failure evidence; the host does not require a preceding failed action. Reflection does not change policy or retry a tool by itself.

**Calls:** One logical model request; no tool calls. Transport attempts are counted separately.

**State and effects:** Appends a model_turn to host history, eligible for later context views. Existing views do not change. The output is recorded evidence, not a mutation of the plan, workspace or controller policy.

**Return and caller responsibility:** Returns causes and adjustments. Both are model-produced text lists, not verified root causes or applied changes.

**Failure contract:** Invalid arguments or result references are candidate errors. Invalid model output is an operational failure, retained with its cost; there is no automatic format-repair call. The fixed gateway retries model timeouts and concurrency-limit faults within the remaining budgets, waiting two and sixty seconds respectively; only timeout attempts and their waits are excluded from charged time. Other recognized transient request faults permit one retry after two seconds. Retries require no effects and use the identical request. Limits, interruption and host failures propagate; they do not produce a successful result.

**Inputs and allowed options:**

- `context` — `ref<context>`; required. ID of a completed component invocation in this task run; the host reads its stored original.
- `inputs` — `[ref<analysis_result/plan/observation>]`; optional. Optional existing background evidence appended to the context view; omission is an empty list. No new text, raw execution IDs or context IDs. Decision scope uses a separate plan-step reference.

**Returned value:**

```text
{causes: [string], adjustments: [string]}
```

## decide

Analyze the evidence and select actions or terminal proposals for the task or a plan step.

**Family:** Propose (`propose`).

**Scope:** One decision about the whole task or an explicitly selected plan step.

**Internal behavior:** Use the task, frozen view, optional result references, remaining limits and filtered capabilities to reason and select jointly. With scope, the host also supplies the original plan step's objective and done_when conditions; the task remains visible and constraining. The host narrows the output union to that scope. No separate analysis result is returned.

**Calls:** One logical model request; no tool calls. Transport attempts are counted separately.

**State and effects:** Appends a model_turn and registers host-assigned action IDs with immutable arguments. Registration does not execute actions or modify the environment.

**Return and caller responsibility:** A nonempty actions list, or completion_proposed for an unscoped decision. A scoped decision instead permits scope_done_proposed or scope_blocked with response text. If the tool filter matches no tools, only the applicable terminal proposals are available. Proposals do not mark a plan step complete or end the worker. The caller owns execution, observation, review, local continuation and final return.

**Failure contract:** Invalid arguments or result references are candidate errors. Invalid model output is an operational failure, retained with its cost; there is no automatic format-repair call. The fixed gateway retries model timeouts and concurrency-limit faults within the remaining budgets, waiting two and sixty seconds respectively; only timeout attempts and their waits are excluded from charged time. Other recognized transient request faults permit one retry after two seconds. Retries require no effects and use the identical request. Limits, interruption and host failures propagate; they do not produce a successful result.

**Inputs and allowed options:**

- `context` — `ref<context>`; required. ID of a completed component invocation in this task run; the host reads its stored original.
- `inputs` — `[ref<analysis_result/plan/observation>]`; optional. Optional existing background evidence appended to the context view; omission is an empty list. No new text, raw execution IDs or context IDs. Decision scope uses a separate plan-step reference.
- `tool_filter` — `"all" | "inspect" | "inspect_test" | "inspect_mutate" | "test"`; optional; default="all". Filter disclosed tool kinds, not the completion target: all=inspect,mutate,test; inspect=inspect; inspect_test=inspect,test; inspect_mutate=inspect,mutate; test=test
- `selection` — `"one" | "sequence"`; optional; default="one". one permits exactly one selected action; sequence permits a nonempty ordered list. Both permit the terminal proposals allowed by the decision's scope.
- `scope` — `{plan: ref<plan>, step: integer (min 0)}`; optional. Optional objective and completion conditions from one zero-based step in a stored plan. With scope, terminal proposals concern only that step; omission targets the whole task.

**Returned value:**

```text
{kind: "actions", actions: [{capability_id: string, arguments: object, action_id: string}] (min 1)} | {kind: "completion_proposed", response: string} | {kind: "scope_done_proposed", response: string} | {kind: "scope_blocked", response: string}
```

The runtime specializes this union using the invocation's scope, selection option and available filtered tools; each action's arguments must match its tool schema. Only the terminal proposals for that invocation's scope are allowed.

## execute

Execute pending registered model actions serially, stopping at the first failure.

**Family:** Act (`act`).

**Scope:** The unattempted prefix of one action decision.

**Internal behavior:** Require an actions decision; execute selected registered requests in order. Stop at the first ordinary failure. Unattempted siblings remain available to another Execute; already attempted IDs cannot be executed again, even after failure.

**Calls:** Zero direct model requests. Up to the selected number of tool calls, subject to failure and limits.

**State and effects:** Mark each dispatched action attempted; record tool_call, tool_result and actual effects. May modify the environment. Raw tool results do not enter context views until observed.

**Return and caller responsibility:** Returns status and outcomes for the attempted prefix. A tool failure yields a completed component invocation with value.status=failed. The caller chooses observation and recovery.

**Failure contract:** Invalid requests and unusable references are candidate errors. Ordinary tool failures return status=failed and their reported effects; unexpected tool exceptions return failed/unknown. Limits, interruption and host failures propagate, retaining the attempted prefix and any uncertain in-flight effects. No implicit retry, replay or rollback.

**Inputs and allowed options:**

- `decision` — `ref<decision>`; required. ID of a completed component invocation in this task run; the host reads its stored original.
- `take` — `"one" | "remaining"`; optional; default="remaining". Select the next unattempted action or all remaining actions from this decision.

**Returned value:**

```text
{status: "ok" | "failed", outcomes: [{action_id: string, status: "ok" | "failed", result: any, effects: "none" | "applied" | "unknown", code?: string}]}
```

## execute_rule

Execute a fresh controller rule action directly, with no model endorsement.

**Family:** Act (`act`).

**Scope:** One fresh controller-origin tool request.

**Internal behavior:** Validate and dispatch the supplied capability and arguments through the same host gateway. No decision reference or model endorsement is needed. Each invocation creates a new action ID; repeating identical arguments is a new action, not an idempotent replay.

**Calls:** Zero direct model requests; one tool call if validation and limits allow dispatch.

**State and effects:** Record origin=controller, tool events and effects; may modify the environment. Results require an Observation before context views include them.

**Return and caller responsibility:** Returns status and one outcome on normal return, including ordinary tool failure.

**Failure contract:** Invalid requests and unusable references are candidate errors. Ordinary tool failures return status=failed and their reported effects; unexpected tool exceptions return failed/unknown. Limits, interruption and host failures propagate, retaining the attempted prefix and any uncertain in-flight effects. No implicit retry, replay or rollback.

**Inputs and allowed options:**

- `capability_id` — `string`; required. An available tool from env.tools.
- `arguments` — `object`; required. Must satisfy that tool's parameter schema.

**Returned value:**

```text
{status: "ok" | "failed", outcomes: [{action_id: string, status: "ok" | "failed", result: any, effects: "none" | "applied" | "unknown", code?: string}]}
```

## observe_full

Publish full execution results, including after brief pages, without rerunning tools.

**Family:** Context / Evidence (`context`).

**Scope:** One completed Execute or ExecuteRule result, including status=failed.

**Internal behavior:** Copy the execution's status and outcomes without shortening results. Permit one full observation per execution, either directly or after brief pages. This reads the original stored result and never reruns a tool. After full observation, reject further full or brief reads.

**Calls:** Zero model or tool calls.

**State and effects:** Append one observation eligible for new context views and explicit inputs. Automatically selected contexts use full in place of that execution's selected brief pages. Existing frozen views and raw execution records remain unchanged.

**Return and caller responsibility:** Returns the full status/outcomes value. Does not judge success, recover or continue the loop.

**Failure contract:** Invalid or already fully observed execution references are candidate errors. An interrupted execution is not a completed reference; its partial results remain in the trace. Limits and host faults propagate.

**Inputs and allowed options:**

- `execution` — `ref<execution>`; required. ID of a completed component invocation in this task run; the host reads its stored original.

**Returned value:**

```text
{status: "ok" | "failed", outcomes: [{action_id: string, status: "ok" | "failed", result: any, effects: "none" | "applied" | "unknown", code?: string}]}
```

## observe_brief

Publish a 1200-character page per result, preserving declared fields, IDs, statuses and effects in full.

**Family:** Context / Evidence (`context`).

**Scope:** One completed Execute or ExecuteRule result, including status=failed.

**Internal behavior:** For object results, extract any present top-level fields named by the originating tool's preserve_observation_fields declaration. JSON-serialize the remaining content, even if short, and return up to 1200 original characters starting at offset, without a marker. If fields were extracted, return a JSON string containing preserved (their full original values) and brief (the page string); otherwise return only the page string. Preserved fields and wrapper overhead are outside the character bound. The host fixes this tool declaration; candidate code cannot override it. Preserve action IDs, status, effects and optional error code. The bounded content need not be valid JSON. No semantic summarization. Each offset may be observed once per execution, until a full observation is published. The same offset applies to every outcome; an offset beyond an outcome's content yields an empty page with next_offset=null.

**Calls:** Zero model or tool calls.

**State and effects:** Append a paged observation; raw results and existing views remain unchanged. New contexts select observed pages, and select full instead once it is available.

**Return and caller responsibility:** Returns status/outcomes with every result represented as a string and a next_offset of offset+1200 when more content remains, otherwise null. Preserved fields and the wrapper are outside the page length. No success judgment or recovery.

**Failure contract:** Invalid execution references, repeated offsets and reads after full observation are candidate errors. An interrupted execution is not a completed reference; its partial results remain in the trace. Limits and host faults propagate.

**Inputs and allowed options:**

- `execution` — `ref<execution>`; required. ID of a completed component invocation in this task run; the host reads its stored original.
- `offset` — `integer (min 0)`; optional; default=0. Character offset into each outcome's serialized optional content. Use its next_offset to read another page.

**Returned value:**

```text
{status: "ok" | "failed", outcomes: [{action_id: string, status: "ok" | "failed", result: string, effects: "none" | "applied" | "unknown", code?: string, next_offset: integer (min 0) | null}]}
```
