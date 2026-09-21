"""Prepare audited τ² subsets, compare fixed Loops, and search specialist/general Loops."""

import argparse
import json
from pathlib import Path
import shutil
import sys

from loopblox import ROOT, snapshot_implementation
from loopblox.runtime.components import catalog
from loopblox.runtime.controller import Limits, ModelMeter, model_usage
from loopblox.runtime.model import ChatCompletionsClient
from loopblox.runtime.io import atomic_json, atomic_text, digest, image_id
from loopblox.experiments.study import BASELINE_CONTROLLER, comparison_plan, model_settings, run_study, write_report
from loopblox.benchmarks.tau2 import DEFAULT_TASK_LIMITS, Tau2Runner, load_suite, prepare_suite, prepare_official_suite


def user_client(args, agent):
    return ChatCompletionsClient(agent.api_key, agent.base_url, args.user_model or agent.model,
                                temperature=0, max_tokens=args.user_output_allowance, timeout=agent.timeout)


def comparison_calls(output):
    """Count each attempt once across explicitly copied comparison recoveries."""
    output = Path(output)
    previous = output / "private/prior-check"
    calls = comparison_calls(previous) if previous.exists() else []
    ledger = output / "private/usage.json"
    return calls + (json.loads(ledger.read_text())["calls"] if ledger.exists() else [])


