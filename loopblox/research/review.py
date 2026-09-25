"""Hand one completed public task trace to the native researcher for analysis only."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import shutil
import tempfile
import time

from loopblox import snapshot_implementation
from loopblox.research.codex import default_researcher, native_usage
from loopblox.runtime.components import object_schema, validate
from loopblox.runtime.controller import ModelMeter
from loopblox.runtime.io import atomic_json, atomic_text, digest


def review(run, output):
    run, output = run.resolve(), output.resolve()
    public_source = run.parent.parent.parent
    result = json.loads((run / "result.json").read_text())
    semantic = json.loads((run / "jev.json").read_text())
    if result["status"] != "completed" or result["verification_verdict"] not in {"pass", "fail"}:
        raise ValueError("Review requires a completed, officially scored task")
    if semantic["status"] != "completed":
        raise ValueError("Mandatory Jev analysis must finish before review")
    setup = json.loads((public_source.parent / "private/setup.json").read_text())
    output.mkdir(parents=True, exist_ok=False)
    public, private = output / "public", output / "private"
    public.mkdir(); private.mkdir()
    scratch = private / "work"
    scratch.mkdir(); scratch.chmod(0o777)
    for name in ("components.json", "component-contracts.md", "controller-api.md", "loop.md",
                 "jev-config.json", "jev-guide.md"):
        shutil.copyfile(public_source / name, public / name)
    shutil.copytree(run, public / "task-run")
    protocol = (
        "# Single-task research handoff\n\n"
        "The user paused the ten-task AppWorld pilot and handed its completed first task to the researcher. "
        "This is one analysis invocation, not a continuous campaign or an evaluation request. "
        "Only this task's public records are available. Do not resume task 2 or dispatch any task.\n\n"
        "Inspect the baseline source, task, exact model inputs and outputs, public observations, official "
        "aggregate score, and Jev evidence. Explain the failure and cost using cited artifact locations and "
        "invocation IDs. Separate confirmed facts from hypotheses; private evaluator assertions and answers "
        "are unavailable. Jev is a noisy judgment, not an official score or causal proof. Distinguish task "
        "model limitations, provider faults, and editable Loop behavior.\n\n"
        "You may propose one reusable Python Loop using the frozen exposed components and options. "
        "Do not hardcode task IDs, answers, app-specific solutions or research history in its source. "
        "Do not change component prompts, models, tools, provider settings, or evaluation. "
        "No particular redesign is prescribed. State the predicted effect, risks, competing explanations "
        "and a focused validation plan; the proposed Loop will not be executed by this handoff.\n\n"
        "Keep the frozen task model and high reasoning effort. Task budgets and the client output cap "
        "were removed for this pilot; request deadlines and provider limits still applied. "
        "Missing usage remains unknown. Analyze only observed spend; do not treat failed requests as free.\n\n"
        "Use native local tools to inspect /evidence and write scratch work under /work. "
        "Return exactly one submit_review request after completing your analysis. There is no evaluate, "
        "checkpoint or further iteration in this handoff. Write the report and rationale in English.\n"
    )
    atomic_text(public / "experiment.md", protocol)
    atomic_json(public / "progress.json", dict(status="reviewing", task_id=result["task_id"],
        completed_tasks=1, official_verdict=result["verification_verdict"], task_dispatch="paused"))
    provenance = {str(path.relative_to(public)): digest(path.read_bytes())
                  for path in public.rglob("*") if path.is_file()}
    atomic_json(private / "provenance.json", dict(source_run=str(run), public_files=provenance))
    atomic_json(private / "implementation-manifest.json", snapshot_implementation(private))
    atomic_json(private / "setup.json", dict(mode="single_task_review", source_run=str(run)))
    meter = ModelMeter(private / "usage.json", seconds=None, output_tokens=None, model_calls=None)
    researcher = default_researcher(public_root=public, scratch_path=scratch, private=private,
        container_image=setup["worker_image"], meter=meter)
    configuration = json.loads((private / "researcher-configuration.json").read_text())
    schema = object_schema({key: {"type": "string"} for key in ("report", "source", "rationale")})
    tools = [dict(capability_id="submit_review", kind="mutate", parameters=schema,
        description="Submit your final evidence-based report, one proposed reusable run(env) source "
                    "(or an empty string if no defensible change is supported), and rationale. "
                    "This saves research claims and source only; it never evaluates or installs them.")]
    materials = private / "exchange"
    (materials / "receipts").mkdir(parents=True)
    atomic_json(materials / "tools.json", tools)
    atomic_json(materials / "task.json", dict(problem=protocol, task_id=result["task_id"],
        experiment=setup["experiment"], task_model=setup["model"], task_limits=setup["task_limits"],
        evidence="/evidence/task-run", source="/evidence/task-run/controller.py"))
    invocation = private / "invocation"
    invocation.mkdir()
    started = time.monotonic()
    record = dict(status="reviewing", source_run=str(run), task_id=result["task_id"],
                  task_dispatch="paused", calls=[])
    atomic_json(output / "result.json", record)
    try:
        with tempfile.TemporaryDirectory(prefix="loopblox-codex-review-") as temporary:
            home = Path(temporary)
            shutil.copyfile(researcher.auth_path, home / "auth.json")
            (home / "auth.json").chmod(0o600)
            atomic_text(home / "config.toml", researcher._config_text())
            call = researcher._invoke(materials, invocation, math.inf,
                                      configuration["container_image"], home)
        record["calls"].append(call)
        if call["exit_code"] or call["failure"] or not call["session_id"]:
            raise RuntimeError("Native review failed; inspect private invocation records")
        request = json.loads((invocation / "output/request.json").read_text())
        if set(request) != {"tool", "arguments"} or request["tool"] != "submit_review":
            raise ValueError("Expected one submit_review request")
        validate(request["arguments"], schema)
        arguments = request["arguments"]
        if not arguments["report"].strip() or not arguments["rationale"].strip():
            raise ValueError("Review report and rationale must be nonempty")
        if arguments["source"].strip():
            compile(arguments["source"], "proposed-controller.py", "exec")
            atomic_text(public / "proposed-controller.py", arguments["source"])
        atomic_text(public / "review.md", arguments["report"])
        atomic_json(public / "proposal.json", dict(status="unexecuted", **arguments))
        record.update(status="completed", report="public/review.md", proposal="public/proposal.json")
    except BaseException as error:
        record.update(status="failed" if isinstance(error, Exception) else "interrupted",
                      error=type(error).__name__ + ": " + str(error))
        raise
    finally:
        record.update(elapsed_seconds=time.monotonic() - started, native_usage=native_usage(record["calls"]))
        atomic_json(output / "result.json", record)
        atomic_json(public / "progress.json", dict(status=record["status"], task_id=result["task_id"],
            completed_tasks=1, official_verdict=result["verification_verdict"], task_dispatch="paused"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    review(args.run, args.output)
