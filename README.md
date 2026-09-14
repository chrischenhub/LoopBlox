# LoopBlox

把 agent harness 的行为拆成有明确契约的组件，在可验证任务中组合、比较，并让研究 agent 自动搜索更有效的 Loop。

Loop 用普通 Python 定义。研究器可以调整组件的顺序、重复、分支和开放选项；宿主固定模型接口、工具、组件实现、预算、隔离与评分。完整任务运行是评价单位，所有候选、调用、失败和成本都有记录。

**当前处于研究原型阶段。** 已接入 τ²-bench retail / telecom 与 TextWorld，完成一轮随机起点筛选和部分深度优先搜索。现有运行用于流程验证，尚未建立 holdout 优化收益。最近一轮结果见 [BFS＋DFS 实验摘要](docs/experiments/bfs-dfs-20260914/README.md)。

## 快速开始

核心宿主只使用 Python 标准库，无需为核心模块额外安装依赖。使用 Python 3.12；以下命令从仓库根目录执行。

```sh
# 查看组件契约和现有命令，不请求模型
python3 -B components.py --markdown
python3 -B run_tau2.py --help
python3 -B run_random_search.py --help
```

τ² 的依赖装在其独立环境中，TextWorld 解释器装在 Docker 镜像中，具体步骤见下方运行说明。

要运行真实任务，还需要可用的 Docker Engine，以及支持当前结构化 Chat Completions 请求的模型服务：

```sh
cp .env.example .env
# 编辑 .env，填写自己的 FREEINFERENCE_API_KEY 和模型配置
```

环境变量及默认值见 [.env.example](.env.example)。变量名称沿用当前网关；更换服务地址时需要确认其结构化响应兼容性。compare、study 和 research 会消耗模型额度，包括 τ² 模拟用户的调用；每次实验前固定模型和预算。

- [运行 τ² / TextWorld](docs/running.md)：固定上游版本，准备任务，执行固定比较和领域研究。
- [随机起点与 DFS](docs/random-search.md)：开发集准备、10 个起点筛选、Top 3 研究和恢复。
- [编写 Loop](CONTROLLER.md)：组件引用、调用与外层 `run(env)` 的返回。
- [网站构建](site/README.md)：英文介绍页与本地预览。

## 一个 Loop

统一 baseline 是 [controllers/reactive.py](controllers/reactive.py)：

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

基线直接组合完整上下文、模型决策、执行与完整观察，通常每轮一个模型请求。模型提出完成后，由外层 controller 返回；组件返回本身不会结束任务。权威评分发生在 worker 关闭后。

当前组件按 Context / Evidence、Propose、Assess、Act 四类组织，共 14 个子组件。类别用于导航，具体契约和开放选项由 [components.py](components.py) 定义，[COMPONENTS.md](COMPONENTS.md) 从同一来源生成。Python 是唯一可执行的 Loop 定义，网站中的图仅用于解释。

| 示例 | 行为 |
| --- | --- |
| [reactive.py](controllers/reactive.py) | 统一基线，full context + full observation。 |
| [brief_work.py](controllers/brief_work.py) | 将基线的观察改为 brief。 |
| [plan_then_work.py](controllers/plan_then_work.py) | 在基线前加一次 Plan。 |
| [planned_work.py](controllers/planned_work.py) | 先规划，对完成提案进行复核。 |
| [reviewed_plan.py](controllers/reviewed_plan.py) | 每批动作前生成和审查计划。 |
| [failure_reflection.py](controllers/failure_reflection.py) | 工具失败后反思。 |
| [stagnation_reflection.py](controllers/stagnation_reflection.py) | 工具失败或连续相同动作与结果时反思。 |

研究器自己的固定 Loop 位于 [controllers/research.py](controllers/research.py)。重复结果只是反思的启发式，不能单独证明没有进展或某个改动有效。

## 实验如何进行

1. 冻结问题、组件边界、模型、环境、任务划分、种子、基线源码和预算。
2. 先运行统一 baseline；研究器保存不可变候选，在 development 上评估、读取公开轨迹并选择。
3. 每次比较先冻结所有候选，再有放回抽取完整共享任务批次；每个候选执行整批，按抽样位置配对并轮换顺序。
4. 关闭研究器、冻结最终选择后，才运行独立 holdout；最终反馈不返回研究器。

