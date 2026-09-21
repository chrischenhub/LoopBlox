# Harness, Loop, components, and experiment scope

This is LoopBlox's authoritative definition of Harness, Loop, Component, Invocation, behavioral scope, and experiment boundaries, updated September 20, 2026. It supersedes the requirement that every component be a macro stage. The Loop / loop-execution distinction does not classify the entire Harness. [AGENTS.md](AGENTS.md) covers engineering constraints and the research episode lifecycle; [COMPONENTS.md](COMPONENTS.md) contains current contracts; [CONTROLLER.md](CONTROLLER.md) describes composition APIs and examples.

This document distinguishes intended design from implemented behavior. Diagrams, concept names, and example contracts do not create callable APIs.

## 1. Harness and behavioral responsibilities

A **Harness** is the software around a model that manages interaction and execution state, applies control policies, and interacts with tools and environments. It translates user and session events into model requests, environment actions, state updates, and visible responses. It may delegate mechanisms to an SDK or another runtime.

Managing interaction does not imply ownership of the whole environment. Task workspaces and external services have their own state and effects. The LoopBlox host enforces access boundaries, factual records, and accounting. Hidden evaluators belong to the experiment infrastructure and are unavailable to candidate controllers. Each experiment defines the boundaries between model, tools, and environment.

Describe behavior by its **responsibility, or surface**, before deciding which responsibilities need components:

| Behavioral surface | Responsibility |
| --- | --- |
| Interaction / Lifecycle | Receive input and cancellation, manage sessions, steering and queued messages, deliver responses, and close turns. |
| Turn Control | Decide what runs next within a turn, including branching, continuation, recovery, and acceptance of completion proposals. |
| State / Context | Preserve history and artifacts, select model-visible information, and manage summaries, compaction, memory, and instruction content. |
| Model Execution | Execute a supplied request, handle transport, streaming and parsing, apply request retry rules, and report results. |
| Action Runtime | Expose tools, validate and schedule actions, enforce authorization and isolation, and record results and actual effects. |

These responsibilities do not form five strictly nested layers or require one module each. A **policy** is a rule used by a behavior. Permission, budget, verification, and stopping policies must identify what they constrain and where they execute. A hook is an integration mechanism; it does not itself determine the behavior's responsibility.

Every rule has one semantic owner. For example, the caller decides when to request compaction, the context policy determines what survives it, and model execution transports the summarization request. These can compose without maintaining competing versions of one rule. Cross-surface behavior is composed through explicit calls and results.

## 2. The scope of a complete Loop

A **Loop** is the complete control-flow definition triggered by one primary user input and ending when control returns. Its normal path connects that input to a final response and may include branches, repetition, multiple model calls, tools, and subtasks.

A Loop defines control within one user turn of a Harness. In LoopBlox, controller code expresses it: which components to call, how to use their results, where to continue, and when to return. Code may invoke approved behavior directly without another model endorsement. A controller calls a model-bearing component when it needs model reasoning or decisions.

A **task run / trial** is one complete execution of a Loop on a concrete input under fixed experiment conditions. The same definition can produce different paths and call counts. The outer controller's normal return ends a run normally. Interruption, exhaustion, and faults retain their own statuses and must not all be described as successful completion.

A Loop is intended to generalize across a class of tasks. The controller organizes context, decisions, actions, feedback, recovery, and return; a particular task's route, business steps, and plan may emerge at runtime. Business workflows can also be reusable, so task count or the presence of a cycle cannot establish this distinction alone. LoopBlox searches for controllers that handle new instances. One trajectory or a task-specific solution is insufficient evidence of a reusable Loop.

A new primary input after a previous run closes begins another task run. Steering or follow-up input arriving during execution does not automatically start one: the native Harness decides whether to incorporate it or queue it as a later primary input. Experiments must record primary inputs, additional inputs, and return boundaries, without deriving run counts from message counts or a source symbol named `turn`. A session can retain state across turns, outside the current Loop's internal stages. Current experiments use fresh workers and workspaces per task and do not implement session continuity across user turns.

