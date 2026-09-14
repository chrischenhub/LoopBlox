"""Shared composition study and recorded-result reports for concrete task runners."""

import difflib
from html import escape
import json
from pathlib import Path
import shutil
import time

from loopblox import ROOT, snapshot_implementation
from loopblox.research.session import ResearchSession, summarize, validate_experiment
from loopblox.runtime.controller import Limits, ModelMeter, model_usage
from loopblox.runtime.model import ChatCompletionsClient
from loopblox.runtime.io import atomic_json, atomic_text, digest, image_id


BASELINE_CONTROLLER = ROOT / "controllers" / "reactive.py"


def model_settings(client):
    return {key: getattr(client, key) for key in ("model", "base_url", "temperature", "max_tokens", "timeout")}


def comparison_plan(candidates, tasks, repeats=1):
    """Preallocate paired runs, rotating candidates by task index plus repeat."""
    names = list(candidates)
    rows = []
    for repeat in range(repeats):
        for index, task in enumerate(tasks):
            offset = (index + repeat) % len(names)
            for name in names[offset:] + names[:offset]:
                rows.append(dict(candidate=name, family=task["family"], task_id=task["task_id"],
                    repeat=repeat, directory=f"comparison/{name}/{task['task_id']}/repeat-{repeat:02d}",
                    status="not_started"))
    return rows


def run_study(args, *, load_suite, runner_factory, include_mixed=False, extra_setup=None):
    original_suite = Path(args.suite).resolve()
    manifest = load_suite(original_suite)
    families = list(dict.fromkeys(task["family"] for task in manifest["tasks"]))
    if not families or any(not any(task["family"] == family and task["split"] == split
                                  for task in manifest["tasks"])
                           for family in families for split in ("development", "holdout")):
        raise ValueError("A study requires development and holdout tasks in every family")
    worker = image_id(args.worker_image)
    client = ChatCompletionsClient.from_env()
    limits = Limits(seconds=args.task_seconds, actions=args.task_actions,
                    model_calls=args.task_model_calls, output_tokens=args.task_output_tokens)
    experiment = validate_experiment(json.loads(Path(args.experiment).read_text()))
    baseline = BASELINE_CONTROLLER.read_text()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    private = output / "private"
    shutil.copytree(original_suite, private / "suite")
    runner = runner_factory(private / "suite", manifest, client, worker, limits, private)
    setup = dict(model=model_settings(client), environment_manifest=manifest, task_limits=vars(limits),
                 experiment=experiment, repeats=1, **(extra_setup or {}),
                 design="All researchers close and freeze their selections before any holdout evaluation. "
                        "Baseline and every selected Loop run on identical held-out tasks with identical task limits. "
                        "The complete comparison matrix is preallocated; candidate order rotates by task index. "
                        "Episode final results and usage are views of this single comparison, not additional runs or costs. "
                        + ("Mixed-domain search has the sum of the per-domain search budgets and development-run allowances."
                           if include_mixed else "Independent per-family searches use equal research budgets."))
    atomic_json(private / "setup.json", setup)
    snapshot_implementation(private)
    atomic_text(output / "controllers/baseline.py", baseline)
    state = dict(status="researching", title=f"Reusable Loop search · {manifest['environment']}",
                 families=families, setup=setup, episodes={}, comparisons=[],
                 candidates={"baseline": dict(source="controllers/baseline.py", sha256=digest(baseline.encode()))})
    atomic_json(output / "result.json", state)
    sessions = {}
    meter = None

    def save():
        # The study's rows and ledger own holdout facts. Episode files are derived
        # views, including unstarted rows and charges from interrupted attempts.
        for condition, session in sessions.items():
            rows = [row for row in state["comparisons"]
                    if row["candidate"] == "selected-" + condition and row["task_id"] in session.holdout]
            scopes = {row["scope"] for row in rows}
            result = dict(status=session.state["status"],
                selected_candidate=session.state.get("frozen_candidate"),
                selection_reason=session.state.get("selection_reason"),
                research_status=session.state.get("research_status", session.state["status"]),
                experiment=session.experiment, component_proposals=list(session.state["proposals"]),
                research_usage=session.meter.summary() if hasattr(session, "meter") else model_usage([]),
                development_task_runs=session.state["task_runs_used"],
                final_runs=[{**row, "directory": "../../" + row["directory"]} for row in rows],
                final_summary=summarize(rows),
                final_usage=model_usage([call for call in meter.calls
                                         if call["scope"].partition(":")[0] in scopes] if meter else []),
                final_results_source="../../result.json", final_usage_source="../../private/comparison-usage.json")
            atomic_json(session.output / "result.json", result)
            state["episodes"][condition] = dict(path=f"episodes/{condition}/result.json", result=result)
        if meter is not None:
            state["comparison_usage"] = meter.summary()
        atomic_json(output / "result.json", state)

    try:
        conditions = families + (["mixed"] if include_mixed else [])
        for index, condition in enumerate(conditions):
            mixed = condition == "mixed"
            tasks = [task for task in manifest["tasks"] if mixed or task["family"] == condition]
            splits = {split: tuple(task["task_id"] for task in tasks if task["split"] == split)
                      for split in ("development", "holdout")}
            factor = len(families) if mixed else 1
            session = ResearchSession(
                output=output / "episodes" / condition, development=splits["development"], holdout=splits["holdout"],
                run_task=runner, research_client=client, worker_image=worker,
                setup={"study_setup": "../../private/setup.json", "model": model_settings(client),
                       "search_condition": condition, "budget_factor": factor},
                experiment={**experiment, "question": experiment["question"] + f" Search condition: {condition}."},
                baseline_source=baseline, max_task_runs=args.development_runs * factor,
                research_seconds=args.research_seconds * factor,
                research_output_tokens=args.research_output_tokens * factor,
                research_model_calls=args.research_model_calls * factor, task_limits=limits, seed=args.seed + index,
            )
            sessions[condition] = session
            print("Searching reusable Loop: " + condition, flush=True)
            session.research()
            source = (session.output / "selected-controller.py").read_text()
            candidate, path = "selected-" + condition, f"controllers/selected-{condition}.py"
            atomic_text(output / path, source)
            state["candidates"][candidate] = dict(source=path, sha256=digest(source.encode()), condition=condition)
            save()
        sources = {name: (output / candidate["source"]).read_text() for name, candidate in state["candidates"].items()}
        state["comparisons"] = comparison_plan(sources, [task for task in manifest["tasks"] if task["split"] == "holdout"])
        for index, row in enumerate(state["comparisons"]):
            row["scope"] = f"comparison-{index}"
        state["status"] = "comparing"
        for session in sessions.values():
            session.state["status"] = "final_evaluation"
            session.save()
        save()
        count = len(state["comparisons"])
        meter = ModelMeter(private / "comparison-usage.json", seconds=limits.seconds * count,
                           model_calls=limits.model_calls * count, output_tokens=limits.output_tokens * count)
        for row in state["comparisons"]:
            row["status"] = "running"
            save()
            print(f"Holdout: {row['candidate']} / {row['task_id']}", flush=True)
            started = time.monotonic()
            try:
                row.update(runner(task_id=row["task_id"], source=sources[row["candidate"]], scope=row["scope"],
                                  directory=output / row["directory"], meter=meter, exposed=experiment["exposed"]))
            except Exception as error:
                row.update(status="host_fault", stop_reason=str(error), verification_verdict=None)
            except BaseException:
                row.update(status="interrupted", stop_reason="host_interrupted", verification_verdict=None)
                raise
            finally:
                row.setdefault("elapsed_seconds", time.monotonic() - started)
                save()
            if row["status"] in {"host_fault", "operational_failure", "verifier_failure"}:
                raise RuntimeError("Comparison failed: " + row["status"])
        state["status"] = "complete"
    except BaseException:
        state["status"] = "interrupted"
        raise
    finally:
        for session in sessions.values():
            if session.state["status"] == "final_evaluation":
                session.state["status"] = state["status"]
                session.save()
        save()
        write_report(output)
    return state


