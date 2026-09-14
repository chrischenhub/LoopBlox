# 四个 Harness 的首轮行为拆分

源码分析基于 2026-09-06 的固定快照；LoopBlox 实现对照更新于 2026-09-12。本文应用 [loop.md](loop.md) 的 v0 定义，不新增 ontology、组件 API 或可执行图。目标是检验这些定义能否描述真实行为，并找出 LoopBlox 组件库的具体缺口。

这是源码与官方文档分析，没有运行四个原生 harness、修改其实现或取得优化结果。图中名称描述行为，不代表 LoopBlox 已批准的组件。下文的候选实验位置也不自动成为 researcher 的可修改权限。

## 1. 证据与本轮范围

| Harness | 本轮证据 | 可信边界 |
| --- | --- | --- |
| Pi | 官方仓库本地快照 `b8b873b9872db04a938fb4357b5e8e824ddc051c` | `coding-agent` 会话层与 `agent` 核心循环；配置与扩展会影响实际行为。 |
| DeepSeek Harness / DSH | 官方仓库本地快照 `4e84901e6471b79ec0338099867ebb4606d12bb5` | 默认 `ReactLoopAgent`、inbox 与工具运行时；不代表任意插件组合或替代 loop。 |
| Codex | 官方仓库本地快照 `27bf160f7909704fb7e23d508f31900d90479699` | 普通用户 turn 的核心、模型流与工具运行时；未穷举 feature 分支。 |
| Claude Code | 2026-09-06 查阅的官方工作原理、Agent SDK loop 与 hooks 文档 | 公开行为契约；没有可固定的官方实现 SHA，不推断内部函数、锁或完整调用顺序。 |

分析时核对了前三个本地仓库的 HEAD 与上述版本一致，工作区无修改。来源与获取方式见 [源码基线记录](docs/sources.md)。Claude Code 的旧非官方恢复源码不用于确认当前行为。

本轮覆盖：主输入接纳、上下文准备、模型与工具迭代、工具调度与拒绝、继续/停止、追加输入以及有证据的压缩/恢复入口。子 agent、跨轮次学习、所有 MCP 协议、完整 UI、持久化恢复和平台级隔离细节留待对应实验需要时继续拆分。

比较的最终单位是完整 task run。为了先得到可比较边界，第一版原生验证应使用**一个主输入、无外部追加输入的任务**；这不改变 harness 的消息规则。研究 steering/follow-up 时，再固定追加输入脚本与归属规则。

## 2. Pi：核心循环结束后，会话层仍可能继续

普通输入从 `AgentSession.prompt()` 进入。会话层处理输入与扩展，调用 `_runAgentPrompt()`；后者等待 `agent.prompt()`，再根据错误恢复、压缩或新排队消息决定是否 `agent.continue()`。因此一次核心 `agent_end` 不能直接当作完整 task run 的返回边界。[输入与会话入口][P1]、[继续与收尾][P2]

```text
主输入 → 会话准备 → agent 核心循环
                    ├─ 准备下一轮上下文、接纳 steering
                    ├─ 模型响应
                    │  ├─ error / aborted → 核心结束
                    │  └─ 工具请求 → 工具组 → 结果进入历史
                    ├─ shouldStopAfterTurn / 工具继续信号 / steering
                    └─ 将停止时检查 follow-up；有则继续
                  → 会话层检查恢复、压缩和新队列
                    ├─ 需要继续 → 再进 agent 核心循环
                    └─ 收尾并交还控制权
```

