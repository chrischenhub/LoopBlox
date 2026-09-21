# Retired domain Loop study proposal for τ² and τ³

Retired September 21, 2026. The current [research protocol](../experiment.md)
iterates Loops on one frozen benchmark. The multi-condition studies, changing
task batches and retail launch commands below preserve a superseded proposal;
they are not the current roadmap or instructions for new runs. Their implementation
is preserved in the [workflow archive](../archive/experiment-workflows-20260921/README.md),
outside the active package.

Proposed protocol, September 14, 2026. **The complete multi-condition lifecycle below is not implemented or validated.** A narrow retail implementation is described in section 9. Current integration and the next implementation milestone are recorded in [README.md](../README.md). This document owns the proposed experiment design; a run must freeze its settings before execution.

The study asks whether a domain Loop can improve through initial training and subsequent task experience, and whether those improvements transfer to unseen tasks at an acceptable total cost. Training searches Python Loop compositions with fixed model weights. The researcher, component library, tool behavior, policies, and evaluator stay fixed within each campaign.

The scope is τ² and τ³ customer-service tasks, evaluated separately by domain and benchmark version. Each task is a complete customer interaction. The outer researcher searches the Loop that handles those tasks. Its development set consists of customer-service tasks, not a separate class of construction problems.

[loop.md](../loop.md) owns behavioral definitions and experiment boundaries. [AGENTS.md](../AGENTS.md) owns execution, isolation, accounting, and evidence invariants. [The BFS/DFS guide](random-search.md) describes an existing development-only search configuration that can inform the search stage; it does not execute this lifecycle.

## 1. Domain conditions

Run each benchmark-version/domain combination as a separate condition, with its own data split, initial search, Loop lineage, experience, and budget. The first implementation uses the existing τ² retail and telecom integrations. Other rows require integration and task audits before execution.

| Domain | τ² condition | τ³ condition | Main task behavior |
| --- | --- | --- | --- |
| Retail | Integrated; lifecycle proposed | Planned | Order changes, returns, and exchanges |
| Telecom | Integrated; lifecycle proposed | Planned | Troubleshooting with agent and simulated-user actions |
| Airline | Planned | Planned | Booking, changing, and canceling travel |
| Banking (`banking_knowledge`) | Outside this version's study | Planned | Retrieving applicable banking rules and completing supported service tasks |

The initial scope is text interaction. Voice and audio-native execution require a separate protocol. Domain names describe the available business surface; the audited task subset determines which behaviors a result actually measures.

Pin the official source commit, task files, database, policy or knowledge corpus, dependencies, user simulator, and grading configuration separately for each condition. Audit each task's actual reward basis and empty-trajectory outcome. A newer benchmark version can change both tasks and scoring; do not treat τ² and τ³ scores as interchangeable or claim improvement by switching versions. See the [official τ benchmark repository](https://github.com/sierra-research/tau2-bench) and its [evaluation documentation](https://github.com/sierra-research/tau2-bench/blob/main/docs/evaluation.md); frozen run files take precedence over these moving links.

No Loop, experience, or generated task crosses domains or versions in this study. The existing specialist/mixed-domain comparison remains a separate experiment. Report per-domain results before any aggregate; an optional aggregate must declare its weighting and cannot hide a domain regression.

## 2. Data roles and exposure

Before initial search, divide eligible task families into three disjoint pools:

All future training and development questions must come from the benchmark's
official train split. This includes `D0`, new-task learning batches and cases
admitted for later development. Preserve the official membership in the frozen
manifest; local labels cannot turn official test into training data. Keep official
test for final evaluation and disclose prior exposure. Historical custom splits
and their results remain unchanged.

| Pool | Purpose | Feedback access |
| --- | --- | --- |
| Initial development set, `D0` | Build the first Loop and provide a fixed regression set | Public task-run traces and permitted scores are available during research |
| Ordered new-task batches, `U1 ... UR` | Measure performance before learning from each batch | Future batches remain unavailable; permitted feedback is released only after the batch closes |
| Final holdout, `H` | Evaluate frozen versions after all research ends | Tasks and feedback remain sealed throughout research |

Group related task variants before splitting. Keep known integration tasks and previously exposed task families out of claims about unseen performance. Record the source, family, split, and prior exposure of every task. Fix batch order and the number of rounds before search; conditions share these assignments.

Exposure and permission to execute a task are separate facts. A researcher that reads a trace has seen evidence about that task even if its condition cannot add the task to development evaluation. Record both. Once a new-task batch has supplied learning feedback, it is no longer unseen for later versions.

