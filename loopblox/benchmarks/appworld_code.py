"""Official AppWorld code execution with public API effects routed to the host."""
from __future__ import annotations

import argparse
import inspect
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
import uuid

from loopblox.runtime.io import atomic_json, check_cancelled, run_process, cancellation_scope
from loopblox.runtime.model import HostFault, ToolResult


def serve():
    # This process has no task databases, evaluator, credentials, host mounts or network.
    from types import SimpleNamespace
    from IPython.terminal.embed import InteractiveShellEmbed
    from traitlets.config.loader import Config
    from appworld.environment import AppWorld, SAID_AVAILABLE_IMPORTS
    from appworld.common.safety_guard import SafetyGuard
    from freezegun import freeze_time

    reader, writer = sys.stdin, sys.stdout

    def send(value):
        writer.write(json.dumps(value) + "\n")
        writer.flush()

    initial = json.loads(reader.readline())

    class Requester:
        def reset_request_count(self):
            self.count = 0

        def request(self, _app_name, _api_name, **arguments):
            self.count += 1
            if self.count > AppWorld.init_defaults.max_api_calls_per_interaction:
                raise Exception("Maximum API calls per code execution reached")
            raise_on_failure = arguments.pop("raise_on_failure", True)
            send(dict(api=dict(app_name=_app_name, api_name=_api_name, arguments=arguments)))
            response = json.loads(reader.readline())
            if response["status"] != "ok" and raise_on_failure:
                raise Exception("API request failed: " + json.dumps(response["result"]))
            return response["result"].get("response", response["result"])

    requester = Requester()
    requester.reset_request_count()
    apis = SimpleNamespace()
    for app, names in initial["api_names"].items():
        namespace = SimpleNamespace()
        for api in names:
            def call(_app=app, _api=api, **arguments):
                return requester.request(_app, _api, **arguments)
            setattr(namespace, api, call)
        setattr(apis, app, namespace)

    class CodeWorld(AppWorld):
        def __init__(self):
            # Reuse the official execute and _shell_run_cell methods unchanged.
            # Host-side AppWorld owns database state, saving and final evaluation.
            config = Config()
            config.HistoryManager.enabled = False
            self.shell = InteractiveShellEmbed(config=config)
            self.shell.ast_node_interactivity = "none"
            self.remote_environment_url = None
            self.raise_on_unsafe_syntax = True
            self.null_patch_unsafe_execution = True
            self.safety_guard = SafetyGuard()
            self.timeout_seconds = AppWorld.init_defaults.timeout_seconds
            self.max_interactions = float("inf")
            self.num_interactions = 0
            self.environment_io = []
            self.requester = requester
            self.output_db_home_path_on_disk = None
            self.shell.run_cell(SAID_AVAILABLE_IMPORTS)
            self.shell.run_cell('''def print(*args, **kwargs):
    if not kwargs and len(args) == 1 and isinstance(args[0], (list, tuple, dict)):
        indent = 1 if len(json.dumps(args[0])) >= 100 else None
        builtins.print(json.dumps(args[0], indent=indent))
    else:
        builtins.print(*args, **kwargs)
''')
            self.shell.run_cell('def input(*args, **kwargs):\n    raise Exception("input is not allowed")')
            self.shell.user_ns["apis"] = apis
            self.shell.user_ns["requester"] = requester

        def _save_state(self, path):
            pass  # The host persists every actual API effect, including partial executions.

        def save_logs(self):
            pass  # The host stores code, output and API receipts per execution.

    with freeze_time(initial["datetime"]):
        world = CodeWorld()
        send(dict(ready=True))
        for line in reader:
            request = json.loads(line)
            send(dict(output=world.execute(request["code"])))


