"""A bounded research episode: editable candidates, development feedback, frozen selection."""

from __future__ import annotations

import copy
import json
import random
import shutil
import time
from pathlib import Path

from loopblox import ROOT, snapshot_implementation
from loopblox.runtime.components import catalog, object_schema, render_contracts, validate
from loopblox.runtime.controller import ControllerRuntime, Limits, MAX_SOURCE_BYTES, ModelMeter
from loopblox.runtime.model import HostFault, OperationalProblem, Tool, ToolResult
from loopblox.runtime.io import atomic_json, atomic_text, digest
from loopblox.report import summarize_trace



RESEARCH_CONTROLLER = ROOT / "controllers" / "research.py"
API_GUIDE = ROOT / "CONTROLLER.md"
CANDIDATE_SCHEMA = object_schema({
    "source": {"type": "string", "description": "Complete Python source defining run(env)."},
    "rationale": {"type": "string", "description":
        "Briefly state the evidence or untested hypothesis, the change, expected outcome, and how to test it. "
        "Cite development records you used; identify historical candidates by episode/candidate, not a bare ID. "
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
    return dict(
        attempted=len(attempted),
        resolved=sum(row.get("verification_verdict") == "pass" for row in attempted),
        unresolved=sum(row.get("verification_verdict") == "fail" for row in attempted),
        unscored=sum(row.get("verification_verdict") is None for row in attempted),
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
        by_task = {}
        for row in attempted:
            if row.get("verification_verdict") in {"pass", "fail"}:
                by_task.setdefault(row["task_id"], []).append(row["verification_verdict"])
        candidates[candidate_id] = dict(
            **summarize(selected), usage=usage,
            distinct_tasks=len({row["task_id"] for row in attempted}),
            tasks_with_multiple_scored_runs=sum(len(values) > 1 for values in by_task.values()),
            tasks_with_score_disagreement=sum(len(set(values)) > 1 for values in by_task.values()))
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
                              control_directory=base["directory"], candidate_directory=row["directory"]))
        comparisons[candidate_id] = dict(control=control, pairs=pairs,
            outcomes={key: sum(pair["outcome"] == key for pair in pairs) for key in (
                "both_pass", "both_fail", "candidate_only_pass", "control_only_pass", "unscored")})
    return dict(candidates=candidates, comparisons=comparisons,
                interpretation="Pairing uses host draw and repeat, with fresh environments and workers. "
                               "Repeated draws/runs are not independent scenario groups. "
                               "Same task seed does not guarantee identical model or simulated-user responses.")


def research_evidence(state, *, episode=None, prefix=""):
    """Derive cross-evaluation facts; researcher prose never owns the counts."""
    candidates = {}
    for candidate_id in state["candidates"]:
        evaluations = [e for e in state["evaluations"] if candidate_id in e["candidate_ids"]]
        rows = [row for e in evaluations for row in e["runs"] if row["candidate_id"] == candidate_id]
        summary = summarize_evaluation(dict(candidate_ids=[candidate_id], runs=rows))["candidates"][candidate_id]
        reference = f"{episode}/{candidate_id}" if episode else candidate_id
        candidates[reference] = dict(
            **summary, source=prefix + f"candidates/{candidate_id}.py", rationale=prefix + f"candidates/{candidate_id}.json",
            evaluations=[prefix + f"evaluations/{e['evaluation_id']}/result.json" for e in evaluations],
            failure_summaries=[prefix + row["trace_summary"] for row in rows if row.get("trace_summary")
                               and (row.get("verification_verdict") == "fail"
                                    or row["status"] not in {"completed", "not_started", "running"})])
    return dict(episode=episode, candidates=candidates, task_runs_used=state["task_runs_used"],
                interpretation="Host-derived totals across evaluations; different candidates may have different draws. "
                               "Use each evaluation's paired comparisons for comparisons. Rationale and notes are "
                               "researcher claims, not verified causes. Unstarted runs are not failed attempts.")


def export_experience(episode, destination):
    """Export a closed episode's public development evidence and its prior experience."""
    episode, destination = Path(episode), Path(destination)
    state = json.loads((episode / "private/state.json").read_text())
    if state["status"] != "selected" or state.get("research_status") != "completed" or not state.get("selection_reason"):
        raise ValueError("Experience requires closed research with an explicit submission, before final evaluation")
    public = episode / "public"
    previous = public / "experience"
    if previous.exists():
        shutil.copytree(previous, destination)
    else:
        destination.mkdir(parents=True, exist_ok=False)
    prefix = f"episodes/{episode.name}"
    target = destination / prefix
    target.mkdir(parents=True, exist_ok=False)
    paths = set()
    for candidate_id in state["candidates"]:
        paths.update((f"candidates/{candidate_id}.py", f"candidates/{candidate_id}.json"))
    for evaluation in state["evaluations"]:
        base = f"evaluations/{evaluation['evaluation_id']}"
        paths.add(base + "/result.json")
        paths.update(f"{base}/sources/{candidate_id}.py" for candidate_id in evaluation["candidate_ids"])
        for row in evaluation["runs"]:
            for name in ("summary.json", "trace.json"):
                path = f"{base}/{row['directory']}/{name}"
                if (public / path).is_file():
                    paths.add(path)
    if (public / "notes.md").is_file():
        paths.add("notes.md")
    for name in sorted(paths):
        path = public / name
        if path.is_symlink() or not path.resolve().is_relative_to(public.resolve()):
            raise ValueError("Experience evidence must be a regular public artifact")
        (target / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target / name)
    atomic_json(target / "submission.json", dict(selected=state["frozen_candidate"],
                reason=state["selection_reason"], interpretation="Researcher claim; verify against evidence.json."))
    # Rebuild navigation and facts from the copied public records. Raw records stay exact;
    # every link in these derived views is relative to the next episode's public root.
    index = dict(episodes=[], interpretation=
        "Development evidence from this lineage only. Identify historical candidates by episode/candidate, "
        "never a bare candidate ID; local IDs can name different source in another episode. "
        "All paths in this index and evidence.json are ready for read_artifact. Counts are host-derived. "
        "Compare paired outcomes, not cumulative totals over different draws. Original evaluation and trace "
        "files retain their episode-local IDs and relative paths. Rationales, notes and submission reasons "
        "are unverified claims. No final scores, private simulator prompts or evaluator internals are exported.")
    for snapshot in sorted((destination / "episodes").iterdir()):
        evaluations = [json.loads(path.read_text())
                       for path in sorted((snapshot / "evaluations").glob("*/result.json"))]
        records = dict(candidates=[path.stem for path in sorted((snapshot / "candidates").glob("*.py"))],
                       evaluations=evaluations, task_runs_used=sum(
                           row["status"] != "not_started" for evaluation in evaluations for row in evaluation["runs"]))
        base = f"experience/episodes/{snapshot.name}/"
        evidence = research_evidence(records, episode=snapshot.name, prefix=base)
        atomic_json(snapshot / "evidence.json", evidence)
        submission = json.loads((snapshot / "submission.json").read_text())
        pairs = []
        for evaluation in evaluations:
            for candidate_id, comparison in summarize_evaluation(evaluation)["comparisons"].items():
                pairs.append(dict(candidate=f"{snapshot.name}/{candidate_id}",
                    control=f"{snapshot.name}/{comparison['control']}", outcomes=comparison["outcomes"],
                    evaluation=base + f"evaluations/{evaluation['evaluation_id']}/result.json"))
        index["episodes"].append(dict(episode=snapshot.name, path=base,
            selected=f"{snapshot.name}/{submission['selected']}", evidence=base + "evidence.json",
            submission=base + "submission.json",
            candidates={reference: {key: value for key, value in facts.items()
                                   if key in {"source", "attempted", "resolved", "unresolved", "unscored"}}
                        for reference, facts in evidence["candidates"].items()},
            paired_comparisons=pairs))
    atomic_json(destination / "index.json", index)
    return index


class ResearchSession:
    def __init__(self, *, output: Path, development: tuple[str, ...], holdout: tuple[str, ...],
                 run_task, research_client, worker_image: str, setup: dict,
                 experiment: dict, baseline_source: str,
                 max_task_runs: int, research_seconds: float, research_output_tokens: int,
                 research_model_calls: int, task_limits: Limits, seed: int = 0,
                 starting_source: str | None = None, experience: Path | None = None):
        if (not development or set(development) & set(holdout)
                or len(set(development)) != len(development) or len(set(holdout)) != len(holdout)):
            raise ValueError("Development must be nonempty; development and holdout must be unique and disjoint")
        if type(max_task_runs) is not int or max_task_runs < 1:
            raise ValueError("max_task_runs must allow at least the initial baseline evaluation")
        if starting_source is not None and starting_source != baseline_source and max_task_runs < 2:
            raise ValueError("Budget must cover the initial baseline and distinct inherited Loop")
        if experience is not None and starting_source is None:
            raise ValueError("Experience inheritance requires the corresponding inherited Loop")
        if min(research_seconds, research_output_tokens, research_model_calls) <= 0:
            raise ValueError("Research budgets must be positive")
        self.experiment = validate_experiment(experiment)
        exposed_catalog = catalog(self.experiment["exposed"])
        self.api_guide = API_GUIDE.read_text()
        self.research_controller = RESEARCH_CONTROLLER.read_text()
        self.output = output.resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        self.public = self.output / "public"
        self.private = self.output / "private"
        self.public.mkdir()
        self.private.mkdir()
        (self.public / "candidates").mkdir()
        (self.public / "evaluations").mkdir()
        (self.public / "proposals").mkdir()
        self.development, self.holdout = development, holdout
        self.run_task, self.client, self.image = run_task, research_client, worker_image
        self.task_limits, self.max_task_runs = task_limits, max_task_runs
        self.random = random.Random(seed)
        self.budgets = dict(seconds=research_seconds, output_tokens=research_output_tokens,
                            model_calls=research_model_calls)
        self.state = dict(status="prepared", candidates=[], evaluations=[], proposals=[], selected=None, task_runs_used=0)
        atomic_json(self.private / "setup.json", {
            **setup, "development": development, "holdout": holdout, "seed": seed,
            "sampling": "uniform_with_replacement; freeze all candidates, draw one complete shared batch, "
                        "repeat with fresh workers/environments; rotate candidate order by draw plus repeat",
            "research_budgets": {**self.budgets, "task_runs": max_task_runs},
            "task_limits": vars(task_limits), "worker_image": worker_image, "components": catalog(),
            "experiment": self.experiment,
        })
        atomic_json(self.public / "experiment.json", self.experiment)
        atomic_json(self.public / "components.json", exposed_catalog)
        atomic_text(self.public / "component-contracts.md", render_contracts(exposed_catalog))
        atomic_text(self.public / "controller-api.md", self.api_guide)
        atomic_text(self.public / "loop.md", (ROOT / "loop.md").read_text())
        examples = self.public / "examples"
        examples.mkdir()
        example_sources = sorted(path for path in (ROOT / "controllers").glob("*.py")
                                 if path.name != RESEARCH_CONTROLLER.name and path.read_text() != baseline_source)
        for path in example_sources:
            atomic_text(examples / path.name, path.read_text())
        atomic_text(examples / "index.md",
                    "# Optional Loop examples\n\n"
                    "Exact source snapshots for API usage, not a recommended search sequence. "
                    "An example is usable only if experiment.json exposes every component and option it calls.\n\n"
                    + "\n".join(f"- [{path.name}]({path.name})" for path in example_sources) + "\n")
        snapshot_implementation(self.private)
        atomic_text(self.private / "implementation/research-controller.py", self.research_controller)
        initial = self.save_candidate({
            "source": baseline_source,
            "rationale": "Host-supplied baseline, without researcher changes. Establish reference success and cost; "
                         "no performance advantage is assumed. Run the initial development trial, then use it "
                         "in shared-task comparisons with alternatives.",
        }, 0)["candidate_id"]
        self.state["selected"] = initial
        self.initial_candidates = [initial]
        self.starting_candidate = initial
        if starting_source is not None:
            self.starting_candidate = self.save_candidate(dict(source=starting_source,
                rationale="Host-supplied inherited Loop source. Previous scores and explanations are not implied. "
                          "Evaluate it against the unchanged unified baseline in this episode."), 0)["candidate_id"]
            if self.starting_candidate != initial:
                self.initial_candidates.append(self.starting_candidate)
        self.experience = None
        if experience is not None:
            shutil.copytree(experience, self.public / "experience")
            self.experience = "experience/index.json"
        inherited_files = {str(path.relative_to(self.public)): digest(path.read_bytes())
                           for path in (self.public / "experience").rglob("*") if path.is_file()}
        setup_path = self.private / "setup.json"
        frozen_setup = json.loads(setup_path.read_text())
        frozen_setup["inheritance"] = dict(starting_candidate=self.starting_candidate,
            starting_source_sha256=None if starting_source is None else digest(starting_source.encode()),
            experience_files=inherited_files)
        atomic_json(setup_path, frozen_setup)
        self.save()

    def save(self):
        atomic_json(self.private / "state.json", self.state)

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
        candidate_id = f"c{len(self.state['candidates']):04d}"
        path = self.public / "candidates" / f"{candidate_id}.py"
        atomic_text(path, source)
        rationale_path = path.with_suffix(".json")
        atomic_json(rationale_path, dict(rationale=rationale, source_sha256=digest(source_bytes)))
        self.state["candidates"].append(candidate_id)
        self.save()
        return dict(candidate_id=candidate_id, path=str(path.relative_to(self.public)),
                    rationale_path=str(rationale_path.relative_to(self.public)), created=True)

    def read_artifact(self, arguments, _timeout):
        raw = arguments.get("path")
        if not isinstance(raw, str) or Path(raw).is_absolute():
            self.reject("path must be relative to the public artifact directory")
        path = (self.public / raw).resolve()
        if not path.is_relative_to(self.public):
            self.reject("No readable public artifact at this path")
        canonical = str(path.relative_to(self.public))
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
            entries = [str(entry.relative_to(self.public)) + ("/" if entry.is_dir() else "")
                       for entry in sorted(directory.iterdir())
                       if entry.resolve().is_relative_to(self.public) and (entry.is_file() or entry.is_dir())]
            if not path.is_dir():
                return ToolResult("failed", dict(code="artifact_not_found", path=canonical,
                    message="This artifact does not exist. Use a listed path or read its directory; "
                            "repeating this missing-file request will not recover it.",
                    directory=str(directory.relative_to(self.public)), available_paths=entries), "none")
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
        candidate_ids, n = arguments.get("candidate_ids"), arguments.get("n")
        repeats = arguments.get("repeats", 1)
        if (not isinstance(candidate_ids, list) or not candidate_ids
                or any(not isinstance(item, str) for item in candidate_ids)
                or len(set(candidate_ids)) != len(candidate_ids)):
            self.reject("candidate_ids must be a nonempty list of unique candidate IDs; first is the control")
        sources = {candidate_id: self.source(candidate_id) for candidate_id in candidate_ids}
        if type(n) is not int or n < 1 or type(repeats) is not int or repeats < 1:
            self.reject("n and repeats must be positive integers")
        count = n * repeats * len(candidate_ids)
        remaining = self.max_task_runs - self.state["task_runs_used"]
        if count > remaining:
            self.reject(f"Requested {count} development runs; only {remaining} remain. No draws or runs were started.")
        evaluation_id = f"e{len(self.state['evaluations']):04d}"
        directory = self.public / "evaluations" / evaluation_id
        directory.mkdir()
        for candidate_id, source in sources.items():
            atomic_text(directory / "sources" / f"{candidate_id}.py", source)
        sampled = [self.random.choice(self.development) for _ in range(n)]
        rows = []
        for draw, task_id in enumerate(sampled):
            for repeat in range(repeats):
                offset = (draw + repeat) % len(candidate_ids)
                for candidate_id in candidate_ids[offset:] + candidate_ids[:offset]:
                    rows.append(dict(candidate_id=candidate_id, task_id=task_id, draw=draw, repeat=repeat,
                                     directory=f"run-{len(rows):04d}", status="not_started"))
        evaluation = dict(evaluation_id=evaluation_id, candidate_ids=list(candidate_ids),
                          sources={key: dict(path=f"sources/{key}.py", sha256=digest(value.encode()))
                                   for key, value in sources.items()},
                          sampled_tasks=sampled, repeats=repeats, requested_runs=count, status="running", runs=rows)
        self.state["evaluations"].append(evaluation)
        self.save()
        return self.run_evaluation(evaluation)

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
        dispatched = []
        try:
            for index, row in enumerate(rows):
                if row["status"] != "not_started":
                    continue
                if (self.state["task_runs_used"] >= self.max_task_runs
                        or any(value <= 0 for value in self.meter.remaining().values())):
                    break
                self.state["task_runs_used"] += 1
                row["status"] = "running"
                dispatched.append(row)
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
        finally:
            # Derive evidence only from the public controller trace, never private environment ledgers.
            for row in dispatched:
                trace = directory / row["directory"] / "trace.json"
                if trace.is_file():
                    evidence = trace.with_name("summary.json")
                    atomic_json(evidence, summarize_trace(json.loads(trace.read_text())))
                    row["trace_summary"] = str(evidence.relative_to(self.public))
            evaluation.update(status="settled", summary=summarize_evaluation(evaluation))
            self.save()
            atomic_json(result_path, evaluation)
            atomic_json(self.public / "evidence.json", research_evidence(self.state, episode=self.output.name))
        return dict(
            evaluation_id=evaluation_id, candidate_ids=candidate_ids,
            summary=evaluation["summary"], runs=rows,
            artifact=f"evaluations/{evaluation_id}/result.json",
            remaining_task_runs=self.max_task_runs - self.state["task_runs_used"],
            research_usage=self.meter.summary(),
            evidence=research_evidence(self.state, episode=self.output.name), evidence_path="evidence.json",
        )

    def select(self, arguments, _timeout):
        candidate_id = arguments.get("candidate_id")
        self.source(candidate_id)
        if not any(any(row["candidate_id"] == candidate_id and row.get("verification_verdict") in {"pass", "fail"}
                       for row in evaluation["runs"])
                   for evaluation in self.state["evaluations"]):
            self.reject("A candidate needs a scored development result (pass or fail) before selection")
        self.state["selected"] = candidate_id
        self.state.pop("selection_reason", None)
        self.save()
        return dict(selected=candidate_id)

    def finish(self, arguments, timeout):
        reason = arguments.get("reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 16000:
            self.reject("Provide a nonempty selection reason of at most 16000 characters")
        receipt = self.select(arguments, timeout)
        self.state["selection_reason"] = reason
        self.save()
        return dict(**receipt, reason=reason)

    def tools(self):
        return (
            Tool("save_candidate", "Save immutable Python source and its research rationale. Exact source duplicates "
                 "return the existing candidate ID with created=false; its original source and rationale stay unchanged. "
                 "Re-evaluate an existing ID to gather more evidence for the same code.",
                 CANDIDATE_SCHEMA, "mutate", self.save_candidate),
            Tool("evaluate", "Compare frozen candidates on the same n host-sampled tasks, each repeated repeats times "
                 "(default 1). First candidate is the control. Costs n * repeats * number of candidates task runs. "
                 "Returns paired outcomes/costs and factual trace-summary paths. All attempts cost budget. "
                 "Infrastructure or verifier faults stop research; ordinary task failures remain valid results.",
                 object_schema({"candidate_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                                "n": {"type": "integer", "minimum": 1},
                                "repeats": {"type": "integer", "minimum": 1}}, ["candidate_ids", "n"]), "test", self.evaluate),
            Tool("select", "Choose a candidate with a scored development result (pass or fail). Last selection survives exhaustion.",
                 object_schema({"candidate_id": {"type": "string"}}), "mutate", self.select),
            Tool("finish", "Submit a candidate with a scored development result and your evidence-based reason to end research. "
                 "A successful receipt makes the outer researcher controller return. Retaining the baseline is valid. "
                 "Use select only for interim choices; use finish when ready to close.",
                 object_schema({"candidate_id": {"type": "string"}, "reason": {"type": "string"}}), "mutate", self.finish),
            Tool("read_artifact", "Read a public file, or list a public directory with exact readable paths. "
                 "Prefer a run's summary.json before its larger trace.json. Missing files return available paths; "
                 "correct the path rather than retrying it. Text pagination uses characters.",
                 object_schema({"path": {"type": "string", "description": "Path relative to public artifacts."},
                         "start": {"type": "integer", "minimum": 0,
                                   "description": "Character offset, not a line number; default 0."},
                         "limit": {"type": "integer", "minimum": 1,
                                   "description": "Character count, not lines or tokens; default 32000, maximum 128000. "
                                                  "Use returned next_start for the next page."}}, ["path"]), "inspect", self.read_artifact),
            Tool("write_notes", "Replace your private research notes; experiment records are retained independently.",
                 object_schema({"text": {"type": "string"}}), "mutate", self.write_notes),
            Tool("propose_component", "Propose a behavioral block for human review. Does not register or execute code.",
                 PROPOSAL_SCHEMA, "mutate", self.propose_component),
        )

    def research(self):
        if self.state["status"] != "prepared":
            raise ValueError("Research requires a new prepared episode")
        self.meter = ModelMeter(self.private / "research-usage.json", **self.budgets)
        self.state["status"] = "researching"
        self.save()
        try:
            baseline_feedback = self.evaluate({"candidate_ids": self.initial_candidates, "n": 1}, 0)
            if any(row["candidate_id"] == self.starting_candidate and row.get("verification_verdict") in {"pass", "fail"}
                   for row in self.state["evaluations"][0]["runs"]):
                self.state["selected"] = self.starting_candidate
                self.save()
            experience = json.loads((self.public / self.experience).read_text()) if self.experience else None
            starting_history = [reference for item in experience["episodes"]
                                for reference, facts in item["candidates"].items()
                                if (self.public / facts["source"]).read_text() == self.source(self.starting_candidate)
                                ] if experience else []
            task = dict(
                episode=self.output.name,
                problem=(
                    "Research reusable Loops for the frozen experiment question. Optimize complete-task success "
                    "under the fixed task limits and compare total execution cost. The supplied baseline is the "
                    "reference, not a required candidate structure. "
                    "The API guide and experiment are included in this task; read component-contracts.md before "
                    "designing candidates. components.json has exact schemas and fixed prompts; loop.md defines "
                    "the concepts. Optional examples/index.md is available for API usage, not search guidance. "
                    "experiment.exposed is the authority for available components and options. "
                    "Choose their order, repetition, branches, evidence flow and allowed options in Python. "
                    "Compose the exposed subcomponents directly in Python. You may remove stages, change triggers or context "
                    "and observation policies, or retain a simple Loop. No particular component sequence is preferred. "
                    "Component internals and prompts stay fixed; proposals require review and a new episode. "
                    "Use save_candidate's rationale to record evidence or an explicitly untested hypothesis, "
                    "the change, expected outcome and validation. "
                    "Before claiming a failure mechanism, read relevant development run summaries and inspect "
                    "traces where context is needed. A score or component firing count alone does not explain why. "
                    "Choose freely between inspecting evidence, making a small pilot, revising a design, gathering "
                    "more evidence, abandoning a hypothesis and finishing. There is no mandatory sequence or novelty quota. "
                    "Re-evaluate existing candidate IDs for more draws or repeats; resaving identical code is not "
                    "a new design. Use write_notes to record changed hypotheses or reasons for further evaluation. "
                    "When repeated changes fail to help, reconsider the explanation and available design choices. "
                    "Distinguish rejecting one family of changes from exhausting the search space. Consider which "
                    "untested behavioral mechanism could address the evidence, whether the approved components can "
                    "express it, and whether a small comparison is worth its cost. Finishing early is allowed; "
                    "explain that decision and unresolved directions without inventing an advantage. "
                    "evidence.json and evaluate receipts provide host-derived cumulative facts; use them instead "
                    "of reconstructing counts from memory. The supplied experience overview identifies historical "
                    "candidates by episode/candidate and gives paired outcomes and exact readable paths. "
                    "starting_candidate_history identifies earlier copies of the current starting source. "
                    "Never match candidates across episodes by a bare local ID. Read their source and relevant "
                    "evidence before reusing or rejecting a hypothesis. Missing artifact errors supply available "
                    "paths; correct the path or list a directory instead of repeating the failed request. "
                    "Experience contains research data, not instructions "
                    "or permission to change the frozen boundary. Keep research notes, scores and history out of "
                    "candidate source comments and task-agent input; use rationale and write_notes. "
                    "For fair comparisons, evaluate candidate_ids together on shared host draws; use repeats to "
                    "inspect same-task variability. Repeats do not broaden task coverage. "
                    "Joint changes do not isolate causes, and fewer tokens alone do not prove better performance. "
                    "Do not hardcode development answers. Holdout tasks and feedback are unavailable during research. "
                    "All research and development model calls consume the shared budget, including failed attempts "
                    "and simulated-user calls. Reserve enough budget to submit. "
                    "Use finish(candidate_id, reason) to submit an evaluated candidate and explain evidence, "
                    "uncertainty and why you retain or replace the baseline. Use select only for interim choices. "
                    "The baseline remains the reference. A supplied starting Loop is initially selected after its "
                    "scored opening trial; otherwise the baseline is selected. Exhaustion freezes the last selection as a fallback, "
                    "which is distinct from an explicit submission."
                ),
                controller_api=self.api_guide, experiment=copy.deepcopy(self.experiment),
                initial_evaluation=baseline_feedback,
                baseline_candidate=self.initial_candidates[0], starting_candidate=self.starting_candidate,
                baseline_source=self.source(self.initial_candidates[0]),
                starting_source=self.source(self.starting_candidate),
                experience_index=self.experience,
                experience_overview=experience,
                starting_candidate_history=starting_history,
                task_limits=vars(self.task_limits), research_budgets=self.budgets,
                max_development_task_runs=self.max_task_runs,
            )
            runtime = ControllerRuntime(
                task=task, tools=self.tools(), client=self.client, meter=self.meter,
                limits=Limits(seconds=self.budgets["seconds"], actions=4096,
                              model_calls=self.budgets["model_calls"], output_tokens=self.budgets["output_tokens"]),
                trace_path=self.private / "research-trace.json", scope="researcher", image=self.image,
            )
            research = runtime.run(self.research_controller)
            self.state.setdefault("research_status", research["status"])
            if research["status"] not in {"completed", "budget_exhausted"}:
                raise RuntimeError("Researcher failed: " + self.state["research_status"])
        except BaseException:
            self.state.update(status="interrupted", frozen_candidate=self.state["selected"])
            self.save()
            raise

        # No research process is alive beyond this point. Freeze before any final feedback.
        selected = self.state["selected"]
        source = self.source(selected)
        atomic_text(self.output / "selected-controller.py", source)
        self.state.update(status="selected", frozen_candidate=selected)
        self.save()
        return selected
