# Initial behavior decomposition of four harnesses

Source analysis uses snapshots pinned on September 6, 2026; the LoopBlox implementation comparison was updated September 12, 2026. This document applies the v0 definitions in [loop.md](loop.md) without adding an ontology, component API, or executable graph. It checks whether those definitions describe native behavior and identifies concrete gaps in the component library.

This is source and official-documentation analysis. None of the four native harnesses was executed or modified, and no optimization result was established. Diagram labels describe behavior rather than approved LoopBlox components. Proposed experiment positions do not grant the researcher edit permissions.

Keep this document as design evidence from pinned versions. References to "this analysis" concern that source review, not the current experiment plan. [README.md](README.md) owns the current environment and next milestone; [experiment guidelines](docs/random-search.md) define the BFS/DFS protocol.

## 1. Evidence and analysis scope

| Harness | Evidence | Coverage boundary |
| --- | --- | --- |
| Pi | Local official-source snapshot `b8b873b9872db04a938fb4357b5e8e824ddc051c` | The `coding-agent` session layer and `agent` core loop; configuration and extensions can change behavior. |
| DeepSeek Harness / DSH | Local official-source snapshot `4e84901e6471b79ec0338099867ebb4606d12bb5` | Default `ReactLoopAgent`, inbox, and tool runtime; excludes arbitrary plugin combinations or replacement loops. |
| Codex | Local official-source snapshot `27bf160f7909704fb7e23d508f31900d90479699` | Ordinary user-turn control, model streaming, and tool runtime; feature branches were not exhaustively reviewed. |
| Claude Code | Official overview, Agent SDK loop, and hooks documentation consulted September 6, 2026 | Public contracts only. No pinned official implementation SHA; internal functions, locks, and complete call order are not inferred. |

The first three local checkouts had matching HEADs and clean worktrees at the time of analysis. See [source provenance](docs/sources.md). Older unofficial recovered Claude Code source is not evidence of current behavior.

Coverage includes primary-input acceptance, context preparation, model/tool iterations, tool scheduling and rejection, continuation/stopping, additional input, and documented compaction/recovery entry points. Subagents, cross-turn learning, complete MCP coverage, full UI behavior, durable recovery, and platform isolation details remain outside this analysis until an experiment needs them.

The final comparison unit is a complete task run. An initial native validation should use **one primary input with no additional external input** to establish a comparable boundary without changing native message rules. Steering/follow-up studies should separately freeze additional-input scripts and attribution rules.

## 2. Pi: the session may continue after the core loop ends

Ordinary input enters `AgentSession.prompt()`. The session handles input and extensions, then calls `_runAgentPrompt()`. That method awaits `agent.prompt()` and may invoke `agent.continue()` for error recovery, compaction, or newly queued messages. A core `agent_end` therefore does not necessarily end the complete task run. [Input/session entry][P1], [continuation and finalization][P2].

```text
Primary input -> session preparation -> core agent loop
                                        ├─ Prepare next context and accept steering
                                        ├─ Model response
                                        │  ├─ error / aborted -> core ends
                                        │  └─ Tool requests -> tool group -> results enter history
                                        ├─ shouldStopAfterTurn / tool continuation signals / steering
                                        └─ Check follow-up before stopping; continue if present
              -> Session checks recovery, compaction, and new queued input
                 ├─ More work -> re-enter core agent loop
                 └─ Finalize and return control
```

| Behavior | Scope × surface | Trigger, input, and return | Owner and evidence |
| --- | --- | --- | --- |
| Accept primary input or queue additional input | turn / session × Interaction | Enter prompt when idle; while running, `streamingBehavior` must choose steer or followUp. Returning from enqueue does not end the active task. | `AgentSession.prompt`, [P1] |
| Prepare model-visible context | iteration × State / Context | The next iteration may refresh context, tools, and settings. Apply `transformContext` before converting to model messages. | Session `prepareNextTurnWithContext` integration and core `streamAssistantResponse`, [P3], [P4] |
| Request and record model output | request × Model Execution | Stream an assistant message from context, tools, and model settings, with separate error and interruption paths. | `streamAssistantResponse` and `runLoop`, [P4], [P5] |
| Schedule a tool group | action group × Action Runtime | Execute on tool requests. If any tool or configuration requires sequential execution, the whole group is serial. Otherwise prepare calls in sequence, execute concurrently, and expose results in model order. | `executeToolCalls` and its two group implementations, [P6] |
| Intercept execution and process results | action × Action Runtime | Resolve tools, process/validate arguments, and invoke `beforeToolCall`. Blocked actions produce error results. `afterToolCall` may override exposed result fields. | `prepareToolCall`, `finalizeExecutedToolCall`, [P7], [P8] |
| Continue or end the core loop | iteration / turn × Turn Control | When every completed tool result has `terminate=true`, tool requests alone no longer require continuation. Stop callbacks, steering, and follow-up still participate. | `runLoop`, `shouldTerminateToolBatch`, [P5], [P9] |
| Recover after core termination and finalize | turn × Turn Control; Context owns state updates | `_handlePostAgentRun` checks recoverable errors, compaction, and new queues; it may re-enter the core loop before emitting settled. | `AgentSession`, [P2] |

