# Continuous RSI experiment

Current research protocol, September 25, 2026. Improve reusable Python Loops on
five frozen official AppWorld training tasks. The user authorized a fresh start,
native code execution and continuous research with no fixed stopping round. The
September 24 revision switches task agents to FreeInference with a 60-second
request deadline and starts a fresh baseline; OpenCode records remain unchanged
and are not imported as research evidence. The September 25 revision adds automatic
fault routing, isolated infrastructure repair, oversized Jev segment recovery and
a streaming generation-inactivity timeout in place of the whole-request deadline
for newly frozen implementations. The current objective is prolonged unattended
AppWorld RSI and automatic failure recovery. Changes to inputs, outputs or protocol
automatically start a new condition rather than mix research evidence.
Telecom research remains stopped. Historical protocols and trial artifacts retain
their exact implementations and evidence in the local archive.

## Research cycle

Start with `controllers/reactive.py`, the only predefined complete Loop disclosed
to the researcher. Import no historical candidates, results or research notes.
Expose the frozen component contracts and API documentation, not alternative
complete Loop examples or a required branching policy.

1. Freeze the five training tasks, baseline source, component catalog, task model,
   native researcher, execution environments and limits. Run the baseline once on
   all five tasks, with official scoring and mandatory Jev analysis.
2. Inspect public evidence and propose a testable change to the Loop. Save one new
   candidate by default, at most two per iteration.
3. Evaluate every new source once on all five tasks, in the same admission order,
   with fresh task state and workers. Duplicate sources reuse their existing IDs
   and evidence; they cannot be evaluated again.
4. The host selects the best fully scored and analyzed candidate. Record the
   hypothesis, observations, failed approaches and next direction in research notes.
5. Checkpoint the iteration and continue. There is no fixed iteration count,
   success threshold or automatic stop after an unsuccessful candidate.

The researcher changes only ordinary Python composition of the approved
components: order, repetition, branches, evidence references and declared options.
Component prompts, schemas, models, tool interfaces and evaluators stay fixed.
Online Judge questions are editable within its frozen typed contract. New
component proposals require human review and a new library condition before use.
Task answers, research history and evaluator internals must not enter candidate
source or task-agent context. A new candidate is a reusable Loop, not a task script.

## Task set and scoring

Pin AppWorld `0.1.3.post1` and its official train split. Shuffle sorted scenario
families with seed `20260922`, then choose one variant per family. Freeze the first
five distinct scenarios in this order:

- `afc0fce_2`
- `771d8fc_1`
- `302c169_2`
- `692c77d_2`
- `29caf6f_2`

`protocol.json` owns the frozen selection, hashes and request settings. Preserve
exact task data, API documentation, base databases, dependencies and source code.
Before task-model dispatch, require every selected task to fail the full official
evaluator on an empty trajectory. Audit details and reference answers remain
private. The operator previously inspected first-task trials and a partial
second-task run on the seeded pilot selection. No uncontaminated selection or
holdout generalization claim is made. The fresh researcher receives none of those
traces, candidate sources, results or notes.

Each task uses its official instruction, supervisor, datetime, app descriptions
and public API helper documentation. There is no simulated user model. The tool
`appworld_execute(code)` uses a persistent isolated shell and the pinned official
AppWorld execution methods. Public API effects pass through the trusted official
world; task data, reference solutions and executable evaluators are outside both
the candidate worker and code shell. See the frozen task's tool contract for
syntax and the public code-execution receipts for internal API effects.

The controller and code shell close before the host runs the original official
evaluator. Public feedback contains the task verdict and aggregate check counts;
private evaluator details are not research evidence. Submission is not verified
completion. Every development task receives mandatory post-run Jev analysis before
batch feedback is released. Jev uses only public task and trace evidence and
never replaces official scores or proves a causal explanation.

## Evaluation pipeline

Task agents use FreeInference `deepseek-v4-flash`, Chat Completions, high
reasoning effort and the canonical component schema. Raw responses and
actual attempts are retained. Assistant history retains original parsed model
output; host metadata is separately labeled evidence. The researcher uses the
pinned native Codex distribution, with its separately frozen model and settings.
Jev retains its own fixed questions and transport. Analysis schema v11 keeps the
public AppWorld instruction in `task_goal` and splits provider-rejected oversized
groups into single observation cycles or tail reasoning calls. It preserves every
invocation and full evidence, retaining the rejected parent request and its usage.
Only leaf segments count toward measurement coverage. A rejected single cycle is
an infrastructure fault. Historical measurements are not rewritten. Version 11
adopts the two retained repairs: parse complete JSON embedded in observation text, and replace exact
repeated evidence with explicit JSON Pointer references. Original states and exact
wire requests are retained. Reconstructability does not establish equivalent Jev
labels; v11 is a new input condition, not a transparent v10 repair.

