"""Fixed model/tool gateways and an isolated process for ordinary Python controllers."""

from __future__ import annotations

import copy
import json
import math
import os
import select
import selectors
import subprocess
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from threading import RLock
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from loopblox.runtime.components import (
    RECENT_EXECUTIONS, brief_observation, capability_kinds, catalog,
    choose_schema, critique_schema, decision_schema, definition, validate, validate_judgments,
)
from loopblox.runtime import jev
from loopblox.runtime.model import (
    BudgetExhausted, HostFault, OperationalProblem, PlanningTurn, Tool, ToolResult,
    _PROVIDER_STOP_CODES, _TRANSIENT_CODES, usage_tokens,
)
from loopblox.runtime.io import atomic_json, run_process, cancellation_scope, check_cancelled, wait_seconds, cancel_dispatch
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
        timeout_wait_seconds=sum(call.get("timeout_wait_seconds", 0) for call in calls),
    )


@dataclass(frozen=True)
class Limits:
    seconds: float | None = 1800
    actions: int | None = 40
    model_calls: int | None = 48
    output_tokens: int | None = 65536

    def __post_init__(self):
        if (self.seconds is not None and self.seconds <= 0) or any(x is not None and (type(x) is not int or x <= 0) for x in
                                    (self.actions, self.model_calls, self.output_tokens)):
            raise ValueError("Limits must be positive, or None for unlimited; counts must be integers")


def _available(limit, used=0):
    return math.inf if limit is None else max(0, limit - used)


def _public_remaining(remaining):
    """JSON uses null for an unlimited allowance; arithmetic stays inside the host."""
    return {key: None if value == math.inf else value for key, value in remaining.items()}


_activity = ContextVar("model_activity", default=None)


def excluded_timeout_seconds(calls, activities=()):
    """Exclude wall time only when every active pipeline job is waiting on timeouts."""
    events = []
    legacy = 0
    for call in calls:
        if "timeout_intervals" not in call:
            legacy += call.get("timeout_wait_seconds", 0)
        for start, end in call.get("timeout_intervals", []):
            events.extend([(start, "waiting", call.get("activity"), 1),
                           (end, "waiting", call.get("activity"), -1)])
    if not events:
        return legacy
    for activity in activities:
        events.extend([(activity["start"], "active", activity["scope"], 1),
                       (activity.get("end", time.monotonic()), "active", activity["scope"], -1)])
    active, waiting, previous, excluded = {}, {}, 0, legacy
    for at, kind, scope, delta in sorted(events, key=lambda item: item[0]):
        if waiting and all(waiting.get(scope, 0) for scope in active):
            excluded += at - previous
        counts = active if kind == "active" else waiting
        counts[scope] = counts.get(scope, 0) + delta
        if counts[scope] == 0:
            del counts[scope]
        previous = at
    return excluded


def _meter_locked(method):
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return locked


class ModelMeter:
    """One owner for the shared research budget, including nested task model calls."""

    def __init__(self, path: Path, *, seconds: float | None, output_tokens: int | None, model_calls: int | None, parent=None):
        if any(value is not None and value <= 0 for value in (seconds, output_tokens, model_calls)):
            raise ValueError("Research limits must be positive")
        self.path = path
        self.parent = parent
        self.lock = parent.lock if parent is not None else RLock()
        self.started = time.monotonic()
        self.limits = dict(seconds=seconds, output_tokens=output_tokens, model_calls=model_calls)
        self.calls: list[dict] = []
        self.activities: list[dict] = []
        self.save()

    @property
    @_meter_locked
    def timeout_wait_seconds(self):
        return excluded_timeout_seconds(self.calls, self.activities)

    @contextmanager
    def activity(self, scope):
        record = dict(scope=scope, start=time.monotonic())
        with self.lock:
            self.activities.append(record)
            self.save()
        token = _activity.set(scope)
        try:
            yield
        finally:
            _activity.reset(token)
            with self.lock:
                record["end"] = time.monotonic()
                self.save()

    @_meter_locked
    def exclude_timeout(self, call, start, end):
        call.setdefault("timeout_intervals", []).append([start, end])
        call["timeout_wait_seconds"] = call.get("timeout_wait_seconds", 0) + end - start
        owner = self
        while owner is not None:
            owner.save()
            owner = owner.parent

    @property
    def deadline(self):
        deadline = (math.inf if self.limits["seconds"] is None else
                    self.started + self.limits["seconds"] + self.timeout_wait_seconds)
        return min(deadline, self.parent.deadline) if self.parent is not None else deadline

    @_meter_locked
    def remaining(self):
        check_cancelled()
        remaining = {
            "seconds": max(0, self.deadline - time.monotonic()),
            "model_calls": _available(self.limits["model_calls"], len(self.calls)),
            "output_tokens": _available(self.limits["output_tokens"], sum(
                call["charged_output_tokens"] for call in self.calls)),
        }
        if self.parent is not None:
            parent = self.parent.remaining()
            remaining = {key: min(value, parent[key]) for key, value in remaining.items()}
        return remaining

    @_meter_locked
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
                dict(scope=scope, activity=_activity.get(), status="started", requested_output_tokens=requested,
                     charged_output_tokens=requested, usage=None, elapsed_seconds=None,
                     request=copy.deepcopy(request)))
        self.calls.append(call)
        self.save()  # Reserve before dispatch: an interrupted request is not free.
        return call

    @_meter_locked
    def finish(self, call, *, usage, status, elapsed):
        if self.parent is not None:
            self.parent.finish(call, usage=usage, status=status, elapsed=elapsed)
        else:
            reported = usage_tokens(usage, "completion_tokens")
            call.update(usage=copy.deepcopy(usage), status=status, elapsed_seconds=elapsed,
                        charged_output_tokens=call["requested_output_tokens"] if reported is None else reported)
        self.save()

    @_meter_locked
    def save(self):
        atomic_json(self.path, {"limits": self.limits, "calls": self.calls, "activities": self.activities})

    @_meter_locked
    def summary(self):
        return model_usage(self.calls)


