# Continuous RSI experiment

Current research protocol, September 22, 2026. Run and improve Loops on one frozen
benchmark and task set. This document defines the experiment rules.
[running.md](docs/running.md) provides environment setup, commands and output paths.

Start a fresh campaign without importing historical results, candidates or research
notes. The researcher iteratively improves the task Loop; model weights and the
approved component library remain fixed.

The supplied reactive baseline is the only predefined complete Loop disclosed to
the researcher. Provide the component contracts, API syntax and permitted evidence
from this campaign. Human-facing repository examples are not exported; guides
must not introduce additional complete Loops or require their design mechanisms.

1. Freeze ten official telecom training tasks, the baseline, components, model
   settings and execution limits. Run the baseline once on all ten tasks, with
   official scoring and Jev analysis. Select it as the initial incumbent.
2. Inspect outcomes, traces and accumulated research notes. Form a testable
   modification to the incumbent or a useful previously explored candidate.
3. Save **one new candidate by default, at most two per iteration**. Evaluate each
   on the same ten tasks with fresh environments and unchanged task limits.
4. Compare task success and cost, and check whether the intended mechanism fired.
   Keep the best evaluated Loop. Record the hypothesis, evidence, failed approaches
   and next research direction; carry this experience into the next iteration.
5. Return to step 2. There is **no fixed iteration count**. Uncertain benefit or
   a failed candidate does not end research. If no candidate is ready, continue
   analysis and hypothesis revision.

Checkpoint after every iteration; a checkpoint does not finish research. Avoid
rerunning unchanged sources. Continue until the user stops the campaign.
Infrastructure faults close the affected episode and follow the recovery policy,
preserving all attempts and spend.

## Task set and scoring

Use the pinned τ²-bench telecom data. The official train split has 74 tasks:
66 require environment assertions alone and eight also require action checks.
The official test split has 40 tasks: 28 require environment assertions alone
and 12 also require action checks. Neither split requires model-based grading.
The pinned task files and official split membership determine eligibility.

Select ten training tasks with one representative per eligible family, stratified
by issue category and fault count using the frozen seed. Exclude reserved families,
families overlapping official test, tasks requiring action checks and tasks that
pass on an empty trajectory. Reservation manifests record prior suite membership,
not proof of execution. Preserve selection, exclusions, seed and exposure in the
suite audit. Freeze every official test task in its original order and with its
original scoring criteria; prior exposure is recorded even when a test task is
retained. Test tasks stay outside the research loop. Any final evaluation requires
separate review and authorization.

Every run uses fresh official environment/user state and an isolated controller
worker. Retain the official policies, tools, conversation state machine, simulated
user and evaluator. The controller receives the domain policy, agent tool schemas
and messages addressed to it. Private user scenarios, user-tool trajectories,
reference actions and evaluator internals remain unavailable to the researcher.
The campaign uses the same model for the agent and simulated user, with user
temperature 0; freeze both client configurations.

Official scoring starts after the task worker closes and retains
`EvaluationType.ALL`, including action checks where required. Task-budget
exhaustion does not prevent deterministic scoring. Verifier failures retain
missing scores and their cause; they never become fabricated task outcomes.
The selected development tasks do not comprehensively measure communication
quality or policy compliance. Reused development results do not establish
holdout or causal improvement.

## Evaluation pipeline

The September 22 revision supports three evaluation lanes for OpenCode Go and one
for FreeInference. Freeze the lane count, model and API with the campaign. The
requested Muse model is `muse-spark-1.3-contributor` on Responses, with high
reasoning effort. Agent and simulator use this model; native Codex research and
Jev keep their existing roles. Responses does not support a generation seed;
retain official task seeds without claiming seeded simulator sampling.

Muse component calls use Responses JSON mode, with the canonical component schema
included as a fixed format instruction and validated by the host before execution.
The instruction distinguishes historical evidence envelopes from the component
result to return; host-assigned record fields are not output-format examples.
Assistant history contains only the original parsed model output for every
provider. Host record metadata is supplied separately as labeled evidence for the
following output, preserving IDs, component, scope and order. Native simulator message roles retain their
original meaning. Freeze and disclose this request-format repair during recovery.
Freeze this mode as `model.structured_output`. Changing this mode defines a new
transport condition: retain previous records, then start a fresh campaign and
baseline. Do not import the previous condition's research notes or attribute
cross-condition score changes to Loop composition. Simulator native tool calls
and component contracts remain unchanged.

