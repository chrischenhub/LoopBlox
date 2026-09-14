# LoopBlox website

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
contracts, and the exact baseline Python source. A rebuild replaces this derived
output.

The website is an ordinary directory in the main repository. Local deployment
metadata under `.openai/` is ignored by Git and is not required to build or preview.
Configure your own hosting destination when publishing. Publish only `dist/`;
experiment data, credentials and source snapshots are not part of the static output.

Bundled fonts retain their [own licenses](assets/fonts/README.md).
