# LoopBlox: composable component research

Engineering and experiment policy, updated 2026-09-21.

- [README.md](README.md) owns the project goal, current status and next milestone.
- [experiment.md](experiment.md) owns the current continuous research protocol on one frozen benchmark and its implementation status.
- [docs/random-search.md](docs/random-search.md), [docs/continual-improvement.md](docs/continual-improvement.md) and [docs/release-research.md](docs/release-research.md) preserve retired protocols; they are not instructions for new campaigns.
- [docs/running.md](docs/running.md#native-codex-researcher) owns native Codex researcher setup; [docs/codex-research-comparison.md](docs/codex-research-comparison.md) preserves the retired two-researcher comparison and its information boundary.
- [loop.md](loop.md) alone owns Harness, Loop, Component, Invocation and experiment boundary definitions.
- `loopblox/runtime/components.py` owns executable component contracts; `COMPONENTS.md` is generated.
- [CONTROLLER.md](CONTROLLER.md) explains the current controller API to the researcher.

## 1. Product and research object

Build an open-source experiment environment for componentizing harness behavior,
comparing compositions on verifiable tasks, and automatically searching for better
Loops. Visualization explains components, candidate changes and observed execution.
TextWorld is retired. The immediate release milestone and its acceptance criteria
are owned by [README.md](README.md#announcement-target). The active release benchmark
is τ²-bench telecom; retail runs are historical. Preserve the
official telecom evaluator, including action checks where required. Do not substitute
environment-only scoring for tasks with additional official criteria. Current work
iterates Loops on the same frozen benchmark under experiment.md. Random search,
BFS/DFS, specialist/mixed-domain studies, researcher comparisons and the bounded
two-batch release workflow are retired. Their sources are preserved under
`archive/experiment-workflows-20260921/`; active launch commands have been removed.
Historical campaigns keep their own frozen implementations. τ³ is not integrated.
SpreadsheetBench 2 modeling/debugging is the subsequent artifact-task
direction; it is not integrated yet.

A researcher chooses approved components, their order, repetition, branches and
allowed options in ordinary Python. Complete task runs are the evaluation unit;
each episode separately freezes the editable scope. The current library exposes subcomponents directly; Python owns their composition.
Component contracts may describe multiple model/tool calls. Viewing internals does
not open them for modification. Do not assign components permanent expansion depths.

Python is the canonical Loop definition. The first website is display-only.
Do not add a JSON control graph, restricted Python language, graph compiler,
general-purpose prompt/callback component, or plugin loader. Judge is the explicit
typed-question interface described below; it does not expose arbitrary model output. Prioritize a reproducible
experiment over a website editor, a universal taxonomy or full harness replication.

## 2. Current implementation constraints: components

Reuse the existing host model/tool gateways and isolated worker. Every component
needs a meaningful behavioral contract. Serialization, logging and transport are
implementation details. Preserve real model-call boundaries when explaining or
changing a composition; inspect `loopblox/runtime/components.py` for current behavior and costs.

`loopblox/runtime/components.py` owns the four capability families, subcomponent membership,
identities, descriptions, parameters, allowed reference categories, fixed prompts,
output schemas and behavior. Each public subcomponent carries its frozen `family`
metadata (id, label, description). Families organize the catalog; they are not
callable stages, reference types, permissions or an execution order. Regenerate `COMPONENTS.md`
with `python3 -B -m loopblox.runtime.components --markdown`; do not hand-edit it. Episode JSON and
Markdown catalogs derive from the same independently narrowed component definitions.
Reference categories are API types, not Harness layers.

The candidate may use ordinary Python control flow and local computation. Model
calls, context views, observations and environment effects pass through approved
components. When exposed, `judge` accepts candidate-authored Noul/Choice questions,
criteria and category labels; these are part of the candidate design and recorded
verbatim with each call. The host fixes its evidence access, typed output protocol,
Jev transport and accounting. Other components do not accept replacement messages
or arbitrary model instructions. Candidates cannot supply arbitrary output schemas
or fabricated host results. Plan steps contain model-proposed
objectives and completion requirements. Scoped decisions resolve a step from the host's
stored Plan; they do not replace task requirements or grant additional permissions.
Critique's target and evidence references follow its declared contract. Its overall
verdict derives from its individual assessments, not from a separate model acceptance flag.
Choose selects an existing decision reference or declines all candidates; it neither
rewrites proposals nor executes their actions.

Each experiment exposes a root component catalog and optional enum restrictions.
The host enforces that boundary for baseline, development and holdout calls.
Every current subcomponent call uses that same boundary. There is no AgentWork
component or trusted composite dispatch path. The boundary does not enforce
arbitrary fixed parent workflows or open arbitrary source positions inside components. Seeing trace/source internals
or adding a Python wrapper grants no additional capabilities.

The examples in `controllers/` define complete Loops, not individual components.
Their required components must be exposed by the experiment. Keep the examples
consistent with the generated contracts. An ordinary Python helper does not create
a recorded component boundary.

## 3. Current implementation constraints: execution

The model proposes actions or completion; the controller owns continuation and
final return. Decide's canonical actions/completion union is `decision_schema` in
`loopblox/runtime/components.py`. Empty actions are not completion. A proposal or component return
does not end the worker; only outer `run(env)` return normally ends the task.
Limits, interruptions and failures retain distinct statuses. A completion proposal
is not hidden verification. Decisions concern the whole task by default. An explicit
`scope` resolves one immutable Plan step and permits local completion or blockage
proposals; Python owns subsequent steps, replanning, and final return. `tool_filter`
filters disclosed tool kinds and does not define a subgoal or grant permission.

The host owns factual history, capability definitions, limits and actual effects.
Each task requires a fresh worker and task workspace. The worker has no network,
credentials, task checkout, evaluator or host mount. Components execute on the host
side of the bounded pipe; later references resolve stored originals. Local edits
to returned dictionaries cannot alter those facts.

Context views are frozen and always include the task. Full history is retained.
Their `through` cursor marks the exclusive history boundary. Full context can retain
an explicit base and append later evidence; a summary inherits its source cursor.
Full and recent selection exclude summary turns unless retained through an explicit
base. Recent context counts the first observations of four distinct executions,
not analysis calls or additional observation pages. Raw execution results need an
explicit Observation to enter model context. Brief results support 1,200-character
pages and may later be observed in full. In a new view, a full observation replaces
brief pages of the same execution; already-frozen views do not change. Python
helpers do not add synthetic component-result history.

Record invocation IDs, parent IDs, arguments, results, statuses, timing and order.
Record actual model attempts and tool requests with their owning invocation IDs.
`loopblox/report.py` derives its report from those facts and the frozen catalog; it
must not invent unexecuted branches or count parent summaries on top of child cost.

Model actions have immutable arguments and host-assigned IDs, each attempted at
most once. Rule execution creates fresh tool requests without model endorsement.
Both origins share tools, action accounting and effect rules. Groups execute
serially, stop on the first failure, and retain the attempted prefix when interrupted.
No implicit tool replay or rollback. Ordinary tool failures allow caller recovery;
effects remain `none`, `applied` or `unknown` as actually reported.

The fixed model gateway retries `model_timeout` without a fixed retry-count cap
while charged-time, model-call and output budgets admit another exact attempt.
Recognized no-effect timeout attempts and their two-second retry waits do not
consume task or ancestor research time. Record their actual wait duration on the
attempt; deadlines and usage summaries derive the exclusion from those records.
Structured HTTP 429 errors with provider code `concurrency_limit_exceeded` are
recognized separately and retry after 60 seconds on each occurrence while budgets
admit another exact attempt. Their elapsed request and retry-wait time remains
charged. Other recognized transient faults permit one exact retry, waiting two
seconds; their elapsed time remains charged. Only faults with no effects qualify.
Messages, schema and requested output allowance stay identical;
every attempt is charged. Unknown usage stays unknown and reserves the requested
allowance. Host faults, operational failures, candidate errors, exhaustion and
verifier failure remain distinct.
If budget or time cannot admit the exact retry, retain the original operational
failure. Exhaustion before an initial attempt remains budget exhaustion.
Admit requests only while charged time remains, then let each reach its client
request deadline so a timeout can be classified and its wait excluded. Successful
requests consume time; a success that exhausts task/research time is retained and
charged but not delivered to the controller. Client request timeouts remain
operational failures. Interrupted attempts retain their charged calls and
unknown-usage allowance; do not assume an interruption was a timeout.
General τ² task defaults are 900 charged seconds, owned by DEFAULT_TASK_LIMITS
in loopblox/benchmarks/tau2.py. The accepted continuous campaign uses
`loopblox/research/campaign.py::TASK_LIMITS`: 900 charged seconds, 60 actions,
256 combined agent/user model attempts and 65,536 output tokens per task. Shared
research limits are explicitly null. experiment.md owns this accepted protocol. Record every attempt and actual usage. This does not
remove per-request transport deadlines/output settings, isolation, fault handling,
the frozen task/batch design or the pause before final comparison. Keep wall duration separate from charged duration
in results and use charged duration when subtracting recovery spend. Historical
frozen runs retain their original limits and time-accounting rules.
Provider-reported length truncation is task output exhaustion only when reported
usage consumes the task's remaining output allowance. Other invalid responses
remain operational failures; do not infer truncation from malformed JSON alone.
Bound the entire HTTP request, including response-body reads, with the existing
process deadline mechanism. Socket inactivity timeouts alone are insufficient.
The trusted HTTP transport process is separate from the isolated candidate worker.

## 4. Research episode

Native Codex is the default researcher for new sessions. The former in-house
controller and two-arm comparison launcher are archived as
`archive/researcher-20260921/controller.py` and
`archive/researcher-20260921/researcher_comparison.py`; do not dispatch them for new
research or silently fall back to them. Historical campaigns retain their exact
frozen implementations and evidence. The switch does not authorize new task runs
or cross an existing review boundary.

Use the pinned Linux Codex 0.155.0 distribution from `LOOPBLOX_CODEX_BINARY_ROOT`
and an existing ChatGPT subscription login. `LOOPBLOX_CODEX_MODEL` defaults to
`gpt-6-astra`; `LOOPBLOX_CODEX_REASONING_EFFORT` defaults to `low`.
`LOOPBLOX_CODEX_AUTH_FILE` overrides `$CODEX_HOME/auth.json` or, when `CODEX_HOME`
is unset, `~/.codex/auth.json`. Freeze native settings, binary identity and access
policy for each session; never freeze or export credentials. Reject missing binary
or login setup before opening task dispatch. Native CLI usage is recorded separately
from gateway attempts: finite shared model-call and output-token caps are unsupported
and must fail before opening, not be silently removed. Changing a historical study's
caps requires an explicitly revised protocol. Finite shared time and task-run caps
remain supported; per-task model and output caps remain enforced.

All future training/development tasks must belong to the benchmark's official train
split. The frozen official split file owns membership; a local development label
cannot override it. For τ², suite loading enforces this before model dispatch.
Historical custom-split campaigns retain their original frozen implementation and
exposure records; they must not seed new training with official test traces.
The historical retail campaign uses official train[:30] in three ordered,
non-overlapping batches of ten, and all official test tasks after research closes.
Its exact task selection includes related families, NL grading, handoffs and
empty-environment-score cases; retain the audits and disclose these scope changes.
The current protocol uses ten audited official telecom training tasks and keeps
official test outside research. Any final evaluation needs separate review and
authorization. Freeze selection, exclusions and known exposure before execution.
The domain pivot requires a new campaign; it is not recovery of the retail study.
The telecom research entry point must reject tasks that require model-based grading before
dispatch, while retaining all deterministic official scoring requirements.

1. Freeze the question, exposed boundary/options, baseline source, library, tools,
   task environment, settings, disjoint development/holdout sets and limits. Prepare
   environments before research. Save exact implementation copies and configuration,
   including environment code, versions and seeds. Provide frozen experiment.md, experiment.json,
   controller-api.md, loop.md, components.json and component-contracts.md. Keep
   complete alternative Loop examples in optional frozen examples/, outside the
   default injected guide; examples do not define the episode's search boundary.
2. Evaluate the supplied baseline once on the full frozen development task set and
   initially select it. The host supplies `controllers/reactive.py` explicitly:
   direct composition with full context and full observations. Keep its recorded
   outcomes as the reference for later Loops on the same benchmark.
   Freeze the native researcher's configuration separately from task Loop sources.
3. Admit one new candidate by default, at most two per iteration. Save source and
   rationale immutably. Duplicate sources reuse their original IDs and evidence;
   they cannot be evaluated again. The researcher may inspect records, revise
   hypotheses and write notes freely inside this candidate allowance.
4. Freeze every new source and evaluate it once on all ten tasks with fresh
   workers, the same task order and the same limits. Rotate execution order when
   two candidates share a batch. Preserve failures, interruptions, missing scores
   and all spend. Complete mandatory Jev analysis before releasing batch feedback.
5. The host selects by official passes, agent input tokens, then agent model calls,
   retaining the incumbent on ties. Only fully scored and analyzed batches qualify.
   `checkpoint(notes)` requires all this iteration's saved candidates to qualify;
   it preserves evidence, incumbent changes and experience, then starts another
   iteration. The researcher has no `select` or `finish` capability. User stop
   closes research and freezes the current incumbent; no final test dispatch follows.

Factual trace summaries derive from public invocations, requests and results.
Repeated visible results do not prove lack of progress, and firing counts do not
establish causal effects. Infrastructure failures retain their own status and
recovery rules; failed candidates do not end the continuous campaign.

Development model calls and Jev share the gateway ledger; native researcher usage
is recorded separately with its coverage limitations. Shared time includes research
and development. Holdout is separate and uses the same per-task limits.
Each episode uses a new output directory. Interrupted
records survive; Python continuations are not resumed. The continuous campaign
uses the task limits and uncapped research policy accepted in experiment.md.

The researcher may use `research_shell` to search and analyze its allowed public
records with shell and Python. Each command has a fresh isolated analysis container,
read-only access to that episode's public records and writable episode scratch. Scratch
files persist across commands; processes do not. No private records, credentials,
network or evaluator access is granted. Existing tool recording and research-time
accounting apply. Freeze command limits in `research-workspace.json`; scratch has
no filesystem quota. Analysis outputs and scratch remain researcher claims and are
not automatically exported as lineage experience. Evaluation receipts and initial
guides provide compact navigation; complete public evidence stays on disk.
Research analysis and host evaluation run serially. Close each analysis container,
including its background processes, before executing the next host request.
For native Codex research, each CLI invocation reads only approved public materials
and its own prior work, then exits with a request. The host validates and executes
that request after the container closes. Start the next CLI only after the request
and any mandatory Jev analysis complete. A successful `checkpoint` continues the sequence.

Online `judge` calls are optional Loop behavior, charged to the task and shared
research ledger, and return `analysis_result` references. Question definitions
travel with their answers so downstream components can interpret their meaning.
`loopblox/runtime/jev.py` owns the shared Jev transport; `components.py` owns the
online Judge contract. Changing questions, categories, thresholds or triggers is
ordinary candidate search when Judge is exposed. Adding Judge requires a new
frozen library condition; preserved campaigns and their boundaries remain exact.

Post-run Jev analysis is mandatory after each development task run and before its feedback
reaches the researcher, including the opening baseline and every candidate run.
`loopblox/analysis/segments.py` owns the fixed four-observation segmentation and
questions; `loopblox/analysis/jev.py` owns dispatch and evidence persistence. Reuse
the shared research model ledger and gateway. Keep Jev inputs limited to public
trace evidence, retain exact responses and missing measurements, and stop feedback
release on analysis failure or budget exhaustion. Jev judgments never replace task
scores. Public `jev.json` records remain part of the campaign evidence.
The A/B pilot is retired; [docs/jev.md](docs/jev.md) documents the adopted workflow.
Research views join Jev segments to their actual public invocations, owned agent
cost and exact input/response locations. Derive these views from the recorded trace
and Jev response; keep missingness, confidence and measurement schemas explicit.
Use them to investigate progress, immediate effectiveness and subsequent recovery
behavior without treating judgments or component participation as causal proof.

Infrastructure or verifier faults in any development evaluation stop the episode:
opening faults prevent researcher startup, and later faults stop it before further
actions or submission. A failed researcher stops the episode; budget exhaustion retains its distinct
fallback behavior. Final-evaluation and comparison infrastructure faults stop further
dispatch, retain the original failure and usage, and must not produce a complete result.

Historical inheritance, continual-improvement conditions and cross-domain studies
are retired. Their exact code is preserved in the workflow archive; their
protocols remain in the historical documents. New campaigns import no old
candidates, notes or results. Accumulated experience belongs to the current
campaign and must stay within its permitted public records. Host-derived counts
own outcomes; rationales, notes and submission reasons remain claims. Keep
research history out of task-agent input and candidate source comments. Private
simulator data, evaluator internals and final scores are never research input.
The current iteration, checkpoint and recovery rules are owned by experiment.md.

An instruction to run an experiment also authorizes diagnosing, fixing, checking and
recovering from operational or infrastructure failures encountered in that work.
Trigger these repairs and reruns autonomously; do not require a new user request
for each recovery. Close the failed episode first, inspect its evidence, make the
smallest justified repair and run focused checks before dispatching again. Preserve
raw failed responses when available so repeated failures can be diagnosed. Ordinary
task failures, disappointing scores and budget exhaustion are not reasons to rerun
for a better result. Do not repeatedly retry an unchanged failure without new
evidence or a justified recovery step.

For recovery, create a new campaign directory and snapshot
completed batches and checkpoints without rerunning or modifying them. Restart
unfinished batches with fresh workers and a fresh researcher; subtract prior attempts from that logical round's task,
model, charged-output and time caps. Retain those attempts privately for accounting,
not as research feedback in the recovered attempt. Freeze and disclose implementation or request-setting
repairs in the new campaign; never mutate the failed campaign. Do not silently
increase total budgets, change scoring or data-access rules, or cross a user-requested
pause or review boundary. In particular, a request to stop before formal comparison
continues to prohibit test dispatch during recovery. Ask only when recovery needs
authority beyond the existing scope or cannot proceed within the remaining budget.
Known provider startup notices are operational failures,
not simulated-user messages; the shared ledger prevents further model dispatch in
that episode. Stop dispatch within an unsuccessful episode, then apply the recovery
procedure above. Creating a scheduled background recovery remains opt-in; recovery
during active authorized work does not require a separate scheduling authorization.
After an actual `service_not_ready` failure,
close the failed episode, wait at least 14 minutes, and recover in a new campaign
with a fresh researcher and prior spend subtracted. Arm the timer only after an
actual occurrence of that code; pause it when recovery starts, and rearm only for
a new occurrence. Preserve completed task records and checkpoints. Stop that
timer on completion, another failure type, or insufficient budget; diagnose a new
failure type under the same recovery procedure. This does not authorize tool replay
or resuming a Python continuation. Local timer state and scheduling authorizations
are operational records, not repository defaults.
Campaign interruption signals its serial child and waits for state and usage cleanup
before closing the parent. Historical comparison recovery used only rows that never
started; interrupted rows and their missing scores remained recorded. Preserve
those records and count their costs once. This does not authorize a comparison
stage in the current protocol.

Authoritative scoring belongs to the environment or sealed task tests and happens
after the task worker closes. Hidden state, reference solutions and evaluator
internals are not model inputs. Specify model-visible feedback separately from final
scoring. The host task runner is responsible for environment isolation and recording.

For an isolated macro comparison, fix internal options; for an internal comparison,
fix the outer workflow. The supplied workflow experiment is joint search. Score
complete outcomes and total cost without attributing joint changes to one level.
The specialist/mixed-domain study is retired. Preserve its original comparison
rows and ledger as the owners of historical outcomes and costs; derived summaries
must not add dispatches or duplicate spend. New work evaluates Loops on the same
benchmark and reports recorded outcomes and cost without claiming a causal effect
from one trial or trace.

τ² uses `loopblox/benchmarks/tau2.py` and `loopblox/benchmarks/run_tau2.py`, reusing
`loopblox/research/session.py::ResearchSession`. No active code may depend on
the archived study or comparison helpers.
Do not restore the retired TextWorld adapter or add a parallel research engine. Pin official source, data and
dependencies. Audit each task's actual reward basis and empty-trajectory result
before selection; group related variants and exclude integration groups from the
main dataset. Frozen task files take precedence over upstream summary prose.

For τ², retain the official policies, tools, user simulator, conversation state
machine and evaluator. Each task gets fresh environment/user state and an isolated
controller worker. Simulated-user and agent calls share the task and research
budgets; expose only messages addressed to the agent, never private user scenarios,
user-tool trajectories or evaluator internals. Store environment model requests in
host-private ledgers, outside researcher-readable evaluation directories. Unknown
prices remain unknown. Authoritative scoring starts only after the worker closes.

SpreadsheetBench 2 and Terminal-Bench are not integrated yet. The obsolete
SWE-bench adapter and launcher have been removed and must not be presented as the
selected benchmark. `ResearchSession`
accepts a host-provided task runner.

## 5. Proposed components

The researcher may submit name, purpose, inputs, outputs, behavior, why existing
components are insufficient and an example composition. Optional implementation is
stored as text. A proposal is not executable or approved merely because it exists,
compiles or was written by the researcher.

Humans review definitions and implementations, then incorporate accepted components
into `loopblox/runtime/components.py` for a new library condition and episode. Never mutate an active
experiment's library. Ordinary composition search needs no approval.

## 6. Website

`site/` is the English, read-only LoopBlox introduction focused on domain loop auto
research on one benchmark. Its SVG illustrations explain continuous research and
the supplied reactive task loop; they do not execute controllers or depict live runs.
The parent README and loop.md own direction, status and definitions. The website
uses explicit snapshots; component families/contracts and baseline source derive
from loopblox/runtime/components.py and controllers/reactive.py. Refresh snapshots with
`python3 site/build.py --refresh-notes`, then review the English summaries against
the canonical documents.

## 7. Engineering

Maintain repository documentation in English, including public experiment summaries.
Historical experiment records and their frozen sources remain exact.

Python implementation lives under `loopblox/`: runtime, research, analysis and
benchmarks. `controllers/` contains complete Loop sources; root `experiments/`
contains JSON conditions. Run CLIs as modules from the source root. Do not add
root-level forwarding scripts or import-path compatibility shims.
`loopblox/__init__.py` owns the source root and implementation snapshot operation.
Snapshots preserve package paths, controller sources, conditions and documentation.
Campaign children must import the frozen package, even when launched from the
mutable checkout. Old campaigns retain their original entry points and sources;
use those frozen implementations when recovering without a code change. A justified
repair is frozen separately in the new campaign, with its differences and the prior
campaign's provenance recorded.

Build the smallest complete slice. Each rule, schema and state transition has one
semantic owner; derive or explicitly snapshot other representations. Reuse execution,
persistence, accounting and evaluation. Remove superseded runtime paths and unused
abstractions; do not keep speculative compatibility layers or parallel engines.
Preserve historical results and their exact source copies when retiring old paths.
Keep raw experiment directories and their frozen implementations outside version
control under `.artifacts/`. Public result summaries must identify their source
records and preserve failure and missing-score counts; summaries cannot replace
raw evidence. Do not modify preserved campaign files when preparing a release.

No TDD or new test suite unless requested. Use focused execution checks for changed
behavior, then simplify the implementation. No speculative registries, adapters,
configuration or UI systems without a current consumer. Changes to frozen models
or budgets require an explicitly revised protocol.
