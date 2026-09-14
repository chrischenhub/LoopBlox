"""Frozen TextWorld tasks and the host task runner used by ResearchSession."""

from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import tempfile
import time
import uuid

from components import object_schema
from controller_runtime import ControllerRuntime, model_usage
from loopblox import HostFault, OperationalProblem, Tool, ToolResult
from runtime_io import atomic_json, atomic_text, digest, image_id, run_process


HERE = Path(__file__).resolve().parent
ENVIRONMENT = HERE / "environments" / "textworld"
ENVIRONMENT_IMAGE = "loopblox-textworld:1.7.0"
ENVIRONMENT_OPTIONS = [
    "--pull", "never", "--platform", "linux/amd64", "--network", "none", "--read-only",
    "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "64",
    "--memory", "512m", "--cpus", "1", "--tmpfs", "/tmp:rw,nosuid,exec,size=64m",
    "--tmpfs", "/root:rw,nosuid,noexec,size=16m",
]
FAMILIES = {
    "navigation": {"challenge": "tw-coin_collector", "arguments": ["--level", "104"],
                   "objective": "Explore the rooms, find the coin, and take it."},
    "cooking": {"challenge": "tw-cooking", "arguments": [
        "--recipe", "2", "--take", "2", "--go", "1", "--cook", "--cut", "--open",
    ]},
}
FEEDBACK = {
    "visible": ["feedback", "description", "inventory", "admissible_commands"],
    "commands": "Currently admissible commands plus look and inventory; interpreter/debug commands are rejected.",
    "hidden": ["game metadata", "facts", "walkthrough", "winning policy", "intermediate reward"],
    "scoring": "After controller closure: pass only when the controller completed normally and TextWorld reports won. "
               "Record environment score, max_score, won, lost and moves separately. Interpreter narrative may reveal success.",
}


def remove_container(name):
    result = run_process(["docker", "rm", "-f", name], timeout=15, capture_output=True, text=True)
    if result.returncode and "No such container" not in result.stderr:
        raise RuntimeError("Could not remove TextWorld container: " + result.stderr)


def prepare_suite(output, *, development, holdout, seed, environment_image=ENVIRONMENT_IMAGE):
    if min(development, holdout) < 1 or not 0 <= seed < 2**31:
        raise ValueError("Use positive split sizes and a seed between 0 and 2**31 - 1")
    image = image_id(environment_image)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    tasks = []
    for family, settings in FAMILIES.items():
        for split, count in (("development", development), ("holdout", holdout)):
            for index in range(count):
                task_seed = seed + len(tasks)
                tasks.append(dict(task_id=f"{family}-{split}-{index:04d}", family=family, split=split,
                                  seed=task_seed, **settings))
    config = dict(seed=seed, families=FAMILIES, tasks=tasks)
    atomic_json(output / "generation.json", config)
    name = "loopblox-prepare-" + uuid.uuid4().hex
    try:
        result = run_process([
            "docker", "run", "--rm", "--name", name, *ENVIRONMENT_OPTIONS,
            "--mount", f"type=bind,source={output},target=/data", image, "prepare", "/data",
        ], timeout=150 * len(tasks))
    finally:
        remove_container(name)
    if result.returncode:
        raise RuntimeError("TextWorld preparation failed; its partial output was retained. Use a new output directory.")
    source = run_process(["docker", "run", "--rm", "--network", "none", "--entrypoint", "cat",
                          image, "/opt/loopblox/game.py"], timeout=30, capture_output=True, text=True)
    if source.returncode:
        raise RuntimeError("Could not freeze the environment implementation")
    atomic_text(output / "implementation" / "game.py", source.stdout)
    shutil.copyfile(ENVIRONMENT / "Dockerfile", output / "implementation" / "Dockerfile")
    for task in tasks:
        task["files"] = {f"games/{task['task_id']}{suffix}": digest(
            (output / "games" / (task["task_id"] + suffix)).read_bytes()) for suffix in (".z8", ".json")}
    files = {str(path.relative_to(output)): digest(path.read_bytes()) for path in (
        output / "generation.json", output / "versions.json", output / "validation.json",
        output / "implementation" / "game.py", output / "implementation" / "Dockerfile",
    )}
    manifest = dict(environment="textworld", image=image, container_options=ENVIRONMENT_OPTIONS,
                    feedback=FEEDBACK, tasks=tasks,
                    files=files, generation=config, versions=json.loads((output / "versions.json").read_text()))
    atomic_json(output / "manifest.json", manifest)
    return manifest


