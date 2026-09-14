# BFS + Top 3 DFS: September 13–14, 2026 pilot

This campaign exercised random starts, batch screening, local search, accounting, and recovery. **It used development tasks only, with no validation or holdout, and does not establish stable optimization gains.** This public summary is current through September 14, 2026. Complete frozen environments and raw records remain in local `.artifacts/` and are not distributed with the source repository.

## Confirmed protocol deviation: sampling with replacement

The user required sampling without replacement. The campaign instead retained repeated `random.choice` calls in `ResearchSession` and wrote that old rule into the frozen protocol. The requirement was missed in implementation, protocol preparation, and preflight checks. This was an experiment execution error.

The first BFS evaluation, `e0001`, already recorded `0013, 0004, 0004, 0007, 0008` with the prefix `retail-development-` and `repeats=1`. Duplication occurred during initial sampling, independently of service retries, recovery, or explicit repeated measurements. Each candidate's five planned runs covered four distinct tasks; `0004` carried 2/5 of the score weight.

The scores and Top 3 below are observations under that incorrect sampling rule. They cannot be presented as screening on five distinct tasks, and corrected sampling may produce a different Top 3. Dropping the duplicate row would not supply the missing fifth task. Original data, missing scores, and spend remain unchanged.

DFS reused the sampler. The submitted loop06 branch's final `e0007` and loop08 branch's final `e0005` also covered only four distinct tasks. Subsequent changes first removed sampling with replacement, then made BFS/DFS reuse a complete list of explicit task IDs. The [current guidelines](../../random-search.md) describe that unrun configuration. Those changes do not alter this page's historical protocol, results, or costs.

## Experiment conditions

- A ten-task τ²-bench retail development subset drawn from previously used development data. Deleting old results did not remove prior exposure.
- Task agent, researcher, and simulated user used `deepseek-v4-flash` at `https://freeinference.org/v1`, with temperature 0. Per-request output allowances were 8,192 for the agent/researcher and 2,048 for the simulated user.
- Each task allowed 300 seconds, 40 actions, 64 model calls, and 65,536 output tokens. Simulated-user calls counted toward those limits.
- BFS seed: 20260913; DFS seed: 20260914. Batches were drawn uniformly with replacement and shared across candidates, paired by draw position. One duplicate among the five BFS draws left four distinct tasks.
- The shared [baseline source](../../../controllers/reactive.py) and candidates used the same component boundary, tools, and per-task limits.

## Random screening and initial local research

Ten immutable Loops and the baseline ran on the same five draws. Only fully scored candidates were ranked by passes and cost. Missing scores were not filled in as failures to make a candidate eligible.

| Loop | Passes / planned runs | Model calls | Outcome |
| --- | --- | --- | --- |
| baseline | 4/5 | 102 | Separate reference. |
| loop06 | 5/5 | 122 | Top 1. |
| loop08 | 4/5 | 112 | Top 2. |
| loop04 | 2/5 | 203 | Top 3. |
| loop09 | 2/5 | 251 | Fully scored. |
| loop01 | 2/5 | 282 | Fully scored. |
| loop05 | 1/5 | 289 | Fully scored. |
| loop07 | 1/5 | 297 | Fully scored. |
| loop02 | 0/5 | 246 | Fully scored. |
| loop03 | 0/5 | — | Four failures and one missing score; excluded from ranking. |
| loop10 | 3/5 | — | One failure and one missing score; excluded from ranking. |

Costs for candidates with missing scores remain in the ledger; dashes mean they are not displayed here. Each Top 3 branch completed initial free local research. loop06 and loop08 retained their starting Loops; loop04 changed brief observations to full. DFS order was not yet enforced. All three submitted, but historical screening gaps kept the BFS campaign status `incomplete`.

## Explicit DFS

Each branch started from one of those submissions and its own public experience. Limits were six new nodes, depth three, and two children per node. Every parent-child edge completed a paired batch of five shared draws before expansion; lower scores did not automatically prune descendants. The cap was 72 task attempts per branch, including opening trials, parent-child comparisons, the final baseline comparison, and prior failed attempts.

| Branch | Completion | Last shared batch: candidate / baseline | Model calls: candidate / baseline |
| --- | --- | --- | --- |
| loop06 | Six new nodes, depth three; submitted c0005. | 4/5 / 3/5 | 168 / 129 |
| loop08 | Four new nodes, depth three; submitted c0002. | 5/5 / 5/5 | 132 / 119 |
| loop04 | No completed submission; `rate_limit` blocked the latest recovery's opening trial. | No final pair. | — |

The submitted sources remain in their original campaigns' `selected-controller.py`. loop06 retained completion review and failure/repetition reflection, clearing explicit reflection guidance for the next iteration after three consecutive anomalies. That does not erase full-context history. Mechanism explanations in candidate source are the candidate's claims. loop08 added reflection after tool failures following an opening Plan.

One loop06 timeout had raw environment reward 1 but was scored as a failure under the host's final status; its result cannot be rewritten as 5/5. Prior failed research consumed loop08's allowance, reducing its actual new-node count below six. The two branches used separate final batches, so 4/5 versus 5/5 does not directly rank them.

## Total spend and interruptions

| Stage | Task attempts | Scored | Missing scores | Model calls |
| --- | ---: | ---: | ---: | ---: |
| BFS screening, initial Top 3 research, and recovery | 110 | 107 | 3 | 3,814 |
| Explicit DFS and recovery | 150 | 148 | 2 | 4,863 |
| Total | 260 | 255 | 5 | 8,677 |

Model calls include the researcher, task agent, and simulated user. Completed copies in recovery chains are counted once. Cumulative DFS attempts were 72 for loop06, 64 for loop08, and 14 for loop04.

The latest DFS status is `interrupted`. loop04 first encountered `service_not_ready`, then an HTTP 429 temporary IP block during recovery. Earlier problems included scheduler termination when a managed command session closed and repeated saves of the same existing candidate. Later runs used independent process sessions. The fixed researcher gained a duplicate-save guard: the second consecutive duplicate triggers reflection, and a third triggers an error.

The repaired loop08 run made only one duplicate save, so the guard did not fire and cannot explain its completion. The 14-minute recovery rule applies only to actual `service_not_ready` failures, not HTTP 429. An external automatic wakeup was also missed during this campaign; unattended recovery still needs validation.

## Evidence limits and provenance

Numbers come from frozen campaign reports, host records, and aggregate ledgers. [provenance.json](provenance.json) lists relative source paths and SHA-256 hashes. Paths are relative to local `.artifacts/`, not downloadable artifacts in a fresh clone. This summary alone cannot support independent inspection of unpublished raw traces. Hashes let holders of the original records verify their copies.

Current source includes later engineering changes and is not treated as the implementation used for these results. Each original campaign's `implementation/` preserves its incorrect sampler. The current fixed-task protocol requires a new experiment; see the [guidelines](../../random-search.md).

Formal conclusions still require unseen tasks, independent repeats, frozen models and budgets, and complete reporting of search and final-task costs. Historical missing scores, failures, and unsuccessful changes remain part of the results.