Admit rows in the frozen task/candidate order, keeping row IDs and report order
independent of completion order. Each lane owns a fresh environment, simulator,
controller worker and task ledger. It completes official scoring and Jev analysis
before admitting another row. Researcher requests remain serial; the researcher
receives no batch feedback until every row has an official score and analysis.
An infrastructure or analysis fault stops admission and cancels in-flight lanes,
waiting for their cleanup and retaining partial records and all reserved usage.
User interruption follows the same cleanup path. Actions within a task stay serial.

Use one locked research ledger for admission and costs. Timeout exclusions remain
per-attempt facts. Shared wall-time exclusion counts only intervals during which
all active lanes are in recognized no-effect timeout requests or their retry waits;
concurrent productive work remains charged. Task charged time retains its own
exclusions. A provider/model or concurrency change starts a new campaign and
baseline; completed evidence from the paused campaign is not imported.

## Limits and accounting

The accepted per-task limits are 900 charged seconds, 60 actions, 256 combined
agent/user model attempts and 65,536 output tokens, owned by
`loopblox/research/campaign.py::TASK_LIMITS`. Shared research time, task runs,
model calls and output tokens are uncapped (`null`); native researcher usage
remains a separate ledger. Finite shared model-call or output-token caps cannot
cover native and gateway usage accurately and are rejected by this protocol.
Per-request deadlines and task limits still apply.

The action limit counts controller-issued actions; user tools are bounded by the
official state machine and its additional step cap. Agent and simulated-user
calls share the task ledger. Online Judge calls also consume task allowance;
mandatory post-run Jev analysis uses the research ledger after the task closes.
Keep usage by role, actual attempts, failed-call costs and unknown measurements.
Dollar cost remains unknown unless unit prices are frozen.

