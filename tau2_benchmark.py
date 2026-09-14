"""Pinned τ² text domains, audited task subsets and the existing controller runtime."""

from __future__ import annotations

from collections import Counter, defaultdict
import importlib.metadata
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import time
import uuid

from components import object_schema
from controller_runtime import ControllerRuntime, ModelMeter, model_call, model_usage
from loopblox import BudgetExhausted, HostFault, OperationalProblem, Tool, ToolResult, usage_tokens
from runtime_io import atomic_json, atomic_text, digest
from trace_report import write_trace_report


HERE = Path(__file__).resolve().parent
UPSTREAM_REVISION = "672227c6b6676edc20d57ea53b7000262aae77b9"
UPSTREAM_URL = "https://github.com/sierra-research/tau2-bench"
DOMAINS = ("retail", "telecom")


def configure(source, data):
    """Called before any tau2 import, once per CLI process."""
    if "tau2.registry" in sys.modules:
        raise RuntimeError("Start a new process when changing the frozen τ² environment")
    os.environ["TAU2_DATA_DIR"] = str(Path(data).resolve())
    sys.path.insert(0, str(Path(source).resolve() / "src"))
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="ERROR")


def task_groups(tasks, domain):
    """Keep persona variants and connected retail customer/order scenarios together."""
    parents = list(range(len(tasks)))
    seen = {}

    def find(index):
        while parents[index] != index:
            index = parents[index]
        return index

    for index, task in enumerate(tasks):
        if domain == "telecom":
            keys = [re.sub(r"\[PERSONA:.*?\]", "", task.id)]
        else:
            keys = [(key, str(value)) for action in task.evaluation_criteria.actions or []
                    for key, value in action.arguments.items() if key in {"order_id", "user_id"}]
            reason = task.user_scenario.instructions.reason_for_call
            keys.append(("template", re.sub(r"\d+", "#", reason.lower()).strip()))
        for key in keys:
            if key in seen:
                parents[find(index)] = find(seen[key])
            seen[key] = index
    groups = defaultdict(list)
    for index, task in enumerate(tasks):
        groups[find(index)].append(task)
    return list(groups.values())


