# Running continuous Loop research

Updated September 21, 2026. This guide covers environment setup, task preparation,
commands and output files for τ²-bench telecom research. [experiment.md](../experiment.md)
defines the [task set and scoring](../experiment.md#task-set-and-scoring),
[limits and accounting](../experiment.md#limits-and-accounting),
[selection and checkpoints](../experiment.md#selection-and-checkpoints), and
[stopping and recovery](../experiment.md#stopping-and-recovery).

Run all commands from the cloned repository root, with Git, Python 3.12, uv,
curl, tar, and Docker Engine available. Use a macOS or Linux host, or WSL2 with
Docker access. Follow the sections below in order. Inspecting the
component catalog and preparing the task suite do not call models. Task execution,
native research and Jev analysis consume their configured services' quota.

## Install the host dependencies

Start Docker, then install the benchmark from its pinned source and lockfile:

```sh
git clone https://github.com/sierra-research/tau2-bench .artifacts/upstream/tau2-bench
git -C .artifacts/upstream/tau2-bench checkout 672227c6b6676edc20d57ea53b7000262aae77b9
uv sync --project .artifacts/upstream/tau2-bench --frozen --no-dev --python 3.12
docker pull python:3.12-slim
```

Install Jev in a separate environment so the benchmark's locked dependencies stay
intact:

```sh
uv venv --python 3.12 .artifacts/venvs/jev
uv pip install --python .artifacts/venvs/jev/bin/python 'typesafe-sdk==0.7.0'
.artifacts/venvs/jev/bin/python -B -m loopblox.runtime.jev describe

# Copy the printed assignment into .env
python3 -c 'from pathlib import Path; print("LOOPBLOX_JEV_PYTHON=" + str(Path.cwd() / ".artifacts/venvs/jev/bin/python"))'
```

Keep that virtualenv entry-point path; do not resolve its symlink to the underlying
Python binary. The benchmark interpreter runs research and tasks; the Jev
interpreter handles typed judgments. `describe` should report SDK version `0.7.0`
without calling a model. No LoopBlox package installation is required.

## Host configuration

Core host modules use the standard library. The τ² entry point uses the pinned
Python 3.12 benchmark environment prepared below; candidate Loops run in Docker
workers. Configure the model through `FREEINFERENCE_API_KEY`,
`FREEINFERENCE_BASE_URL` and `FREEINFERENCE_MODEL` in the ignored local `.env`.
Create it with `cp .env.example .env` on first setup, then edit the values.
Use literal absolute paths: this loader does not expand shell variables in `.env`.
Existing process environment variables take precedence over the file.

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

### Download the pinned Linux distribution

The researcher runs inside a Linux container, including on macOS. Use the
**complete Linux 0.155.0 distribution** for the worker image's architecture;
the host's macOS executable or npm launcher alone is insufficient. The official
[Codex CLI guide](https://learn.chatgpt.com/docs/codex/cli) documents npm
distribution. The pinned platform archives are
[Linux ARM64](https://registry.npmjs.org/@openai/codex/-/codex-0.155.0-linux-arm64.tgz)
and [Linux x64](https://registry.npmjs.org/@openai/codex/-/codex-0.155.0-linux-x64.tgz).
The following commands download and extract the matching package without a Node.js
installation:

```sh
case "$(docker run --rm --network none python:3.12-slim uname -m)" in
  aarch64|arm64) codex_arch=arm64; codex_target=aarch64-unknown-linux-musl ;;
  x86_64|amd64) codex_arch=x64; codex_target=x86_64-unknown-linux-musl ;;
  *) printf '%s\n' 'Unsupported Docker architecture' >&2; exit 1 ;;
esac

codex_dir="$PWD/.artifacts/tools/codex-0.155.0-linux-$codex_arch"
mkdir -p "$codex_dir"
curl --fail --location --retry 3 \
  "https://registry.npmjs.org/@openai/codex/-/codex-0.155.0-linux-$codex_arch.tgz" \
  --output "$codex_dir/package.tgz"
tar -xzf "$codex_dir/package.tgz" -C "$codex_dir"
export LOOPBLOX_CODEX_BINARY_ROOT="$codex_dir/package/vendor/$codex_target"

# Both executables are required; retain the package's resource directories too
test -x "$LOOPBLOX_CODEX_BINARY_ROOT/bin/codex"
test -x "$LOOPBLOX_CODEX_BINARY_ROOT/bin/codex-code-mode-host"
docker run --rm --network none \
  --mount "type=bind,src=$LOOPBLOX_CODEX_BINARY_ROOT,dst=/opt/codex,readonly" \
  python:3.12-slim /opt/codex/bin/codex --version

# Copy the printed assignment into .env for future terminals
printf 'LOOPBLOX_CODEX_BINARY_ROOT=%s\n' "$LOOPBLOX_CODEX_BINARY_ROOT"
```

The version command must print `codex-cli 0.155.0`; it makes no model request.
Keep the full `vendor/<target>` directory, including `codex-resources` and
`codex-path`. LoopBlox freezes and hashes its contents before research. An
architecture error usually means a host executable or the wrong Linux package
was supplied; inspect the worker image's `uname -m` output again.

### ChatGPT login

Reuse an existing ChatGPT subscription login in `auth.json`. If you do not have
one, install the host-native CLI using the
[official installation guide](https://learn.chatgpt.com/docs/codex/cli), then run
on the host:

```sh
codex -c 'cli_auth_credentials_store="file"' login
codex -c 'cli_auth_credentials_store="file"' login status
```

Complete the ChatGPT sign-in flow. File storage is required by this adapter;
an OS-keychain-only login does not provide its `auth.json` input. For a headless
host, use `login --device-auth` if enabled for your account. See the official
[authentication guide](https://learn.chatgpt.com/docs/auth#login-caching) for
credential storage and headless sign-in. The host CLI here establishes a login;
research always uses the separate pinned Linux distribution above.

Keep the login file outside this repository. Set `LOOPBLOX_CODEX_AUTH_FILE` only
when it is stored somewhere other than the default location below. Choose a
research model available to your account before starting a new campaign; recovery
retains the campaign's frozen model and settings.

### Configuration and preflight

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

The [research protocol](../experiment.md#selection-and-checkpoints) defines one
native conversation per iteration. The host uses
[`codex exec resume <session_id>`](https://learn.chatgpt.com/docs/non-interactive-mode#resume-a-non-interactive-session)
within that iteration and starts a new session after a successful checkpoint.
Every invocation receives the latest host receipt; older receipts remain in
`/exchange/receipts`. Native trace entries record `resumed_session_id` and
`session_id`, so continuation and iteration boundaries can be inspected.
`session_usage` retains the CLI's cumulative token report; `usage` contains the
derived invocation usage used in campaign totals.

## Prepare the benchmark environment and task suite

With the benchmark environment installed above, freeze an audited task suite:

```sh
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

### Visualize a research campaign

Generate a standalone HTML report from any campaign using the current continuous
research protocol. This tool is independent of the promotional website in `site/`.
It reads existing public records, makes no model calls, and does not execute or
modify candidates, evaluations or campaign state.

```sh
python3 -B -m loopblox.research.visualize .artifacts/tau2/research-NEW \
  --output .artifacts/visualizations/research-NEW.html
```

Open the resulting HTML in a browser. No server or additional Python packages are
required. The input may also be the campaign's `research/` or `research/public/`
directory. Keep the output outside the campaign to preserve its frozen records.
Run the command again to update the static snapshot while research is running.
The report supports any number of iterations and both candidates in a round.
Archived protocols are not imported or silently converted.

Candidate cards show recorded selection, official task outcomes, agent input tokens
and model attempts, saved rationale, Python source and changes relative to the
incumbent at the start of that round. The source comparison is not a parentage claim.
Missing scores, unknown usage, incomplete evaluations and missing traces remain
explicit; the report never substitutes its own selection for the host's incumbent.
Only fully released evaluation feedback qualifies for the evaluated label.

Each diagram uses the same task across candidates: the first recorded task by
default, or an explicit task selected with `--task telecom-development-0004`.
Diagrams derive from actual root component invocations, grouped at observations
using that trace's frozen component contracts. They retain repeated component names within paths,
display observed transition counts and highlight component names absent from the
comparison trace. Expand **Exact path order** to inspect the recorded sequence.
Grouping equal component/status sequences does not imply equal arguments, equal
results or stalled progress. The diagram does not parse arbitrary Python into a
control-flow graph, invent unexecuted branches, or infer source-code conditions.

Scores and costs cover the whole recorded candidate evaluation; diagrams and
invocation counts cover only the displayed task. Agent costs exclude simulated
users, post-run Jev and researcher usage. Prior interrupted recovery attempts are
not added to candidate totals. Research notes and the saved rationale remain
researcher claims, separate from host-derived observations. The embedded snapshot
records file hashes and exact invocation IDs for provenance. A running campaign's
files are read individually, so this is a read-time snapshot, not a transaction
across the entire experiment.

### Inspect individual component calls

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
