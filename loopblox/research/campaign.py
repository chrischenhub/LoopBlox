"""Frozen single-benchmark continuous campaigns; no final-test dispatch path."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

from loopblox import ROOT, snapshot_implementation
from loopblox.analysis import jev
from loopblox.benchmarks.tau2 import Tau2Runner, load_suite
from loopblox.research.session import RANKING_RULE, ResearchSession, validate_experiment
from loopblox.research.codex import native_usage
from loopblox.runtime.components import catalog
from loopblox.runtime.controller import Limits, model_usage, excluded_timeout_seconds
from loopblox.runtime.io import atomic_json, atomic_text, digest, image_id
from loopblox.runtime.model import ChatCompletionsClient, HostFault, load_env

TASK_LIMITS = Limits(seconds=900, actions=60, model_calls=256, output_tokens=65536)


def read(path):
    return json.loads(Path(path).read_text())


def model_settings(client):
    if client is None:
        return None
    return {key: getattr(client, key) for key in (
        "model", "base_url", "api", "reasoning_effort", "structured_output", "temperature", "max_tokens", "timeout")}


def evaluation_workers():
    """Provider policy for new campaigns; freeze it before opening dispatch."""
    load_env()
    return 3 if os.environ.get("LOOPBLOX_PROVIDER", "freeinference") == "opencode_go" else 1


def clients(protocol=None, *, solo_mode=False):
    if protocol is not None:
        solo_mode = protocol.get("solo_mode", False)
    client = ChatCompletionsClient.from_env()
    user = None if solo_mode else ChatCompletionsClient(client.api_key, client.base_url, client.model,
                                 temperature=0, max_tokens=2048, timeout=client.timeout, api=client.api)
    if protocol:
        # Pre-Responses campaigns used only serial Chat Completions with JSON
        # Schema; those fixed settings were implicit in their frozen sources.
        defaults = dict(api="chat_completions", reasoning_effort=None, structured_output="json_schema")
        for current, name in ((client, "model"), (user, "user_model")):
            expected = None if protocol[name] is None else {**defaults, **protocol[name]}
            if model_settings(current) != expected:
                raise ValueError("Model settings differ from the frozen campaign")
    return client, user


def development_tasks(suite, manifest, *, solo_mode=False):
    """Validate official membership and deterministic scoring before opening dispatch."""
    development = [task for task in manifest["tasks"] if task["split"] == "development"]
    holdout = [task for task in manifest["tasks"] if task["split"] == "holdout"]
    if len(development) != 10 or any(task["family"] != "telecom" for task in manifest["tasks"]):
        raise ValueError("Continuous research requires ten frozen official telecom training tasks")
    splits = read(Path(suite) / "upstream/data/tau2/domains/telecom/split_tasks.json")
    if [task["upstream_id"] for task in holdout] != splits["test"]:
        raise ValueError("Preserve every official test task in its original order")
    groups = {task["group"] for task in development}
    if len(groups) != 10 or groups & {task["group"] for task in holdout}:
        raise ValueError("Development families must be distinct and disjoint from test")
    if solo_mode:
        for task in development:
            initial = task["task"].get("initial_state") or {}
            if not task["task"].get("ticket") or initial.get("message_history"):
                raise ValueError("No-user requires an official ticket and no initial message history: " + task["task_id"])
    for task in manifest["tasks"]:
        criteria = task["task"].get("evaluation_criteria") or {}
        basis = set(criteria.get("reward_basis", []))
        allowed = {"ENV_ASSERTION"} if task["split"] == "development" else {"ENV_ASSERTION", "ACTION"}
        if ("ENV_ASSERTION" not in basis or not basis <= allowed or not criteria.get("env_assertions")
                or criteria.get("nl_assertions") or criteria.get("communicate_info")):
            raise ValueError("Only audited deterministic telecom criteria are admitted: " + task["task_id"])
    return development


def recovery_task_budgets(attempts, limits, *, restart_candidate=None):
    """Derive unfinished logical tasks' remaining caps from original attempts only."""
    states = []
    for attempt in attempts:
        path = Path(attempt) / "research/private/state.json"
        states.append(read(path) if path.exists() else {"evaluations": []})
    tasks = {}
    scopes = {}
    # A failed recovery startup may have no state yet; it must not erase an
    # earlier evaluation plan, its completed batches or its remaining budgets.
    batches = {batch["evaluation_id"]: batch for state in states for batch in state["evaluations"]}
    sources = {cid: source["sha256"] for batch in batches.values() for cid, source in batch["sources"].items()}
    for batch in batches.values():
        if batch.get("feedback_ready"):
            continue
        for index, row in enumerate(batch["runs"]):
            source = batch["sources"][row["candidate_id"]]["sha256"]
            key = (source, row["task_id"])
            tasks[key] = dict(task_id=row["task_id"], source_sha256=source,
                             spent=dict(seconds=0.0, actions=0, model_calls=0, output_tokens=0))
            scopes[f"{batch['evaluation_id']}-{index}"] = key
    def reset_spend(candidate):
        if candidate not in sources:
            raise ValueError(f"Unknown restart candidate: {candidate}")
        for (source, _), task in tasks.items():
            if source == sources[candidate]:
                task["spent"] = dict(seconds=0.0, actions=0, model_calls=0, output_tokens=0)

    for attempt, state in zip(attempts, states):
        # An explicit restart begins a new allowance, not a new cumulative ledger.
        # On later recovery, charge every attempt after that boundary normally.
        restarted = read(Path(attempt) / "protocol.json").get("recovery", {}).get("restart_candidate")
        if restarted:
            reset_spend(restarted)
        for batch in state["evaluations"]:
            # Completed batches may have been copied into multiple attempts.
            if batch.get("feedback_ready"):
                continue
            for row in batch["runs"]:
                key = (batch["sources"][row["candidate_id"]]["sha256"], row["task_id"])
                if key not in tasks or row["status"] == "not_started":
                    continue
                path = Path(attempt) / "research/public/evaluations" / batch["evaluation_id"] / row["directory"] / "result.json"
                if not path.is_file():
                    raise ValueError(f"Cannot recover without the original task accounting: {path}")
                result = read(path)
                if result["task_id"] != row["task_id"]:
                    raise ValueError(f"Recovery task identity changed: {path}")
                spend = dict(seconds=result["budget_seconds"], actions=result["actions"],
                             model_calls=result["usage"]["model_calls"],
                             output_tokens=result["usage"]["charged_output_tokens"])
                for name, value in spend.items():
                    tasks[key]["spent"][name] += value
    if restart_candidate is not None:
        if not any(source == sources.get(restart_candidate) for source, _ in tasks):
            raise ValueError("Explicit restart requires a candidate in an unfinished evaluation")
        reset_spend(restart_candidate)
    for task in tasks.values():
        task["limits"] = {name: None if cap is None else max(0, cap - task["spent"][name])
                          for name, cap in limits.items()}
        # Do not replenish an exhausted task or dispatch part of an inadmissible batch.
        exhausted = [name for name, value in task["limits"].items() if value == 0]
        if exhausted:
            raise ValueError(f"Recovery budget exhausted for {task['task_id']}: {', '.join(exhausted)}")
        Limits(**task["limits"])
    return {scope: tasks[key] for scope, key in scopes.items()}


