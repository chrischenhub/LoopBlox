"""An isolated native repair worker and serial supervisor for AppWorld research.

Repairs create a new implementation; they never write the checkout, candidate
sources, previous attempts, task data, evaluator or component contracts.
"""
from __future__ import annotations

import ast
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from loopblox.research.codex import default_researcher, native_usage
from loopblox.research.workspace import ResearchWorkspace
from loopblox.research.failures import incident, fingerprint
from loopblox.runtime.controller import ModelMeter
from loopblox.runtime.io import atomic_json, atomic_text, digest
from loopblox.runtime.model import HostFault, _TRANSIENT_CODES

# This is the repair authority, not a suggestion that a model can broaden.
EDITABLE = {
    "loopblox/runtime/model.py": ("ChatCompletionsClient._request", "_ChatStream.observe", "_ChatStream.complete"),
    "loopblox/runtime/io.py": ("run_process", "wait_seconds"),
    "loopblox/runtime/jev.py": ("sdk_process", "complete", "main"),
    "loopblox/analysis/jev.py": ("analyze_run",),
    "loopblox/analysis/segments.py": ("turns", "_unwrap", "_user_messages"),
    "loopblox/benchmarks/appworld_code.py": ("CodeEnvironment.receive", "CodeEnvironment.execute", "CodeEnvironment.close"),
}
# Every other allowed edit may change model-visible evidence or execution policy.
# Uncertainty creates a fresh condition; the proposing agent cannot waive this rule.
PRESERVES_CONDITION = {"loopblox/benchmarks/appworld_code.py": ("CodeEnvironment.close",)}
TRANSIENT = _TRANSIENT_CODES | {"service_not_ready"}
INSTRUCTIONS = (
    "You are the infrastructure repair worker, not the Loop researcher. Read /exchange/task.json "
    "and /evidence/incident.json. Inspect source and public evidence under /evidence. "
    "Propose the smallest repair within editable_functions, with an executable Python regression "
    "check that reproduces the reported fault or verifies its repaired behavior without network, "
    "model calls, task execution or private evaluator data. Use /work for analysis. "
    "Keep all original evidence, usage, errors and missing measurements. Never weaken isolation, "
    "scoring, component contracts, frozen models/budgets or measurement questions. No truncating "
    "or inventing evidence. Do not optimize or modify candidates. Human escalation is only for "
    "missing budget, access, permissions or an explicitly required authority outside this repair scope; "
    "difficulty or an unsuccessful fix is not an escalation reason. "
    "You may repair evidence representation and segmentation within editable_functions. The host "
    "starts a fresh baseline and researcher whenever a repair may change inputs, outputs or protocol; "
    "only host-approved cleanup edits preserve an existing condition. Never claim unchanged measurement "
    "semantics merely because evidence can be reconstructed. Consult recovery-history.json for recurring "
    "faults and prior checked repairs: a passed check is not proof that the fault is resolved. "
    "Return exactly one JSON object with action ('repair', 'retry', or 'human'), reason, "
    "files (map of relative source path to complete replacement text), check (Python source), "
    "and required_action (empty except for human escalation). Retry without changes is only "
    "available for the host-listed transient codes on their first occurrence, after the enforced cooldown; never retry "
    "a deterministic fault unchanged. Prior rejected proposals and validation feedback are in "
    "/exchange/receipts. Return a revised repair when a check fails."
)


def _protected(source, allowed):
    tree = ast.parse(source)
    def visit(nodes, prefix=""):
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and prefix + node.name in allowed:
                # Signature, decorators and every other definition remain protected.
                node.body = [ast.Pass()]
            elif isinstance(node, ast.ClassDef):
                visit(node.body, prefix + node.name + ".")
    visit(tree.body)
    return ast.dump(tree, include_attributes=False)


def apply_repair(original, destination, files):
    if not isinstance(files, dict) or not files:
        raise ValueError("A repair requires changed source files")
    changed = {}
    for name, source in files.items():
        if name not in EDITABLE or not isinstance(source, str):
            raise ValueError("Outside infrastructure repair scope: " + str(name))
        before = (original / name).read_text()
        compile(source, name, "exec")
        if _protected(before, EDITABLE[name]) != _protected(source, EDITABLE[name]):
            raise ValueError("Protected definitions or function signatures changed: " + name)
        if ast.dump(ast.parse(before)) != ast.dump(ast.parse(source)):
            changed[name] = dict(before=digest(before.encode()), after=digest(source.encode()),
                preserves_condition=_protected(before, PRESERVES_CONDITION.get(name, ())) ==
                                    _protected(source, PRESERVES_CONDITION.get(name, ())))
    if not changed:
        raise ValueError("An unchanged deterministic failure is not a repair")
    shutil.copytree(original, destination)
    for name, source in files.items():
        atomic_text(destination / name, source)
    return changed