def prepare_suite(output, *, source, development=18, holdout=18, seed=1701, exclude_suites=()):
    if min(development, holdout) < 1:
        raise ValueError("Both splits require a positive task count")
    source, output = Path(source).resolve(), Path(output).resolve()
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != UPSTREAM_REVISION or subprocess.run(["git", "-C", str(source), "diff", "--quiet", "HEAD"]).returncode:
        raise ValueError("Use the clean pinned upstream revision " + UPSTREAM_REVISION)
    output.mkdir(parents=True, exist_ok=False)
    configure(source, source / "data")
    from tau2.data_model.tasks import RewardType, Task
    from tau2.evaluator.evaluator_env import EnvironmentEvaluator
    from tau2.registry import registry
    reserved = {(task["family"], task["group"]) for path in exclude_suites for task in load_suite(path)["tasks"]}
    rng, selected, audit = random.Random(seed), [], {}
    for domain in DOMAINS:
        raw = json.loads((source / "data/tau2/domains" / domain / "tasks.json").read_text())
        tasks = [Task.model_validate(item) for item in raw]
        eligible, excluded = [], Counter()
        for task in tasks:
            criteria = task.evaluation_criteria
            if not criteria or RewardType.ACTION in criteria.reward_basis:
                excluded["missing_outcome_score_or_required_action_path"] += 1
            elif criteria.nl_assertions:
                excluded["nonempty_llm_judged_assertions"] += 1
            elif any(action.name == "transfer_to_human_agents" for action in criteria.actions or []):
                excluded["handoff_requires_separate_communication_audit"] += 1
            else:
                eligible.append(task)
        groups = task_groups(eligible, domain)
        # One representative per group; other variants never enter either split.
        pools = defaultdict(list)
        for group in groups:
            group_id = digest("\n".join(sorted(item.id for item in group)).encode())[:16]
            if (domain, group_id) in reserved:
                excluded["reserved_for_integration"] += 1
                continue
            task = rng.choice(group)
            if domain == "telecom":
                match = re.match(r"\[([^]]+)\]([^[]+)", task.id)
                faults = len(match[2].split("|"))
                stratum = match[1] + ("/1" if faults == 1 else "/2-3" if faults <= 3 else "/4+")
            else:
                env = registry.get_env_constructor(domain)()
                writes = [action.name for action in task.evaluation_criteria.actions or []
                          if env.tools.tool_mutates_state(action.name)]
                stratum = "+".join(sorted(set(writes))) or "no_write"
            pools[stratum].append((task, group_id))
        for pool in pools.values():
            rng.shuffle(pool)
        strata = sorted(pools)
        rng.shuffle(strata)
        accepted, scores = [], []
        # Audit only candidate representatives, round-robin across control demands.
        while len(accepted) < development + holdout and any(pools.values()):
            for stratum in strata:
                if not pools[stratum] or len(accepted) >= development + holdout:
                    continue
                task, group_id = pools[stratum].pop()
                try:
                    empty = EnvironmentEvaluator.calculate_reward(
                        registry.get_env_constructor(domain), task, list(
                            task.initial_state.message_history or [] if task.initial_state else []))
                except Exception as error:
                    excluded["empty_trajectory_audit_error"] += 1
                    scores.append(dict(task=task.id, error=str(error)))
                    continue
                if empty.reward == 1:
                    excluded["empty_trajectory_passes"] += 1
                    continue
                accepted.append((task, group_id, stratum))
                scores.append(dict(task=task.id, empty_reward=empty.reward,
                                   reward_basis=[value.value for value in task.evaluation_criteria.reward_basis]))
        if len(accepted) < development + holdout:
            atomic_json(output / "incomplete-audit.json", dict(domain=domain, available=len(accepted), excluded=dict(excluded)))
            raise ValueError(f"Only {len(accepted)} audited independent {domain} groups; request a smaller subset")
        # Interleave splits across the round-robin strata ordering.
        counts = dict(development=0, holdout=0)
        for index, (task, group_id, stratum) in enumerate(accepted):
            split = "development" if index % 2 == 0 else "holdout"
            if counts[split] >= {"development": development, "holdout": holdout}[split]:
                split = "holdout" if split == "development" else "development"
            selected.append(dict(task_id=f"{domain}-{split}-{counts[split]:04d}", family=domain,
                                 upstream_id=task.id, split=split, seed=seed + len(selected),
                                 group=group_id, stratum=stratum, task=task.model_dump(mode="json")))
            counts[split] += 1
        audit[domain] = dict(total=len(tasks), eligible=len(eligible), groups=len(groups),
                             reward_bases=dict(Counter("+".join(t.evaluation_criteria.reward_basis) for t in tasks)),
                             exclusions=dict(excluded), score_checks=scores)
    upstream = output / "upstream"
    shutil.copytree(source / "src", upstream / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("pyproject.toml", "uv.lock", "LICENSE"):
        shutil.copyfile(source / name, upstream / name)
    shutil.copytree(source / "data/tau2/user_simulator", upstream / "data/tau2/user_simulator")
    for domain in DOMAINS:
        for path in (source / "data/tau2/domains" / domain).iterdir():
            if path.suffix in {".md", ".toml", ".json"} and path.name not in {
                    "tasks_voice.json", "audio_difficulty.json", "tasks_full.json", "tasks_small.json"}:
                dest = upstream / "data/tau2/domains" / domain / path.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, dest)
    versions = dict(python=sys.version, packages={d.metadata["Name"]: d.version for d in importlib.metadata.distributions()})
    atomic_json(output / "audit.json", audit)
    atomic_json(output / "versions.json", versions)
    files = {str(path.relative_to(output)): digest(path.read_bytes()) for path in output.rglob("*") if path.is_file()}
    manifest = dict(environment="tau2", revision=revision, source=UPSTREAM_URL, tasks=selected, files=files,
                    seed=seed, excluded_groups=sorted(reserved),
                    feedback="Official domain policy, agent tool schemas and messages addressed to the agent only. "
                    "User scenarios, user-tool transcripts, assertions and reference actions remain host-private.",
                    scoring="Unmodified official evaluator with each task's reward_basis; no required-action-path, "
                    "nonempty LLM-assertion, handoff or empty-trajectory-passing tasks in this first subset.",
                    grouping="One task per group; telecom persona variants grouped, retail shared customer/order IDs "
                    "and digit-normalized request templates joined before splitting.")
    atomic_json(output / "manifest.json", manifest)
    return manifest


