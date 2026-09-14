# Current BFS/DFS experiment guidelines

Updated September 14, 2026. **This page describes the fixed-task protocol implemented in the current code. It has not been rerun yet.** The September 13–14 campaign used the old sampling rule. Its results and protocol deviation are documented in the [historical experiment summary](experiments/bfs-dfs-20260914/README.md); they are not results from this protocol.

This is a development-only pilot. Training means searching Python Loop compositions; model weights do not change. This page owns the current settings and operator workflow. [AGENTS.md](../AGENTS.md) owns engineering and evidence rules across experiments, and [CONTROLLER.md](../CONTROLLER.md) describes the researcher API. Run all commands from the repository root, using a new output directory each time.

## Agreed settings

| Item | Current rule |
| --- | --- |
| Task subset | BFS, Top 3 local research, and DFS share five fixed retail development tasks, listed below. There is no separate validation/test/holdout subset. |
| BFS | Generate 10 distinct random Loops. Run each candidate and the baseline on the same five tasks, then select the Top 3. Loop compositions are random; task IDs are fixed. |
| Top 3 local research | The current entry point retains this stage: each starting Loop undergoes free local research and submission before the explicitly ordered DFS starts. |
| DFS | Up to six new nodes per branch, maximum depth three, and at most two children per node. Complete each parent-child comparison before expanding. A lower score does not automatically prune descendants. |
| Comparison after a change | Rerun the parent on five tasks and run the child on those same five tasks: 10 complete task runs. Previous parent scores do not replace its runs in the new comparison. |
| Repetition and pairing | One run per candidate per task, `repeats=1`. Task IDs and order stay fixed across evaluations. Each run gets a fresh environment and worker; candidate order rotates by task position. |
| Completion and selection | Judge performance after the complete batch. DFS exploration order is separate from final selection. The baseline comparison before submission uses the same five tasks. |
| Per-task limits | 300 seconds, 40 agent actions, 64 model calls, and 65,536 output tokens. Simulated-user model calls count toward the budget. Models and total research budgets are frozen in the new campaign's `protocol.json`. |

A task run is one Loop's complete attempt at one task, potentially containing many model and tool calls. Five parent runs plus five child runs cover five distinct tasks. Historical scores and traces remain available for diagnosis and explanation. Reruns provide evidence about same-task variability, but one paired evaluation cannot eliminate variability or establish causality.

The default task-run allowances are caps, not recorded spend:

| Stage | Task-run allowance |
| --- | ---: |
| BFS screening | 56: one opening baseline run + (10 candidates + baseline) × five tasks. |
| Top 3 free local research | 22 per branch: up to two baseline/start opening runs + 20 subsequent runs; 66 across three branches. |
| DFS | 72 per branch: up to two opening runs + six parent-child edges × 10 runs + 10 runs for the baseline comparison before submission; 216 across three branches. |
| Full workflow | At most 338 task attempts. Time, model, output limits, or early submission may reduce actual runs. |

Missing scores cannot be filled in as passes or failures. Failures and interruptions remain charged; recovery subtracts prior spend rather than resetting the logical budget. These five tasks support screening and search, with each task worth 20% of a batch's success rate. The Top 3 are starting points for further exploration. Repeated selection on this set cannot establish generalization. Independent final validation is not configured; it requires a separate frozen dataset and an accurate record of prior task exposure.

## 1. Prepare a development-only suite

Follow the [τ² setup guide](running.md) to pin upstream source, install its separate Python environment, and prepare Docker. Configure the root `.env`.

The general `python -m loopblox.benchmarks.run_tau2 prepare` command creates both development and holdout splits. The random-search entry point requires a manifest containing only development tasks, so it cannot directly consume that general suite. There is no CLI for choosing a custom development subset. Prepare and freeze a development-only suite on the host, recording its source, grouping, selection rule, and file hashes. Do not relabel holdout tasks as development.

In the commands below, `.artifacts/tau2/development-001` refers to that prepared suite; a fresh clone does not include it. The preserved BFS/DFS campaigns contain complete frozen suites that can be used locally for later development experiments. A formal study still needs its own frozen data protocol.

BFS and DFS use these five development tasks: the first five IDs in ascending order from the original ten-task pool, chosen without reference to scores:

`retail-development-0000`, `retail-development-0002`, `retail-development-0004`, `retail-development-0006`, `retail-development-0007`.

[`TASK_IDS`](../loopblox/experiments/search.py) is the sole source of this list. Preparation copies it into `protocol.json`; batch size derives from its length, and `--batch` is no longer available. The suite must contain these development tasks; missing IDs cause an error. BFS, Top 3 local research, every DFS branch, all comparisons, and the baseline comparison before submission use the full list once per candidate, without task sampling. The separate opening check uses only the first task and does not eliminate candidates.

## 2. Freeze 10 random starts and select the Top 3

