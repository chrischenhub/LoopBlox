# LoopBlox

![Search for better agent loops.](docs/assets/loopblox-banner.svg)

[Quick start](#quick-start) · [Write a Loop](CONTROLLER.md) · [Components](COMPONENTS.md) · [Research protocol](experiment.md)

LoopBlox is an open-source research environment for composing agent behavior in Python and letting a research agent improve Loops on the same benchmark. Evaluate complete task outcomes and costs while keeping the tasks, model, tools, and component contracts fixed.

**Research prototype.** The active release benchmark is **τ²-bench telecom**. Its pinned official train/test tasks use deterministic environment checks, with additional action checks on some tasks; they do not require an LLM grader. The retail adapter and historical experiments remain available. No holdout improvement has been established.

**Native Codex is the default researcher.** It analyzes approved public evidence and requests work through the existing research host. The former LoopBlox researcher and its two-arm launcher are [archived](archive/researcher-20260921/); historical campaigns retain their exact frozen implementations. See [researcher setup](docs/running.md#native-codex-researcher).

The current [continuous research protocol](experiment.md) evaluates new Loops on one frozen benchmark and carries the evidence into the next iteration. Random search, BFS/DFS and multi-condition studies are retired. The continuous launcher freezes the implementation and task set, checkpoints each iteration, and supports explicit stop and infrastructure recovery.

## Announcement target

The first LinkedIn announcement requires a complete, reproducible **τ²-bench telecom** example. Readers should be able to follow the Python Loop, see how research changed it, and inspect its recorded execution. Three deliverables define this milestone:

1. A non-baseline Loop with an observed success-rate gain. Search on official training tasks and select a Loop with a meaningful behavioral change from [the reactive baseline](controllers/reactive.py). The result requirement still needs a separately authorized final evaluation on the complete pinned official telecom test split, with research closed and selection frozen. Evaluate the baseline and selected Loop on that same benchmark under identical settings and task limits, with fresh environments and rotated execution order. Report the paired success-rate gain alongside calls, tokens, time, known costs, failures and missing scores. Reused development results alone do not satisfy this result requirement.
2. An educational visualization of that result. Show the baseline and selected Python Loops, explain the changed composition, and connect their components to recorded task executions. Make model calls, context, tool execution and observations understandable, with Jev measurements linked to the evidence they describe. Distinguish illustrative control flow from executed steps. The view is read-only and derives from source and recorded traces.
3. Jev integrated into the released research workflow. Generate semantic measurements from public development traces, make them available to the researcher, and preserve evidence that the researcher inspected them during the search that produced the selected Loop. Include input provenance, returned measurements, model/schema identity and usage. Document how to run this path from a fresh checkout. The environment evaluator remains the source of task scores; Jev supplies diagnostic evidence.

Before the campaign, freeze task membership and prior exposure, candidate-selection rules, model settings, budgets, repeats and score handling in its run protocol. Historical research exposed some official test tasks; disclose that exposure and related task families in the result. Official test tasks stay outside research. Any final evaluation requires separate review and authorization, with research closed before its feedback is available. Report an observed gain with its sample size and uncertainty; stronger claims require supporting evidence. An incomplete final evaluation or no gain leaves the result requirement unmet.

Publish the exact baseline and selected source, reproduction commands, frozen configuration, task results and permitted trace examples with the visualization. Raw evidence retains its existing artifact provenance. [experiment.md](experiment.md) owns the current research workflow.

## A Loop is Python

This is the [shared baseline](controllers/reactive.py):

```python
def run(env):
    while True:
        context = env.component("context_full")
        decision = env.component("decide", context=context["id"])
        if decision["value"]["kind"] == "completion_proposed":
            return decision["value"]["response"]
        execution = env.component("execute", decision=decision["id"])
        env.component("observe_full", execution=execution["id"])
```

A Loop chooses component order, repetition, branches, and exposed options using ordinary Python. The host owns model and tool access, isolation, budgets, and scoring. The outer `run(env)` return ends the controller; scoring follows after its worker closes.

The [14 components](COMPONENTS.md) cover context and evidence, proposals, assessment, and actions. Try [working through plan steps](controllers/scoped_plan.py), [comparing decision proposals](controllers/compared_work.py), [reviewing completion](controllers/planned_work.py), or [reflecting after tool failures](controllers/failure_reflection.py). Context can retain a summary while adding new evidence, and brief observations can be paged or expanded to their original full result. The `judge` component uses Jev for caller-defined yes/no judgments and classification; questions and category descriptions are editable while evidence access and output types stay fixed. See [Judge usage](CONTROLLER.md#judge-online-typed-judgments). Contracts live in [components.py](loopblox/runtime/components.py); the catalog is generated from that source.

## How research works

1. Freeze one benchmark's development tasks, component boundary, baseline, model, seeds, and budgets. Evaluate the baseline on the full task set.
2. Inspect evidence, save new Loops and evaluate them on that same task set. Every development task run receives [Jev analysis](docs/jev.md) before its feedback reaches the researcher: four observed cycles per segment, with the final partial segment retained.
3. Keep the best evaluated Loop and checkpoint the evidence for the next iteration. Record outcomes, failures and costs, including the researcher and simulated user. Follow [the protocol](experiment.md) for candidate allowances and stopping conditions.

Search changes Python compositions; model weights stay fixed. Each task gets a fresh environment and isolated worker. A checkpoint preserves work without ending continuous research. The old comparison launchers are [archived](archive/experiment-workflows-20260921/README.md); the [continuous launcher](docs/running.md#run-stop-and-recover) freezes one campaign and keeps iterating until stopped.

## Quick start

Use **Python 3.12** from the repository root. These commands inspect the project without model requests; the core host uses only the standard library:

```sh
python3 -B -m loopblox.runtime.components --markdown
python3 -B -m loopblox.benchmarks.run_tau2 --help
```

For task runs, start Docker Engine and configure a model service compatible with the gateway's structured Chat Completions requests:

```sh
cp .env.example .env
# Set FREEINFERENCE_API_KEY and model settings in .env
```

Follow the [τ² setup guide](docs/running.md) to install the pinned benchmark environment and prepare its task suite. It documents launching, inspecting, stopping and recovering the continuous campaign. Real runs consume model quota, including simulated-user calls; freeze settings before starting. Raw runs stay in Git-ignored `.artifacts/` and are not included in a fresh clone.

Research also requires `TYPESAFE_API_KEY` and `typesafe-sdk==0.7.0` in the host interpreter or a separate interpreter selected by `LOOPBLOX_JEV_PYTHON`. [Jev setup and accounting](docs/jev.md) covers both optional online `judge` calls and mandatory post-run analysis. Online calls consume task and research budgets; post-run analysis consumes the research budget after the task closes. Loops that call Judge require the same Jev setup outside research too.

For research, configure `LOOPBLOX_CODEX_BINARY_ROOT` with the pinned Linux Codex 0.155.0 distribution and provide an existing ChatGPT subscription login. The default is `gpt-6-astra` with `low` reasoning. [Native Codex setup](docs/running.md#native-codex-researcher) explains authentication, isolation and supported budgets; missing setup fails before opening task runs, with no fallback to the archived researcher.

For a local chat with a live view of the reactive Loop, run `python3 -B -m loopblox.chat serve` and open http://127.0.0.1:8766/. It uses the configured model and Docker worker. The [playground guide](site/README.md#local-chat-and-loop-view) describes its read-only tools, per-message limits, and saved traces.

## Research status

The September 21 Codex researcher completed 30 candidate evaluations on the reused telecom opening: the terminal-guard Loop passed 8/10, the summary variant 5/10 and the repetition-triggered reflection variant 6/10. It submitted the terminal-guard Loop. These are development results; historical control budgets differed, and no holdout comparison has run. The [comparison record](docs/codex-research-comparison.md) preserves the interrupted two-researcher study and its costs. The former researcher was subsequently retired; that decision does not establish a comparative research advantage.

The September 13–15, 2026 pilot screened 10 random Loops and completed initial research on three. Two DFS branches submitted; the latest loop04 recovery completed its task evaluations but stopped after a submission-guard error. In its last paired batch, baseline passed 5/5 and the original loop04 source passed 3/5. DFS and its recoveries retain 210 task attempts, 204 scored results, six missing scores, and 6,655 model attempts; these totals exclude BFS. The [September 15 closeout](docs/experiments/dfs-closeout-20260915/README.md) records the latest results. The [earlier report](docs/experiments/bfs-dfs-20260914/README.md) preserves BFS screening and the sampling error: five draws covered only four distinct tasks. There was no validation or holdout.

The [BFS/DFS protocol](docs/random-search.md), [bounded release protocol](docs/release-research.md), [multi-condition lifecycle proposal](docs/continual-improvement.md), and specialist/mixed-domain `study` workflow are retired. Their records describe historical work and superseded designs. The corrected fixed-task BFS/DFS design was never rerun.

The continuous workflow in [experiment.md](experiment.md) now connects the native researcher, task runner and Jev analysis. Its launch, stop and recovery paths have offline validation; a live campaign and evidence of improvement remain the next validation milestone. The [announcement target](#announcement-target) remains a useful improved Loop and an educational view of its evidence.

SpreadsheetBench 2 modeling/debugging is the next benchmark direction. It and Terminal-Bench are not integrated; TextWorld is retired.

## Explore

| Start here | What you'll find |
| --- | --- |
| [Controller API](CONTROLLER.md) / [examples](controllers/) | Write and compose Loops. |
| [Concepts](loop.md) / [component contracts](COMPONENTS.md) | Definitions, boundaries, and available operations. |
| [Research protocol](experiment.md) | Continuous Loop improvement on one frozen benchmark. |
| [τ² setup](docs/running.md) | Environment setup, task preparation, continuous runs and recovery. |
| [Jev analysis](docs/jev.md) | Fixed post-run segment measurements, researcher feedback, setup and usage. |
| [Native Codex setup](docs/running.md#native-codex-researcher) / [comparison record](docs/codex-research-comparison.md) | Default researcher, access boundary and archived two-researcher experiment. |
| [Implementation](loopblox/) / [conditions](experiments/) | Runtime and research code; experiment configuration. |
| [Website](site/README.md) | Build the read-only visual introduction. |
| [Engineering policy](AGENTS.md) | Isolation, accounting, freezing, and recovery rules. |

[MIT license](LICENSE). Benchmark sources and bundled font licenses are documented in [Sources and licenses](docs/sources.md).
