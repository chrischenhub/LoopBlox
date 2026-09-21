# Jev trace-label A/B v2 — September 20, 2026

## Result

**The pilot completed, but does not establish that Jev improves Loop modification
quality.** All nine planned comparison runs received official scores. A proposed
a changed Loop and passed 1/3 tasks; B retained the exact baseline and passed 2/3.
The separate baseline executions passed 0/3. B's higher score cannot represent an
improved source: B and baseline are byte-identical. This difference directly
demonstrates variation between executions of the same Loop on the same tasks.

B consumed fewer researcher calls, input tokens and raw-evidence reads in this
single pair. That is a useful descriptive efficiency signal, not an established
effect across independent researchers.

## Frozen conditions

- Fresh campaign: `.artifacts/tau2/jev-trace-ab-v2-20260920-01/`. No prior opening
  traces, Jev answers or researcher attempts were reused.
- FreeInference `deepseek-v4-flash`, temperature 0, for both researchers and the
  task runs; Jev `jev-1.13.0`, schema `segment-semantics-v2`.
- Three official retail training tasks, local IDs `0013`, `0022`, `0027`, mapped
  to official IDs `16`, `29`, `37`. These were selected **before dispatch** from
  recorded failures of the same reactive baseline in the earlier retail campaign.
  The protocol records selection evidence and file hashes. This is a deliberately
  failure-enriched sample, not a representative estimate of retail performance.
- A then B, frozen from seed 20260920; one researcher and at most one new local
  candidate per arm. Baseline retention was allowed. There were no independent
  researcher repeats or official test evaluations.
- Unlimited cumulative researcher time, model calls, actions and output tokens,
  as explicitly requested. Each task retained identical limits: 900 charged
  seconds, 40 actions, 64 model calls, 65,536 output tokens.
- One fresh shared opening batch: 0/3 passed. Task 0013 completed and failed;
  0022 and 0027 exhausted task budgets and failed. These outcomes were retained
  without replacement or reruns.
- Both arms received identical factual summaries, raw segments and full-trace
  access. A byte comparison verified all 115 shared evidence files. After
  removing B's measurement fields, segment-index contents were also identical.
  Both researchers closed with successful `finish_proposal` receipts before
  comparison dispatch. No research continuation or manual interruption was needed.

## Revised Jev evidence

Each input contained the initial public user request, latest public user message
before the segment, starting observation, proposed actions, complete resulting
observations and any recorded reasoning. There was no 600-character observation
cutoff. Component sequence remained researcher metadata; the available tool-name
list was omitted. No private simulator scenario, evaluator data or final task
score was sent to Jev.

The three measurements were progress and action effectiveness (0–3 Scores), and
recovery need (0–1 probability). The available-data predicate was removed. Of 92
segments, 91 were labeled and one completion-only claim was marked not applicable.
Full state length averaged 2,053 characters, with a maximum of 5,395. Jev used
125,356 input and 4,823 output tokens, with no failed requests.

One remaining input-design limitation appeared in the recorded batch: the two
budget-exhausted tail segments lacked resulting observations but still received
measurements. For example, `run-0002/s0040` received progress 1.61 despite having
no observed outcome. These are unsupported transition scores, not evidence of
effects. A future version should mark incomplete transitions unmeasured. This
pilot's frozen inputs and answers were preserved unchanged.

## Proposals and researcher behavior

| Measure | A: factual evidence | B: factual evidence + Jev |
| --- | ---: | ---: |
| New source | 1 | 0; retained baseline |
| Model calls | 20 | 8 |
| Input tokens | 1,084,861 | 307,559 |
| Output tokens | 2,086 | 916 |
| Successful raw-segment reads | 18 | 6 |
| Distinct raw segments read | 18 | 6 |
| Raw characters disclosed | 223,987 | 74,925 |
| Full-trace reads | 0 | 0 |
| Component-contract file reads | 0 | 0 |
| Wall / charged seconds | 64.33 / 64.33 | 33.49 / 33.49 |
| Final worker status | Completed | Completed |

