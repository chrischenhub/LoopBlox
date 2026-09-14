# LoopBlox

Compose agent harness behavior from components with explicit contracts, compare those compositions on verifiable tasks, and let a research agent search for better Loops.

Loops are ordinary Python. The researcher can change component order, repetition, branches, and exposed options. The host fixes model interfaces, tools, component implementations, budgets, isolation, and scoring. Complete task runs are the evaluation unit; candidates, calls, failures, and costs are recorded.

**This is a research prototype.** It integrates τ²-bench retail and telecom. One random-start screening campaign and part of a depth-first search have run to exercise the process; no holdout improvement has been established. See the latest [BFS + DFS experiment summary](docs/experiments/bfs-dfs-20260914/README.md).

## Quick start

The core host uses only the Python standard library. Use Python 3.12 and run these commands from the repository root.

```sh
# Inspect component contracts and commands without model requests
python3 -B -m loopblox.runtime.components --markdown
python3 -B -m loopblox.benchmarks.run_tau2 --help
python3 -B -m loopblox.experiments.search --help
```

τ² dependencies have their own environment, and candidate Loops run in Docker workers. Setup instructions are linked below.

Real task runs also require a working Docker Engine and a model service compatible with the current structured Chat Completions requests:

```sh
cp .env.example .env
# Set your FREEINFERENCE_API_KEY and model configuration in .env
```

Environment variables and defaults are listed in [.env.example](.env.example). Their names follow the current gateway. Verify structured-response compatibility when changing the service address. Comparisons, studies, and research consume model quota, including calls by the τ² simulated user. Freeze the model and budgets before each experiment.

- [Run τ²](docs/running.md): pin the upstream version, prepare tasks, and run fixed comparisons or domain studies.
- [Current experiment guidelines](docs/random-search.md): the fixed five-task subset, BFS screening, Top 3 local research, DFS, and budgets.
- [Write a Loop](CONTROLLER.md): component references, calls, and the outer `run(env)` return.
- [Build the website](site/README.md): the English introduction and local preview.

## A Loop

The shared baseline is [controllers/reactive.py](controllers/reactive.py):

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

It directly composes full context, model decisions, execution, and full observations, normally with one model request per iteration. The outer controller returns after a completion proposal; a component return alone does not end the task. Authoritative scoring happens after the worker closes.

The library has 14 subcomponents organized into Context / Evidence, Propose, Assess, and Act. Families organize the catalog. [loopblox/runtime/components.py](loopblox/runtime/components.py) defines the contracts and allowed options, and [COMPONENTS.md](COMPONENTS.md) is generated from that source. Python is the sole executable Loop definition; website diagrams are explanatory.

| Example | Behavior |
| --- | --- |
| [reactive.py](controllers/reactive.py) | Shared baseline with full context and full observations. |
| [brief_work.py](controllers/brief_work.py) | Changes the baseline's observations to brief. |
| [plan_then_work.py](controllers/plan_then_work.py) | Adds one opening Plan to the baseline. |
| [planned_work.py](controllers/planned_work.py) | Plans first and reviews completion proposals. |
| [reviewed_plan.py](controllers/reviewed_plan.py) | Generates and reviews a plan before each action group. |
| [failure_reflection.py](controllers/failure_reflection.py) | Reflects after tool failures. |
| [stagnation_reflection.py](controllers/stagnation_reflection.py) | Reflects after tool failures or consecutive identical actions and results. |

The researcher's fixed Loop is [controllers/research.py](controllers/research.py). Repeated results are a reflection heuristic; they do not by themselves establish lack of progress or the effectiveness of a change.

## How experiments work

1. Freeze the question, component boundary, model, environment, task splits, seeds, baseline source, and budgets.
2. Run the shared baseline. The researcher saves immutable candidates, evaluates them on development tasks, reads public traces, and selects candidates.
3. Freeze all candidates in each comparison, then run the complete shared task batch. Pair results by task position and rotate candidate order. BFS/DFS uses the same five explicit task IDs on every comparison; see the [guidelines](docs/random-search.md).
4. Where holdout evaluation is configured, close the researcher and freeze its selection before running it. Final feedback never returns to the researcher.

Here, training means **searching Python Loop compositions**; model weights do not change. Complete the batch before judging a candidate. Each batch has `n` distinct tasks, and an insufficient task pool causes rejection rather than duplicate padding. BFS/DFS reuses its fixed task list, once per candidate per task. Other studies default to sampling without replacement within each evaluation. Repeated runs do not add independent task groups. Training-only pilots do not run holdout.

Task execution, research, and simulated-user calls share accounting and budgets. Task failure, exhaustion, model-service errors, host faults, and scoring faults retain distinct statuses. Interruptions and unknown usage stay in the ledger. Recovery starts in a new directory, preserves completed branches, and subtracts prior spend. Definitions are in [loop.md](loop.md); the full rules are in [AGENTS.md](AGENTS.md).

