# 运行实验

所有命令从仓库根目录执行。先完成 [README 的环境配置](../README.md#快速开始)，并启动 Docker。查看组件目录和本页的 prepare 不调用模型；compare、study、run 和分支研究会调用配置的模型服务，消耗额度。先查看对应命令的 `--help` 并设置预算。

核心宿主模块使用标准库；τ² 入口使用其冻结的 Python 3.12 环境，TextWorld 解释器位于单独的 Docker 镜像。模型使用 `.env` 中的 `FREEINFERENCE_API_KEY`、`FREEINFERENCE_BASE_URL` 和 `FREEINFERENCE_MODEL` 配置。

## τ²-bench：领域对比

```sh
git clone https://github.com/sierra-research/tau2-bench .artifacts/upstream/tau2-bench
git -C .artifacts/upstream/tau2-bench checkout 672227c6b6676edc20d57ea53b7000262aae77b9
uv sync --project .artifacts/upstream/tau2-bench --frozen --no-dev
docker pull python:3.12-slim

# 小规模接入检查集：每领域 2 development + 1 holdout
.artifacts/upstream/tau2-bench/.venv/bin/python -B run_tau2.py prepare \
  --output .artifacts/tau2/integration-001 --development 2 --holdout 1

# full、brief、Plan→full 三个固定 Loop；只运行 development
.artifacts/upstream/tau2-bench/.venv/bin/python -B run_tau2.py compare \
  --suite .artifacts/tau2/integration-001 --output .artifacts/tau2/compare-001

# 对冻结顺序中的每领域前两个开发任务各重跑两遍，观察同任务波动
.artifacts/upstream/tau2-bench/.venv/bin/python -B run_tau2.py compare \
  --suite .artifacts/tau2/integration-001 --output .artifacts/tau2/repeat-001 \
  --development-per-domain 2 --repeats 2

# 专用搜索、混合搜索、全部冻结、相同 holdout 对照
.artifacts/upstream/tau2-bench/.venv/bin/python -B run_tau2.py study \
  --suite .artifacts/tau2/integration-001 --output .artifacts/tau2/study-001

# 后续实验的候选集合准备示例：每领域 18 + 18，排除接入检查组
.artifacts/upstream/tau2-bench/.venv/bin/python -B run_tau2.py prepare \
  --output .artifacts/tau2/domain-001 --development 18 --holdout 18 \
  --seed 3101 --exclude-suite .artifacts/tau2/integration-001

python3 -B run_tau2.py report .artifacts/tau2/study-001
```

`prepare` 不调用模型：它审核空轨迹评分，按控制需求分层选取任务，再冻结代码、数据、依赖版本和种子。若审核后组数不足会保留失败记录并退出，不以重复模板填充。运行须使用准备时的 Python 与依赖；每次输出目录必须是新的。

这是自定义分组 subset，不等同于官方 train/test 划分或完整榜单的可靠性指标。CLI 内部串行执行任务；它不会协调其他进程对同一模型服务的请求。

`compare` 默认使用全部开发任务、每个 controller 运行一次。可用 `--development-per-domain` 在执行前固定每领域的开发任务前缀，并用 `--repeats` 重跑；每次重建环境和 worker，保留相同任务种子，轮换 controller 顺序。报告按任务与重复编号配对。重复运行不增加独立任务组数量，也不保证服务商在相同种子下返回相同结果。

宿主通过 `compare(args, controllers=(("control", "failure_reflection.py"), ("stagnation", "stagnation_reflection.py")))` 指定额外候选时，reactive baseline 自动加入。`baseline` 名称保留给统一基线；`control` 表示额外的局部消融对照。未指定额外候选时，默认比较 baseline、brief、plan 三个 Loop。

适配器沿用官方政策、工具、对话状态机、模拟用户和最终评分，替换执行 agent 的 Loop。telecom 的用户拥有独立设备工具，其内部调用和私有指令不进入 controller 上下文。每题新建官方环境与用户状态，并在隔离 Docker worker 中执行候选。`respond_to_user` 发送客户可见回复；外层 `run(env)` 返回结束 controller，但不会代替发送消息，也不代表评分通过。

**评分以固定版本任务文件为准。** 在固定的 [retail tasks](https://github.com/sierra-research/tau2-bench/blob/672227c6b6676edc20d57ea53b7000262aae77b9/data/tau2/domains/retail/tasks.json) 中，112/114 使用 DB + NL_ASSERTION；[telecom tasks](https://github.com/sierra-research/tau2-bench/blob/672227c6b6676edc20d57ea53b7000262aae77b9/data/tau2/domains/telecom/tasks.json) 中，2253/2285 使用 ENV_ASSERTION，另外 32 个还要求 ACTION。这与上游概览中“DB + COMMUNICATE”的描述不一致。

首轮 subset 排除非空 LLM 断言、指定动作路径、转交人工以及空轨迹即可得分的任务。它验证交易结果与诊断后的环境条件，不全面评价拒绝、转交、沟通质量或政策遵循。官方评分在 worker 关闭后执行；研究 agent 只读取开发任务的得分和公开轨迹，参考动作、断言与完整用户模拟记录保存在宿主私有目录。

agent 和模拟用户使用同一固定模型配置，用户温度默认为 0；可用 `--user-model` 单独冻结用户模型。两者共用每题及研究预算，分别报告用量。工具动作上限约束 controller 发出的动作，用户工具由官方状态机和额外步数上限约束。没有冻结美元单价时价格为未知，实际 token 与失败调用成本仍保留。

SpreadsheetBench 2 是后续验证方向：建模／调试需要依照[官方运行说明](https://github.com/RUCKBReasoning/SpreadsheetBench-2)用 LibreOffice 重算工作簿；可视化除了 VLM 判断，还涉及官方 Windows Excel/WPS 图像导出。接入前需逐题审核评分覆盖与依赖，不能将财务表格能力直接称为完整 accounting operations。

## TextWorld：机制检查

```sh
# 准备环境与 controller 镜像；TextWorld 的发行包使用 x86_64 原生解释器
docker build --platform linux/amd64 -t loopblox-textworld:1.7.0 environments/textworld
docker pull python:3.12-slim

# 每个任务族生成 4 个开发任务和 4 个 holdout 任务，并私下验证可解性
python3 -B run_textworld.py prepare --output .artifacts/textworld/suite-001

# 基线、两个任务族的搜索、同任务 holdout 对照与跨任务族比较
python3 -B run_textworld.py study \
  --suite .artifacts/textworld/suite-001 \
  --output .artifacts/textworld/study-001

# 从已有记录重新生成 report.html，不调用模型
python3 -B run_textworld.py report .artifacts/textworld/study-001
```

`study --help` 列出每题限制与每个研究 episode 的预算；默认值是开发设置。每次准备和实验都要求新的输出目录，不恢复中断的 Python continuation。实验冻结 Docker image ID、依赖版本、生成参数、种子、游戏文件校验值、代码和组件目录。重跑已有 suite 需要保留对应 image ID；跨机器搬运时可用 `docker save` / `docker load` 保留该镜像。

模型可见信息只包括游戏叙述、当前房间、背包和合法命令。金币任务的默认路线提示在编译前替换为目标说明。游戏元数据、参考解法、隐藏事实和策略奖励不进入模型上下文；调试命令被拒绝。每题使用新的 interpreter、worker 和临时工作目录，解法文件不放在研究 agent 可读取的 public artifacts 中。worker 关闭后读取环境胜负和得分；只有正常返回且环境报告获胜才计为通过，其他状态分别保留。

TextWorld 工具声明完整保留 `admissible_commands`，使 brief 观察仍能提供当前合法动作。其余内容按组件契约截短；保留字段计入实际模型输入成本，因此 brief 并不保证完整任务更便宜。修改后的组件库用于新的运行，历史实验保留原始实现与结果。

```sh
# 导出当前完整组件目录
python3 -B components.py

# 从同一份定义更新可读契约
python3 -B components.py --markdown > COMPONENTS.md

# 为一份已有轨迹生成只读报告
python3 -B trace_report.py path/to/trace.json --output path/to/report.html
```

[COMPONENTS.md](../COMPONENTS.md) 包含每个组件的返回引用类型与完整契约；[CONTROLLER.md](../CONTROLLER.md) 是研究 agent 读取的编排 API。episode 中的 JSON 与 Markdown 目录从同一份过滤结果生成，以实际开放选项为准。
