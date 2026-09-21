"""Continuous research on one frozen task set, with host-owned selection and checkpoints."""

from __future__ import annotations

import copy
import json
import time
import shutil
from pathlib import Path

from loopblox import ROOT, snapshot_implementation
from loopblox.analysis import jev
from loopblox.research.codex import default_researcher
from loopblox.research.workspace import ResearchWorkspace, configuration as workspace_configuration
from loopblox.runtime.components import catalog, object_schema, render_contracts, validate
from loopblox.runtime.controller import Limits, MAX_SOURCE_BYTES, ModelMeter
from loopblox.runtime.model import BudgetExhausted, HostFault, OperationalProblem, Tool, ToolResult
from loopblox.runtime.io import atomic_json, atomic_text, digest
from loopblox.report import summarize_trace



API_GUIDE = ROOT / "CONTROLLER.md"
RANKING_RULE = "Official passes descending; agent input tokens ascending; agent model calls ascending; retain incumbent on ties. Unknown usage sorts after known usage. Only fully scored and analyzed batches qualify."
CANDIDATE_SCHEMA = object_schema({
    "source": {"type": "string", "description": "Complete Python source defining run(env)."},
    "rationale": {"type": "string", "description":
        "Briefly state the evidence or untested hypothesis, the change, expected outcome, and how to test it. "
        "Cite the development records and candidate IDs you used. "
        "Distinguish observations from conjecture. "
        "Nonempty, at most 16000 characters. This is research documentation, not a task-agent instruction."},
})
PROPOSAL_SCHEMA = object_schema({key: {"type": "string"} for key in (
    "name", "purpose", "inputs", "outputs", "behavior", "why_existing_insufficient",
    "example_composition", "implementation",
)}, ["name", "purpose", "inputs", "outputs", "behavior", "why_existing_insufficient", "example_composition"])
PROPOSAL_SCHEMA["properties"]["purpose"]["description"] = "State the behavior's scope and Harness surfaces."
PROPOSAL_SCHEMA["properties"]["behavior"]["description"] = (
    "Describe model/tool calls, state effects, return and failure conditions, fixed internals and allowed options. "
    "Separate the component's behavior from its caller's trigger and continuation policy."
)


def validate_experiment(experiment):
    if (not isinstance(experiment, dict) or set(experiment) != {"question", "exposed"}
            or not isinstance(experiment["question"], str) or not experiment["question"].strip()):
        raise ValueError("Experiment requires a question and an exposed composition boundary")
    catalog(experiment["exposed"])
    return copy.deepcopy(experiment)


def summarize(rows):
    attempted = [row for row in rows if row["status"] != "not_started"]
    verdicts = [row.get("verification_verdict") for row in attempted]
    return dict(
        attempted=len(attempted),
        resolved=verdicts.count("pass"),
        unresolved=verdicts.count("fail"),
        unscored=verdicts.count(None),
        statuses={status: sum(row["status"] == status for row in attempted)
                  for status in sorted({row["status"] for row in attempted})},
    )


def summarize_evaluation(evaluation):
    rows = evaluation["runs"]
    cost_keys = ("model_calls", "model_input_tokens", "model_output_tokens", "charged_output_tokens")
    candidates = {}
    for candidate_id in evaluation["candidate_ids"]:
        selected = [row for row in rows if row["candidate_id"] == candidate_id]
        attempted = [row for row in selected if row["status"] != "not_started"]
        usage = {}
        for key in cost_keys:
            values = [row.get("usage", {}).get(key) for row in attempted]
            usage[key] = sum(values) if all(value is not None for value in values) else None
        candidates[candidate_id] = dict(
            **summarize(selected), usage=usage,
            distinct_tasks=len({row["task_id"] for row in attempted}))
    control = evaluation["candidate_ids"][0]
    indexed = {(row["candidate_id"], row["draw"], row["repeat"]): row for row in rows}
    comparisons = {}
    for candidate_id in evaluation["candidate_ids"][1:]:
        pairs = []
        for row in rows:
            if row["candidate_id"] != candidate_id:
                continue
            base = indexed[control, row["draw"], row["repeat"]]
            a, b = base.get("verification_verdict"), row.get("verification_verdict")
            outcome = ("unscored" if a not in {"pass", "fail"} or b not in {"pass", "fail"} else
                       "both_pass" if a == b == "pass" else "both_fail" if a == b == "fail" else
                       "candidate_only_pass" if b == "pass" else "control_only_pass")
            delta = {}
            for key in cost_keys:
                x, y = base.get("usage", {}).get(key), row.get("usage", {}).get(key)
                delta[key] = y - x if x is not None and y is not None else None
            pairs.append(dict(draw=row["draw"], repeat=row["repeat"], task_id=row["task_id"],
                              outcome=outcome, cost_delta=delta,
                              control_verdict=a, candidate_verdict=b,
                              control_directory=base["directory"], candidate_directory=row["directory"]))
        comparisons[candidate_id] = dict(control=control, pairs=pairs,
            outcomes={key: sum(pair["outcome"] == key for pair in pairs) for key in (
                "both_pass", "both_fail", "candidate_only_pass", "control_only_pass", "unscored")})
    return dict(candidates=candidates, comparisons=comparisons,
                interpretation="Pairing uses host draw and repeat, with fresh environments and workers. "
                               "Outcomes use official verdicts; missing scores remain unscored. "
                               "Repeated draws/runs are not independent scenario groups. "
                               "Same task seed does not guarantee identical model or simulated-user responses.")