| 行为 | scope × surface | 触发、输入与返回 | 实现所有者与证据 |
| --- | --- | --- | --- |
| 接纳主输入或排队追加输入 | turn / session × Interaction | 空闲时进入 prompt；运行中必须按 `streamingBehavior` 选择 steer 或 followUp。入队调用返回不代表正在执行的任务结束。 | `AgentSession.prompt`，[P1] |
| 准备模型可见上下文 | iteration × State / Context | 下一轮可刷新上下文、工具与设置；请求前执行 `transformContext`，再转成模型消息。 | 会话层的 `prepareNextTurnWithContext` 接入与核心的 `streamAssistantResponse`，[P3]、[P4] |
| 模型请求与记录 | request × Model Execution | 给定上下文、工具和模型配置，流式生成 assistant message；错误和中断有独立返回路径。 | `streamAssistantResponse` 与 `runLoop`，[P4]、[P5] |
| 工具组调度 | action group × Action Runtime | 有工具请求时执行。任一工具声明 sequential，或配置要求 sequential，整组走串行；否则先依次准备，再并发执行，并按模型顺序提供结果。 | `executeToolCalls` 及两种组执行实现，[P6] |
| 执行前拦截与结果处理 | action × Action Runtime | 查工具、处理与校验参数、调用 `beforeToolCall`；被 block 的动作产生错误结果。`afterToolCall` 可覆盖暴露的结果字段。 | `prepareToolCall`、`finalizeExecutedToolCall`，[P7]、[P8] |
| 决定继续或核心结束 | iteration / turn × Turn Control | 工具组的所有已完成结果都带 `terminate=true` 时，不再仅因工具请求继续；仍结合 stop callback、steering 与 follow-up 处理。 | `runLoop`、`shouldTerminateToolBatch`，[P5]、[P9] |
| 核心结束后的恢复与最终收尾 | turn × Turn Control；状态更新由 Context 行为负责 | `_handlePostAgentRun` 检查可恢复错误、压缩与新队列；必要时再次调用核心循环，最后发送 settled。 | `AgentSession`，[P2] |

这里的串行组**不会因普通工具错误自动停止余下动作**，循环中的提前 break 是 abort 检查。这与当前 LoopBlox 的“串行且首错停止”不同。[P6]

**返回边界与组件化含义：** Pi 核心事件里的 `turn_start/turn_end` 包围一次内部响应及工具处理，不是本文的完整用户 Loop。会话收尾规则属于外围组合，工具组的 preflight、执行与结果顺序则属于内部行为。两者可以分别成为实验位置；不能在同一实验中既固定整个会话处理组件，又悄悄改它封装的内部策略。

## 3. DSH：消息路由与插件规则参与继续判断

本轮分析默认 `ReactLoopAgent`。`followup` 进入 `next-turn`，`steer` 进入 `next-step`；driver 在被唤醒后执行 `kick()`，后者可以连续调用多次 `turn()`。因此 `whenIdle()` 是 driver 收敛边界，不能无条件等同于一个主输入对应的 task run。[D1]

```text
主输入入队并唤醒 driver
└─ 一个原生 turn
   ├─ claim 对应 inbox → 组装系统上下文 → agent/pre-step
   │  └─ reject → blocked 结束
   ├─ step：构造请求 → 接收模型流
   │  ├─ request-error 处理要求 retry → step 内再请求
   │  ├─ 工具请求 → 工具调度 → 结果与附加上下文
   │  └─ 无工具 / 工具 concludesTurn → 提出本 turn 收尾
   ├─ 若有 next-step 消息 → 下一 step
   └─ 将停止时执行 agent/turn-stopping，再检查 next-step
      → turn/end
driver 若还有 next-turn 工作可继续；否则 idle
```

| 行为 | scope × surface | 触发、输入与返回 | 实现所有者与证据 |
| --- | --- | --- | --- |
| 输入路由与唤醒 | session / turn × Interaction | `followup`、`steer`、`inject` 区分目标队列及是否唤醒；取消后的唤醒输入转到后续 turn。 | `ReactLoopAgent.send` 与 driver，[D1] |
| step 准备 | iteration × State / Context、Turn Control | claim 队列，组装 prompt sections 与运行时上下文，再由 `agent/pre-step` 接入规则返回 enter 或 reject。 | `preStep`；插件拥有各自规则，[D2] |
| 模型请求与错误恢复 | request / step × Model Execution | `step` 内建请求、消费流、记录消息；结构化失败可由 `agent/request-error` 要求再次请求。不能把这个重试当作新用户 Loop。 | `step` 与 request-error 接入规则，[D3] |
| 工具授权与准备 | action × Action Runtime | `tools/pre-execute` 返回 allow / deny / ask；ask 经 approval service，allow 后仍检查 guard。拒绝生成错误结果而不执行工具 body。 | `ToolRuntime.prepareExecution`，[D4] |
| 工具组调度与结果提交 | action group × Action Runtime | exclusive 调用形成屏障，parallel 调用进入有上限的滚动池；启动前重新判断模式，结果与附加上下文按模型顺序提交。 | `executeToolCalls` / `runGroup`，[D5] |
| 停止建议与再接纳输入 | turn × Turn Control | 无工具、`concludesTurn` 等产生结束原因；检查 `nextStep`，运行 `agent/turn-stopping` 后再次检查，才决定结束。 | `turn`；工具只提供信号，插件可注入继续信息，[D2]、[D3] |
| 取消与效果收敛 | action group / turn × Action Runtime、Lifecycle | 中止补充新调度，等待已启动调用收敛；未启动动作使用取消结果。调度器内部故障走独立路径，不伪造正常结果。 | 工具调度器与 turn 的异常收尾，[D5]、[D2] |

