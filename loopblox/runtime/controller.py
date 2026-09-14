"""Fixed model/tool gateways and an isolated process for ordinary Python controllers."""

from __future__ import annotations

import copy
import json
import os
import select
import selectors
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from loopblox.runtime.components import (
    RECENT_TURNS, brief_observation, capability_kinds, catalog,
    decision_schema, definition, validate,
)
from loopblox.runtime.model import (
    BudgetExhausted, HostFault, OperationalProblem, Tool, ToolResult,
    _PROVIDER_STOP_CODES, _TRANSIENT_CODES, usage_tokens,
)
from loopblox.runtime.io import atomic_json, run_process
from loopblox.report import write_trace_report


WORKER = Path(__file__).with_name("worker.py")
WORKER_SOURCE = WORKER.read_text()
MAX_WIRE_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 128 * 1024


class CandidateError(Exception):
    pass


def model_usage(calls):
    """Summarize actual attempts once, preserving unknown provider usage."""
    inputs = [usage_tokens(call["usage"], "prompt_tokens") for call in calls]
    outputs = [usage_tokens(call["usage"], "completion_tokens") for call in calls]
    return dict(
        model_calls=len(calls),
        model_input_tokens=sum(inputs) if all(x is not None for x in inputs) else None,
        model_output_tokens=sum(outputs) if all(x is not None for x in outputs) else None,
        known_model_input_tokens=sum(x or 0 for x in inputs),
        known_model_output_tokens=sum(x or 0 for x in outputs),
        charged_output_tokens=sum(call["charged_output_tokens"] for call in calls),
        incomplete_usage_calls=sum(i is None or o is None for i, o in zip(inputs, outputs)),
    )


@dataclass(frozen=True)
class Limits:
    seconds: float = 1800
    actions: int = 40
    model_calls: int = 48
    output_tokens: int = 65536

    def __post_init__(self):
        if self.seconds <= 0 or any(type(x) is not int or x <= 0 for x in
                                    (self.actions, self.model_calls, self.output_tokens)):
            raise ValueError("All limits must be positive; counts must be integers")


class ModelMeter:
    """One owner for the shared research budget, including nested task model calls."""

    def __init__(self, path: Path, *, seconds: float, output_tokens: int, model_calls: int, parent=None):
        if min(seconds, output_tokens, model_calls) <= 0:
            raise ValueError("Research limits must be positive")
        self.path = path
        self.parent = parent
        self.deadline = time.monotonic() + seconds
        if parent is not None:
            self.deadline = min(self.deadline, parent.deadline)
        self.limits = dict(seconds=seconds, output_tokens=output_tokens, model_calls=model_calls)
        self.calls: list[dict] = []
        self.save()

    def remaining(self):
        remaining = {
            "seconds": max(0, self.deadline - time.monotonic()),
            "model_calls": max(0, self.limits["model_calls"] - len(self.calls)),
            "output_tokens": max(0, self.limits["output_tokens"] - sum(
                call["charged_output_tokens"] for call in self.calls)),
        }
        if self.parent is not None:
            parent = self.parent.remaining()
            remaining = {key: min(value, parent[key]) for key, value in remaining.items()}
        return remaining

    def start(self, scope: str, requested: int, request: dict):
        # The shared ledger owns session-wide provider failures, including user calls.
        # Refusing a later dispatch is not another model attempt and is not charged.
        for call in reversed(self.calls):
            if call.get("failure_code") in _PROVIDER_STOP_CODES:
                raise OperationalProblem("Provider remains unavailable in this episode: " + call["failure"],
                                         code=call["failure_code"], effects="none")
        remaining = self.remaining()
        if remaining["seconds"] <= 0 or remaining["model_calls"] <= 0:
            raise BudgetExhausted("research_time_or_model_call_limit")
        if requested <= 0 or requested > remaining["output_tokens"]:
            raise BudgetExhausted("research_output_token_limit")
        call = (self.parent.start(scope, requested, request) if self.parent is not None else
                dict(scope=scope, status="started", requested_output_tokens=requested,
                     charged_output_tokens=requested, usage=None, elapsed_seconds=None,
                     request=copy.deepcopy(request)))
        self.calls.append(call)
        self.save()  # Reserve before dispatch: an interrupted request is not free.
        return call

    def finish(self, call, *, usage, status, elapsed):
        if self.parent is not None:
            self.parent.finish(call, usage=usage, status=status, elapsed=elapsed)
        else:
            reported = usage_tokens(usage, "completion_tokens")
            call.update(usage=copy.deepcopy(usage), status=status, elapsed_seconds=elapsed,
                        charged_output_tokens=call["requested_output_tokens"] if reported is None else reported)
        self.save()

    def save(self):
        atomic_json(self.path, {"limits": self.limits, "calls": self.calls})

    def summary(self):
        return model_usage(self.calls)


