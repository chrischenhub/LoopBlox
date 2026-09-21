# Retired bounded release research

Retired September 21, 2026. New work follows [experiment.md](../experiment.md),
which iterates Loops on one frozen benchmark. This page preserves the older
L0/L1/L2 comparison and its two-batch policy. Its launcher is preserved in the
[workflow archive](../archive/experiment-workflows-20260921/README.md), outside the
active package. It must not be used as the current launch path. Limits and "current"
settings below refer to this retired protocol, not new campaigns.

This telecom study compares a supplied reactive Loop (L0), a supplied Loop
that reviews completion proposals and returns on explicit terminal observations (L1), and the source selected by one researcher
(L2). It measures development outcomes and preserves evidence for a human review
before any final comparison. Keeping L0 is a valid result.

L1 preserves Critique feedback for further decisions while the environment is
open. If the initial or a full tool observation explicitly reports that the
conversation has ended, it returns a neutral termination message. This fixes the
observed post-conversation loop without treating a noisy contradicted verdict as
an automatic stop. The unchanged L0 lacks that guard, so the L0/L1 comparison is a
joint Loop contrast, not an isolated measurement of Critique. The guard does not
guarantee termination for repeated rejected completions while the environment is open.

`loopblox.experiments.release_research` is the executable protocol owner. It reuses
`ResearchSession`, the isolated controller runtime, the audited τ² runner, and the
mandatory Jev analysis stage. It has only `prepare` and `run` commands. These
commands, including preparation of a recovery, never dispatch official test tasks.

The retired [Codex researcher comparison](codex-research-comparison.md) reused
this development policy for two independent researcher systems with common
opening evidence. Its launcher is preserved in
[`archive/researcher-20260921/researcher_comparison.py`](../archive/researcher-20260921/researcher_comparison.py).
The current native adapter lives in `loopblox/research/codex.py`.

## Frozen development design

Use ten official telecom training tasks, one representative per recorded family,
chosen from the 74-task pinned official train split without consulting historical
outcomes. Selection is seeded and stratified by issue category and fault count;
the main development pool uses environment assertions, excludes prescribed action
paths and known integration groups, and requires a zero empty-trajectory reward.
The suite's `selection.json` records its exact selection rule, source audit,
exclusions and known exposure. Public task feedback
continues to exclude private user scenarios, evaluator assertions and reference
solutions.

The pinned official telecom test split contains 40 tasks: 28 use environment
assertions and 12 also require action checks. All 40 retain their original criteria
and order. These checks are deterministic; none requires NL grading. The release
entry point rejects unsupported or model-graded criteria before task dispatch.
The simulated customer and Jev still use models and consume budget.

The September 20 retail campaign remains an interrupted historical record. Its
last task exhausted all 64 task model calls before its NL grader could start.
The missing score remains missing. The telecom pivot starts a new experiment;
it does not relabel retail evidence, resume its researcher, or alter its budgets.

The opening evaluates L0 and L1 on all ten tasks (20 attempts). The first research
batch includes both controls and at most three new sources (at most 50 attempts).
The second includes both controls, the first batch's best source, and at most two
additional sources (at most 50 attempts). Duplicate identities are included only
once. Each comparison uses the same ten tasks, one run per source and task, with
rotated source order and fresh environments and workers. Candidates are frozen
before dispatch. Early submission is allowed; source counts are caps, not quotas.

A complete shared batch ranks sources by official passes, then known agent input
tokens, agent model calls, and original candidate order. Unknown usage is never
zero. An incomplete batch cannot establish a winner. Submission uses the latest
complete batch's best source. Jev judgments help locate evidence for investigation;
they do not replace official scores or establish the cause of a failure.

The current release uses `RELEASE_TASK_LIMITS`: **60 actions, 256 combined agent
and simulated-user model attempts, 65,536 output tokens and 900 charged seconds
per task**. The host meter owns time accounting; the upstream wall-clock timeout
does not independently consume excluded model-timeout waits. Critique-only loops
still consume model calls, output and time. Cumulative research time, model calls,
output tokens and task runs remain `null`. Jev uses the shared research ledger
after each task, so exhausting a task does not consume its analysis allowance.
Official deterministic scoring still runs after task exhaustion. All actual
usage and unknown measurements remain recorded. Individual requests retain their
frozen output settings and transport deadlines. Historical unlimited runs remain exact.

