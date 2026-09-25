"""Freeze and run AppWorld evaluations or continuous Loop research on official train tasks."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import random
import shutil
import signal
import subprocess
import sys
import time

from loopblox import ROOT, snapshot_implementation
from loopblox.benchmarks.appworld import AppWorldRunner, Environment
from loopblox.research.session import ResearchSession, summarize_evaluation
from loopblox.research.failures import incident
from loopblox.runtime.components import catalog
from loopblox.runtime.controller import Limits, ModelMeter, model_usage, MAX_MODEL_RETRIES
from loopblox.runtime.io import atomic_json, atomic_text, digest, image_id
from loopblox.runtime.model import ChatCompletionsClient, load_env


PILOT_LIMITS = Limits(seconds=None, actions=None, model_calls=None, output_tokens=None)


def pilot_client(*, request_timeout=60):
    client = ChatCompletionsClient.from_env()
    client.max_tokens = None
    client.timeout = request_timeout
    client.stream = client.api == "chat_completions"
    return client


def model_settings(client):
    return {key: getattr(client, key) for key in (
        "model", "base_url", "api", "reasoning_effort", "structured_output", "temperature", "max_tokens", "timeout", "stream")}


def inventory(root):
    return {str(path.relative_to(root)): digest(path.read_bytes()) for path in sorted(root.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"}


def prepare(args):
    restart = getattr(args, "restart_from", None)
    if restart is not None:
        args.continuous = True
    if not 0 < args.request_timeout < float("inf"):
        raise ValueError("Request timeout must be positive and finite")
    if args.task_count < 1:
        raise ValueError("Task count must be positive")
    if args.continuous and not args.code_image:
        raise ValueError("Continuous AppWorld research requires the official code shell")
    output = args.output.resolve()
    if output.exists():
        raise ValueError("A pilot requires a new output directory")
    client = pilot_client(request_timeout=args.request_timeout)
    from loopblox.analysis.jev import configuration
    configuration()  # Reject missing analysis dependencies before any dispatch.
    worker_image = image_id(args.worker_image)
    code_image = image_id(args.code_image) if args.code_image else None
    previous = None
    review = None
    restart_record = None
    if restart is not None:
        restart = restart.resolve()
        prior_protocol = json.loads((restart / "protocol.json").read_text())
        if json.loads((restart / "result.json").read_text())["status"] not in {"failed", "interrupted", "stopped"}:
            raise ValueError("A fresh condition requires a closed prior experiment")
        if not args.recovery_reason:
            raise ValueError("A fresh condition requires a recorded protocol-change reason")
        if ({key: prior_protocol["model"][key] for key in model_settings(client) if key != "stream"}
                != {key: value for key, value in model_settings(client).items() if key != "stream"}
                or prior_protocol["task_limits"] != vars(PILOT_LIMITS)
                or prior_protocol["worker_image"] != worker_image or prior_protocol.get("code_image") != code_image):
            raise ValueError("Automatic condition changes retain task models, budgets and isolation images")
        args.data_root = restart / "private/appworld"
        args.appworld_venv = restart / "private/appworld-venv"
        args.seed, args.task_count = prior_protocol["seed"], len(prior_protocol["task_ids"])
        native_path = restart / "evaluation/private/researcher-configuration.json"
        restart_record = dict(directory=str(restart), reason=args.recovery_reason,
            protocol_sha256=digest((restart / "protocol.json").read_bytes()),
            expected_researcher=json.loads(native_path.read_text()) if native_path.exists() else prior_protocol.get("expected_researcher"))
    if args.review is not None:
        review_root = args.review.resolve()
        review_result = json.loads((review_root / "result.json").read_text())
        if review_result["status"] != "completed":
            raise ValueError("Candidate evaluation requires a completed research review")
        reference_run = Path(review_result["source_run"])
        reference_pilot = reference_run.parents[4]
        prior_protocol = json.loads((reference_pilot / "protocol.json").read_text())
        proposal = json.loads((review_root / "public/proposal.json").read_text())
        source = (review_root / "public/proposed-controller.py").read_text()
        if not source.strip() or source != proposal["source"]:
            raise ValueError("Proposed source differs from the research submission")
        compile(source, "proposed-controller.py", "exec")
        if json.loads((review_root / "public/components.json").read_text()) != catalog():
            raise ValueError("The reviewed component contracts changed")
        reference_model = dict(prior_protocol["model"])
        if args.provider is not None:
            # An explicit provider revision permits its model and wire protocol;
            # reasoning effort, temperature and budgets still match the reference.
            for key in ("model", "base_url", "api", "structured_output"):
                reference_model[key] = getattr(client, key)
        reference_model["timeout"] = args.request_timeout
        # This authorized transport revision preserves every other frozen setting.
        reference_model["stream"] = client.stream
        if (reference_model != model_settings(client)
                or prior_protocol["task_limits"] != vars(PILOT_LIMITS)
                or prior_protocol["worker_image"] != worker_image):
            raise ValueError("Retain the reference task's model, budgets and worker image")
        reference_result = json.loads((reference_run / "result.json").read_text())
        if reference_result["status"] != "completed" or reference_result["verification_verdict"] not in {"pass", "fail"}:
            raise ValueError("The reference task must have a complete official score")
        review = dict(directory=str(review_root), source_run=str(reference_run),
                      task_id=reference_result["task_id"], source_sha256=digest(source.encode()),
                      model_changes={key: dict(before=prior_protocol["model"].get(key, False if key == "stream" else None), after=value)
                                     for key, value in model_settings(client).items()
                                     if prior_protocol["model"].get(key, False if key == "stream" else None) != value})
        args.data_root = reference_pilot / "private/appworld"
        args.appworld_venv = reference_pilot / "private/appworld-venv"
        args.seed = prior_protocol["seed"]
    if args.previous is not None:
        previous = args.previous.resolve()
        state = json.loads((previous / "result.json").read_text())
        if state["status"] not in {"failed", "interrupted"}:
            raise ValueError("Recovery requires a closed unsuccessful pilot")
        prior_protocol = json.loads((previous / "protocol.json").read_text())
        if prior_protocol.get("continuous"):
            if not args.recovery_reason:
                raise ValueError("Continuous recovery requires a recorded diagnosis or repair reason")
            if (prior_protocol["model"] != model_settings(client)
                    or prior_protocol.get("gateway_max_retries") != MAX_MODEL_RETRIES
                    or prior_protocol["task_limits"] != vars(PILOT_LIMITS)
                    or prior_protocol["worker_image"] != worker_image
                    or prior_protocol.get("code_image") != code_image):
                raise ValueError("Recovery must retain model settings, uncapped task limits and images")
            old_catalog = previous / "evaluation/public/components.json"
            same_catalog = (json.loads(old_catalog.read_text()) == catalog() if old_catalog.exists() else
                (previous / "private/implementation/loopblox/runtime/components.py").read_bytes()
                == (ROOT / "loopblox/runtime/components.py").read_bytes())
            if (not same_catalog or (previous / "private/implementation/controllers/reactive.py").read_text()
                    != (ROOT / "controllers/reactive.py").read_text()):
                raise ValueError("Recovery must retain component contracts and the baseline")
            args.continuous = True
            args.task_count = len(prior_protocol["task_ids"])
        args.data_root = previous / "private/appworld"
        args.appworld_venv = previous / "private/appworld-venv"
        args.seed = prior_protocol["seed"]
    split_path = args.data_root / "data/datasets/train.txt"
    train = [line.split(":")[0].strip() for line in split_path.read_text().splitlines() if line.strip()]
    groups = {}
    for task_id in train:
        groups.setdefault(task_id.split("_")[0], []).append(task_id)
    randomizer = random.Random(args.seed)
    families = sorted(groups)
    randomizer.shuffle(families)
    selected = ([review["task_id"]] if review else
                [randomizer.choice(groups[family]) for family in families[:args.task_count]])
    if (previous is not None or restart is not None) and selected != prior_protocol["task_ids"]:
        raise ValueError("Recovery must retain the original task selection")
    if len(selected) != (1 if review else args.task_count) or any(task not in train for task in selected):
        raise ValueError("Expected the authorized task count and official train membership")
    private = output / "private"
    private.mkdir(parents=True)
    if review:
        shutil.copytree(reference_run, private / "reference-run")
        batch = json.loads((reference_run.parent / "result.json").read_text())
        reference_row = next(row for row in batch["runs"] if row["directory"] == reference_run.name)
        atomic_json(private / "reference-row.json", reference_row)
        atomic_json(private / "review-proposal.json", proposal)
        atomic_text(private / "candidate.py", source)
    prior_attempt = None
    if previous is not None:
        rows = [row for path in sorted((previous / "evaluation/public/evaluations").glob("*/result.json"))
                for row in json.loads(path.read_text())["runs"]]
        if not args.continuous and any(row.get("verification_verdict") in {"pass", "fail"} for row in rows):
            raise ValueError("This recovery path is for a pilot with no scored tasks; preserve scored tasks separately")
        prior_usage = state.get("cumulative_usage", state.get("usage", model_usage([])))
        if prior_usage is None:
            prior_usage = dict.fromkeys(model_usage([]))
        prior_attempt = dict(directory=str(previous), protocol_sha256=digest((previous / "protocol.json").read_bytes()),
            reason=args.recovery_reason,
            model_changes={key: dict(before=prior_protocol["model"].get(key, False if key == "stream" else None), after=value)
                           for key, value in model_settings(client).items()
                           if prior_protocol["model"].get(key, False if key == "stream" else None) != value},
            usage=prior_usage,
            tasks=[{key: row.get(key) for key in ("task_id", "status", "usage", "actions", "budget_seconds")}
                   for row in rows if row["status"] != "not_started"])
        for source, target in (("evaluation", "prior-evaluation"), ("private/runs", "prior-runs")):
            if (previous / source).is_dir():
                shutil.copytree(previous / source, private / target)
        if args.continuous:
            evaluation_private = previous / "evaluation/private"
            prior_state = (json.loads((evaluation_private / "state.json").read_text())
                           if (evaluation_private / "state.json").exists() else {})
            prior_setup = (json.loads((evaluation_private / "setup.json").read_text())
                           if (evaluation_private / "setup.json").exists() else {})
            prior_attempt["accounting"] = dict(usage=prior_attempt["usage"],
                task_runs=prior_state.get("task_runs_used", 0) + prior_setup.get("prior_accounting", {}).get("task_runs", 0),
                charged_seconds=state.get("cumulative_charged_seconds"))
            native_config = evaluation_private / "researcher-configuration.json"
            prior_attempt["expected_researcher"] = (json.loads(native_config.read_text()) if native_config.exists()
                                                    else prior_protocol.get("expected_researcher"))
            ledger_path = evaluation_private / "research-usage.json"
            ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else dict(calls=[])
            if any(call.get("failure_code") == "service_not_ready" for call in ledger["calls"]):
                prior_attempt["not_before"] = state.get("closed_at", (previous / "result.json").stat().st_mtime) + 14 * 60
        atomic_json(private / "prior-attempt.json", prior_attempt)
    world_root = private / "appworld"
    data = world_root / "data"
    data.mkdir(parents=True)
    for name in ("base_dbs", "api_docs"):
        shutil.copytree(args.data_root / "data" / name, data / name)
    for name in ("version.txt", "LICENSE", "README_BEFORE_SHARING.md"):
        shutil.copyfile(args.data_root / "data" / name, data / name)
    (data / "datasets").mkdir()
    shutil.copyfile(split_path, data / "datasets/train.txt")
    for task_id in selected:
        shutil.copytree(args.data_root / "data/tasks" / task_id, data / "tasks" / task_id)
    venv = private / "appworld-venv"
    shutil.copytree(args.appworld_venv, venv, symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    python = venv / "bin/python"
    result = subprocess.run([str(python), "-c", "import sys,json,importlib.metadata as m; "
        "print(json.dumps(dict(python=sys.version,packages={d.metadata['Name']:d.version for d in m.distributions()})))"],
        check=True, capture_output=True, text=True, timeout=30)
    versions = json.loads(result.stdout)
    if versions["packages"].get("appworld") != "0.1.3.post1":
        raise ValueError("This pilot pins AppWorld 0.1.3.post1")
    manifest = dict(versions=versions, data=inventory(data), environment=inventory(venv))
    if (previous is not None or restart is not None) and args.continuous:
        if manifest != json.loads(((previous or restart) / "private/environment-manifest.json").read_text()):
            raise ValueError("Recovery must retain the frozen AppWorld data and dependencies")
    atomic_json(private / "environment-manifest.json", manifest)
    if code_image:
        manifest_code = ("import json,inspect,hashlib,importlib.metadata as m; "
            "from appworld.environment import AppWorld; "
            "print(json.dumps(dict(packages={d.metadata['Name']:d.version for d in m.distributions()}, "
            "execute_sha256=hashlib.sha256(inspect.getsource(AppWorld.execute).encode()).hexdigest(), "
            "shell_run_cell_sha256=hashlib.sha256(inspect.getsource(AppWorld._shell_run_cell).encode()).hexdigest())))")
        shell_manifest = json.loads(subprocess.run(["docker", "run", "--rm", "--network", "none",
            code_image, "python", "-B", "-c", manifest_code],
            check=True, capture_output=True, text=True, timeout=60).stdout)
        host_manifest = json.loads(subprocess.run([str(python), "-B", "-c", manifest_code],
            check=True, capture_output=True, text=True, timeout=30).stdout)
        if (shell_manifest["packages"].get("appworld") != "0.1.3.post1" or
                any(shell_manifest[key] != host_manifest[key]
                    for key in ("execute_sha256", "shell_run_cell_sha256"))):
            raise ValueError("The code image must retain the pinned official execution methods")
        atomic_json(private / "code-environment-manifest.json", dict(image=code_image, **shell_manifest))
    protocol = dict(benchmark="AppWorld", version="0.1.3.post1", split="train", task_ids=selected,
        selection=("Only the completed task supplied to the research review; baseline evidence is reused."
                   if review else "Seeded shuffle of sorted official train scenario IDs; one randomly chosen variant per scenario."),
        seed=args.seed, worker_image=worker_image, task_limits=vars(PILOT_LIMITS),
        model=model_settings(client), user_model=None, evaluation_workers=1,
        code_image=code_image, continuous=args.continuous,
        failure_routing="researcher_after_batch_or_isolated_infra_repair; human_for_budget_access_or_authority",
        gateway_max_retries=MAX_MODEL_RETRIES,
        restart_from=restart_record,
        prior_attempt=prior_attempt,
        prior_accounting=(prior_attempt or {}).get("accounting", {}),
        expected_researcher=(prior_attempt or restart_record or {}).get("expected_researcher"),
        review=review,
        revision="User authorized no task/action/model/output budget caps and no client-request output cap "
                 "to measure actual usage. "
                 + (f"User authorized streaming Chat Completions with a {client.timeout:g}-second generation-inactivity deadline. "
                    "Only text, reasoning and tool-function deltas renew it; heartbeats do not. "
                    if client.stream else
                    f"Task-model requests have a {client.timeout:g}-second socket and whole-request deadline. ")
                 + f"Recognized no-effect transient failures permit at most {MAX_MODEL_RETRIES} exact retries while budgets permit. "
                 + "Provider constraints remain. "
                 "Prior attempts retain their costs; infinite remaining budgets need no subtraction. "
                 + (f"User explicitly selected provider {args.provider}; model settings are frozen above. "
                    if args.provider is not None else ""),
        interaction_mode=("Official AppWorld.execute code shell in an isolated container; public API effects "
                          "and official evaluation remain on the host. One action is one code block. "
                          "Native 100-second code-execution and 1000-API-call block guards remain; "
                          "task and output budgets stay uncapped; model transport has its separately frozen deadline."
                          if code_image else
                          "One public API call per action; dynamic API documentation discovery; no code tool."),
        purpose=("Continuous research on this fixed official train set, starting from a fresh reactive baseline. "
                 "No imported candidates, notes or results; no iteration or shared budget cap; user owns stopping."
                 if args.continuous else
                 "One authorized evaluation of the reviewed candidate on its source training task; "
                 "fresh state, retained reference evidence, no other task dispatch." if review else
                 "Baseline-only integration and capability pilot; no researcher, search, or official test evaluation."),
        official_split_sha256=digest(split_path.read_bytes()),
        prior_exposure="The operator previously inspected first-task trials, the first two baseline tasks and "
                       "a stalled third-task trace under OpenCode. No uncontaminated task-selection claim is made. "
                       "Fresh continuous research imports none of those candidates, results or notes. "
                       "No prior evidence is supplied to the task agent. Previous pilot attempts, when present, "
                       "are retained privately for accounting. Integration preflight inspected "
                       "the public instruction and public helper API documentation of train task 82e2fac_1; "
                       "no model run, solution, or evaluator answer was used.")
    atomic_json(output / "protocol.json", protocol)
    atomic_json(private / "implementation-manifest.json", snapshot_implementation(private))
    atomic_json(output / "result.json", dict(status="prepared", task_ids=selected))
    return output


def run(output):
    protocol = json.loads((output / "protocol.json").read_text())
    private = output / "private"
    world_root, python = private / "appworld", private / "appworld-venv/bin/python"
    frozen = json.loads((private / "environment-manifest.json").read_text())
    if inventory(world_root / "data") != frozen["data"] or inventory(private / "appworld-venv") != frozen["environment"]:
        raise ValueError("Frozen AppWorld environment changed")
    client = pilot_client(request_timeout=protocol["model"]["timeout"])
    if model_settings(client) != protocol["model"]:
        raise ValueError("Frozen model settings changed")
    if json.loads((output / "result.json").read_text())["status"] != "prepared":
        raise ValueError("A frozen pilot may only be dispatched once")
    limits = Limits(**protocol["task_limits"])
    session = None
    def interrupt(_signal, _frame):
        raise KeyboardInterrupt("user_stop")
    previous_term = signal.signal(signal.SIGTERM, interrupt)
    previous_int = signal.signal(signal.SIGINT, interrupt)
    with (output / "started.json").open("x") as lock:
        json.dump(dict(pid=os.getpid()), lock)
    result = dict(status="auditing", task_ids=protocol["task_ids"])
    atomic_json(output / "result.json", result)
    try:
        not_before = (protocol.get("prior_attempt") or {}).get("not_before", 0)
        while time.time() < not_before:
            time.sleep(min(1, not_before - time.time()))
        audits = []
        for task_id in protocol["task_ids"]:
            audit = private / "audit" / task_id
            environment = Environment(python=python, root=world_root, task_id=task_id,
                experiment_name="audit-" + task_id, seed=protocol["seed"], private=audit)
            try:
                score = environment.request(dict(operation="evaluate", private_result=str(audit / "verification.json")), 120)
                if score["success"] or score["total"] == 0 or score["passed"] + score["failed"] != score["total"]:
                    raise ValueError("Empty-trajectory official evaluation must fail with complete checks: " + task_id)
                audits.append(dict(task_id=task_id, **score))
                atomic_json(private / "audit.json", dict(tasks=audits))
                print(json.dumps(dict(stage="audited", task_id=task_id)), flush=True)
            finally:
                environment.close()
        runner = AppWorldRunner(root=world_root, python=python, client=client,
            worker_image=protocol["worker_image"], limits=limits, private=private / "runs", seed=protocol["seed"],
            code_image=protocol.get("code_image"))
        review = protocol.get("review")
        baseline = (private / "reference-run/controller.py" if review else ROOT / "controllers/reactive.py").read_text()
        session = ResearchSession(output=output / "evaluation", development=tuple(protocol["task_ids"]),
            run_task=runner, worker_image=protocol["worker_image"], setup=protocol,
            experiment=dict(question=("Improve complete-task success and execution cost by composing approved "
                "components into reusable Python Loops on the frozen AppWorld official training tasks. "
                "Continue researching and checkpointing until the user stops."
                if protocol.get("continuous") else "Evaluate the frozen Loop on the authorized AppWorld official "
                "training tasks using public APIs and the official evaluator. No automatic candidate search."),
                exposed={name: {} for name in catalog()}),
            baseline_source=baseline, task_limits=limits, evaluation_workers=1)
        if protocol.get("continuous"):
            if (private / "prior-evaluation/private/state.json").is_file():
                session.restore(private / "prior-evaluation")
            result["status"] = "researching"
            atomic_json(output / "result.json", result)
            session.research()
            result.update(status=session.state["status"], research_status=session.state.get("research_status"))
            if session.state["status"] == "budget_exhausted":
                result["incident"] = dict(route="human", action="supply_budget_or_access",
                    stage="researcher", code="research_budget_exhausted", detail=session.state.get("stop_reason"))
            return result
        # Preserve the bounded pilot's guide instead of the continuous protocol.
        atomic_text(session.public / "experiment.md", (ROOT / "docs/appworld.md").read_text())
        session.meter = ModelMeter(session.private / "research-usage.json", **session.budgets)
        session.state["status"] = "evaluating"
        session.save()
        candidate_id = session.baseline_candidate
        if review:
            source = (private / "candidate.py").read_text()
            if digest(source.encode()) != review["source_sha256"]:
                raise ValueError("Frozen proposed source changed")
            semantic = json.loads((private / "reference-run/jev.json").read_text())
            if semantic["status"] != "completed" or semantic["configuration"] != session.jev_configuration:
                raise ValueError("Reference Jev analysis must be complete under the same configuration")
            reference = session.public / "evaluations/e0000"
            reference.mkdir()
            shutil.copytree(private / "reference-run", reference / "run-0000")
            atomic_text(reference / "sources/c0000.py", baseline)
            row = json.loads((private / "reference-row.json").read_text())
            row.update(candidate_id="c0000", directory="run-0000", draw=0, repeat=0)
            batch = dict(evaluation_id="e0000", candidate_ids=["c0000"],
                sources={"c0000": dict(path="sources/c0000.py", sha256=digest(baseline.encode()))},
                sampled_tasks=protocol["task_ids"], repeats=1, requested_runs=1, status="completed",
                feedback_ready=True, runs=[row], imported_from=review["source_run"],
                note="Derived one-task reference view; no baseline rerun or new baseline spend.")
            batch["summary"] = summarize_evaluation(batch)
            atomic_json(reference / "result.json", batch)
            session.state["evaluations"].append(batch)
            session.update_selection()
            proposal = json.loads((private / "review-proposal.json").read_text())
            candidate_id = session.save_candidate(dict(source=source, rationale=proposal["rationale"]), 0)["candidate_id"]
            if candidate_id == session.baseline_candidate:
                raise ValueError("The proposed Loop is identical to the already evaluated baseline")
            result["reference"] = dict(source_run=review["source_run"], verdict=row["verification_verdict"],
                                       usage=row["usage"], imported=True)
        result["status"] = "running"
        result["candidate_id"] = candidate_id
        atomic_json(output / "result.json", result)
        feedback = session.evaluate(dict(candidate_ids=[candidate_id]), 0)
        session.state["status"] = "completed"
        result.update(status="completed", feedback=feedback)
    except KeyboardInterrupt:
        result.update(status="stopped", research_status="user_stopped")
        if session is not None:
            session.state.update(status="stopped", research_status="user_stopped")
    except BaseException as error:
        result.update(status="interrupted" if not isinstance(error, Exception) else "failed",
                      error=type(error).__name__ + ": " + str(error))
        if session is not None:
            session.state["status"] = result["status"]
        result["incident"] = (session.state.get("incident") if session is not None else None) or incident(
            error, stage="researcher" if session is not None else "initialization")
        raise
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)
        if session is not None:
            session.save()
        meter = getattr(session, "meter", None)
        result["usage"] = meter.summary() if meter is not None else model_usage([])
        prior = (protocol.get("prior_attempt") or {}).get("usage")
        result["charged_seconds"] = (max(0, time.monotonic() - meter.started - meter.timeout_wait_seconds)
                                     if meter is not None else 0)
        prior_seconds = protocol.get("prior_accounting", {}).get("charged_seconds", 0)
        result["cumulative_charged_seconds"] = (None if prior_seconds is None else
            prior_seconds + result["charged_seconds"])
        result["cumulative_usage"] = {key: (None if value is None or (prior and prior.get(key) is None)
            else value + (prior.get(key, 0) if prior else 0)) for key, value in result["usage"].items()}
        result["closed_at"] = time.time()
        atomic_json(output / "result.json", result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--previous", type=Path, help="Recover a failed continuous run, or a pilot with no scored tasks")
    mode.add_argument("--restart-from", type=Path, help="Start a fresh condition on the same tasks; import no research evidence")
    parser.add_argument("--recovery-reason", help="Diagnosis or repair recorded for continuous recovery")
    mode.add_argument("--review", type=Path, help="Evaluate the exact reviewed proposal once on its source task")
    mode.add_argument("--continuous", action="store_true", help="Run the baseline and continuous research until stopped")
    parser.add_argument("--task-count", type=int, default=10, help="Number of distinct official train scenarios")
    parser.add_argument("--seed", type=int, default=20260922)
    parser.add_argument("--data-root", type=Path, default=ROOT / ".artifacts/upstream/appworld-data")
    parser.add_argument("--appworld-venv", type=Path, default=ROOT / ".artifacts/upstream/appworld-venv")
    parser.add_argument("--worker-image", default="python:3.12-slim")
    parser.add_argument("--code-image", help="Explicit interaction revision: use the isolated official AppWorld code shell")
    parser.add_argument("--request-timeout", type=float, default=60,
                        help="Task-model generation-inactivity timeout for streaming Chat Completions; "
                             "whole-request deadline for Responses (default: 60 seconds)")
    parser.add_argument("--provider", choices=("freeinference", "opencode_go"),
                        help="Explicit protocol revision: select the task-model provider")
    parser.add_argument("--frozen", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--attempt", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.provider is not None:
        os.environ["LOOPBLOX_PROVIDER"] = args.provider
    if args.frozen:
        if args.continuous:
            from loopblox.research.infra import supervise
            supervise(args.output.resolve())
        else:
            run(args.output.resolve())
    else:
        output = prepare(args)
        implementation = output / "private/implementation"
        load_env()
        for name in ("LOOPBLOX_CODEX_BINARY_ROOT", "LOOPBLOX_CODEX_AUTH_FILE", "LOOPBLOX_JEV_PYTHON"):
            if os.environ.get(name):
                os.environ[name] = str(Path(os.environ[name]).expanduser().absolute())
        environment = {**os.environ, "PYTHONPATH": str(implementation), "PYTHONDONTWRITEBYTECODE": "1"}
        # Freeze the supervisor too. Recovered attempts do not create nested supervisors.
        supervision = ["--continuous"] if args.continuous and not args.attempt else []
        os.chdir(implementation)
        os.execve(sys.executable, [sys.executable, "-B", "-m", "loopblox.benchmarks.run_appworld",
            "--output", str(output), "--frozen", *supervision], environment)


if __name__ == "__main__":
    main()