def load_suite(path):
    path = Path(path).resolve()
    manifest = json.loads((path / "manifest.json").read_text())
    if manifest["container_options"] != ENVIRONMENT_OPTIONS:
        raise ValueError("Suite was prepared with different environment isolation settings")
    for name, expected in manifest["files"].items():
        if digest((path / name).read_bytes()) != expected:
            raise ValueError("Frozen suite file changed: " + name)
    ids = [task["task_id"] for task in manifest["tasks"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Task IDs must be unique across all families and splits")
    for task in manifest["tasks"]:
        for name, expected in task["files"].items():
            if digest((path / name).read_bytes()) != expected:
                raise ValueError("Frozen task changed: " + name)
    return manifest


class TextWorldGame:
    """One isolated interpreter, controlled only through the host's bounded pipe."""

    def __init__(self, workspace, image, log, timeout):
        self.name = "loopblox-textworld-" + uuid.uuid4().hex
        self.log = log.open("wb")
        self.buffer = bytearray()
        self.failure = None
        try:
            self.process = subprocess.Popen([
                "docker", "run", "--rm", "-i", "--name", self.name, *ENVIRONMENT_OPTIONS,
                "--mount", f"type=bind,source={workspace},target=/game,readonly",
                image, "serve", "/game/task.z8",
            ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log)
            self.initial = self.receive(timeout)["observation"]
        except BaseException:
            self.close()
            raise

    def receive(self, timeout):
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            while b"\n" not in self.buffer:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise OperationalProblem("TextWorld response timed out", code="environment_timeout", effects="unknown")
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise OperationalProblem("TextWorld interpreter exited; see environment.log",
                                             code="environment_failed", effects="unknown")
                self.buffer.extend(chunk)
                if len(self.buffer) > 2 * 1024 * 1024:
                    raise HostFault("TextWorld response exceeds the message limit")
        line, _, self.buffer = self.buffer.partition(b"\n")
        return json.loads(line)

    def request(self, message, timeout):
        if self.failure:
            raise HostFault("TextWorld connection is unusable after an environment failure")
        try:
            self.process.stdin.write((json.dumps(message) + "\n").encode())
            self.process.stdin.flush()
            return self.receive(timeout)
        except (OperationalProblem, BrokenPipeError, ValueError) as error:
            self.failure = str(error)
            # Stop the controller: a later request must not consume an earlier, uncertain response.
            raise HostFault("TextWorld connection failed: " + str(error)) from error

    def command(self, arguments, timeout):
        result = self.request(dict(method="step", command=arguments["command"]), timeout)
        return ToolResult(result["status"], result["result"], result["effects"])

    def close(self):
        try:
            remove_container(self.name)
        finally:
            process = getattr(self, "process", None)
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=10)
            self.log.close()


class TextWorldRunner:
    def __init__(self, suite, manifest, client, worker_image, limits):
        self.suite, self.manifest = Path(suite).resolve(), manifest
        self.tasks = {task["task_id"]: task for task in manifest["tasks"]}
        self.client, self.worker_image, self.limits = client, worker_image, limits

    def __call__(self, *, task_id, source, scope, directory, meter, exposed):
        task = self.tasks[task_id]
        directory.mkdir(parents=True, exist_ok=False)
        atomic_text(directory / "controller.py", source)
        row = dict(task_id=task_id, family=task["family"], status="running", verification_verdict=None)
        game, runtime = None, None
        started = time.monotonic()
        try:
            # This workspace is outside public artifacts: .json contains solutions and hidden facts.
            with tempfile.TemporaryDirectory(prefix="loopblox-textworld-") as workspace:
                for name, expected in task["files"].items():
                    data = (self.suite / name).read_bytes()
                    if digest(data) != expected:
                        raise HostFault("Frozen task changed: " + name)
                    (Path(workspace) / ("task" + Path(name).suffix)).write_bytes(data)
                game = TextWorldGame(workspace, self.manifest["image"], directory / "environment.log",
                                     min(60, meter.remaining()["seconds"]))
                disclosed = dict(problem=(
                    "Complete the objective in this TextWorld game. Use textworld_command to interact. "
                    "Choose commands from the current observation's admissible_commands, or use look/inventory. "
                    "Commands can change the world irreversibly. When the goal is achieved, return a final response. "
                    "A completion proposal does not change the game or verify success."
                ), initial_observation=game.initial)
                atomic_json(directory / "task.json", disclosed)
                tools = (Tool("textworld_command", "Issue one command in the current TextWorld game.",
                              object_schema({"command": {"type": "string"}}),
                              "mutate", game.command, preserve_observation_fields=("admissible_commands",)),)
                runtime = ControllerRuntime(task=disclosed, tools=tools, client=self.client, meter=meter,
                                            limits=self.limits, trace_path=directory / "trace.json",
                                            scope=scope, image=self.worker_image, exposed=exposed)
                record = runtime.run(source)
                row.update(status=record["status"], stop_reason=record.get("stop_reason"),
                           usage=model_usage(record["model_calls"]), actions=record["actions_executed"],
                           trace="trace.json", report="trace.html")
                if game.failure:
                    raise OperationalProblem(game.failure, code="environment_failed", effects="unknown")
                # Runtime.run has closed its worker. Only now request authoritative scoring.
                try:
                    verification = game.request({"method": "finish"}, 15)["verification"]
                    atomic_json(directory / "verification.json", verification)
                    row.update(verification=verification, verification_verdict=(
                        "pass" if record["status"] == "completed" and verification["won"] else "fail"))
                except Exception as error:
                    row.update(status="verifier_failure", execution_status=record["status"],
                               verification_error=str(error))
                finally:
                    closing = game
                    game = None
                    closing.close()
        except OperationalProblem as error:
            row.update(status="operational_failure", stop_reason=str(error), verification_verdict=None)
        except Exception as error:
            row.update(status="host_fault", stop_reason=str(error), verification_verdict=None)
        except BaseException:
            row.update(status="interrupted", stop_reason="host_interrupted")
            raise
        finally:
            try:
                if game is not None:
                    game.close()
            finally:
                if runtime is not None:
                    row.update(usage=model_usage(runtime.record["model_calls"]), actions=runtime.actions_used)
                    row.update(trace="trace.json", report="trace.html")
                row["elapsed_seconds"] = time.monotonic() - started
                atomic_json(directory / "result.json", row)
        return row