Report wall time and charged time separately. Gateway retry and timeout accounting
follow [the execution contract](CONTROLLER.md#decisions-and-termination).

## Selection and checkpoints

The host ranks fully scored, Jev-analyzed candidates on the same ten tasks by:

1. Official passed-task count, descending.
2. Known total **agent input tokens**, ascending.
3. Agent model attempts, ascending.
4. Keep the current incumbent on a full tie; otherwise use candidate creation order.

Unknown cost sorts after known cost and never becomes zero.
Jev judgments do not change official scores. Incomplete
batches cannot promote an incumbent, and ordinary failed tasks remain scored
results. The baseline becomes the initial incumbent only after its full batch.
Continuous research does not guarantee improvement at every iteration.

`save_candidate` admits at most two new sources before the next checkpoint.
Duplicate saves return the original ID and rationale. `evaluate(candidate_ids)`
runs each requested new source once on the whole task list. It rejects sources
that already have an evaluation. The host updates the incumbent after every
complete batch; there is no researcher `select` or `finish` tool.

`checkpoint(notes)` requires all candidates saved in this iteration to have
complete scored and analyzed batches. It writes an immutable iteration record
with the sources, ranking, incumbent change, notes and cumulative gateway spend,
then opens the next iteration. Notes should cover the hypothesis, evidence,
failed approaches and next direction. `write_notes` remains available for work
in progress. Checkpoints and public evidence carry experience within this campaign.

The native researcher uses one Codex conversation per iteration. After each host
request, its next CLI invocation resumes the exact recorded session and receives
the request's receipt. A successful checkpoint ends that conversation; the next
iteration starts a new session from the notebook, latest checkpoint and public
evidence. A rejected checkpoint does not change sessions. Each CLI and its
container still close before host work begins. Session storage stays in the
temporary private Codex home and is removed when the researcher closes;
infrastructure recovery always starts a fresh session. Record requested and
observed session IDs with each native invocation.
Native CLI token reports are cumulative within a conversation. Retain those raw
totals and derive each invocation's usage by subtracting its preceding report in
the same session; missing or decreasing counters remain unknown. New sessions
start their own accounting baseline.

## Stopping and recovery

There is no shared research cap or fixed iteration count in the current protocol.
The user stops research with the stop command or Ctrl-C. The host interrupts the
active operation, closes its workers, records partial attempts and preserves the
last fully evaluated incumbent. A checkpoint continues research; CLI final prose
is a tool request, not a campaign completion signal.

Infrastructure failures close the attempt. Recovery requires a new output
directory and a recorded diagnosis or repair reason. It keeps the same logical
campaign, task set, limits, baseline, component contracts and model settings.
Completed batches, their sources and checkpoints are copied without rerunning or
changing their records. An unfinished evaluation batch restarts with fresh
workers and a fresh native researcher. Its prior attempted rows remain private
and charged; they are not imported as research feedback. Completed batches in the
unfinished iteration remain available. A partial opening reruns the opening; a completed baseline is
never reopened. This exception is for infrastructure recovery, not disappointing
scores or ordinary task failures.

Recovery preserves original attempt ledgers once, records implementation changes,
and counts prior task, model, output and charged-time spend. For every unfinished
logical task, subtract all previous attempts' charged seconds, actions, combined
agent/user model calls and charged output tokens from its original task caps.
Match attempts by frozen candidate source and task identity. Unknown output usage
keeps its reserved charge; timeout exclusions come from the original task record.
Freeze these derived allowances in recovery provenance and enforce them in both
the task meter and isolated controller. Missing accounting or an exhausted task
allowance blocks recovery before any model dispatch. An explicit user instruction
to completely restart an unfinished candidate may grant that candidate one new
full per-task allowance. Record the candidate ID and authorization in the new
campaign's recovery provenance. This is a disclosed protocol revision, never an
automatic recovery option. Preserve every prior attempt and its cumulative cost;
later recoveries subtract spend incurred since that explicit restart. Other
candidates retain their existing allowances. Completed batches are copied
once and unstarted tasks retain their original caps. Since shared caps are
currently null, there is no finite research allowance to replenish. Researcher
scratch and native process continuations are not resumed. A recorded
`service_not_ready` failure imposes at least fourteen minutes between closure
and recovered dispatch; other failures do not arm that delay. User stops and
budget exhaustion are not eligible for automatic recovery. Existing test review
boundaries remain unchanged.

An operator diagnosing an infrastructure fault uses `stop --diagnostic-reason`
with a concrete explanation. It closes the attempt as an infrastructure failure,
drains active lanes and remains eligible for the normal repair/recovery process.
Plain `stop`, Ctrl-C and SIGTERM remain user stops; diagnostic stop requests cannot
overwrite an existing user stop. Historical misclassified stops remain unchanged
and do not gain automatic recovery eligibility from this implementation change.
After an explicit user request to resume, `recover --resume-stopped` may open a
new attempt from a stopped campaign. Record that authorization in the recovery
reason and provenance; preserve the original stop and deduct all prior spend.
The flag does not permit recovery from budget exhaustion or raise any limit.

## Implemented path

`loopblox/benchmarks/run_tau2.py` exposes `prepare`, `run`, `status`, `stop` and
`recover`. `loopblox/research/campaign.py` owns campaign freezing, process control,
recovery provenance and cumulative reports. `ResearchSession` owns iterations,
candidates, evaluations, selection and checkpoints. Native Codex, the isolated
τ² task runner and mandatory Jev analysis use the existing execution paths.
Campaign children import their frozen implementation. New sessions freeze this
protocol and expose it as `public/experiment.md`.

The research runner receives only development IDs. Host records own the current
incumbent, iteration history, missing results, task/Jev spend and separate native
usage. Reports derive from those records. See
[running.md](docs/running.md#inspect-campaign-outputs) for their locations and
[execution commands](docs/running.md#run-stop-and-recover).
Offline checks cover multiple iterations, selection, candidate allowances,
checkpoints, native receipt continuation, frozen-child execution, interruption
and recovery accounting. They do not constitute a live research run or evidence
of an improved Loop.