这里的 training 是**搜索 Python Loop 的组合**，不更新神经网络权重。完整批次先跑完再判断；重复抽到同一题不增加独立任务组。训练专用 pilot 明确不运行 holdout。

执行、研究器和模拟用户共享记录与预算。任务失败、额度耗尽、模型服务错误、宿主故障和评分故障保留各自状态；中断和未知用量不会从账本消失。恢复在新目录中启动新研究器，保留完成分支并扣除已有开销。实验定义见 [loop.md](loop.md)，完整规则见 [AGENTS.md](AGENTS.md)。

## 当前状态与下一个里程碑

2026-09-13～14 的 pilot 从 10 个随机 Loops、每个 5 次共享开发抽样开始，选择 loop06、loop08、loop04。三支完成首轮局部研究后，再进行明确记录父子关系的 DFS。DFS 中 loop06 和 loop08 已提交；loop04 被模型服务错误阻断。本轮没有 validation 或 holdout，完整数据与限制见 [实验摘要](docs/experiments/bfs-dfs-20260914/README.md)。

下一步正式实验要回答：**同样的模型与组件，针对一个领域搜索的 Loop，能否在未见任务上优于统一基线和混合领域搜索的 Loop？**

计划使用经过评分审核的 τ² retail / telecom 分组 subset，分别进行两个领域专用搜索和一个混合搜索。混合搜索获得两个专用搜索的预算之和。所有研究器关闭后，将基线、专用 Loop 和混合 Loop 放到相同 holdout 上比较，同时记录总成本与跨领域表现。模型、预算、独立重复和正式数据划分仍需冻结。

TextWorld 保留作机制检查。SpreadsheetBench 2 的建模／调试任务是后续方向，尚未集成；Terminal-Bench 也未集成。Pi、DeepSeek Harness、Codex 与 Claude Code 仅用于行为边界分析，来源见 [固定参考版本](docs/sources.md) 和 [harness 拆分](harness-decomposition.md)。目前没有原生 harness 优化结果。

## 代码与文档导航

| 入口 | 职责 |
| --- | --- |
| [components.py](components.py) | 子组件、参数、固定提示词与输入输出契约。 |
| [controller_runtime.py](controller_runtime.py) / [controller_worker.py](controller_worker.py) | 宿主执行、计量和隔离 worker。 |
| [loopblox.py](loopblox.py) / [runtime_io.py](runtime_io.py) | 模型网关、失败类型、原子记录与进程期限。 |
| [autoresearch.py](autoresearch.py) / [study.py](study.py) | 共用 ResearchSession、基线和最终比较。 |
| [random_loops.py](random_loops.py) / [run_random_search.py](run_random_search.py) / [dfs_research.py](dfs_research.py) | 随机候选、筛选和深度优先搜索。 |
| [run_inheritance.py](run_inheritance.py) | 多轮继承研究，以及搜索共用的进程与快照函数。 |
| [run_tau2.py](run_tau2.py) / [tau2_benchmark.py](tau2_benchmark.py) | τ² CLI、审核、官方环境和模拟用户桥接。 |
| [run_textworld.py](run_textworld.py) / [textworld_benchmark.py](textworld_benchmark.py) | TextWorld CLI 与任务准备；解释器在 [environments/textworld](environments/textworld/)。 |
| [trace_report.py](trace_report.py) | 从已有轨迹生成可展开的 HTML 报告。 |
| [experiments/](experiments/) | 开放组件边界与研究问题。 |
| [docs/limitations.md](docs/limitations.md) | 未决设计和证据限制。 |

更新组件后重新生成 `COMPONENTS.md`；更新网站输入后刷新快照：

```sh
python3 -B components.py --markdown > COMPONENTS.md
python3 -B site/build.py --refresh-notes
```

原始实验、冻结环境和恢复链存放在被 Git 忽略的 `.artifacts/`；公开摘要位于 `docs/experiments/`。新 clone 需要重新准备任务环境，源码仓库不携带原始任务轨迹、模型凭据或本机部署身份。历史数据暴露不会因清理文件而重置。MIT 许可证见 [LICENSE](LICENSE)，第三方来源及字体许可证见 [docs/sources.md](docs/sources.md)。