A **model/tool iteration** is one model decision with the actions and feedback it triggers, followed by another iteration if needed. Name other loops explicitly: a UI/event loop handles interface or asynchronous events, while cross-turn memory or skill updates may form an adaptation loop. These need not be instances of the Loop defined here or occur within the current run. The research agent's search and evaluation loop also sits outside the Loop being tested.

## 3. Component and Invocation

| Concept | Definition |
| --- | --- |
| Loop | A complete, reusable control-flow definition triggered by one primary input and ending when control returns. |
| Component | A reusable behavioral block with explicit responsibilities, inputs, outputs, and return conditions. It may compose approved components internally. |
| Invocation | One actual component call within a run, with concrete inputs, outputs, status, and cost. |

A macro stage is one kind of Component and needs no separate stage engine. A component can make zero, one, or multiple model calls and execute multiple tools. Its fixed contract and actual execution determine call counts; a single diagram box does not imply a single call.

The researcher chooses approved components, allowed implementation options, and composition. Approved implementations and fixed framing stay fixed within an episode. When exposed, Judge explicitly permits candidate-authored typed judgment questions and classification criteria; other component prompts remain fixed. Ordinary Python functions in a candidate can organize nested control flow, and the researcher can modify composition code where the experiment allows it. This does not grant access to approved component internals. A wrapper creates neither an approved component nor a recorded component boundary. New components still require proposal and human incorporation.

### 3.1 Capability families and subcomponents