def research_evidence(state, *, episode):
    """Derive cross-evaluation facts; researcher prose never owns the counts."""
    candidates = {}
    for candidate_id in state["candidates"]:
        evaluations = [e for e in state["evaluations"] if candidate_id in e["candidate_ids"]]
        rows = [row for e in evaluations for row in e["runs"] if row["candidate_id"] == candidate_id]
        summary = summarize_evaluation(dict(candidate_ids=[candidate_id], runs=rows))["candidates"][candidate_id]
        reference = f"{episode}/{candidate_id}"
        candidates[reference] = dict(
            **summary, source=f"candidates/{candidate_id}.py", rationale=f"candidates/{candidate_id}.json",
            evaluations=[f"evaluations/{e['evaluation_id']}/result.json" for e in evaluations],
            jev_evidence=[row["jev"]["artifact"] for row in rows if row.get("jev")],
            failure_summaries=[row["trace_summary"] for row in rows if row.get("trace_summary")
                               and (row.get("verification_verdict") == "fail"
                                    or row["status"] not in {"completed", "not_started", "running"})])
    return dict(episode=episode, candidates=candidates, task_runs_used=state["task_runs_used"],
                interpretation="Host-derived totals across fixed-task evaluations; incomplete batches remain visible. "
                               "task_runs_used counts this episode's dispatches. "
                               "Use each evaluation's paired comparisons for comparisons. Rationale and notes are "
                               "researcher claims, not verified causes. Unstarted runs are not failed attempts. "
                               "Missing official scores remain unscored.")