def load_suite(path):
    path = Path(path).resolve()
    manifest = json.loads((path / "manifest.json").read_text())
    if manifest["revision"] != UPSTREAM_REVISION:
        raise ValueError("Unsupported τ² revision")
    for name, expected in manifest["files"].items():
        if digest((path / name).read_bytes()) != expected:
            raise ValueError("Frozen suite changed: " + name)
    groups = [task["family"] + ":" + task["group"] for task in manifest["tasks"]]
    if len(groups) != len(set(groups)):
        raise ValueError("Repeated task group in frozen subset")
    return manifest


class Tau2Runner:
    """Fresh official environment/user per task; all candidate code stays in the isolated worker."""

    def __init__(self, suite, manifest, client, user_client, worker_image, limits, private):
        self.suite, self.manifest = Path(suite).resolve(), manifest
        versions = json.loads((self.suite / "versions.json").read_text())
        installed = {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}
        if sys.version != versions["python"] or installed != versions["packages"]:
            raise ValueError("Run with the Python environment frozen by prepare (uv sync --frozen --no-dev)")
        self.tasks = {task["task_id"]: task for task in manifest["tasks"]}
        self.client, self.user_client, self.worker_image, self.limits = client, user_client, worker_image, limits
        self.private = Path(private)
        configure(self.suite / "upstream", self.suite / "upstream/data")

    def __call__(self, *, task_id, source, scope, directory, meter, exposed):
        from litellm import ModelResponse
        from tau2.agent.base_agent import HalfDuplexAgent
        from tau2.data_model.message import AssistantMessage, ToolCall, ToolMessage, UserMessage
        from tau2.data_model.simulation import TerminationReason
        from tau2.data_model.tasks import Task
        from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
        from tau2.orchestrator.orchestrator import Orchestrator, Role
        from tau2.registry import registry
        from tau2.user.user_simulator import UserSimulator
        from tau2.utils import llm_utils
        from tau2.utils.utils import get_now

        class ExternalAgent(HalfDuplexAgent):
            pending = None

            def generate_next_message(self, message, state):
                if self.pending is None:
                    raise RuntimeError("External controller did not provide an action")
                result, self.pending = self.pending, None
                return result, state

            def get_init_state(self, message_history=None):
                return None

            def set_seed(self, seed):
                pass  # External agent settings are frozen by the host.

            @classmethod
            def is_stop(cls, message):
                return message.content is not None and "###STOP###" in message.content

        selected = self.tasks[task_id]
        task = Task.model_validate(selected["task"])
        directory.mkdir(parents=True, exist_ok=False)
        atomic_text(directory / "controller.py", source)
        private = self.private / uuid.uuid4().hex
        task_meter = ModelMeter(private / "usage.json", parent=meter, seconds=self.limits.seconds,
                                model_calls=self.limits.model_calls, output_tokens=self.limits.output_tokens)
        started, runtime, orchestrator = time.monotonic(), None, None
        environment_error = None
        row = dict(task_id=task_id, family=selected["family"], status="running", verification_verdict=None)
        original_completion = llm_utils.completion
        original_cost = llm_utils.get_response_cost

        def completion(**kwargs):
            owner = runtime.active_component_id if runtime else None
            request = dict(role="simulated_user", component_id=owner, phase="tool" if owner else "initialization",
                           messages=kwargs["messages"], tools=kwargs.get("tools"), seed=kwargs.get("seed"))
            turn, call = model_call(
                meter=task_meter, scope=scope + ":user", request=request, max_tokens=self.user_client.max_tokens,
                remaining=task_meter.remaining, time_origin=started,
                invoke=lambda allowance, seconds: self.user_client.complete_chat(
                    kwargs["messages"], tools=kwargs.get("tools"), tool_choice=kwargs.get("tool_choice"),
                    seed=kwargs.get("seed"), max_output_tokens=allowance, timeout_seconds=seconds),
            )
            call["response"] = turn.raw
            task_meter.save()
            if (usage_tokens(turn.usage, "completion_tokens") or 0) > call["requested_output_tokens"]:
                raise HostFault("Simulated user exceeded its requested output allowance", usage=turn.usage)
            return ModelResponse(**turn.raw)

        def advance():
            while not orchestrator.done and orchestrator.to_role != Role.AGENT:
                if task_meter.remaining()["seconds"] <= 0:
                    raise BudgetExhausted("time_limit")
                orchestrator.step()
                orchestrator._check_termination()

        def observation():
            message = orchestrator.message
            visible = []
            if isinstance(message, UserMessage) and not message.is_tool_call():
                visible.append(dict(role="user", content=message.content))
            elif isinstance(message, ToolMessage) and message.requestor == "assistant":
                visible.append(dict(role="tool", content=message.content, error=message.error))
            return dict(messages=visible, conversation_done=orchestrator.done)

        def act(name, arguments, timeout):
            nonlocal environment_error
            if orchestrator.done:
                return ToolResult("failed", dict(error="Conversation has ended. Return from the controller.",
                                                 conversation_done=True), "none")
            before = (environment.get_db_hash(), environment.get_user_db_hash())
            if name == "respond_to_user":
                agent.pending = AssistantMessage(role="assistant", content=arguments["message"])
            else:
                agent.pending = AssistantMessage(role="assistant", tool_calls=[ToolCall(
                    id=uuid.uuid4().hex, name=name, arguments=arguments)])
            try:
                orchestrator.step()
                orchestrator._check_termination()
                advance()
            except BudgetExhausted:
                raise
            except Exception as error:
                # A failed user generation leaves the conversation between agent turns.
                # It cannot be recovered by pretending the next agent tool was executed.
                environment_error = error
                atomic_json(private / "environment-error.json", dict(type=type(error).__name__, detail=str(error)))
                raise HostFault("The τ² environment could not advance; details retained privately") from error
            after = (environment.get_db_hash(), environment.get_user_db_hash())
            value = observation()
            failed = any(item.get("error") for item in value["messages"])
            return ToolResult("failed" if failed else "ok", value,
                              "applied" if before != after or name == "respond_to_user" else "none")

        try:
            # Retain the official prompts, message conversion and user-tool behavior.
            # Only provider transport is replaced; the host owns retries and every charge.
            llm_utils.completion = completion
            # The configured endpoint has no frozen dollar-price table. Unknown is not zero.
            llm_utils.get_response_cost = lambda response: None
            environment = registry.get_env_constructor(selected["family"])()
            agent = ExternalAgent(environment.get_tools(), environment.get_policy())
            user = UserSimulator(tools=environment.get_user_tools(include=task.user_tools) if environment.user_tools else None,
                                 instructions=task.user_scenario, llm=self.user_client.model,
                                 llm_args={"temperature": self.user_client.temperature, "num_retries": 0})
            orchestrator = Orchestrator(domain=selected["family"], agent=agent, user=user, environment=environment,
                                        task=task, seed=selected["seed"], max_steps=self.limits.actions * 8,
                                        timeout=self.limits.seconds)
            orchestrator._run_start_time, orchestrator._run_start_perf = get_now(), time.perf_counter()
            orchestrator.initialize()
            advance()
            disclosed = dict(problem="Help the simulated customer under the domain policy. All customer-facing replies, "
                             "questions and confirmations must use respond_to_user. Domain tools change the simulated "
                             "environment. When conversation_done is true, or your work is complete, return a final "
                             "controller response. A final return is not delivered to the customer and does not verify success.",
                             policy=environment.get_policy(), initial_observation=observation())
            atomic_json(directory / "task.json", disclosed)
            tools = []
            for item in environment.get_tools():
                function = item.openai_schema["function"]
                name = function["name"]
                tools.append(Tool(name, function["description"], function["parameters"],
                                  "mutate" if environment.tools.tool_mutates_state(name) else "inspect",
                                  lambda arguments, timeout, name=name: act(name, arguments, timeout),
                                  preserve_observation_fields=("conversation_done",)))
            tools.append(Tool("respond_to_user", "Send a message to the simulated customer and receive their response. "
                              "The customer may use their own device tools. Each user-model attempt consumes task budget.",
                              object_schema({"message": {"type": "string"}}), "mutate",
                              lambda arguments, timeout: act("respond_to_user", arguments, timeout),
                              preserve_observation_fields=("conversation_done",)))
            runtime = ControllerRuntime(task=disclosed, tools=tuple(tools), client=self.client, meter=task_meter,
                                        limits=self.limits, trace_path=directory / "trace.json", scope=scope,
                                        image=self.worker_image, exposed=exposed)
            record = runtime.run(source)
            if environment_error is not None:
                record.update(status="operational_failure" if isinstance(environment_error, OperationalProblem)
                              else "host_fault", stop_reason="tau2_environment_failed")
                runtime.save()
            row.update(status=record["status"], stop_reason=record.get("stop_reason"))
            # No task worker is alive here. Close the official simulation, then score.
            if not orchestrator.done:
                orchestrator.done = True
                orchestrator.termination_reason = (
                    TerminationReason.AGENT_STOP if record["status"] == "completed" else
                    TerminationReason.MAX_STEPS if record["status"] == "budget_exhausted" else TerminationReason.AGENT_ERROR)
            simulation = orchestrator._finalize()
            atomic_json(private / "simulation.json", simulation.model_dump(mode="json"))
            try:
                verification = evaluate_simulation(simulation, task, EvaluationType.ALL, False, selected["family"])
                atomic_json(private / "verification.json", verification.model_dump(mode="json"))
                # Public feedback contains scores only, never reference actions or assertions.
                public_score = dict(reward=verification.reward, reward_basis=verification.reward_basis,
                                    reward_breakdown=verification.reward_breakdown,
                                    termination_reason=simulation.termination_reason.value)
                atomic_json(directory / "verification.json", public_score)
                verdict = (None if record["status"] in {"host_fault", "operational_failure"} else
                           "pass" if record["status"] == "completed" and verification.reward == 1 else "fail")
                row.update(verification=public_score, verification_verdict=verdict)
            except Exception as error:
                atomic_json(private / "verification-error.json", dict(type=type(error).__name__, detail=str(error)))
                row.update(status="verifier_failure", execution_status=record["status"],
                           verification_error="Official evaluator failed; details retained privately")
        except BudgetExhausted as error:
            row.update(status="budget_exhausted", stop_reason=str(error), verification_verdict="fail")
        except OperationalProblem as error:
            atomic_json(private / "initialization-error.json", dict(type=type(error).__name__, detail=str(error)))
            row.update(status="operational_failure", stop_reason=error.code)
        except Exception as error:
            atomic_json(private / "initialization-error.json", dict(type=type(error).__name__, detail=str(error)))
            row.update(status="host_fault", stop_reason="tau2_host_failed")
        except BaseException:
            row.update(status="interrupted", stop_reason="host_interrupted")
            raise
        finally:
            llm_utils.completion = original_completion
            llm_utils.get_response_cost = original_cost
            if orchestrator is not None:
                # Keep partial official trajectories after failures; no Python continuation resumes.
                atomic_json(private / "trajectory.json", [message.model_dump(mode="json") for message in orchestrator.trajectory])
                orchestrator._cleanup()
            user_calls = [call for call in task_meter.calls if call["request"].get("role") == "simulated_user"]
            row.update(usage=task_meter.summary(), user_usage=model_usage(user_calls),
                       agent_usage=model_usage(runtime.calls if runtime else []),
                       actions=runtime.actions_used if runtime else 0, elapsed_seconds=time.monotonic() - started)
            if runtime is not None:
                runtime.record["environment_usage"] = row["user_usage"]
                runtime.save()
                write_trace_report(runtime.record, directory / "trace.html")
                row.update(trace="trace.json", report="trace.html")
            atomic_json(directory / "result.json", row)
        return row
