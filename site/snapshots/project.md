# LoopBlox

![Search for better agent loops.](docs/assets/loopblox-banner.svg)

[Quick start](#quick-start) · [Write a Loop](CONTROLLER.md) · [Components](COMPONENTS.md) · [Experiments](docs/continual-improvement.md)

LoopBlox is an open-source research environment for composing agent behavior in Python and letting a research agent search for better compositions. Compare complete task outcomes and costs while keeping the model, tools, and component contracts fixed.

**Research prototype.** The active release benchmark is **τ²-bench telecom**. Its pinned official train/test tasks use deterministic environment checks, with additional action checks on some tasks; they do not require an LLM grader. The retail adapter and historical experiments remain available. No holdout improvement has been established.

## Announcement target

The first LinkedIn announcement requires a complete, reproducible **τ²-bench telecom** example. Readers should be able to follow the Python Loop, see how research changed it, and inspect its recorded execution. Three deliverables define this milestone:

1. A non-baseline Loop with an observed success-rate gain. Search on official training tasks and select a Loop with a meaningful behavioral change from [the reactive baseline](controllers/reactive.py). Close all researchers and freeze the selection before comparing it with the baseline on the complete pinned official telecom test split. Use the same model settings, tools, component contracts, task limits, tasks and repeats, with fresh environments and rotated execution order. The selected Loop must achieve a higher paired success rate; report the size of the gain alongside calls, tokens, time, known costs, failures and missing scores.
2. An educational visualization of that result. Show the baseline and selected Python Loops, explain the changed composition, and connect their components to at least one recorded task comparison. Make model calls, context, tool execution and observations understandable, with Jev measurements linked to the evidence they describe. Distinguish illustrative control flow from executed steps. The view is read-only and derives from source and recorded traces.
3. Jev integrated into the released research workflow. Generate semantic measurements from public development traces, make them available to the researcher, and preserve evidence that the researcher inspected them during the search that produced the selected Loop. Include input provenance, returned measurements, model/schema identity and usage. Document how to run this path from a fresh checkout. The environment evaluator remains the source of task scores; Jev supplies diagnostic evidence.

Before the campaign, freeze task membership and prior exposure, candidate-selection rules, model settings, budgets, repeats and score handling in its run protocol. Historical research exposed some official test tasks; disclose that exposure and related task families in the result. Final test feedback must not guide further tuning or candidate selection. Report an observed gain with its sample size and uncertainty; stronger claims require supporting evidence. An incomplete comparison or no gain leaves the result requirement unmet.

Publish the exact baseline and selected source, reproduction commands, frozen configuration, aggregate comparison and permitted trace examples with the visualization. Raw evidence retains its existing artifact provenance. The broader [domain improvement study](docs/continual-improvement.md) remains a research direction beyond this release milestone.

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

1. Freeze the experiment: tasks, component boundary, baseline, model, seeds, and budgets.
2. Run the baseline, then let the researcher save immutable Loops, evaluate them on development tasks, inspect traces, and select candidates. Every development task run receives [Jev analysis](docs/jev.md) before its feedback reaches the researcher: four observed cycles per segment, with the final partial segment retained.
3. Compare candidates on complete shared task batches. Record calls, outcomes, failures, and costs, including the researcher and simulated user.

Search changes Python compositions; model weights stay fixed. Each task gets a fresh environment and isolated worker. In studies with holdout evaluation, all researchers close and selections freeze before holdout runs. Final feedback never returns to the researcher.

The proposed [domain improvement protocol](docs/continual-improvement.md) extends research across rounds: build an initial Loop, measure it on new tasks, release permitted experience, and search the next version before final sealed evaluation. It covers τ² and τ³ separately by domain. Each episode freezes its inputs; task-set updates happen between episodes. A narrow retail command now supports one lineage over three new official training batches followed by all official test; the complete multi-condition lifecycle is not implemented yet.

## Quick start

Use **Python 3.12** from the repository root. These commands inspect the project without model requests; the core host uses only the standard library:

```sh
python3 -B -m loopblox.runtime.components --markdown
python3 -B -m loopblox.benchmarks.run_tau2 --help
python3 -B -m loopblox.experiments.search --help
```

For task runs, start Docker Engine and configure a model service compatible with the gateway's structured Chat Completions requests:

```sh
cp .env.example .env
# Set FREEINFERENCE_API_KEY and model settings in .env
```

Follow the [τ² setup guide](docs/running.md) to install the pinned benchmark environment and run a comparison. The [search guide](docs/random-search.md) covers BFS/DFS preparation and budgets. Real runs consume model quota, including simulated-user calls; freeze settings before starting. Raw runs stay in Git-ignored `.artifacts/` and are not included in a fresh clone.

Research also requires `TYPESAFE_API_KEY` and `typesafe-sdk==0.7.0` in the host interpreter or a separate interpreter selected by `LOOPBLOX_JEV_PYTHON`. [Jev setup and accounting](docs/jev.md) covers both optional online `judge` calls and mandatory post-run analysis. Online calls consume task and research budgets; post-run analysis consumes the research budget after the task closes. Loops that call Judge require the same Jev setup outside research too.

For a local chat with a live view of the reactive Loop, run `python3 -B -m loopblox.chat serve` and open http://127.0.0.1:8766/. It uses the configured model and Docker worker. The [playground guide](site/README.md#local-chat-and-loop-view) describes its read-only tools, per-message limits, and saved traces.

## Research status

The September 13–15, 2026 pilot screened 10 random Loops and completed initial research on three. Two DFS branches submitted; the latest loop04 recovery completed its task evaluations but stopped after a submission-guard error. In its last paired batch, baseline passed 5/5 and the original loop04 source passed 3/5. DFS and its recoveries retain 210 task attempts, 204 scored results, six missing scores, and 6,655 model attempts; these totals exclude BFS. The [September 15 closeout](docs/experiments/dfs-closeout-20260915/README.md) records the latest results. The [earlier report](docs/experiments/bfs-dfs-20260914/README.md) preserves BFS screening and the sampling error: five draws covered only four distinct tasks. There was no validation or holdout.

The corrected [BFS/DFS protocol](docs/random-search.md) reuses five explicit development tasks for every comparison. **It has not been rerun yet.**

The next milestone is the [telecom announcement target](#announcement-target): a winning non-baseline Loop, an educational visualization, and Jev in the research workflow. The [bounded release protocol](docs/release-research.md) stops after development for review; switching domains requires a fresh campaign and does not resume the interrupted retail experiment. The broader round-based [protocol](docs/continual-improvement.md) compares a frozen initial Loop, continued search on fixed development tasks, and continued search with inherited experience, separately by domain. Reviewed task expansion follows as another condition. Its models, budgets, repeats, and splits still need to be frozen. τ² airline and τ³ integrations are planned and require separate audits. The existing specialist/mixed-domain study remains available as a separate comparison.

SpreadsheetBench 2 modeling/debugging is the next benchmark direction. It and Terminal-Bench are not integrated; TextWorld is retired.

## Explore

| Start here | What you'll find |
| --- | --- |
| [Controller API](CONTROLLER.md) / [examples](controllers/) | Write and compose Loops. |
| [Concepts](loop.md) / [component contracts](COMPONENTS.md) | Definitions, boundaries, and available operations. |
| [Domain improvement protocol](docs/continual-improvement.md) | Proposed training, new-task feedback, cross-round updates, and final evaluation for τ²/τ³. |
| [Run τ²](docs/running.md) / [BFS/DFS guide](docs/random-search.md) | Current setup, comparisons, and development-only search campaigns. |
| [Jev analysis](docs/jev.md) | Fixed post-run segment measurements, researcher feedback, setup and usage. |
| [Implementation](loopblox/) / [conditions](experiments/) | Runtime and research code; experiment configuration. |
| [Website](site/README.md) | Build the read-only visual introduction. |
| [Engineering policy](AGENTS.md) | Isolation, accounting, freezing, and recovery rules. |

[MIT license](LICENSE). Benchmark sources and bundled font licenses are documented in [Sources and licenses](docs/sources.md).
