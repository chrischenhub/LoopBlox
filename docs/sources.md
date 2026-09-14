# 固定来源与第三方许可

这些版本用于已有分析或实验环境，不表示上游当前最新版本。源码分析没有运行原生 harness，也没有建立对它们的优化收益。

## Harness 行为分析

分析日期为 2026-09-06。三个开源仓库在分析时核对了干净工作区及完整提交 SHA；仓库内的 [行为拆分](../harness-decomposition.md) 链接到这些版本的具体行。上游源码副本不随本仓库分发。

| 项目 | 固定来源与主要入口 |
| --- | --- |
| Pi | [b8b873b9872db04a938fb4357b5e8e824ddc051c](https://github.com/earendil-works/pi/tree/b8b873b9872db04a938fb4357b5e8e824ddc051c)，`packages/agent/src/agent-loop.ts`。 |
| DeepSeek Harness | [4e84901e6471b79ec0338099867ebb4606d12bb5](https://github.com/deepseek-ai/deepseek-harness/tree/4e84901e6471b79ec0338099867ebb4606d12bb5)，`packages/core/agent-loop/src/agent.ts`。 |
| Codex | [27bf160f7909704fb7e23d508f31900d90479699](https://github.com/openai/codex/tree/27bf160f7909704fb7e23d508f31900d90479699)，`codex-rs/core/src/session/turn.rs`。 |
| Claude Code | 当日查阅的官方 [工作原理](https://code.claude.com/docs/en/how-claude-code-works)、[Agent SDK loop](https://code.claude.com/docs/en/agent-sdk/agent-loop) 与 [hooks](https://code.claude.com/docs/en/hooks-guide) 文档；没有固定官方实现 SHA。 |

## 任务环境

τ²-bench 固定在官方 [672227c6b6676edc20d57ea53b7000262aae77b9](https://github.com/sierra-research/tau2-bench/tree/672227c6b6676edc20d57ea53b7000262aae77b9)，安装时使用该版本的锁文件。TextWorld 版本固定为 1.7.0，安装定义在 [Dockerfile](../environments/textworld/Dockerfile)。两者均独立获取，保留各自上游许可；LoopBlox 的 MIT 许可证不替代上游的许可。

## 随仓库分发的字体

网站使用本地字体文件，并随源码和构建输出保留各自许可证：

- Departure Mono：[许可证](../site/assets/fonts/DepartureMono-LICENSE)。
- JetBrains Mono：[SIL Open Font License](../site/assets/fonts/JetBrainsMono-OFL.txt)。
- Source Serif 4：[SIL Open Font License](../site/assets/fonts/SourceSerif4-OFL.txt)。

字体用途见 [字体说明](../site/assets/fonts/README.md)。其许可证独立于仓库代码的 [MIT 许可证](../LICENSE)。
