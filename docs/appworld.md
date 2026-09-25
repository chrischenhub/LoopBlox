# AppWorld integration and execution

The active five-task continuous RSI protocol is owned by
[experiment.md](../experiment.md). It starts from a fresh reactive baseline,
uses the official train split, and continues until the user stops. Earlier
single-task and ten-task pilot artifacts are archived; their results and sources
are not imported. Telecom research remains stopped.

## Setup and launch

Prepare a separate Python 3.11 environment with `appworld==0.1.3.post1`, run
`appworld install`, and download official data into a dedicated root. The defaults
are `.artifacts/upstream/appworld-venv` and `.artifacts/upstream/appworld-data`.
Use the existing LoopBlox host environment with Jev and configure the pinned
Linux Codex distribution and ChatGPT subscription login as described in
[running.md](running.md). Keep all environment paths absolute.

Build the isolated code shell once:

```sh
python -B -m loopblox.benchmarks.appworld_code --build-image loopblox-appworld-code:0.1.3-post1
```

Start the fresh continuous experiment:

```sh
python -B -m loopblox.benchmarks.run_appworld \
  --output .artifacts/appworld/research-NEW \
  --continuous --task-count 5 --seed 20260922 \
  --provider freeinference --request-timeout 60 \
  --code-image loopblox-appworld-code:0.1.3-post1
```

The launcher snapshots the task data, dependencies, implementation and settings,
then replaces itself with the frozen serial supervisor, preserving its host PID.
The supervisor starts one frozen attempt at a time. Before
baseline dispatch it checks the official empty-trajectory scores and validates
native researcher setup. No old candidates or task results are loaded.

Read `result.json` for the run status and `evaluation/public/progress.json` for
iterations and incumbent. Every batch writes `evaluation/public/evaluations/eNNNN/result.json`;
its task directories contain public traces, code receipts, official aggregate
scores and Jev measurements. Native researcher settings and usage live under
`evaluation/private`. Private AppWorld data and dependency snapshots must not be
published.

Ctrl-C, or SIGTERM to `supervisor_pid` in the sibling
`<output>-supervision/state.json`, stops the active operation and waits for cleanup.
The same state file identifies the current attempt and child PID. A user stop of
the child is also terminal for the supervisor. There is no fixed stopping round or final test dispatch. A failed
attempt cannot be resumed in place. Cleanup-only recovery preserves completed
batches and prior spend. A repair affecting inputs, outputs or protocol creates a
fresh condition using `--restart-from`, the same tasks and a newly evaluated
baseline, without importing candidates or research evidence. The supervisor
classifies the repair, retains its history, and rejects recurring unchanged fixes. The older `--previous`
option also recovers failed continuous runs when supplied with
`--recovery-reason`, the same provider/request settings and immutable image IDs.
It retains task selection, data, dependencies, model settings and cumulative spend;
the existing session restore copies complete batches and checkpoints unchanged,
while restarting unfinished batches with fresh workers and a fresh researcher.
Missing prior total charged duration remains unknown. Historical bounded pilots
can use `--previous` only when they have no scored tasks.

New continuous launches recover automatically after infrastructure diagnosis.
An isolated native worker reads frozen source and public failure evidence, proposes
an allowed function-body repair, and supplies a check run in the existing isolated
analysis workspace. Its proposal, validation, native usage and repaired source live
under `<output>-supervision/repair-NNNN`; recovered attempts live alongside them.
Existing attempts and the checkout are never rewritten. Ordinary task failures and
per-task exhaustion continue the batch and go to the Loop researcher. Global quota,
missing access or repairs requiring authority outside the frozen repair scope are
recorded as human blockers. Read [the routing policy](../experiment.md#evaluation-pipeline)
for scope and accounting. This applies to newly frozen implementations; historical
running campaigns do not change in place.

## Execution and isolation

The frozen protocol records its immutable image ID. The code shell inherits the
official AppWorld `execute` and `_shell_run_cell` methods unchanged, retaining
IPython variables, the official syntax/runtime guards, printed outputs and error
feedback. The native per-block guards are 100 seconds and 1,000 public API calls;
task interaction and output budgets are uncapped, while task-model requests
use a separately frozen 60-second generation-inactivity deadline for streaming
Chat Completions. Text, reasoning and tool-function deltas renew the watchdog;
heartbeats do not. Total generation can exceed 60 seconds. Partial streams are
recorded but never executed; recognized no-effect transient faults permit at most
three exact retries (four attempts total), then route to infra diagnosis. Responses requests
retain their whole-request deadline. Existing frozen attempts keep their original
transport; streaming is an explicit new model setting.

The shell is a separate non-root, read-only, networkless container with temporary
scratch space, no host mounts, no credentials, no task databases or ground truth,
and no executable evaluator. Its `apis.<app>.<api>(**parameters)` functions forward
public API requests over the host pipe to the existing trusted official AppWorld
world. The host validates public APIs and parameters, executes effects serially,
and persists state after every call. Exceptions retain the attempted prefix; there
is no replay or rollback. The official execution methods are reused, but API
transport and persistence are adapted for this isolation boundary; this is not a
claim of reproducing the complete official baseline agent implementation.

One Loop action now means one code block. Public `code-executions/code-NNNN.json`
records its exact code, output, internal API requests/results, effects and duration.
The tool result links to that execution ID and reports the API count; `result.json`
separately records total internal API calls. Internal responses enter model context
only when the code prints them. API receipts remain available for public trace
inspection. The shell and controller close before the unchanged host-side official
evaluator runs. Historical API-only trials remain archived. New research starts with a fresh
reactive baseline under the same code-shell condition as its candidates.