```sh
.artifacts/upstream/tau2-bench/.venv/bin/python -B -m loopblox.experiments.search prepare \
  .artifacts/tau2/random-001 --suite .artifacts/tau2/development-001 \
  --seed 20260913 --count 10 --top 3 --deep-runs 20

PYTHONPATH=.artifacts/tau2/random-001/implementation \
.artifacts/upstream/tau2-bench/.venv/bin/python -P -B -m loopblox.experiments.search run \
  .artifacts/tau2/random-001
```

`prepare` checks model configuration, Docker, and frozen dependencies, then saves candidates and implementation snapshots without model requests. `run` starts model calls. `PYTHONPATH` points to the frozen implementation; `-P` prevents source in the current working directory from taking precedence. Commands still run from the repository root to read the local `.env`. The generator samples exposed context, decision, observation, planning, review, and reflection choices to produce distinct Python sources without reading task answers.

Screening reserves 56 runs: one opening baseline run plus 11 controllers × five fixed tasks. Every controller uses identical task IDs and task order. Fully scored candidates rank by passes, then model calls, input/output tokens, and generation order. The baseline is a separate reference. Missing scores remain recorded and exclude a candidate from ranking.

Each Top 3 candidate starts a fresh researcher, runs the baseline/start opening pair, and receives `--deep-runs` additional development-run allowance. This is free local research; it does not yet enforce DFS order. The new campaign's `protocol.json` owns its frozen budgets and model settings. Do not edit a frozen protocol to change an active experiment.

## 3. Start DFS from the three submitted results

All starting branches must have completed submission before a DFS campaign can be created:

```sh
.artifacts/upstream/tau2-bench/.venv/bin/python -B -m loopblox.experiments.search dfs \
  .artifacts/tau2/dfs-001 .artifacts/tau2/random-001 \
  --seed 20260914 --nodes 6 --depth 3

PYTHONPATH=.artifacts/tau2/dfs-001/implementation \
.artifacts/upstream/tau2-bench/.venv/bin/python -P -B -m loopblox.experiments.search run \
  .artifacts/tau2/dfs-001
```

Each branch starts from its submitted source and its own public research experience, with at most six new nodes, depth three, and two children per node. Each parent-child edge first completes a comparison on the fixed five tasks: five runs per version, 10 runs total. A lower score does not automatically prune descendants. Search backtracks at the depth or child-count limit. Exploration and final selection are separate; the researcher may select a previously evaluated candidate. The baseline comparison before submission reruns the same five tasks and is not validation.

The per-branch task cap is `2 + 2 × batch × nodes + 2 × batch`, or 72 with the current settings, including opening runs and the baseline comparison before submission. Early submission or insufficient remaining budget reduces actual node coverage and must be reported. Branches share task IDs but execute separately; their results do not constitute one unified paired ranking.

## 4. Inspect results and explicitly recover

```sh
# Generate a report from existing records without model requests
PYTHONPATH=.artifacts/tau2/dfs-001/implementation \
python3 -P -B -m loopblox.experiments.search report \
  .artifacts/tau2/dfs-001
```

Start with `report.md`, `analysis.json`, each branch's `selected-controller.py`, and `public/evaluations/`. Raw records contain substantial task data and model content and live in Git-ignored `.artifacts/` by default.

After an error, establish its type and close the old process. Once recovery is explicitly authorized, use the original campaign's frozen entry point to create a new directory, then run its implementation:

```sh
PYTHONPATH=.artifacts/tau2/dfs-001/implementation \
.artifacts/upstream/tau2-bench/.venv/bin/python -P -B -m loopblox.experiments.search resume \
  .artifacts/tau2/dfs-recovery-001 .artifacts/tau2/dfs-001

PYTHONPATH=.artifacts/tau2/dfs-recovery-001/implementation \
.artifacts/upstream/tau2-bench/.venv/bin/python -P -B -m loopblox.experiments.search run \
  .artifacts/tau2/dfs-recovery-001
```

Recovery preserves submitted branches and starts fresh researchers for unfinished ones, subtracting prior task, model, output, and time spend. It does not resume Python call stacks or replay tools. Any implementation change must be recorded in a new campaign without rewriting historical sources.

Scheduled recovery requires operator authorization and an external scheduler; the CLI does not create timers. An authorized policy may wait at least 14 minutes after an actual `service_not_ready` failure. HTTP 429 / `rate_limit` and other failures do not meet that condition, and normal execution must not be periodically restarted. Use an operator-managed persistent terminal or process service for long experiments; closing a temporary command session may terminate the scheduler.

The preserved September 13–14 campaigns use the earlier flat source layout and must recover through their original `implementation/run_random_search.py`. Those frozen implementations retain the confirmed sampling-with-replacement error; resuming them does not satisfy the no-replacement requirement. The fixed-task rule applies only to new experiments. Do not combine old and new results as one experiment without a protocol deviation, or replace an old campaign's implementation or protocol.