def verify(root):
    root = Path(root).resolve()
    protocol = read(root / "protocol.json")
    if protocol["kind"] != "continuous_telecom":
        raise ValueError("Not a continuous telecom campaign")
    solo_mode = protocol.get("solo_mode", False)
    if type(solo_mode) is not bool or solo_mode != (protocol["user_model"] is None):
        raise ValueError("Frozen interaction mode and user model disagree")
    if protocol["research_budgets"] != dict(seconds=None, model_calls=None, output_tokens=None, task_runs=None):
        raise ValueError("This continuous protocol requires explicitly uncapped shared research budgets")
    for name, expected in protocol["implementation_sha256"].items():
        if digest((root / "implementation" / name).read_bytes()) != expected:
            raise ValueError("Frozen implementation changed: " + name)
    if digest((root / "suite/manifest.json").read_bytes()) != protocol["suite_manifest_sha256"]:
        raise ValueError("Frozen suite manifest changed")
    manifest = load_suite(root / "suite")
    if [task["task_id"] for task in development_tasks(root / "suite", manifest, solo_mode=solo_mode)] != protocol["task_ids"]:
        raise ValueError("Frozen task IDs changed")
    for name, expected in protocol.get("recovery", {}).get("imported_files", {}).items():
        if digest((root / name).read_bytes()) != expected:
            raise ValueError("Preserved recovery record changed: " + name)
    if "task_budgets" in protocol.get("recovery", {}):
        derived = recovery_task_budgets(sorted((root / "private/prior").glob("attempt-*")), protocol["task_limits"],
                                       restart_candidate=protocol["recovery"].get("restart_candidate"))
        if derived != protocol["recovery"]["task_budgets"]:
            raise ValueError("Recovery task budgets differ from original accounting")
    return protocol


