"""File-based research: native CLI exits before the host executes its request."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, replace

from loopblox.runtime.components import validate
from loopblox.runtime.io import atomic_json, image_id, run_process
from loopblox.runtime.model import BudgetExhausted, HostFault, OperationalProblem, ToolResult, _PROVIDER_STOP_CODES, load_env
from loopblox.research.failures import incident

NATIVE_VERSION = "0.155.0"
NATIVE_SOURCE = "f0a1b8f0849d90960bc406b848f32e5a129b0457"
FEATURES = dict(apps=False, plugins=False, remote_plugin=False, hooks=False, memories=False,
                multi_agent=False, multi_agent_v2=False, browser_use=False,
                browser_use_external=False, computer_use=False, image_generation=False,
                code_mode=True, code_mode_host=True, goals=False, skill_search=False,
                skill_mcp_dependency_install=False, skip_host_skill_discovery=True,
                shell_snapshot=False)
DOCKER_SANDBOX = ["--security-opt", "seccomp=unconfined", "--cap-drop", "ALL",
                  "--cap-add", "SETUID", "--cap-add", "SETGID", "--cap-add", "SETFCAP",
                  "--security-opt", "no-new-privileges"]
FILE_INSTRUCTIONS = (
    "Read /exchange/task.json for the opening research task and /exchange/tools.json for the canonical host tools. "
    "Read /evidence/progress.json for current state; the opening task's selection and iteration counts are historical. "
    "At the start of this iteration, read /evidence/notes.md and the latest checkpoint "
    "in /evidence/checkpoints/iteration-*.json (the highest iteration number), if present. "
    "These files may not exist yet at the start of research. "
    "The allowed evidence is in /evidence. Maintain /evidence/notes.md as the single research notebook, "
    "updating it through the host tools write_notes or checkpoint. Keep hypotheses, evidence references, "
    "failed approaches and next steps there; checkpoints retain each iteration's notes and recorded state. "
    "Use /work for temporary drafts, scripts, data and analysis. These files persist within this episode "
    "but are not automatically included in notes or checkpoints. Transfer useful research conclusions "
    "into the research notebook rather than maintaining a second notebook in /work. "
    "Both notes and scratch remain researcher claims, not verified facts. "
    "The host resumes this conversation after each request within the iteration. A successful checkpoint "
    "ends this conversation; the next iteration starts a new conversation from notes, checkpoints and "
    "public evidence. A rejected checkpoint keeps this conversation open. "
    "The latest completed host request and receipt are included below, when present; consume that result "
    "before choosing the next request. Earlier requests and receipts are in /exchange/receipts. "
    "Use native local tools to read and analyze /evidence, /work and receipt files within this invocation. "
    "If a receipt contains an output preview, read its output_path under /evidence for the remaining content; "
    "do not rerun a completed command just to retrieve its output. "
    "The host tools are requested through your final output, "
    "not called as native tools. End this invocation with exactly one JSON object containing "
    "\"tool\" (a canonical tool name) and \"arguments\" (its argument object), without Markdown. "
    "The host will execute it only after this CLI and its container close. "
    "A fresh invocation receives the updated files after every request. Checkpoint each iteration and continue; "
    "the host owns selection and the user owns stopping."
)


def default_researcher(*, public_root, scratch_path, private, container_image, meter):
    """Freeze and validate the default native researcher before any opening task runs."""
    load_env()
    binary_root = os.environ.get("LOOPBLOX_CODEX_BINARY_ROOT")
    if not binary_root:
        raise ValueError("Set LOOPBLOX_CODEX_BINARY_ROOT to the pinned Linux Codex distribution before research")
    auth = os.environ.get("LOOPBLOX_CODEX_AUTH_FILE") or str(
        Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json")
    native = CodexResearcher(
        model=os.environ.get("LOOPBLOX_CODEX_MODEL") or "gpt-6-astra",
        reasoning_effort=os.environ.get("LOOPBLOX_CODEX_REASONING_EFFORT") or "low",
        binary_root=Path(binary_root).expanduser().resolve(), container_image=container_image,
        auth_path=Path(auth).expanduser(), public_root=public_root, scratch_path=scratch_path)
    native.validate_limits(meter)
    native.validate_auth()
    configuration = native.configuration()
    setup_path = Path(private) / "setup.json"
    setup = json.loads(setup_path.read_text())
    expected = setup.get("expected_researcher")
    if expected and any(configuration[key] != expected[key] for key in
                        ("version", "binary_sha256", "model", "reasoning_effort", "container_image")):
        raise ValueError("Recovery must retain the frozen native researcher binary, model and settings")
    destination = Path(private) / "native-binaries"
    shutil.copytree(native.binary_root, destination)
    if _binary_digest(destination) != configuration["binary_sha256"]:
        raise HostFault("Copied native researcher distribution differs from its frozen configuration")
    atomic_json(Path(private) / "researcher-configuration.json", configuration)
    setup["researcher"] = dict(configuration=configuration, binary_path="native-binaries",
                               usage_path="native-researcher.json")
    atomic_json(setup_path, setup)
    return replace(native, binary_root=destination)


def _remove_container(name):
    result = run_process(["docker", "rm", "--force", name], timeout=15, capture_output=True, text=True)
    if result.returncode and "No such container" not in result.stderr:
        raise HostFault("Codex container cleanup failed: " + result.stderr.strip())


def _binary_digest(root):
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Codex distribution must contain no symlinks")
        if path.is_file():
            item = hashlib.sha256()
            with path.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    item.update(block)
            digest.update(str(path.relative_to(root)).encode() + b"\0" + item.digest())
    return digest.hexdigest()


def native_usage(calls):
    """CLI turn totals never claim provider attempts or subscription cost."""
    usages = [call.get("usage") for call in calls]
    return dict(model_attempts=None, cost_usd=None, child_agents="disabled", calls=usages,
        coverage="Per-invocation usage derived from CLI session totals; failed or interrupted usage may be missing",
        **{key: sum(value[key] for value in usages)
           if usages and all(value is not None and type(value.get(key)) is int for value in usages) else None
           for key in ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_output_tokens")})


@dataclass(frozen=True, kw_only=True)
class CodexResearcher:
    model: str
    reasoning_effort: str
    binary_root: Path
    container_image: str
    auth_path: Path | None = None
    public_root: Path | None = None
    scratch_path: Path | None = None
    timeout_seconds: float | None = None

    @staticmethod
    def validate_limits(meter):
        owner = meter
        while owner is not None:
            if any(owner.limits[key] is not None for key in ("model_calls", "output_tokens")):
                raise ValueError("Native research requires separate model accounting and uncapped shared model/output limits; "
                                 "freeze compatible budgets explicitly before starting a new episode")
            owner = owner.parent

    def validate_auth(self):
        """Check the selected native credential mode without exposing its values.

        Expiry, refresh and subscription eligibility remain native Codex concerns;
        this local preflight does not claim that an online login will succeed.
        """
        if self.auth_path is None:
            raise ValueError("Codex requires an explicit ChatGPT auth file")
        try:
            auth = json.loads(Path(self.auth_path).read_text())
        except (OSError, ValueError) as error:
            raise ValueError("Cannot read the supplied native Codex auth file") from error
        tokens = auth.get("tokens") if isinstance(auth, dict) else None
        if (not isinstance(auth, dict) or auth.get("auth_mode") != "chatgpt"
                or auth.get("OPENAI_API_KEY") or not isinstance(tokens, dict)
                or not all(isinstance(tokens.get(key), str) and tokens[key]
                           for key in ("access_token", "refresh_token"))):
            raise ValueError("The supplied Codex auth file must contain an existing ChatGPT subscription login")
        return dict(mode="chatgpt", online_validity="not_checked")

    def configuration(self):
        """Freeze the native distribution and policy without auth or model calls."""
        binary = Path(self.binary_root).resolve()
        if not (binary / "bin/codex").is_file():
            raise ValueError("binary_root must contain the Linux Codex distribution's bin/codex")
        if not self.model or self.reasoning_effort not in {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}:
            raise ValueError("Codex requires an explicit model and reasoning effort")
        if self.timeout_seconds is not None and (not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0):
            raise ValueError("Codex timeout must be positive and finite, or None")
        image = image_id(self.container_image)
        name = "loopblox-codex-version-" + uuid.uuid4().hex
        try:
            version = run_process(["docker", "run", "--rm", "--pull", "never", "--name", name,
                                   "--network", "none", "--read-only", "--mount",
                                   f"type=bind,src={binary},dst=/opt/codex,readonly", image,
                                   "/opt/codex/bin/codex", "--version"],
                                  timeout=30, capture_output=True, text=True)
            if version.returncode or version.stdout.strip() != "codex-cli " + NATIVE_VERSION:
                raise ValueError(f"Native Codex must be pinned to {NATIVE_VERSION}")
        finally:
            _remove_container(name)
        return dict(kind="native_codex", version=NATIVE_VERSION, source_commit=NATIVE_SOURCE,
                    binary_sha256=_binary_digest(binary), container_image=image, model=self.model,
                    reasoning_effort=self.reasoning_effort, timeout_seconds=self.timeout_seconds,
                    authentication="native_chatgpt_subscription", features=copy.deepcopy(FEATURES),
                    invocation="codex exec / codex exec resume <session_id>",
                    exchange="one JSON tool request per completed CLI invocation",
                    file_instructions=FILE_INSTRUCTIONS, ephemeral=False,
                    sessions="Resume within an iteration; new session after a successful checkpoint or infrastructure recovery",
                    session_storage="Temporary private Codex home; removed when the researcher closes",
                    children="disabled",
                    web_search="disabled", bundled_skills=False,
                    sandbox=dict(profile="research", extends=":workspace", network=False,
                                 denied_paths=["/root/.codex"], docker_arguments=DOCKER_SANDBOX,
                                 evidence="/evidence (read-only)", scratch="/work"),
                    usage="Per-invocation differences of CLI session totals; provider attempt count and subscription price unknown")

    def _config_text(self):
        lines = [f"model = {json.dumps(self.model)}",
                 f"model_reasoning_effort = {json.dumps(self.reasoning_effort)}",
                 'web_search = "disabled"', 'approval_policy = "never"',
                 'default_permissions = "research"', 'cli_auth_credentials_store = "file"',
                 '[permissions.research]', 'extends = ":workspace"',
                 '[permissions.research.filesystem]', '"/root/.codex" = "deny"',
                 '[permissions.research.network]', 'enabled = false', '[features]']
        lines.extend(f"{name} = {str(enabled).lower()}" for name, enabled in FEATURES.items())
        lines.extend(['[skills]', 'include_instructions = false', '[skills.bundled]', 'enabled = false'])
        return "\n".join(lines) + "\n"

    def _invoke(self, materials, directory, seconds, image, home, *, session_id=None, instructions=None):
        """Return only after natural CLI exit and removal of its entire container."""
        prompt = ("Continue the current research iteration using the host result below. "
                  "The previous CLI and its container closed before the host executed that request. "
                  "Conversation history is preserved; tool processes and in-memory variables are not. "
                  "Read updated public evidence as needed. Return exactly one JSON object with tool and arguments."
                  if session_id else FILE_INSTRUCTIONS)
        if instructions is not None:
            prompt = instructions
        receipts = sorted((materials / "receipts").glob("call-*.json"))
        if receipts:
            latest = receipts[-1]
            prompt += f"\n\nLatest completed host exchange (/exchange/receipts/{latest.name}):\n" + latest.read_text()
        name = "loopblox-codex-" + uuid.uuid4().hex
        process = None
        output = directory / "output"
        output.mkdir()
        command = ["docker", "run", "--rm", "--interactive", "--pull", "never", "--name", name, "--read-only",
                       *DOCKER_SANDBOX, "--pids-limit", "128", "--memory", "1g", "--cpus", "2",
                       "--workdir", "/work", "--tmpfs", "/tmp:rw,nosuid,size=64m",
                       "--mount", f"type=bind,src={Path(self.binary_root).resolve()},dst=/opt/codex,readonly",
                       "--mount", f"type=bind,src={home},dst=/root/.codex",
                       "--mount", f"type=bind,src={Path(self.public_root).resolve()},dst=/evidence,readonly",
                       "--mount", f"type=bind,src={Path(self.scratch_path).resolve()},dst=/work",
                       "--mount", f"type=bind,src={materials},dst=/exchange,readonly",
                       "--mount", f"type=bind,src={output},dst=/output", image,
                       "/opt/codex/bin/codex", "exec", "--json", "--skip-git-repo-check",
                       "--color", "never", "-C", "/work", "-o", "/output/request.json"]
        command += ["resume", session_id, "-"] if session_id else ["-"]
        try:
            with (directory / "events.jsonl").open("wb") as events, (directory / "stderr.txt").open("wb") as errors:
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=events, stderr=errors)
                process.communicate(prompt.encode(), timeout=None if math.isinf(seconds) else seconds)
        except subprocess.TimeoutExpired as error:
            raise BudgetExhausted("research_time_limit") from error
        finally:
            try:
                _remove_container(name)
            finally:
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=10)
        usage, observed_session = None, None
        failure = dict(type="error", message="Native CLI exited without turn.completed")
        for line in (directory / "events.jsonl").read_text().splitlines():
            event = json.loads(line)
            if event.get("type") == "thread.started":
                observed_session = event.get("thread_id")
            elif event.get("type") == "turn.completed":
                usage = event.get("usage")
                # Successful completion supersedes transient reconnect errors retained in events.jsonl.
                failure = None
            elif event.get("type") in {"error", "turn.failed"}:
                failure = event
        return dict(exit_code=process.returncode, usage=usage, failure=failure, session_id=observed_session)

    def run(self, task, tools, meter, trace_path, *, check_stop=lambda: None):
        self.validate_auth()
        if self.public_root is None or self.scratch_path is None:
            raise ValueError("Codex run requires public_root and scratch_path")
        self.validate_limits(meter)
        configuration = self.configuration()
        trace_path = Path(trace_path)
        private = trace_path.parent
        materials, calls_directory = private / "codex-materials", private / "codex-calls"
        materials.mkdir(); calls_directory.mkdir()
        (materials / "receipts").mkdir()
        tool_list = tuple(tools)
        tools = {tool.capability_id: tool for tool in tool_list}
        if not tools or len(tools) != len(tool_list):
            raise ValueError("Native research requires unique canonical tools")
        atomic_json(materials / "task.json", task)
        atomic_json(materials / "tools.json", [tool.disclosure_record() for tool in tool_list])
        started = time.monotonic()
        result = dict(status="failed", configuration=configuration, calls=[])

        def remaining():
            seconds = meter.remaining()["seconds"]
            if self.timeout_seconds is not None:
                seconds = min(seconds, self.timeout_seconds - (time.monotonic() - started))
            if seconds <= 0:
                raise BudgetExhausted("research_time_limit")
            owner = meter
            while owner is not None:
                if any(call.get("failure_code") in _PROVIDER_STOP_CODES for call in owner.calls):
                    raise HostFault("A provider failure has stopped the shared research ledger")
                owner = owner.parent
            return seconds

        native_home = tempfile.TemporaryDirectory(prefix="loopblox-codex-home-")
        try:
            home = Path(native_home.name)
            shutil.copyfile(Path(self.auth_path), home / "auth.json")
            (home / "auth.json").chmod(0o600)
            (home / "config.toml").write_text(self._config_text())
            session_id = None
            while True:
                check_stop()
                identifier = f"call-{len(result['calls']) + 1:06d}"
                directory = calls_directory / identifier
                directory.mkdir()
                call = dict(call_id=identifier, status="started", resumed_session_id=session_id,
                            start_seconds=time.monotonic() - started)
                result["calls"].append(call)
                atomic_json(trace_path, result)
                call.update(self._invoke(materials, directory, remaining(), configuration["container_image"], home,
                                         session_id=session_id))
                # Resumed CLI usage is cumulative for the conversation, not this invocation.
                call["session_usage"] = call["usage"]
                if session_id:
                    previous = (result["calls"][-2].get("session_usage")
                                if call["session_id"] == session_id else None)
                    current = call["session_usage"]
                    call["usage"] = ({key: value - previous[key]
                                      if type(value) is int and type(previous.get(key)) is int
                                      and value >= previous[key] else None
                                      for key, value in current.items()}
                                     if current is not None and previous is not None else None)
                atomic_json(trace_path, result)
                check_stop()
                if call["exit_code"] or call["failure"]:
                    raise HostFault("Native CLI failed; inspect " + str(directory / "stderr.txt"), response=call["failure"])
                if not call["session_id"] or (session_id and call["session_id"] != session_id):
                    raise HostFault("Native CLI did not return the expected research session")
                session_id = call["session_id"]
                request = json.loads((directory / "output/request.json").read_text())
                if (not isinstance(request, dict) or set(request) != {"tool", "arguments"}
                        or request["tool"] not in tools or not isinstance(request["arguments"], dict)):
                    raise HostFault("Native CLI must return one canonical tool name and argument object")
                call["request"] = request
                tool = tools[request["tool"]]
                try:
                    try:
                        validate(request["arguments"], tool.parameters)
                    except ValueError as error:
                        outcome = dict(status="failed", result=str(error), effects="none")
                    else:
                        value = tool.execute(copy.deepcopy(request["arguments"]), remaining())
                        outcome = (dict(status=value.status, result=value.result_or_error, effects=value.effects)
                                   if isinstance(value, ToolResult) else
                                   dict(status="ok", result=value, effects="applied" if tool.kind == "mutate" else "none"))
                except (BudgetExhausted, HostFault):
                    raise
                except OperationalProblem as error:
                    if error.code in _PROVIDER_STOP_CODES or error.effects != "none":
                        raise
                    outcome = dict(status="failed", result=str(error), effects=error.effects, code=error.code)
                except Exception as error:
                    raise HostFault("Research tool failed: " + str(error)) from error
                call.update(status="completed", outcome=outcome, end_seconds=time.monotonic() - started)
                atomic_json(materials / "receipts" / (identifier + ".json"), dict(request=request, receipt=outcome))
                atomic_json(trace_path, result)
                if request["tool"] == "checkpoint" and outcome["status"] == "ok":
                    session_id = None
        except KeyboardInterrupt:
            result.update(status="stopped", error="user_stop")
            raise
        except BudgetExhausted as error:
            result.update(status="budget_exhausted", error=str(error))
        except Exception as error:
            result.update(status="failed", error=str(error), incident=incident(error, stage="researcher"))
        finally:
            native_home.cleanup()
            result["native_usage"] = native_usage(result["calls"])
            result["elapsed_seconds"] = time.monotonic() - started
            atomic_json(trace_path, result)
        return result
