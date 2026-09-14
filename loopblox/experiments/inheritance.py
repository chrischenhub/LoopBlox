"""Serial, frozen inheritance experiments using ResearchSession and the existing τ² comparator."""

import argparse
import json
import math
from pathlib import Path
from loopblox import ROOT, snapshot_implementation
from loopblox.experiments.common import read, run_stage, verify, clients
import shutil
import sys
import time

from loopblox.research.session import ResearchSession, export_experience, research_evidence
from loopblox.runtime.components import catalog
from loopblox.runtime.controller import Limits, model_usage
from loopblox.runtime.model import ChatCompletionsClient
from loopblox.runtime.io import atomic_json, atomic_text, digest, image_id
from loopblox.experiments.study import BASELINE_CONTROLLER, model_settings
from loopblox.benchmarks.tau2 import Tau2Runner, load_suite


CONDITIONS = ("independent", "loop", "loop_memory")


def episode_budget(protocol, item):
    spent = [attempt["spent"] for attempt in item.get("prior_attempts", [])]
    return {key: cap - sum(attempt[key] for attempt in spent)
            for key, cap in protocol["research_budgets"].items()}


def prepare_resume(source, root):
    """Preserve completed episodes; rerun unfinished ones within their unspent caps."""
    source, root = Path(source).resolve(), Path(root).resolve()
    protocol, old_state = read(source / "protocol.json"), read(source / "result.json")
    if old_state["status"] not in {"incomplete", "interrupted"}:
        raise ValueError("Recovery requires a stopped campaign")
    previous_check = source / "training-check"
    if previous_check.exists() and any(item["status"] != "complete" for item in old_state["episodes"]):
        raise ValueError("Checkpoint recovery requires all research to have completed")
    for name, sha in protocol["implementation_sha256"].items():
        if digest((source / "implementation" / name).read_bytes()) != sha:
            raise ValueError("Original frozen implementation changed: " + name)
        if name not in {"loopblox/runtime/model.py", "loopblox/runtime/controller.py", "loopblox/experiments/inheritance.py", "loopblox/experiments/common.py", "loopblox/benchmarks/run_tau2.py", "AGENTS.md", "README.md"}:
            if digest((ROOT / name).read_bytes()) != sha:
                raise ValueError("Recovery must preserve the research instructions, component library and environment: " + name)
    if digest((source / "suite/manifest.json").read_bytes()) != protocol["suite_manifest_sha256"]:
        raise ValueError("Original frozen manifest changed")
    manifest = load_suite(source / "suite")
    client, user = clients(protocol)
    image_id(protocol["worker_image"])
    root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source / "suite", root / "suite")
    Tau2Runner(root / "suite", manifest, client, user, protocol["worker_image"],
                Limits(**protocol["task_limits"]), root / "private/preflight")
    if (source / "private/prior-attempts").exists():
        shutil.copytree(source / "private/prior-attempts", root / "private/prior-attempts")
    old_items = {item["label"]: item for item in old_state["episodes"]}
    imported_hashes = {str(path.relative_to(root)): digest(path.read_bytes())
                       for path in (root / "private/prior-attempts").rglob("*") if path.is_file()}
    reused, remaining = [], []
    for item in protocol["episodes"]:
        old_item = old_items[item["label"]]
        old_episode = source / item["directory"]
        if old_item["status"] == "complete":
            state, result = read(old_episode / "private/state.json"), read(old_episode / "result.json")
            if state.get("research_status") != "completed" or not state.get("selection_reason") or result["status"] != "complete":
                raise ValueError("Only explicitly submitted research can be reused")
            if digest((old_episode / "selected-controller.py").read_bytes()) != result["selected_sha256"]:
                raise ValueError("Submitted source changed")
            destination = root / item["directory"]
            shutil.copytree(old_episode, destination)
            reused.append(item["label"])
        elif (old_episode / "private/state.json").exists():
            attempts = item.setdefault("prior_attempts", [])
            destination = root / "private/prior-attempts" / item["label"] / f"attempt-{len(attempts) + 1:02d}"
            shutil.copytree(old_episode, destination)
            state, result = read(old_episode / "private/state.json"), read(old_episode / "result.json")
            usage = model_usage(read(old_episode / "private/research-usage.json")["calls"])
            seconds = result.get("elapsed_seconds")
            if seconds is None:
                # Older episodes have no overall duration; charge their conservative wall-clock envelope.
                seconds = (old_episode / "result.json").stat().st_mtime - (old_episode / "private/setup.json").stat().st_mtime
            attempts.append(dict(directory=str(destination.relative_to(root)),
                spent=dict(task_runs=state["task_runs_used"], model_calls=usage["model_calls"],
                           output_tokens=usage["charged_output_tokens"], seconds=math.ceil(max(0, seconds))),
                seconds_basis="recorded episode duration" if "elapsed_seconds" in result else "setup-to-result file timestamps, rounded up"))
        else:
            continue
        for path in destination.rglob("*"):
            if path.is_file():
                imported_hashes[str(path.relative_to(root))] = digest(path.read_bytes())
    for item in protocol["episodes"]:
        if item["label"] not in reused:
            budget = episode_budget(protocol, item)
            if min(budget.values()) <= 0 or budget["task_runs"] < 2:
                raise ValueError("No complete opening comparison fits the remaining budget: " + item["label"])
            remaining.append(dict(label=item["label"], budget=budget))
    if previous_check.exists():
        # A new comparator continues only unstarted rows. Prior attempts remain exact,
        # including interrupted/unscored rows; no task or model attempt is replayed.
        read(previous_check / "result.json")
        destination = root / "training-check/private/prior-check"
        shutil.copytree(previous_check, destination)
        for path in destination.rglob("*"):
            if path.is_file():
                imported_hashes[str(path.relative_to(root))] = digest(path.read_bytes())
    protocol["implementation_sha256"] = snapshot_implementation(root)
    protocol["recovery"] = dict(source_campaign=str(source), source_protocol_sha256=digest((source / "protocol.json").read_bytes()),
        source_result_sha256=digest((source / "result.json").read_bytes()), reused_episodes=reused,
        imported_files=imported_hashes, remaining=remaining,
        policy="Explicitly completed episodes are byte-for-byte snapshots, never rerun. Unfinished episodes get fresh "
               "researchers and retain only their unspent task/model/output/time caps. Prior failed attempts are "
               "private accounting records, not inherited research experience. The library, research instructions, "
               "models, tasks and seeds stay fixed; only service-failure handling and campaign recovery changed. "
               "Old successful results retain their original runtime snapshots. Checkpoint recovery continues only "
               "unstarted comparisons; every prior attempted row and its costs remain recorded, including unscored "
               "interruptions. No Python continuation is resumed.")
    atomic_json(root / "protocol.json", protocol)
    atomic_json(root / "result.json", dict(status="prepared", episodes=[{**item,
        "status": "complete" if item["label"] in reused else "not_started"} for item in protocol["episodes"]]))
    report(root)
    print(json.dumps(dict(output=str(root), reused=reused, remaining=remaining,
        max_new_research_runs=sum(row["budget"]["task_runs"] for row in remaining), holdout_runs=0)), flush=True)
    return root


