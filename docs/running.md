# Running continuous Loop research

Updated September 21, 2026. This guide covers environment setup, task preparation,
commands and output files for τ²-bench telecom research. [experiment.md](../experiment.md)
defines the [task set and scoring](../experiment.md#task-set-and-scoring),
[limits and accounting](../experiment.md#limits-and-accounting),
[selection and checkpoints](../experiment.md#selection-and-checkpoints), and
[stopping and recovery](../experiment.md#stopping-and-recovery).

Run all commands from the repository root. Complete the
[README setup](../README.md#quick-start) and start Docker first. Inspecting the
component catalog and preparing the task suite do not call models. Task execution,
native research and Jev analysis consume their configured services' quota.

## Host configuration

Core host modules use the standard library. The τ² entry point uses the pinned
Python 3.12 benchmark environment prepared below; candidate Loops run in Docker
workers. Configure the model through `FREEINFERENCE_API_KEY`,
`FREEINFERENCE_BASE_URL` and `FREEINFERENCE_MODEL` in the ignored local `.env`.

Research also requires [Jev setup](jev.md): `TYPESAFE_API_KEY` and
`typesafe-sdk==0.7.0`, optionally in a separate host interpreter selected by
`LOOPBLOX_JEV_PYTHON`. Loops using the optional `judge` component require the same
setup for standalone task runs and the local playground. See
[Judge usage](../CONTROLLER.md#judge-online-typed-judgments) for its API.

To use OpenCode Go, set `LOOPBLOX_PROVIDER=opencode_go` and `OPENCODE_GO_API_KEY`
in `.env` or the process environment. Its defaults are
`https://opencode.ai/zen/go/v1` and `glm-5.1`; [.env.example](../.env.example)
lists optional overrides. Choose a model with a Chat Completions endpoint from
the [Go documentation](https://opencode.ai/docs/go/#endpoints).
The default provider is `freeinference`.

## Native Codex researcher

Configure these values in the local `.env` or process environment:

| Setting | Value |
| --- | --- |
| `LOOPBLOX_CODEX_BINARY_ROOT` | Required path to the pinned **Linux Codex 0.155.0** distribution containing `bin/codex` and its stock Code Mode host. Use the distribution matching the container architecture. |
| `LOOPBLOX_CODEX_MODEL` | Optional; defaults to `gpt-6-astra`. |
| `LOOPBLOX_CODEX_REASONING_EFFORT` | Optional; defaults to `low`. |
| `LOOPBLOX_CODEX_AUTH_FILE` | Optional path to an existing ChatGPT subscription login; defaults to `$CODEX_HOME/auth.json`, or `~/.codex/auth.json` when `CODEX_HOME` is unset. |

Codex uses the ChatGPT subscription login; API-key authentication is rejected.
The task model and simulated user use the configured model gateway. Local
preflight checks the native binary and login format before task dispatch; online
authentication or subscription failures can still occur later. Credentials are
not copied into frozen evidence.

## Prepare the benchmark environment and task suite

```sh
git clone https://github.com/sierra-research/tau2-bench .artifacts/upstream/tau2-bench
git -C .artifacts/upstream/tau2-bench checkout 672227c6b6676edc20d57ea53b7000262aae77b9
uv sync --project .artifacts/upstream/tau2-bench --frozen --no-dev
docker pull python:3.12-slim

# Freeze an audited task suite
.artifacts/upstream/tau2-bench/.venv/bin/python -B -m loopblox.benchmarks.run_tau2 \
  prepare --output .artifacts/tau2/telecom-suite-NEW --seed 20260921
```

Use a new output directory. `--seed` is required; the command above supplies an
example value. Add `--exclude-suite PATH` for each prior suite whose exposure must
be recorded. The [task selection rules](../experiment.md#task-set-and-scoring)
define how those reservations affect the new suite.

`prepare` writes `manifest.json`, `selection.json`, `audit.json`, `versions.json`
and the frozen upstream files. It does not start research or execute task Loops.

## Run, stop and recover

After configuring the model gateway, Jev, Docker and native Codex:

```sh
# Freeze code, task suite and settings, then start the continuous researcher
.artifacts/upstream/tau2-bench/.venv/bin/python -B -m loopblox.benchmarks.run_tau2 \
  run --suite .artifacts/tau2/telecom-suite-NEW --output .artifacts/tau2/research-NEW

# Read live state and refresh report.md / status.json
python3 -B -m loopblox.benchmarks.run_tau2 status --output .artifacts/tau2/research-NEW

# Request a stop
python3 -B -m loopblox.benchmarks.run_tau2 stop --output .artifacts/tau2/research-NEW
```

`run` stays in the foreground and starts a child from the frozen implementation.
Use a new output directory. Ctrl-C also requests a stop and waits for cleanup.
Use a second terminal for `status` or `stop` while `run` is active.

After diagnosing a failure, check the
[recovery conditions](../experiment.md#stopping-and-recovery), then recover into
a new directory with the diagnosis or repair recorded in `--reason`:

```sh
.artifacts/upstream/tau2-bench/.venv/bin/python -B -m loopblox.benchmarks.run_tau2 \
  recover --previous .artifacts/tau2/research-FAILED \
  --output .artifacts/tau2/research-RECOVERED \
  --reason "Describe the diagnosed fault, new evidence or implementation repair"
```

`recover` starts the new attempt in the foreground. Its eligibility checks,
waiting conditions, retained evidence and accounting follow the linked protocol.

## Inspect campaign outputs

Paths below are relative to the campaign's output directory. Run `status` to
refresh the derived report and usage summary.

| Path | Contents |
| --- | --- |
| `protocol.json` | Frozen task IDs, settings, limits and implementation hashes. |
| `report.md` / `status.json` | Current state, iteration history and cumulative usage. |
| `research/selected-controller.py` | Current fully evaluated Loop, once available. |
| `research/public/progress.json` | Incumbent, pending candidates and iteration count. |
| `research/public/evidence.json` | Candidate outcomes and links to recorded evidence. |
| `research/public/checkpoints/` | Completed iteration records and notes. |
| `research/public/evaluations/` | Batch results, task traces and Jev evidence. |

## Component catalog and execution reports

```sh
# Export the current full component catalog
python3 -B -m loopblox.runtime.components

# Regenerate readable contracts from the same definitions
python3 -B -m loopblox.runtime.components --markdown > COMPONENTS.md

# Generate a read-only report from an existing trace
python3 -B -m loopblox.report path/to/trace.json --output path/to/report.html
```

[COMPONENTS.md](../COMPONENTS.md) lists component contracts.
[CONTROLLER.md](../CONTROLLER.md) explains composition, task execution and the
researcher API.