The serial group **does not stop remaining actions on an ordinary tool error**; the early break checks abort. This differs from LoopBlox's current serial, stop-on-first-failure rule. [P6]

Pi's `turn_start/turn_end` core events surround an internal response and tool cycle, not the complete user Loop defined here. Session finalization belongs to outer composition; tool preflight, execution, and result ordering belong to internal behavior. They can be separate experiment positions. An experiment cannot fix the whole session component while also modifying a policy encapsulated inside it.

## 3. DSH: message routing and plugin rules affect continuation

This analysis covers the default `ReactLoopAgent`. `followup` targets `next-turn`, while `steer` targets `next-step`. A wakeup triggers the driver's `kick()`, which may call `turn()` several times. `whenIdle()` is a driver-quiescence boundary and is not unconditionally one primary input's complete task run. [D1]

```text
Queue primary input and wake driver
└─ One native turn
   ├─ Claim inbox -> assemble system context -> agent/pre-step
   │  └─ reject -> end as blocked
   ├─ step: build request -> consume model stream
   │  ├─ request-error asks for retry -> another request within step
   │  ├─ Tool requests -> scheduling -> results and additional context
   │  └─ No tools / tool concludesTurn -> propose turn finalization
   ├─ next-step messages present -> another step
   └─ Before stopping: agent/turn-stopping, then recheck next-step
      -> turn/end
Driver continues if next-turn work remains; otherwise idle
```

| Behavior | Scope × surface | Trigger, input, and return | Owner and evidence |
| --- | --- | --- | --- |
| Route input and wake execution | session / turn × Interaction | `followup`, `steer`, and `inject` determine the target queue and whether to wake the driver. Wakeup input after cancellation goes to a later turn. | `ReactLoopAgent.send` and driver, [D1] |
| Prepare a step | iteration × State / Context, Turn Control | Claim queued input, assemble prompt sections and runtime context, then apply `agent/pre-step` rules returning enter or reject. | `preStep`; plugins own their rules, [D2] |
| Model request and error recovery | request / step × Model Execution | Build requests, consume streams, and record messages within `step`. Structured failures can let `agent/request-error` request another attempt. This does not begin a new user Loop. | `step` and request-error integration rules, [D3] |
| Authorize and prepare tools | action × Action Runtime | `tools/pre-execute` returns allow / deny / ask. Ask uses the approval service; allow is still followed by a guard check. Rejection returns an error without executing the tool body. | `ToolRuntime.prepareExecution`, [D4] |
| Schedule tool groups and commit results | action group × Action Runtime | Exclusive calls form barriers; parallel calls enter a bounded rolling pool. Recheck mode before starting and commit results/additional context in model order. | `executeToolCalls` / `runGroup`, [D5] |
| Propose stopping and accept new input | turn × Turn Control | No tools, `concludesTurn`, and similar signals supply end reasons. Check `nextStep`, run `agent/turn-stopping`, then recheck before ending. Tools signal; plugins may inject continuation input. | `turn`, [D2], [D3] |
| Cancel and settle effects | action group / turn × Action Runtime, Lifecycle | Stop scheduling new work, await started calls, and give unstarted actions cancellation results. Internal scheduler faults follow a separate path rather than fabricating normal results. | Tool scheduler and turn exception finalization, [D5], [D2] |

DSH tool results can carry `additionalContexts` and `concludesTurn` alongside visible content. These affect the next input and stopping decision. Flattening the result into a string would lose native behavior. `step()` also contains request retries, so one source-level step does not guarantee one physical model request.

With one primary input and no additional queued input, one native turn can map to a complete task run. Multi-input experiments must record which turn claimed each message and which message was primary, rather than merging all work until driver idle. This analysis did not review every context-compaction plugin. The `pre-step` integration point does not prove any particular compaction policy is enabled by default.

## 4. Codex: model streaming and tool execution can overlap

