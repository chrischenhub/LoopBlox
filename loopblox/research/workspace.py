"""Isolated shell analysis of public evidence; scratch is never host evidence."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time
import uuid

from loopblox.runtime.io import atomic_json, atomic_text, run_process
from loopblox.runtime.model import BudgetExhausted, HostFault, ToolResult


DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 120
MAX_OUTPUT_BYTES = 1024 * 1024
PREVIEW_CHARACTERS = 8000
MAX_COMMAND_BYTES = 65536


def configuration():
    return dict(default_timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
                max_timeout_seconds=MAX_TIMEOUT_SECONDS, max_output_bytes=MAX_OUTPUT_BYTES,
                preview_characters=PREVIEW_CHARACTERS, max_command_bytes=MAX_COMMAND_BYTES,
                scratch_disk_quota_bytes=None)


class ResearchWorkspace:
    """One episode's writable scratch, with a fresh container for each command.

    Only public evidence and scratch are mounted. Scratch has no filesystem quota;
    container memory, process count, command duration and captured output are bounded.
    The host never reads or writes researcher-controlled scratch paths. Exact commands
    and the captured output prefix live in the host-owned, read-only public tree.
    """

    def __init__(self, public: Path, private: Path, image: str):
        self.public = public.resolve()
        self.image = image
        self.scratch = private.resolve() / "research-work"
        self.scratch.mkdir(exist_ok=False)
        self.scratch.chmod(0o777)
        self.artifacts = self.public / "analysis"
        self.artifacts.mkdir(exist_ok=False)

    def run(self, arguments: dict, remaining_seconds: float | None):
        command = arguments.get("command")
        timeout = arguments.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        if (not isinstance(command, str) or not command.strip() or "\0" in command
                or len(command.encode()) > MAX_COMMAND_BYTES):
            return ToolResult("failed", {"code": "invalid_command", "message":
                f"command must be nonempty, contain no NUL, and fit {MAX_COMMAND_BYTES} UTF-8 bytes."}, "none")
        if (type(timeout) not in (float, int) or not math.isfinite(timeout)
                or not 0 < timeout <= MAX_TIMEOUT_SECONDS):
            return ToolResult("failed", {"code": "invalid_timeout", "message":
                f"timeout_seconds must be greater than zero and at most {MAX_TIMEOUT_SECONDS}."}, "none")
        if remaining_seconds is not None:
            if remaining_seconds <= 0:
                raise BudgetExhausted("Research time exhausted before analysis command")
            timeout = min(timeout, remaining_seconds)

        identifier = "command-" + uuid.uuid4().hex
        directory = self.artifacts / identifier
        directory.mkdir()
        atomic_text(directory / "command.sh", command)
        output_path = directory / "output.txt"
        relative = str(directory.relative_to(self.public))
        result = dict(command_id=identifier, command_path=relative + "/command.sh",
                      output_path=relative + "/output.txt", result_path=relative + "/result.json",
                      timeout_seconds=timeout, exit_code=None, output_bytes=0,
                      output_truncated=False, status="running")
        atomic_json(directory / "result.json", result)
        name = "loopblox-research-" + uuid.uuid4().hex
        invocation = [
            "docker", "run", "--pull", "never", "--name", name, "--network", "none", "--read-only",
            "--log-driver", "none",
            "--user", "65534:65534", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "32", "--memory", "256m", "--cpus", "1", "--workdir", "/work",
            "--tmpfs", "/tmp:rw,nosuid,size=32m",
            "--mount", f"type=bind,src={self.public},dst=/evidence,readonly",
            "--mount", f"type=bind,src={self.scratch},dst=/work",
            self.image, "sh", "-c", command,
        ]
        process = None
        started = time.monotonic()
        deadline = started + timeout
        preview = bytearray()
        failure = None
        try:
            with output_path.open("wb") as output:
                process = subprocess.Popen(invocation, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, start_new_session=True)
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    while selector.get_map():
                        seconds = deadline - time.monotonic()
                        if seconds <= 0:
                            result["status"] = "timeout"
                            break
                        for key, _ in selector.select(min(0.1, seconds)):
                            data = os.read(key.fileobj.fileno(), 65536)
                            if not data:
                                selector.unregister(key.fileobj)
                                continue
                            remaining = MAX_OUTPUT_BYTES - result["output_bytes"]
                            captured = data[:remaining]
                            output.write(captured)
                            result["output_bytes"] += len(captured)
                            preview.extend(captured[:max(0, PREVIEW_CHARACTERS * 4 - len(preview))])
                            if len(data) > remaining:
                                result.update(status="output_limit", output_truncated=True)
                                break
                        if result["status"] != "running":
                            break
                if result["status"] == "running":
                    try:
                        result["exit_code"] = process.wait(timeout=max(0.001, deadline - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        result["status"] = "timeout"
                    else:
                        state = run_process(["docker", "inspect", "--format", "{{json .State}}", name],
                                            timeout=10, capture_output=True, text=True)
                        if state.returncode:
                            raise HostFault("Analysis container state unavailable: " + state.stderr.strip())
                        state = json.loads(state.stdout)
                        if (state.get("Running") or state.get("Error")
                                or state.get("StartedAt", "0001").startswith("0001")):
                            raise HostFault("Analysis container could not complete: " + str(state.get("Error")))
                        result.update(status="completed", oom_killed=bool(state.get("OOMKilled")))
                        if state.get("ExitCode") != result["exit_code"]:
                            raise HostFault("Analysis container and Docker client exit codes disagree")
        except BaseException as error:
            failure = error
            result.update(status="interrupted" if not isinstance(error, Exception) else "host_fault",
                          error=str(error))
        finally:
            # Killing the CLI alone does not kill its Docker container. Always remove
            # the named container as well, including when output/time limits fire.
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                cleanup = run_process(["docker", "rm", "--force", name], timeout=10,
                                      capture_output=True, text=True)
                if cleanup.returncode and "No such container" not in cleanup.stderr:
                    raise HostFault("Analysis container cleanup failed: " + cleanup.stderr.strip())
            except Exception as error:
                result["cleanup_error"] = str(error)
                if failure is None:
                    failure = error
                    result.update(status="host_fault", error=str(error))
            finally:
                if process is not None:
                    process.wait(timeout=10)
                    process.stdout.close()
                result.update(elapsed_seconds=time.monotonic() - started,
                              output_preview=preview.decode("utf-8", errors="replace")[:PREVIEW_CHARACTERS])
                atomic_json(directory / "result.json", result)
        if failure is not None:
            if not isinstance(failure, Exception):
                raise failure
            if isinstance(failure, HostFault):
                raise failure
            raise HostFault("Analysis workspace failed: " + str(failure)) from failure
        return ToolResult("ok" if result["status"] == "completed" and result["exit_code"] == 0 else "failed",
                          result, "applied")