class CodeEnvironment:
    def __init__(self, *, environment, image, directory, private):
        self.environment, self.directory = environment, directory
        self.count, self.api_count = 0, 0
        self.name = "loopblox-appworld-code-" + uuid.uuid4().hex
        self.log = (private / "code-environment.log").open("w")
        command = ["docker", "run", "--pull", "never", "--rm", "-i", "--name", self.name,
            "--network", "none", "--read-only", "--user", "65534:65534", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--pids-limit", "64", "--memory", "1g",
            "--cpus", "1", "--workdir", "/tmp", "--tmpfs", "/tmp:rw,nosuid,size=128m",
            "--env", "HOME=/tmp", image, "python", "-u", "-B", "-c",
            "import json, sys\n" + inspect.getsource(serve) + "\nserve()\n"]
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self.log, start_new_session=True, bufsize=0)
        self.buffer = b""
        try:
            metadata = environment.request(dict(operation="code_metadata"), 30)
            self.send(metadata)
            if self.receive(time.monotonic() + 120) != dict(ready=True):
                raise HostFault("AppWorld code shell failed to initialize")
        except BaseException as error:
            try:
                self.close()
            except Exception as cleanup_error:
                error.add_note("AppWorld code initialization cleanup failed: " + str(cleanup_error))
            raise

    def send(self, value):
        self.process.stdin.write((json.dumps(value) + "\n").encode())

    def receive(self, deadline):
        while b"\n" not in self.buffer:
            check_cancelled()
            if time.monotonic() >= deadline:
                raise HostFault("AppWorld code process exceeded its execution deadline")
            if select.select([self.process.stdout], [], [], 0.2)[0]:
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise HostFault("AppWorld code process closed unexpectedly")
                self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\n", 1)
        return json.loads(line)

    def execute(self, arguments, timeout):
        self.count += 1
        receipt = dict(execution_id=f"code-{self.count:04d}", code=arguments["code"],
                       status="started", api_calls=[])
        path = self.directory / "code-executions" / (receipt["execution_id"] + ".json")
        atomic_json(path, receipt)
        started = time.monotonic()
        deadline = started + min(timeout, 120)
        try:
            self.send(dict(code=arguments["code"]))
            while True:
                message = self.receive(deadline)
                if "api" in message:
                    call = dict(arguments=message["api"], status="started")
                    receipt["api_calls"].append(call)
                    self.api_count += 1
                    atomic_json(path, receipt)
                    result = self.environment.request(dict(operation="call", call=message["api"]),
                        max(0.001, min(100, deadline - time.monotonic())))
                    call.update(result)
                    atomic_json(path, receipt)
                    self.send(result)
                elif "output" in message:
                    output = message["output"]
                    failed = output.startswith("Execution failed.") or output == "No code available to execute."
                    effects = {call.get("effects", "unknown") for call in receipt["api_calls"]}
                    effects = "unknown" if "unknown" in effects else "applied" if "applied" in effects else "none"
                    task_completed = self.environment.request(dict(operation="code_complete",
                        code=arguments["code"], output=output), 30)["task_completed"]
                    receipt.update(status="failed" if failed else "ok", output=output, effects=effects,
                                   task_completed=task_completed)
                    return ToolResult(receipt["status"], dict(output=output, task_completed=task_completed,
                        api_calls=len(receipt["api_calls"]), execution_id=receipt["execution_id"]), effects)
                else:
                    raise HostFault("Invalid AppWorld code transport message")
        except BaseException:
            receipt.update(status="interrupted", effects="unknown")
            raise
        finally:
            receipt["elapsed_seconds"] = time.monotonic() - started
            atomic_json(path, receipt)

    def close(self):
        with cancellation_scope(None):
            try:
                self.process.stdin.close()
                result = run_process(["docker", "rm", "-f", self.name], timeout=15, capture_output=True)
                if result.returncode:
                    raise HostFault("AppWorld code container cleanup failed: " + result.stderr.decode(errors="replace")[-500:])
                self.process.wait(timeout=15)
            finally:
                if self.process.poll() is None:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=15)
                self.process.stdout.close()
                self.log.close()


def build_image(tag):
    # Only dependencies enter the image. No repository, task data or credentials.
    dockerfile = '''FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir appworld==0.1.3.post1
RUN appworld install
RUN python - <<'PY'
import pathlib, shutil
root = pathlib.Path('/usr/local/lib/python3.11/site-packages')
(root / 'appworld/evaluator.py').write_text('def unavailable(*args, **kwargs):\\n    raise RuntimeError("Evaluation is host-only")\\nTestTracker = Metric = evaluate_dataset = evaluate_task = evaluate_tasks = unavailable\\n')
for path in root.rglob('__pycache__'):
    shutil.rmtree(path)
for path in (root / 'tests', root / 'appworld/.source', pathlib.Path('/root/.appworld')):
    if path.exists(): shutil.rmtree(path)
PY
'''
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "Dockerfile").write_text(dockerfile)
        subprocess.run(["docker", "build", "-t", tag, tmp], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-image")
    args = parser.parse_args()
    if args.build_image:
        build_image(args.build_image)
    else:
        serve()