There is one evaluation lane. Each row completes task execution, official scoring
and Jev analysis before the next row starts. Candidate and task admission order is
frozen; researcher host requests are serial. No batch feedback is released until
all required task scores and analysis are present. Actions and internal API effects
within each task remain serial. Exceptions retain the attempted prefix, without
implicit replay or rollback.

`loopblox/research/failures.py` owns error routing. Ordinary task failures,
candidate errors and per-task budget exhaustion retain their official score and
analysis, then continue to the next task. The complete batch goes to the researcher;
these outcomes do not authorize reruns or increased budgets. Global budget/quota
and authentication failures require the missing resource. Unknown errors go to
infrastructure diagnosis, never silently to task failure. Online Judge input-size
rejection is a catchable `judge_input_limit` candidate error: no label is invented
and no dispatch cancellation occurs. Uncaught errors go through official scoring
and mandatory analysis before researcher feedback. Post-run Jev rejection remains
an infra fault. Internal cancellation is distinct from a user interrupt; cleanup
cannot replace the original error or prevent its ledger from being persisted.

Infrastructure, researcher, verifier or analysis faults close the episode before
further task dispatch. The serial supervisor then invokes an isolated native infra
worker with the failure, public trace evidence and frozen source. Jev is not needed
to classify its own failures. The worker proposes a source repair plus an offline
regression check, or identifies a missing resource or authority. It does not modify
candidate Loops. Repairs are restricted to the function bodies owned by
`loopblox/research/infra.py::EDITABLE`; signatures, other definitions and files remain
fixed. Checks run without network, credentials, benchmark execution or private
evaluator data. Rejected proposals return to the worker with their check results.
A passing check permits a new frozen implementation, never an edit to an existing
attempt or the operator's checkout. The host compares changed function bodies
against `PRESERVES_CONDITION` in the same module. Only explicitly allowed cleanup
edits recover the same condition; all other changes, including uncertain ones,
start from a fresh baseline and researcher without imported research evidence.
The repair worker cannot override this classification. Missing authority to
repair outside this scope requires human input. A model's repair and check are not
proof of correctness; the recovered attempt retains any subsequent failure.
If the repair worker itself cannot start, or repeatedly fails before returning a
diagnostic without a recognized transient code, record the missing runtime or
repair authority as a human blocker instead of indefinitely relaunching it.

## Limits and accounting

Task seconds, actions, model attempts and output tokens are uncapped (`null`).
Shared research time, task runs, model calls and output tokens are also uncapped.
Task-model requests have no client output cap. New FreeInference Chat Completions
requests use streaming with a 60-second generation-inactivity deadline, starting
at transport launch. Nonempty text, reasoning and tool-function deltas renew it;
heartbeats, roles, IDs and usage-only events do not. This host process watchdog
covers connection setup, headers and body reads. Continuous visible generation may
exceed 60 seconds in total. Hidden generation without emitted deltas cannot be
distinguished from a stalled request. Exact SSE data events, including partial
responses on timeout, are retained; only complete responses reach the Loop. Final
provider usage is requested and missing usage stays unknown. Streaming is frozen
as a model setting; existing campaigns retain their original transport. The
Responses adapter retains its whole-request deadline. A streaming-policy revision
starts a new condition; ordinary recovery requires identical frozen transport
settings and retry policy. A recognized no-effect timeout waits
two seconds and retries the exact request at most three times (four attempts
total), while budgets permit. The same retry cap applies to other recognized
no-effect transient faults; concurrency-limit retries wait sixty seconds. Failed
attempts and unknown usage remain recorded. Timeout request and retry-wait durations are
excluded from charged time under the existing gateway contract. Exhaustion routes
the original operational fault to infra diagnosis. Provider capacities and quotas
still apply. Native code
execution retains AppWorld's 100-second and 1,000-API-call per-block guards;
environment, analysis and isolation transport guards remain in effect.

