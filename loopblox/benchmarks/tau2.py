"""Pinned τ² text domains, audited task subsets and the existing controller runtime."""

from __future__ import annotations

from collections import Counter, defaultdict
import importlib.metadata
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import time
import uuid

from loopblox.runtime.components import object_schema
from loopblox.runtime.controller import ControllerRuntime, Limits, ModelMeter, model_call, model_usage
from loopblox.runtime.model import BudgetExhausted, HostFault, OperationalProblem, Tool, ToolResult, usage_tokens
from loopblox.runtime.io import atomic_json, atomic_text, digest
from loopblox.report import write_trace_report



UPSTREAM_REVISION = "672227c6b6676edc20d57ea53b7000262aae77b9"
UPSTREAM_URL = "https://github.com/sierra-research/tau2-bench"
DEFAULT_TASK_LIMITS = Limits(seconds=900, actions=40, model_calls=64, output_tokens=65536)


def configure(source, data):
    """Called before any tau2 import, once per CLI process."""
    if "tau2.registry" in sys.modules:
        raise RuntimeError("Start a new process when changing the frozen τ² environment")
    os.environ["TAU2_DATA_DIR"] = str(Path(data).resolve())
    sys.path.insert(0, str(Path(source).resolve() / "src"))
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="ERROR")


def task_groups(tasks):
    """Keep telecom persona variants in the same task family."""
    groups = defaultdict(list)
    for task in tasks:
        groups[re.sub(r"\[PERSONA:.*?\]", "", task.id)].append(task)
    return list(groups.values())



