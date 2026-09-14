# Component contracts

Generated from `loopblox/runtime/components.py`; do not edit this document independently. Regenerate the repository reference with `python3 -B -m loopblox.runtime.components --markdown > COMPONENTS.md`. Episode copies are generated from that episode's exposed, narrowed catalog.

These are current executable contracts, not a universal Harness taxonomy. Concepts and composition boundaries are defined in `loop.md`. The JSON catalog retains the exact schemas and fixed prompts; the shapes below are reading aids, not executable syntax.

## Shared invocation rules

- Call `env.component(name, **arguments)`; normal return is `{'id': ..., 'value': ...}`. Each output below describes `value`. References use the invocation ID and resolve the host's original result within this run. Local dictionary edits cannot change it.
- Each callable subcomponent has a `family` with an ID, label and description. Families organize the catalog; they are not callable stages, reference types or permission groups. The controller can mix, skip and repeat exposed subcomponents in ordinary Python. Parameters belong to each subcomponent; there is no family-level mode dispatcher or mandatory work-loop component.
- The parameter schema owns accepted reference categories; each component's category owns its returned reference type, shown in the catalog. Equal value shapes do not make reference types interchangeable. These categories are API result types, not Harness surfaces or expansion levels. Optional fields have `?`; omitted inputs mean no supplemental result references. Only listed arguments and approved options are accepted.
- A model request sees the task, its frozen context records, optional input references, the fixed component instruction, remaining limits and (for decisions only) filtered capabilities. Critique also receives its required target's identity and original value separately from background evidence. Controllers cannot provide replacement prompts or schemas. Component prompts are in the JSON catalog.
- All invocations are recorded. Model turns become eligible for later context views; raw tool results require Observation. Analysis results are not private by default: later full context may include them even without explicit inputs. Existing context snapshots never grow automatically.
- Model-call counts describe logical requests when execution reaches them. Invalid input, exhaustion or interruption may stop earlier. One exact transient transport retry is host-owned; every attempt is charged. Work performed inside an environment tool follows that tool's own contract.
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

Produce analysis, hypotheses, plans, subtasks or action/completion proposals. Proposals do not execute tools or end the controller.