def prepare(output, *, suite=None, worker_image="python:3.12-slim", previous=None, reason=None,
            resume_stopped=False, restart_candidate=None, solo_mode=None):
    """Freeze a new attempt; recovery copies originals and starts a fresh researcher."""
    root = Path(output).resolve()
    previous = Path(previous).resolve() if previous else None
    old = verify(previous) if previous else None
    if old and solo_mode is not None and solo_mode != old.get("solo_mode", False):
        raise ValueError("Changing interaction mode requires a fresh campaign and baseline")
    solo_mode = old.get("solo_mode", False) if old else bool(solo_mode)
    if restart_candidate is not None and old is None:
        raise ValueError("A candidate restart requires its previous campaign")
    if old:
        closed = read(previous / "result.json")
        stop_path = previous / "stop-request.json"
        stop = read(stop_path) if stop_path.exists() else {}
        stopped = closed["status"] == "stopped" and closed.get("research_status") == "user_stopped"
        failed = (closed["status"] == "interrupted" and closed.get("research_status") != "user_stopped"
                  and (not stop_path.exists() or stop.get("reason") == "infrastructure_failure"))
        if not (failed or (stopped and resume_stopped)):
            raise ValueError("Recovery requires a closed infrastructure failure, not a user stop or budget exhaustion")
        if not reason or not reason.strip():
            raise ValueError("Recovery requires a recorded diagnosis or repair reason")
        suite, worker_image = previous / "suite", old["worker_image"]
        task_budgets = recovery_task_budgets(
            [*sorted((previous / "private/prior").glob("attempt-*")), previous], old["task_limits"],
            restart_candidate=restart_candidate)
    suite = Path(suite).resolve()
    manifest = load_suite(suite)
    tasks = development_tasks(suite, manifest, solo_mode=solo_mode)
    client, user = clients(old, solo_mode=solo_mode)
    worker = image_id(worker_image)
    configuration = jev.configuration()
    experiment = validate_experiment(read(ROOT / "experiments/tau2.json"))
    experiment["question"] += (
        " This campaign uses official No-user (solo) mode: a fixed task ticket, official policy, "
        "combined agent and user tools, and done. There is no simulated-user model or conversation. "
        "Private scenarios and evaluator internals remain unavailable."
        if solo_mode else
        " This campaign uses the official interactive user simulator; its model calls share task budgets. "
        "The environment supplies customer messages addressed to the agent.")
    baseline = (ROOT / "controllers/reactive.py").read_text()
    if old and any((configuration != old["jev"], worker != old["worker_image"],
                    evaluation_workers() != old.get("evaluation_workers", 1),
                    vars(TASK_LIMITS) != old["task_limits"], experiment != old["experiment"],
                    digest(baseline.encode()) != old["baseline_sha256"], catalog() != old["components"])):
        raise ValueError("Recovery must preserve tasks, limits, baseline, components, models and Jev configuration")
    root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(suite, root / "suite")
    protocol = dict(kind="continuous_telecom", campaign_id=old["campaign_id"] if old else root.name,
        task_ids=[task["task_id"] for task in tasks], worker_image=worker, task_limits=vars(TASK_LIMITS),
        research_budgets=dict(seconds=None, model_calls=None, output_tokens=None, task_runs=None),
        model=model_settings(client), user_model=model_settings(user), experiment=experiment,
        evaluation_workers=evaluation_workers(), solo_mode=solo_mode,
        components=catalog(), baseline_sha256=digest(baseline.encode()), jev=configuration,
        ranking=RANKING_RULE, suite_manifest_sha256=digest((root / "suite/manifest.json").read_bytes()),
        implementation_sha256=snapshot_implementation(root))
    if old:
        prior = root / "private/prior"
        prior.mkdir(parents=True)
        for path in sorted((previous / "private/prior").glob("attempt-*")):
            shutil.copytree(path, prior / path.name, symlinks=True)
        attempt = prior / f"attempt-{len(list(prior.iterdir())) + 1:04d}"
        # Flatten prior attempts so each original ledger is counted exactly once.
        def ignore(path, names):
            if Path(path) == previous / "private":
                return {"prior"}
            if Path(path) == previous / "research/private":
                return {"research-work", "native-binaries"}
            return {"__pycache__"}
        shutil.copytree(previous, attempt, ignore=ignore, symlinks=True)
        protocol["recovery"] = dict(previous=str(previous), reason=reason,
            resumed_user_stop=stopped,
            task_budgets=task_budgets,
            latest_attempt=str(attempt.relative_to(root)),
            not_before=closed.get("closed_at", 0) + (14 * 60 if "service_not_ready" in closed.get("failure_codes", []) else 0),
            implementation_changes={name: dict(previous=old["implementation_sha256"].get(name),
                                               current=protocol["implementation_sha256"].get(name))
                for name in sorted(set(old["implementation_sha256"]) | set(protocol["implementation_sha256"]))
                if old["implementation_sha256"].get(name) != protocol["implementation_sha256"].get(name)},
            imported_files={str(path.relative_to(root)): digest(path.read_bytes())
                            for path in prior.rglob("*") if path.is_file() and not path.is_symlink()})
        if restart_candidate is not None:
            protocol["recovery"]["restart_candidate"] = restart_candidate
        native_setup = attempt / "research/private/researcher-configuration.json"
        if old.get("expected_researcher"):
            protocol["expected_researcher"] = old["expected_researcher"]
        elif native_setup.exists():
            protocol["expected_researcher"] = read(native_setup)
    atomic_json(root / "protocol.json", protocol)
    atomic_json(root / "result.json", dict(status="prepared", campaign_id=protocol["campaign_id"]))
    return root


