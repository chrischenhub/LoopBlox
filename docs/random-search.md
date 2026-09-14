# 当前 BFS／DFS 实验 guideline

更新于 2026-09-14。**本页记录已落实到当前代码、尚未实际重跑的固定题号协议。** 2026-09-13～14 已跑的实验使用旧抽样规则，结果与协议偏差见[历史实验摘要](experiments/bfs-dfs-20260914/README.md)，不能当成本页协议的运行结果。

这是 development-only pilot：training 指搜索 Python Loop 的组合，不训练模型权重。本页集中维护当前实验设置与运行步骤；跨实验的工程和证据规则由 [AGENTS.md](../AGENTS.md) 维护，研究器调用接口见 [CONTROLLER.md](../CONTROLLER.md)。所有命令从仓库根目录执行，每次使用新的输出目录。

## 已确定的设置

| 项目 | 当前规则 |
| --- | --- |
| 任务子集 | BFS、Top 3 局部研究、DFS 使用同一组固定的 5 道 retail development 题，题号见下节。没有单独的 validation/test/holdout。 |
| BFS | 生成 10 个不同的随机 Loop；每个候选与 baseline 都跑同样的 5 题，再选 Top 3。随机的是 Loop 组合，题号不随机。 |
| Top 3 局部研究 | 当前入口仍保留这一阶段：三个起点各自进行自由局部研究、完成提交，再启动明确约束顺序的 DFS。 |
| DFS | 每支最多 6 个新节点，最大深度 3，每个节点最多 2 个孩子；父子比较完成后再深入，得分下降不自动剪枝。 |
| 每次改动的比较 | 父版本在 5 题上重新运行，子版本也跑同样的 5 题，合计 10 次完整任务运行；不复用父版本的旧分数代替本次运行。 |
| 重复与配对 | 每个候选每题运行一次，`repeats=1`；各轮题号和顺序不变，每次新建环境和 worker，按任务位置轮换候选执行顺序。 |
| 完成与选择 | 整批完成后判断表现；DFS 的探索顺序与最终选择分开。提交前的 baseline 比较仍使用同一组 5 题。 |
| 每题上限 | 300 秒、40 次 agent 动作、64 次模型调用、65,536 输出 token；模拟用户模型调用也计入预算。模型及研究总预算在新 campaign 的 `protocol.json` 中冻结。 |

一次“任务运行”指一个 Loop 处理一道题的完整过程，内部可能调用模型和工具多次。父 5 次＋子 5 次只覆盖 5 道不同题，不是 10 道题，也不是 10 次模型调用。历史分数和轨迹仍保留，供研究器诊断与解释；重跑能补充同任务波动的证据，但一次配对不能消除波动或证明因果。

默认任务运行额度如下；它们是上限，不是已发生的开销：

| 阶段 | 任务运行额度 |
| --- | ---: |
| BFS 筛选 | 56：1 次开场 baseline ＋（10 个候选＋baseline）× 5 题。 |
| Top 3 自由局部研究 | 每支 22：最多 2 次 baseline／起点开场 ＋ 20 次后续运行；三支共 66。 |
| DFS | 每支 72：最多 2 次开场 ＋ 6 条父子边 × 10 次 ＋ 10 次提交前比较；三支共 216。 |
| 全流程 | 最多 338 次任务尝试；时间、模型、输出额度或提前提交可能使实际次数更少。 |

缺分不能当失败或成功补齐，失败和中断照常计量；恢复扣除已发生的开销，不重置逻辑预算。这组 5 题用于初步筛选和搜索，每道题占单批成功率的 20%。Top 3 是继续探索的起点；反复在同一组题上选优，不能证明泛化提升。独立任务的最终验证尚未配置，不是本轮已有步骤；后续需要另行冻结数据，并保留已有任务暴露记录。

## 1. 准备开发专用 suite

先按照 [τ² 环境安装](running.md) 固定上游版本、安装其独立 Python 环境并准备 Docker；填写根目录 `.env`。

通用 `python -m loopblox.benchmarks.run_tau2 prepare` 会生成 development 与 holdout 两个划分。随机搜索入口要求 manifest 中只有 development，因此不能直接传入通用 suite。当前入口不提供单独选择开发子集的 CLI；运行者需先在宿主侧准备并冻结 development-only suite，记录它的来源、分组和选择规则，保留文件校验值，不能将 holdout 重新标记为 development。

以下命令中的 `.artifacts/tau2/development-001` 指这份已经准备好的 suite，新 clone 不包含它。本次保留的 BFS／DFS campaign 各有完整冻结 suite，可在本地用于后续开发实验。正式实验仍需另行冻结数据协议。

当前 BFS 和 DFS 固定使用以下 5 道开发题，按原 10 题池的题号升序取前 5 题，不依据成绩选题：

`retail-development-0000`、`retail-development-0002`、`retail-development-0004`、`retail-development-0006`、`retail-development-0007`。

题号唯一来源是 [`TASK_IDS`](../loopblox/experiments/search.py)，准备时写入 `protocol.json`，题数由列表长度派生；不再提供 `--batch`。suite 必须包含这些开发题，缺题直接报错。BFS、Top 3 局部研究、DFS 各分支、各轮比较和提交前比较都使用同一完整列表，每个候选每题运行一次，不随机抽题。单独的开场检查只使用列表第一题；它不用于提前淘汰候选。

