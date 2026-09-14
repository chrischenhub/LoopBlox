# τ² environment and general experiment commands

Updated September 14, 2026. This page covers environment setup, fixed Loop comparisons, and domain studies. The current BFS/DFS protocol uses five fixed tasks; see its [experiment guidelines](random-search.md). The development/holdout splits and explicit repeat options below are separate from that pilot's configuration.

Run all commands from the repository root. Complete the [README setup](../README.md#quick-start) and start Docker first. Inspecting the component catalog and running this page's `prepare` command do not call models. Comparisons, studies, campaign runs, and branch research use the configured model service and consume quota. Inspect the relevant `--help` output and set budgets first.

Core host modules use the standard library. The τ² entry point uses its frozen Python 3.12 environment; candidate Loops run in isolated Docker workers. Configure the model through `FREEINFERENCE_API_KEY`, `FREEINFERENCE_BASE_URL`, and `FREEINFERENCE_MODEL` in `.env`.

## τ²-bench domain comparisons

```sh
git clone https://github.com/sierra-research/tau2-bench .artifacts/upstream/tau2-bench
git -C .artifacts/upstream/tau2-bench checkout 672227c6b6676edc20d57ea53b7000262aae77b9
uv sync --project .artifacts/upstream/tau2-bench --frozen --no-dev
docker pull python:3.12-slim

# Small integration subset: 2 development + 1 holdout task per domain
.artifacts/upstream/tau2-bench/.venv/bin/python -B -m loopblox.benchmarks.run_tau2 prepare \
  --output .artifacts/tau2/integration-001 --development 2 --holdout 1

# Three fixed Loops: full, brief, and Plan followed by full; development only
.artifacts/upstream/tau2-bench/.venv/bin/python -B -m loopblox.benchmarks.run_tau2 compare \
  --suite .artifacts/tau2/integration-001 --output .artifacts/tau2/compare-001

# Run the first two frozen development tasks per domain twice to observe variability
.artifacts/upstream/tau2-bench/.venv/bin/python -B -m loopblox.benchmarks.run_tau2 compare \
  --suite .artifacts/tau2/integration-001 --output .artifacts/tau2/repeat-001 \
  --development-per-domain 2 --repeats 2

# Specialist and mixed search; freeze all selections, then compare on shared holdout
.artifacts/upstream/tau2-bench/.venv/bin/python -B -m loopblox.benchmarks.run_tau2 study \
  --suite .artifacts/tau2/integration-001 --output .artifacts/tau2/study-001

# Example pool for a later study: 18 + 18 per domain, excluding integration groups
.artifacts/upstream/tau2-bench/.venv/bin/python -B -m loopblox.benchmarks.run_tau2 prepare \
  --output .artifacts/tau2/domain-001 --development 18 --holdout 18 \
  --seed 3101 --exclude-suite .artifacts/tau2/integration-001

python3 -B -m loopblox.benchmarks.run_tau2 report .artifacts/tau2/study-001
```

`prepare` audits empty-trajectory scores, selects tasks stratified by control requirements, and freezes code, data, dependency versions, and seeds without model calls. If too few eligible groups remain, it preserves the failure record and exits rather than filling the set with repeated templates. Runs must use the Python environment and dependencies recorded during preparation. Every output directory must be new.

These are custom grouped subsets, not the official train/test splits or full-leaderboard reliability metrics. The CLI runs tasks serially and does not coordinate requests from other processes using the same model service.

`compare` defaults to all development tasks with one run per controller. `--development-per-domain` freezes a prefix of each domain's development tasks before execution; `--repeats` reruns those tasks. Each run creates a fresh environment and worker, retains the task seed, and rotates controller order. Reports pair by task and repeat index. Repeats do not add independent task groups or guarantee identical provider responses under the same seed.

A host call such as `compare(args, controllers=(("control", "failure_reflection.py"), ("stagnation", "stagnation_reflection.py")))` adds the reactive baseline automatically. The name `baseline` is reserved for that shared reference; `control` labels an additional mechanism ablation. With no additional controllers specified, the defaults are baseline, brief, and plan.

The adapter retains the official policies, tools, conversation state machine, simulated user, and final evaluator while replacing the agent's Loop. Telecom users have separate device tools; their internal calls and private instructions are excluded from controller context. Every task gets fresh official environment/user state and an isolated controller worker. `respond_to_user` sends customer-visible messages. The outer `run(env)` return ends the controller; it neither sends a customer message nor certifies success.

**Scoring follows the pinned task files.** In the pinned [retail tasks](https://github.com/sierra-research/tau2-bench/blob/672227c6b6676edc20d57ea53b7000262aae77b9/data/tau2/domains/retail/tasks.json), 112/114 use DB + NL_ASSERTION. In the [telecom tasks](https://github.com/sierra-research/tau2-bench/blob/672227c6b6676edc20d57ea53b7000262aae77b9/data/tau2/domains/telecom/tasks.json), 2253/2285 use ENV_ASSERTION; the other 32 also require ACTION. This differs from the upstream overview's DB + COMMUNICATE description.

The initial subset excludes nonempty LLM assertions, prescribed action paths, human handoffs, and tasks that score on an empty trajectory. It verifies transaction outcomes and environment conditions after diagnosis, without comprehensively evaluating refusals, handoffs, communication quality, or policy compliance. Official scoring begins after the worker closes. The researcher can read development scores and public traces; reference actions, assertions, and complete user-simulation records stay in host-private directories.

The agent and simulated user default to the same model, with user temperature 0. `--user-model` can freeze a separate user model. Both share task and research budgets, with usage reported separately. The action limit applies to controller-issued actions; user tools are bounded by the official state machine and an additional step cap. Dollar cost remains unknown unless unit prices are frozen. Actual token use and failed-call costs remain recorded.

SpreadsheetBench 2 is a subsequent validation direction. Its [official instructions](https://github.com/RUCKBReasoning/SpreadsheetBench-2) require LibreOffice recalculation for modeling/debugging; visualization evaluation also involves Windows Excel/WPS image export alongside VLM assessment. Audit task scoring and dependencies before integration. Financial spreadsheet tasks alone do not establish full accounting-operations capability.

## Component catalog and execution reports

```sh
# Export the current full component catalog
python3 -B -m loopblox.runtime.components

# Regenerate readable contracts from the same definitions
python3 -B -m loopblox.runtime.components --markdown > COMPONENTS.md

# Generate a read-only report from an existing trace
python3 -B -m loopblox.report path/to/trace.json --output path/to/report.html
```

[COMPONENTS.md](../COMPONENTS.md) lists each component's returned reference type and full contract. [CONTROLLER.md](../CONTROLLER.md) is the composition API read by the researcher. Episode JSON and Markdown catalogs derive from the same filtered definitions; only the episode's exposed options are available.