**返回边界与组件化含义：** DSH 的工具结果除了可见内容，还能带 `additionalContexts` 与 `concludesTurn`。它们分别影响下一步输入和停止判断；不能把整份工具结果压成一个字符串后仍声称保留原生行为。`step()` 本身也有请求重试循环，所以源码中的一个 step 不保证一次物理模型请求。

单主输入、无追加队列时，可以将一个原生 turn 映射到完整 task run。多输入实验必须记录每条输入被哪个 turn claim、哪个是主输入，不能把 driver 一直到 idle 的所有工作盲目合并。本轮没有审查全部上下文压缩插件；`pre-step` 接入点不等于已经证明某种压缩策略默认启用。

## 4. Codex：模型流、工具执行与轮内控制并非严格串行阶段

`run_turn()` 负责一个用户 turn 的核心控制：先处理必要的上下文准备，再反复执行 sampling request，检查后续工作、追加输入、上下文窗口和停止规则。官方 App Server 的 `turn/steer` 也明确把输入加入当前活跃 turn，而不创建新 turn。[C1]、[App Server 输入边界](https://learn.chatgpt.com/docs/app-server#steer-an-active-turn)

```text
主输入 → 必要的压缩、上下文与输入准备
       → 构建本请求的上下文与工具快照
       → 模型流：完整输出项到达时可派发工具
                    └─ 工具执行可与后续流接收重叠
       → 本请求收尾并收集已启动工具结果
       → 判断是否有模型后续工作或追加输入
          ├─ 需要继续且触发窗口切换 → 压缩 → 继续
          ├─ 需要继续 → 下一请求
          └─ 无后续工作 → Stop hooks
             ├─ block 且有继续内容 → 注入内容并继续
             └─ 接受停止 → 返回
```

| 行为 | scope × surface | 触发、输入与返回 | 实现所有者与证据 |
| --- | --- | --- | --- |
| 主输入准备与追加输入接纳 | turn / iteration × Interaction、Turn Control | 初始输入先进入请求；后续请求边界才按规则取 pending input。压缩后某些模型/工具续接会先于 steering。 | `run_turn` 的输入接纳规则，[C1]、[C2] |
| 请求快照与上下文视图 | request × State / Context | 捕获 step context，保持模型可见工具与实际路由使用一致视图；从历史构建本次输入。 | `run_turn` / step context，[C2] |
| 模型流与请求重试 | request × Model Execution | 接收输出项、处理失败；可重试错误由 stream retry 规则处理，后续尝试可从当前历史重新构建输入。 | `run_sampling_request`，[C3] |
| 工具派发与流收尾 | output item / action × Model Execution、Action Runtime | 完整输出项到达后交给工具处理，保存 in-flight future；流结束后 drain。模型响应与工具的墙钟时间不必是两个互不重叠区间。 | `try_run_sampling_request`、输出项处理与 `ToolCallRuntime`，[C4]、[C9]、[C5] |
| 并发与互斥 | action group × Action Runtime | 路由器判断工具是否支持并发；可并发者取共享锁，其他取独占锁。 | `ToolCallRuntime.handle_tool_call_with_source`，[C5] |
| 动作授权与隔离 | action × Action Runtime | 使用该路径的工具运行时依据审批要求、环境权限与隔离配置处理动作；拒绝、尝试和恢复有各自规则。不能将这一实现推广为所有工具唯一入口。 | `ToolOrchestrator`；另有 registry 前后 hooks，[C6]、[C7] |
| 压缩、继续与结束 | turn / iteration × Turn Control、State / Context | `needs_follow_up` 综合模型结果与 pending input；窗口条件触发压缩。无后续工作时检查 Stop hooks，block 必须有可注入内容才能继续。 | `run_turn`，[C8] |

**返回边界与组件化含义：** `run_sampling_request` 包含模型流与工具处理，不是纯粹的“调用一次模型”。把它拆成完全串行的 `Decide → Execute` 会丢掉时间与调度语义。可视化应允许行为展开后出现重叠；这不需要新增 Harness surface。[C3]、[C4]、[C5]

原生 stream retry 也不能直接套用 LoopBlox 当前“无效果、完全相同请求、仅一次”的固定重试契约。两者属于不同执行条件；原生研究应保留并记录原生行为。本轮未验证各 feature 下的流中断、去重与重连路径，不能据此声称完整复现了失败恢复。

## 5. Claude Code：公开行为映射，内部调度留空

官方工作原理将调查、行动与验证描述为会混合和重复的活动，不支持把它们强制画成三个独立组件。Agent SDK 文档公开了输入、模型响应、工具反馈与最终结果的流程；本节据此描述公开契约，不使用恢复源码补齐内部细节。[工作原理][A1]、[SDK loop][A2]

```text
主输入与会话上下文 → 模型响应
                     ├─ 工具请求 → 执行前 hook 与权限处理
                     │             → 执行或拒绝反馈 → 继续模型处理
                     └─ 无工具的完成响应 → 停止规则 → 最终结果
配置的 Stop hook 可要求继续；压缩与取消按相应事件参与处理。
此图未规定工具批次的并发策略、锁或模型流与执行的内部重叠。
```

| 行为 | scope × surface | 公开契约与触发位置 | 证据与未确定部分 |
| --- | --- | --- | --- |
| 输入与任务活动 | turn × Interaction、Turn Control | 接收 prompt 与会话信息；调查、修改、验证由模型按任务组织，可接受用户引导。 | [A1]；不将过程活动升级为固定阶段。 |
| 模型/工具反馈 | iteration × Model Execution、Action Runtime | 响应可含文本、工具或两者；工具结果进入后续判断。最终 `ResultMessage` 与中间 assistant message 不同。 | [A2]；内部函数边界未确定。 |
| 执行前 hook 与权限 | action × Action Runtime | `PreToolUse` 可阻止动作并提供拒绝原因；hook 无异议不等于绕过后续权限处理。 | [A3]；规则由配置和权限系统拥有。 |
| 上下文压缩 | context window × State / Context | 上下文接近限制时压缩旧历史，并暴露 `compact_boundary` 事件。 | [A2]；不假定其算法与 LoopBlox 的 summary 组件相同。 |
| 停止与继续 | turn boundary × Turn Control | 配置的 Stop hook 可阻止本次停止；它不是默认存在的独立模型 Review 阶段。 | [A3]；具体 hook 内容必须另行固定。 |

**返回边界与组件化含义：** 本轮以单主输入 SDK 请求到最终结果为待验证的实验边界。`ResultMessage` 标记结果交付，但其后仍可能有少量系统事件，SDK 消费侧应继续读完整个流。SDK 文档将内部反馈周期也称为 turn，不能直接拿 `num_turns` 充当 LoopBlox 的 task run 数量。交互 CLI 与 streaming input 的完整排队归属仍需单独验证。[A2]

目前无法仅凭这些公开说明确定工具组完整调度、流失败重试、效果去重和所有取消竞态。将这些单元标为未确定，比直接套用 Pi 或 Codex 的实现更准确；它们属于证据缺口，不是增加 ontology 层级的理由。

## 6. 对 v0 定义与当前组件库的检验

这轮尚未找到必须增加 surface 或层级的反例。现有的职责、范围、接入位置、所有者与组件契约能够描述已检查行为；需要纠正的是将原生控制流映射成积木时的假设。

| 遇到的真实行为 | v0 如何描述 | 当前 LoopBlox 的差距 |
| --- | --- | --- |
| 核心循环结束后，Pi 会话层仍可恢复并继续 | 不同调用者的返回边界；完整运行以最外层已约定边界结束。 | 已有直接组合子组件、定向复核完成决策和继续工作的 controller 示例；当前调用没有额外的工作组件边界，仍无 Pi 会话恢复组件或原生事件映射。 |
| DSH driver 连续处理多 turn；Pi 与 Claude SDK 的 turn 指向内部周期 | 记录实际输入接纳与返回契约，不用源码名称确定 scope。 | 当前每个任务新 worker；未实现追加输入与原生事件映射。 |
| 工具结果参与停止或注入上下文 | 输出契约区分可见内容、状态效果与给调用者的控制信号；父控制流作最终决定。 | 当前 Execution 未提供上述原生信号契约，不能只映射到 `kind=completion_proposed`。 |
| Pi 全组策略、DSH 滚动池、Codex 共享/独占锁 | Action Runtime 下不同调度规则；冻结工具兼容条件再做比较。 | 当前仅串行且首错停止，不足以重建三者。 |
| Codex 工具执行与模型流重叠 | request 与 action 各有边界和依赖，时间上可以重叠。 | 当前先完成决策组件，再独立执行工具；不能声称忠实覆盖原生时序。 |
| 压缩、停止 hook、重试分布在不同位置 | 策略属于具体行为；按触发条件和调用者定位，而非统一塞进一层。 | 已有上下文与分析组件，但没有对应的原生接入契约。 |
| Claude Code 内部实现未公开确认 | 映射公开契约，标记未知项；限制覆盖与保真声明。 | 无法据静态重建证明原生等价，后续需固定可执行版本做行为验证。 |

**首轮暴露的主要缺口在当前执行契约：串行的决策/执行与简单工具结果不足以保留上述原生行为。** 图形可以解释总体流程，但实际轨迹还需保持依赖、重叠、输入归属和不同返回边界。scope × surface 暂无需要扩展的证据；这里也无需引入图编译器或另一套状态机。

## 7. 据此收窄下一步实验

首个**原生 harness 验证**建议从 Pi 的工具组调度开始：已读源码给出了现成的串行/并行选择和明确的工具兼容约束。这个原生对照无需假定 Pi 有独立 Planning / Review 阶段。当前子组件组合、冻结实验目录和实际调用报告只验证 LoopBlox 基础设施，并未实现下述原生实验。

| 实验项 | 冻结或开放的内容 |
| --- | --- |
| 最终评价单位 | 一个主输入到约定会话收尾的完整 task run。 |
| Exposed boundary | 只开放一个工具组的批准调度选项；会话编排、模型决策、上下文、preflight 与结果呈现固定。 |
| 允许变化 | 选择原生 sequential 或在原生工具兼容规则下的 parallel；不改工具实现、不修改授权规则。 |
| 先验证的行为 | 同一已选动作组在两种配置下的启动/结束顺序、拒绝与失败结果、返回边界；含 sequential-only 工具时保留原生强制串行。 |
| 完整任务上的指标 | 任务结果、总模型与工具用量、墙钟时间、失败与中断记录；调度收益先按延迟评估，质量收益需另有证据。 |
| 暂不开放 | 父层 workflow、模型/提示词、工具能力、隐藏评分、硬预算，以及库内部自由改写。 |

完成原生行为验证后，再决定把该调度契约纳入 LoopBlox approved catalog，还是先通过固定原生配置作为实验对象。后续可分别研究 DSH 的结果上下文/停止信号、Codex 的停止接入规则与流时序；不在第一轮同时改变这些轴。模型、具体预算与统计方案继续单独讨论。

## 源码引用

以下 GitHub 链接固定到已核对的本地提交；行号用于定位，源码拥有原生行为定义。本文只拥有拆分与覆盖判断。

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
