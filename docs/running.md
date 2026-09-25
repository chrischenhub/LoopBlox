# Running continuous Loop research

For the active five-task AppWorld continuous experiment, see [AppWorld setup](appworld.md).
The telecom commands below describe the retained, currently stopped integration.

Updated September 21, 2026. This guide covers environment setup, task preparation,
commands and output files for the retained τ²-bench telecom integration. Historical
campaign snapshots own their telecom protocols. The active
[experiment.md](../experiment.md) now defines the AppWorld research condition.

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

The task model adapter explicitly requests high reasoning effort for both agent
components and simulated-user calls: `reasoning_effort: "high"` on Chat
Completions, or `reasoning.effort: "high"` on Responses. This fixed setting is
recorded in campaign model settings; it does not configure Jev or the native
researcher. Historical frozen campaigns retain their original settings.

Start a full No-user campaign with `run --no-user`. `Tau2Runner(..., solo_mode=True)` uses the
official task ticket, combined agent/user tool set, DummyUser, solo orchestrator
and official solo evaluator. The existing isolated Loop worker still owns task
execution. This path currently requires a ticket and no initial message history;
it exposes `done` instead of `respond_to_user` and makes no simulated-user model
calls. The campaign freezes `solo_mode: true` and `user_model: null`, checks all
ten training tasks before dispatch, and gives the researcher the frozen mode in
its research question. Recovery inherits the mode. Without `--no-user`, new
campaigns use the interactive simulator. No-user results are a separate condition
and must not replace interactive results. New gateway requests ask the provider to
retain reasoning in the recorded raw response for diagnosis; structured component
outputs still come from the response body.

Structured component requests disclose the same canonical output schema in the
model messages and the API response format. Both derive from the supplied schema;
the host validates that original contract. This avoids relying on the provider's
constrained decoder alone to explain completion fields to the reasoning model.