def prepare_telecom_suite(output, *, source, seed, development, exclude_suites=()):
    """Freeze audited telecom training tasks and the sealed official test split."""
    if development < 1:
        raise ValueError("Use a positive development count")
    domain = "telecom"
    source, output = Path(source).resolve(), Path(output).resolve()
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != UPSTREAM_REVISION or subprocess.run(["git", "-C", str(source), "diff", "--quiet", "HEAD"]).returncode:
        raise ValueError("Use the clean pinned upstream revision " + UPSTREAM_REVISION)
    output.mkdir(parents=True, exist_ok=False)
    configure(source, source / "data")
    from tau2.data_model.tasks import RewardType, Task
    from tau2.data_model.simulation import SimulationRun, TerminationReason
    from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
    from tau2.evaluator.evaluator_env import EnvironmentEvaluator
    from tau2.registry import registry
    folder = source / "data/tau2/domains" / domain
    official = json.loads((folder / "split_tasks.json").read_text())
    tasks = [Task.model_validate(item) for item in json.loads((folder / "tasks.json").read_text())]
    by_id = {task.id: task for task in tasks}
    groups = {task.id: digest("\n".join(sorted(item.id for item in group)).encode())[:16]
              for group in task_groups(tasks) for task in group}
    reserved, reservation_sources = set(), []
    for path in exclude_suites:
        path = Path(path).resolve() / "manifest.json"
        manifest = json.loads(path.read_text())
        reserved.update((task["family"], groups.get(task["upstream_id"], task["group"]))
                        for task in manifest["tasks"] if task["family"] == domain)
        reserved.update(tuple(group) for group in manifest.get("excluded_groups", []))
        reservation_sources.append(dict(path=str(path), sha256=digest(path.read_bytes())))
    selected, checks, exclusions = [], [], Counter()
    audited = {}

    def audit_task(upstream_id):
        if upstream_id not in audited:
            task = by_id[upstream_id]
            criteria = task.evaluation_criteria
            if not criteria:
                raise ValueError("Official task has no evaluation criteria: " + upstream_id)
            if (criteria.nl_assertions or criteria.communicate_info or
                    RewardType.ENV_ASSERTION not in criteria.reward_basis or not criteria.env_assertions or
                    not set(criteria.reward_basis) <= {RewardType.ENV_ASSERTION, RewardType.ACTION}):
                raise ValueError("Telecom requires deterministic official criteria: " + upstream_id)
            empty = EnvironmentEvaluator.calculate_reward(registry.get_env_constructor(domain), task,
                list(task.initial_state.message_history or [] if task.initial_state else []))
            simulation = SimulationRun(id="empty-audit", task_id=upstream_id, start_time="", end_time="",
                duration=0, termination_reason=TerminationReason.AGENT_STOP,
                messages=list(task.initial_state.message_history or [] if task.initial_state else []))
            full_reward = evaluate_simulation(simulation, task, EvaluationType.ALL, False, domain).reward
            audited[upstream_id] = dict(upstream_id=upstream_id, group=groups[upstream_id],
                reward_basis=[value.value for value in criteria.reward_basis],
                empty_environment_reward=empty.reward,
                empty_full_reward=full_reward,
                nl_assertion_count=len(criteria.nl_assertions or []),
                handoff=any(action.name == "transfer_to_human_agents" for action in criteria.actions or []))
        return audited[upstream_id]

    rng, pools = random.Random(seed), defaultdict(list)
    test_groups = {groups[upstream_id] for upstream_id in official["test"]}
    seen = set()
    for upstream_id in official["train"]:
        task, group = by_id[upstream_id], groups[upstream_id]
        if (domain, group) in reserved:
            exclusions["reserved_family"] += 1
        elif group in test_groups:
            exclusions["family_crosses_official_split"] += 1
        elif group in seen:
            exclusions["additional_family_variant"] += 1
        elif not task.evaluation_criteria or set(task.evaluation_criteria.reward_basis) != {RewardType.ENV_ASSERTION}:
            exclusions["not_environment_assertions_only"] += 1
        elif audit_task(upstream_id)["empty_environment_reward"] == 1:
            exclusions["empty_trajectory_passes"] += 1
        else:
            seen.add(group)
            match = re.match(r"\[([^]]+)\]([^[]+)", upstream_id)
            faults = len(match[2].split("|"))
            stratum = match[1] + ("/1" if faults == 1 else "/2-3" if faults <= 3 else "/4+")
            pools[stratum].append(upstream_id)
    for pool in pools.values():
        rng.shuffle(pool)
    strata = sorted(pools)
    rng.shuffle(strata)
    development_ids = []
    while len(development_ids) < development and any(pools.values()):
        for stratum in strata:
            if pools[stratum] and len(development_ids) < development:
                development_ids.append(pools[stratum].pop())
    selection_rule = ("Seeded shuffle within category/fault-count strata, then round-robin over seeded strata. "
        "One representative per family from official train; environment-assertion-only, empty reward below one. "
        "Exclude reserved and official-test families. Candidate execution outcomes do not inform selection.")
    if len(development_ids) != development:
        atomic_json(output / "incomplete-audit.json", dict(domain=domain, available=len(development_ids),
                    requested=development, exclusions=dict(exclusions)))
        raise ValueError("Not enough eligible official training families for the requested development batch")
    for split, ids in (("development", development_ids), ("holdout", official["test"])):
        for index, upstream_id in enumerate(ids):
            task = by_id[upstream_id]
            check = audit_task(upstream_id)
            checks.append({**check, "split": split, "reserved_family": (domain, groups[upstream_id]) in reserved})
            selected.append(dict(task_id=f"{domain}-{split}-{index:04d}", family=domain, upstream_id=upstream_id,
                split=split, seed=seed + len(selected), group=groups[upstream_id], task=task.model_dump(mode="json")))
    audit = {domain: dict(total=len(tasks), official_train=len(official["train"]), official_test=len(official["test"]),
        selected=len(selected), score_checks=checks,
        exclusions=dict(exclusions), selection=selection_rule,
        policy="All official test IDs retain their original order and reward basis, including required actions. "
               "Related groups and prior exposure must be reported; empty environment scores alone do not "
               "establish action or NL assertion outcomes.")}
    atomic_json(output / "selection.json", dict(domain=domain, seed=seed, development_rule=selection_rule,
        development_upstream_ids=development_ids, holdout_rule="Every official test ID, in the pinned split order",
        reservation_sources=reservation_sources, audit="audit.json",
        exposure="Reservation manifests record prior suite membership, not proof of execution. Their families "
                 "are excluded from development; all official test IDs remain, with reserved-family flags in "
                 "the audit. Other historical exposure has not been exhaustively inventoried; do not claim "
                 "that the full test set is globally unseen."))
    return freeze_suite(output, source, selected, audit, seed, reserved,
        scoring="Unmodified official evaluator, including environment and required-action checks; telecom has no "
                "NL assertions and needs no grader model calls.",
        grouping="Related families are recorded; every official test task is retained, including related variants.")


