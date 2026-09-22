# LoopBlox website

## Local chat and Loop view

`chat.html` is a local two-pane playground: conversation on the left, the current
turn's reactive Loop source, stage diagram, and invocation trail on the right.
The chat uses the existing model gateway and `ControllerRuntime`, with a fresh
isolated worker per message. Prior user messages and completed replies become
the next turn's conversation context. This is a chat demonstration, with no
benchmark scoring, automatic research, or controller editing.

After configuring `.env` and starting Docker with `python:3.12-slim` available:

```sh
python3 -B -m loopblox.chat serve --port 8766
```

Open http://127.0.0.1:8766/. The server binds only to loopback. Keep that process
running while using the page; Ctrl+C closes the active worker and server.
No static build is needed. This local page is excluded from `dist/` and is not
part of the hosted introduction.

Each message freezes `controllers/reactive.py` and the reference notes. The only
tool reads the project, concepts, or component reference; it cannot edit files or
access benchmark tasks. Limits are 180 charged seconds, eight tool actions,
12 model attempts, and 32,768 output tokens per turn, with at most 4,096 requested
output tokens per model call. Existing timeout retry/accounting rules apply.

Progress is read from the runtime's atomic trace snapshots. Source highlights map
the baseline's unique component call sites to recorded invocations; the view does
not compile a graph or manufacture transitions. Fast calls remain selectable in
the trail. Each stage retains its invocation counts, and chat replies list the actual tool
outcomes. A tool name comes from its host-assigned action ID matched to the recorded
execution result; a proposed but unexecuted action does not appear as a tool result.
Replies appear after outer `run(env)` returns and worker cleanup finishes; provider
token streaming is not implemented. Select an earlier reply to inspect
its recorded source and calls, or choose Follow latest to return to the current run.

Conversations, exact Loop sources, reference notes, traces, and usage ledgers stay
under Git-ignored `.artifacts/chat/`. New chat preserves prior records. The browser
stores only the current conversation ID. Stop retains interrupted calls and their
reserved cost. One turn runs at a time across this local server.

## Hosted introduction

The English introduction to domain loop auto research. It shows the baseline and
first three iterations of the current telecom campaign, then explains continuous
research, the reactive task-loop baseline and the component library. The dark pixel interface uses an ink-green
canvas with a faint pixel-dither field, square panels with terminal title bars and corner
ticks, and pixel-shadowed buttons. Departure Mono carries the wordmark, labels, and
diagrams, JetBrains Mono the code and component identifiers, and Source Serif 4 the
headings and running prose. SVG paths show continuation, branching, and research
boundaries. Candidate diagrams are reviewed summaries of saved Python, never
executable controllers or live traces. The evolution view is static and has no
polling, animation, graph editor or backend.

## Content ownership

- The parent `README.md` owns the project direction, study question, and status.
- `experiment.md` owns the continuous protocol. The site does not dispatch research
  or final evaluations.
- [The evolution snapshot](snapshots/evolution.json) derives outcomes, agent usage,
  component counts and selection checkpoints from the campaign's public records.
  It includes source paths, hashes, exact candidate Python, rationales and a UTC
  snapshot time. This is a bounded view of four evaluated sources, not cumulative
  campaign accounting; recovery attempts are not included in these candidate costs.
- `evolution.py` owns the reviewed presentation of those four exact source hashes.
  It extracts the snapshot and renders the static cards. Source changes require
  review of the diagrams; arbitrary Python is not compiled into a control graph.
  The top rail shows incumbent retention/replacement, not inferred code ancestry.
- The [September 15 closeout snapshot](snapshots/experiment-report.md) and
  [result snapshot](snapshots/results.json) preserve the historical experiment
  retained as downloadable files without a homepage section. Its scores and cumulative counts derive from that
  JSON, whose provenance identifies the raw host records. These exact snapshots
  remain unchanged by `--refresh-notes`; the original reports and protocols have
  moved to the local, Git-ignored `archive/` directory.
- The parent `loop.md` owns the definitions and experiment boundaries.
- `loopblox/runtime/components.py` owns the component catalog. Family membership, descriptions,
  contracts, and counts are generated from its frozen JSON catalog.
- `build.py` owns `PLAIN_NAMES`, the plain-language label shown for each component in
  the diagrams, family lists, and contract panel. The identifiers stay visible beside
  them. The build fails if the map and the catalog disagree, so a new or renamed
  component must be given a label before the site can be published.
- `controllers/reactive.py` owns the baseline source. The build checks its component
  sequence against the reviewed baseline illustration; it does not compile graphs.
- `index.html` contains the reviewed English introduction and SVG illustrations.
  Update its summaries when their canonical sources change. Do not turn pilot
  validation into an optimization claim.

`snapshots/` preserves the exact project and concept documents, generated component
catalog / contracts, and baseline source used for this version. Project documents
remain build inputs and are not published. Refreshing snapshots does not translate
or rewrite the reviewed English introduction automatically.

## Build and preview

From the parent repository:

```sh
python3 -B site/build.py --refresh-notes
python3 -m http.server 8765 --bind 127.0.0.1 --directory site/dist
```

To build only from the checked-in snapshots, run `python3 -B site/build.py` from
the repository root.

To explicitly replace the first-three-round snapshot from the reviewed campaign:

```sh
python3 -B site/build.py --research-records .artifacts/tau2/continuous-telecom-20260921-recovery-02/research/public
```

This reads public records only and never writes to the campaign. Incomplete
feedback is rejected. Checkpoint status and failure counts remain in the downloadable
snapshot without separate status lines on the cards. Ordinary builds and `--refresh-notes` retain
the saved research snapshot; neither follows a running campaign automatically.

There are no third-party runtime dependencies. The generated `dist/` contains the
English page, locally served fonts and their licenses, downloadable component
contracts, the exact baseline and candidate Python sources, the evolution snapshot, and the historical experiment report
and aggregate results with source hashes. Repository-only links are removed from
the deployed report. A rebuild replaces this derived
output.

The website is an ordinary directory in the main repository. Local deployment
metadata under `.openai/` is ignored by Git and is not required to build or preview.
Configure your own hosting destination when publishing. Publish only `dist/`;
raw task traces, private experiment data, credentials and implementation snapshots
are not part of the static output.

Bundled fonts retain their [own licenses](assets/fonts/README.md).