`run_turn()` owns core control for one user turn. It performs required context preparation, repeatedly runs sampling requests, and checks follow-up work, pending input, the context window, and stop rules. The official App Server's `turn/steer` also adds input to the active turn without creating another turn. [C1], [App Server input boundary](https://learn.chatgpt.com/docs/app-server#steer-an-active-turn).

```text
Primary input -> required compaction, context, and input preparation
              -> capture this request's context and tool snapshot
              -> model stream: dispatch tools as complete output items arrive
                               └─ Tool execution may overlap later stream reception
              -> finalize request and collect started tool results
              -> check model follow-up work and pending input
                 ├─ Continue with a window transition -> compact -> continue
                 ├─ Continue -> next request
                 └─ No follow-up work -> Stop hooks
                    ├─ block with continuation content -> inject and continue
                    └─ Accept stop -> return
```

| Behavior | Scope × surface | Trigger, input, and return | Owner and evidence |
| --- | --- | --- | --- |
| Prepare primary input and accept additional input | turn / iteration × Interaction, Turn Control | Initial input enters the request. Later request boundaries take pending input according to policy. Some model/tool continuations after compaction precede steering. | `run_turn` input-acceptance rules, [C1], [C2] |
| Capture request state and context | request × State / Context | Capture step context so model-visible tools and actual routing use the same view; build input from history. | `run_turn` / step context, [C2] |
| Model streaming and retries | request × Model Execution | Receive output items and handle failures. Stream retry rules govern eligible faults; later attempts may rebuild input from current history. | `run_sampling_request`, [C3] |
| Dispatch tools and finalize streams | output item / action × Model Execution, Action Runtime | Hand complete output items to tools, retain in-flight futures, and drain after the stream ends. Model-response and tool-execution intervals can overlap. | `try_run_sampling_request`, output-item handling, `ToolCallRuntime`, [C4], [C9], [C5] |
| Concurrency and mutual exclusion | action group × Action Runtime | The router determines parallel support. Parallel-capable tools take a shared lock; others take an exclusive lock. | `ToolCallRuntime.handle_tool_call_with_source`, [C5] |
| Authorize and isolate actions | action × Action Runtime | Tools using this path apply approval requirements, environment permissions, and isolation settings. Refusal, attempts, and recovery have distinct rules. This is not necessarily the sole entry point for all tools. | `ToolOrchestrator`, plus registry before/after hooks, [C6], [C7] |
| Compact, continue, and stop | turn / iteration × Turn Control, State / Context | `needs_follow_up` combines model results and pending input. Window conditions trigger compaction. Stop hooks run when no follow-up remains; a block requires injectable content to continue. | `run_turn`, [C8] |

`run_sampling_request` includes model streaming and tool processing. Replacing it with strictly serial `Decide -> Execute` loses timing and scheduling semantics. Visualization should allow expanded behaviors to overlap without introducing another Harness surface. [C3], [C4], [C5]

Native stream retries also differ from LoopBlox's fixed one-retry contract requiring no effects and an identical request. Native studies must preserve and record native behavior. Stream interruption, deduplication, and reconnection across all feature conditions were not validated here, so this analysis does not establish complete failure-recovery fidelity.

## 5. Claude Code: public contracts with unknown internal scheduling

The official overview describes investigation, action, and verification as activities that can mix and repeat; it does not support forcing them into three independent components. Agent SDK documentation describes input, model responses, tool feedback, and final results. This section maps those public contracts without filling gaps from recovered source. [Overview][A1], [SDK loop][A2].

```text
Primary input and session context -> model response
                                     ├─ Tool request -> pre-execution hook and permissions
                                     │                 -> execution or refusal feedback -> continue
                                     └─ Completion without tools -> stop rules -> final result
Configured Stop hooks may require continuation; compaction and cancellation use their events.
This diagram does not specify group concurrency, locks, or stream/execution overlap.
```

| Behavior | Scope × surface | Public contract and trigger | Evidence and unknowns |
| --- | --- | --- | --- |
| Input and task activities | turn × Interaction, Turn Control | Accept prompt and session data. The model organizes investigation, editing, and verification for the task and may receive user guidance. | [A1]; activities do not imply fixed stages. |
| Model/tool feedback | iteration × Model Execution, Action Runtime | Responses may contain text, tools, or both. Tool results inform later decisions. Final `ResultMessage` differs from intermediate assistant messages. | [A2]; internal function boundaries are unknown. |
| Pre-execution hooks and permissions | action × Action Runtime | `PreToolUse` can block an action and give a refusal reason. A hook's lack of objection does not bypass later permission checks. | [A3]; configuration and permission systems own their rules. |
| Context compaction | context window × State / Context | Compact old history near the context limit and expose a `compact_boundary` event. | [A2]; no assumption of equivalence to LoopBlox's summary algorithm. |
| Stopping and continuation | turn boundary × Turn Control | A configured Stop hook may prevent stopping. It is not a default independent model Review stage. | [A3]; the specific hook must be frozen separately. |