def repair(attempt, destination, *, history, failure=None, implementation=None):
    """Return a checked repair or resource escalation. No experiment dispatch here."""
    protocol = json.loads((attempt / "protocol.json").read_text())
    result = json.loads((attempt / "result.json").read_text())
    failure = failure or result["incident"]
    public, private = destination / "public", destination / "private"
    public.mkdir(parents=True); private.mkdir()
    original = Path(implementation) if implementation is not None else attempt / "private/implementation"
    shutil.copytree(original, public / "source")
    if (attempt / "evaluation/public").is_dir():
        shutil.copytree(attempt / "evaluation/public", public / "evidence")
    native_record = attempt / "evaluation/private/research-trace.json"
    if native_record.is_file():
        native_result = json.loads(native_record.read_text())
        atomic_json(public / "native-diagnostic.json", dict(
            **{key: native_result.get(key) for key in ("status", "error", "incident", "native_usage")},
            failures=[call["failure"] for call in native_result.get("calls", []) if call.get("failure")]))
    atomic_json(public / "incident.json", failure)
    atomic_json(public / "recovery-history.json", history)
    frozen_native = attempt / "evaluation/private/researcher-configuration.json"
    expected = json.loads(frozen_native.read_text()) if frozen_native.is_file() else protocol.get("expected_researcher")
    atomic_json(private / "setup.json", dict(role="infra", expected_researcher=expected))
    workspace = ResearchWorkspace(public, private, protocol["worker_image"])
    meter = ModelMeter(private / "usage.json", seconds=None, model_calls=None, output_tokens=None)
    native = default_researcher(public_root=public, scratch_path=workspace.scratch,
        private=private, container_image=protocol["worker_image"], meter=meter)
    exchange = private / "exchange"
    (exchange / "receipts").mkdir(parents=True)
    fault_id = fingerprint(failure)
    previous_faults = [item for item in history if item.get("fingerprint") == fault_id]
    atomic_json(exchange / "task.json", dict(role="infra", editable_functions=EDITABLE,
        preserves_condition=PRESERVES_CONDITION, fingerprint=fault_id, prior_occurrences=len(previous_faults),
        incident=failure, retry_codes=sorted(TRANSIENT), instruction=INSTRUCTIONS))
    record = dict(status="repairing", role="infra", source_attempt=str(attempt), fingerprint=fault_id, calls=[])
    try:
        with tempfile.TemporaryDirectory(prefix="loopblox-infra-codex-") as temporary:
            home = Path(temporary)
            shutil.copyfile(native.auth_path, home / "auth.json")
            (home / "auth.json").chmod(0o600)
            atomic_text(home / "config.toml", native._config_text())
            while True:
                identifier = f"call-{len(record['calls']) + 1:06d}"
                invocation = private / identifier
                invocation.mkdir()
                # Independent diagnostic invocations have independent token totals.
                call = native._invoke(exchange, invocation, math.inf, protocol["worker_image"], home,
                                      instructions=INSTRUCTIONS)
                record["calls"].append(call)
                record["native_usage"] = native_usage(record["calls"])
                atomic_json(destination / "result.json", record)
                if call["exit_code"] or call["failure"]:
                    atomic_json(exchange / "receipts" / (identifier + ".json"), dict(native_failure=call["failure"],
                        exit_code=call["exit_code"]))
                    fault = incident(HostFault("Infra worker invocation failed", response=call["failure"]), stage="infra_worker")
                    if fault["route"] == "human":
                        record.update(status="blocked", action="human", incident=fault,
                            reason="Native repair worker lacks budget or access",
                            required_action="Restore the native Codex subscription quota or login identified in the recorded failure")
                        return record
                    if (fault.get("code") not in TRANSIENT and len(record["calls"]) > 1
                            and record["calls"][-2].get("failure") == call["failure"]):
                        record.update(status="blocked", action="human", incident=fault,
                            reason="The isolated infra worker cannot complete a diagnostic",
                            required_action="Restore the native repair-worker runtime or authorize a repair outside its scope; see retained invocation failures")
                        return record
                    # A disconnected native invocation is an infra fault, not a task outcome.
                    # Retain it and give the next fresh invocation its diagnostic after cooldown.
                    time.sleep(30)
                    continue
                try:
                    proposal = json.loads((invocation / "output/request.json").read_text())
                    if set(proposal) != {"action", "reason", "files", "check", "required_action"}:
                        raise ValueError("Expected action, reason, files, check and required_action")
                    if not isinstance(proposal["reason"], str) or not proposal["reason"].strip():
                        raise ValueError("A concrete diagnosis is required")
                    if proposal["action"] == "human":
                        if not isinstance(proposal["required_action"], str) or not proposal["required_action"].strip():
                            raise ValueError("Identify the missing resource or permission the human must supply")
                        record.update(status="blocked", **proposal)
                        return record
                    if proposal["action"] == "retry":
                        if failure.get("code") not in TRANSIENT or proposal["files"] or previous_faults:
                            raise ValueError("Unchanged retry is restricted to the first occurrence of a transient fault; recurring faults require a new repair")
                        record.update(status="ready", **proposal)
                        return record
                    if proposal["action"] != "repair" or not isinstance(proposal["check"], str) or not proposal["check"].strip():
                        raise ValueError("A source repair requires an executable focused check")
                    repaired = public / identifier
                    changes = apply_repair(original, repaired, proposal["files"])
                    repaired_hashes = {key: value["after"] for key, value in changes.items()}
                    if any(repaired_hashes == {key: value["after"] for key, value in item.get("changes", {}).items()}
                           for item in previous_faults):
                        raise ValueError("This checked repair already preceded recurrence of the same fault; investigate and revise it")
                    atomic_text(repaired / "infra-check.py", proposal["check"])
                    checked = workspace.run(dict(command=f"cd /evidence/{identifier} && PYTHONPATH=. python -B infra-check.py"), None)
                    if checked.status != "ok":
                        raise ValueError("Repair check failed: " + json.dumps(checked.result_or_error))
                    record.update(status="ready", action="repair", reason=proposal["reason"],
                                  next_run="recover" if all(change["preserves_condition"] for change in changes.values()) else "restart",
                                  implementation=str(repaired), changes=changes, validation=checked.result_or_error)
                    return record
                except (ValueError, SyntaxError, TypeError, KeyError, FileNotFoundError) as error:
                    atomic_json(exchange / "receipts" / (identifier + ".json"), dict(error=str(error)))
    except BaseException as error:
        record.update(status="interrupted" if not isinstance(error, Exception) else "failed", error=str(error))
        raise
    finally:
        record["native_usage"] = native_usage(record["calls"])
        atomic_json(destination / "result.json", record)


