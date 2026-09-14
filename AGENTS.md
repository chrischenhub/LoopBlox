# LoopBlox: composable component research

Engineering and experiment policy, updated 2026-09-14.

- [README.md](README.md) owns the project goal, current status and next milestone.
- [loop.md](loop.md) alone owns Harness, Loop, Component, Invocation and experiment boundary definitions.
- `components.py` owns executable component contracts; `COMPONENTS.md` is generated.
- [CONTROLLER.md](CONTROLLER.md) explains the current controller API to the researcher.

## 1. Product and research object

Build an open-source experiment environment for componentizing harness behavior,
comparing compositions on verifiable tasks, and automatically searching for better
Loops. Visualization explains components, candidate changes and observed execution.
TextWorld remains a mechanism check. The first domain study uses audited τ²-bench
retail/telecom subsets, with specialist and mixed-domain search as specified in
README.md. SpreadsheetBench 2 modeling/debugging is the subsequent artifact-task
direction; it is not integrated yet.

A researcher chooses approved components, their order, repetition, branches and
allowed options in ordinary Python. Complete task runs are the evaluation unit;
each episode separately freezes the editable scope. The current library exposes subcomponents directly; Python owns their composition.
Component contracts may describe multiple model/tool calls. Viewing internals does
not open them for modification. Do not assign components permanent expansion depths.

Python is the canonical Loop definition. The first website is display-only.
Do not add a JSON control graph, restricted Python language, graph compiler,
arbitrary prompt/callback component, or plugin loader. Prioritize a reproducible
experiment over a website editor, a universal taxonomy or full harness replication.

## 2. Current implementation constraints: components

Reuse the existing host model/tool gateways and isolated worker. Every component
needs a meaningful behavioral contract. Serialization, logging and transport are
implementation details. Preserve real model-call boundaries when explaining or
changing a composition; inspect `components.py` for current behavior and costs.

`components.py` owns the four capability families, subcomponent membership,
identities, descriptions, parameters, allowed reference categories, fixed prompts,
output schemas and behavior. Each public subcomponent carries its frozen `family`
metadata (id, label, description). Families organize the catalog; they are not
callable stages, reference types, permissions or an execution order. Regenerate `COMPONENTS.md`
with `python3 -B components.py --markdown`; do not hand-edit it. Episode JSON and
Markdown catalogs derive from the same independently narrowed component definitions.
Reference categories are API types, not Harness layers.

The candidate may use ordinary Python control flow and local computation. Model
calls, context views, observations and environment effects pass through approved
components. The candidate cannot supply replacement messages, arbitrary model
instructions, output schemas, or fabricated host results. Critique's target and
background evidence follow its declared contract.

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
`components.py`. Empty actions are not completion. A proposal or component return
does not end the worker; only outer `run(env)` return normally ends the task.
Limits, interruptions and failures retain distinct statuses. A completion proposal
is not hidden verification. Current decisions concern the whole task; `tool_filter`
filters tool kinds and does not define an independent subgoal.

The host owns factual history, capability definitions, limits and actual effects.
Each task requires a fresh worker and task workspace. The worker has no network,
credentials, task checkout, evaluator or host mount. Components execute on the host
side of the bounded pipe; later references resolve stored originals. Local edits
to returned dictionaries cannot alter those facts.

Context views are frozen and always include the task. Full history is retained.
Summary context preserves summarizer input and output. Raw execution results need
an explicit Observation to enter model context. A shortened representation does
not erase originals. Python helpers do not add synthetic component-result history.

Record invocation IDs, parent IDs, arguments, results, statuses, timing and order.
Record actual model attempts and tool requests with their owning invocation IDs.
`trace_report.py` derives its report from those facts and the frozen catalog; it
must not invent unexecuted branches or count parent summaries on top of child cost.

Model actions have immutable arguments and host-assigned IDs, each attempted at
most once. Rule execution creates fresh tool requests without model endorsement.
Both origins share tools, action accounting and effect rules. Groups execute
serially, stop on the first failure, and retain the attempted prefix when interrupted.
No implicit tool replay or rollback. Ordinary tool failures allow caller recovery;
effects remain `none`, `applied` or `unknown` as actually reported.

The fixed model gateway permits one exact retry for recognized transient faults
with no effects. Messages, schema and requested output allowance stay identical;
every attempt is charged. Unknown usage stays unknown and reserves the requested
allowance. Host faults, operational failures, candidate errors, exhaustion and
verifier failure remain distinct.
If budget or time cannot admit the exact retry, retain the original operational
failure. Exhaustion before an initial attempt remains budget exhaustion.
When the task/research deadline bounds an in-flight HTTP request, its expiry is
budget exhaustion. The client request timeout remains an operational failure.
Deadline-cancelled attempts retain their charged calls and unknown-usage allowance.
Provider-reported length truncation is task output exhaustion only when reported
usage consumes the task's remaining output allowance. Other invalid responses
remain operational failures; do not infer truncation from malformed JSON alone.
Bound the entire HTTP request, including response-body reads, with the existing
process deadline mechanism. Socket inactivity timeouts alone are insufficient.
The trusted HTTP transport process is separate from the isolated candidate worker.