def prepare(args):
    from loopblox.benchmarks.run_tau2 import user_client
    if args.rounds < 2:
        raise ValueError("Inheritance requires at least two rounds")
    manifest = load_suite(args.suite)
    if not manifest["tasks"] or any(task["split"] != "development" for task in manifest["tasks"]):
        raise ValueError("Supply a development-only suite; this experiment performs no holdout evaluation")
    client = ChatCompletionsClient.from_env()
    user = user_client(args, client)
    limits = Limits(**{name: getattr(args, "task_" + name) for name in vars(Limits())})
    worker = image_id(args.worker_image)
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(args.suite, root / "suite")
    # Check the pinned runtime before research. Every subsequent phase uses a fresh process.
    Tau2Runner(root / "suite", manifest, client, user, worker, limits, root / "private/preflight")
    source_hashes = snapshot_implementation(root)
    episodes = []
    for index in range(args.rounds):
        offset = index % len(CONDITIONS)
        for condition in CONDITIONS[offset:] + CONDITIONS[:offset]:
            label = f"{condition}-r{index + 1:02d}"
            episodes.append(dict(label=label, condition=condition, round=index + 1, seed=args.seed + index,
                directory=f"episodes/{label}", parent=None if index == 0 or condition == "independent"
                else f"episodes/{condition}-r{index:02d}"))
    experiment = dict(exposed={name: {} for name in catalog()}, question=(
        "Search for a reusable Loop on the frozen development tasks. Improve complete-task success under the "
        "fixed limits, and compare total execution cost including the simulated user. The unified baseline is "
        "always available. A supplied starting source is an incumbent, not a required structure. If an experience "
        "overview is supplied, use its scoped candidate identities and follow the relevant evidence before designing candidates; previous "
        "hypotheses are not established causes. Compare candidates on shared draws. Consider whether the evidence "
        "motivates a different mechanism rather than only another option in the same family. Retaining the "
        "baseline and finishing early remain valid. Explain unresolved directions and the value or cost of further "
        "search in your submission. Do not encode task answers, IDs, business workflows or research history in "
        "candidate code. The host will check all submitted checkpoints on the entire development suite only after "
        "every researcher closes. Those checks never return to research and are training evidence, not holdout."))
    budgets = dict(task_runs=args.development_runs, seconds=args.research_seconds,
                   model_calls=args.research_model_calls, output_tokens=args.research_output_tokens)
    if min(budgets.values()) <= 0 or budgets["task_runs"] < 2:
        raise ValueError("Each round needs positive budgets and at least two initial-comparison slots")
    protocol = dict(conditions=CONDITIONS, rounds=args.rounds, episodes=episodes, research_budgets=budgets, concurrency=1,
        model=model_settings(client), user_model=model_settings(user), worker_image=worker, task_limits=vars(limits),
        task_ids=[task["task_id"] for task in manifest["tasks"]], holdout_task_ids=[], experiment=experiment,
        baseline_sha256=digest(BASELINE_CONTROLLER.read_bytes()),
        suite_manifest_sha256=digest((root / "suite/manifest.json").read_bytes()),
        implementation_sha256=source_hashes,
        max_research_runs=len(episodes) * budgets["task_runs"],
        max_training_check_runs=(len(episodes) + 1) * len(manifest["tasks"]),
        design="One chain per condition, with equal per-round budget caps and shared sampling seed by round. "
               "Independent rounds receive neither previous source nor experience. Loop rounds inherit only their "
               "own immediate predecessor's submitted source. Loop+memory rounds also receive cumulative public "
               "development evidence from their own chain. First rounds are separate baseline starts. Researchers "
               "are fresh, tools and models are fixed, execution is serial, and condition order rotates by round. "
               "Early finish is allowed and actual expenditure is reported; equal caps need not yield equal spend. "
               "One chain is a pilot, not an estimate of a reproducible causal inheritance effect. Exact duplicate "
               "checkpoint sources share one final training check. No checkpoint is chosen using that later check. "
               "Best-so-far training scores are descriptive of the submitted set, not independently validated selections.")
    atomic_json(root / "protocol.json", protocol)
    atomic_json(root / "result.json", dict(status="prepared", episodes=[{**e, "status": "not_started"} for e in episodes]))
    report(root)
    print(json.dumps(dict(output=str(root), rounds=args.rounds, episodes=len(episodes), train_tasks=len(manifest["tasks"]),
                         max_research_runs=protocol["max_research_runs"],
                         max_training_check_runs=protocol["max_training_check_runs"], holdout_runs=0)), flush=True)
    return root