def write_report(output):
    output = Path(output)
    state = json.loads((output / "result.json").read_text())
    rows, families = state["comparisons"], state["families"]

    def link(path, text):
        return f'<a href="{escape(path, quote=True)}">{escape(text)}</a>'

    def tokens(items, key):
        values = [row.get("usage", {}).get(key) for row in items]
        return str(sum(values)) if values and all(value is not None for value in values) else "unknown"

    matrix = []
    for candidate, metadata in state["candidates"].items():
        cells = []
        for family in families:
            items = [row for row in rows if row["candidate"] == candidate and row["family"] == family]
            summary = summarize(items)
            calls = sum(row.get("usage", {}).get("model_calls", 0) for row in items)
            seconds = sum(row.get("elapsed_seconds", 0) for row in items)
            cells.append(f'<td><strong>{summary["resolved"]}/{len(items)}</strong> passed'
                         f'<br>{calls} model calls · {seconds:.1f}s'
                         f'<br>{tokens(items, "model_input_tokens")} input / {tokens(items, "model_output_tokens")} output tokens'
                         f'<br>{summary["unscored"]} unscored · {len(items) - summary["attempted"]} not started</td>')
        same = ("<br><small>Same source as baseline; separate task runs.</small>"
                if candidate != "baseline" and metadata["sha256"] == state["candidates"]["baseline"]["sha256"] else "")
        matrix.append(f'<tr><th>{link(metadata["source"], candidate)}{same}</th>{"".join(cells)}</tr>')

    baseline = (output / state["candidates"]["baseline"]["source"]).read_text()
    details = []
    for candidate, metadata in state["candidates"].items():
        source = (output / metadata["source"]).read_text()
        diff = "".join(difflib.unified_diff(baseline.splitlines(True), source.splitlines(True),
                                           fromfile="baseline.py", tofile=candidate + ".py"))
        details.append(f'<details><summary>{escape(candidate)} — source and change</summary>'
                       f'<p>SHA-256: <code>{metadata["sha256"]}</code></p>'
                       f'<pre>{escape(diff or "Identical to the starting baseline.")}</pre>'
                       f'<details><summary>Complete reusable controller</summary><pre>{escape(source)}</pre></details></details>')

    paired = []
    controls = ["baseline"] + [name for name in ("control", "selected-mixed") if name in state["candidates"]]
    for control in controls:
        for candidate in state["candidates"]:
            if candidate == control or candidate == "baseline":
                continue
            for family in families:
                base = {(row["task_id"], row.get("repeat", 0)): row for row in rows
                        if row["candidate"] == control and row["family"] == family}
                counts = dict(candidate_only=0, control_only=0, both_pass=0, both_fail=0, unscored=0)
                for row in (row for row in rows if row["candidate"] == candidate and row["family"] == family):
                    a = row.get("verification_verdict")
                    b = base.get((row["task_id"], row.get("repeat", 0)), {}).get("verification_verdict")
                    key = ("unscored" if a not in {"pass", "fail"} or b not in {"pass", "fail"} else
                           "both_pass" if a == b == "pass" else "both_fail" if a == b == "fail" else
                           "candidate_only" if a == "pass" else "control_only")
                    counts[key] += 1
                paired.append(f'<tr><th>{escape(candidate)} vs {escape(control)} / {escape(family)}</th>'
                              + "".join(f"<td>{value}</td>" for value in counts.values()) + "</tr>")

    runs = []
    for row in rows:
        path = row["directory"]
        report = link(path + "/trace.html", "Trace") if (output / path / "trace.html").exists() else "—"
        verification = link(path + "/verification.json", "Score") if (output / path / "verification.json").exists() else "—"
        label = row["task_id"] + (f' · repeat {row["repeat"] + 1}' if "repeat" in row else "")
        runs.append(f'<tr><td>{escape(row["candidate"])}</td><td>{escape(label)}</td>'
                    f'<td>{escape(row["status"])}</td><td>{escape(str(row.get("verification_verdict")))}</td>'
                    f'<td>{report} · {verification}</td></tr>')
    searches = []
    for family, episode in state["episodes"].items():
        result = episode["result"]
        usage = result["research_usage"]
        searches.append(f'<li>{escape(family)}: {result["development_task_runs"]} development runs; '
                        f'{usage["model_calls"]} research + development model calls; '
                        f'{usage["model_input_tokens"]} input / {usage["model_output_tokens"]} output tokens; '
                        f'research status: {escape(result["research_status"])}; '
                        f'{link(episode["path"], "episode result")}, '
                        f'{link("episodes/" + family + "/private/setup.json", "frozen settings")}, '
                        f'{link("episodes/" + family + "/private/research-trace.html", "research trace") if (output / "episodes" / family / "private/research-trace.html").exists() else "research trace not produced"}</li>')
    document = f'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>LoopBlox · Loop experiment</title>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<style>body{{font:16px/1.55 system-ui,sans-serif;max-width:1200px;margin:40px auto;padding:0 24px;color:#202c38;background:#f7f9fc}}