The proposed boundary for validation is a single-primary-input SDK request through its final result. `ResultMessage` marks result delivery, but a few system events may follow; SDK consumers should finish reading the stream. The SDK also calls internal feedback cycles turns, so `num_turns` cannot directly count LoopBlox task runs. Full input-queue attribution for the interactive CLI and streaming input needs separate validation. [A2]

Public documentation alone does not establish complete group scheduling, stream retry behavior, effect deduplication, or every cancellation race. These remain evidence gaps. Substituting Pi or Codex internals would not resolve them, and they do not justify additional ontology levels.

## 6. Checking the v0 definitions and component library

The analyzed behavior did not reveal a counterexample requiring another surface or level. Responsibility, scope, integration point, owner, and component contract can describe the inspected behavior. The assumptions used to map native control flow into blocks need care.

| Native behavior | Description under v0 | LoopBlox implementation gap |
| --- | --- | --- |
| Pi sessions can recover and continue after core termination | Callers have different return boundaries; the complete run ends at the agreed outer boundary. | Examples directly compose components, review completion decisions, and continue. They add no work-component boundary; Pi session recovery and native event mapping remain absent. |
| DSH drivers process multiple turns; Pi and Claude SDK use turn for internal cycles | Record actual input-acceptance and return contracts instead of inferring scope from source names. | Fresh worker per task; additional-input and native-event mapping are unimplemented. |
| Tool results affect stopping or inject context | Output contracts distinguish visible content, effects, and caller control signals; the parent makes the final transition. | Execution has no equivalent native signal contract; `kind=completion_proposed` alone cannot represent it. |
| Pi group policy, DSH rolling pools, and Codex shared/exclusive locks | Different Action Runtime scheduling policies; freeze compatibility conditions before comparison. | Serial, stop-on-first-failure execution cannot reconstruct all three. |
| Codex tools overlap model streaming | Requests and actions have separate boundaries and dependencies and may overlap in time. | Decisions finish before separate tool execution, so native timing fidelity is unproven. |
| Compaction, stop hooks, and retries occur at different integration points | Locate each policy by trigger and caller rather than assigning all policies to one layer. | Context and analysis components exist, without the corresponding native integration contracts. |
| Claude Code internals lack public confirmation | Map public contracts, label unknowns, and limit coverage/fidelity claims. | Static reconstruction cannot prove native equivalence; validation needs a pinned executable version. |

**The main gaps are in execution contracts: serial decisions/execution and simple tool results cannot preserve all of these native behaviors.** Diagrams can explain overall flow, but traces must retain dependencies, overlap, input attribution, and return boundaries. This analysis found no need to expand scope × surface or add a graph compiler or parallel state machine.

## 7. Early native-validation proposal, not implemented

One proposal from the analysis was to validate Pi's tool-group scheduling. Inspected source exposes serial/parallel choices and tool-compatibility constraints without assuming independent Planning or Review stages. This proposal was not implemented and is outside the current τ² BFS/DFS and domain-study workflow.

| Experiment item | Fixed or exposed behavior |
| --- | --- |
| Final evaluation unit | A complete task run from one primary input through agreed session finalization. |
| Exposed boundary | Approved scheduling options for one tool group. Session composition, model decisions, context, preflight, and result presentation remain fixed. |
| Allowed changes | Native sequential execution or native parallel execution subject to tool compatibility. Tool implementations and authorization rules stay fixed. |
| Initial validation | Start/end order, refusals, failures, and return boundaries for the same selected action group under both settings. Retain native forced serial execution when a tool requires it. |
| Complete-task metrics | Outcomes, total model/tool usage, wall-clock time, failures, and interruptions. Evaluate scheduling first for latency; quality gains require separate evidence. |
| Excluded changes | Parent workflow, models/prompts, tool capabilities, hidden scoring, hard budgets, and arbitrary library-internal edits. |

After native behavior validation, decide whether to incorporate the scheduling contract into the approved catalog or first evaluate frozen native configurations. DSH result-context/stop signals and Codex stop integration/stream timing could be separate later studies; do not change all these axes in the first experiment. Models, budgets, and statistical protocols require separate decisions.

