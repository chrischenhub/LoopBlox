"use strict";

const $ = id => document.getElementById(id);
const names = {context_full: "Full history", decide: "Decide next step", execute: "Run tools", observe_full: "Full result"};
const shortNames = {context_full: "Context", decide: "Decide", execute: "Execute", observe_full: "Observe"};
let config, chat, selectedTurn, selectedCall, selectedStage;
let following = true, posting = false, stopping = false, timer, sourceHash;
const messageNodes = new Map();

async function request(path, data) {
  const response = await fetch(path, data === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "The local server could not complete this request.");
  return result;
}

function error(message) {
  $("chat-error").textContent = message || "";
  $("chat-error").hidden = !message;
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function lastTurn() { return chat?.turns.at(-1); }
function busy() { return posting || lastTurn()?.status === "running"; }

function failureText(turn) {
  if (turn.status === "interrupted") return "Stopped. The recorded calls and their usage have been retained.";
  if (turn.error?.includes("concurrency_limit_exceeded")) return "The model service is busy with another request. Try again when it is free.";
  if (turn.error === "action_limit") return `The loop reached its limit of ${turn.actions} tool calls before returning a reply. Inspect the recorded calls below.`;
  return `This run ended. ${turn.error || turn.status.replaceAll("_", " ")}`;
}

function toolResults(calls) {
  const actions = new Map(calls.flatMap(call => call.value?.actions || []).map(action => [action.action_id, action]));
  return calls.filter(call => call.component === "execute").flatMap(call =>
    (call.value?.outcomes || []).map(outcome => ({...actions.get(outcome.action_id), ...outcome, invocation: call.id})));
}

function controls() {
  const running = busy();
  $("message").disabled = !chat || posting;
  $("send").disabled = !chat || running || !$("message").value.trim();
  $("send").hidden = running;
  $("stop").hidden = !running;
  $("stop").disabled = posting || stopping;
  $("stop").textContent = stopping ? "Stopping…" : "■ Stop";
  $("new-chat").disabled = !config || running;
  $("composer-hint").textContent = running ? "The loop is running. You can draft your next message." : "Enter to send · Shift + Enter for a new line";
  document.querySelectorAll("[data-prompt]").forEach(button => { button.disabled = !chat || running; });
}

function showSource(loop) {
  if (sourceHash === loop.sha256) return;
  sourceHash = loop.sha256;
  $("source-code").replaceChildren();
  loop.source.trimEnd().split("\n").forEach((line, index) => {
    const row = node("div", "code-line");
    row.dataset.line = String(index + 1);
    row.append(node("span", "line-number", String(index + 1)));
    const code = node("code");
    // Token coloring only. Python remains the source; no graph or code is executed in the browser.
    const tokens = /("[^"\n]*"|'[^'\n]*'|\b(?:def|while|if|return|True)\b|\b(?:run|component)\b)/g;
    let cursor = 0;
    for (const match of line.matchAll(tokens)) {
      code.append(document.createTextNode(line.slice(cursor, match.index)));
      const kind = /^['"]/.test(match[0]) ? "string" : /^(run|component)$/.test(match[0]) ? "function" : "keyword";
      code.append(node("span", "token-" + kind, match[0]));
      cursor = match.index + match[0].length;
    }
    code.append(document.createTextNode(line.slice(cursor)));
    row.append(code);
    $("source-code").append(row);
  });
  $("source-name").textContent = loop.filename;
  $("source-hash").textContent = loop.sha256.slice(0, 8);
}

function renderMessages() {
  const messages = $("messages");
  const nearBottom = messages.scrollHeight - messages.scrollTop - messages.clientHeight < 120;
  $("welcome").hidden = chat.turns.length > 0;
  for (const [index, turn] of chat.turns.entries()) {
    let entry = messageNodes.get(turn.id);
    if (!entry) {
      const article = node("article", "chat-turn");
      const user = node("div", "user-message");
      user.append(node("div", "message-role", "You"), node("p", "message-text", turn.message));
      const assistant = node("div", "assistant-message");
      const role = node("div", "message-role");
      const inspect = node("button", "run-select", `View run ${String(index + 1).padStart(2, "0")} ↗`);
      inspect.addEventListener("click", () => {
        selectedTurn = turn.id; selectedCall = selectedStage = null; following = false;
        render();
        if (window.matchMedia("(max-width: 780px)").matches) $("loop-heading").scrollIntoView({behavior: "smooth", block: "start"});
      });
      role.append(node("span", "", "LoopBlox"), inspect);
      const text = node("p", "message-text");
      const tools = node("details", "tool-activity");
      const toolSummary = node("summary");
      const toolList = node("div", "tool-list");
      tools.append(toolSummary, toolList);
      assistant.append(role, tools, text); article.append(user, assistant); messages.append(article);
      entry = {article, text, tools, toolSummary, toolList}; messageNodes.set(turn.id, entry);
    }
    entry.article.classList.toggle("selected", turn.id === selectedTurn);
    const results = toolResults(turn.invocations);
    entry.tools.hidden = !results.length;
    const toolKey = results.map(result => `${result.action_id}:${result.status}`).join(",");
    if (entry.tools.dataset.key !== toolKey) {
      entry.tools.dataset.key = toolKey;
      entry.toolSummary.textContent = `${results.length} tool call${results.length === 1 ? "" : "s"} · ${[...new Set(results.map(result => result.capability_id))].join(",")} ↓`;
      entry.toolList.replaceChildren();
      for (const result of results) {
        const button = node("button", "tool-result");
        button.append(node("code", "", `${result.capability_id}(${JSON.stringify(result.arguments)})`),
          node("span", result.status === "ok" ? "tool-ok" : "tool-failed", result.status === "ok" ? "Completed" : result.status));
        button.addEventListener("click", () => {
          selectedTurn = turn.id; selectedCall = result.invocation; selectedStage = null; following = false;
          $("call-details").open = true; render();
        });
        entry.toolList.append(button);
      }
    }
    const current = turn.invocations.at(-1);
    let content;
    if (turn.status === "completed") {
      content = typeof turn.response === "string" ? turn.response : JSON.stringify(turn.response, null, 2);
    } else if (turn.status === "running") {
      content = stopping && turn.id === lastTurn().id ? "Stopping the loop and retaining its recorded calls…" :
        current?.status === "started" ? `${names[current.component] || current.component}…` : "Running the loop…";
    } else {
      content = failureText(turn);
    }
    if (entry.text.textContent !== content) entry.text.textContent = content;
    entry.text.classList.toggle("pending-message", turn.status !== "completed");
  }
  if (nearBottom || posting) messages.scrollTop = messages.scrollHeight;
}

function renderLoop() {
  const turn = chat?.turns.find(item => item.id === selectedTurn);
  const loop = turn?.loop || config.loop;
  const calls = turn?.invocations || [];
  const call = selectedCall ? calls.find(item => item.id === selectedCall) : selectedStage ? null : calls.at(-1);
  const isLatest = following && !selectedCall && !selectedStage;
  const finished = turn?.status === "completed" && !selectedCall && !selectedStage;
  const stage = selectedStage || (finished ? "return" : call?.component);
  const running = turn?.status === "running" && !selectedCall && !selectedStage;
  showSource(loop);
  $("follow-live").setAttribute("aria-pressed", String(isLatest));
  $("follow-live").textContent = isLatest ? "● Following latest" : "↗ Follow latest";
  const failed = turn && !["completed", "running"].includes(turn.status);
  $("stage-dot").className = "stage-dot" + (running ? " running" : failed ? " failed" : finished ? " completed" : "");
  $("stage-name").textContent = selectedStage ? names[stage] + " / contract" : selectedCall ?
    `${names[stage]} / ${call.status}` : finished ? "Reply returned" : failed ? turn.status.replaceAll("_", " ") :
    running ? (call?.status === "started" ? names[stage] : "Advancing the loop") : "Ready for a message";
  const index = turn ? chat.turns.indexOf(turn) + 1 : 0;
  $("turn-label").textContent = turn ? `Run ${String(index).padStart(2, "0")}${selectedCall ? " / " + selectedCall : ""}` : "No run yet";
  document.querySelectorAll("[data-stage]").forEach(element => {
    const name = element.dataset.stage;
    element.classList.toggle("active", name === stage);
    element.classList.toggle("visited", calls.some(item => item.component === name && item.status === "completed"));
    element.classList.toggle("failed", name === stage && ["failed", "interrupted"].includes(call?.status));
  });
  document.querySelectorAll("[data-stage-count]").forEach(element => {
    const records = calls.filter(item => item.component === element.dataset.stageCount);
    const counts = [
      [records.filter(item => item.status === "completed").length, "done"],
      [records.filter(item => item.status === "started").length, "running"],
      [records.filter(item => item.status === "failed").length, "failed"],
      [records.filter(item => item.status === "interrupted").length, "stopped"],
    ];
    element.textContent = counts.filter(([count]) => count).map(([count, label]) => `${count} ${label}`).join(" · ") || "not run";
  });
  document.querySelectorAll("[data-wire]").forEach(element => {
    element.classList.toggle("active", element.dataset.wire === stage && (!selectedStage) &&
      (stage !== "context_full" || calls.filter(item => item.component === "context_full").length > 1));
  });
  const line = finished ? loop.return_line : loop.lines[stage];
  document.querySelectorAll(".code-line").forEach(row => row.classList.toggle("active", Number(row.dataset.line) === line));
  $("source-location").textContent = line ? `Line ${line} · ${finished ? "outer run(env) returned" : stage}` : "Waiting for execution";
  const upto = call ? calls.slice(0, calls.indexOf(call) + 1) : calls;
  $("iteration-count").textContent = turn ? String(upto.filter(item => item.component === "context_full").length) : "—";
  $("model-count").textContent = turn?.usage.model_calls ?? 0;
  $("tool-count").textContent = turn?.actions ?? 0;
  $("elapsed-time").textContent = turn ? `${Math.floor(turn.elapsed_seconds)}s` : "—";
  $("event-count").textContent = `${calls.length} invocation${calls.length === 1 ? "" : "s"}`;
  const trail = $("event-trail");
  const trailKey = calls.map(item => `${item.id}:${item.status}`).join(",") + ":" + (call?.id || "");
  if (trail.dataset.key !== trailKey) {
    trail.dataset.key = trailKey;
    trail.replaceChildren();
    if (!calls.length) trail.append(node("p", "empty-trail", "Actual calls appear here as the loop runs."));
    for (const item of calls) {
      const button = node("button", `event ${item.status}${item.id === call?.id ? " active" : ""}`);
      button.append(node("i"), document.createTextNode(`${item.id.slice(1)} ${shortNames[item.component]}`));
      button.title = `${item.component} · ${item.status}`;
      button.setAttribute("aria-pressed", String(item.id === call?.id));
      button.addEventListener("click", () => {
        selectedCall = item.id; selectedStage = null; following = false;
        $("call-details").open = true; renderLoop();
      });
      trail.append(button);
    }
  }
  const spec = (turn?.components || config.components)[stage];
  $("detail-title").textContent = call && !selectedStage ? `${call.id} / ${call.component}` : spec ? stage : "Component details";
  $("detail-description").textContent = spec?.description || "Select a stage to read its contract, or select a recorded call to inspect it.";
  const detail = selectedStage ? {parameters: spec.parameters, contract: spec.contract} : call ?
    {status: call.status, arguments: call.arguments, result: call.value, ...(call.error ? {error: call.error} : {})} : null;
  $("detail-json").textContent = detail ? JSON.stringify(detail, null, 2) : "";
}

function render() {
  if (following) selectedTurn = lastTurn()?.id;
  renderMessages(); renderLoop(); controls();
}

async function poll() {
  clearTimeout(timer);
  try {
    chat = await request(`/api/chats/${chat.id}`);
    if (!busy()) stopping = false;
    error(""); render();
    if (busy()) timer = setTimeout(poll, 220);
  } catch (failure) {
    error("Connection interrupted. " + failure.message + " Reconnecting…");
    timer = setTimeout(poll, 2000);
  }
}

async function newChat() {
  clearTimeout(timer);
  chat = await request("/api/chats", {});
  localStorage.setItem("loopblox-chat", chat.id);
  messageNodes.forEach(entry => entry.article.remove()); messageNodes.clear();
  selectedTurn = selectedCall = selectedStage = null; following = true; stopping = false;
  $("message").value = ""; error(""); render(); $("message").focus();
}

$("composer").addEventListener("submit", async event => {
  event.preventDefault();
  const message = $("message").value.trim();
  if (!message || busy()) return;
  let submitError;
  posting = true; error(""); controls();
  try {
    await request(`/api/chats/${chat.id}/turns`, {message});
    $("message").value = ""; following = true; selectedCall = selectedStage = null;
  } catch (failure) { submitError = failure.message; }
  finally { posting = false; }
  await poll(); if (submitError) error(submitError); $("message").focus();
});
$("message").addEventListener("input", controls);
$("message").addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault(); if (!busy()) $("composer").requestSubmit();
  }
});
$("stop").addEventListener("click", async () => {
  stopping = true; controls();
  try { await request(`/api/chats/${chat.id}/stop`, {}); }
  catch (failure) { stopping = false; error(failure.message); controls(); }
});
$("new-chat").addEventListener("click", () => { newChat().catch(failure => error(failure.message)); });
$("follow-live").addEventListener("click", () => { following = true; selectedCall = selectedStage = null; render(); });
document.querySelectorAll("[data-prompt]").forEach(button => button.addEventListener("click", () => {
  $("message").value = button.dataset.prompt; controls(); $("composer").requestSubmit();
}));
document.querySelectorAll("[data-stage][role='button']").forEach(element => {
  const select = () => {
    selectedStage = element.dataset.stage; selectedCall = null; following = false;
    $("call-details").open = true; renderLoop();
  };
  element.addEventListener("click", select);
  element.addEventListener("keydown", event => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); select(); } });
});
$("copy-code").addEventListener("click", async () => {
  try {
    const turn = chat?.turns.find(item => item.id === selectedTurn);
    await navigator.clipboard.writeText((turn?.loop || config.loop).source);
    $("copy-code").textContent = "Copied";
    setTimeout(() => { $("copy-code").textContent = "Copy"; }, 1500);
  } catch { error("Copy is unavailable in this browser. You can select the source text directly."); }
});

(async () => {
  try {
    config = await request("/api/config");
    $("model-name").textContent = config.model;
    showSource(config.loop);
    const saved = localStorage.getItem("loopblox-chat");
    if (saved && /^[a-f0-9]{32}$/.test(saved)) {
      try { chat = await request(`/api/chats/${saved}`); }
      catch { localStorage.removeItem("loopblox-chat"); }
    }
    if (!chat) await newChat();
    else { render(); if (busy()) await poll(); }
  } catch (failure) { error("Could not connect to the local chat server. " + failure.message); }
})();