def freeze_suite(output, source, selected, audit, seed, reserved, *, scoring, grouping):
    """Freeze the benchmark implementation, data and audited task selection once."""
    upstream = output / "upstream"
    shutil.copytree(source / "src", upstream / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("pyproject.toml", "uv.lock", "LICENSE"):
        shutil.copyfile(source / name, upstream / name)
    shutil.copytree(source / "data/tau2/user_simulator", upstream / "data/tau2/user_simulator")
    for domain in sorted({task["family"] for task in selected}):
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
    manifest = dict(environment="tau2", revision=UPSTREAM_REVISION, source=UPSTREAM_URL, tasks=selected, files=files,
                    seed=seed, excluded_groups=sorted(reserved),
                    feedback="Official domain policy, agent tool schemas and messages addressed to the agent only. "
                    "User scenarios, user-tool transcripts, assertions and reference actions remain host-private.",
                    scoring=scoring, grouping=grouping)
    atomic_json(output / "manifest.json", manifest)
    return load_suite(output)


def load_suite(path):
    path = Path(path).resolve()
    manifest = json.loads((path / "manifest.json").read_text())
    if manifest["revision"] != UPSTREAM_REVISION:
        raise ValueError("Unsupported τ² revision")
    for name, expected in manifest["files"].items():
        if digest((path / name).read_bytes()) != expected:
            raise ValueError("Frozen suite changed: " + name)
    identities = [(task["family"], task["upstream_id"]) for task in manifest["tasks"]]
    if len(identities) != len(set(identities)):
        raise ValueError("Repeated upstream task in frozen suite")
    splits = {domain: json.loads((path / "upstream/data/tau2/domains" / domain / "split_tasks.json").read_text())
              for domain in {task["family"] for task in manifest["tasks"]}}
    for task in manifest["tasks"]:
        official = {"development": "train", "holdout": "test"}[task["split"]]
        if task["upstream_id"] not in splits[task["family"]][official]:
            raise ValueError(f"{task['task_id']} is not in official {official}; frozen historical code is required for old custom splits")
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
        environment_error, grading = None, False
        row = dict(task_id=task_id, family=selected["family"], status="running", verification_verdict=None)
        original_completion = llm_utils.completion
        original_cost = llm_utils.get_response_cost

        def completion(**kwargs):
            owner = runtime.active_component_id if runtime and not grading else None
            role = "grader" if grading else "simulated_user"
            request = dict(role=role, component_id=owner, phase="evaluation" if grading else "tool" if owner else "initialization",
                           messages=kwargs["messages"], tools=kwargs.get("tools"), seed=kwargs.get("seed"))
            turn, call = model_call(
                meter=task_meter, scope=scope + (":grader" if grading else ":user"), request=request, max_tokens=self.user_client.max_tokens,
                remaining=task_meter.remaining, time_origin=started,
                invoke=lambda allowance: self.user_client.complete_chat(
                    kwargs["messages"], tools=kwargs.get("tools"), tool_choice=kwargs.get("tool_choice"),
                    seed=kwargs.get("seed"), max_output_tokens=allowance, timeout_seconds=self.user_client.timeout,
                    session_id=private.name + ":" + role),
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
                                        task=task, seed=selected["seed"],
                                        # The pinned upstream only compares this internal value;
                                        # persisted limits retain None rather than JSON Infinity.
                                        max_steps=math.inf if self.limits.actions is None else self.limits.actions * 8,
                                        # The host meter owns charged time, including excluded
                                        # no-effect model timeout waits. Upstream uses wall time.
                                        timeout=None)
            orchestrator._run_start_time, orchestrator._run_start_perf = get_now(), time.perf_counter()
            orchestrator.initialize()
            initialization_exhaustion = None
            try:
                advance()
            except BudgetExhausted as error:
                # A user turn can exhaust the shared meter before an agent worker
                # starts. Close and score that actual trajectory below, too.
                initialization_exhaustion = error
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
            if initialization_exhaustion is None:
                record = runtime.run(source)
            else:
                record = runtime.record
                record.update(status="budget_exhausted", stop_reason=str(initialization_exhaustion),
                              stop_phase="initialization", elapsed_seconds=0, timeout_wait_seconds=0,
                              budget_seconds=0)
                runtime.save()
            if environment_error is not None:
                record.update(status="operational_failure" if isinstance(environment_error, OperationalProblem)
                              else "host_fault", stop_reason="tau2_environment_failed")
                runtime.save()
            row.update(status=record["status"], stop_reason=record.get("stop_reason"))
            if initialization_exhaustion is not None:
                row["stop_phase"] = "initialization"
            # No task worker is alive here. Close the official simulation, then score.
            if not orchestrator.done:
                orchestrator.done = True
                orchestrator.termination_reason = (
                    TerminationReason.AGENT_STOP if record["status"] == "completed" else
                    TerminationReason.MAX_STEPS if record["status"] == "budget_exhausted" else TerminationReason.AGENT_ERROR)
            simulation = orchestrator._finalize()
            atomic_json(private / "simulation.json", simulation.model_dump(mode="json"))
            try:
                grading = True
                verification = evaluate_simulation(simulation, task, EvaluationType.ALL, False, selected["family"])
                expected = task.evaluation_criteria.nl_assertions if task.evaluation_criteria else None
                if (expected and "NL_ASSERTION" in (verification.reward_basis or [])
                        and Counter(check.nl_assertion for check in verification.nl_assertions or []) != Counter(expected)):
                    raise ValueError("The official grader did not return exactly one result per assertion")
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
                if isinstance(error, BudgetExhausted):
                    row.update(verification_error_code="budget_exhausted", verification_stop_reason=str(error))
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
            grader_calls = [call for call in task_meter.calls if call["request"].get("role") == "grader"]
            row.update(usage=task_meter.summary(), user_usage=model_usage(user_calls),
                       grader_usage=model_usage(grader_calls),
                       agent_usage=model_usage(runtime.calls if runtime else []),
                       actions=runtime.actions_used if runtime else 0, elapsed_seconds=time.monotonic() - started)
            row["budget_seconds"] = max(0, row["elapsed_seconds"] - row["usage"]["timeout_wait_seconds"])
            if runtime is not None:
                runtime.record["environment_usage"] = model_usage(user_calls + grader_calls)
                runtime.save()
                write_trace_report(runtime.record, directory / "trace.html")
                row.update(trace="trace.json", report="trace.html")
            atomic_json(directory / "result.json", row)
        return row