class ResearchSession:
    def __init__(self, *, output: Path, development: tuple[str, ...],
                 run_task, worker_image: str, setup: dict,
                 experiment: dict, baseline_source: str,
                 task_limits: Limits, check_stop=lambda: None):
        if not development or len(set(development)) != len(development):
            raise ValueError("Development tasks must be nonempty and unique")
        self.jev_configuration = jev.configuration()
        self.experiment = validate_experiment(experiment)
        exposed_catalog = catalog(self.experiment["exposed"])
        self.api_guide = API_GUIDE.read_text()
        self.output = output.resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        self.public = self.output / "public"
        self.private = self.output / "private"
        self.public.mkdir()
        self.private.mkdir()
        (self.public / "candidates").mkdir()
        (self.public / "evaluations").mkdir()
        (self.public / "proposals").mkdir()
        self.development = development
        self.check_stop = check_stop
        self.task_selection = (
            "Every new candidate runs once on the entire fixed development list, in its frozen order. "
            "Existing sources reuse their recorded results. Task IDs: " + ", ".join(development) + "."
        )
        self.run_task, self.image = run_task, worker_image
        self.workspace = ResearchWorkspace(self.public, self.private, self.image)
        self.task_limits = task_limits
        self.prior_accounting = setup.get("prior_accounting", {})
        self.budgets = dict(seconds=None, output_tokens=None, model_calls=None)
        self.state = dict(status="prepared", candidates=[], evaluations=[], proposals=[], selected=None,
                          task_runs_used=0, iterations=[], pending_candidates=[])
        atomic_json(self.private / "setup.json", {
            **setup, "development": development,
            "sampling": self.task_selection,
            "research_budgets": {**self.budgets, "task_runs": None},
            "task_limits": vars(task_limits), "worker_image": worker_image, "components": catalog(),
            "experiment": self.experiment, "jev": self.jev_configuration,
            "research_workspace": workspace_configuration(),
        })
        atomic_json(self.public / "experiment.json", self.experiment)
        atomic_json(self.public / "jev-config.json", self.jev_configuration)
        atomic_json(self.public / "research-workspace.json", workspace_configuration())
        atomic_text(self.public / "jev-guide.md", (ROOT / "docs/jev.md").read_text())
        atomic_json(self.public / "components.json", exposed_catalog)
        atomic_text(self.public / "component-contracts.md", render_contracts(exposed_catalog))
        atomic_text(self.public / "controller-api.md", self.api_guide)
        atomic_text(self.public / "experiment.md", (ROOT / "experiment.md").read_text())
        atomic_text(self.public / "loop.md", (ROOT / "loop.md").read_text())
        examples = self.public / "examples"
        examples.mkdir()
        example_sources = sorted(path for path in (ROOT / "controllers").glob("*.py")
                                 if path.read_text() != baseline_source)
        for path in example_sources:
            atomic_text(examples / path.name, path.read_text())
        atomic_text(examples / "index.md",
                    "# Optional Loop examples\n\n"
                    "Exact source snapshots for API usage, not a recommended search sequence. "
                    "An example is usable only if experiment.json exposes every component and option it calls.\n\n"
                    + "\n".join(f"- [{path.name}]({path.name})" for path in example_sources) + "\n")
        snapshot_implementation(self.private)
        initial = self.save_candidate({
            "source": baseline_source,
            "rationale": "Host-supplied baseline, without researcher changes. Establish reference success and cost; "
                         "no performance advantage is assumed. Run the initial development trial, then use it "
                         "in shared-task comparisons with alternatives.",
        }, 0)["candidate_id"]
        self.baseline_candidate = initial
        self.save()

    def save(self):
        atomic_json(self.private / "state.json", self.state)
        atomic_json(self.public / "progress.json", dict(status=self.state["status"],
            incumbent=self.state["selected"], completed_iterations=len(self.state["iterations"]),
            pending_candidates=self.state["pending_candidates"], ranking_rule=RANKING_RULE,
            task_runs_this_attempt=self.state["task_runs_used"]))

    @staticmethod
    def reject(message):
        raise OperationalProblem(message, code="invalid_research_request", effects="none")

    def source(self, candidate_id):
        if candidate_id not in self.state["candidates"]:
            self.reject("Unknown candidate ID")
        return (self.public / "candidates" / f"{candidate_id}.py").read_text()

    def save_candidate(self, arguments, _timeout):
        try:
            validate(arguments, CANDIDATE_SCHEMA)
        except ValueError as error:
            self.reject(f"Invalid candidate: {error}")
        source, rationale = arguments["source"], arguments["rationale"]
        source_bytes = source.encode()
        if not source.strip() or len(source_bytes) > MAX_SOURCE_BYTES:
            self.reject("Provide a nonempty Python source file of at most 128 KiB")
        if not rationale.strip() or len(rationale) > 16000:
            self.reject("Provide a nonempty candidate rationale of at most 16000 characters")
        try:
            compile(source, "controller.py", "exec")
        except (SyntaxError, ValueError) as error:
            self.reject(f"Controller does not compile: {error}")
        for candidate_id in self.state["candidates"]:
            if (self.public / "candidates" / f"{candidate_id}.py").read_bytes() == source_bytes:
                return dict(candidate_id=candidate_id, path=f"candidates/{candidate_id}.py",
                            rationale_path=f"candidates/{candidate_id}.json", created=False)
        if hasattr(self, "baseline_candidate") and len(self.state["pending_candidates"]) >= 2:
            self.reject("At most two new candidates per iteration. Evaluate and checkpoint this iteration first.")
        candidate_id = f"c{len(self.state['candidates']):04d}"
        path = self.public / "candidates" / f"{candidate_id}.py"
        atomic_text(path, source)
        rationale_path = path.with_suffix(".json")
        atomic_json(rationale_path, dict(rationale=rationale, source_sha256=digest(source_bytes)))
        self.state["candidates"].append(candidate_id)
        if hasattr(self, "baseline_candidate"):
            self.state["pending_candidates"].append(candidate_id)
        self.save()
        return dict(candidate_id=candidate_id, path=str(path.relative_to(self.public)),
                    rationale_path=str(rationale_path.relative_to(self.public)), created=True)

    def read_artifact(self, arguments, _timeout):
        public = self.public
        raw = arguments.get("path")
        if not isinstance(raw, str) or Path(raw).is_absolute():
            self.reject("path must be relative to the public artifact directory")
        path = (public / raw).resolve()
        if not path.is_relative_to(public):
            self.reject("No readable public artifact at this path")
        canonical = str(path.relative_to(public))
        start = arguments.get("start", 0)
        limit = arguments.get("limit", 32000)
        if type(start) is not int or start < 0 or type(limit) is not int or not 1 <= limit <= 128000:
            self.reject("start must be nonnegative and limit must be between 1 and 128000")
        if path.is_file():
            text = path.read_text()
        else:
            directory = path
            while not directory.is_dir():
                directory = directory.parent
            entries = [str(entry.relative_to(public)) + ("/" if entry.is_dir() else "")
                       for entry in sorted(directory.iterdir())
                       if entry.resolve().is_relative_to(public) and (entry.is_file() or entry.is_dir())]
            if not path.is_dir():
                return ToolResult("failed", dict(code="artifact_not_found", path=canonical,
                    message="This artifact does not exist. Use a listed path or read its directory; "
                            "repeating this missing-file request will not recover it.",
                    directory=str(directory.relative_to(public)), available_paths=entries), "none")
            text = json.dumps(dict(entries=entries), ensure_ascii=False, indent=2)
        return dict(path=canonical, text=text[start:start + limit], total_characters=len(text),
                    next_start=start + limit if start + limit < len(text) else None)

    def write_notes(self, arguments, _timeout):
        text = arguments.get("text")
        if not isinstance(text, str) or len(text) > 128000:
            self.reject("Notes must be text of at most 128000 characters")
        atomic_text(self.public / "notes.md", text)
        return {"path": "notes.md"}

    def propose_component(self, arguments, _timeout):
        try:
            validate(arguments, PROPOSAL_SCHEMA)
        except ValueError as error:
            self.reject(f"Invalid component proposal: {error}")
        if any(not text.strip() for text in arguments.values()) or len(json.dumps(arguments).encode()) > MAX_SOURCE_BYTES:
            self.reject("Proposal fields must be nonempty; the complete proposal must fit within 128 KiB")
        proposal_id = f"p{len(self.state['proposals']):04d}"
        path = f"proposals/{proposal_id}.json"
        atomic_json(self.public / path, dict(proposal_id=proposal_id, status="proposed", **arguments))
        self.state["proposals"].append(proposal_id)
        self.save()
        return dict(proposal_id=proposal_id, status="proposed", path=path,
                    message="Stored for human review; unavailable to controllers until approved in a new episode.")

    def evaluate(self, arguments, _timeout):
        candidate_ids = arguments.get("candidate_ids")
        if (not isinstance(candidate_ids, list) or not candidate_ids
                or any(not isinstance(item, str) for item in candidate_ids)
                or len(set(candidate_ids)) != len(candidate_ids)):
            self.reject("candidate_ids must be a nonempty list of unique candidate IDs")
        sources = {cid: self.source(cid) for cid in candidate_ids}
        evaluated = {cid for batch in self.state["evaluations"] for cid in batch["candidate_ids"]}
        if any(cid in evaluated for cid in candidate_ids):
            self.reject("This source already has an evaluation. Read its recorded results instead of rerunning it.")
        allowed = self.state["pending_candidates"] if self.state["evaluations"] else [self.baseline_candidate]
        if any(cid not in allowed for cid in candidate_ids):
            self.reject("Only this iteration's new candidates may be evaluated")
        evaluation_id = f"e{len(self.state['evaluations']):04d}"
        directory = self.public / "evaluations" / evaluation_id
        directory.mkdir()
        for cid, source in sources.items():
            atomic_text(directory / "sources" / f"{cid}.py", source)
        rows = []
        for draw, task_id in enumerate(self.development):
            offset = draw % len(candidate_ids)
            for cid in candidate_ids[offset:] + candidate_ids[:offset]:
                rows.append(dict(candidate_id=cid, task_id=task_id, draw=draw, repeat=0,
                                 directory=f"run-{len(rows):04d}", status="not_started"))
        evaluation = dict(evaluation_id=evaluation_id, candidate_ids=list(candidate_ids),
                          sources={key: dict(path=f"sources/{key}.py", sha256=digest(value.encode()))
                                   for key, value in sources.items()},
                          sampled_tasks=list(self.development), repeats=1, requested_runs=len(rows),
                          status="running", runs=rows)
        self.state["evaluations"].append(evaluation)
        self.save()
        feedback = self.run_evaluation(evaluation)
        self.update_selection()
        return dict(**feedback, incumbent=self.state["selected"], ranking=self.ranking(),
                    pending_candidates=self.state["pending_candidates"], next_action="checkpoint after evaluating all saved candidates")

    def run_evaluation(self, evaluation):
        """Dispatch only unstarted rows of a host-frozen evaluation plan."""
        evaluation_id, rows = evaluation["evaluation_id"], evaluation["runs"]
        candidate_ids = evaluation["candidate_ids"]
        directory = self.public / "evaluations" / evaluation_id
        sources = {}
        for candidate_id, snapshot in evaluation["sources"].items():
            source = (directory / snapshot["path"]).read_text()
            if digest(source.encode()) != snapshot["sha256"] or source != self.source(candidate_id):
                raise HostFault("Frozen evaluation source changed: " + candidate_id)
            sources[candidate_id] = source
        result_path = directory / "result.json"
        evaluation["status"] = "running"
        atomic_json(result_path, evaluation)
        try:
            for index, row in enumerate(rows):
                if row["status"] != "not_started":
                    continue
                self.check_stop()
                self.state["task_runs_used"] += 1
                row["status"] = "running"
                self.save()
                atomic_json(result_path, evaluation)
                started = time.monotonic()
                try:
                    row.update(self.run_task(
                        task_id=row["task_id"], source=sources[row["candidate_id"]], scope=f"{evaluation_id}-{index}",
                        directory=directory / row["directory"], meter=self.meter,
                        exposed=copy.deepcopy(self.experiment["exposed"]),
                    ))
                except Exception as error:
                    row.update(status="host_fault", stop_reason=str(error), verification_verdict=None)
                except BaseException:
                    row.update(status="interrupted", stop_reason="host_interrupted", verification_verdict=None)
                    raise
                finally:
                    row["elapsed_seconds"] = time.monotonic() - started
                    self.save()
                    atomic_json(result_path, evaluation)
                if row["status"] in {"host_fault", "operational_failure", "verifier_failure"}:
                    self.state["research_status"] = row["status"]
                    # HostFault propagates through the research tool gateway, ending
                    # the worker before it can submit or execute another batched action.
                    raise HostFault(f"Development evaluation {evaluation_id}/{row['directory']} failed: {row['status']}")
                trace = directory / row["directory"] / "trace.json"
                semantic = trace.with_name("jev.json")
                try:
                    jev.analyze_run(trace, configuration=self.jev_configuration, meter=self.meter,
                                    scope=f"{evaluation_id}-{index}")
                except BudgetExhausted:
                    self.state["research_status"] = "budget_exhausted"
                    raise
                except Exception as error:
                    self.state["research_status"] = "operational_failure"
                    raise HostFault(f"Jev analysis failed for {evaluation_id}/{row['directory']}: {error}") from error
                finally:
                    if semantic.is_file():
                        row["jev"] = jev.feedback(json.loads(semantic.read_text()),
                                                  str(semantic.relative_to(self.public)), json.loads(trace.read_text()))
                    self.save()
                    atomic_json(result_path, evaluation)
            if any(row.get("verification_verdict") not in {"pass", "fail"} for row in rows):
                self.state["research_status"] = "incomplete_evaluation"
                raise HostFault("The complete task batch requires official scores; missing scores are not failures")
            evaluation["feedback_ready"] = True
        finally:
            # Derive evidence only from the public controller trace, never private environment ledgers.
            for row in rows:
                trace = directory / row["directory"] / "trace.json"
                if trace.is_file():
                    evidence = trace.with_name("summary.json")
                    atomic_json(evidence, summarize_trace(json.loads(trace.read_text())))
                    row["trace_summary"] = str(evidence.relative_to(self.public))
            evaluation.update(status="completed" if evaluation.get("feedback_ready") else "interrupted",
                              summary=summarize_evaluation(evaluation))
            self.save()
            atomic_json(result_path, evaluation)
            atomic_json(self.public / "evidence.json", research_evidence(self.state, episode=self.output.name))
        return dict(
            evaluation_id=evaluation_id, candidate_ids=candidate_ids,
            summary=dict(candidates=evaluation["summary"]["candidates"],
                         comparisons={candidate: {key: comparison[key] for key in ("control", "outcomes")}
                                      for candidate, comparison in evaluation["summary"]["comparisons"].items()}),
            jev=jev.overview([row["jev"] for row in rows if row.get("jev")]),
            artifact=f"evaluations/{evaluation_id}/result.json",
            research_usage=self.meter.summary(),
            evidence_path="evidence.json",
        )

    def ranking(self):
        """Only complete, scored and analyzed fixed batches can compete."""
        ranked = []
        for batch in self.state["evaluations"]:
            if not batch.get("feedback_ready"):
                continue
            for cid in batch["candidate_ids"]:
                rows = [row for row in batch["runs"] if row["candidate_id"] == cid]
                costs = {}
                for key in ("model_input_tokens", "model_calls"):
                    values = [row.get("agent_usage", {}).get(key) for row in rows]
                    costs[key] = sum(values) if all(value is not None for value in values) else None
                ranked.append(dict(candidate_id=cid, passed=sum(row["verification_verdict"] == "pass" for row in rows),
                                   tasks=len(rows), agent_usage=costs))
        ranked.sort(key=lambda row: (-row["passed"],
            *(row["agent_usage"][key] if row["agent_usage"][key] is not None else float("inf")
              for key in ("model_input_tokens", "model_calls")),
            row["candidate_id"] != self.state["selected"], self.state["candidates"].index(row["candidate_id"])))
        return ranked

    def update_selection(self):
        ranked = self.ranking()
        self.state["selected"] = ranked[0]["candidate_id"] if ranked else None
        if self.state["selected"]:
            atomic_text(self.output / "selected-controller.py", self.source(self.state["selected"]))
        self.save()

    def checkpoint(self, arguments, _timeout):
        notes = arguments.get("notes")
        if not isinstance(notes, str) or not notes.strip() or len(notes) > 128000:
            self.reject("Provide notes with hypothesis, evidence, failed approaches and next direction (1..128000 characters)")
        pending = self.state["pending_candidates"]
        scored = {row["candidate_id"] for row in self.ranking()}
        if not pending or any(cid not in scored for cid in pending):
            self.reject("A checkpoint requires one or two new candidates with complete scored and analyzed batches")
        self.update_selection()
        index = len(self.state["iterations"]) + 1
        current_usage = self.meter.summary()
        prior_usage = self.prior_accounting.get("usage", {})
        cumulative_usage = {key: value + prior_usage.get(key, 0)
                            if value is not None and prior_usage.get(key, 0) is not None else None
                            for key, value in current_usage.items()}
        record = dict(iteration=index, candidate_ids=list(pending), incumbent=self.state["selected"],
                      previous_incumbent=(self.state["iterations"][-1]["incumbent"]
                                          if self.state["iterations"] else self.baseline_candidate),
                      ranking=self.ranking(), notes=notes, task_runs_used=self.state["task_runs_used"],
                      research_usage=current_usage, cumulative_usage=cumulative_usage,
                      cumulative_task_runs=self.prior_accounting.get("task_runs", 0) + self.state["task_runs_used"],
                      cumulative_charged_seconds=self.prior_accounting.get("charged_seconds", 0) + max(0,
                          time.monotonic() - self.meter.started - self.meter.timeout_wait_seconds))
        atomic_json(self.public / "checkpoints" / f"iteration-{index:04d}.json", record)
        atomic_text(self.public / "notes.md", notes)
        self.state["iterations"].append(record)
        self.state["pending_candidates"] = []
        self.save()
        return dict(iteration=index, incumbent=self.state["selected"],
                    checkpoint=f"checkpoints/iteration-{index:04d}.json", continue_research=True)

    def restore(self, previous):
        """Recover complete batches, restarting only unfinished evaluations with fresh workers."""
        previous = Path(previous)
        old = json.loads((previous / "private/state.json").read_text())
        complete = [batch for batch in old["evaluations"] if batch.get("feedback_ready")]
        self.recovery_batches = [batch["candidate_ids"] for batch in old["evaluations"] if not batch.get("feedback_ready")]
        # Reuse all immutable sources, but never expose incomplete batch traces as experience.
        paths = [f"candidates/{cid}{suffix}" for cid in old["candidates"] for suffix in (".py", ".json")]
        paths += [f"checkpoints/iteration-{row['iteration']:04d}.json" for row in old["iterations"]]
        paths += [f"proposals/{pid}.json" for pid in old["proposals"]]
        for name in paths:
            target = self.public / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(previous / "public" / name, target)
        for batch in complete:
            shutil.copytree(previous / "public/evaluations" / batch["evaluation_id"],
                            self.public / "evaluations" / batch["evaluation_id"])
        self.state.update(candidates=old["candidates"], proposals=old["proposals"], evaluations=complete,
                          iterations=old["iterations"], pending_candidates=old["pending_candidates"],
                          selected=old["selected"])
        notes = previous / "public/notes.md"
        if notes.exists():
            atomic_text(self.public / "notes.md", notes.read_text())
        self.update_selection()
        atomic_json(self.public / "evidence.json", research_evidence(self.state, episode=self.output.name))

    def tools(self):
        return (
            Tool("research_shell", "Run shell or Python analysis over /evidence (read-only public records) "
                 "and /work (your persistent episode scratch directory). Python standard library and sh are "
                 "available. Search files, parse JSON, compare runs, and save analysis scripts. "
                 "Commands have no network or private evaluator access. Return an output preview and exact "
                 "public output paths; use read_artifact or another command to inspect more. "
                 "Scratch is unverified researcher work, not a task result. "
                 "Only evaluate can dispatch development tasks. See research-workspace.json for limits.",
                 object_schema({"command": {"type": "string", "minLength": 1,
                                    "maxLength": workspace_configuration()["max_command_bytes"],
                                    "description": "Shell source; UTF-8 byte limit is frozen in research-workspace.json."},
                                "timeout_seconds": {"type": "number", "exclusiveMinimum": 0,
                                    "maximum": workspace_configuration()["max_timeout_seconds"]}}, ["command"]),
                 "mutate", self.workspace.run),
            Tool("save_candidate", "Save immutable Python source and its research rationale. Exact source duplicates "
                 "return the existing candidate ID with created=false; its original source and rationale stay unchanged. "
                 "Reuse its recorded evidence; evaluation requests must follow the frozen campaign policy.",
                 CANDIDATE_SCHEMA, "mutate", self.save_candidate),
            Tool("evaluate", self.task_selection + " Evaluate one or both saved candidates. "
                 "All ten results and mandatory Jev analysis must finish before feedback. "
                 "The host ranks success first, then agent input tokens, then agent model calls; ties retain the incumbent. "
                 "Infrastructure faults stop this attempt; ordinary task failures remain valid results.",
                 object_schema({"candidate_ids": {"type": "array", "items": {"type": "string"},
                                                  "minItems": 1, "maxItems": 2}}), "test", self.evaluate),
            Tool("checkpoint", "Complete this iteration without ending research. All its saved candidates must be evaluated. "
                 "Preserve hypothesis, evidence, failed approaches and next direction in notes. "
                 "The host selects the best fully evaluated Loop; then begin another iteration.",
                 object_schema({"notes": {"type": "string", "minLength": 1, "maxLength": 128000}}),
                 "mutate", self.checkpoint),
            Tool("read_artifact", "Read a public file, or list a public directory with exact readable paths. "
                 "Prefer a run's summary.json before its larger trace.json. Missing files return available paths; "
                 "correct the path rather than retrying it. Text pagination uses characters.",
                 object_schema({"path": {"type": "string", "description": "Path relative to public artifacts."},
                         "start": {"type": "integer", "minimum": 0,
                                   "description": "Character offset, not a line number; default 0."},
                         "limit": {"type": "integer", "minimum": 1,
                                   "description": "Character count, not lines or tokens; default 32000, maximum 128000. "
                                                  "Use returned next_start for the next page."}}, ["path"]), "inspect", self.read_artifact),
            Tool("write_notes", "Replace public notes.md with your research notes; claims are not verified facts. "
                 "Experiment records are retained independently.",
                 object_schema({"text": {"type": "string"}}), "mutate", self.write_notes),
            Tool("propose_component", "Propose a behavioral block for human review. Does not register or execute code.",
                 PROPOSAL_SCHEMA, "mutate", self.propose_component),
        )
    def research(self, *, researcher=None):
        if self.state["status"] != "prepared":
            raise ValueError("Research requires a new prepared episode")
        self.meter = ModelMeter(self.private / "research-usage.json", **self.budgets)
        self.state["status"] = "researching"
        self.save()
        try:
            if researcher is None:
                researcher = default_researcher(public_root=self.public, scratch_path=self.workspace.scratch,
                    private=self.private, container_image=self.image, meter=self.meter)
            self.check_stop()
            if not self.state["evaluations"]:
                self.evaluate({"candidate_ids": [self.baseline_candidate]}, 0)
            # An infrastructure recovery retries the unfinished batch, not completed sources.
            for candidates in getattr(self, "recovery_batches", []):
                evaluated = {cid for batch in self.state["evaluations"] for cid in batch["candidate_ids"]}
                if not all(cid in evaluated for cid in candidates):
                    self.evaluate({"candidate_ids": candidates}, 0)
            baseline_feedback = dict(artifact="evaluations/e0000/result.json", evidence_path="evidence.json")
            task = dict(
                episode=self.output.name,
                problem=(
                    "Research reusable Loops for the frozen experiment question. Optimize complete-task success "
                    "under the fixed task limits and compare total execution cost. The supplied baseline is the "
                    "reference, not a required candidate structure. "
                    "The experiment is included in this task; read experiment.md, controller-api.md and component-contracts.md "
                    "before designing candidates. components.json has exact schemas and fixed prompts; loop.md defines "
                    "the concepts. Optional examples/index.md is available for API usage, not search guidance. "
                    "Use research_shell to search and analyze the allowed public records in /evidence with shell "
                    "and Python. /work preserves your scripts and scratch files across commands in this episode. "
                    "Evaluation receipts and this task contain compact navigation, not the full evidence. "
                    "Read linked files, compute comparisons, and follow exact invocation references as needed. "
                    "Derived scratch results are your claims; verify them against the original public records. "
                    "experiment.exposed is the authority for available components and options. "
                    "Choose their order, repetition, branches, evidence flow and allowed options in Python. "
                    "Compose the exposed subcomponents directly in Python. You may remove stages, change triggers or context "
                    "and observation policies, or retain a simple Loop. No particular component sequence is preferred. "
                    "Component internals and fixed framing stay fixed; proposals require review and a new episode. "
                    "When judge is exposed, you may define its Noul/Choice questions and category descriptions, "
                    "choose evidence references and compose the returned judgments in Python. Read the Judge "
                    "section of controller-api.md for question design and uncertainty guidance. Other component "
                    "prompts and all arbitrary output schemas remain outside your editable scope. "
                    "Use save_candidate's rationale to record evidence or an explicitly untested hypothesis, "
                    "the change, expected outcome and validation. "
                    "Use a flexible research cycle: choose a worthwhile problem or opportunity within the editable "
                    "Loop boundary; assess its possible causes and scope; form an improvement hypothesis; decide "
                    "what evidence would support or weaken it; implement and compare; then update your explanation "
                    "and candidate selection from complete-task outcomes and cost. Successful runs may also expose "
                    "avoidable work. This is a reasoning guide, not a mandatory tool sequence or novelty quota. "
                    "Distinguish model errors from harness errors before proposing a failure-driven change. Inspect "
                    "the exact context and instructions actually provided to the model, its recorded response, "
                    "and the controller's use of that response. Facts elsewhere in a trace were not necessarily "
                    "visible in that model request. Errors in the fixed model's reasoning, knowledge or instruction "
                    "following are outside the editable scope; record them as model limitations rather than "
                    "relabeling them as harness defects. A wrong answer, failed task or Jev judgment alone cannot "
                    "establish a harness error. "
                    "A harness hypothesis must identify a specific editable context, observation, evidence-flow, "
                    "branching, continuation or checking policy and its predicted effect. A model-origin error "
                    "may motivate such a separate hypothesis, but pursuing it requires a specific, testable "
                    "in-scope mechanism. State its evidence or untested assumptions and compare outcomes and cost. "
                    "Do not add checks or repeated model calls to every "
                    "failure. A later correction does not by itself prove the earlier harness was defective or "
                    "that model capability improved. Preserve mixed or uncertain attribution and competing "
                    "explanations when public evidence cannot distinguish them. If you cannot identify a defensible "
                    "in-scope mechanism, leave the model error outside this search. Infrastructure and verifier faults "
                    "retain their separate stop rules; they are not optimization feedback. "
                    "Each completed development run passes through Jev before feedback is released. Its measurements "
                    "are in each run's jev field; the linked jev.json retains exact inputs, responses and attempts. "
                    "Read jev-guide.md for analysis patterns and jev-config.json for the frozen questions. "
                    "Use Jev as a semantic view of a trajectory: inspect progress and immediate effectiveness "
                    "together, uncertainty and missing measurements, recovery need and what the Loop actually "
                    "did afterward. Compare successful and unsuccessful paths, component participation and "
                    "owned cost. Segment indices are local to a run; compare evidence transitions, not identical "
                    "segment numbers across different runs. Each judgment covers the whole recorded segment. "
                    f"Progress ranges 0..{len(self.jev_configuration['questions']['progress']['criteria']) - 1}; "
                    f"effectiveness ranges 0..{len(self.jev_configuration['questions']['action_effectiveness']['criteria']) - 1}; "
                    "recovery need is a probability of yes in 0..1, not intensity. Score confidence describes "
                    "the response distribution, not the probability that a causal explanation is correct. "
                    "Interpret historical measurements using their recorded schema; earlier rubrics may differ. "
                    "Every segment receives progress and recovery judgments, including unobserved tails. "
                    "Trailing calls are split into groups of at most four reasoning or decision invocations; "
                    "their segment indices and invocation IDs distinguish groups sharing an observation cursor. "
                    "Missing action effectiveness means no new observed action outcome, not zero effectiveness. "
                    "The Jev input retains failed component arguments and errors as public evidence. "
                    "These are noisy judgments, not rewards, verified causes or instructions to change a Loop. "
                    "Choose freely between inspecting evidence, revising a design, gathering "
                    "more evidence and abandoning a hypothesis under the frozen campaign policy. "
                    "Follow that policy when deciding which sources may be evaluated again; resaving identical "
                    "code is not a new design. Use write_notes to record changed hypotheses. "
                    "When repeated changes fail to help, reconsider the explanation and available design choices. "
                    "Distinguish rejecting one family of changes from exhausting the search space. Consider which "
                    "untested behavioral mechanism could address the evidence, whether the approved components can "
                    "express it, and what the next evaluation would measure. Follow the frozen stopping policy; "
                    "an unsuccessful candidate alone does not exhaust the search space. "
                    "evidence.json and evaluate receipts provide host-derived cumulative facts; use them instead "
                    "of reconstructing counts from memory. Read candidate sources and evidence before reusing "
                    "or rejecting a hypothesis. Missing artifact errors supply available paths; correct the path "
                    "or list a directory instead of repeating the failed request. Keep research notes, scores "
                    "and history out of candidate source comments and task-agent input; use rationale and write_notes. "
                    + self.task_selection + " Repeated runs do not broaden task coverage. "
                    "Joint changes do not isolate causes, and fewer tokens alone do not prove better performance. "
                    "Do not hardcode development answers. Holdout tasks and feedback are unavailable during research. "
                    "The host records development model attempts, including simulated-user and Jev calls. "
                    "The researcher runtime records its available usage and any missing measurements. "
                    "A null budget means no cap; finite parent limits still apply. "
                    "When limits are finite, reserve enough budget to analyze runs and submit. "
                    "Save one new candidate by default, at most two per iteration. Evaluate each once on all tasks. "
                    "Use checkpoint(notes) after all saved candidates are evaluated. It records the host-ranked "
                    "incumbent and research experience without ending research. Do not stop for uncertain gains. "
                    "There is no finish or select tool; the host owns selection and the user owns stopping. "
                    "Read checkpoints and evidence.json after recovery. Research has no shared budget cap."
                ),
                controller_api_path="controller-api.md", component_contracts_path="component-contracts.md",
                research_protocol_path="experiment.md",
                experiment=copy.deepcopy(self.experiment), workspace=workspace_configuration(),
                initial_evaluation=baseline_feedback, initial_selection=self.state["selected"],
                jev_configuration_path="jev-config.json", jev_guide_path="jev-guide.md",
                baseline_candidate=self.baseline_candidate,
                baseline_source=self.source(self.baseline_candidate),
                task_limits=vars(self.task_limits), research_budgets=self.budgets,
                max_development_task_runs=None,
                completed_iterations=len(self.state["iterations"]), incumbent=self.state["selected"],
            )
            tools = self.tools()
            atomic_json(self.private / "research-task.json", task)
            atomic_json(self.private / "research-tools.json", [tool.disclosure_record() for tool in tools])
            trace_path = self.private / "research-trace.json"
            research = researcher.run(task, tools, self.meter, trace_path, check_stop=self.check_stop)
            atomic_json(self.private / "native-researcher.json", research)
            self.state.setdefault("research_status", research["status"])
            if research["status"] == "budget_exhausted":
                self.state.update(status="budget_exhausted", stop_reason=research.get("error"))
            else:
                raise HostFault("Continuous researcher ended unexpectedly: " + research["status"])
        except KeyboardInterrupt:
            self.state.update(status="stopped", research_status="user_stopped", stop_reason="user_stop")
        except BaseException as error:
            self.state.update(status="interrupted", error=str(error), error_type=type(error).__name__)
            self.state.setdefault("research_status", "host_fault")
            raise
        finally:
            self.state["frozen_candidate"] = self.state["selected"]
            self.save()
        return self.state["selected"]
