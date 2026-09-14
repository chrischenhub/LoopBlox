# Pinned sources and third-party licenses

These versions support existing analyses or experiment environments. They are not claims about the latest upstream releases. The source analysis did not execute native harnesses or establish improvements to them.

## Harness behavior analysis

The analysis dates to September 6, 2026. At that time, the three open-source checkouts were verified as clean and their full commit SHAs recorded. The [behavior decomposition](../harness-decomposition.md) links to specific lines in those versions. Upstream source copies are not distributed with this repository.

| Project | Pinned source and main entry point |
| --- | --- |
| Pi | [b8b873b9872db04a938fb4357b5e8e824ddc051c](https://github.com/earendil-works/pi/tree/b8b873b9872db04a938fb4357b5e8e824ddc051c), `packages/agent/src/agent-loop.ts`. |
| DeepSeek Harness | [4e84901e6471b79ec0338099867ebb4606d12bb5](https://github.com/deepseek-ai/deepseek-harness/tree/4e84901e6471b79ec0338099867ebb4606d12bb5), `packages/core/agent-loop/src/agent.ts`. |
| Codex | [27bf160f7909704fb7e23d508f31900d90479699](https://github.com/openai/codex/tree/27bf160f7909704fb7e23d508f31900d90479699), `codex-rs/core/src/session/turn.rs`. |
| Claude Code | Official [overview](https://code.claude.com/docs/en/how-claude-code-works), [Agent SDK loop](https://code.claude.com/docs/en/agent-sdk/agent-loop), and [hooks](https://code.claude.com/docs/en/hooks-guide) documentation consulted that day; no pinned official implementation SHA. |

## Task environment

τ²-bench is pinned to official commit [672227c6b6676edc20d57ea53b7000262aae77b9](https://github.com/sierra-research/tau2-bench/tree/672227c6b6676edc20d57ea53b7000262aae77b9), using that version's lockfile for installation. Fetch its dependencies separately and retain upstream licensing. LoopBlox's MIT license does not replace those terms.

## Bundled fonts

The website serves local font files and retains their licenses in both source and build output:

- Departure Mono: [license](../site/assets/fonts/DepartureMono-LICENSE).
- JetBrains Mono: [SIL Open Font License](../site/assets/fonts/JetBrainsMono-OFL.txt).
- Source Serif 4: [SIL Open Font License](../site/assets/fonts/SourceSerif4-OFL.txt).

See the [font guide](../site/assets/fonts/README.md) for their roles. Font licensing is separate from the repository code's [MIT license](../LICENSE).
