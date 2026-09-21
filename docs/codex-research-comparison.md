# Native Codex and the archived researcher comparison

**Current policy, September 21, 2026:** native Codex is the default researcher for
new sessions. The former LoopBlox researcher is retired. Its controller and the
two-arm launcher are preserved in
[`archive/researcher-20260921/`](../archive/researcher-20260921/), and historical
campaigns retain their exact frozen implementations. The default remains pinned
Codex 0.155.0, `gpt-6-astra`, `low` reasoning and an existing ChatGPT subscription
login, with the research access boundary described below. See
[native researcher setup](running.md#native-codex-researcher) for configuration and
supported budgets. This change launches no research or task evaluations; new
experiments require their own frozen protocol and authorization.

The `finish` behavior and early stopping described in the comparison protocol
below are historical. The current continuous adapter exposes `checkpoint`, has no
researcher termination tool, and follows [experiment.md](../experiment.md).

## Historical status

The file-based runner passed its isolated two-invocation roundtrip and
a live ChatGPT-subscription check on 2026-09-21. The first launch was interrupted
when the user changed future evaluations to new candidates only; its started
control attempt and researcher work remain recorded under the amendment below.
Codex subsequently completed its 30 candidate scores and Jev analyses and submitted
the terminal-guard Loop (8/10). The summary and repetition-triggered reflection candidates
scored 5/10 and 6/10; Reflect never fired in the latter. A local stage-launch
failure then prevented LoopBlox startup. After that repair, LoopBlox made 11
researcher calls before the provider returned `service_not_ready`, without saving
or evaluating candidates. A subsequent amendment restricted LoopBlox to analysis
without running proposed Loops; the user then retired that researcher and closed
the comparison. The completed Codex optimization and interrupted LoopBlox arm are
therefore
not an equal-opportunity two-researcher result or evidence of improvement over the
historical controls.
The Codex arm uses the existing ChatGPT
subscription; it must not switch to API billing.

## Historical question and fixed conditions

Given the same initial evidence, component boundary and evaluation opportunities,
what Loops do the then-current LoopBlox researcher and native Codex produce?

This compares complete researcher configurations. Their base models and research
workflows may differ, so an outcome cannot isolate the effect of Codex's harness.
The task agent answering telecom customers stays identical between arms.

| Fixed between arms | Allowed to differ |
| --- | --- |
| Initial task, public documents, supplied sources and opening evidence | Researcher model and native system instructions |
| Accessible task-specific information and feedback rules | Research workflow, context management and local analysis tools |
| Candidate slots, development tasks, batch rules and selection | Inspection order, hypotheses, candidates and early stopping |
| Task agent, components, user simulator, evaluator and Jev | Researcher usage, elapsed time and cost |

The comparison froze the LoopBlox implementation, including its research workspace,
Jev navigation and the former `controllers/research.py`. Freeze the native CLI version and
binary, execution environment, enabled capabilities, model and reasoning setting.
The intended initial Codex settings are 0.155.0, `gpt-6-astra` and `low` reasoning;
the prepared protocol owns the actual settings. Each Codex invocation starts a
fresh session and receives its own previous files and host receipts. This restart
behavior is part of the compared researcher configuration.

## File-based research rounds

Reuse `ResearchSession` and the release policy. The Codex adapter only exchanges
files with the host:

1. Export the canonical research task, tool declarations and allowed public
   records into an isolated CLI workspace. Include that arm's previous requests,
   receipts, notes and scratch files.
2. Run `codex exec`. Codex may search evidence, compute analyses and draft source.
   It writes one JSON request using an existing research tool's name and argument
   schema, then exits. Its local candidate files are drafts until `save_candidate`
   accepts the exact source.
3. After the CLI and its descendants have stopped, the host validates and executes
   that request through the existing session handler. Only `evaluate` dispatches
   development tasks. Save the exact request, receipt, timing and effects.
4. Export the completed receipt and newly available public files for the next
   invocation. Repeat until successful submission or a stopping condition.

The host tool declarations derive from `ResearchSession.tools()` and
`Tool.disclosure_record()`. The adapter does not implement its own candidate,
evaluation or ranking rules. Extra CLI instructions explain paths and the request
file format; they add no task facts or research advice from this conversation.

No Codex process runs while the host evaluates a batch. Export its results only
after the complete batch and mandatory Jev analyses finish. Ordinary tool errors
return a receipt the researcher can inspect and correct. Infrastructure, verifier
or Jev failures stop the arm and retain their records. A failed CLI invocation
does not authorize executing a partially written request.

Only a successful `finish(candidate_id, reason)` receipt submits a Loop. Native
final prose and a zero CLI exit code are insufficient. After successful `finish`,
start no further invocation and freeze selection. Interrupted or exhausted work
retains its distinct status. Never replay a request whose effects are uncertain.

## Historical development opportunities

Use the audited ten official telecom training tasks and the candidate-only policy
owned by the now-archived `researcher_comparison.py`, reusing the release's
three-then-two candidate allowances and ranking rule. Preserve the suite's selection
and exposure records. Neither arm receives historical research experience.

Use one common opening: L0 and L1 on all ten tasks, with Jev analysis.
Both arms receive identical copies of these 20 public records and the same
receipt. Two separately sampled openings would give different evidence.
On 2026-09-21 the user explicitly chose to reuse the completed historical
opening instead of rerunning it. Preparation accepts that campaign through
`--opening`; without that option it runs a fresh common opening.

After startup, the user amended the protocol: do not repeat L0, L1 or previously
evaluated candidates. Evaluate only each researcher's newly proposed Loops;
when there is no worthwhile improvement hypothesis, finish without a new run.
Each arm independently receives:

| Batch | Eligible sources | Maximum task runs |
| --- | --- | --- |
| First | Up to three new sources from that researcher | 30 |
| Second | Up to two additional new sources from that researcher | 20 |

Every new source runs once on each of the ten tasks, with fresh workers/environments
and the existing source-order rotation. Freeze all sources before dispatch.
Reject controls and already evaluated sources before allocating a batch.
Unused first-batch slots do not transfer. Early finish is valid, including zero
new evaluations; record unused opportunities. Candidate counts are ceilings,
not requirements to invent changes or spend evaluation slots.

With a fresh opening the maximum is **20 common opening runs plus 50 per arm:
120 unique development dispatches**. Reusing the historical opening requires
zero opening dispatches and at most **100 new candidate-task dispatches**.
Each arm can save at most five novel sources. The shared opening
has one cost owner; copied evidence consumes no additional task or Jev calls.
Freeze a host-seeded order for the two arms before dispatch and run them serially
without cross-arm feedback. Retain timestamps; one pair does not eliminate time
or provider variation.

Keep release task limits fixed: 900 charged seconds, 60 actions, 256 combined
task-agent/user model attempts and 65,536 output tokens per task. Task-agent,
simulated-user and Jev settings stay fixed. Researcher time, model-call and token
caps remain null; record their actual available usage separately. Isolation
limits are disclosed independently. A quota or provider error never silently
changes the selected model.

The reused `telecom-release-research-20260921-bounded-01` opening includes
11 attempts with the earlier unlimited task settings, nine with the current
caps, and one user-adjudicated failure whose official score remains missing.
It is exploratory starting evidence, not a uniform-budget comparison.
Freeze its original public evaluation and setup separately, hash every imported
file, and validate source identities, task order, component contracts, model
settings, exact per-row limits and adjudication, scores and completed Jev records.
The source seed is recorded separately from the new arm-order seed. The new
researcher instructions may differ; the task component boundary must agree.
Both arms receive `opening-provenance.json` explaining these conditions.
Later research candidates, notes and evaluations are not imported. Historical
task and Jev costs remain owned by the original campaign and its prior-attempt
ledgers; each new arm starts with zero charged dispatches and 20 carried records.
New evaluations use the same current task caps in both arms. Do not fabricate
official scores, rewrite raw historical records or resume a stopped worker.

The release ranking rule owns selection: passes, then known agent input tokens,
agent model calls and original candidate order. Select from the completed opening
and completed new-candidate batches. Retaining the opening winner is valid.
These cross-batch rankings are descriptive: the controls are historical, budgets
were mixed and provider timing differs. Do not label them a new paired control
experiment or a confirmed improvement. Candidates evaluated together can retain
their within-batch comparison. Jev guides investigation; its judgments do not
replace official scores or establish causal explanations.

The original comparison was interrupted during its first repeated L0 task, before
L1 or any proposed candidate task started. Preserve that unscored attempt and its
usage; it is neither an official failure nor a new opening result. Codex had
already saved three untested sources. A new frozen campaign may restore those
sources, exact rationales, completed save receipts and that arm's own scratch
after recording the common initial input. They count toward its five-source
allowance. Start a fresh native invocation under the amended policy; never replay
the interrupted evaluation or expose its partial task feedback. The other arm
receives no Codex work. Disclose that the protocol changed after research began
and retain prior native and task usage separately in the experiment accounting.

The first candidate batch later stopped after eight scored runs when the simulated
user's model returned `service_not_ready`. A fresh recovery preserves those eight
run directories and Jev records exactly, retries only the infrastructure-failed
row, and dispatches the 21 unstarted rows. The original failed attempt remains
private and charged; ordinary task failures are not retried. The fresh researcher
receives its own candidate work but no incomplete evaluation feedback; its new
evaluation request releases feedback only after the recovered batch completes.
Freeze the prior attempt and admit no recovery dispatch until fourteen minutes
after the failed campaign closed. Nine prior candidate dispatches reduce Codex's
new allowance from 50 to 41; the other arm retains 50. Restoring the eight scores
does not charge them again, and consumes no additional Jev calls. The interrupted
pre-amendment L0 attempt remains a separate retained cost. The selected loops and
rankings still require the same completion and review boundaries.

The completed Codex campaign is
`.artifacts/tau2/telecom-researcher-comparison-20260921-service-recovery-01`;
the independent result audit is
`.artifacts/analysis/codex-researcher-results-20260921/review.md`.
Its launcher reused one process across arms, so τ²'s environment initialization
guard rejected LoopBlox before it created a research session or spent any calls.
Each stage now runs in its own frozen CLI process through the existing serial
process runner. The new campaign retains the common opening, shared input snapshot,
completed Codex artifacts and all prior usage exactly. Only the launcher changes;
the untouched LoopBlox arm keeps its original 50-run ceiling and candidate-only
policy. Copied costs are attributed to their original stages once.

The subsequent startup-notice failure is retained in
`.artifacts/tau2/telecom-researcher-comparison-20260921-stage-recovery-01`.
Its 11 researcher calls used 114,908 input tokens, 672 output tokens and 42.624
charged seconds. No task, simulated-user or Jev call was made. Recovery archives
that arm privately, retains its usage once and starts a fresh researcher from the
identical common input after at least fourteen minutes. No unfinished scratch or
claims are supplied as experience. Shared research caps remain null and the
unchanged task allowance is 50. Timers remain disabled.

The later user amendment permitted zero new task runs for LoopBlox. It could inspect
the same opening and Jev evidence, write findings and save up to five untested
source proposals, without a proposal quota. The host removes `evaluate`, rejects
new evaluation requests and sets its task allowance to zero. Submission requires
research notes and retains the scored opening winner; untested proposals cannot
be selected. The amendment receives a separate initial-input snapshot and is
disclosed in the final result. Completed Codex records remain unchanged. That
researcher is now retired and will not continue this review. The user subsequently
lifted the restriction on new Loop runs for future experiments, to be started
separately; it does not reopen this comparison.

## Information boundary and launch checks

Both arms receive the same common base task, tool semantics and public-file contents;
freeze and compare these before researcher dispatch. On amendment, Codex additionally
receives its own previously completed work after this base-input check; record its
actual task separately. Their later evidence may
differ because they submit different candidates. Neither arm receives the other
arm's outputs, this conversation, old research sessions or additional experience.

Public development traces and scores are legitimate evidence, including facts
visible in successful runs. Hidden user scenarios, evaluator assertions,
reference solutions, private simulator trajectories and holdout feedback remain
unavailable. Different model pretraining is an allowed, uncontrolled difference.

Use the native workspace-write sandbox in a clean container whose task-specific
files contain only approved inputs and that arm's own work. Disable external
retrieval and unrelated integrations. The researcher must not gain access to the
host repository or other workspaces. Authentication needed for official ChatGPT
sign-in may be present inside the clean container; do not claim it is isolated
from every process there. Keep credentials out of exported research records.
The stock Code Mode host is enabled for the selected model's native tools; it
delegates commands to the same native sandbox. No research tool server is used.
The frozen CLI permission profile extends the native workspace policy, denies
tool reads of its authentication home and disables tool networking. The container
has no repository or evaluator mount. A focused native-sandbox check verified
these restrictions and the allowed evidence/scratch access.
The clean native home grants no project trust. Untrusted scratch configuration
cannot grant itself trust or override the profile; the focused check is recorded
in `.artifacts/codex-research-comparison-20260921/project-config-latest-report.json`.

Before any real model or benchmark run, use synthetic evidence and replayed host
results to check:

- Allowed file reads and writes work; hidden files and external retrieval remain
  inaccessible through every enabled capability.
- CLI termination also ends background work before host execution starts.
- Request parsing, ordinary errors, submission and failure paths preserve exact
  records and never execute an uncertain or partial request twice.
- Both arms receive identical initial inputs, share opening costs once and obey
  the same candidate and task-run allowances.
- Completed feedback becomes available in the next invocation, while failed
  evaluation or analysis stops further research.

Use focused checks, not a separate testing framework. The file-based roundtrip
record is `.artifacts/codex-research-comparison-20260921/file-cli-code-mode-latest-report.json`:
two native CLI invocations, a synthetic host evaluation between them, updated
evidence and prior scratch/receipt visible on the second invocation, followed by
submission. It used no real credentials or model calls. The separate two-arm
orchestration replay validated the earlier control-inclusive 220-run ceiling and
zero test dispatches. The candidate-only amendment requires focused checks of
control rejection, new-source allowances, no-evaluation submission and accounting.
Earlier real-time adapter checks do not validate this runner.

The live check is recorded in
`.artifacts/codex-research-comparison-20260921/subscription-check-h81ormvx/`.
The CLI read synthetic task/tool files, returned a valid request, closed, and
the host accepted `finish`. It dispatched no benchmark task. An earlier attempt
under `subscription-check-y_jtu1xv/` failed because the required stock Code Mode
host was disabled; both attempts and their reported usage remain recorded.

## Archived implementation

The active `loopblox.experiments.researcher_comparison` entry point has been removed.
Its source is preserved at
[`archive/researcher-20260921/researcher_comparison.py`](../archive/researcher-20260921/researcher_comparison.py),
alongside the retired controller at
[`archive/researcher-20260921/controller.py`](../archive/researcher-20260921/controller.py).
These files document the historical opening import, candidate-only amendment,
service recovery and analysis-only review; they are not a supported launcher for
new research. Each recorded campaign retains its own exact `implementation/`,
protocol, requests, receipts and costs. Do not rewrite those records or restart
the closed comparison. New sessions use the native adapter through the existing
research host and [current setup](running.md#native-codex-researcher).

## Reporting and later comparison

Report submitted sources, latest complete batch rankings, valid and failed
candidates, scored and missing outcomes, unused opportunities, evidence/Jev use,
and recorded usage. Separate shared opening spend, each arm's task-agent/user/Jev
spend and researcher usage. Preserve native CLI events and available usage for
every invocation, including failures. Native token totals may omit attempts or
other details; retain unknown fields and coverage limitations. Do not invent a
dollar charge for subscription usage or equate different tokenizers' counts.

The retired design proposed all 40 official telecom test tasks with two repeats
per unique L0/L1/selected-LoopBlox/selected-Codex source, at most 320 runs. That matrix
was never authorized or dispatched. A future evaluation must freeze its actual
sources and protocol separately, close research before final feedback and retain
the official scoring. **This archived experiment authorizes no test dispatch.**

Reused training results cannot establish generalization. One researcher run per
arm compares two realized outcomes; even a later test win does not establish the
average advantage of a researcher system. Independent repeated searches would
require a separately frozen extension.