h1,h2{{line-height:1.2}}a{{color:#155da8}}table{{border-collapse:collapse;width:100%;background:white;margin:20px 0}}
th,td{{padding:12px;text-align:left;border:1px solid #d9e1eb;vertical-align:top}}th{{background:#edf2f8}}
details{{background:white;border:1px solid #d9e1eb;padding:14px;margin:10px 0}}summary{{cursor:pointer;font-weight:600}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}}code{{overflow-wrap:anywhere}}.note{{border-left:4px solid #5994c7;padding:10px 18px;background:#edf4fc}}</style>
<h1>{escape(state.get("title", "Reusable Loop comparison"))}</h1>
<p>Status: <strong>{escape(state["status"])}</strong> · Model: {escape(state["setup"]["model"]["model"])} · {link("result.json", "All recorded results")}</p>
<p class="note">{escape(state["setup"]["design"])}
This run is a pilot; differences do not establish a universally best Loop or a causal component effect. Identical-source comparisons measure run variability, not composition gains. Search cost is separate from task execution cost. Task model usage includes the simulated user when present; controller traces show agent calls.
Unknown token usage stays unknown; token counts are not dollar prices.</p>
<h2>Task performance and execution cost</h2>
<table><tr><th>Reusable controller</th>{"".join(f"<th>{escape(family)}</th>" for family in families)}</tr>{"".join(matrix)}</table>
<h2>Paired outcomes against the controls</h2>
<table><tr><th>Controller / task family</th><th>Candidate only passes</th><th>Control only passes</th><th>Both pass</th><th>Both fail</th><th>Unscored</th></tr>{"".join(paired)}</table>
<h2>What changed</h2>{"".join(details)}
<h2>Actual task runs</h2><table><tr><th>Controller</th><th>Task</th><th>Execution status</th><th>Verification</th><th>Evidence</th></tr>{"".join(runs)}</table>
<h2>Search records</h2><ul>{"".join(searches)}</ul>
<details><summary>Frozen conditions and feedback boundary</summary><pre>{escape(json.dumps(state["setup"], indent=2, ensure_ascii=False))}</pre></details>
</html>'''
    atomic_text(output / "report.html", document)