def model_call(*, meter, scope, request, max_tokens, remaining, invoke, time_origin, record_attempt=None):
    """One gateway for agent and environment model attempts, retry and accounting."""
    allowance = min(max_tokens, remaining()["output_tokens"])
    if not remaining()["model_calls"] or allowance <= 0:
        raise BudgetExhausted("model_limit")
    failure = None
    for attempt in range(2):
        try:
            available = remaining()
            if available["seconds"] <= 0 or not available["model_calls"] or allowance > available["output_tokens"]:
                raise BudgetExhausted("model_retry_budget")
            call = meter.start(scope, allowance, request)
        except BudgetExhausted:
            # A refused retry does not replace the failure of the actual attempt.
            if failure is not None:
                raise failure from None
            raise
        call["start_seconds"] = time.monotonic() - time_origin
        if record_attempt is not None:
            record_attempt(call)
        started, usage, failure = time.monotonic(), None, None
        status = "interrupted"
        try:
            turn = invoke(allowance, remaining()["seconds"])
            usage, status = turn.usage, "returned"
        except BudgetExhausted as error:
            status = "budget_exhausted"
            call.update(failure_code="time_limit", failure=str(error))
            raise
        except (OperationalProblem, HostFault) as error:
            usage, failure, status = error.usage, error, "failed"
            call.update(failure_code=getattr(error, "code", "host_fault"), failure=str(error))
            if (isinstance(error, OperationalProblem) and error.code == "model_output_limit"
                    and usage_tokens(usage, "completion_tokens") == allowance == available["output_tokens"]):
                status = "budget_exhausted"
                raise BudgetExhausted("output_token_limit") from error
        finally:
            call["end_seconds"] = time.monotonic() - time_origin
            meter.finish(call, usage=usage, status=status, elapsed=time.monotonic() - started)
        if failure is None:
            return turn, call
        if (attempt == 0 and isinstance(failure, OperationalProblem)
                and failure.effects == "none" and failure.code in _TRANSIENT_CODES):
            if remaining()["seconds"] <= 2:
                raise failure
            time.sleep(2)
            continue
        raise failure