The library has four **families**: Context / Evidence, Propose, Assess, and Act. They describe the main capability of a callable behavior, while surfaces describe responsibilities across the whole Harness. Families do not prescribe Loop stages or order. `loopblox/runtime/components.py` owns family definitions, descriptions, and membership. See generated [COMPONENTS.md](COMPONENTS.md#component-families) for members and parameters.

A **subcomponent** is a callable Component belonging to a catalog family. Membership does not imply execution inside a parent component. Families are not callable, create no invocations or extra cost, and grant no access to sibling components. Each current subcomponent declares one primary catalog family; its full contract describes behavior spanning multiple responsibilities. For example, executing a test is an Act tool behavior whose results may inform Assess.

Every public entry includes frozen `family: {id, label, description}` metadata. Its own `parameters` define its allowed arguments; there is no family-level `mode` or separate dispatch API. `category` and `reference_categories` continue to describe result-reference types. Plan belongs to Propose and returns `plan`; Critique belongs to Assess and returns `analysis_result`. Family membership and compatible references are separate facts.

Current composition uses complete Python controllers calling exposed subcomponents directly. The default model/tool cycle is a baseline controller recipe, with no AgentWork registration or trusted composite-dispatch path. If a future complete behavior needs multiple model or tool calls, define and implement that contract first. Neither family membership nor the term "low level" permanently restricts call counts.

## 4. Scope and expansion depth

A Harness behavior has a **scope**, identifying the lifecycle segment or objective it concerns, and a **surface**, identifying its responsibility. Scope may be a session, turn, explicit subgoal or stage, model/tool iteration, request, or action. These names follow actual contracts; they do not impose a hierarchy every Harness must traverse.

Also identify the behavior's **trigger, integration point, and semantic owner**. An action authorization check decides whether the action may produce effects and runs before execution. It may live in a shared dispatcher or a tool wrapper. Moving that check does not automatically change its rule or make it editable by the researcher.

Define `step` where it is used: it could mean a decision iteration, tool group, or stage. It does not inherently mean one LLM call. Likewise, a source-level "outer/macro loop" need not be LoopBlox macro-stage composition.

The following terms remain useful for discussion:

- **Loop level:** how macro behavioral stages connect after user input until control returns.
- **Loop exec level:** how an expanded stage executes internally, including context handling, model/tool interaction, feedback, and continuation.

Loop exec level names internal execution without fixing its depth. A candidate can be explained by expanding complete workflow, internal stage composition, behavioral operations, and execution mechanisms. That is a view of the candidate, not a universal Harness hierarchy. Authorization, context, and cancellation can act at several integration points. Depth labels do not determine responsibility or edit permission.

This is the current `planned_work.py` control flow. Indentation shows Python branches; it does not create component invocations:

```text
Complete Loop: handle the current user input
├─ Context -> Plan
├─ Python loop
│  ├─ Context -> Decide
│  ├─ Action proposal: Execute -> Observe -> continue
│  └─ Completion proposal: Context -> Critique(target=decision ID)
│     ├─ Contradicted or unknown: retain assessment reference -> continue
│     └─ Supported: outer controller returns the response
└─ Model requests and tool actions belong to their owning component invocations
```

A model/tool iteration is a convenient execution description, without requiring a dedicated entity or fixed pipeline. Standalone Think, summary, or Review calls need not involve tools. Tool groups may contain several actions; model requests may have fixed transport retries; a subagent may have its own internal process. Nesting and concurrency do not imply a fixed number of levels.

**The complete Loop is the execution and final-evaluation unit; each experiment separately defines editable scope.** Accounting and scoring apply to its complete task run under frozen conditions. Local calls can supply diagnostic metrics. Component granularity concerns abstraction depth, and the evaluation unit does not determine edit permission. A whole-task controller can directly use fine-grained components or compose macro components. Direct composition still defines a complete Loop without adding an independent stage boundary.

A native Harness may have one broad autonomous task stage in which the model arranges investigation, planning, edits, and checks dynamically. Do not invent stages to create different diagram shapes or present a sequence observed in one run as a mandatory source-level sequence.

## 5. Components, composition rules, options, and fixed constraints

These concepts have different semantic owners and should not all become freely connected graph nodes:

| Item | Semantic owner | Example |
| --- | --- | --- |
| Behavioral component | Approved component implementation | Review inspects an artifact and returns findings. |
| Composition rule | Calling controller or parent component | Invoke Reflect only after failure; rework after rejected review. |
| Implementation option | Allowed options in the catalog | A tool-execution component uses serial execution or a permitted parallel strategy. |
| Fixed constraint | Experiment environment and host | Tool permissions, resource limits, tasks, scoring, and hidden-feedback boundaries. |

Parallel execution above is a possible future option; current tool groups run serially.

**LoopBlox exposes selected Harness behaviors as composable Blox, calling rules, and approved options while fixing the other mechanisms and experiment conditions.** A surface need not correspond to one block. A component may encapsulate multiple responsibilities with a clear contract and semantic owner. The approved catalog bounds the current search space; this classification adds no edit permissions.

A diagram's `decision` may be a code branch rather than an LLM Decide call. Logs, protocol conversion, and input/end markers can be displayed without becoming searchable components. Expanding approved internals in a view does not let the researcher modify them.

Components should remain complete behaviors worth testing experimentally. Do not turn every Python statement into a block. Establish responsibilities and replaceable behavior before defining display boundaries.

## 6. Required contracts for new components

| Contract field | Required answers |
| --- | --- |
| Responsibility and target scope | Does it handle the whole task, a subgoal, or local work on an action group? Do not infer this from its name or model-call count. |
| Inputs and visibility | Which task facts, context, artifacts, and shared state can it read? How does the parent supply them? |
| Outputs and effects | What does it return? Does it update shared state, call tools, or affect the environment? Which results reach the caller? |
| Internal capabilities and options | Which approved components and tools can it use? Can it make repeated model interactions? Which arguments vary and which behaviors stay fixed? |
| Return and failure conditions | When does control return to the caller? How are ordinary failures represented? How do interruption, exhaustion, and faults propagate? |

The contract owns internal behavior; the parent controller owns call timing and subsequent transitions. Map responsibility, scope, and integration points to the contract and concrete call sites without adding a competing hierarchy schema. The researcher can change approved composition, but cannot expand its permissions through fabricated results, replacement prompts outside Judge's typed-question contract, or hidden scoring access.

`loopblox/runtime/components.py` solely owns executable per-component contracts: families and membership, parameter/result schemas, reference categories, fixed prompts, and `contract` fields for responsibility, scope, internals, call-cost semantics, effects, return, and failure conditions. The host reads allowed reference categories from parameter schemas. They are API result types rather than Harness layers. [COMPONENTS.md](COMPONENTS.md) is generated from the catalog. An episode's `component-contracts.md` and `components.json` derive from the same filtered catalog, exposing only its approved components and options. Source visibility does not expand that boundary.

An experiment must distinguish changes to component identity, caller triggers/transitions, and approved implementation options. Inspect actual information visibility as well. Full context already includes earlier analysis artifacts, so removing an explicit input reference may leave the artifact's influence intact. Contracts make this inspectable; causal conclusions still need matched controls.

A **future Task Execution component**, for example, might take an explicit subgoal, approved plan, and context reference; make multiple model/tool calls; and return stage artifacts, attempted actions, and unresolved issues. It would hand control back on a defined stage return condition or blockage. The parent would choose review, further work, or completion. Exact fields, prompts, and implementation must be approved before incorporation; this example creates no API.

Matching names do not guarantee matching contracts. Current `plan` proposes an immutable list of steps with objectives and completion requirements. A controller can scope decisions to one of those steps, but Plan does not execute a step, maintain its progress, or start a worker. Recheck scope, state visibility, and return semantics when wrapping an existing controller.

## 7. Completion signals and control ownership

**Component return, stage completion, task-run termination, and a passing score are separate events.**

- The model may propose actions or completion, while the caller owns outer control flow.
- A subcomponent return closes that invocation and returns control to its caller.
- The parent controller may continue, switch components, request rework, or return to its caller.
- A normal outermost controller return ends the task run. The environment's authoritative evaluator determines success.

Nested components must bind completion proposals to their current target scope. Finishing a subgoal does not automatically authorize the final user response. An ordinary component failure need not terminate the outer run; recovery follows its explicit contract. Starting a subcomponent cannot reset interruption or resource limits.

Current `decide` reasons and selects actions jointly. Without an explicit scope it returns `ActionsSelected(actions)` or `CompletionProposed(response)`. With `scope={plan: plan_id, step: index}`, the host resolves one original Plan step and the decision returns actions, `scope_done_proposed`, or `scope_blocked`. The JSON contract is `loopblox/runtime/components.py::decision_schema`. Empty actions do not mean completion. Whole-task `kind="completion_proposed"` carries a proposed `response`, which the caller may accept; it may describe an actual blockage. Local completion and blockage concern only the selected step and cannot terminate the task by themselves.

Controllers handle decision results directly. They may inspect completion or pass the decision ID to Critique and continue when evidence is contradicted or unknown. The host derives Critique's overall verdict from its evidence-linked assessments; it is a model judgment, not a verified score. Choose can compare existing same-scope decisions and return one original reference or decline all of them. Neither operation executes actions. Ordinary Python helpers organize step iteration, recovery, replanning, and final return without an extra work result, progress engine, or `work` reference type.

Controllers own conditional repetition; components may also repeat internally under their fixed contracts. Normal completion does not require exactly N iterations. A model transport retry follows fixed host rules, while a new decision is a new behavioral call. Recovery branches cannot implicitly replay tool actions.

## 8. Actual invocations, traces, and visualization

Python remains the sole executable Loop definition, and approved code owns component behavior. The first version has no JSON control-flow language or graph compiler; the website is read-only. Components may be expanded for inspection without making those details editable experiment variables.

Traces distinguish:

- a complete task run;
- component invocations and their actual parent-child relationships;
- each component's model requests, transport attempts, tool actions, and environment effects.

A data dependency is not necessarily nesting. Review referencing Execution's output does not make Review a child invocation of Execution. Names cannot establish ordinary function calls or unrecorded stage boundaries.

Report labels D0, D1, D2, and so on derive from the actual call tree and indicate expansion depth. Reports also identify the containing composition and record type: composite component, leaf component, model request, or tool action. Depth labels are neither additional Harness layers nor permanent component properties. Current subcomponents are called directly by the controller. Reports retain historical parent-child relationships without inventing parent nodes from family membership.

The host ledger counts model and tool usage once. Parent summaries may aggregate descendant costs, but totals must not add those summaries again. Concurrent durations also cannot simply be summed as wall-clock time.

Actual traces explain **what happened in a run**; structural diagrams describe **possible controller behavior**. Both need explicit provenance. Static scenario animations can illustrate behavior but are not execution records or optimization evidence. Current traces record invocation, model-request, and action ownership with timing; current subcomponents have null `parent_id`. Read-only HTML derives capability families from the record and frozen catalog. Historical composite calls retain their original relationships and implementation context. Native stream concurrency, session events, and complete dependency graphs are not yet recorded.

## 9. Defining the researcher's experiment scope

A research episode sits outside the task run being evaluated. The researcher creates candidates, requests evaluations, and analyzes development feedback; the task controller handles input and component results. The research cycle is not an internal stage of the tested Loop. Final hidden scoring never returns to a completed task controller.

**Each experiment freezes its exposed composition boundary before the episode starts.** This specifies editable composition positions, available components and options, and behavior held fixed inside components. Different experiments may expose different depths, but the researcher cannot expand, retract, or move the boundary within an episode.

For example, exposing `Planning -> TaskExecution -> Review` leaves TaskExecution internals fixed. Exposing its internal `Context -> Decide -> Execute -> Observe` requires an explicit internal composition position and parent constraints. Joint search may expose several specified positions without forcing one graph-wide depth. A behavior cannot have two competing definitions in a fixed parent implementation and independently editable internal composition.

An exposed internal boundary still does not permit arbitrary edits to approved source or prompts. Internal composition must be available through the episode's approved interfaces and options, or expressed as candidate code over fixed subcomponents before the experiment starts. If current components cannot express the boundary, propose and incorporate the necessary component before opening a new episode. Visual expansion changes no permissions.

**The implemented boundary is a root composition boundary.** `experiment.json` freezes the research question, components directly callable by candidates, and each component's allowed discrete options. The host enforces the same restriction for baseline, development, and holdout runs. Any composite component must call its internals through its fixed implementation. Candidates can freely compose exposed outer calls. This does not lock arbitrary Python workflow shapes or expose arbitrary source positions. An internal experiment can expose approved fine-grained components for recomposition. Fixing a parent workflow while searching one internal position requires a corresponding approved interface; prose alone cannot enforce it.

Every new experiment should give the researcher a clear guide covering:

1. The objective and baseline: the question and the supplied Loop source.
2. The frozen exposed boundary: responsibilities and target scopes, components and call sites, triggers, implementation options, composition rules, semantic owners, and fixed internals.
3. Executable contracts: the episode catalog, scope, inputs, outputs, return, and failure semantics. APIs mentioned only in design documents are unavailable.
4. Conditions and evidence: task splits, model/environment settings, limits, scoring, task/search cost accounting, expected effects on model input, action effects, state updates or returns, and how to compare them.

**An architectural difference is not automatically a meaningful experiment variable.** Moving a rule into a tool wrapper or handing an equivalent loop to an SDK may change only code organization and maintenance. A task-performance experiment must identify a behavioral change. If only execution overhead changes, state that overhead is the subject. Different graph shapes or module boundaries do not establish a new reasoning strategy.

Describe editable behavior and fixed conditions separately:

| Candidate behavior | Required invariant |
| --- | --- |
| Continue, reflect, or return a blockage after action failure or refusal | Authorization rules and enforcement cannot be bypassed. Moving a check does not grant edit permission. |
| Choose when to invoke model-visible checks and how to use results | Authoritative scoring and hidden tests remain fixed and inaccessible to candidates. |
| Allocate allowed resources among planning, action, checking, and early stopping | Total limits and actual accounting remain fixed; failures and interruptions retain costs. |
| Choose context views or approved tool-scheduling strategies | Original facts and effects are preserved; tool implementation, allowed concurrency, and isolation remain fixed. |
| Make a new model decision after failure | Charge the new call normally; transport retry rules do not vary with the controller. |

These are ways to specify boundaries, not a claim that every option is implemented. The researcher receives only the executable capabilities exposed by its episode.

The following scopes are experiment conditions using the same runtime:

| Experiment scope | Editable behavior | Fixed behavior |
| --- | --- | --- |
| Macro composition | Stage selection, order, handoff, branches, and repetition | Stage internals and implementation options |
| Internal execution strategy | Explicitly exposed internal candidate composition or catalog-approved options | Outer macro workflow and other behavior |
| Joint search | Specified macro and internal changes | Unexposed implementations and environment constraints |

Approved implementations and fixed framing stay fixed even in internal or joint search, including those of incorporated composite components. Judge's caller-defined questions are an explicit parameter, not edits to those internals. The researcher edits allowed candidate composition or selects catalog options, including Judge questions and Noul/Choice criteria when exposed. Rewriting approved internals requires a proposal, human incorporation, and a new library condition and episode.

An example instruction for a future macro experiment is:

> Compare macro compositions of Planning, Task Execution, and Review. Select, order, repeat, and conditionally invoke these approved components while fixing their internals and options. A subcomponent return completes only that call. The outer controller decides whether to continue and when to answer. Use development feedback during search, then evaluate complete outcomes and total cost on tasks excluded from search.

This is a future contract example; Task Execution and AgentWork are not current components. The supplied `experiments/workflow.json` directly exposes context, Plan, Decide, Critique, Execute, and observation components. It permits both Python composition and catalog-option changes, making it joint search without a fixed internal or outer workflow. [CONTROLLER.md](CONTROLLER.md) provides operational instructions. New episodes copy `public/controller-api.md`, `public/loop.md`, the frozen experiment specification, and its filtered catalog.

When several levels change together, gains cannot be attributed solely to macro structure. Traces suggest explanations; matched controls and ablations test them. A single success does not establish improvement, and a searched composition may not beat the original baseline. Freeze the model, budget, and statistical protocol separately for each experiment.

## 10. Current implementation boundaries

- `controllers/*.py` define complete task controllers that directly compose exposed subcomponents. `reactive.py` is the shared baseline; completion review references decision results directly.
- `loopblox/runtime/components.py` owns four families and the membership and contracts of 14 subcomponents. Each current model-bearing subcomponent makes one logical model call, with every transport attempt charged separately. Families add no calls or permissions.
- Plan steps can scope decisions; Python owns their composition and continuation. AgentWork, `work` references, trusted composite dispatch, and subagent components are absent.
- Research entry points freeze the question, outer components, and allowed options. Judge questions and category definitions may vary with the frozen candidate source. The host restricts calls but does not enforce edit constraints at arbitrary internal source positions.
- Invocation records contain actual parent-child relationships. Normal finalization writes JSON traces and expandable read-only HTML showing executed paths and frozen implementations without inventing unexecuted branches.
- Decide's `tool_filter` filters tool capability categories. `inspect_mutate` selects inspection and mutation tools. Tool filters are independent of task or Plan-step scope and do not grant additional permissions.
- Full context can combine an explicit frozen base with later evidence; summaries preserve their source cursor. Recent context counts four first-observed executions instead of model calls. Brief observations can be paged and later expanded to full results; new views prefer a full observation, while existing views stay frozen.
- Tool groups run serially. The host owns models, permissions, scoring, budgets, and original facts.
- Research connects to environments through a host-provided task runner. τ²-bench uses `loopblox/benchmarks/tau2.py` and `ResearchSession`; the specialist/mixed-domain caller is archived outside the active package. [experiment.md](experiment.md) owns the current continuous protocol and its launch readiness. TextWorld is retired; README owns benchmark direction and scoring limitations. SpreadsheetBench 2 and Terminal-Bench are not integrated. The obsolete SWE-bench placeholder adapter and entry point have been removed.

Start subsequent work with a complete experiment around one explicit behavioral variable: define responsibility, scope, and invariants; choose existing components or propose a necessary one; then implement, record, and evaluate. These definitions do not require a speculative nesting engine, registry, policy framework, or graph language.