def model_call(*, meter, scope, request, max_tokens, remaining, invoke, time_origin, record_attempt=None):
    """One gateway for agent and environment model attempts, retry and accounting."""
    allowance = min(max_tokens, remaining()["output_tokens"])
    if not remaining()["model_calls"] or allowance <= 0:
        raise BudgetExhausted("model_limit")
    failure = None
    transient_retry_used = False
    while True:
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
        with meter.lock:
            call["start_seconds"] = time.monotonic() - time_origin
        if record_attempt is not None:
            record_attempt(call)
        started, usage, failure = time.monotonic(), None, None
        status = "interrupted"
        try:
            # A request must reach its own timeout before we can distinguish
            # excluded timeout waiting from a successful call's charged time.
            turn = invoke(allowance)
            usage, status = turn.usage, "returned"
        except BudgetExhausted as error:
            status = "budget_exhausted"
            with meter.lock:
                call.update(failure_code="time_limit", failure=str(error))
            raise
        except (OperationalProblem, HostFault) as error:
            usage, failure, status = error.usage, error, "failed"
            with meter.lock:
                call.update(failure_code=getattr(error, "code", "host_fault"), failure=str(error))
                if error.response is not None:
                    # Keep failed provider output with its existing attempt and privacy scope.
                    call["response"] = copy.deepcopy(error.response)
            if (isinstance(error, OperationalProblem) and error.code == "model_output_limit"
                    and usage_tokens(usage, "completion_tokens") == allowance == available["output_tokens"]):
                status = "budget_exhausted"
                raise BudgetExhausted("output_token_limit") from error
        finally:
            with meter.lock:
                call["end_seconds"] = time.monotonic() - time_origin
            elapsed = time.monotonic() - started
            if (isinstance(failure, OperationalProblem) and failure.code == "model_timeout"
                    and failure.effects == "none"):
                meter.exclude_timeout(call, started, started + elapsed)
            meter.finish(call, usage=usage, status=status, elapsed=elapsed)
        if failure is None:
            if remaining()["seconds"] <= 0:
                raise BudgetExhausted("time_limit")
            return turn, call
        if (isinstance(failure, OperationalProblem) and failure.effects == "none"
                and failure.code in _TRANSIENT_CODES
                and (failure.code in {"model_timeout", "concurrency_limit_exceeded"} or not transient_retry_used)):
            delay = 60 if failure.code == "concurrency_limit_exceeded" else 2
            available = remaining()
            if (not available["model_calls"] or allowance > available["output_tokens"]
                    or available["seconds"] <= (0 if failure.code == "model_timeout" else delay)):
                raise failure
            waiting = time.monotonic()
            try:
                wait_seconds(delay)
            finally:
                if failure.code == "model_timeout":
                    meter.exclude_timeout(call, waiting, time.monotonic())
            if failure.code not in {"model_timeout", "concurrency_limit_exceeded"}:
                transient_retry_used = True
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
        self.session_id = uuid.uuid4().hex
        self.trace_path, self.scope, self.image = trace_path, scope, image
        self.started = time.monotonic()
        self.initial_timeout_wait_seconds = meter.timeout_wait_seconds
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

    @property
    def deadline(self):
        excluded = self.meter.timeout_wait_seconds - self.initial_timeout_wait_seconds
        return min(self.started + _available(self.limits.seconds) + excluded, self.meter.deadline)

    def save(self):
        self.record["actions_executed"] = self.actions_used
        atomic_json(self.trace_path, self.record)

    def remaining(self):
        return dict(
            seconds=max(0, self.deadline - time.monotonic()),
            actions=_available(self.limits.actions, self.actions_used),
            model_calls=max(0, min(_available(self.limits.model_calls, len(self.calls)),
                                   self.meter.remaining()["model_calls"])),
            output_tokens=max(0, min(_available(self.limits.output_tokens, sum(
                call["charged_output_tokens"] for call in self.calls)),
                self.meter.remaining()["output_tokens"])),
        )

    def check_time(self):
        if self.remaining()["seconds"] <= 0:
            raise BudgetExhausted("time_limit")

    def dispatch(self, request):
        self.check_time()
        self.rpc_calls += 1
        if self.rpc_calls > 4096 and self.limits.actions is not None:
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
            return _public_remaining(self.remaining())
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

    def visible_history(self, start=0):
        """Summaries are explicit context representations, not additional raw evidence."""
        return [i for i in range(start, len(self.history))
                if self.history[i]["type"] == "observation"
                or (self.history[i]["type"] == "model_turn"
                    and self.history[i]["component"] != "context_summary")]

    def evidence_indices(self, indices):
        """Prefer full evidence only when it is explicitly present in this selection."""
        indices = list(dict.fromkeys(indices))
        full = {self.history[i]["execution_id"] for i in indices
                if self.history[i]["type"] == "observation"
                and self.blocks[self.history[i]["component_id"]]["component"] == "observe_full"}
        return [i for i in indices if self.history[i]["type"] != "observation"
                or self.history[i]["execution_id"] not in full
                or self.blocks[self.history[i]["component_id"]]["component"] == "observe_full"]

    def decision_scope(self, arguments):
        """Resolve a proposed local objective without changing task facts or permissions."""
        if "scope" not in arguments:
            return None
        scope = arguments["scope"]
        schema = definition("decide")["parameters"]["properties"]["scope"]
        plan = self.reference(scope["plan"], schema["properties"]["plan"])
        if scope["step"] >= len(plan["value"]["steps"]):
            raise CandidateError("Scope step is outside the referenced plan")
        return dict(plan=plan["id"], step=scope["step"], **plan["value"]["steps"][scope["step"]])

    def proposal(self, block):
        """Disclose a stored proposal, including the decision's original scope and options."""
        value = dict(id=block["id"], component=block["component"],
                     category=definition(block["component"])["category"], value=block["value"])
        if value["category"] == "decision":
            value.update(scope=self.decision_scope(block["arguments"]),
                         tool_filter=block["arguments"]["tool_filter"],
                         selection=block["arguments"]["selection"])
        return value

    def evidence(self, indices):
        """Resolve public model claims and observations identically for every model provider."""
        evidence = []
        for index in indices:
            record = self.history[index]
            if record["type"] == "model_turn":
                source = self.blocks[record["component_id"]]
                item = dict(id=source["id"], type="model_turn", component=source["component"],
                            category=definition(source["component"])["category"], value=record["output"])
                if item["category"] == "decision":
                    item["scope"] = self.decision_scope(source["arguments"])
            else:
                item = dict(id=record["component_id"], **record)
            evidence.append(item)
        return evidence

    def invoke(self, block, spec, args):
        name = block["component"]
        parameters = spec["parameters"]["properties"]
        if name in {"context_full", "context_recent"}:
            indices = self.visible_history()
            if "base" in args:
                base = self.reference(args["base"], parameters["base"])["value"]
                indices = [*base["records"], *self.visible_history(base["through"])]
            if name == "context_recent":
                first_observations = {}
                for i in indices:
                    if self.history[i]["type"] == "observation":
                        first_observations.setdefault(self.history[i]["execution_id"], i)
                if len(first_observations) > RECENT_EXECUTIONS:
                    start = list(first_observations.values())[-RECENT_EXECUTIONS]
                    indices = [i for i in indices if i >= start]
                    decisions = [self.requesting_turn(i) for i in indices
                                 if self.history[i]["type"] == "observation"]
                    indices = sorted(set(indices) | {i for i in decisions if i is not None})
            return dict(records=self.evidence_indices(indices), through=len(self.history))
        if "prompt" in spec:
            context = self.reference(args["context"], parameters["context"])
            indices = list(context["value"]["records"])
            for input_id in args.get("inputs", []):
                self.reference(input_id, parameters["inputs"]["items"])
                indices.extend(i for i, record in enumerate(self.history)
                               if record.get("component_id") == input_id and i not in indices)
            indices = self.evidence_indices(indices)
            if name == "judge":
                return self.judge(block, spec, args, indices)
            scope = self.decision_scope(args) if spec["category"] == "decision" else None
            target = self.reference(args["target"], parameters["target"]) if "target" in parameters else None
            candidates = []
            if name == "choose":
                candidates = [self.reference(candidate, parameters["candidates"]["items"])
                              for candidate in args["candidates"]]
                scopes = [candidate["arguments"].get("scope") for candidate in candidates]
                if any(candidate_scope != scopes[0] for candidate_scope in scopes):
                    raise CandidateError("Choose candidates must concern the same task or plan step")
                if any(self.actions[action["action_id"]]["attempted"] for candidate in candidates
                       for action in candidate["value"].get("actions", [])):
                    raise CandidateError("Choose requires proposals whose actions have not been attempted")
            tool_filter = args.get("tool_filter", "all")
            if target and definition(target["component"])["category"] == "decision":
                tool_filter = target["arguments"]["tool_filter"]
            capabilities = tuple(tool.disclosure_record() for tool in self.tools.values()
                                 if name != "context_summary" and tool.kind in capability_kinds(tool_filter))
            evidence_ids = ["task", *(self.history[i]["component_id"] for i in indices)]
            if target:
                evidence_ids.append(target["id"])
            evidence_ids = list(dict.fromkeys(evidence_ids))
            if spec["category"] == "decision":
                schema = decision_schema(capabilities, args["selection"], scoped=scope is not None)
            elif name == "critique":
                schema = critique_schema(evidence_ids)
            elif name == "choose":
                schema = choose_schema(args["candidates"])
            else:
                schema = spec.get("model_output", spec["output"])
            messages = [{"role": "system", "content":
                         "Work on the disclosed task using the supplied structured output contract. "
                         "The original task and policy always apply, including within a plan step. "
                         "Model outputs, plans and completion proposals are claims, not proof of effects. "
                         "Evidence IDs identify stored originals; the active component defines this call's behavior."},
                        {"role": "user", "content": json.dumps(dict(id="task", **self.history[0]), ensure_ascii=False)}]
            for evidence in self.evidence(indices):
                if evidence["type"] == "model_turn":
                    # Replay only the original model output as the assistant turn.
                    # Host metadata identifies it without changing its output format.
                    output = evidence.pop("value")
                    messages.append({"role": "user", "content":
                                     "Host metadata for the following historical model output:\n"
                                     + json.dumps(evidence, ensure_ascii=False)})
                    messages.append({"role": "assistant", "content": json.dumps(output, ensure_ascii=False)})
                else:
                    messages.append({"role": "user", "content": json.dumps(evidence, ensure_ascii=False)})
            request = dict(component=name, instruction=spec["prompt"], capabilities=capabilities,
                           remaining=_public_remaining(self.remaining()))
            if scope is not None:
                request["scope"] = scope
            if target:
                request["target"] = self.proposal(target)
                request["evidence_ids"] = evidence_ids
            if candidates:
                request["candidates"] = [self.proposal(candidate) for candidate in candidates]
            messages.append({"role": "user", "content": json.dumps(request, ensure_ascii=False)})
            # Host-assigned IDs belong to the component result, not the model's original output.
            output = copy.deepcopy(self.model_request(
                block, dict(messages=messages, schema=schema), max_tokens=self.client.max_tokens,
                invoke=lambda allowance: self.client.complete(
                    tuple(messages), schema, max_output_tokens=allowance, timeout_seconds=self.client.timeout,
                    session_id=self.session_id)))
            try:
                validate(output, schema)
                if output.get("kind") == "actions":
                    for action in output["actions"]:
                        validate(action["arguments"], self.tools[action["capability_id"]].parameters)
                if name == "critique" and any(item["verdict"] != "unknown" and not item["evidence_refs"]
                                              for item in output["assessments"]):
                    raise ValueError("Supported or contradicted assessments require visible evidence references")
            except ValueError as error:
                raise OperationalProblem(f"Component output contract violated: {error}",
                                         code="invalid_model_response", effects="none") from error
            if output.get("kind") == "actions":
                for index, action in enumerate(output["actions"]):
                    action_id = f"{block['id']}-a{index + 1}"
                    action["action_id"] = action_id
                    self.actions[action_id] = dict(request=copy.deepcopy(action), attempted=False)
            if name == "context_summary":
                return dict(records=[len(self.history) - 1], through=context["value"]["through"],
                            summary=output["summary"])
            if name == "critique":
                verdicts = {item["verdict"] for item in output["assessments"]}
                output["verdict"] = next(value for value in ("contradicted", "unknown", "supported") if value in verdicts)
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
            for record in self.history:
                if record["type"] != "observation" or record["execution_id"] != execution["id"]:
                    continue
                observed = self.blocks[record["component_id"]]
                if observed["component"] == "observe_full":
                    raise CandidateError("This execution has already been observed in full")
                if name == "observe_brief" and observed["arguments"]["offset"] == args["offset"]:
                    raise CandidateError("This execution page has already been observed")
            value = copy.deepcopy(execution["value"])
            if name == "observe_brief":
                for outcome in value["outcomes"]:
                    capability_id = next(event["capability_id"] for event in self.history
                                         if event["type"] == "tool_call" and event["action_id"] == outcome["action_id"])
                    outcome["result"], outcome["next_offset"] = brief_observation(
                        outcome["result"], self.tools[capability_id].preserve_observation_fields, args["offset"])
            self.history.append(dict(type="observation", component_id=block["id"],
                                     execution_id=execution["id"],
                                     **({"offset": args["offset"]} if name == "observe_brief" else {}), **value))
            return value
        raise HostFault(f"Approved component has no implementation: {name}")

    def judge(self, block, spec, args, indices):
        reservation = jev.judge_output_reservation(args["questions"])
        if self.remaining()["output_tokens"] < reservation:
            raise BudgetExhausted("jev_output_reservation")
        if "judge_configuration" not in self.record:
            self.record["judge_configuration"] = jev.configuration()
            self.save()
        configuration = self.record["judge_configuration"]
        body = dict(model=configuration["model"], questions=copy.deepcopy(args["questions"]),
                    state=dict(instruction=spec["prompt"], task=copy.deepcopy(self.task),
                               evidence=self.evidence(indices),
                               capabilities=[tool.disclosure_record() for tool in self.tools.values()]))

        def invoke(allowance):
            turn = jev.complete(body, configuration, allowance)
            return PlanningTurn(raw=turn.raw, usage=turn.usage,
                                output=dict(questions=body["questions"], answers=turn.output))

        output = self.model_request(block, dict(provider="jev", **body), max_tokens=reservation, invoke=invoke)
        try:
            validate_judgments(output["answers"], args["questions"])
        except ValueError as error:
            raise OperationalProblem(f"Judge output contract violated: {error}",
                                     code="invalid_model_response", effects="none") from error
        return output

    def model_request(self, block, request, *, max_tokens, invoke):
        request = dict(component_id=block["id"], component=block["component"], **copy.deepcopy(request))
        def record_attempt(call):
            self.calls.append(call)
            self.save()

        try:
            turn, call = model_call(
                meter=self.meter, scope=self.scope, request=request, max_tokens=max_tokens,
                remaining=self.remaining, time_origin=self.started, record_attempt=record_attempt,
                invoke=invoke,
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
        if self.remaining()['actions'] <= 0:
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
            cancel_dispatch()
            self.record.update(status="operational_failure", stop_reason=str(error), code=getattr(error, "code", None))
        except HostFault as error:
            cancel_dispatch()
            self.record.update(status="host_fault", stop_reason=str(error))
        except (CandidateError, ValueError, BrokenPipeError) as error:
            self.record.update(status="candidate_error", stop_reason=str(error))
        except BaseException:
            self.record.update(status="interrupted", stop_reason="host_interrupted")
            raise
        finally:
            try:
                with cancellation_scope(None):
                    run_process(["docker", "rm", "-f", name], timeout=10, capture_output=True)
            except Exception as error:
                self.record.update(status="operational_failure", cleanup_error=str(error))
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=10)
                self.record.update(stderr=stderr.decode(errors="replace"), elapsed_seconds=time.monotonic() - self.started)
                self.record["timeout_wait_seconds"] = self.meter.timeout_wait_seconds - self.initial_timeout_wait_seconds
                self.record["budget_seconds"] = max(0, self.record["elapsed_seconds"] - self.record["timeout_wait_seconds"])
                self.save()
                write_trace_report(self.record, self.trace_path.with_suffix(".html"))
        return copy.deepcopy(self.record)