Research also requires [Jev setup](jev.md): `TYPESAFE_API_KEY` and
`typesafe-sdk==0.7.0`, optionally in a separate host interpreter selected by
`LOOPBLOX_JEV_PYTHON`. Loops using the optional `judge` component require the same
setup for standalone task runs and the local playground. See
[Judge usage](../CONTROLLER.md#judge-online-typed-judgments) for its API.

To use OpenCode Go, set `LOOPBLOX_PROVIDER=opencode_go` and `OPENCODE_GO_API_KEY`
in `.env` or the process environment. Its defaults are
`https://opencode.ai/zen/go/v1` and `muse-spark-1.3-contributor`;
[.env.example](../.env.example) lists optional overrides. This Muse model uses
Responses with high reasoning effort. Component outputs use JSON mode plus the
canonical schema in a fixed format instruction; host schema validation remains
mandatory before execution. This mode avoids the terminal-placeholder behavior
observed with Muse's schema-constrained output path. The transport mode is frozen
with the model settings and requires a fresh baseline when changed.
Simulator calls use native tools (`auto` selection, as used by τ²).
Other configured models retain Chat Completions transport;
check the [Go endpoints](https://opencode.ai/docs/go/#endpoints) before selecting one.
Responses has no generation seed parameter. Official environment seeds remain
frozen, but simulator generations on this API are not seeded.

New OpenCode campaigns freeze **three concurrent evaluation lanes**; FreeInference
freezes **one**. Each lane runs a fresh task, official scoring and mandatory Jev
analysis. Batch feedback is released only after every lane completes. The provider
policy is owned by `campaign.evaluation_workers`; it is not a claim about the
provider's maximum concurrency. Two overlapping Muse requests succeeded in the
September 22, 2026 local probe; the Go docs do not publish a concurrency ceiling.
The default provider remains `freeinference`. Changing the provider/model requires
a fresh campaign and a new baseline, not recovery of an existing campaign.

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
# Freeze a No-user condition, evaluate a fresh baseline, then start the researcher
.artifacts/upstream/tau2-bench/.venv/bin/python -B -m loopblox.benchmarks.run_tau2 \
  run --no-user --suite .artifacts/tau2/telecom-suite-NEW --output .artifacts/tau2/research-NEW

# Read live state and refresh report.md / status.json
python3 -B -m loopblox.benchmarks.run_tau2 status --output .artifacts/tau2/research-NEW

# Request a stop
python3 -B -m loopblox.benchmarks.run_tau2 stop --output .artifacts/tau2/research-NEW
```

`run` stays in the foreground and starts a child from the frozen implementation.
Use a new output directory. Ctrl-C also requests a stop and waits for cleanup.
Use a second terminal for `status` or `stop` while `run` is active.

For an infrastructure fault requiring diagnosis, add `--diagnostic-reason` with
a concrete explanation to the stop command. This retains worker cleanup and
records an infrastructure failure eligible for recovery. Plain `stop` and Ctrl-C
remain user pauses and cannot be automatically recovered. A diagnostic request
cannot replace an existing stop request.

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
Only after the user explicitly requests resumption, add `--resume-stopped` to
recover a stopped campaign, recording the request in `--reason`. This preserves
the original stop record and all budget deductions; it does not resume an old
worker or reset its allowance.

Only when the user explicitly authorizes a complete, full-budget restart of an
unfinished candidate, add `--restart-candidate c0006` and record that authorization
in `--reason`. This restarts all that candidate's tasks with the original per-task
caps while preserving completed batches and all historical spend. Subsequent
ordinary recovery deducts attempts since this restart; it does not reset again.

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

New campaign implementations retain the full provider response in each structured
model turn's `raw` field, including the response ID, reported model and finish
reason when supplied. The parsed component value remains in `output`. A returned
request can still fail component validation: `result.json` aggregates failure codes
from gateway attempts and task records without changing request usage or status.
Historical frozen campaigns retain their original recording behavior.

Assistant history replays only the original parsed model output. Host metadata
(including invocation IDs, component and scope) is supplied separately as a user
message identifying the following historical output; it is not an assistant turn.

## Component catalog and execution reports

### Live research dashboard

Run this from the current repository checkout in a separate terminal:

```sh
python3 -B -m loopblox.research.dashboard

# Monitor one AppWorld campaign
python3 -B -m loopblox.research.dashboard .artifacts/appworld/research-NEW --port 8767

# Or monitor one collection, including historical telecom campaigns
python3 -B -m loopblox.research.dashboard .artifacts/tau2 --port 8767
```

Open [http://127.0.0.1:8767/](http://127.0.0.1:8767/). The local server needs only
Python's standard library. Keep its terminal open; Ctrl-C closes the dashboard
independently of the experiment. It binds only to the local computer and has no
experiment controls or model calls. Frozen campaigns are never modified.
The dashboard follows the website's ink-green palette and pixel typography, using
the tracked LoopBlox logo and bundled fonts. These assets are served locally from
the repository; the monitor does not depend on `site/` or remote font services.

The default directory is `.artifacts/`; discovery checks immediate campaigns in
its `appworld/` and `tau2/` collections, plus direct `attempt-*` children of
AppWorld `*-supervision/` directories. It does not traverse arbitrary nested
directories. You can also pass one campaign or one collection directory explicitly.
**Follow live experiment** detects AppWorld and telecom research hosts and AppWorld
supervisors by validating their recorded local PIDs against the matching process.
For supervised runs, it follows the supervisor's recorded current-attempt pointer;
while a new attempt is being prepared, the last available attempt remains visible.
A live supervisor can keep the research marked live during repair or retry wait
even when the preceding task attempt has closed. A newer unrelated stopped or
prepared campaign does not displace a live one. When no live host or supervisor is
detected, the page says so and shows the latest recorded campaign. Process presence
confirms liveness, not progress.
Choose a specific attempt in the selector to keep it fixed. Archived directories
are outside default discovery. **Explore Loops** jumps to the integrated **Loop evolution**
section on the same page. It uses the generic visualizer's candidate comparisons,
source validation and recorded execution diagrams. Choose a task to compare the
same task across every Loop, then expand Python source, source changes, exact path
order or task outcomes. The task selection stays fixed while that campaign updates;
switching campaigns resets it to the first recorded task. Open disclosures and
diagram scroll positions survive refreshes. Standalone HTML export remains
available with the visualization command below.

**Dashboard** is the home page. The **Research** tab at `/research` summarizes the
selected campaign's research question, candidate history, recorded outcomes and
research notebook. All three tabs retain the campaign selection and follow-live mode.
When the displayed attempt belongs to the current supervised run, all three tabs show
the supervisor phase, process presence, repair count and any recorded required
action above the task attempt. Repair and retry wait share a recorded state and
are labeled together; the dashboard does not infer which is happening. Closed
attempt outcomes remain closed while supervision continues. The selector names
nested attempts as their original run and attempt name; selecting a historical
attempt fixes that view and does not attach the current supervisor's status to it.
Their campaign header identifies the benchmark, frozen task count and task
interface from that campaign's records. AppWorld native code-shell runs count
submitted code blocks; a block may make multiple API calls. Historical telecom
runs continue to show actions, and each campaign uses its own recorded task set.
The Research page distinguishes mandatory post-run Jev analysis from optional
online `judge` invocations, and shows analysis coverage alongside the researcher's
recorded evidence references. Notes and hypotheses remain attributed researcher
claims; Jev measurements do not replace official scores or establish why a change
worked. Its history covers the public records in the selected campaign, including
inherited completed evaluations, while cumulative gateway usage still includes prior
recovery attempts. The page summarizes existing evidence without additional model
calls.

The **Trace** tab at `/trace` joins one candidate's recorded task run to its Jev
segments. Choose a candidate, task and run, or use **Inspect trace** in the
Dashboard's task table. Without an explicit selection, it follows the latest
available analysis. Three linked plots show segment progress, immediate action
effectiveness and the probability that the approach needs correction. Progress
is per segment, not cumulative completion; correction need is not recovery
success. Axes use that run's recorded question scales, so historical schemas
retain their own ranges. Missing measurements leave gaps and remain selectable.

Segment order follows recorded leaf order, excluding split parent records;
numeric record IDs may be nonsequential after splitting. Click a plotted point,
use arrow keys while a point is focused, or choose a segment from the selector
to inspect its measurements and public evidence. The inspector preserves exact
Jev responses, full segment evidence, recorded request attempts and component
invocations in expandable disclosures. Encoded request inputs remain separate
from original segment evidence. A pinned whole-task result shows Success, Failure
or Not scored while browsing the plots and segment evidence. Success and Failure
come only from the official evaluator; unfinished or interrupted runs without a
score remain Not scored. Jev segment completion is labeled separately.
Selection and open disclosures survive live refreshes; pending
analysis shows a waiting state rather than invented measurements.

The page refreshes every three seconds. Connection status means the monitor is
reachable; campaign state and the recorded local host process are shown separately.
Last recorded activity is a file timestamp, not a heartbeat or proof of progress.
A completed trace without a task result is shown as scoring / cleanup; those stages
cannot be separated from the available records. Task completion, official scoring
and mandatory Jev completion have separate counts. Incomplete or interrupted
batches retain their missing scores and never qualify as evaluated.

Candidate comparisons use the recorded agent usage and host-selected incumbent.
Campaign gateway usage derives from the selected benchmark's recorded accounting
to include failed recovery attempts once, with wall time separate from charged
time. Native researcher usage is displayed separately: AppWorld shows the current
attempt's recorded native tokens, excluding prior attempts; telecom retains its
recorded cumulative native usage. Supervisor infrastructure-repair usage remains
separate from the displayed task, Jev and native researcher totals; it is not
assumed to be zero. Missing token measurements and charged duration
remain unknown until recorded. AppWorld start time falls back to the host start
record's modification time when no start timestamp was saved; wall duration is
unknown for closed records without a closing timestamp. The server projects
only aggregate accounting from private ledgers; it never serves their request
bodies, simulator data or credentials. It reads records directly rather than the
on-demand `status.json` report. Files are read individually, so a refresh can span
a host transition; a read error keeps the last successful view with a warning.

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