## 4. Research episode

1. Freeze the question, exposed boundary/options, baseline source, library, tools,
   task environment, settings, disjoint development/holdout sets and limits. Prepare
   environments before research. Save exact implementation copies and configuration,
   including environment code, versions and seeds. Provide frozen experiment.json,
   controller-api.md, loop.md, components.json and component-contracts.md. Keep
   complete alternative Loop examples in optional frozen examples/, outside the
   default injected guide; examples do not define the episode's search boundary.
2. Run one supplied baseline trial and initially select that baseline. The host
   supplies its source explicitly. Standard studies and fixed comparisons share
   `study.BASELINE_CONTROLLER`, pointing to `controllers/reactive.py`: direct
   composition with full context and full observations. Fixed comparisons always include this
   baseline; additional mechanism controls cannot replace it. Label an optional
   matched mechanism comparison `control` to retain its own paired report.
   The researcher's own controller (`controllers/research.py`) is frozen separately.
3. Let the researcher save immutable candidates, request development evaluations,
   inspect public traces, write notes and select candidates with at least one scored
   development result (pass or fail) in any order. An unscored attempt does not
   qualify for selection or submission.
   Candidate saves include a brief rationale describing evidence or an untested
   hypothesis, the change, expected outcome and validation. Preserve it beside the
   source as research documentation, never as task-agent input. Exact-source
   duplicates reuse the existing ID and original rationale; further evaluations
   use that ID. Do not enforce a fixed research sequence or novelty quota.
4. Freeze all candidates in an evaluation before drawing the complete shared
   development batch uniformly with replacement from the recorded host seed.
   Run each candidate on each draw and repeat with fresh environments/workers,
   rotating order by draw plus repeat. Pair by draw and repeat, not task ID alone.
   Repeats do not add independent task groups. Preallocate all planned runs;
   attempts, interruptions, failures and costs cannot be removed or refunded.
5. Close the researcher and freeze its last selection before holdout evaluation.
   Final feedback never returns to the researcher or completed task controller.

The researcher may explicitly submit an evaluated candidate and evidence-based
reason through `finish`. Its successful receipt is observed by the fixed researcher
controller, whose outer `run(env)` returns before any later batched action. The
tool does not stop the worker or freeze selection itself. Interim selection and
exhaustion fallback remain distinct from a completed submission. Factual trace
summaries derive from public invocations/requests/results; repeated visible results
do not prove lack of progress, and firing counts do not establish causal effects.

Researcher and development model calls share accounting. Holdout is separate and
uses the same per-task limits. Each episode uses a new output directory. Interrupted
records survive; Python continuations are not resumed. Existing model/limit defaults
remain implementation settings; formal model and budget selection is deferred.

Infrastructure or verifier faults in any development evaluation stop the episode:
opening faults prevent researcher startup, and later faults stop it before further
actions or submission. A failed researcher stops the study; budget exhaustion retains its distinct
fallback behavior. Final-evaluation and comparison infrastructure faults stop further
dispatch, retain the original failure and usage, and must not produce a complete study.

Inheritance campaigns reuse ResearchSession with a fresh researcher each round.
Keep the unified baseline immutable; a distinct inherited source is an additional
opening candidate, evaluated on the same draw and charged to that round. After a
scored opening trial, the inherited source is the initial selection. Independent
rounds inherit nothing; Loop-only rounds receive only the predecessor's submitted
source; Loop+experience rounds also receive cumulative public development evidence
from their own lineage. Export experience only from explicitly completed research,
using the public evidence allowlist. Host-derived counts own outcomes; rationales,
notes and submission reasons remain claims. Never export private user/evaluator data
or final scores. Do not encode research experience in candidate source comments.
Use readable episode/candidate references for inherited identities, not hashes or
bare local IDs. Derive the injected experience overview and source correspondence
from public records and source contents; its navigation paths and evidence links
are relative to the next researcher's public root. Keep raw historical records exact.
Missing-file reads expose public recovery paths. A repeated failure for the same
canonical path stops the fixed researcher with a recorded error, not a submission;
it must not become inheritable experience or silently select a replacement.
Two consecutive duplicate saves of the same existing candidate trigger one reflection
in the fixed researcher before a new decision. A third consecutive duplicate save
stops it with a recorded error. Ordinary duplicate lookup and subsequent evaluation
remain allowed; this is not a candidate novelty requirement. An explicitly requested
recovery may repair the fixed researcher controller in a new frozen campaign, with
implementation changes recorded; completed episodes retain their original controller.
Freeze equal per-round caps, seeds and order; report actual spend and unused budget.
All researchers close before checkpoint comparisons. Identical checkpoint sources
may share one recorded comparison with explicit aliases. A training-only pilot and
its best observed training checkpoint do not establish a causal or holdout gain.