def episode(root, label):
    protocol = verify(root)
    item = next(e for e in protocol["episodes"] if e["label"] == label)
    output = root / item["directory"]
    starting, experience = None, None
    parent_hash = None
    if item["parent"]:
        parent = root / item["parent"]
        result = read(parent / "result.json")
        if result["status"] != "complete":
            raise ValueError("The predecessor did not explicitly finish; no continuation is permitted")
        source = parent / "selected-controller.py"
        if digest(source.read_bytes()) != result["selected_sha256"]:
            raise ValueError("Inherited source changed")
        starting = source.read_text()
        parent_hash = digest((parent / "private/state.json").read_bytes())
        if item["condition"] == "loop_memory":
            experience = root / "private/experience" / label
            export_experience(parent, experience)
    client, user = clients(protocol)
    limits = Limits(**protocol["task_limits"])
    manifest = load_suite(root / "suite")
    runner = Tau2Runner(root / "suite", manifest, client, user, protocol["worker_image"], limits,
                        root / "private/environments" / label)
    budget = episode_budget(protocol, item)
    session = ResearchSession(output=output, development=tuple(protocol["task_ids"]), holdout=(), run_task=runner,
        research_client=client, worker_image=protocol["worker_image"],
        setup=dict(model=protocol["model"], user_model=protocol["user_model"], condition=item["condition"],
                   round=item["round"], parent=item["parent"], parent_state_sha256=parent_hash,
                   campaign_protocol_sha256=digest((root / "protocol.json").read_bytes())),
        experiment=protocol["experiment"], baseline_source=BASELINE_CONTROLLER.read_text(),
        starting_source=starting, experience=experience, max_task_runs=budget["task_runs"],
        research_seconds=budget["seconds"], research_model_calls=budget["model_calls"],
        research_output_tokens=budget["output_tokens"], task_limits=limits, seed=item["seed"])
    result = dict(status="running", **item)
    atomic_json(output / "result.json", result)
    started = time.monotonic()
    try:
        session.research()
        if session.state.get("research_status") != "completed" or not session.state.get("selection_reason"):
            raise RuntimeError("Research ended without a completed explicit submission")
        result.update(status="complete", selected=session.state["frozen_candidate"],
                      selected_sha256=digest((output / "selected-controller.py").read_bytes()))
    except BaseException as error:
        result.update(status="interrupted", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        result.update(research_status=session.state.get("research_status", session.state["status"]),
                      task_runs=session.state["task_runs_used"], evidence=research_evidence(session.state),
                      elapsed_seconds=time.monotonic() - started)
        if hasattr(session, "meter"):
            result["usage"] = session.meter.summary()
        atomic_json(output / "result.json", result)
        print(json.dumps({k: result.get(k) for k in ("label", "status", "selected", "task_runs", "usage")}), flush=True)


def check(root):
    from loopblox.benchmarks.run_tau2 import compare
    protocol = verify(root)
    clients(protocol)
    if any(read(root / item["directory"] / "result.json")["status"] != "complete" for item in protocol["episodes"]):
        raise ValueError("All researchers must explicitly finish before checkpoint evaluation")
    aliases, additional = {}, []
    hashes = {protocol["baseline_sha256"]: "baseline"}
    closures = {}
    for item in protocol["episodes"]:
        output = root / item["directory"]
        result = read(output / "result.json")
        source = output / "selected-controller.py"
        sha = digest(source.read_bytes())
        if sha != result["selected_sha256"]:
            raise ValueError("A submitted checkpoint changed")
        if sha not in hashes:
            name = item["label"].replace("-", "_")
            hashes[sha] = name
            additional.append((name, source))
        aliases[item["label"]] = hashes[sha]
        closures[item["label"]] = digest((output / "private/state.json").read_bytes())
    atomic_json(root / "check-plan.json", dict(aliases=aliases, sources=hashes, research_state_hashes=closures,
                repeats=1, task_ids=protocol["task_ids"], holdout_runs=0, training_only=True))
    args = argparse.Namespace(suite=root / "suite", output=root / "training-check", worker_image=protocol["worker_image"],
        repeats=1, development_per_domain=None, user_model=protocol["user_model"]["model"],
        user_output_allowance=protocol["user_model"]["max_tokens"],
        **{"task_" + key: value for key, value in protocol["task_limits"].items()})
    previous = root / "training-check/private/prior-check"
    compare(args, controllers=tuple(additional), previous=previous if previous.exists() else None)
    for item in protocol["episodes"]:
        if digest((root / item["directory"] / "private/state.json").read_bytes()) != closures[item["label"]]:
            raise ValueError("Research changed during the final training check")


def run(root):
    protocol = verify(root)
    state = read(root / "result.json")
    if state["status"] != "prepared":
        raise ValueError("Start a new campaign; interrupted research is never silently resumed")
    state["status"] = "researching"
    atomic_json(root / "result.json", state)
    try:
        for item in state["episodes"]:
            if item["status"] == "complete":
                continue
            parent = root / item["parent"] / "result.json" if item["parent"] else None
            if parent is not None and (not parent.exists() or read(parent)["status"] != "complete"):
                item.update(status="blocked", reason="Predecessor did not explicitly finish")
            else:
                item["status"] = "running"
                atomic_json(root / "result.json", state)
                report(root)
                print(f"Starting {item['label']} (fresh researcher, at most {episode_budget(protocol, item)['task_runs']} task runs)", flush=True)
                exit_code = run_stage([sys.executable, "-P", "-B", "-m", "loopblox.experiments.inheritance", "episode", str(root), item["label"]])
                path = root / item["directory"] / "result.json"
                item.update(status="complete" if exit_code == 0 else "interrupted", exit_code=exit_code)
                if path.exists():
                    item["result"] = str(path.relative_to(root))
            atomic_json(root / "result.json", state)
            report(root)
            if item["status"] != "complete":
                state.update(status="interrupted", stop_reason=f"Stopped after {item['label']}; later episodes were not dispatched")
                return
        if all(item["status"] == "complete" for item in state["episodes"]):
            state["status"] = "training_check"
            atomic_json(root / "result.json", state)
            exit_code = run_stage([sys.executable, "-P", "-B", "-m", "loopblox.experiments.inheritance", "check", str(root)])
            state["status"] = "complete" if exit_code == 0 else "interrupted"
        else:
            state["status"] = "incomplete"
    except BaseException as error:
        state.update(status="interrupted", error_type=type(error).__name__, error=str(error))
        for item in state["episodes"]:
            if item["status"] == "running":
                path = root / item["directory"] / "result.json"
                item["status"] = "complete" if path.exists() and read(path)["status"] == "complete" else "interrupted"
                if path.exists():
                    item["result"] = str(path.relative_to(root))
        raise
    finally:
        atomic_json(root / "result.json", state)
        report(root)


def report(root):
    protocol, state = read(root / "protocol.json"), read(root / "result.json")
    calls, rows = [], []
    aliases = read(root / "check-plan.json")["aliases"] if (root / "check-plan.json").exists() else {}
    comparison_path = root / "training-check/result.json"
    if not comparison_path.exists():
        comparison_path = root / "training-check/private/prior-check/result.json"
    comparison = read(comparison_path) if comparison_path.exists() else {}
    counts, seen, best = {c: 0 for c in CONDITIONS}, {c: set() for c in CONDITIONS}, {c: None for c in CONDITIONS}
    chain_calls = {c: [] for c in CONDITIONS}
    total_runs, prior_runs, reused_runs = 0, 0, 0
    retained_calls = []
    reused = protocol.get("recovery", {}).get("reused_episodes", [])
    for item in sorted(state["episodes"], key=lambda e: (e["round"], CONDITIONS.index(e["condition"]))):
        output = root / item["directory"]
        evidence, usage, selected, memory_reads, novel = {}, {}, "—", 0, 0
        episode_calls, old_runs = [], 0
        for attempt in item.get("prior_attempts", []):
            previous = root / attempt["directory"]
            recorded = read(previous / "private/research-usage.json")["calls"]
            assert len(recorded) == attempt["spent"]["model_calls"]
            episode_calls.extend(recorded)
            retained_calls.extend(recorded)
            old_runs += attempt["spent"]["task_runs"]
        prior_runs += old_runs
        total_runs += old_runs
        counts[item["condition"]] += old_runs
        if (output / "private/state.json").exists():
            episode_state = read(output / "private/state.json")
            evidence = research_evidence(episode_state)
            selected = episode_state.get("frozen_candidate", episode_state["selected"])
            total_runs += evidence["task_runs_used"]
            counts[item["condition"]] += evidence["task_runs_used"]
            if item["label"] in reused:
                reused_runs += evidence["task_runs_used"]
            for candidate in episode_state["candidates"]:
                sha = digest((output / f"public/candidates/{candidate}.py").read_bytes())
                if sha != protocol["baseline_sha256"] and sha not in seen[item["condition"]]:
                    novel += 1
                seen[item["condition"]].add(sha)
        ledger = output / "private/research-usage.json"
        if ledger.exists():
            recorded = read(ledger)["calls"]
            episode_calls.extend(recorded)
            if item["label"] in reused:
                retained_calls.extend(recorded)
        calls.extend(episode_calls)
        chain_calls[item["condition"]].extend(episode_calls)
        usage = model_usage(episode_calls)
        trace = output / "private/research-trace.json"
        if trace.exists():
            history = read(trace)["history"]
            successful = {event["action_id"] for event in history
                          if event["type"] == "tool_result" and event["status"] == "ok"}
            memory_reads = sum(event["type"] == "tool_call" and event["capability_id"] == "read_artifact"
                               and event["arguments"].get("path", "").startswith("experience/")
                               and event["action_id"] in successful for event in history)
        final = [row for row in comparison.get("comparisons", []) if row["candidate"] == aliases.get(item["label"])]
        score = None
        if len(final) == len(protocol["task_ids"]) and all(row.get("verification_verdict") in {"pass", "fail"} for row in final):
            score = sum(row["verification_verdict"] == "pass" for row in final)
            previous = best[item["condition"]]
            best[item["condition"]] = score if previous is None else max(previous, score)
        rows.append(dict(**item, task_runs=evidence.get("task_runs_used", 0) + old_runs, prior_attempt_task_runs=old_runs,
            reused=item["label"] in reused, cumulative_task_runs=counts[item["condition"]],
            model_calls=usage.get("model_calls", 0), selected=selected, new_source_count=novel,
            usage=usage, cumulative_usage=model_usage(chain_calls[item["condition"]]),
            experience_reads=memory_reads, training_passes=score, best_submitted_training_passes=best[item["condition"]]))
    search_usage = model_usage(calls)
    from loopblox.benchmarks.run_tau2 import comparison_calls
    check_calls = comparison_calls(root / "training-check")
    check_runs = sum(row["status"] != "not_started" for row in comparison.get("comparisons", []))
    analysis = dict(status=state["status"], episodes=rows, research_task_runs=total_runs, training_check_runs=check_runs,
        total_task_runs=total_runs + check_runs, research_usage=search_usage, training_check_usage=model_usage(check_calls),
        total_usage=model_usage(calls + check_calls), holdout_runs=0,
        reused_completed_task_runs=reused_runs, prior_attempt_task_runs=prior_runs,
        new_research_task_runs=total_runs-reused_runs-prior_runs, retained_usage=model_usage(retained_calls))
    atomic_json(root / "analysis.json", analysis)
    lines = ["# Loop inheritance · training-only pilot", "", f"Status: **{state['status']}**.", "",
        "| Condition / round | Status | Task runs / cumulative | Model requests / cumulative | New sources | Experience reads | Training score |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    for row in rows:
        score = "pending" if row["training_passes"] is None else f"{row['training_passes']}/{len(protocol['task_ids'])}"
        lines.append(f"| [{row['label']}]({row['directory']}/public/evidence.json) | {row['status']} | "
                     f"{row['task_runs']} / {row['cumulative_task_runs']} | {row['model_calls']} / {row['cumulative_usage']['model_calls']} | "
                     f"{row['new_source_count']} | {row['experience_reads']} | {score} |")
    lines += ["", f"Actual totals: {analysis['total_task_runs']} task runs; {analysis['total_usage']['model_calls']} model requests. "
              "All agent, researcher and simulated-user requests are counted, including failures. Unknown usage remains unknown.", "",
              f"Caps: {protocol['max_research_runs']} research task runs + {protocol['max_training_check_runs']} checkpoint checks. "
              "Unused budget is not moved between rounds. Identical submitted sources share one check, with aliases in check-plan.json.", "",
              protocol["design"], "", "Source novelty means exact source bytes, not a new behavioral mechanism. "
              "Experience reads show access, not correct understanding. Final checks are training evidence on previously used tasks. "
              "Researcher descriptions remain hypotheses; use host-derived evidence and paired records to verify them.", "",
              "[Frozen protocol](protocol.json) · [Full accounting](analysis.json) · [Training comparison](training-check/report.html)", ""]
    if "recovery" in protocol:
        lines += ["## Recovery", "", protocol["recovery"]["policy"], "",
                  f"Retained: {reused_runs} task runs from completed episodes and {prior_runs} from failed attempts. "
                  f"New research attempts: {analysis['new_research_task_runs']}. Retained work is included once in total costs. "
                  "Per-round caps are reduced by prior attempt usage, including reserved output for unknown usage. "
                  "Older episode time is charged from its recorded file timestamp envelope, rounded up.", ""]
    atomic_text(root / "report.md", "\n".join(lines))
    return analysis


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "episode", "check", "report", "resume"))
    parser.add_argument("output", type=Path)
    parser.add_argument("label", nargs="?")
    parser.add_argument("--from-campaign", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    root = args.output.resolve()
    if args.command == "resume":
        if args.from_campaign is None:
            parser.error("resume requires --from-campaign")
        prepare_resume(args.from_campaign, root)
        if not args.prepare_only:
            raise SystemExit(run_stage([sys.executable, "-P", "-B", "-m", "loopblox.experiments.inheritance", "run", str(root)],
                                      source_root=root / "implementation"))
    elif args.command == "episode":
        episode(root, args.label)
    else:
        {"run": run, "check": check, "report": report}[args.command](root)
        if args.command == "run" and read(root / "result.json")["status"] != "complete":
            raise SystemExit(1)