Freeze each round's development set before starting its researcher. Admit new tasks only between rounds. A generated variant inherits its source family's exposure history and never becomes independent holdout evidence. If a proposed task overlaps a still-sealed family, the host excludes it from admission and records the exclusion privately without exposing that family. Use a predeclared family rule rather than inspecting future failures to choose splits.

These are custom research splits. They do not define an official full-benchmark score. A fixed sequence of simulated tasks studies adaptation to newly revealed cases; a claim about changing business policies requires a separate environment-change condition.

## 3. Initial training and subsequent rounds

Use the shared reactive baseline from `controllers/reactive.py`. Initial research searches on `D0`, closes its worker, and freezes a selected `L0` and its permitted research evidence. Fork the experimental conditions below from this same result within each independent repeat. Preserve the baseline as a separate fixed reference.

For round `t`:

1. Freeze each condition's current Loop `L(t-1)` before revealing `Ut`. Run it on every task in that batch, with fresh environments and workers. Run the reactive reference on the same tasks. Record outcomes before any feedback from this batch can influence an update.
2. Close the entire batch across conditions. Save immutable results and release only each condition's allowed feedback. No condition reads another condition's traces or candidates.
3. Prepare the allowed experience and task additions. Freeze the next development set and all research inputs. Task proposals that have not passed admission checks remain proposals.
4. Start a fresh research episode from the preceding submitted Loop, using the same fixed researcher and component boundary. Compare proposed candidates with the incumbent on complete shared development batches. Freeze the selection before it can serve another new-task batch.
5. Adopt the submitted candidate only under the predeclared selection rule; otherwise retain the incumbent. Record either outcome, the evidence, spend, and reason. Continue with the next batch.

Task-local recovery, reflection, and further tool calls remain behavior inside the frozen task Loop. Cross-task updates happen after worker closure. A campaign is a sequence of episodes and evaluations; it does not change the definition of a Loop or resume a completed Python continuation.

Before execution, specify how paired development outcomes, cost, ties, missing scores, and the incumbent determine adoption. Do not treat a single higher development score as proof of generalization. Use the existing failure and exhaustion semantics: an unsuccessful researcher or infrastructure fault stops dispatch; an exhaustion fallback is recorded distinctly from a completed submission. The [recovery policy in AGENTS.md](../AGENTS.md) governs recovery from actual run faults in an already authorized experiment, without resetting budgets or changing the frozen data, capability, scoring or review boundaries.

Final holdout begins only after the last update and all researchers have closed. Evaluate the reactive baseline, `L0`, and each condition's final selected Loop on the same holdout tasks. Any additional checkpoints must be chosen before seeing holdout results. Identical sources may share recorded evaluations with explicit aliases. Holdout results never choose a new incumbent or return to later research in this campaign.

## 4. Experimental conditions

| Condition | What continues after initial training | Development evaluations in later rounds |
| --- | --- | --- |
| Frozen Loop | Keep `L0`; no further research | None |
| Loop only | Inherit the incumbent source | `D0` only |
| Loop + experience | Also inherit cumulative permitted research evidence and completed new-task traces | `D0` only |
| Loop + experience + tasks | Also admit completed new-task cases and validated trace-derived variants | `D0` plus admitted tasks |

All active search conditions can inspect traces from their current development evaluations. Loop-only research does not receive historical notes or new-task feedback. Experience is researcher input and must not be embedded in candidate comments or injected into the task agent's prompt. The full condition adds the ability to rerun admitted cases and variants under the official environment, beyond reading their historical traces.

Compare Loop only with Frozen Loop to measure further search. Compare Loop + experience with Loop only to measure the effect of historical evidence. Compare the full condition with Loop + experience to measure executable task-set expansion under the same total improvement budget. That last comparison includes task preparation and changed task coverage; it does not isolate the quality of the generator alone. A later ablation can distinguish replaying original cases from generating variants.

Freeze equal per-round improvement caps for the three active conditions. Task generation, checking, and any model-assisted review consume the full condition's cap, leaving less for candidate search. Record actual spend and unused capacity. Frozen Loop has no post-training search cost; report that difference rather than inventing matched work. Initial training is shared within a repeat: count its actual cost once in the campaign ledger and disclose the same initialization cost when estimating each condition's standalone cost.

BFS, DFS, or free researcher search can implement a search stage, but the chosen method and candidate-selection rule must match across conditions. The existing five-task BFS/DFS protocol cannot automatically run on these changing datasets; its use requires an explicitly recorded implementation change. Keep the initial baseline and model choice fixed across independent repeats, while recording each repeat's seeds and initial search result.