| Subcomponent | Returned reference type | Surfaces |
| --- | --- | --- |
| [think](#think) | `ref<analysis_result>` | Turn Control |
| [decompose](#decompose) | `ref<analysis_result>` | Turn Control |
| [plan](#plan) | `ref<analysis_result>` | Turn Control |
| [decide](#decide) | `ref<decision>` | Turn Control |
| [think_decide](#think_decide) | `ref<decision>` | Turn Control |

### Assess (`assess`)

Review a selected target or diagnose observed failures. Current members return model judgments, not verified facts; tool-based checks use Act and observed evidence.

| Subcomponent | Returned reference type | Surfaces |
| --- | --- | --- |
| [critique](#critique) | `ref<analysis_result>` | Turn Control |
| [reflect](#reflect) | `ref<analysis_result>` | Turn Control |

### Act (`act`)

Execute approved tools from model-selected actions or explicit controller requests. Record actual results and effects; the controller owns observation and recovery.

| Subcomponent | Returned reference type | Surfaces |
| --- | --- | --- |
| [execute](#execute) | `ref<execution>` | Action Runtime |
| [execute_rule](#execute_rule) | `ref<execution>` | Action Runtime |

## context_full

Freeze all model turns and explicit observations; always include the task. An optional drop rule can leave failed results out of this view.

**Family:** Context / Evidence (`context`).

**Scope:** One immutable view of the current task history.

**Internal behavior:** Select the indices of every model_turn and explicit observation currently recorded. The task is supplied separately in every model request; raw tool events are not selected. All model turns count, including summaries and analyses. drop is applied last, after the records in scope are selected.

**Calls:** Zero model or tool calls.

**State and effects:** Stores the view as an invocation result; adds no history entry.

**Return and caller responsibility:** Returns records (history indices), not copied messages. Later events require a new view.

**Failure contract:** Unexpected arguments are candidate errors. Time limits and host interruption propagate.

**Inputs and allowed options:**

- `drop` — `"none" | "failed_results"`; optional; default="none". none selects every record in scope. failed_results excludes observations whose status is failed, and the requesting decision turn when every observation it produced is excluded. Recorded history is unchanged; a later view can select those records again.

**Returned value:**

```text
{records: [integer]}
```

## context_recent

Freeze the last 4 model turns and their observations; always include the task. An optional drop rule can leave failed results out of this view.

**Family:** Context / Evidence (`context`).

**Scope:** One immutable recent-history view within the current task.

**Internal behavior:** With more than 4 model_turn entries, select model turns and observations from the 4th-last model turn onward; otherwise select all of them. These are model turns, not user messages or tool rounds: analysis and summary calls also consume the window. The task is always supplied separately. drop is applied last, to the records already inside the window; it does not pull in older records.

**Calls:** Zero model or tool calls.

**State and effects:** Stores a view without deleting or changing history.

**Return and caller responsibility:** Returns records (history indices). Explicit analysis_result/observation inputs may supplement the view.

**Failure contract:** Unexpected arguments are candidate errors. Time limits and host interruption propagate.

**Inputs and allowed options:**

- `drop` — `"none" | "failed_results"`; optional; default="none". none selects every record in scope. failed_results excludes observations whose status is failed, and the requesting decision turn when every observation it produced is excluded. Recorded history is unchanged; a later view can select those records again.

**Returned value:**

```text
{records: [integer]}
```

## context_summary

Summarize a frozen view in one model call; retain original factual records.

**Family:** Context / Evidence (`context`).

**Scope:** The supplied frozen context view, within the current task.

**Internal behavior:** Send the task and selected context records to the fixed summarizer. Return a new view whose only history index points to that summary model turn. A supplied summary view is summarized again; this component never selects a compression threshold.

**Calls:** One logical model request; no tool calls. Every invocation summarizes, including empty views.

**State and effects:** Appends the summary model_turn and stores the new view. Original records remain. Later full/recent views may include both original turns and the summary.

**Return and caller responsibility:** Returns records and summary text. Passing this context ID uses the summary plus the task; it does not automatically include the original selected records.

**Failure contract:** Invalid arguments or result references are candidate errors. Invalid model output is an operational failure, retained with its cost; there is no automatic format-repair call. The fixed gateway may retry one recognized transient request fault with no effects, using the identical request. Limits, interruption and host failures propagate; they do not produce a successful result.

**Inputs and allowed options:**

- `context` — `ref<context>`; required. ID of a completed component invocation in this task run; the host reads its stored original.

**Returned value:**

```text
{records: [integer], summary: string}
```

## think

Analyze the current evidence without selecting executable actions.

**Family:** Propose (`propose`).

**Scope:** Analysis of the whole task through the supplied evidence.

**Internal behavior:** Separate observations, hypotheses and unknowns. No action registration or implicit subsequent Decide. This is an observable analysis result, not access to hidden model reasoning.

**Calls:** One logical model request; no tool calls. Transport attempts are counted separately.

**State and effects:** Appends a model_turn to host history, eligible for later context views. Existing views do not change. The output is recorded evidence, not a mutation of the plan, workspace or controller policy.

**Return and caller responsibility:** Returns observations, hypotheses and unknowns as text lists. The caller decides how to use them.

**Failure contract:** Invalid arguments or result references are candidate errors. Invalid model output is an operational failure, retained with its cost; there is no automatic format-repair call. The fixed gateway may retry one recognized transient request fault with no effects, using the identical request. Limits, interruption and host failures propagate; they do not produce a successful result.

**Inputs and allowed options:**

- `context` — `ref<context>`; required. ID of a completed component invocation in this task run; the host reads its stored original.
- `inputs` — `[ref<analysis_result/observation>]`; optional. Optional existing background evidence appended to the context view; omission is an empty list. No new text, raw execution IDs, context IDs, or independently assigned subgoals.

**Returned value:**

```text
{observations: [string], hypotheses: [string], unknowns: [string]}
```

## decompose

Break the remaining task into concrete subtasks.

**Family:** Propose (`propose`).

**Scope:** Decomposition of the remaining whole task.

**Internal behavior:** Produce textual subtasks. Does not create workers, assign independent goals or execute subtasks.

**Calls:** One logical model request; no tool calls. Transport attempts are counted separately.

**State and effects:** Appends a model_turn to host history, eligible for later context views. Existing views do not change. The output is recorded evidence, not a mutation of the plan, workspace or controller policy.

**Return and caller responsibility:** Returns a subtasks list. Subtask text is advisory; it is not an executable action or subagent handle.

**Failure contract:** Invalid arguments or result references are candidate errors. Invalid model output is an operational failure, retained with its cost; there is no automatic format-repair call. The fixed gateway may retry one recognized transient request fault with no effects, using the identical request. Limits, interruption and host failures propagate; they do not produce a successful result.

**Inputs and allowed options:**

- `context` — `ref<context>`; required. ID of a completed component invocation in this task run; the host reads its stored original.
- `inputs` — `[ref<analysis_result/observation>]`; optional. Optional existing background evidence appended to the context view; omission is an empty list. No new text, raw execution IDs, context IDs, or independently assigned subgoals.

**Returned value:**

```text
{subtasks: [string]}
```

## plan

Write an ordered plan and checks for completion, without executing it.

**Family:** Propose (`propose`).

**Scope:** Planning for the remaining whole task.

**Internal behavior:** Produce ordered textual steps and proposed completion checks. Does not register actions, run the checks or replace a persistent plan. A revised plan is another invocation result.

**Calls:** One logical model request; no tool calls. Transport attempts are counted separately.

**State and effects:** Appends a model_turn to host history, eligible for later context views. Existing views do not change. The output is recorded evidence, not a mutation of the plan, workspace or controller policy.

**Return and caller responsibility:** Returns steps and completion_checks. The caller decides whether to critique or supply the plan to work.

**Failure contract:** Invalid arguments or result references are candidate errors. Invalid model output is an operational failure, retained with its cost; there is no automatic format-repair call. The fixed gateway may retry one recognized transient request fault with no effects, using the identical request. Limits, interruption and host failures propagate; they do not produce a successful result.

**Inputs and allowed options:**

- `context` — `ref<context>`; required. ID of a completed component invocation in this task run; the host reads its stored original.
- `inputs` — `[ref<analysis_result/observation>]`; optional. Optional existing background evidence appended to the context view; omission is an empty list. No new text, raw execution IDs, context IDs, or independently assigned subgoals.

**Returned value:**

```text
{steps: [string], completion_checks: [string]}
```

## critique

Review one explicitly selected analysis result or decision against the available evidence.

**Family:** Assess (`assess`).

**Scope:** Review of one target in relation to the whole task's requirements.

**Internal behavior:** The required target reference selects the object being judged. The host includes its identity and stored value even if it is already in context or absent from that view. Context and optional inputs are background evidence, not alternative targets. Selecting a target does not hide other analysis results in context. No tools or hidden verifier are called.

**Calls:** One logical model request; no tool calls. Transport attempts are counted separately.

**State and effects:** Appends a model_turn to host history, eligible for later context views. Existing views do not change. The output is recorded evidence, not a mutation of the plan, workspace or controller policy.

**Return and caller responsibility:** Returns accept and issues. accept is a model opinion, not verified success or a termination signal. The caller owns acceptance, revision and repetition.

**Failure contract:** Invalid arguments or result references are candidate errors. Invalid model output is an operational failure, retained with its cost; there is no automatic format-repair call. The fixed gateway may retry one recognized transient request fault with no effects, using the identical request. Limits, interruption and host failures propagate; they do not produce a successful result.

**Inputs and allowed options:**

- `context` — `ref<context>`; required. ID of a completed component invocation in this task run; the host reads its stored original.
- `inputs` — `[ref<analysis_result/observation>]`; optional. Optional existing background evidence appended to the context view; omission is an empty list. No new text, raw execution IDs, context IDs, or independently assigned subgoals.
- `target` — `ref<analysis_result/decision>`; required. Required review target: one completed analysis result, decision (actions or completion). The host supplies its ID, component, category and original value separately from background evidence.

**Returned value:**

```text
{accept: boolean, issues: [string]}
```

## reflect

Diagnose observed failures and propose changes to the approach.

**Family:** Assess (`assess`).

**Scope:** Diagnosis of failures present in the supplied whole-task evidence.

**Internal behavior:** Propose causes and adjustments. The caller supplies relevant failure evidence; the host does not require a preceding failed action. Reflection does not change policy or retry a tool by itself.

**Calls:** One logical model request; no tool calls. Transport attempts are counted separately.

**State and effects:** Appends a model_turn to host history, eligible for later context views. Existing views do not change. The output is recorded evidence, not a mutation of the plan, workspace or controller policy.

**Return and caller responsibility:** Returns causes and adjustments. Both are model-produced text lists, not verified root causes or applied changes.

**Failure contract:** Invalid arguments or result references are candidate errors. Invalid model output is an operational failure, retained with its cost; there is no automatic format-repair call. The fixed gateway may retry one recognized transient request fault with no effects, using the identical request. Limits, interruption and host failures propagate; they do not produce a successful result.

**Inputs and allowed options:**

- `context` — `ref<context>`; required. ID of a completed component invocation in this task run; the host reads its stored original.
- `inputs` — `[ref<analysis_result/observation>]`; optional. Optional existing background evidence appended to the context view; omission is an empty list. No new text, raw execution IDs, context IDs, or independently assigned subgoals.

**Returned value:**

```text
{causes: [string], adjustments: [string]}
```

## decide

Select the next action(s) or propose completion from the supplied evidence and analysis results.

**Family:** Propose (`propose`).

**Scope:** One decision about the whole disclosed task.

**Internal behavior:** Use the task, frozen view, optional result references, remaining limits and filtered capabilities to select actions or completion. No separate analysis result is returned.

**Calls:** One logical model request; no tool calls. Transport attempts are counted separately.

**State and effects:** Appends a model_turn and registers host-assigned action IDs with immutable arguments. Registration does not execute actions or modify the environment.

**Return and caller responsibility:** ActionsSelected with a nonempty action list, or CompletionProposed with response text. If the tool filter matches no tools, only a completion proposal is available. The caller owns execution, observation, another decision, review and final return. No fixed number of rounds.

**Failure contract:** Invalid arguments or result references are candidate errors. Invalid model output is an operational failure, retained with its cost; there is no automatic format-repair call. The fixed gateway may retry one recognized transient request fault with no effects, using the identical request. Limits, interruption and host failures propagate; they do not produce a successful result.

**Inputs and allowed options:**

- `context` — `ref<context>`; required. ID of a completed component invocation in this task run; the host reads its stored original.
- `inputs` — `[ref<analysis_result/observation>]`; optional. Optional existing background evidence appended to the context view; omission is an empty list. No new text, raw execution IDs, context IDs, or independently assigned subgoals.
- `tool_filter` — `"all" | "inspect" | "inspect_test" | "inspect_mutate" | "test"`; optional; default="all". Filter disclosed tool kinds, not the completion target: all=inspect,mutate,test; inspect=inspect; inspect_test=inspect,test; inspect_mutate=inspect,mutate; test=test
- `selection` — `"one" | "sequence"`; optional; default="one". one permits exactly one selected action; sequence permits a nonempty ordered list. Both permit a whole-task completion proposal.

**Returned value:**

```text
{kind: "actions", actions: [{capability_id: string, arguments: object, action_id: string}] (min 1)} | {kind: "completion_proposed", response: string}
```

The runtime specializes this union using the invocation's selection option and available filtered tools; each action's arguments must match its tool schema.

## think_decide

Analyze the task and select actions or completion jointly in one model call.

**Family:** Propose (`propose`).

**Scope:** One decision about the whole disclosed task.

**Internal behavior:** The fixed prompt asks for reasoning and selection jointly. The returned schema is exactly the Decide schema, with no separate Think output. Think then Decide uses two calls and is not a visual expansion of this call.

**Calls:** One logical model request; no tool calls. Transport attempts are counted separately.

**State and effects:** Appends a model_turn and registers host-assigned action IDs with immutable arguments. Registration does not execute actions or modify the environment.

**Return and caller responsibility:** ActionsSelected with a nonempty action list, or CompletionProposed with response text. If the tool filter matches no tools, only a completion proposal is available. The caller owns execution, observation, another decision, review and final return. No fixed number of rounds.

**Failure contract:** Invalid arguments or result references are candidate errors. Invalid model output is an operational failure, retained with its cost; there is no automatic format-repair call. The fixed gateway may retry one recognized transient request fault with no effects, using the identical request. Limits, interruption and host failures propagate; they do not produce a successful result.

**Inputs and allowed options:**

- `context` — `ref<context>`; required. ID of a completed component invocation in this task run; the host reads its stored original.
- `inputs` — `[ref<analysis_result/observation>]`; optional. Optional existing background evidence appended to the context view; omission is an empty list. No new text, raw execution IDs, context IDs, or independently assigned subgoals.
- `tool_filter` — `"all" | "inspect" | "inspect_test" | "inspect_mutate" | "test"`; optional; default="all". Filter disclosed tool kinds, not the completion target: all=inspect,mutate,test; inspect=inspect; inspect_test=inspect,test; inspect_mutate=inspect,mutate; test=test
- `selection` — `"one" | "sequence"`; optional; default="one". one permits exactly one selected action; sequence permits a nonempty ordered list. Both permit a whole-task completion proposal.

**Returned value:**

```text
{kind: "actions", actions: [{capability_id: string, arguments: object, action_id: string}] (min 1)} | {kind: "completion_proposed", response: string}
```

The runtime specializes this union using the invocation's selection option and available filtered tools; each action's arguments must match its tool schema.

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

Append full execution results to model-visible history once.

**Family:** Context / Evidence (`context`).

**Scope:** One completed Execute or ExecuteRule result, including status=failed.

**Internal behavior:** Copy the execution's status and outcomes without shortening results. Only one observation of either policy is allowed per execution ID.

**Calls:** Zero model or tool calls.

**State and effects:** Append one observation eligible for new context views and explicit inputs. Existing views and raw execution records remain unchanged.

**Return and caller responsibility:** Returns the full status/outcomes value. Does not judge success, recover or continue the loop.

**Failure contract:** Invalid or already-observed execution references are candidate errors. An interrupted execution is not a completed reference; its partial results remain in the trace. Limits and host faults propagate.

**Inputs and allowed options:**

- `execution` — `ref<execution>`; required. ID of a completed component invocation in this task run; the host reads its stored original.

**Returned value:**

```text
{status: "ok" | "failed", outcomes: [{action_id: string, status: "ok" | "failed", result: any, effects: "none" | "applied" | "unknown", code?: string}]}
```

## observe_brief

Append results once, retaining tool-declared observation fields in full and bounding the remaining serialized content to 1200 characters; retain IDs, statuses, and effects.

**Family:** Context / Evidence (`context`).

**Scope:** One completed Execute or ExecuteRule result, including status=failed.

**Internal behavior:** For object results, extract any present top-level fields named by the originating tool's preserve_observation_fields declaration. JSON-serialize the remaining content, even if short, and cut it to 1200 characters including '… [omitted]' when needed. If fields were extracted, return a JSON string containing preserved (their full original values) and brief (the bounded content string); otherwise return only the bounded string. Preserved fields and wrapper overhead are outside the character bound. The host fixes this tool declaration; candidate code cannot override it. Preserve action IDs, status, effects and optional error code. The bounded content need not be valid JSON. No semantic summarization; one observation per execution ID.

**Calls:** Zero model or tool calls.

**State and effects:** Append one shortened observation; raw results remain unchanged in execution history. New full context includes the shortened observation, not the omitted raw tool result.

**Return and caller responsibility:** Returns status/outcomes with every result represented as a string. No success judgment or recovery.

**Failure contract:** Invalid or already-observed execution references are candidate errors. An interrupted execution is not a completed reference; its partial results remain in the trace. Limits and host faults propagate.

**Inputs and allowed options:**

- `execution` — `ref<execution>`; required. ID of a completed component invocation in this task run; the host reads its stored original.

**Returned value:**

```text
{status: "ok" | "failed", outcomes: [{action_id: string, status: "ok" | "failed", result: string, effects: "none" | "applied" | "unknown", code?: string}]}
```
