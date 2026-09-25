![LoopBlox](docs/assets/loopblox-banner.png)
[Quick start](#quick-start) · [Visualize research](#visualize-your-experiment) · [Write a Loop](CONTROLLER.md) · [Components](COMPONENTS.md) · [Research protocol](experiment.md)

LoopBlox lets a Codex researcher edit an agent's Python loop and test each version on the same benchmark. It saves source code, task traces, scores and research notes from every iteration. The current experiment uses five official **AppWorld** training tasks, an isolated native code shell and the original evaluator. Research continues until you stop it.

The earlier telecom campaign and AppWorld pilot runs remain stopped and archived.
[AppWorld setup](docs/appworld.md) describes the current execution environment;
[experiment.md](experiment.md) owns the continuous research protocol.

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

The researcher can change component order, add branches, and repeat calls using ordinary Python. LoopBlox provides [14 components](COMPONENTS.md); their behavior, the task model, and the scoring rules stay fixed during research. See the [controller API](CONTROLLER.md) to write a Loop.

## How research works

![Research and Harness Loops: review results, edit and evaluate the Loop, save findings, and route errors to research feedback, infrastructure repair, or human input.](docs/assets/research-process.png)

LoopBlox first runs the baseline on five AppWorld tasks. Codex reviews the scores and traces, edits the Loop, and requests an evaluation on the same tasks.

LoopBlox keeps the best Loop by success rate, then cost. Codex saves its findings and tries the next change. This continues until you stop it. The [research protocol](experiment.md) defines evaluation and recovery rules.

## Quick start

You need **Python 3.12, Git, [uv](https://docs.astral.sh/uv/getting-started/installation/), and Docker** on macOS, Linux, or WSL2. Start Docker, clone the repository, and keep your terminal in its root directory for the steps below.

```sh
git clone https://github.com/chrischenhub/LoopBlox.git
cd LoopBlox
cp .env.example .env
```

### 1. Set up the services

Research uses three services. Codex edits Loops through your ChatGPT subscription. FreeInference or OpenCode Go runs the task agent (and the simulated user in interactive mode). Jev analyzes task traces.

Follow the [installation guide](docs/running.md#install-the-host-dependencies) to install the benchmark environment, Jev SDK, and pinned Linux Codex distribution, then sign in to ChatGPT. Copy the two path assignments printed by setup into `.env` and set `FREEINFERENCE_API_KEY` and `TYPESAFE_API_KEY`. Paths must be absolute; `.env` does not expand `$HOME` or `$PWD`.

The guide also covers [other model providers](docs/running.md#host-configuration) and [login locations](docs/running.md#chatgpt-login). Research consumes service quota and continues until you stop it. Each task has [its own budget](experiment.md#limits-and-accounting).

### 2. Prepare tasks and start research

```sh
# Use the benchmark's Python environment
source .artifacts/upstream/tau2-bench/.venv/bin/activate

# Run a fresh baseline, then continuously research on five training tasks
python -B -m loopblox.benchmarks.run_appworld \
  --output .artifacts/appworld/research-NEW \
  --continuous --task-count 5 --seed 20260922 \
  --provider freeinference --request-timeout 60 \
  --code-image loopblox-appworld-code:0.1.3-post1
```

Prepare AppWorld and its code image using [the setup guide](docs/appworld.md). Choose an unused output directory name. The runner stays in the foreground; leave that terminal open while research is running.

### 3. Check progress and stop

Read `<output>/evaluation/public/progress.json` for the incumbent and iteration count,
and `<output>/result.json` for run status. To stop, press Ctrl-C in the running
terminal or send SIGTERM to the PID recorded in `<output>/started.json`. Wait for
worker cleanup; completed results and usage remain on disk. Infrastructure recovery
uses a fresh directory and preserves completed evidence and all prior spend.

## Inspect a run

The campaign saves its files under the directory you passed to `--output`:

```text
research-NEW/
├── protocol.json               # Frozen task set, models and limits
├── result.json                 # Run status
└── evaluation/
    ├── private/                # Native researcher and gateway ledgers
    └── public/
        ├── progress.json       # Current incumbent and iteration count
        ├── notes.md            # Researcher's notebook
        ├── checkpoints/        # Saved iterations
        ├── candidates/         # Immutable Loop sources
        └── evaluations/        # Task traces, official scores and Jev analysis
```

`selected-controller.py` appears once a Loop has been fully evaluated. The researcher writes its notebook as it works. The example paths keep these records in Git-ignored `.artifacts/`; keep the campaign directory to retain them.

## Visualize your experiment

The live dashboard discovers AppWorld and historical telecom campaigns. Start it from
the repository root:

```sh
python3 -B -m loopblox.research.dashboard
```

Open [http://127.0.0.1:8767/](http://127.0.0.1:8767/). It refreshes every three seconds, discovers campaigns in `.artifacts/appworld/` and `.artifacts/tau2/`, and follows the newest confirmed live experiment. When none is detected, it says so and shows the latest recorded campaign. All tabs identify the selected benchmark, frozen task count and task interface. The page combines live task progress, official scores, Jev analysis and usage with the generic Loop visualizer: candidate comparisons, Python source and differences, and actual execution paths. Select one task to compare across all Loops, or select a campaign to keep watching that attempt. The dashboard reads existing records without making model calls or changing the experiment. See the [live dashboard guide](docs/running.md#live-research-dashboard) for options and accounting.

The **Research** tab summarizes the selected campaign's candidate evolution,
recorded findings and research notes, including post-run Jev coverage and optional
online Judge use. The main **Dashboard** tab keeps live progress and Loop exploration.
The **Trace** tab plots Jev's recorded segment judgments for a selected Loop and task.
Select a segment to inspect its original judgment, confidence and public execution
evidence. Missing measurements remain gaps; Jev judgments are separate from official scores.

For a standalone HTML report from a running or completed campaign:

```sh
python3 -B -m loopblox.research.visualize .artifacts/appworld/research-NEW/evaluation \
  --output .artifacts/visualizations/research-NEW.html
```

Open the HTML in a browser to compare Loop versions, read source changes, and inspect one task's recorded component calls. The report also shows evaluation scores and agent model usage. Run the command again to refresh it as research progresses; generating a report makes no model calls. The [visualization guide](docs/running.md#visualize-a-research-campaign) covers task selection and accounting.

## Try the local playground

The playground needs the task-model gateway and Docker. With `FREEINFERENCE_API_KEY` set in `.env` and Docker running:

```sh
docker pull python:3.12-slim
python3 -B -m loopblox.chat serve
```

Open http://127.0.0.1:8766/ to chat and watch the baseline's component calls. Each message uses the model service. See the [playground guide](docs/playground.md) for limits and saved traces.

## Find your way around the code

| File | What it does |
| --- | --- |
| [controllers/reactive.py](controllers/reactive.py) | The baseline task Loop. |
| [runtime/components.py](loopblox/runtime/components.py) | Component behavior, parameters, and fixed prompts. |
| [research/session.py](loopblox/research/session.py) | Candidate evaluations, selection, and iteration checkpoints. |
| [benchmarks/run_appworld.py](loopblox/benchmarks/run_appworld.py) | Frozen AppWorld runs and continuous research dispatch. |
| [benchmarks/appworld.py](loopblox/benchmarks/appworld.py) | Official AppWorld state, public API effects and private scoring. |
| [research/campaign.py](loopblox/research/campaign.py) | Historical telecom campaign lifecycle and recovery. |
| [benchmarks/tau2.py](loopblox/benchmarks/tau2.py) | Task preparation and integration with the official τ² environment and evaluator. |

The [concept guide](loop.md) defines Loops and components. [Running research](docs/running.md) covers setup and operation; the [protocol](experiment.md) defines evaluation rules. Read [AGENTS.md](AGENTS.md) before changing the implementation.

[MIT license](LICENSE). Benchmark sources and bundled font licenses are documented in [Sources and licenses](docs/sources.md).