B used 60% fewer researcher calls and 71.6% fewer researcher input tokens.
Jev's separate labeling usage above must be included when considering total
overhead; token counts across different models are not dollar prices. No monetary
cost was measured. Actual successful execution records own the read counts.

A proposed an exact-repeat guard. Its implementation has three substantive
problems: it compares action identity but does not compare result equality or
require no effects; it ends the entire task rather than attempting recovery; and
its fixed return text embeds a replacement-item explanation from one task. The
last issue violates the instruction requiring reusable source without embedded
answers or domain workflows. Candidate source was evaluated as submitted, without
post hoc repair or replacement; its scores are not acceptance of its compliance.

The guard fired on task 0013, which failed. It did not fire on 0022, which passed,
or 0027, which failed. The sole A pass therefore does not demonstrate a benefit
from its early-return mechanism. A's claim that termination would preserve an
opportunity to perform the final mutation also conflicts with its actual return.

B claimed the failures could not be addressed by a local composition change and
retained baseline. That impossibility claim was not established: the frozen
catalog exposed critique, reflection and planning components. Neither researcher
opened `component-contracts.md` despite the instruction to do so. Both accessed
raw segments only from run-0002, although all three task summaries were injected.
These limitations constrain any claim about the quality of their diagnosis.

## Paired task results

| Local task / official ID | Fresh baseline | A | B |
| --- | --- | --- | --- |
| 0013 / 16 | Fail | Fail; early-return guard fired | Pass |
| 0022 / 29 | Fail; task budget exhausted | Pass | Fail |
| 0027 / 37 | Fail | Fail | Pass |
| **Pass count** | **0/3** | **1/3** | **2/3** |

The frozen primary differences are B minus A: +1 pass; A minus baseline: +1;
B minus baseline: +2. These are descriptive counts from one pair of researchers
on three training tasks. B's source equality with baseline, A's implementation
and instruction failures, and different outcomes for the same source prevent a
claim that Jev produced a better modification. Same seeds and temperature 0 did
not yield identical model/user trajectories. No holdout or generalization claim
is supported.

| Comparison cost | Baseline | A | B |
| --- | ---: | ---: | ---: |
| Model calls | 121 | 90 | 90 |
| Input tokens | 925,029 | 652,568 | 619,577 |
| Output tokens | 9,920 | 6,180 | 6,855 |
| Wall / charged seconds | 307.54 / 307.54 | 164.12 / 164.12 | 154.80 / 154.80 |
| Scored failures | 3 | 2 | 1 |
| Unscored attempts / not started | 0 / 0 | 0 / 0 | 0 / 0 |

No infrastructure or verifier failure occurred. Budget exhaustion remains
distinct from normal completion and was scored as recorded by the official
runner. Faster failure is not automatically a better Loop.

## Provenance and accounting

Canonical raw root: `.artifacts/tau2/jev-trace-ab-v2-20260920-01/`.

- `protocol.json` and `implementation/`: frozen models, tasks, limits and 46
  implementation-file hashes, verified unchanged after execution.
- `opening/public/evaluations/e0000/`: the fresh shared opening and its public traces.
- `semantic/`: exact Jev states, questions, answers and usage.
- `A/`, `B/`, `controllers/`: immutable sources, rationales, closing receipts and
  researcher invocation records.
- `result.json` and `comparison/`: all nine comparison rows and original executions.
- `analysis.json`: derived counts and source audit; regenerate with the local
  `derive_analysis.py`. `report.md` is the driver's basic derived report.
- `opening/private/research-usage.json`, both arm ledgers and
  `private/comparison-usage.json`: non-overlapping main-model accounting.

The shared opening used 136 main-model calls, 1,186,298 input and 11,132 output
tokens. Including it once, both researchers and all comparison attempts, this
fresh pilot used **465 main-model calls, 4,775,892 input and 37,089 output tokens**.
All usage was known. Jev usage is reported separately above. Earlier pilots are
separate historical experiments and are not included in this fresh-run total.

The initial local image-tag lookup failed during preparation and was repaired
before the protocol was created; it consumed no model calls. Historical campaign
records were not changed. This experiment did not promote either proposal into
the project's supplied baseline.
