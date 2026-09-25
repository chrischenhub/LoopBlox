"""Official AppWorld API environment, isolated from the host's real-time clock."""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time
import traceback

from loopblox import ROOT
from loopblox.report import write_trace_report
from loopblox.runtime.components import object_schema
from loopblox.runtime.controller import ControllerRuntime, ModelMeter, model_usage
from loopblox.runtime.io import atomic_json, atomic_text, check_cancelled, cancellation_scope, EvaluationCancelled
from loopblox.runtime.model import HostFault, Tool, ToolResult


def serve():
    """Trusted JSON bridge. Candidate input can invoke only documented public APIs."""
    output = sys.stdout
    world = None
    with contextlib.redirect_stdout(sys.stderr):
        for line in sys.stdin:
            try:
                request = json.loads(line)
                operation = request["operation"]
                if operation == "open" and world is None:
                    from appworld import AppWorld
                    from appworld.common.path_store import path_store
                    path_store.update_root(request["root"])
                    world = AppWorld(request["task_id"], experiment_name=request["experiment_name"],
                                     load_ground_truth=False, random_seed=request["seed"])
                    value = dict(benchmark="AppWorld", task_id=world.task.id,
                        instruction=world.task.instruction, supervisor=dict(world.task.supervisor),
                        datetime=world.task.datetime.isoformat(), apps=world.task.app_descriptions,
                        api_discovery=dict(world.task.api_docs["api_docs"]),
                        supervisor_apis=dict(world.task.api_docs["supervisor"]),
                        controller_contract="Use appworld_api to call the documented APIs in this simulated "
                        "personal-assistant environment. Discover APIs through api_docs. Supply API parameters "
                        "inside arguments. Use supervisor.complete_task to submit the requested concise answer "
                        "or mark the requested actions complete. Then propose completion so run(env) returns. "
                        "task_completed is a submission flag, not a success evaluation.")
                elif operation == "call" and world is not None:
                    call = request["call"]
                    app, api, arguments = call["app_name"], call["api_name"], call["arguments"]
                    doc = world.task.api_docs.get(app, {}).get(api)
                    reserved = {"client", "raise_on_failure", "show", "track", "_app_name", "_api_name"}
                    allowed = {parameter["name"] for parameter in doc["parameters"]} if doc else set()
                    if doc is None or not isinstance(arguments, dict) or set(arguments) - allowed or set(arguments) & reserved:
                        value = dict(status="failed", effects="none", result=dict(
                            message="Unknown public API or unsupported parameters; consult api_docs."))
                    else:
                        response = world.requester._request(app, api, raise_on_failure=False, **arguments)
                        success = 200 <= response.status_code < 300
                        value = dict(status="ok" if success else "failed",
                            effects="none" if doc["method"] == "GET" else "applied" if success else "unknown",
                            result=dict(response=world.requester.response_to_json(response),
                                        task_completed=world.task_completed()))
                        world.num_interactions += 1
                        world._save_state(world.output_db_home_path_on_disk)
                        world.save_logs()
                        world.requester.reset_request_count()
                elif operation == "code_metadata" and world is not None:
                    value = dict(datetime=world.task.datetime.isoformat(),
                                 api_names={app: list(apis) for app, apis in world.task.api_docs.items()})
                elif operation == "code_complete" and world is not None:
                    world.environment_io.append(dict(input=request["code"], output=request["output"]))
                    world.save_logs()
                    value = dict(task_completed=world.task_completed())
                elif operation == "evaluate" and world is not None:
                    # Only the host sends this operation, after the isolated controller exits.
                    from appworld.evaluator import evaluate_task
                    world._save_state(world.output_db_home_path_on_disk)
                    world.save_logs()
                    tracker = evaluate_task(world.task_id, experiment_name=world.experiment_name)
                    atomic_json(Path(request["private_result"]), tracker.to_dict())
                    if tracker.num_tests == 0 or tracker.total_count != tracker.num_tests:
                        raise ValueError("Official evaluator did not complete every check")
                    value = dict(success=tracker.success, passed=tracker.pass_count,
                                 failed=tracker.fail_count, total=tracker.num_tests)
                else:
                    raise ValueError("Invalid environment lifecycle operation")
                packet = dict(ok=True, value=value)
            except BaseException as error:
                traceback.print_exc(file=sys.stderr)
                packet = dict(ok=False, error=type(error).__name__ + ": " + str(error))
            output.write(json.dumps(packet, ensure_ascii=False) + "\n")
            output.flush()
        if world is not None:
            world.close()


