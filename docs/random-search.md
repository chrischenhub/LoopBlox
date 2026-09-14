# 随机起点筛选与 DFS

这是 development-only pilot：搜索 Python Loop 的组合，不训练模型权重，不运行 validation 或 holdout。完整实验规则由 [AGENTS.md](../AGENTS.md) 维护。所有命令从仓库根目录执行，每次使用新的输出目录。

## 1. 准备开发专用 suite

先按照 [τ² 环境安装](running.md) 固定上游版本、安装其独立 Python 环境并准备 Docker；填写根目录 `.env`。

通用 `python -m loopblox.benchmarks.run_tau2 prepare` 会生成 development 与 holdout 两个划分。随机搜索入口要求 manifest 中只有 development，因此不能直接传入通用 suite。当前入口不提供单独选择开发子集的 CLI；运行者需先在宿主侧准备并冻结 development-only suite，记录它的来源、分组和选择规则，保留文件校验值，不能将 holdout 重新标记为 development。

以下命令中的 `.artifacts/tau2/development-001` 指这份已经准备好的 suite，新 clone 不包含它。本次保留的 BFS／DFS campaign 各有完整冻结 suite，可在本地用于后续开发实验。正式实验仍需另行冻结数据协议。

## 2. 冻结 10 个随机起点并筛选 Top 3

```sh
.artifacts/upstream/tau2-bench/.venv/bin/python -B -m loopblox.experiments.search prepare \
  .artifacts/tau2/random-001 --suite .artifacts/tau2/development-001 \
  --seed 20260913 --count 10 --batch 5 --top 3 --deep-runs 20

PYTHONPATH=.artifacts/tau2/random-001/implementation \
.artifacts/upstream/tau2-bench/.venv/bin/python -P -B -m loopblox.experiments.search run \
  .artifacts/tau2/random-001
```

`prepare` 不请求模型，但会检查模型配置、Docker 和冻结依赖，保存候选及实现副本。`run` 才开始模型调用。`PYTHONPATH` 指向冻结的 implementation，`-P` 防止当前工作目录中的源码优先加载；命令仍从仓库根目录执行，以读取本地 `.env`。生成器从已开放组件中抽取上下文、决策、观察、规划、复核和反思等组合，生成不同的普通 Python 源码，不读取题目答案。

筛选需要 1 次开场 baseline，以及 11 个 controller × 5 次共享抽样，共预留 56 次题目运行。同一批不放回抽样，因此每个 controller 运行 5 道不同题；开发题池少于 5 道时在准备阶段拒绝。各 controller 共享这 5 道题。完整评分的候选按通过数排序，平分时依次比较模型调用、输入／输出 token 和生成顺序；baseline 单独作为参考。缺分保留且不参与排名。

Top 3 各自启动新研究器，先跑 baseline 和起点的开场配对，再获得 `--deep-runs` 次开发运行额度。这里是自由局部研究，还没有强制 DFS 顺序。预算及模型设置以新 campaign 的 `protocol.json` 为准；不要编辑已冻结的协议来改变正在进行的实验。

## 3. 从三个已提交结果开始 DFS

只有起始分支全部完成提交，才能创建 DFS campaign：

```sh
.artifacts/upstream/tau2-bench/.venv/bin/python -B -m loopblox.experiments.search dfs \
  .artifacts/tau2/dfs-001 .artifacts/tau2/random-001 \
  --seed 20260914 --nodes 6 --depth 3 --batch 5

PYTHONPATH=.artifacts/tau2/dfs-001/implementation \
.artifacts/upstream/tau2-bench/.venv/bin/python -P -B -m loopblox.experiments.search run \
  .artifacts/tau2/dfs-001
```

每支从已提交源码和自己的公开研究经验出发，最多 6 个新节点、深度 3，每个节点最多 2 个孩子。每条父子边先跑完整的 5 次共享抽样配对，再继续深入；分数下降不会自动剪枝。到深度或孩子数量上限后回溯。探索顺序与最终选择分开，研究器可以选择之前评估过的候选。

每支题目上限为 `2 + 2 × batch × nodes + 2 × batch`：当前参数下为 72 次，包含开场和提交前的 baseline 比较。提前提交或剩余额度不足会减少实际探索节点，必须如实报告。不同分支的独立批次不能直接组成候选总排名。

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

2026-09-13～14 保留的旧 campaign 使用整理前的平铺目录，仍应通过其原始 `implementation/run_random_search.py` 入口恢复。旧冻结实现仍包含本轮已确认的有放回抽样错误；原样恢复不能视为落实了不放回要求。要使用修正后的采样规则，必须创建新实验，不能将新旧结果合并成同一个无偏差实验。不要替换旧 campaign 的实现副本或协议。
