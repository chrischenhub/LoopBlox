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

The English introduction to domain loop auto research. It explains the research
process, the reactive task-loop baseline, the approved component library, and the
planned retail / telecom / mixed-domain study. The dark pixel interface uses an ink-green
canvas with a faint pixel-dither field, square panels with terminal title bars and corner
ticks, and pixel-shadowed buttons. Departure Mono carries the wordmark, labels, and
diagrams, JetBrains Mono the code and component identifiers, and Source Serif 4 the
headings and running prose. SVG paths show continuation, branching, and research
boundaries; they are illustrations, never executable controllers or live traces.

## Content ownership

- The parent `README.md` owns the project direction, study question, and status.
- The [September 15 closeout](../docs/experiments/dfs-closeout-20260915/README.md)
  and its `results.json` own the latest public experiment summary. The website
  freezes exact copies under `snapshots/`; `--refresh-notes` updates them. All
  displayed scores and cumulative counts derive from that JSON, whose provenance
  identifies the raw host records. A normal build does not read raw experiment data.
- The current BFS/DFS [experiment guideline](../docs/random-search.md) owns its
  fixed-task pilot settings. The site's holdout diagram describes the planned
  domain study; it is not a record of validation or holdout in that pilot.
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
There are no third-party runtime dependencies. The generated `dist/` contains the
English page, locally served fonts and their licenses, downloadable component
contracts, the exact baseline Python source, and the reviewed experiment report
and aggregate results with source hashes. Repository-only links are removed from
the deployed report. A rebuild replaces this derived
output.

The website is an ordinary directory in the main repository. Local deployment
metadata under `.openai/` is ignored by Git and is not required to build or preview.
Configure your own hosting destination when publishing. Publish only `dist/`;
experiment data, credentials and source snapshots are not part of the static output.

Bundled fonts retain their [own licenses](assets/fonts/README.md).