class Environment:
    def __init__(self, *, python, root, task_id, experiment_name, seed, private):
        private.mkdir(parents=True, exist_ok=True)
        self.log = (private / "environment.log").open("w")
        # No provider credentials are needed by the simulated apps.
        environment = {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR", "LANG") if key in os.environ}
        environment.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1", APPWORLD_ROOT=str(root))
        self.process = subprocess.Popen([str(python), "-u", "-B", "-m", __name__, "--bridge"],
            cwd=private, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=self.log, start_new_session=True, bufsize=0)
        self.buffer = b""
        try:
            self.task = self.request(dict(operation="open", root=str(root), task_id=task_id,
                experiment_name=experiment_name, seed=seed), 120)
        except BaseException as error:
            try:
                self.close()
            except Exception as cleanup_error:
                error.add_note("AppWorld initialization cleanup failed: " + str(cleanup_error))
            raise

    def request(self, payload, timeout):
        deadline = time.monotonic() + timeout
        try:
            self.process.stdin.write((json.dumps(payload) + "\n").encode())
            while b"\n" not in self.buffer:
                check_cancelled()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise HostFault("AppWorld environment request exceeded its wall-time deadline")
                if select.select([self.process.stdout], [], [], min(0.2, remaining))[0]:
                    chunk = os.read(self.process.stdout.fileno(), 65536)
                    if not chunk:
                        raise HostFault("AppWorld environment process closed unexpectedly")
                    self.buffer += chunk
            line, self.buffer = self.buffer.split(b"\n", 1)
            response = json.loads(line)
            if not response["ok"]:
                raise HostFault("AppWorld environment failed; see private environment.log")
            return response["value"]
        except (OSError, ValueError) as error:
            raise HostFault("AppWorld bridge failed: " + str(error)) from error

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait()
        self.process.stdout.close()
        self.log.close()


class AppWorldRunner:
    def __init__(self, *, root, python, client, worker_image, limits, private, seed, code_image=None):
        self.root, self.python, self.client = Path(root), Path(python), client
        self.worker_image, self.limits, self.private, self.seed = worker_image, limits, Path(private), seed
        self.code_image = code_image

    def __call__(self, *, task_id, source, scope, directory, meter, exposed):
        directory.mkdir(parents=True, exist_ok=False)
        private = self.private / scope
        atomic_text(directory / "controller.py", source)
        task_meter = ModelMeter(private / "usage.json", parent=meter, seconds=self.limits.seconds,
            model_calls=self.limits.model_calls, output_tokens=self.limits.output_tokens)
        started, runtime, environment, code_environment = time.monotonic(), None, None, None
        row = dict(task_id=task_id, family=task_id.split("_")[0], status="running", verification_verdict=None)
        stage = "initialization"
        try:
            environment = Environment(python=self.python, root=self.root, task_id=task_id,
                experiment_name=scope, seed=self.seed, private=private)
            if self.code_image:
                from loopblox.benchmarks.appworld_code import CodeEnvironment
                code_environment = CodeEnvironment(environment=environment, image=self.code_image,
                    directory=directory, private=private)
                environment.task["controller_contract"] = (
                    "Use appworld_execute to execute Python code in the official AppWorld shell. "
                    "Variables persist across code executions. Call public APIs as "
                    "apis.<app_name>.<api_name>(**parameters). Discover documentation through apis.api_docs. "
                    "Use Python loops and local computation as needed; print results you need to observe. "
                    "Code errors return execution feedback; earlier API effects are not rolled back. "
                    "Call apis.supervisor.complete_task to submit, then propose completion so run(env) returns. "
                    "The submission flag does not verify success.")
            atomic_json(directory / "task.json", environment.task)

            def invoke(arguments, timeout):
                result = environment.request(dict(operation="call", call=arguments), min(timeout, 100))
                return ToolResult(result["status"], result["result"], result["effects"])

            tool = Tool("appworld_api", "Call one official public AppWorld API. Discover available API names "
                "and parameter requirements with api_docs. Calls can read or modify simulated app state.",
                object_schema(dict(app_name={"type": "string"}, api_name={"type": "string"},
                                   arguments={"type": "object", "additionalProperties": True})),
                "mutate", invoke, preserve_observation_fields=("task_completed",))
            if code_environment is not None:
                tool = Tool("appworld_execute", "Execute Python in the persistent official AppWorld shell. "
                    "Use apis.<app>.<api>(**parameters), variables, loops and print. "
                    "A code block may issue multiple API calls; earlier effects survive later errors.",
                    object_schema(dict(code={"type": "string"})), "mutate", code_environment.execute,
                    preserve_observation_fields=("task_completed",))
            runtime = ControllerRuntime(task=environment.task, tools=(tool,), client=self.client,
                meter=task_meter, limits=self.limits, trace_path=directory / "trace.json", scope=scope,
                image=self.worker_image, exposed=exposed)
            stage = "task"
            record = runtime.run(source)
            row.update(status=record["status"], stop_reason=record.get("stop_reason"), code=record.get("code"))
            if row["status"] in {"host_fault", "operational_failure"}:
                # The shared gateway has stopped dispatch. Preserve its original
                # failure instead of replacing it with evaluator cancellation.
                return row
            if code_environment is not None:
                code_environment.close()
                row["api_calls"] = code_environment.api_count
                code_environment = None
            stage = "verification"
            score = environment.request(dict(operation="evaluate", private_result=str(private / "verification.json")), 120)
            atomic_json(directory / "verification.json", score)
            row.update(verification=score, verification_verdict=None if row["status"] in {
                "host_fault", "operational_failure"} else "pass" if row["status"] == "completed" and score["success"] else "fail")
        except EvaluationCancelled:
            row.update(status="interrupted", stop_reason="evaluation_cancelled")
            raise
        except Exception as error:
            atomic_json(private / "error.json", dict(stage=stage, type=type(error).__name__, detail=str(error)))
            row.update(status="verifier_failure" if stage == "verification" else "host_fault",
                       stop_reason="appworld_" + stage + "_failed", verification_verdict=None)
        except BaseException:
            row.update(status="interrupted", stop_reason="host_interrupted")
            raise
        finally:
            if code_environment is not None:
                row["api_calls"] = code_environment.api_count
            with cancellation_scope(None):
                for resource in (code_environment, environment):
                    if resource is None:
                        continue
                    try:
                        resource.close()
                    except Exception as error:
                        row.setdefault("cleanup_errors", []).append(dict(type=type(error).__name__, detail=str(error)))
                        if row["status"] not in {"operational_failure", "host_fault", "verifier_failure", "interrupted"}:
                            row.update(status="host_fault", stop_reason="appworld_cleanup_failed", verification_verdict=None)
            row.update(usage=task_meter.summary(), agent_usage=model_usage(runtime.calls if runtime else []),
                user_usage=model_usage([]), grader_usage=model_usage([]), actions=runtime.actions_used if runtime else 0,
                elapsed_seconds=time.monotonic() - started)
            row["budget_seconds"] = max(0, row["elapsed_seconds"] - row["usage"]["timeout_wait_seconds"])
            if runtime is not None:
                runtime.save()
                write_trace_report(runtime.record, directory / "trace.html")
                row.update(trace="trace.json", report="trace.html")
            atomic_json(directory / "result.json", row)
        return row


if __name__ == "__main__":
    if sys.argv[1:] != ["--bridge"]:
        raise SystemExit("Only the trusted host may start this module with --bridge")
    serve()