## 5. Trace-to-benchmark admission

A trace can support a failure hypothesis, retrieval guidance, or a regression case. It is not an authoritative answer. Keep experience summaries separate from executable task proposals.

For a completed τ task, the host already has the original task and environment. Admitting that original case means granting development access to its frozen definition; it does not require reconstructing it from the trace. Generating variants is useful when a failure suggests missing coverage, such as a customer correcting earlier information or a policy exception requiring more evidence.

A proposed new task must identify:

- Its source traces, parent task family, and the behavior it is intended to test.
- A user goal and simulator instructions, with a reproducible initial state.
- The frozen policy or knowledge evidence supporting the expected outcome.
- Evaluation criteria and their active reward basis, with a checked valid solution.

The host validates the task schema, state construction, supported tools, and policy consistency. Run a valid reference solution, an empty trajectory, and a targeted incorrect behavior to check the scoring distinction. For a legitimate no-mutation task, an unchanged database is insufficient evidence of success; confirm the active communication or other criteria distinguish an adequate response. Current subset exclusions continue to apply until a new audited condition explicitly expands them.

The first task-expansion experiment uses researcher proposals with human review of policy and scoring. Record review effort and rejected proposals. Fully automatic admission is a later condition and cannot be claimed from this study. Task authors and reviewers do not optimize their criteria against final holdout outcomes.

After approval, the host stores the task, state, evidence provenance, review decision, and evaluator version immutably. Only model-visible task content and permitted evaluation feedback enter research. Private simulator instructions, reference actions, and evaluator internals remain outside researcher-readable files. The task generator receives only explicitly allowed inputs; the host or reviewer supplies private criteria as needed.

Rerun new Loops in the interactive environment. Replaying fixed tool responses cannot evaluate a Loop that takes a different action. Score complete task outcomes; any required action matching must follow the task's explicit reward basis. A new API fault or unsupported business operation requires a separately frozen environment change, beyond task generation.

## 6. Feedback and accounting

The host owns authoritative outcomes. Feedback released after a new-task batch can include the permitted task score, agent-visible conversation, tool results, and public invocation records. Release it as explicitly authorized learning evidence in the next episode. This extends current development-evidence export; it does not open final evaluation or simulator-private ledgers.

Charge actual model attempts for the researcher, task agent, simulated user, graders, and task preparation, as applicable. Record tool work, wall time, known price-based cost, and human review effort separately. Preserve unknown usage and prices as unknown. Parent trace summaries and inherited evidence do not create additional spend. Search, new-task measurement, and final holdout have separate ledgers with a combined total; none may omit failed or interrupted attempts.

Fix per-task limits across conditions and stages. Within a comparison, candidates run on identical tasks and repeats with rotated order and fresh state. Task-family counts measure coverage; repeats measure run variability. A fresh random seed does not make an already exposed task unseen.

## 7. Reporting

Report each benchmark-version/domain condition separately, including:

- Initial training improvement from the reactive baseline to `L0`.
- Each round's performance on `Ut`, measured before learning from that batch, and cumulative performance across the sequence. Include the frozen `L0` and reactive references.
- Final paired holdout outcomes for all predeclared versions, with uncertainty across independent research repeats and task families.
- Performance on fixed `D0` to show regressions, labeled as development evidence.
- Candidate adoption or retention, task additions and rejections, exposure history, actual costs, unused budgets, failures, and missing scores.

Do not select the best round retrospectively using new-task or holdout scores and call it the final policy. A rising development score alone cannot establish improvement. Extra computation, changing dataset difficulty, and source-family overlap must remain visible in the comparisons.

This study evaluates sustained improvement of task Loops under a fixed researcher. Evidence that the researcher itself becomes better at producing improvements requires a separate comparison with matched starting Loops, data, and budgets.

## 8. Implementation order and run readiness

First implement fixed-data rounds for τ² retail and telecom, separately, with the Frozen Loop, Loop only, and Loop + experience conditions. Reuse `ResearchSession`, immutable candidates, isolated workers, source snapshots, accounting, and recovery. Add the missing new-task scheduling and feedback-release behavior around those mechanisms.

Then add reviewed task admission and the full condition. Integrate and audit τ³ domains and τ² airline independently before applying the same protocol. Documentation does not authorize an unimplemented command, an expanded component catalog, or a different benchmark evaluator.