class ControllerRuntime:
    def __init__(self, *, task: dict, tools: tuple[Tool, ...], client, meter: ModelMeter,
                 limits: Limits, trace_path: Path, scope: str, image: str, exposed=None):
        self.exposed = copy.deepcopy(exposed if exposed is not None else {name: {} for name in catalog()})
        self.public_catalog = catalog(self.exposed)
        self.task = copy.deepcopy(task)
        self.tools = {tool.capability_id: tool for tool in tools}
        if len(self.tools) != len(tools):
            raise ValueError("Duplicate capability IDs")
        self.client, self.meter, self.limits = client, meter, limits
        self.trace_path, self.scope, self.image = trace_path, scope, image
        self.started = time.monotonic()
        self.deadline = min(self.started + limits.seconds, meter.deadline)
        self.history: list[dict] = [{"type": "task", "task": self.task}]
        self.actions: dict[str, dict] = {}
        self.calls: list[dict] = []
        self.blocks: dict[str, dict] = {}
        self.active_component_id: str | None = None
        self.actions_used = 0
        self.rpc_calls = 0
        self.record: dict[str, Any] = dict(status="running", scope=scope, limits=asdict(limits),
                                           history=self.history, model_calls=self.calls,
                                           component_calls=[], exposed=self.exposed, library=catalog(),
                                           tools=[tool.disclosure_record() for tool in tools])
        self.save()

    def save(self):
        self.record["actions_executed"] = self.actions_used
        atomic_json(self.trace_path, self.record)

    def remaining(self):
        return dict(
            seconds=max(0, min(self.deadline, self.meter.deadline) - time.monotonic()),
            actions=max(0, self.limits.actions - self.actions_used),
            model_calls=max(0, min(self.limits.model_calls - len(self.calls),
                                   self.meter.remaining()["model_calls"])),
            output_tokens=max(0, min(self.limits.output_tokens - sum(
                call["charged_output_tokens"] for call in self.calls),
                self.meter.remaining()["output_tokens"])),
        )

    def check_time(self):
        if self.remaining()["seconds"] <= 0:
            raise BudgetExhausted("time_limit")

    def dispatch(self, request):
        self.check_time()
        self.rpc_calls += 1
        if self.rpc_calls > 4096:
            raise BudgetExhausted("controller_request_limit")
        if not isinstance(request, dict) or set(request) != {"method", "arguments"}:
            raise CandidateError("Expected a controller method and arguments")
        arguments = request["arguments"]
        if not isinstance(arguments, dict):
            raise CandidateError("Controller arguments must be an object")
        method = request["method"]
        if method == "component":
            return self.component(**arguments)
        if method == "history" and not arguments:
            return copy.deepcopy(self.history)
        if method == "remaining" and not arguments:
            return self.remaining()
        raise CandidateError(f"Unknown controller method: {method!r}")

    def component(self, name, **arguments):
        self.check_time()
        block_id = f"b{len(self.blocks) + 1:04d}"
        block = dict(id=block_id, component=name, arguments=copy.deepcopy(arguments),
                     parent_id=None, start_seconds=time.monotonic() - self.started,
                     status="started", value=None)
        self.blocks[block_id] = block
        self.record["component_calls"].append(block)
        self.save()
        started = time.monotonic()
        self.active_component_id = block_id
        try:
            try:
                spec = definition(name)
                if name not in self.public_catalog:
                    raise CandidateError(f"Component is outside the exposed composition boundary: {name}")
                parameters = self.public_catalog[name]["parameters"]
                validate(arguments, parameters)
                arguments = {
                    **{key: copy.deepcopy(schema["default"]) for key, schema in parameters["properties"].items()
                       if "default" in schema},
                    **arguments,
                }
            except ValueError as error:
                raise CandidateError(str(error)) from error
            block["arguments"] = copy.deepcopy(arguments)
            self.save()
            value = self.invoke(block, spec, arguments)
            block.update(status="completed", value=value)
            return copy.deepcopy(dict(id=block_id, value=value))
        except BaseException as error:
            block.update(status="failed" if isinstance(error, Exception) else "interrupted",
                         error=str(error), error_type=type(error).__name__)
            raise
        finally:
            self.active_component_id = None
            block["elapsed_seconds"] = time.monotonic() - started
            block["end_seconds"] = time.monotonic() - self.started
            self.save()

    def reference(self, block_id, schema):
        categories = schema["reference_categories"]
        block = self.blocks.get(block_id) if isinstance(block_id, str) else None
        if (block is None or block["status"] != "completed"
                or definition(block["component"])["category"] not in categories):
            raise CandidateError(f"Expected a completed {'/'.join(categories)} reference")
        return block

    def requesting_turn(self, observation):
        """History index of the decision turn behind this observation; None for controller-origin calls."""
        execution = self.blocks.get(self.history[observation]["execution_id"], {})
        decision = execution.get("arguments", {}).get("decision")
        if not isinstance(decision, str):
            return None
        return next((i for i, record in enumerate(self.history)
                     if record["type"] == "model_turn" and record["component_id"] == decision), None)

    def without_failed_results(self, indices):
        """Drop failed observations, and a decision turn only when every observation it produced is dropped."""
        selected = set(indices)
        dropped = {i for i in indices if self.history[i]["type"] == "observation"
                   and self.history[i]["status"] == "failed"}
        produced: dict[int, list[int]] = {}
        for i in indices:
            if self.history[i]["type"] != "observation":
                continue
            turn = self.requesting_turn(i)
            if turn is not None and turn in selected:
                produced.setdefault(turn, []).append(i)
        dropped |= {turn for turn, observations in produced.items()
                    if all(i in dropped for i in observations)}
        return [i for i in indices if i not in dropped]

    def invoke(self, block, spec, args):
        name = block["component"]
        parameters = spec["parameters"]["properties"]
        if name in {"context_full", "context_recent"}:
            indices = [i for i, record in enumerate(self.history)
                       if record["type"] in {"model_turn", "observation"}]
            if name == "context_recent":
                turns = [i for i in indices if self.history[i]["type"] == "model_turn"]
                if len(turns) > RECENT_TURNS:
                    indices = [i for i in indices if i >= turns[-RECENT_TURNS]]
            if args.get("drop") == "failed_results":
                indices = self.without_failed_results(indices)
            return dict(records=indices)
        if "prompt" in spec:
            context = self.reference(args["context"], parameters["context"])
            indices = list(context["value"]["records"])
            for input_id in args.get("inputs", []):
                self.reference(input_id, parameters["inputs"]["items"])
                indices.extend(i for i, record in enumerate(self.history)
                               if record.get("component_id") == input_id and i not in indices)
            capabilities = tuple(tool.disclosure_record() for tool in self.tools.values()
                                 if spec["category"] == "decision"
                                 and tool.kind in capability_kinds(args["tool_filter"]))
            schema = (decision_schema(capabilities, args["selection"])
                      if spec["category"] == "decision" else spec.get("model_output", spec["output"]))
            messages = [{"role": "system", "content":
                         "Work on the disclosed task using the supplied structured output contract. "
                         "History and analysis results are task evidence. The active component defines this call's behavior."},
                        {"role": "user", "content": json.dumps(self.history[0], ensure_ascii=False)}]
            for index in indices:
                record = self.history[index]
                messages.append({"role": "assistant" if record["type"] == "model_turn" else "user",
                                 "content": json.dumps(record["output"] if record["type"] == "model_turn"
                                                       else record, ensure_ascii=False)})
            request = dict(component=name, instruction=spec["prompt"], capabilities=capabilities,
                           remaining=self.remaining())
            if "target" in parameters:
                target = self.reference(args["target"], parameters["target"])
                request["target"] = dict(id=target["id"], component=target["component"],
                                         category=definition(target["component"])["category"],
                                         value=target["value"])
            messages.append({"role": "user", "content": json.dumps(request, ensure_ascii=False)})
            # Host-assigned IDs belong to the component result, not the model's original output.
            output = copy.deepcopy(self.model_request(block, messages, schema))
            try:
                validate(output, schema)
                if output.get("kind") == "actions":
                    for action in output["actions"]:
                        validate(action["arguments"], self.tools[action["capability_id"]].parameters)
            except ValueError as error:
                raise OperationalProblem(f"Component output contract violated: {error}",
                                         code="invalid_model_response", effects="none") from error
            if output.get("kind") == "actions":
                for index, action in enumerate(output["actions"]):
                    action_id = f"{block['id']}-a{index + 1}"
                    action["action_id"] = action_id
                    self.actions[action_id] = dict(request=copy.deepcopy(action), attempted=False)
            if name == "context_summary":
                return dict(records=[len(self.history) - 1], summary=output["summary"])
            return output
        if spec["category"] == "execution":
            if name == "execute":
                decision = self.reference(args["decision"], parameters["decision"])["value"]
                if decision["kind"] != "actions":
                    raise CandidateError("execute requires an action decision")
                selected = [self.actions[action["action_id"]] for action in decision["actions"]
                            if not self.actions[action["action_id"]]["attempted"]]
                if args["take"] == "one":
                    selected = selected[:1]
                if not selected:
                    raise CandidateError("Decision has no unattempted actions")
            else:
                selected = [dict(request=dict(action_id=f"{block['id']}-rule", **args))]
            value = dict(status="ok", outcomes=[])
            block["value"] = value  # Retain the attempted prefix even if a later action exhausts limits.
            for action in selected:
                request = action["request"]
                outcome = self.perform(request["capability_id"], request["arguments"],
                                       "model" if name == "execute" else "controller", request["action_id"], block["id"])
                value["outcomes"].append(outcome)
                if outcome["status"] == "failed":
                    value["status"] = "failed"
                    break
            return value
        if spec["category"] == "observation":
            execution = self.reference(args["execution"], parameters["execution"])
            if any(record["type"] == "observation" and record["execution_id"] == execution["id"]
                   for record in self.history):
                raise CandidateError("This execution has already been observed")
            value = copy.deepcopy(execution["value"])
            if name == "observe_brief":
                for outcome in value["outcomes"]:
                    capability_id = next(event["capability_id"] for event in self.history
                                         if event["type"] == "tool_call" and event["action_id"] == outcome["action_id"])
                    outcome["result"] = brief_observation(
                        outcome["result"], self.tools[capability_id].preserve_observation_fields)
            self.history.append(dict(type="observation", component_id=block["id"],
                                     execution_id=execution["id"], **value))
            return value
        raise HostFault(f"Approved component has no implementation: {name}")

    def model_request(self, block, messages, schema):
        request = dict(component_id=block["id"], component=block["component"],
                       messages=copy.deepcopy(messages), schema=copy.deepcopy(schema))
        def record_attempt(call):
            self.calls.append(call)
            self.save()

        try:
            turn, call = model_call(
                meter=self.meter, scope=self.scope, request=request, max_tokens=self.client.max_tokens,
                remaining=self.remaining, time_origin=self.started, record_attempt=record_attempt,
                invoke=lambda allowance, seconds: self.client.complete(
                    tuple(messages), schema, max_output_tokens=allowance, timeout_seconds=seconds),
            )
        finally:
            self.save()
        usage, request_limit = turn.usage, call["requested_output_tokens"]
        output = copy.deepcopy(turn.output)
        record = dict(type="model_turn", component_id=block["id"], component=block["component"],
                      raw=copy.deepcopy(turn.raw), output=output)
        self.history.append(record)
        self.save()  # Retain malformed model output and its incurred costs too.
        if usage_tokens(usage, "completion_tokens") is not None and usage["completion_tokens"] > request_limit:
            raise HostFault("Model exceeded its requested output allowance; actual usage was retained")
        return output

    def perform(self, capability_id, arguments, origin, action_id, component_id):
        self.check_time()
        if self.actions_used >= self.limits.actions:
            raise BudgetExhausted("action_limit")
        if not isinstance(capability_id, str) or capability_id not in self.tools or not isinstance(arguments, dict):
            raise CandidateError("Tool requests require an available capability and object arguments")
        try:
            validate(arguments, self.tools[capability_id].parameters)
        except ValueError as error:
            raise CandidateError(f"Invalid tool arguments: {error}") from error
        self.actions_used += 1
        if origin == "model":
            self.actions[action_id]["attempted"] = True
        record = dict(type="tool_call", action_id=action_id, origin=origin, component_id=component_id,
                      capability_id=capability_id, arguments=copy.deepcopy(arguments), status="started",
                      start_seconds=time.monotonic() - self.started)
        self.history.append(record)
        self.save()
        started = time.monotonic()
        try:
            value = self.tools[capability_id].execute(copy.deepcopy(arguments), self.remaining()["seconds"])
            if isinstance(value, ToolResult):
                result = dict(status=value.status, result=value.result_or_error, effects=value.effects)
            else:
                result = dict(status="ok", result=value,
                              effects="applied" if self.tools[capability_id].kind == "mutate" else "none")
        except OperationalProblem as error:
            result = dict(status="failed", result=str(error), code=error.code, effects=error.effects)
        except (BudgetExhausted, HostFault):
            record.update(status="interrupted", effects="unknown", elapsed_seconds=time.monotonic() - started,
                          end_seconds=time.monotonic() - self.started)
            self.save()
            raise
        except Exception as error:
            result = dict(status="failed", result=str(error), effects="unknown")
        except BaseException:
            record.update(status="interrupted", effects="unknown", elapsed_seconds=time.monotonic() - started,
                          end_seconds=time.monotonic() - self.started)
            self.save()
            raise
        result["action_id"] = action_id
        record.update(status="completed", elapsed_seconds=time.monotonic() - started,
                      end_seconds=time.monotonic() - self.started)
        self.history.append(dict(type="tool_result", component_id=component_id, **result))
        self.save()
        return result

    def run(self, source: str):
        if len(source.encode()) > MAX_SOURCE_BYTES:
            raise CandidateError("Controller source is too large")
        name = "loopblox-controller-" + uuid.uuid4().hex
        command = [
            "docker", "run", "--pull", "never", "--rm", "-i", "--name", name, "--network", "none", "--read-only",
            "--user", "65534:65534", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "32", "--memory", "256m", "--cpus", "1", "--workdir", "/tmp",
            "--tmpfs", "/tmp:rw,nosuid,size=32m",
            self.image, "python", "-I", "-u", "-c", WORKER_SOURCE,
        ]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        os.set_blocking(process.stdin.fileno(), False)
        stderr = bytearray()
        buffer = bytearray()

        def send(record):
            data = memoryview((json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n").encode())
            while data:
                self.check_time()
                if process.poll() is not None:
                    raise CandidateError("Controller exited before receiving its result")
                if select.select([], [process.stdin], [], min(1, self.remaining()["seconds"]))[1]:
                    try:
                        data = data[os.write(process.stdin.fileno(), data[:65536]):]
                    except BlockingIOError:
                        continue

        try:
            send(dict(source=source, task=self.task,
                      tools=[tool.disclosure_record() for tool in self.tools.values()],
                      components=self.public_catalog))
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                selector.register(process.stderr, selectors.EVENT_READ)
                finished = False
                while not finished:
                    self.check_time()
                    events = selector.select(min(1, self.remaining()["seconds"]))
                    if not events and process.poll() is not None:
                        if process.returncode in {125, 126, 127}:
                            raise OperationalProblem("Controller container could not start", code="controller_environment_failed", effects="none")
                        raise CandidateError(f"Controller process exited with code {process.returncode}")
                    for key, _ in events:
                        data = os.read(key.fileobj.fileno(), 65536)
                        if not data:
                            selector.unregister(key.fileobj)
                            continue
                        if key.fileobj is process.stderr:
                            stderr.extend(data)
                            del stderr[:-65536]
                            continue
                        buffer.extend(data)
                        if len(buffer) > MAX_WIRE_BYTES:
                            raise CandidateError("Controller request exceeds the message limit")
                        while b"\n" in buffer:
                            line, _, rest = buffer.partition(b"\n")
                            buffer[:] = rest
                            request = json.loads(line)
                            if isinstance(request, dict) and set(request) == {"finished"}:
                                self.record.update(status="completed", result=request["finished"])
                                finished = True
                                break
                            if isinstance(request, dict) and set(request) == {"candidate_error"}:
                                raise CandidateError(str(request["candidate_error"]))
                            try:
                                result = self.dispatch(request)
                                send({"result": result})
                            except (CandidateError, TypeError) as error:
                                send({"error": str(error)})
                        if finished:
                            break
        except BudgetExhausted as error:
            self.record.update(status="budget_exhausted", stop_reason=str(error))
        except OperationalProblem as error:
            self.record.update(status="operational_failure", stop_reason=str(error), code=getattr(error, "code", None))
        except HostFault as error:
            self.record.update(status="host_fault", stop_reason=str(error))
        except (CandidateError, ValueError, BrokenPipeError) as error:
            self.record.update(status="candidate_error", stop_reason=str(error))
        except BaseException:
            self.record.update(status="interrupted", stop_reason="host_interrupted")
            raise
        finally:
            try:
                run_process(["docker", "rm", "-f", name], timeout=10, capture_output=True)
            except Exception as error:
                self.record.update(status="operational_failure", cleanup_error=str(error))
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=10)
                self.record.update(stderr=stderr.decode(errors="replace"), elapsed_seconds=time.monotonic() - self.started)
                self.save()
                write_trace_report(self.record, self.trace_path.with_suffix(".html"))
        return copy.deepcopy(self.record)
