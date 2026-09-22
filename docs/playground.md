# Local chat and Loop view

`loopblox/chat_assets/chat.html` is a local two-pane playground: conversation on the left, the current
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
No static build is needed. The page and its assets are bundled under
`loopblox/chat_assets/`, independently of the local promotional website.

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