def supervise(output):
    """Close each frozen child before repairing and opening a fresh attempt."""
    output = output.resolve()
    control = output.with_name(output.name + "-supervision")
    control.mkdir()
    state = dict(status="running", attempt=str(output), supervisor_pid=os.getpid(), started_at=time.time(), attempts=[], repairs=[])
    source_attempt = output
    restart_required = False
    process = None
    def interrupt(_signum, _frame):
        raise KeyboardInterrupt("user_stop")
    previous = signal.signal(signal.SIGTERM, interrupt)
    try:
        command = [sys.executable, "-B", "-m", "loopblox.benchmarks.run_appworld", "--output", str(output), "--frozen"]
        implementation = output / "private/implementation"
        while True:
            state.update(status="running", attempt=str(output))
            atomic_json(control / "state.json", state)
            with (control / f"attempt-{len(state['attempts']):04d}.log").open("wb") as log:
                process = subprocess.Popen(command, cwd=implementation,
                    env={**os.environ, "PYTHONPATH": str(implementation)}, stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=True)
                state["pid"] = process.pid
                atomic_json(control / "state.json", state)
                exit_code = process.wait()
            process = None
            result_path = output / "result.json"
            result = json.loads(result_path.read_text()) if result_path.exists() else dict(status="preparation_failed")
            state["attempts"].append(dict(directory=str(output), status=result["status"], exit_code=exit_code,
                closed_at=result.get("closed_at"), usage=result.get("usage"), charged_seconds=result.get("charged_seconds")))
            if result["status"] in {"stopped", "completed"}:
                state["status"] = result["status"]
                break
            failure = result.get("incident")
            if (failure or {}).get("route") == "human" or result["status"] == "budget_exhausted":
                state.update(status="blocked", incident=failure)
                break
            diagnostic_attempt = output if (output / "private/implementation").is_dir() and (output / "protocol.json").is_file() else source_attempt
            if failure and result["status"] in {"failed", "interrupted"}:
                # A recovery that fails before restoring the session cannot replace
                # the last source of completed batches and cumulative task spend.
                if (output / "evaluation/private/state.json").is_file():
                    source_attempt = output
                    restart_required = False
            else:
                # Preparation may fail before opening an episode. Diagnose it against the
                # last frozen source, without treating an unfinished directory as a recovery source.
                failure = incident(RuntimeError(log.name + ": " + Path(log.name).read_text()[-6000:]), stage="preparation")
            state["status"] = "repairing"
            atomic_json(control / "state.json", state)
            while True:
                repair_directory = control / f"repair-{len(state['repairs']):04d}"
                try:
                    outcome = repair(diagnostic_attempt, repair_directory, history=state["repairs"], failure=failure,
                        implementation=output / "private/implementation" if (output / "private/implementation").is_dir() else implementation)
                except Exception as error:
                    fault = incident(error, stage="infra_worker")
                    atomic_json(repair_directory / "bootstrap-failure.json", fault)
                    state["repairs"].append(dict(directory=str(repair_directory), incident=fault))
                    atomic_json(control / "state.json", state)
                    if fault["route"] == "human":
                        outcome = dict(action="human", required_action=fault["detail"])
                        break
                    if fault.get("code") not in TRANSIENT:
                        # The diagnostic runtime is outside its own editable function scope.
                        # Do not loop forever restarting an unchanged, unavailable worker.
                        outcome = dict(action="human", required_action=
                            "Restore the infra-worker runtime or authorize repair outside its scope: " + fault["detail"])
                        break
                    # The failed diagnostic is retained for the next fresh worker; no task is replayed.
                    time.sleep(60)
                    continue
                state["repairs"].append(dict(directory=str(repair_directory), action=outcome.get("action"),
                    fingerprint=fingerprint(failure), incident=failure, reason=outcome.get("reason"),
                    changes=outcome.get("changes", {}), validation=outcome.get("validation"), next_run=outcome.get("next_run")))
                atomic_json(control / "state.json", state)
                break
            if outcome["action"] == "human":
                state.update(status="blocked", required_action=outcome["required_action"])
                break
            protocol = json.loads((source_attempt / "protocol.json").read_text())
            implementation = Path(outcome.get("implementation", str(diagnostic_attempt / "private/implementation")))
            restart_required = restart_required or outcome.get("next_run") == "restart"
            cooldown = 14 * 60 if failure.get("code") == "service_not_ready" else 60 if outcome["action"] == "retry" else 0
            until = result.get("closed_at", time.time()) + cooldown
            while time.time() < until:
                time.sleep(max(0, min(1, until - time.time())))
            old = source_attempt
            output = control / f"attempt-{len(state['attempts']):04d}"
            old_result = json.loads((old / "result.json").read_text())
            continuation = (["--restart-from", str(old), "--recovery-reason", outcome["reason"]] if restart_required else
                ["--previous", str(old), "--recovery-reason", outcome["reason"]]
                if old_result["status"] in {"failed", "interrupted"} else
                ["--continuous", "--task-count", str(len(protocol["task_ids"])), "--seed", str(protocol["seed"]),
                 "--data-root", str(old / "private/appworld"), "--appworld-venv", str(old / "private/appworld-venv")])
            command = [sys.executable, "-B", "-m", "loopblox.benchmarks.run_appworld",
                "--output", str(output), *continuation,
                "--worker-image", protocol["worker_image"], "--code-image", protocol["code_image"],
                "--request-timeout", str(protocol["model"]["timeout"]), "--attempt"]
    except KeyboardInterrupt:
        if process is not None:
            previous_int = signal.signal(signal.SIGINT, signal.SIG_IGN)
            try:
                process.send_signal(signal.SIGTERM)
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            finally:
                signal.signal(signal.SIGINT, previous_int)
        state["status"] = "stopped"
    except Exception as error:
        state.update(status="failed", incident=incident(error, stage="supervisor"))
        raise
    finally:
        signal.signal(signal.SIGTERM, previous)
        atomic_json(control / "state.json", state)
    return state