def status(root):
    """Read-only projection of live state and original ledgers, including failed attempts."""
    root = Path(root)
    result = read(root / "result.json")
    state_path = root / "research/private/state.json"
    state = read(state_path) if state_path.exists() else {}
    calls, native, attempts = [], [], []
    task_runs, charged_seconds = 0, 0.0
    for attempt in [*sorted((root / "private/prior").glob("attempt-*")), root]:
        private = attempt / "research/private"
        ledger = private / "research-usage.json"
        usage_record = read(ledger) if ledger.exists() else {}
        usage = usage_record.get("calls", [])
        calls.extend(usage)
        attempt_state = read(private / "state.json") if (private / "state.json").exists() else {}
        count = attempt_state.get("task_runs_used", 0)
        task_runs += count
        record = read(attempt / "result.json")
        elapsed = record.get("elapsed_seconds", max(0, time.time() - record["started_at"]) if record.get("started_at") else 0)
        charged = max(0, elapsed - excluded_timeout_seconds(usage, usage_record.get("activities", [])))
        charged_seconds += charged
        attempts.append(dict(path=str(attempt), task_runs=count, charged_seconds=charged))
        path = private / "research-trace.json"
        if path.exists():
            trace = read(path)
            native.append(dict(attempt=str(attempt), usage=native_usage(trace.get("calls", [])),
                               coverage="Completed CLI turn usage; provider attempts and missing usage remain unknown"))
    return dict(**result, session_status=state.get("status"), incumbent=state.get("selected"),
        iterations=state.get("iterations", []), pending_candidates=state.get("pending_candidates", []),
        evaluations=[dict(evaluation_id=batch["evaluation_id"], status=batch["status"],
                          completed=batch.get("feedback_ready", False), summary=batch.get("summary"))
                     for batch in state.get("evaluations", [])],
        cumulative_task_runs=task_runs, cumulative_usage=model_usage(calls),
        cumulative_charged_seconds=charged_seconds, native_researcher_usage=native, attempts=attempts)