Count a Loop action as one code block and record internal API calls separately.
Record exact attempts, raw usage, elapsed wall time and charged time. Missing
usage stays unknown and uncapped requests reserve no invented token allowance.
Gateway attempts, including online Judge and post-run Jev, share the research
ledger. Native researcher and infra-worker usage are recorded separately, with
missingness and coverage limitations explicit. Each repair's native calls and raw
events remain under the supervision directory; they are not charged again as task
calls. Dollar costs remain unknown without frozen prices.

## Selection and checkpoints

Rank fully scored, Jev-analyzed candidates on the same task set by:

1. Official passed-task count, descending.
2. Known total agent input tokens, ascending.
3. Agent model attempts, ascending.
4. Retain the incumbent on a full tie; otherwise use candidate creation order.

Unknown cost sorts after known cost. Incomplete batches cannot promote an
incumbent. The baseline becomes the initial incumbent only after its complete
batch. Improvement is not guaranteed at every iteration.

`checkpoint(notes)` requires every candidate saved in this iteration to have a
complete scored and analyzed batch. It preserves the sources, ranking, incumbent
change, notes and cumulative spend, then starts another iteration. There is no
researcher `select` or `finish` capability. Notes and scratch are researcher claims;
host records own outcome and usage counts.

Within one iteration, resume the exact recorded native Codex conversation after
each host request. A successful checkpoint starts a fresh conversation from the
notebook, latest checkpoint and public evidence. A rejected checkpoint retains
the current conversation. Every CLI invocation and container closes before the
host executes its request. Raw native token totals are cumulative per conversation;
derive invocation usage from successive reports in that conversation. Missing or
decreasing counters remain unknown. Infrastructure recovery uses a fresh session.

## Stopping and recovery

Continue until the user stops the campaign. SIGINT or SIGTERM interrupts the
active operation and waits for worker and usage cleanup. Preserve partial attempts
and the last fully evaluated incumbent. No final or test-split evaluation follows.

Continuous AppWorld launches automatically supervise recovery. An infrastructure
failure requires diagnosis and a new frozen output directory before recovery.
The infra worker may request an unchanged retry only for host-recognized transient
codes on their first occurrence, with a sixty-second cooldown (fourteen minutes for `service_not_ready`).
Deterministic faults require a changed, checked implementation.
For cleanup-only recovery, keep completed batches, sources and checkpoints
unchanged and restart only unfinished batches with fresh workers and a fresh
researcher. For an input/output or protocol change, use `--restart-from`: preserve
the same official tasks, models, budgets and isolation images, but run a new
baseline with no imported candidates, labels, notes or checkpoints. The new
implementation includes accumulated repairs; `restart_from` records provenance
without carrying prior research into the new condition. Retain failed attempts privately for cumulative accounting, not as
research feedback. Record and freeze any justified repair and its provenance.
All existing spend remains recorded; this condition's null budgets impose no
finite remaining allowance. Do not reinterpret an ordinary task failure or a user
stop as an infrastructure fault. A recorded `service_not_ready` failure requires
at least fourteen minutes between closure and recovered dispatch. Recovery must
respect user pauses and cannot authorize test dispatch.

Fault fingerprints, source changes and check results persist across conditions.
A recurring fault requires new diagnosis and a revised repair; the supervisor
rejects unchanged retries and previously checked identical repairs for that fault.
Passing an offline check is not evidence of successful unattended recovery.

The sibling `<initial-output>-supervision/state.json` records the supervisor PID,
active child PID, attempt directories, repair directories and any required human
action. SIGINT or SIGTERM to the supervisor stops its active child and cleanup,
including during a repair or cooldown. It never interprets a user stop as failure.
The supervisor runs under the initial frozen implementation. Each repair and each
recovered child records its own source provenance; completed records stay immutable.

## Implementation and records

`loopblox/benchmarks/run_appworld.py` freezes and dispatches the task set and
implementation. `ResearchSession` owns the existing continuous research lifecycle:
baseline, candidates, evaluations, selection, checkpoints and native researcher.
`AppWorldRunner` supplies fresh worlds and host-only official scoring. There is no
separate research engine. Frozen children import only their implementation copy.

Root `protocol.json` and `result.json` describe the run. Under `evaluation/public`,
`progress.json` reports iterations and incumbent; `candidates`, `evaluations`,
`notes.md` and `checkpoints` retain public evidence. Private native and gateway
ledgers retain their respective costs. Setup and launch commands live in
[docs/appworld.md](docs/appworld.md).