On an explicitly requested recovery, create a new campaign directory and snapshot
completed episodes without rerunning or modifying them. Restart unfinished episodes
with fresh researchers; subtract prior attempts from that logical round's task,
model, charged-output and time caps. Retain those attempts privately for accounting,
not as inherited experience. Known provider startup notices are operational failures,
not simulated-user messages; the shared ledger prevents further model dispatch in
that episode. Stop campaign dispatch on an unsuccessful episode. A later recovery
requires a new explicit request unless the user has authorized scheduled recovery.
Scheduled recovery is opt-in. When explicitly authorized for `service_not_ready`,
close the failed episode, wait at least 14 minutes, and recover in a new campaign
with a fresh researcher and prior spend subtracted. Arm the timer only after an
actual occurrence of that code; pause it when recovery starts, and rearm only for
a new occurrence. Preserve completed screening and submitted branches. Stop on
completion, another failure type, or insufficient budget. This does not authorize
tool replay or resuming a Python continuation. Local timer state and user-specific
authorizations are operational records, not repository defaults.
Campaign interruption signals its serial child and waits for state and usage cleanup
before closing the parent. Recovery during final checkpoint comparison preserves all
research and attempted comparison rows, then runs only rows that never started. It
does not retry interrupted comparisons; their missing scores and reserved usage stay
visible. Prior comparison artifacts remain exact and their costs are counted once.

Authoritative scoring belongs to the environment or sealed task tests and happens
after the task worker closes. Hidden state, reference solutions and evaluator
internals are not model inputs. Specify model-visible feedback separately from final
scoring. The host task runner is responsible for environment isolation and recording.

For an isolated macro comparison, fix internal options; for an internal comparison,
fix the outer workflow. The supplied workflow experiment is joint search. Score
complete outcomes and total cost without attributing joint changes to one level.
Domain studies compare the baseline, domain-selected Loops and a mixed-domain Loop
on identical holdout tasks. All researchers must close before any holdout is run.
The study preallocates the full holdout matrix and rotates candidate order by
task index. Its comparison rows and ledger own the results and costs; episode
final summaries are derived views, never additional dispatches or accounting.
The mixed-domain search receives the sum of the specialist search budgets and
development-run allowances. Independent research repeats and mechanism ablations
remain protocol decisions. A smoke run is not a research gain; a single trial or
trace does not establish a winner or causal effect.

TextWorld is integrated through `textworld_benchmark.py` and `run_textworld.py`.
τ² uses `tau2_benchmark.py` and `run_tau2.py`; both reuse `study.py` and
`ResearchSession`, with no parallel research engine. Pin official source, data and
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
into `components.py` for a new library condition and episode. Never mutate an active
experiment's library. Ordinary composition search needs no approval.

## 6. Four-harness evidence

Ground design questions in the reference harnesses. Module names are evidence, not
the canonical taxonomy. Provenance is in
[the source baseline record](docs/sources.md); decomposition
and known gaps are in [harness-decomposition.md](harness-decomposition.md).

- Pi `b8b873b`: `packages/agent/src/agent-loop.ts`.
- DSH `4e84901`: `packages/core/agent-loop/src/agent.ts`; the Cordis tutorial also
  demonstrates direct code-driven tool execution.
- Codex `27bf160`: `codex-rs/core/src/session/turn.rs`.
- Claude Code: [official loop documentation](https://code.claude.com/docs/en/agent-sdk/agent-loop)
  and [hooks guide](https://code.claude.com/docs/en/hooks-guide). The March 2026 unofficial
  snapshot is not evidence of current official behavior.

Map real behavior boundaries and exercise different compositions; four similar
model/tool cycles do not prove full expressiveness. A reconstructed loop is not a
native replica. Native optimization claims require a pinned original baseline and
validation of the change in that implementation.

`site/` is the English, read-only LoopBlox introduction focused on domain loop auto
research. Its SVG illustrations explain research, the supplied reactive task loop,
and the planned domain study; they do not execute controllers or depict live runs.
The parent README and loop.md own direction, status and definitions. The website
uses explicit snapshots; component families/contracts and baseline source derive
from components.py and controllers/reactive.py. Refresh snapshots with
`python3 site/build.py --refresh-notes`, then review the English summaries against
the canonical documents. The four-harness atlas is retired from the current website. Current builds must not
publish retired pages.

## 7. Engineering

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
configuration or UI systems without a current consumer. Keep model/budget selection
separate from this infrastructure work.