## 2. 冻结 10 个随机起点并筛选 Top 3

```sh
.artifacts/upstream/tau2-bench/.venv/bin/python -B -m loopblox.experiments.search prepare \
  .artifacts/tau2/random-001 --suite .artifacts/tau2/development-001 \
  --seed 20260913 --count 10 --top 3 --deep-runs 20

PYTHONPATH=.artifacts/tau2/random-001/implementation \
.artifacts/upstream/tau2-bench/.venv/bin/python -P -B -m loopblox.experiments.search run \
  .artifacts/tau2/random-001
```

`prepare` 不请求模型，但会检查模型配置、Docker 和冻结依赖，保存候选及实现副本。`run` 才开始模型调用。`PYTHONPATH` 指向冻结的 implementation，`-P` 防止当前工作目录中的源码优先加载；命令仍从仓库根目录执行，以读取本地 `.env`。生成器从已开放组件中抽取上下文、决策、观察、规划、复核和反思等组合，生成不同的普通 Python 源码，不读取题目答案。

筛选需要 1 次开场 baseline，以及 11 个 controller × 5 道固定题，共预留 56 次题目运行。各 controller 使用完全相同的题号和题目顺序。完整评分的候选按通过数排序，平分时依次比较模型调用、输入／输出 token 和生成顺序；baseline 单独作为参考。缺分保留且不参与排名。

Top 3 各自启动新研究器，先跑 baseline 和起点的开场配对，再获得 `--deep-runs` 次开发运行额度。这里是自由局部研究，还没有强制 DFS 顺序。预算及模型设置以新 campaign 的 `protocol.json` 为准；不要编辑已冻结的协议来改变正在进行的实验。

## 3. 从三个已提交结果开始 DFS

只有起始分支全部完成提交，才能创建 DFS campaign：

```sh
.artifacts/upstream/tau2-bench/.venv/bin/python -B -m loopblox.experiments.search dfs \
  .artifacts/tau2/dfs-001 .artifacts/tau2/random-001 \
  --seed 20260914 --nodes 6 --depth 3

PYTHONPATH=.artifacts/tau2/dfs-001/implementation \
.artifacts/upstream/tau2-bench/.venv/bin/python -P -B -m loopblox.experiments.search run \
  .artifacts/tau2/dfs-001
```

每支从已提交源码和自己的公开研究经验出发，最多 6 个新节点、深度 3，每个节点最多 2 个孩子。每条父子边先在固定的 5 道题上比较：父、子各跑 5 题，共 10 次运行，再继续深入；分数下降不会自动剪枝。到深度或孩子数量上限后回溯。探索顺序与最终选择分开，研究器可以选择之前评估过的候选。提交前的 baseline 比较也重跑这同一组题，不构成 validation。

每支题目上限为 `2 + 2 × batch × nodes + 2 × batch`：当前参数下为 72 次，包含开场和提交前的 baseline 比较。提前提交或剩余额度不足会减少实际探索节点，必须如实报告。不同分支虽使用相同题号，仍是独立运行，不构成一次统一的候选配对排名。

## 4. 查看结果与显式恢复

```sh
# 只从已有记录生成报告，不请求模型
PYTHONPATH=.artifacts/tau2/dfs-001/implementation \
python3 -P -B -m loopblox.experiments.search report \
  .artifacts/tau2/dfs-001
```

入口包括 `report.md`、`analysis.json`、各分支的 `selected-controller.py` 及 `public/evaluations/`。原始记录会含大量任务数据与模型内容，默认全部保存在 Git 忽略的 `.artifacts/`。

出现错误后先确认故障类型并关闭旧进程。明确决定恢复时，使用原 campaign 的冻结入口创建新目录，再从新实现启动：

```sh
PYTHONPATH=.artifacts/tau2/dfs-001/implementation \
.artifacts/upstream/tau2-bench/.venv/bin/python -P -B -m loopblox.experiments.search resume \
  .artifacts/tau2/dfs-recovery-001 .artifacts/tau2/dfs-001

PYTHONPATH=.artifacts/tau2/dfs-recovery-001/implementation \
.artifacts/upstream/tau2-bench/.venv/bin/python -P -B -m loopblox.experiments.search run \
  .artifacts/tau2/dfs-recovery-001
```

恢复保留已经提交的分支，未完成分支从新研究器开始，扣除此前任务、模型、输出和时间开销。它不会继续旧 Python 调用栈或重放已执行工具。若需要修改实现，应在新 campaign 中明确记录变更，不能改写历史来源。

定时恢复需要运行者另行授权及外部调度器；CLI 不会自行创建计时器。可选择仅对实际 `service_not_ready` 等待至少 14 分钟后恢复。429 / `rate_limit` 和其他错误不能套用这个条件，正常运行期间也不周期性重启。长实验应放在由运行者管理的持久终端或进程服务中；临时命令会话的关闭可能终止调度。

2026-09-13～14 保留的旧 campaign 使用整理前的平铺目录，仍应通过其原始 `implementation/run_random_search.py` 入口恢复。旧冻结实现仍包含本轮已确认的有放回抽样错误；原样恢复不能视为落实了不放回要求。固定题号规则只适用于新实验，不能将新旧结果合并成同一个无偏差实验。不要替换旧 campaign 的实现副本或协议。