def compare(args, *, controllers=None, previous=None, split="development"):
    """Compare additional controllers against the mandatory shared baseline."""
    additional = (("brief", "brief_work.py"), ("plan", "plan_then_work.py")) if controllers is None else controllers
    controllers = (("baseline", BASELINE_CONTROLLER), *additional)
    names = [name for name, _ in controllers]
    if len(names) != len(set(names)) or not all(name.isidentifier() for name in names):
        raise ValueError("Controller names must be unique identifiers; baseline is supplied by the host. "
                         "Name an additional mechanism comparison control instead.")
    manifest = load_suite(args.suite)
    if split not in {"development", "holdout"}:
        raise ValueError("Comparisons require a development or holdout split")
    if args.repeats < 1 or (args.development_per_domain is not None and args.development_per_domain < 1):
        raise ValueError("Repeat and development-task counts must be positive")
    families = list(dict.fromkeys(task["family"] for task in manifest["tasks"]))
    tasks = []
    for family in families:
        available = [task for task in manifest["tasks"]
                     if task["family"] == family and task["split"] == split]
        if args.development_per_domain is not None and len(available) < args.development_per_domain:
            raise ValueError(f"Not enough {split} tasks in {family}")
        tasks.extend(available[:args.development_per_domain])
    if not tasks:
        raise ValueError(f"No {split} tasks selected")
    client = ChatCompletionsClient.from_env()
    user = user_client(args, client)
    limits = Limits(seconds=args.task_seconds, actions=args.task_actions,
                    model_calls=args.task_model_calls, output_tokens=args.task_output_tokens)
    worker = image_id(args.worker_image)
    output = Path(args.output).resolve()
    if previous is not None:
        previous = Path(previous).resolve()
        if previous != output / "private/prior-check" or (output / "result.json").exists():
            raise ValueError("Comparison recovery requires a newly prepared output and its preserved prior check")
    output.mkdir(parents=True, exist_ok=previous is not None)
    private = output / "private"
    shutil.copytree(args.suite, private / "suite")
    snapshot_implementation(private)
    exposed = {name: {} for name in catalog()}
    setup = dict(model=model_settings(client), user_model=model_settings(user), task_limits=vars(limits),
                 worker_image=worker, environment_manifest=manifest, exposed=exposed,
                 task_ids=[task["task_id"] for task in tasks], split=split, repeats=args.repeats,
                 design=f"Fixed Python controllers ({', '.join(names)}) run {args.repeats} time(s) on the same "
                        f"{split} tasks, selected by the frozen manifest order within each domain. "
                        "Each repeat starts a fresh environment and worker with the same frozen task seed. "
                        "Pairing uses task and repeat; repeats are not new scenario groups. "
                        "Agent, simulated-user and grader calls share each task's limits.")
    atomic_json(private / "setup.json", setup)
    runner = Tau2Runner(private / "suite", manifest, client, user, worker, limits, private / "environments")
    state = dict(title=f"Fixed Loop comparison · τ² {split}", status="running", setup=setup,
                 families=families,
                 candidates={}, episodes={}, comparisons=[])
    for name, filename in controllers:
        source = (ROOT / "controllers" / filename).read_text()
        path = "controllers/" + name + ".py"
        atomic_text(output / path, source)
        state["candidates"][name] = dict(source=path, sha256=digest(source.encode()))
    state["comparisons"] = comparison_plan(state["candidates"], tasks, args.repeats)
    if previous is not None:
        old = json.loads((previous / "result.json").read_text())
        keys = ("candidate", "family", "task_id", "repeat")
        if (old["setup"] != setup or old["candidates"] != state["candidates"]
                or [[row[k] for k in keys] for row in old["comparisons"]]
                != [[row[k] for k in keys] for row in state["comparisons"]]):
            raise ValueError("Recovered comparisons must retain their frozen settings, sources and task order")
        for index, row in enumerate(old["comparisons"]):
            if row["status"] != "not_started":
                state["comparisons"][index] = {**row, "directory": "private/prior-check/" + row["directory"]}
                if row["status"] == "running":
                    state["comparisons"][index].update(status="interrupted", verification_verdict=None,
                        stop_reason="Prior attempt stopped before a final result was persisted")
        state["recovery"] = "Continue only unstarted rows; prior attempts, unscored outcomes and costs are retained."
    pending = [(index, row) for index, row in enumerate(state["comparisons"]) if row["status"] == "not_started"]
    count = len(pending)
    meter = (ModelMeter(private / "usage.json", seconds=limits.seconds * count,
                       model_calls=limits.model_calls * count, output_tokens=limits.output_tokens * count)
             if count else None)
    atomic_json(output / "result.json", state)
    try:
        for index, row in pending:
            row["status"] = "running"
            atomic_json(output / "result.json", state)
            print(f"{split.title()}: {row['candidate']} / {row['task_id']} / repeat {row['repeat'] + 1}", flush=True)
            source = (output / state["candidates"][row["candidate"]]["source"]).read_text()
            try:
                row.update(runner(task_id=row["task_id"], source=source, scope=f"fixed-{index}",
                                  directory=output / row["directory"], meter=meter, exposed=exposed))
            except BaseException:
                row.update(status="interrupted", verification_verdict=None)
                raise
            finally:
                atomic_json(output / "result.json", state)
            print(json.dumps({key: row.get(key) for key in ("candidate", "task_id", "status", "verification_verdict", "usage")}), flush=True)
            if row["status"] in {"host_fault", "operational_failure", "verifier_failure"}:
                raise RuntimeError("Fix the recorded integration failure before running the remaining batch")
        state["status"] = "complete"
    except BaseException:
        state["status"] = "interrupted"
        raise
    finally:
        state["usage"] = model_usage(comparison_calls(output))
        atomic_json(output / "result.json", state)
        write_report(output)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Audit and freeze disjoint groups without model calls")
    prepare.add_argument("--source", default=str(ROOT / ".artifacts/upstream/tau2-bench"))
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--development", type=int, default=18)
    prepare.add_argument("--holdout", type=int, default=18)
    prepare.add_argument("--exclude-suite", action="append", default=[], help="Reserve all groups already used for integration checks")
    prepare.add_argument("--seed", type=int, default=2701)
    for command, domain, count, seed in (("prepare-retail-rounds", "retail", 30, 20260915),
                                         ("prepare-telecom-release", "telecom", 10, 20260920)):
        official = commands.add_parser(command, help=f"Audit {count} official {domain} train tasks and freeze all test without model calls")
        official.set_defaults(domain=domain, development=count)
        official.add_argument("--source", default=str(ROOT / ".artifacts/upstream/tau2-bench"))
        official.add_argument("--output", required=True)
        official.add_argument("--seed", type=int, default=seed)
        if domain == "telecom":
            official.add_argument("--exclude-suite", action="append", default=[],
                                 help="Exclude previously reserved suite families from training; retain and disclose test overlap")
    for command in ("compare", "study", "inherit"):
        run = commands.add_parser(command)
        run.add_argument("--suite", required=True)
        run.add_argument("--output", required=True)
        run.add_argument("--worker-image", default="python:3.12-slim")
        run.add_argument("--user-model")
        run.add_argument("--user-output-allowance", type=int, default=2048)
        for name, value in vars(DEFAULT_TASK_LIMITS).items():
            run.add_argument("--task-" + name.replace("_", "-"), type=type(value), default=value)
        if command in {"study", "inherit"}:
            if command == "study":
                run.add_argument("--experiment", default=str(ROOT / "experiments/tau2.json"))
            run.add_argument("--seed", type=int, default=0)
            run.add_argument("--development-runs", type=int, default=8)
            run.add_argument("--research-seconds", type=float, default=3600)
            run.add_argument("--research-model-calls", type=lambda value: None if value.lower() == "none" else int(value),
                             default=256, help="Shared call cap; explicitly use 'none' for native Codex research")
            run.add_argument("--research-output-tokens", type=lambda value: None if value.lower() == "none" else int(value),
                             default=262144, help="Shared output cap; explicitly use 'none' for native Codex research")
            if command == "inherit":
                run.add_argument("--rounds", type=int, default=3)
                run.add_argument("--prepare-only", action="store_true", help="Freeze and check the campaign without model calls")
        else:
            run.add_argument("--development-per-domain", type=int,
                             help="Use the first N development tasks per domain in frozen manifest order")
            run.add_argument("--repeats", type=int, default=1,
                             help="Fresh runs of each task/controller pair; not additional task groups")
    report = commands.add_parser("report")
    report.add_argument("output")
    args = parser.parse_args()
    if args.command in {"prepare-retail-rounds", "prepare-telecom-release"}:
        manifest = prepare_official_suite(args.output, source=args.source, seed=args.seed,
                                         domain=args.domain, development=args.development,
                                         exclude_suites=getattr(args, "exclude_suite", ()))
        print(json.dumps({"tasks": len(manifest["tasks"]), "manifest": str(Path(args.output) / "manifest.json")}))
    elif args.command == "prepare":
        manifest = prepare_suite(args.output, source=args.source, development=args.development,
                                 holdout=args.holdout, seed=args.seed, exclude_suites=args.exclude_suite)
        print(json.dumps({"tasks": len(manifest["tasks"]), "manifest": str(Path(args.output) / "manifest.json")}))
    elif args.command == "report":
        write_report(args.output)
    elif args.command == "compare":
        compare(args)
    elif args.command == "inherit":
        from loopblox.experiments.inheritance import prepare
        from loopblox.experiments.common import run_stage
        output = prepare(args)
        if not args.prepare_only:
            raise SystemExit(run_stage([sys.executable, "-P", "-B", "-m", "loopblox.experiments.inheritance",
                                        "run", str(output)], source_root=output / "implementation"))
    else:
        agent = ChatCompletionsClient.from_env()
        user = user_client(args, agent)
        run_study(args, load_suite=load_suite,
                  runner_factory=lambda suite, manifest, client, worker, limits, private: Tau2Runner(
                      suite, manifest, client, user, worker, limits, private / "environments"),
                  include_mixed=True,
                  extra_setup={"user_model": model_settings(user)})


if __name__ == "__main__":
    main()