## Current status and next milestone

The September 13–14, 2026 pilot started with 10 random Loops, each evaluated on five shared development draws, and selected loop06, loop08, and loop04. All three completed initial local research before DFS recorded explicit parent-child edges. In DFS, loop06 and loop08 submitted; a model-service error blocked loop04. The campaign incorrectly sampled with replacement, violating the requirement. Its five BFS draws covered only four distinct tasks. Original results remain records of that protocol deviation. There was no validation or holdout; see the [experiment summary](docs/experiments/bfs-dfs-20260914/README.md) for results and limitations.

The current code uses explicit task IDs: BFS and DFS share five development tasks, and both parent and child rerun the full batch. There is no separate validation/test subset. **This protocol has not been rerun yet.** Its settings, stages, and budgets are in the [current experiment guidelines](docs/random-search.md).

The next formal study asks: **with the same model and components, can a Loop researched for one domain outperform the shared baseline and a mixed-domain Loop on unseen tasks?**

The plan uses audited, grouped τ² retail and telecom subsets for two specialist searches and one mixed-domain search. Mixed search receives the sum of the specialist budgets. After all researchers close, the baseline, specialist Loops, and mixed Loop face the same holdout tasks, with total cost and cross-domain performance recorded. Models, budgets, independent repeats, and formal dataset splits still need to be frozen.

TextWorld is retired; τ² is the only current environment. SpreadsheetBench 2 modeling/debugging is a subsequent direction and is not integrated. Terminal-Bench is also not integrated. Pi, DeepSeek Harness, Codex, and Claude Code inform behavior-boundary analysis; see the [pinned sources](docs/sources.md) and [harness decomposition](harness-decomposition.md). There are no native-harness optimization results.

## Code and documentation map

```text
loopblox/                 Python implementation; run modules from the repository root
├── runtime/              Component contracts, host execution, isolated worker, model and file I/O
├── research/             Research episodes, random candidate generation, DFS constraints
├── experiments/          Search, inheritance, domain studies, and shared process control
├── benchmarks/           τ² environment and command entry point
└── report.py             Reports for individual execution traces
controllers/              Baseline, mechanism controls, and the fixed researcher Loop
experiments/              JSON conditions: research questions and exposed components
docs/                    Running instructions, sources, limitations, and public experiment summaries
site/                     English introduction website
```

`loopblox/experiments/` contains orchestration code; the root `experiments/` contains configuration data. Each document has a defined responsibility. Historical records and build snapshots do not independently define the current experiment settings.

| Document | Responsibility and status |
| --- | --- |
| [README.md](README.md) | Project entry point, current status, next milestone, and navigation. |
| [Current experiment guidelines](docs/random-search.md) | BFS/DFS tasks, stages, budgets, and evidence limits. |
| [Run τ²](docs/running.md) | Environment setup, general fixed comparisons, and domain studies. Its holdout examples are separate from the current BFS/DFS pilot. |
| [AGENTS.md](AGENTS.md) | Engineering, freezing, accounting, isolation, research, and recovery rules. |
| [loop.md](loop.md) | Harness, Loop, Component, Invocation, and experiment-boundary definitions. |
| [CONTROLLER.md](CONTROLLER.md) | Implemented controller and researcher APIs. |
| [COMPONENTS.md](COMPONENTS.md) | Generated component contracts; do not edit independently. |
| [Historical experiment summary](docs/experiments/bfs-dfs-20260914/README.md) | Recorded BFS + DFS results, failures, missing scores, and the sampling deviation. |
| [Four-harness decomposition](harness-decomposition.md) | Design evidence from pinned versions. Early native-experiment ideas are outside the current run plan. |
| [Sources and licenses](docs/sources.md) | Pinned upstream versions, provenance, and third-party licenses. |
| [Website guide](site/README.md), [font guide](site/assets/fonts/README.md) | Site build, content ownership, and font licenses. `site/snapshots/*.md` are derived build inputs. |

Regenerate `COMPONENTS.md` after component changes and refresh snapshots after changing website inputs:

```sh
python3 -B -m loopblox.runtime.components --markdown > COMPONENTS.md
python3 -B site/build.py --refresh-notes
```

Raw experiments, frozen environments, and recovery chains live in Git-ignored `.artifacts/`; public summaries live in `docs/experiments/`. A fresh clone requires task-environment setup. The source repository excludes raw task trajectories, model credentials, and local deployment identity. Deleting files does not reset historical task exposure. See [LICENSE](LICENSE) for MIT terms and [docs/sources.md](docs/sources.md) for third-party sources and font licenses.