This changes spending limits, not the comparison design: ten tasks per shared
batch, one opening, two research batches, and at most three then two new sources
remain fixed. These source counts define the experiment; they are not a requirement
to use every slot. The earlier prepared campaign with finite caps remains exact
and is superseded by a newly frozen preparation, not edited in place.
Infrastructure failures stop the current episode. An unfinished or exhausted
researcher is not an explicit submission. The [recovery policy in AGENTS.md](../AGENTS.md)
owns authorization: after an actual fault in an already authorized experiment,
close the failed run, diagnose and repair it, perform focused checks, and recover
autonomously in a new frozen campaign with fresh researchers. Prior spend remains
recorded, and is subtracted wherever the frozen cap is finite; unlimited caps stay
`null`. Recovery preserves the capability,
data, scoring and final-review boundaries. Low scores or budget exhaustion do not
justify restarting, and repeated errors without progress must not trigger an
unbounded retry loop. This workflow does not create a background scheduler.

## Execution and review

Prepare from the working checkout with the benchmark's frozen host interpreter:

```sh
.artifacts/upstream/tau2-bench/.venv/bin/python -B -m loopblox.benchmarks.run_tau2 \
  prepare-telecom-release --output .artifacts/tau2/telecom-release-suite-NEW \
  --exclude-suite .artifacts/tau2/domain-subset-02

.artifacts/upstream/tau2-bench/.venv/bin/python -B -m loopblox.experiments.release_research \
  prepare .artifacts/tau2/telecom-release-research-NEW \
  --suite .artifacts/tau2/telecom-release-suite-NEW \
  --worker-image IMAGE_ID
```

Pass the local integration suite paths that actually exist; omit `--exclude-suite`
on a fresh checkout with no integration exposure. Preparation and empty-trajectory
audits do not dispatch model requests or benchmark task runs. Record any prior
exposure even when a task is retained in the complete official test split.

Preparation freezes source, suite, task selection, model settings, Jev configuration
and limits. Execute `run OUTPUT` using the frozen `OUTPUT/implementation` package,
with credentials loaded into the host environment. Frozen runs must never import
mutable checkout code. Each output directory is new; a failed run cannot resume
its Python continuation.

Prepare a recovery with `prepare NEW_DIRECTORY --previous OLD_DIRECTORY`, then
execute `run NEW_DIRECTORY` from its frozen implementation. The previous campaign
supplies the recovery provenance and prior spend; its records remain unchanged. A stopped
infrastructure failure after researcher startup also admits a fresh episode: it
restarts the opening and researcher, retains prior attempts privately for accounting,
and reduces the remaining new-source allowance. It does not resume the failed
researcher or inherit its partial-batch feedback.
The current release entry point rejects a retail predecessor. Historical campaigns
retain their own frozen entry points; domain changes require a new protocol.

An explicit user instruction may continue an interrupted opening using
`prepare NEW_DIRECTORY --previous OLD_DIRECTORY --continue-opening`. This carries
the completed prefix into a fresh host session, counts the single interrupted
attempt as a user-adjudicated failure, and dispatches only the unstarted suffix
under current release task caps. It never resumes a task worker. The original
campaign remains exact; the new public row records the adjudication separately
from its missing official verification, and the interrupted trace receives Jev
analysis before feedback is released. Prior costs enter cumulative accounting
once. The opening mixes historical and new limits and cannot establish a gain
under a uniform budget; subsequent complete research batches use common caps.
Ordinary recovery does not automatically authorize this disposition.

After a successful explicit submission, the top-level result becomes
`awaiting_review`. The selected source is `controllers/L2.py`; aliases identify
whether it is identical to L0 or L1. `research/public/evidence.json` links each
candidate's rationale, paired results, public traces and Jev records. The underlying
research session keeps its own closed-selection state.

A later proposed comparison is all 40 official telecom test tasks, two runs per
unique L0/L1/L2 source, at most 240 attempts. It requires a separate review and
launch. Known historical test exposure and train/test family overlap must be
reported; the complete test set is not globally unseen. Development selection on
ten reused tasks cannot establish generalization or a reproducible search gain.