Before a formal run, freeze domain/version pins, audited family assignments, `D0`, ordered batches, `H`, batch sizes, round count, search method, selection rule, exposed components, model settings, all caps, task-admission rules, feedback access, independent repeats, and the analysis plan. Do not inherit the pilot's five-task size, one-repeat setting, or budgets as formal defaults. Save the exact protocol and implementation with the run. Existing historical campaigns retain their original data and claims.

## 9. Historical retail request: three new training batches

The active educational release now uses telecom, as specified in [README.md](../README.md)
and [the release protocol](release-research.md). This section preserves the earlier
retail design and its reproduction commands; it does not authorize a new retail run.

The September 15 request defines a narrower, single-lineage experiment. Initialize
`L0` with the final submitted loop08 candidate (`c0002`) from the preserved DFS
campaign. Inherit its source only; old pilot traces include official test tasks and
are not admitted as new research experience.

Use the pinned official retail `split_tasks.json`: the first 30 train IDs in its
file order, divided into three consecutive batches of ten. Each round executes
only its newly opened ten tasks, while retaining the preceding submitted source
and cumulative permitted training experience from this campaign. The opening
baseline/incumbent comparison closes on the whole batch before a fresh researcher
receives its feedback. Every candidate comparison runs baseline, incumbent and
candidate on those same ten tasks, omitting duplicate sources/IDs. Adopt a
replacement only for more paired passes, or equal passes with fewer model calls;
retain the incumbent on a full tie. A completed submission is required to advance.

After all three researchers close, compare the reactive baseline, `L0` and the
final `L3` on all 40 official test tasks, once per source/task. Identical sources
share evaluations with explicit aliases. No test feedback returns to training and
no additional checkpoint is chosen from test scores.

This exact task selection expands the earlier audited subset: retain NL assertion
tasks, handoffs, related variants and cases whose empty environment state scores
positively. Audit and report them without silently substituting tasks. Official
evaluator prompts and reward rules are retained; the configured user model also
serves as the NL grader, replacing the upstream default grader model. Grader
requests stay private, run after worker closure, and consume the existing task
and research budgets. A missing or incomplete assertion result is a verifier
failure. This is a custom evaluation configuration, with known historical test
exposure and possible family overlap; it is not an untouched official test score
or a causal comparison of inheritance conditions.

The run's `protocol.json` freezes the candidate cap and budgets. Current code is
`loopblox.experiments.retail_rounds`, using `ResearchSession`, the inheritance
episode/recovery lifecycle and the existing fixed comparator. This implements
the requested three-batch run, not the other conditions or generated-task admission.

The requested timing revision uses 900 charged seconds per task. Recognized API
timeout attempts and their retry waits are excluded from both task and research
time; successful requests and other work remain charged. Record wall time and
excluded waits separately, retaining every attempt's call/token cost. The shared
gateway owns these rules (see AGENTS.md); the τ² default limits are defined once
in `loopblox/benchmarks/tau2.py`. Existing frozen 300-second campaigns remain exact;
applying the revision to a recovery requires a new, explicitly amended snapshot.

```sh
.artifacts/upstream/tau2-bench/.venv/bin/python -B -m loopblox.benchmarks.run_tau2 \
  prepare-retail-rounds --output .artifacts/tau2/official-retail-suite

.artifacts/upstream/tau2-bench/.venv/bin/python -B -m loopblox.experiments.retail_rounds \
  prepare .artifacts/tau2/retail-rounds-001 \
  --suite .artifacts/tau2/official-retail-suite \
  --initial-source PATH_TO_SUBMITTED_LOOP --candidates 2

PYTHONPATH=.artifacts/tau2/retail-rounds-001/implementation \
.artifacts/upstream/tau2-bench/.venv/bin/python -P -B -m loopblox.experiments.retail_rounds \
  run .artifacts/tau2/retail-rounds-001
```

Preparation makes no provider requests. After an actual run fault, follow the
[AGENTS.md recovery policy](../AGENTS.md): close the failed run, diagnose and repair
the fault, and perform focused checks before starting a new frozen campaign with
fresh researchers. For recovery without an implementation change, run this
campaign's frozen `retail_rounds resume NEW_DIRECTORY --from-campaign OLD_DIRECTORY`,
then launch the new frozen implementation. Any repair belongs in the new snapshot
with its changes recorded, never in the old campaign. Completed episodes are
preserved exactly; unfinished episodes restart within their remaining caps. Final
comparison recovery runs only rows that never started, retaining prior missing
scores and costs.