## Source references

The GitHub links below are pinned to the local commits verified during analysis. Line numbers locate behavior owned by the native source. This document owns only decomposition and coverage judgments.

[P1]: https://github.com/earendil-works/pi/blob/b8b873b9872db04a938fb4357b5e8e824ddc051c/packages/coding-agent/src/core/agent-session.ts#L1160
[P2]: https://github.com/earendil-works/pi/blob/b8b873b9872db04a938fb4357b5e8e824ddc051c/packages/coding-agent/src/core/agent-session.ts#L1106
[P3]: https://github.com/earendil-works/pi/blob/b8b873b9872db04a938fb4357b5e8e824ddc051c/packages/coding-agent/src/core/agent-session.ts#L562
[P4]: https://github.com/earendil-works/pi/blob/b8b873b9872db04a938fb4357b5e8e824ddc051c/packages/agent/src/agent-loop.ts#L279
[P5]: https://github.com/earendil-works/pi/blob/b8b873b9872db04a938fb4357b5e8e824ddc051c/packages/agent/src/agent-loop.ts#L156
[P6]: https://github.com/earendil-works/pi/blob/b8b873b9872db04a938fb4357b5e8e824ddc051c/packages/agent/src/agent-loop.ts#L409
[P7]: https://github.com/earendil-works/pi/blob/b8b873b9872db04a938fb4357b5e8e824ddc051c/packages/agent/src/agent-loop.ts#L607
[P8]: https://github.com/earendil-works/pi/blob/b8b873b9872db04a938fb4357b5e8e824ddc051c/packages/agent/src/agent-loop.ts#L720
[P9]: https://github.com/earendil-works/pi/blob/b8b873b9872db04a938fb4357b5e8e824ddc051c/packages/agent/src/agent-loop.ts#L589
[D1]: https://github.com/deepseek-ai/deepseek-harness/blob/4e84901e6471b79ec0338099867ebb4606d12bb5/packages/core/agent-loop/src/agent.ts#L122
[D2]: https://github.com/deepseek-ai/deepseek-harness/blob/4e84901e6471b79ec0338099867ebb4606d12bb5/packages/core/agent-loop/src/agent.ts#L234
[D3]: https://github.com/deepseek-ai/deepseek-harness/blob/4e84901e6471b79ec0338099867ebb4606d12bb5/packages/core/agent-loop/src/agent.ts#L341
[D4]: https://github.com/deepseek-ai/deepseek-harness/blob/4e84901e6471b79ec0338099867ebb4606d12bb5/packages/core/tools/src/index.ts#L1454
[D5]: https://github.com/deepseek-ai/deepseek-harness/blob/4e84901e6471b79ec0338099867ebb4606d12bb5/packages/core/agent-loop/src/tool-calls.ts#L60
[C1]: https://github.com/openai/codex/blob/27bf160f7909704fb7e23d508f31900d90479699/codex-rs/core/src/session/turn.rs#L155
[C2]: https://github.com/openai/codex/blob/27bf160f7909704fb7e23d508f31900d90479699/codex-rs/core/src/session/turn.rs#L304
[C3]: https://github.com/openai/codex/blob/27bf160f7909704fb7e23d508f31900d90479699/codex-rs/core/src/session/turn.rs#L1382
[C4]: https://github.com/openai/codex/blob/27bf160f7909704fb7e23d508f31900d90479699/codex-rs/core/src/session/turn.rs#L2405
[C5]: https://github.com/openai/codex/blob/27bf160f7909704fb7e23d508f31900d90479699/codex-rs/core/src/tools/parallel.rs#L95
[C6]: https://github.com/openai/codex/blob/27bf160f7909704fb7e23d508f31900d90479699/codex-rs/core/src/tools/orchestrator.rs#L138
[C7]: https://github.com/openai/codex/blob/27bf160f7909704fb7e23d508f31900d90479699/codex-rs/core/src/tools/registry.rs#L568
[C8]: https://github.com/openai/codex/blob/27bf160f7909704fb7e23d508f31900d90479699/codex-rs/core/src/session/turn.rs#L405
[C9]: https://github.com/openai/codex/blob/27bf160f7909704fb7e23d508f31900d90479699/codex-rs/core/src/stream_events_utils.rs#L298
[A1]: https://code.claude.com/docs/en/how-claude-code-works
[A2]: https://code.claude.com/docs/en/agent-sdk/agent-loop
[A3]: https://code.claude.com/docs/en/hooks-guide