def write_report(root):
    report = status(root)
    lines = ["# Continuous telecom research", "", f"Status: {report.get('session_status') or report['status']}",
             f"Incumbent: {report['incumbent']}", f"Task attempts: {report['cumulative_task_runs']}",
             "", "| Iteration | Candidates | Incumbent |", "| --- | --- | --- |"]
    for row in report["iterations"]:
        lines.append(f"| {row['iteration']} | {', '.join(row['candidate_ids'])} | {row['incumbent']} |")
    lines += ["", "All results concern reused training tasks. Missing scores remain missing. "
              "No test tasks were dispatched. Usage, incomplete batches and native coverage are in status.json."]
    atomic_text(root / "report.md", "\n".join(lines) + "\n")
    atomic_json(root / "status.json", report)
    return report


def failure_codes(calls, evaluations, public):
    """Derive campaign failures from transport attempts and authoritative task records."""
    codes = {call["failure_code"] for call in calls if call.get("failure_code")}
    for batch in evaluations:
        for row in batch["runs"]:
            codes.update(row[key] for key in ("code", "verification_error_code") if row.get(key))
            trace = Path(public) / "evaluations" / batch["evaluation_id"] / row["directory"] / "trace.json"
            if trace.is_file():
                code = read(trace).get("code")
                if code:
                    codes.add(code)
    return sorted(codes)


