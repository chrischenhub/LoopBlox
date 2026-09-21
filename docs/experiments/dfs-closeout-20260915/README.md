# Retail DFS pilot: September 15 closeout

The latest recovery completed all 12 authorized task attempts: two opening runs and ten paired comparison runs. Both opening runs passed. In the comparison, the baseline passed 5/5 and the original loop04 starting source passed 3/5. No new task score is missing. These are development results; no validation or holdout was run.

| Branch / evaluated source | Loop passes | Baseline passes | Model calls: Loop / baseline | Submission |
| --- | --- | --- | --- | --- |
| loop04 / original start c0001 | 3/5 | 5/5 | 139 / 138 | Interrupted; no accepted submission. |
| loop06 / c0005 | 4/5 | 3/5 | 168 / 129 | Earlier submission preserved. |
| loop08 / c0002 | 5/5 | 5/5 | 132 / 119 | Earlier submission preserved. |

Each row uses its own paired batch. Five draws covered four distinct tasks in each batch under the historical sampling-with-replacement protocol. The rows do not form a ranking across branches. The current fixed-task protocol has not been rerun; see the [search guide](../../random-search.md). The [September 13–14 report](../bfs-dfs-20260914/README.md) records the original sampling error and BFS screening.

loop04 used its original inherited starting source with full context, full observations, and sequence decisions. The evaluated source is not the unsubmitted candidate from the preceding recovery. Its two failures were action-limit exhaustion and a completed run that failed verification. loop06's timeout remains a scored failure even though the environment reported reward 1. Candidate rationales do not establish causes.

After the task evaluations, the researcher requested baseline submission twice. The frozen submission guard rejected the complete paired comparison because it incorrectly required a baseline-only candidate list. The operator stopped the researcher at 00:31:19 America/New_York on September 15. The campaign remains interrupted, with no accepted loop04 submission. A subsequent local repair and offline validation do not change that historical status.

The latest recovery charged 357 model attempts: 317 for tasks, including simulated users, and 40 for research. One in-flight researcher request was interrupted and remains charged. No provider operational failure occurred during the 12 task runs. loop04 used its entire cumulative allowance of 74 task attempts.

Across all three DFS branches and their recovery history, the ledger retains 210 task attempts, 204 scored results, six missing scores, and 6,655 model attempts. These totals exclude the earlier BFS campaign. Holdout runs remain zero. Completed loop06 and loop08 records were preserved byte for byte.

[results.json](results.json) is the reviewed public data snapshot used by the website. Its comparison counts were checked against individual host-recorded outcomes and usage; cumulative totals come from the campaign accounting and closeout. It includes exact source paths and SHA-256 hashes. Raw records remain local under `.artifacts/tau2/dfs-top3-20260915-recovery-08/`; they are not downloadable from this report. Frozen records and implementations were not rewritten.