def run(root):
    root = Path(root).resolve()
    protocol = verify(root)
    if ROOT != root / "implementation":
        raise ValueError("Run this campaign through its frozen implementation")
    if (protocol["ranking"] != RANKING_RULE or protocol["task_limits"] != vars(TASK_LIMITS)
            or protocol["components"] != catalog()
            or protocol["baseline_sha256"] != digest((ROOT / "controllers/reactive.py").read_bytes())):
        raise ValueError("Frozen campaign rules differ from its implementation")
    result = read(root / "result.json")
    if result["status"] != "prepared":
        raise ValueError("Use a fresh campaign directory; Python continuations cannot resume")
    # Only one host may open this attempt, even under concurrent CLI invocations.
    with (root / "started.json").open("x") as lock:
        json.dump(dict(pid=os.getpid()), lock)
    started = time.monotonic()
    result.update(status="researching", started_at=time.time())
    atomic_json(root / "result.json", result)
    session = None
    def check_stop():
        if (root / "stop-request.json").exists():
            signal.setitimer(signal.ITIMER_REAL, 0)
            request = read(root / "stop-request.json")
            if request.get("reason") == "infrastructure_failure":
                raise HostFault("Operator interrupted for diagnosis: " + request["detail"])
            raise KeyboardInterrupt("user_stop")
    def interrupt(_signal, _frame):
        signal.setitimer(signal.ITIMER_REAL, 0)
        raise KeyboardInterrupt("user_stop")
    previous_signal = signal.signal(signal.SIGTERM, interrupt)
    previous_interrupt = signal.signal(signal.SIGINT, interrupt)
    previous_alarm = signal.signal(signal.SIGALRM, lambda *_: check_stop())
    signal.setitimer(signal.ITIMER_REAL, 1, 1)
    try:
        check_stop()
        wait_until = protocol.get("recovery", {}).get("not_before", 0)
        while time.time() < wait_until:
            check_stop()
            time.sleep(max(0, min(1, wait_until - time.time())))
        client, user = clients(protocol)
        if evaluation_workers() != protocol["evaluation_workers"]:
            raise ValueError("Evaluation concurrency differs from the frozen campaign")
        manifest = load_suite(root / "suite")
        development = development_tasks(root / "suite", manifest, solo_mode=protocol.get("solo_mode", False))
        runner = Tau2Runner(root / "suite", {**manifest, "tasks": development}, client, user,
            protocol["worker_image"], Limits(**protocol["task_limits"]), root / "private/environments",
            recovery_tasks=protocol.get("recovery", {}).get("task_budgets", {}),
            solo_mode=protocol.get("solo_mode", False))
        accounting = status(root)
        session = ResearchSession(output=root / "research", development=tuple(protocol["task_ids"]), run_task=runner,
            worker_image=protocol["worker_image"], setup=dict(model=protocol["model"], user_model=protocol["user_model"],
                solo_mode=protocol.get("solo_mode", False),
                expected_researcher=protocol.get("expected_researcher"), prior_accounting=dict(
                    task_runs=accounting["cumulative_task_runs"], usage=accounting["cumulative_usage"],
                    charged_seconds=sum(row["charged_seconds"] for row in accounting["attempts"][:-1]))),
            experiment=protocol["experiment"],
            baseline_source=(ROOT / "controllers/reactive.py").read_text(), task_limits=Limits(**protocol["task_limits"]),
            check_stop=check_stop, evaluation_workers=protocol["evaluation_workers"])
        if session.jev_configuration != protocol["jev"]:
            raise ValueError("Jev configuration changed after freezing")
        recovery = protocol.get("recovery")
        if recovery:
            for attempt in reversed(sorted((root / "private/prior").glob("attempt-*"))):
                prior_session = attempt / "research"
                state_path = prior_session / "private/state.json"
                if state_path.exists() and read(state_path)["evaluations"]:
                    session.restore(prior_session)
                    break
        session.research()
        result.update(status=session.state["status"], research_status=session.state.get("research_status"))
    except KeyboardInterrupt:
        result.update(status="stopped", research_status="user_stopped")
    except BaseException as error:
        result.update(status="interrupted", error_type=type(error).__name__, error=str(error),
                      research_status=session.state.get("research_status", "host_fault") if session else "host_fault")
        raise
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGTERM, previous_signal)
        signal.signal(signal.SIGINT, previous_interrupt)
        signal.signal(signal.SIGALRM, previous_alarm)
        calls = session.meter.calls if session and hasattr(session, "meter") else []
        result.update(closed_at=time.time(), elapsed_seconds=time.monotonic() - started,
                      failure_codes=failure_codes(calls, session.state["evaluations"] if session else [],
                                                  root / "research/public"))
        atomic_json(root / "result.json", result)
        write_report(root)
    return result


def dispatch(root):
    """Run a serial frozen child; interruption waits for task and usage cleanup."""
    root = Path(root).resolve()
    load_env()
    for name in ("LOOPBLOX_CODEX_BINARY_ROOT", "LOOPBLOX_CODEX_AUTH_FILE", "LOOPBLOX_JEV_PYTHON"):
        if os.environ.get(name):
            # Keep interpreter symlinks: resolving a venv's python can drop its environment.
            os.environ[name] = str(Path(os.environ[name]).expanduser().absolute())
    process = subprocess.Popen([sys.executable, "-B", "-m", "loopblox.research.campaign", str(root)],
        cwd=root / "implementation", env={**os.environ, "PYTHONPATH": str(root / "implementation")}, start_new_session=True)
    def interrupt(_signal, _frame):
        raise KeyboardInterrupt("user_stop")
    previous_term = signal.signal(signal.SIGTERM, interrupt)
    try:
        return process.wait()
    except KeyboardInterrupt:
        old = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            try:
                os.killpg(process.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        finally:
            signal.signal(signal.SIGINT, old)
        return 130
    finally:
        signal.signal(signal.SIGTERM, previous_term)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if run(args.output)["status"] != "stopped":
        raise SystemExit(1)
