"""A shared telecom opening followed by two isolated researcher systems; no test dispatch."""

import argparse
import copy
from dataclasses import replace
import json
import os
from pathlib import Path
import random
import shutil
import sys
import time

from loopblox import ROOT
from loopblox.benchmarks.tau2 import Tau2Runner, load_suite
from loopblox.experiments import release_research
from loopblox.experiments.common import clients, read, run_stage, verify
from loopblox.experiments.release_research import ReleaseResearchSession, rank_evaluation
from loopblox.research.session import ResearchSession, evaluation_verdict, research_evidence
from loopblox.runtime.controller import Limits, ModelMeter, model_usage
from loopblox.runtime.io import atomic_json, atomic_text, digest, image_id
from loopblox.runtime.model import BudgetExhausted, HostFault


ARMS = ("loopblox", "codex")
SELECTION_INTERPRETATION = (
    "Selection compares each candidate's one complete ten-task evaluation, including the historical opening. "
    "L0 and L1 are not rerun. The historical opening has mixed limits and a user-adjudicated failure; "
    "cross-batch rankings are descriptive selection evidence, not a fresh paired control comparison or "
    "proof of improvement. Paired comparisons within a new batch concern only that batch's new sources."
)


class SharedOpeningSession(ReleaseResearchSession):
    """Import one common opening, then evaluate each new source at most once."""

    def __init__(self, *, common_opening, opening_import=None, research_only=False, **arguments):
        self.opening_import = opening_import
        self.research_only = research_only
        self.recovery_evaluation = None
        super().__init__(opening=Path(common_opening), **arguments)
        if research_only:
            # Construction registers the supplied sources; imported opening runs are not new dispatches.
            self.max_task_runs = 0
            setup = read(self.private / "setup.json")
            setup["research_budgets"]["task_runs"] = 0
            atomic_json(self.private / "setup.json", setup)
        atomic_json(self.public / "release-policy.json", dict(
            task_ids=self.development, historical_controls=self.initial_candidates,
            candidate_caps=release_research.ROUND_CANDIDATE_CAPS,
            new_candidate_cap=self.new_candidate_cap, task_cap=self.max_task_runs,
            ranking=release_research.RANKING_RULE, interpretation=SELECTION_INTERPRETATION,
            finish="Submit the host-ranked best source across complete opening and research evaluations. "
                   "Finish without saving or evaluating any new source when no worthwhile improvement hypothesis exists.",
            evaluation="Save the complete batch before evaluate. First batch: up to three new sources. "
                       "Second batch: up to two additional new sources. Include every pending saved source. "
                       "Never evaluate L0, L1, or any previously evaluated source again. n=10, repeats=1. "
                       "Unused first-batch slots do not transfer; source counts are upper bounds, not quotas."))
        if research_only:
            policy = read(self.public / "release-policy.json")
            policy.update(mode="research_only", candidate_caps=[], task_cap=0,
                evaluation="Disabled by user. Analyze the existing opening only; no new task or Jev runs.",
                finish="Write your research findings to notes.md, optionally save up to five untested source "
                       "proposals, then finish with the existing opening winner. Saved proposals remain "
                       "untested and cannot be selected. No evaluation is required or allowed.")
            atomic_json(self.public / "release-policy.json", policy)
        if opening_import:
            atomic_json(self.public / "opening-provenance.json", {
                key: value for key, value in opening_import.items() if key not in {"path", "files"}})

    def next_batch(self):
        if self.research_only:
            remaining = max(0, self.new_candidate_cap - len(self.state["candidates"]) + len(self.initial_candidates))
            return dict(required_candidate_ids=[], pending_candidate_ids=self.pending_candidates(),
                additional_candidate_slots=remaining, new_candidate_allowance=remaining,
                remaining_task_runs=0, remaining_new_candidates=remaining,
                remaining_research_batches=0, can_evaluate=False)
        round_index = len(self.state["evaluations"]) - 1
        caps = release_research.ROUND_CANDIDATE_CAPS
        slots = caps[round_index] if 0 <= round_index < len(caps) else 0
        remaining = self.remaining_task_runs
        if remaining is not None:
            slots = min(slots, remaining // len(self.development))
        new_remaining = max(0, self.new_candidate_cap - len(self.state["candidates"])
                            + len(self.initial_candidates))
        pending = self.pending_candidates()
        return dict(required_candidate_ids=[], pending_candidate_ids=pending,
                    additional_candidate_slots=slots,
                    new_candidate_allowance=max(0, min(slots - len(pending), new_remaining)),
                    remaining_task_runs=remaining, remaining_new_candidates=new_remaining,
                    remaining_research_batches=max(0, len(caps) - max(round_index, 0)),
                    can_evaluate=slots > 0 and bool(pending or new_remaining))

    def selection_ranking(self):
        complete = [batch for batch in self.state["evaluations"]
                    if batch["status"] == "settled" and all(
                        evaluation_verdict(row) in {"pass", "fail"} for row in batch["runs"])]
        ranking = rank_evaluation(dict(
            candidate_ids=[candidate for batch in complete for candidate in batch["candidate_ids"]],
            runs=[row for batch in complete for row in batch["runs"]]), self.state["candidates"])
        evaluations = {candidate: batch["evaluation_id"]
                       for batch in complete for candidate in batch["candidate_ids"]}
        return [dict(row, evaluation_id=evaluations[row["candidate_id"]]) for row in ranking]

    def evaluate(self, arguments, timeout):
        if self.research_only and self.state["evaluations"]:
            self.reject("The user requested research only. New task evaluations are disabled; write findings and finish.")
        if (type(arguments.get("n")) is not int or arguments["n"] != len(self.development)
                or type(arguments.get("repeats", 1)) is not int or arguments.get("repeats", 1) != 1):
            self.reject("This comparison requires all ten fixed tasks with n=10, repeats=1.")
        if not self.state["evaluations"]:
            feedback = super().evaluate(arguments, timeout)
        else:
            ids, pending, options = arguments.get("candidate_ids"), self.pending_candidates(), self.next_batch()
            if (not options["can_evaluate"] or not isinstance(ids, list) or not ids
                    or any(not isinstance(candidate, str) for candidate in ids)
                    or len(set(ids)) != len(ids) or set(ids) != set(pending)
                    or len(ids) > options["additional_candidate_slots"]):
                self.reject("Evaluate only every pending newly saved source, once each. Never rerun L0, L1, "
                            "or a previously evaluated source. First batch allows up to three new sources; "
                            "second allows up to two. Finish without another evaluation if no improvement "
                            "hypothesis warrants a new source.")
            feedback = (self.run_evaluation(self.import_recovery_evaluation(ids))
                        if self.recovery_evaluation is not None else
                        ResearchSession.evaluate(self, arguments, timeout))
            batch = self.state["evaluations"][-1]
            if any(evaluation_verdict(row) not in {"pass", "fail"} for row in batch["runs"]):
                self.state["research_status"] = ("budget_exhausted" if any(
                    row["status"] == "not_started" for row in batch["runs"]) else "incomplete_evaluation")
                self.save()
                if self.state["research_status"] == "budget_exhausted":
                    raise BudgetExhausted("comparison_batch_incomplete")
                raise HostFault("An incomplete candidate batch cannot determine selection")
            batch["release_ranking"] = rank_evaluation(batch, self.state["candidates"])
        batch = self.state["evaluations"][-1]
        ranking = self.selection_ranking()
        batch.update(selection_ranking=ranking, selection_interpretation=SELECTION_INTERPRETATION)
        self.state["selected"] = ranking[0]["candidate_id"]
        self.save()
        atomic_json(self.public / feedback["artifact"], batch)
        feedback.update(release_ranking=batch["release_ranking"], selection_ranking=ranking,
                        selection_interpretation=SELECTION_INTERPRETATION,
                        best_candidate=ranking[0]["candidate_id"], next_batch=self.next_batch(),
                        remaining_research_batches=self.next_batch()["remaining_research_batches"])
        return feedback

    def import_recovery_evaluation(self, candidate_ids):
        """Carry a verified completed prefix; restart only its infrastructure failure."""
        original = Path(self.recovery_evaluation)
        previous = read(original / "result.json")
        evaluation_id = f"e{len(self.state['evaluations']):04d}"
        if (len(self.state["evaluations"]) != 1 or previous["evaluation_id"] != evaluation_id
                or previous["status"] != "settled" or previous["candidate_ids"] != candidate_ids
                or previous["sampled_tasks"] != list(self.development) or previous["repeats"] != 1
                or previous["requested_runs"] != len(candidate_ids) * len(self.development)):
            self.reject("Recovery requires the original first candidate batch, in its frozen source and task order.")
        expected = [dict(candidate_id=candidate, task_id=task, draw=draw, repeat=0,
                         directory=f"run-{draw * len(candidate_ids) + offset:04d}", status="not_started")
                    for draw, task in enumerate(self.development)
                    for offset, candidate in enumerate(candidate_ids[draw % len(candidate_ids):]
                                                       + candidate_ids[:draw % len(candidate_ids)])]
        identity = ("candidate_id", "task_id", "draw", "repeat", "directory")
        if (len(previous["runs"]) != len(expected) or any(
                any(row.get(key) != planned[key] for key in identity)
                for row, planned in zip(previous["runs"], expected))):
            raise HostFault("Recovery evaluation row identities or order changed")
        sources = {candidate: dict(path=f"sources/{candidate}.py", sha256=digest(self.source(candidate).encode()))
                   for candidate in candidate_ids}
        if previous["sources"] != sources or any(
                (original / snapshot["path"]).read_bytes() != self.source(candidate).encode()
                for candidate, snapshot in sources.items()):
            raise HostFault("Recovery evaluation source differs from the restored candidate")
        carried, failed = [], []
        for row, planned in zip(previous["runs"], expected):
            run = original / row["directory"]
            if row["status"] == "not_started":
                if not failed or run.exists():
                    raise HostFault("Recovery requires one closed failure followed by untouched unstarted rows")
                continue
            if failed or row.get("adjudication") is not None:
                raise HostFault("Recovery accepts only a completed prefix before one infrastructure failure")
            result, trace = read(run / "result.json"), read(run / "trace.json")
            if (any(result.get(key) != row.get(key) for key in result if key != "elapsed_seconds")
                    or trace["limits"] != vars(self.task_limits)
                    or trace["exposed"] != self.experiment["exposed"]
                    or (run / "controller.py").read_bytes() != self.source(row["candidate_id"]).encode()):
                raise HostFault("Recovery row differs from its frozen result, limits, boundary, or source")
            if row["status"] in {"operational_failure", "host_fault", "verifier_failure"}:
                if row.get("verification_verdict") is not None:
                    raise HostFault("An infrastructure retry must retain an unscored prior attempt")
                planned["prior_attempt"] = dict(evaluation_id=previous["evaluation_id"],
                    directory=row["directory"], status=row["status"],
                    result_sha256=digest((run / "result.json").read_bytes()),
                    accounting="The original attempt and its usage are retained in the private prior campaign ledger.")
                failed.append(row["directory"])
                continue
            analysis = read(run / "jev.json")
            if (row.get("verification_verdict") not in {"pass", "fail"}
                    or row["status"] in {"running", "interrupted"} or trace["status"] != row["status"]
                    or analysis["configuration"] != self.jev_configuration or analysis["status"] != "completed"
                    or any(segment["status"] != "completed" for segment in analysis["segments"])
                    or analysis["source_trace_sha256"] != digest((run / "trace.json").read_bytes())):
                raise HostFault("A carried development row requires an official score and complete exact Jev evidence")
            planned.clear()
            planned.update(copy.deepcopy(row))
            carried.append(row["directory"])
        if len(failed) != 1:
            raise HostFault("Recovery requires exactly one closed infrastructure failure")
        new_runs = len(expected) - len(carried)
        if self.remaining_task_runs is not None and new_runs > self.remaining_task_runs:
            self.reject(f"Recovery requires {new_runs} new runs; only {self.remaining_task_runs} remain.")
        directory = self.public / "evaluations" / evaluation_id
        directory.mkdir()
        for snapshot in sources.values():
            destination = directory / snapshot["path"]
            destination.parent.mkdir(exist_ok=True)
            shutil.copy2(original / snapshot["path"], destination)
        for name in carried:
            shutil.copytree(original / name, directory / name)
        evaluation = dict(evaluation_id=evaluation_id, candidate_ids=list(candidate_ids), sources=sources,
            sampled_tasks=list(self.development), repeats=1, requested_runs=len(expected), status="running", runs=expected,
            recovery=dict(source_evaluation=previous["evaluation_id"],
                source_result_sha256=digest((original / "result.json").read_bytes()),
                carried_run_directories=carried, restarted_infrastructure_runs=failed, new_requested_runs=new_runs,
                accounting="Carried records are exact prior observations and incur no new task or Jev dispatch. "
                           "All prior attempts remain charged once in the private prior campaign ledger."))
        self.state["evaluations"].append(evaluation)
        self.state["carried_development_runs"] = len(carried)
        self.recovery_evaluation = None
        self.save()
        return evaluation

    def run_evaluation(self, evaluation):
        try:
            feedback = super().run_evaluation(evaluation)
        finally:
            if self.state.get("carried_development_runs"):
                evidence = research_evidence(self.state, episode=self.output.name)
                evidence["carried_development_runs"] = self.state["carried_development_runs"]
                evidence["interpretation"] += (
                    " carried_task_runs counts the shared opening only; carried_development_runs counts exact "
                    "completed development records retained during recovery. Neither adds new dispatches or "
                    "charges usage to this episode; their costs remain in the prior campaign ledger.")
                atomic_json(self.public / "evidence.json", evidence)
        if self.state.get("carried_development_runs"):
            feedback["carried_development_runs"] = self.state["carried_development_runs"]
            if evaluation.get("recovery"):
                feedback["recovery"] = evaluation["recovery"]
        return feedback

    def select(self, arguments, timeout):
        ranking = self.selection_ranking()
        if not ranking or arguments.get("candidate_id") != ranking[0]["candidate_id"]:
            self.reject("Choose the host-ranked best candidate across all complete opening and research batches.")
        return ResearchSession.select(self, arguments, timeout)

    def finish(self, arguments, timeout):
        if self.research_only:
            notes = self.public / "notes.md"
            if not notes.is_file() or not notes.read_text().strip():
                self.reject("Write your research findings and uncertainties using write_notes before finishing.")
        return ResearchSession.finish(self, arguments, timeout)

    def tools(self):
        descriptions = dict(
            save_candidate="Save immutable Python source and its improvement rationale. Exact duplicates reuse "
                           "their existing ID; previously evaluated IDs cannot be evaluated again. The two "
                           "batches allow at most three then two new sources. No new source is required.",
            evaluate="Evaluate every pending newly saved source on all ten frozen tasks, n=10, repeats=1. "
                     "Never rerun L0, L1, or previously evaluated sources. Costs ten runs per new source. "
                     "The first new source is only the within-batch comparison reference. Complete mandatory "
                     "Jev analysis before feedback. Infrastructure, verifier, or Jev failure stops the arm. "
                     "Return the batch ranking and descriptive selection ranking including historical opening.",
            select="Choose the host-ranked best source across complete opening and research batches. "
                   "The selection ranking includes historical evidence and does not establish a paired gain.",
            finish="Submit the host-ranked best source across complete opening and research batches and your "
                   "evidence-based reason. A successful receipt ends research. You may retain the opening "
                   "winner without saving or evaluating new sources when no worthwhile hypothesis exists.")
        if self.research_only:
            descriptions.update(
                save_candidate="Save an untested Loop proposal and evidence-based rationale. At most five new "
                               "sources; no quota. Evaluation is disabled, so new proposals cannot be selected.",
                finish="Finish this research-only review with the existing opening winner and your conclusions. "
                       "First write findings, evidence, proposed changes and uncertainties using write_notes. "
                       "No new Loop will run; saved proposals remain untested.")
        return tuple(replace(tool, description=descriptions[tool.capability_id])
                     if tool.capability_id in descriptions else tool for tool in super().tools()
                     if not (self.research_only and tool.capability_id == "evaluate"))

    def import_opening(self):
        previous = self.opening
        old_setup = read(previous / "private/setup.json")
        setup = read(self.private / "setup.json")
        keys = ["development", "task_limits", "worker_image", "components", "jev", "model", "user_model"]
        if self.opening_import:
            if old_setup["experiment"]["exposed"] != setup["experiment"]["exposed"]:
                raise ValueError("Historical opening component boundary differs")
        else:
            keys.extend(("seed", "experiment"))
        for key in keys:
            if old_setup[key] != setup[key]:
                raise ValueError("Shared opening settings differ: " + key)
        original = previous / "public/evaluations/e0000"
        batch = read(original / "result.json")
        if (batch["candidate_ids"] != self.initial_candidates
                or set(batch["sources"]) != set(self.initial_candidates)
                or batch["sampled_tasks"] != list(self.development) or batch["repeats"] != 1
                or batch["status"] != "settled"):
            raise ValueError("Shared opening must be the complete supplied-source comparison")
        expected = [(candidate, task, draw, 0, f"run-{draw * len(self.initial_candidates) + offset:04d}")
                    for draw, task in enumerate(self.development)
                    for offset, candidate in enumerate(self.initial_candidates[draw % len(self.initial_candidates):]
                                                       + self.initial_candidates[:draw % len(self.initial_candidates)])]
        actual = [(row["candidate_id"], row["task_id"], row["draw"], row["repeat"], row["directory"])
                  for row in batch["runs"]]
        if actual != expected:
            raise ValueError("Shared opening task order differs from the frozen comparison")
        for candidate, snapshot in batch["sources"].items():
            source = (original / snapshot["path"]).read_bytes()
            if digest(source) != snapshot["sha256"] or source != self.source(candidate).encode():
                raise ValueError("Shared opening source changed: " + candidate)
        for row in batch["runs"]:
            run = original / row["directory"]
            result, trace, analysis = (read(run / name) for name in ("result.json", "trace.json", "jev.json"))
            historical = (self.opening_import["rows"][row["directory"]] if self.opening_import else
                          dict(limits=vars(self.task_limits), adjudication=None))
            adjudicated = bool(historical["adjudication"])
            if (evaluation_verdict(row) not in {"pass", "fail"}
                    or row.get("adjudication") != historical["adjudication"]
                    or (row["status"] == "interrupted" and not adjudicated)
                    or row["status"] in {"not_started", "running", "host_fault",
                                         "operational_failure", "verifier_failure"}
                    or any(result.get(key) != row.get(key) for key in ("task_id", "status", "verification_verdict"))
                    or trace["limits"] != historical["limits"]
                    or analysis["configuration"] != self.jev_configuration
                    or analysis["status"] != "completed"
                    or any(segment["status"] != "completed" for segment in analysis["segments"])
                    or analysis["source_trace_sha256"] != digest((run / "trace.json").read_bytes())):
                raise ValueError("Shared opening row is incomplete or differs from its frozen records: " + row["directory"])
        shutil.copytree(original, self.public / "evaluations/e0000")
        self.state["evaluations"].append(batch)
        self.state["carried_task_runs"] = len(batch["runs"])
        self.save()
        return batch


def _native(configuration, binary_root, *, auth_path=None, session=None):
    from loopblox.research.codex import CodexResearcher
    return CodexResearcher(
        model=configuration["model"], reasoning_effort=configuration["reasoning_effort"],
        binary_root=Path(binary_root), container_image=configuration["container_image"],
        auth_path=auth_path, public_root=session.public if session else None,
        scratch_path=session.workspace.scratch if session else None)


def _freeze_opening(root, previous):
    """Snapshot only the explicitly requested opening, never the old researcher's work."""
    destination = root / "private/imported-opening"
    original = previous / "research/public/evaluations/e0000"
    batch = read(original / "result.json")
    shutil.copytree(original, destination / "public/evaluations/e0000")
    (destination / "private").mkdir()
    shutil.copy2(previous / "research/private/setup.json", destination / "private/setup.json")
    shutil.copy2(previous / "protocol.json", destination / "private/source-protocol.json")
    return dict(path=str(destination.relative_to(root)), source_campaign=previous.name,
        source_evaluation="research/public/evaluations/e0000", source_seed=read(previous / "protocol.json")["seed"],
        authorization="User explicitly requested reuse of the existing 20 opening runs for both researchers.",
        interpretation="Historical opening evidence has mixed execution limits and a user-adjudicated failure. "
                       "It is not a uniform-budget comparison. Original official missing scores remain missing. "
                       "Both researchers receive identical evidence; all new evaluations use the current task caps.",
        accounting="Historical task and Jev usage remains owned by the source campaign and its prior-attempt "
                   "ledgers. Copying evidence makes no new task or Jev calls; arm ledgers charge only new work.",
        rows={row["directory"]: dict(limits=read(original / row["directory"] / "trace.json")["limits"],
                                     adjudication=row.get("adjudication")) for row in batch["runs"]},
        files={str(path.relative_to(destination)): digest(path.read_bytes())
               for path in sorted(destination.rglob("*")) if path.is_file()})


def _freeze_previous(root, previous, protocol):
    """Retain the interrupted control attempt and Codex's completed, untested own work."""
    old, result = read(previous / "protocol.json"), read(previous / "result.json")
    if (result["status"] != "interrupted" or result.get("error_type") != "KeyboardInterrupt"
            or set(result["arms"]) != {"codex"} or result.get("failed_stage") != "codex"):
        raise ValueError("This amendment imports only the user-interrupted first Codex arm")
    for key in ("task_ids", "seed", "worker_image", "model", "user_model", "task_limits", "sources", "jev"):
        if old[key] != protocol[key]:
            raise ValueError("Amendment changed a retained execution setting: " + key)
    for key in ("arm_order", "native_configuration", "opening_import"):
        if old["comparison"][key] != protocol["comparison"][key]:
            raise ValueError("Amendment changed common evidence or native runtime: " + key)
    prior = previous / "arms/codex/research"
    state = read(prior / "private/state.json")
    controls = state["evaluations"][0]["candidate_ids"]
    candidates = [candidate for candidate in state["candidates"] if candidate not in controls]
    if state.get("selection_reason") or len(candidates) > release_research.ROUND_CANDIDATE_CAPS[0]:
        raise ValueError("Amendment requires unsubmitted first-batch candidate work")
    for batch in state["evaluations"][1:]:
        for row in batch["runs"]:
            if row["status"] != "not_started" and (row["candidate_id"] not in controls
                    or row["status"] != "interrupted" or row.get("verification_verdict") is not None):
                raise ValueError("This amendment cannot import candidate feedback or completed control reruns")
    receipts = []
    for path in sorted((prior / "private/codex-materials/receipts").glob("*.json")):
        receipt = read(path)
        if receipt["request"]["tool"] != "save_candidate" or receipt["receipt"]["status"] != "ok":
            raise ValueError("Only completed own candidate-save receipts may be restored")
        candidate = receipt["receipt"]["result"]["candidate_id"]
        arguments = receipt["request"]["arguments"]
        source = (prior / "public/candidates" / (candidate + ".py")).read_text()
        rationale = read(prior / "public/candidates" / (candidate + ".json"))
        if (candidate not in candidates or arguments != dict(source=source, rationale=rationale["rationale"])
                or digest(source.encode()) != rationale["source_sha256"]):
            raise ValueError("Prior candidate save receipt differs from its immutable source")
        receipts.append(path.name)
    if len(receipts) != len(candidates):
        raise ValueError("Every prior candidate requires its completed save receipt")
    destination = root / "private/prior-campaign"
    shutil.copytree(previous / "arms/codex", destination / "arms/codex")
    for name in ("protocol.json", "result.json", "launch.json"):
        shutil.copy2(previous / name, destination / name)
    prior_result = result["arms"]["codex"]
    prior_cap = old["logical_caps"]["task_runs"]
    if prior_cap is not None and prior_result["task_runs"] + protocol["research_budgets"]["task_runs"] > prior_cap:
        raise ValueError("Amendment would exceed the previous logical task allowance")
    return dict(path=str(destination.relative_to(root)), source_campaign=previous.name,
        reason="User changed future evaluations to newly proposed Loops only; no L0/L1 reruns.",
        candidate_ids=candidates, completed_save_receipts=receipts,
        prior_task_runs=prior_result["task_runs"], prior_usage=prior_result["usage"], prior_logical_task_cap=prior_cap,
        accounting="Retain prior interrupted control and all native usage once. Each arm may dispatch up to "
                   "50 new candidate tasks; Codex also retains its prior control attempt, below its original "
                   "100-task cap. Restored candidates consume the original three-then-two source allowance.",
        files={str(path.relative_to(destination)): digest(path.read_bytes())
               for path in sorted(destination.rglob("*")) if path.is_file()})


def _freeze_recovery(root, previous, protocol):
    """Preserve the failed first candidate batch and its spend before a fresh attempt."""
    old, result = read(previous / "protocol.json"), read(previous / "result.json")
    if (result["status"] != "interrupted" or result.get("failed_stage") != "codex"
            or set(result["arms"]) != {"codex"} or old["comparison"].get("recovery")):
        raise ValueError("Recovery requires the stopped first Codex candidate batch")
    for key in ("task_ids", "seed", "worker_image", "model", "user_model", "task_limits", "sources", "jev"):
        if old[key] != protocol[key]:
            raise ValueError("Recovery changed a frozen execution setting: " + key)
    for key in ("native_configuration", "arm_order", "opening_import", "amendment"):
        if old["comparison"][key] != protocol["comparison"][key]:
            raise ValueError("Recovery changed prior work or shared inputs: " + key)
    arm = result["arms"]["codex"]
    research = previous / "arms/codex/research"
    state = read(research / "private/state.json")
    failures = [call for call in read(research / "private/research-usage.json")["calls"]
                if call.get("failure_code")]
    if (arm.get("research_status") != "operational_failure" or len(state["evaluations"]) != 2
            or not failures or failures[-1]["failure_code"] != "service_not_ready"):
        raise ValueError("Recovery requires the recorded service_not_ready failure")
    remaining = old["research_budgets"]["task_runs"] - arm["task_runs"]
    if remaining <= 0:
        raise ValueError("No candidate task allowance remains")
    destination = root / "private/recovery-attempt"
    shutil.copytree(previous / "arms/codex", destination / "arms/codex")
    for name in ("protocol.json", "result.json", "launch.json"):
        shutil.copy2(previous / name, destination / name)
    return dict(path=str(destination.relative_to(root)), source_campaign=previous.name,
        failure_code="service_not_ready", not_before=(previous / "result.json").stat().st_mtime + 14 * 60,
        timing_basis="Fourteen minutes after the closed top-level result file timestamp",
        prior_task_runs=arm["task_runs"], prior_usage=arm["usage"], remaining_task_runs=remaining,
        evaluation="arms/codex/research/public/evaluations/e0001",
        policy="Fresh researcher and workers. Preserve closed scored rows exactly; retry only infrastructure "
               "failure rows and dispatch unstarted rows. Original failures and spend remain private and charged. "
               "Release no incomplete batch feedback. No control or ordinary task failure reruns.",
        files={str(path.relative_to(destination)): digest(path.read_bytes())
               for path in sorted(destination.rglob("*")) if path.is_file()})


class AmendedCodexResearcher:
    """Restore only this researcher's completed work after freezing the common base input."""

    def __init__(self, native, session, previous, amendment, recovery=None, recovery_root=None):
        self.native, self.session, self.previous, self.amendment = native, session, previous, amendment
        self.recovery, self.recovery_root = recovery, recovery_root

    def run(self, task, tools, meter, trace_path):
        session, prior = self.session, self.previous / "arms/codex/research"
        for candidate in self.amendment["candidate_ids"]:
            source = (prior / "public/candidates" / (candidate + ".py")).read_text()
            rationale = read(prior / "public/candidates" / (candidate + ".json"))
            saved = session.save_candidate(dict(source=source, rationale=rationale["rationale"]), 0)
            if saved["candidate_id"] != candidate or not saved["created"]:
                raise HostFault("Restored own candidate identity changed")
        shutil.copytree(prior / "private/research-work", session.workspace.scratch, dirs_exist_ok=True)
        receipts = session.workspace.scratch / "prior-campaign/receipts"
        receipts.mkdir(parents=True)
        for name in self.amendment["completed_save_receipts"]:
            shutil.copy2(prior / "private/codex-materials/receipts" / name, receipts / name)
        task = copy.deepcopy(task)
        task["own_prior_work"] = dict(source_campaign=self.amendment["source_campaign"],
            candidate_ids=self.amendment["candidate_ids"], receipts="/work/prior-campaign/receipts",
            notice="These are your own completed candidate saves and scratch from before the user's policy "
                   "amendment. They count toward your candidate allowance and remain untested. Earlier plans "
                   "to rerun L0/L1 or submit only the latest batch winner are superseded by release-policy.json. "
                   "No previous evaluation receipt or partial task feedback is imported. Make a new request "
                   "under the current policy; you may evaluate the pending sources or finish without new runs.")
        task["initial_evaluation"]["next_batch"] = session.next_batch()
        if self.recovery:
            session.max_task_runs = self.recovery["remaining_task_runs"]
            session.recovery_evaluation = self.recovery_root / self.recovery["evaluation"]
            task["max_development_task_runs"] = session.max_task_runs
            task["initial_evaluation"].update(remaining_task_runs=session.remaining_task_runs,
                                             next_batch=session.next_batch())
            task["own_prior_work"]["recovery"] = dict(
                source_campaign=self.recovery["source_campaign"], policy=self.recovery["policy"],
                remaining_task_runs=session.max_task_runs,
                pending_candidate_order=read(session.recovery_evaluation / "result.json")["candidate_ids"])
            setup = read(session.private / "setup.json")
            setup["research_budgets"]["task_runs"] = session.max_task_runs
            setup["recovery"] = task["own_prior_work"]["recovery"]
            atomic_json(session.private / "setup.json", setup)
            policy = read(session.public / "release-policy.json")
            policy.update(task_cap=session.max_task_runs, recovery=task["own_prior_work"]["recovery"])
            atomic_json(session.public / "release-policy.json", policy)
        atomic_json(session.public / "own-prior-work.json", task["own_prior_work"])
        atomic_json(session.public / "evidence.json", research_evidence(session.state, episode=session.output.name))
        atomic_json(session.private / "research-task.json", task)
        return self.native.run(task, tools, meter, trace_path)


def _prepare_completed_recovery(args):
    """Keep submitted stages exact and restart LoopBlox only before candidate work begins."""
    previous, root = args.completed_from.resolve(), args.output.resolve()
    protocol, result = read(previous / "protocol.json"), read(previous / "result.json")
    completed = result.get("arms", {}).get("codex", {})
    if (result.get("status") != "interrupted" or result.get("failed_stage") != "loopblox"
            or result.get("opening", {}).get("status") != "complete"
            or completed.get("status") != "complete" or completed.get("research_status") != "completed"):
        raise ValueError("Completed-stage recovery requires the submitted Codex arm")
    failed_research = previous / "arms/loopblox/research"
    prior_attempts = copy.deepcopy(protocol["comparison"].get("completed_recovery", {}).get("prior_research_attempts", []))
    not_before = None
    if failed_research.exists():
        failed_state = read(failed_research / "private/state.json")
        trace = read(failed_research / "private/research-trace.json")
        failed_arm = result["arms"].get("loopblox", {})
        if (trace.get("code") != "service_not_ready" or failed_arm.get("research_status") != "operational_failure"
                or failed_arm.get("task_runs") != 0 or failed_state.get("task_runs_used") != 0
                or failed_state.get("candidates") != ["c0000", "c0001"]
                or len(failed_state.get("evaluations", [])) != 1 or failed_state.get("selection_reason")
                or any(protocol["research_budgets"][key] is not None
                       for key in ("seconds", "model_calls", "output_tokens"))):
            raise ValueError("Researcher startup recovery requires service_not_ready before candidate work, with uncapped shared usage")
        not_before = (previous / "result.json").stat().st_mtime + 14 * 60
        if time.time() < not_before:
            raise ValueError("The service_not_ready recovery wait has not elapsed")
    elif result.get("error") != "Start a new process when changing the frozen τ² environment":
        raise ValueError("Unstarted LoopBlox recovery requires the recorded environment initialization failure")
    state = read(previous / "arms/codex/research/private/state.json")
    selected = completed["selected"]
    if (state.get("research_status") != "completed" or not state.get("selection_reason")
            or state.get("frozen_candidate") != selected["candidate_id"]
            or digest((previous / selected["path"]).read_bytes()) != selected["sha256"]):
        raise ValueError("Completed Codex submission differs from its frozen source")
    for name, expected in protocol["implementation_sha256"].items():
        if digest((previous / "implementation" / name).read_bytes()) != expected:
            raise ValueError("Completed campaign implementation changed: " + name)
    excluded = {"implementation", "protocol.json", "result.json", "launch.json", "process.log"}
    shutil.copytree(previous, root, ignore=lambda path, names: excluded & set(names)
                    if Path(path) == previous else set())
    archive = root / "private/completed-recovery" / previous.name
    archive.mkdir(parents=True)
    for name in ("protocol.json", "result.json", "launch.json", "process.log"):
        shutil.copy2(previous / name, archive / name)
    shutil.copytree(previous / "implementation", archive / "implementation")
    if failed_research.exists():
        (archive / "arms").mkdir()
        shutil.move(str(root / "arms/loopblox"), str(archive / "arms/loopblox"))
        prior_attempts.append(dict(source_campaign=previous.name,
            result=str((archive / "arms/loopblox/result.json").relative_to(root)),
            failure_code="service_not_ready", task_runs=0,
            accounting="Retain this attempt's researcher calls and charged time once; no candidate work is restored."))
    shutil.copytree(previous / "implementation", root / "implementation")
    launcher = "loopblox/experiments/researcher_comparison.py"
    (root / "implementation" / launcher).write_bytes(Path(__file__).read_bytes())
    old_hash = protocol["implementation_sha256"][launcher]
    protocol["implementation_sha256"][launcher] = digest((root / "implementation" / launcher).read_bytes())
    if getattr(args, "research_only", False):
        protocol["comparison"]["loopblox_research_only"] = dict(
            authorization="User requested completion of the own researcher's analysis without running any new Loop.",
            new_task_runs=0, new_jev_calls=0,
            policy="Retain opening evidence; analyze, write notes and optionally save untested source proposals. "
                   "Remove evaluate from disclosed tools and reject host evaluation requests. Finish with the "
                   "existing scored opening winner; no untested proposal is promoted.",
            input_snapshot="private/loopblox-research-only-input.json",
            comparison_limit="LoopBlox now completes a research-only review; this is no longer an equal-opportunity "
                             "two-researcher optimization comparison. Completed Codex results remain exact.")
    protocol["comparison"]["completed_recovery"] = dict(source_campaign=previous.name,
        source_record=str((archive / "result.json").relative_to(root)), stages=["opening", "codex"],
        remaining_stages=["loopblox"],
        prior_research_attempts=prior_attempts, not_before=not_before,
        repair="Run each opening and researcher stage in a fresh frozen CLI process using common.run_stage. "
               "The completed Codex arm, common opening, base input and all prior costs are retained exactly. "
               "Prior LoopBlox research-only attempts are retained privately; no new task was dispatched. "
               + ("The user's research-only amendment permits zero new tasks and a separate amended input snapshot. "
                  if protocol["comparison"].get("loopblox_research_only") else
                  "A fresh researcher receives the common initial input; its original 50-task allowance is unchanged. ")
               + "No control reruns.",
        implementation_changes={launcher: dict(previous=old_hash, current=protocol["implementation_sha256"][launcher])},
        retained_files={str(path.relative_to(root)): digest(path.read_bytes())
                        for path in sorted(root.rglob("*")) if path.is_file()
                        and not path.is_relative_to(root / "implementation")})
    atomic_json(root / "protocol.json", protocol)
    atomic_json(root / "result.json", dict(status="prepared", opening=result["opening"],
        arms=dict(codex=completed), final_task_runs=0, arm_order=protocol["comparison"]["arm_order"]))
    return protocol


def prepare(args):
    """Reuse release preparation, then freeze the two researcher configurations and order."""
    if getattr(args, "completed_from", None):
        return _prepare_completed_recovery(args)
    if args.native_binaries is None:
        raise ValueError("Preparation requires --native-binaries for the pinned Linux Codex runtime")
    binary_root = args.native_binaries.resolve()
    native_settings = dict(model=args.codex_model, reasoning_effort=args.codex_effort,
                           container_image=image_id(args.native_image or args.worker_image or "python:3.12-slim"))
    native_configuration = _native(native_settings, binary_root).configuration()
    protocol = release_research.prepare(argparse.Namespace(
        output=args.output, suite=args.suite, worker_image=args.worker_image, seed=args.seed,
        previous=None, continue_opening=False))
    root = args.output.resolve()
    atomic_json(root / "result.json", dict(status="preparing"))
    shutil.copytree(binary_root, root / "private/native-binaries")
    if _native(native_settings, root / "private/native-binaries").configuration() != native_configuration:
        raise ValueError("Copied native runtime differs from its frozen configuration")
    order = list(ARMS)
    random.Random(protocol["seed"]).shuffle(order)
    post_opening_runs = len(protocol["task_ids"]) * sum(protocol["candidate_caps"])
    protocol["research_budgets"]["task_runs"] = post_opening_runs
    protocol["logical_caps"]["task_runs"] = post_opening_runs
    protocol["experiment"]["question"] = (
        "Research a reusable telecom Loop for an educational open-source release using the ten frozen official "
        "training tasks. Both supplied sources already have a shared twenty-run opening with Jev evidence: "
        "L0 is reactive; L1 critiques completion proposals and returns on explicit terminal observations. "
        "This is a joint Loop contrast, not a pure Critique ablation. Read release-policy.json and "
        "component-contracts.md. Use Jev's noisy judgments to locate trace evidence worth inspecting, not as "
        "task scores or proof of causes. Identify a worthwhile, testable improvement hypothesis before saving "
        "a new source; no candidate count, component diversity, or additional evaluation is required. "
        "There are at most two research evaluations, both n=10 and repeats=1. For the first, save up to three "
        "new sources; for the second, save up to two additional new sources. Each evaluation includes only "
        "all of that batch's pending saved sources. Never rerun L0, L1, or any previously evaluated source, "
        "including the first batch's winner. Unused first-batch slots do not transfer. The host rejects "
        "control and repeat evaluation requests before dispatch. The next_batch receipt gives pending IDs "
        "and remaining opportunities. A modified source is a new candidate; exact duplicates keep their ID. "
        "The host supplies release_ranking for the just-completed batch and selection_ranking for every "
        "complete candidate evaluation so far, including opening. best_candidate refers to that overall "
        "selection. " + release_research.RANKING_RULE + " " + SELECTION_INTERPRETATION + " "
        "Submit this host-ranked best source with finish and an evidence-based reason. Retaining the opening "
        "winner is valid, including finishing with zero new candidates or task runs when no worthwhile "
        "improvement hypothesis exists. Explain uncertainty and untested directions. Do not encode task IDs, "
        "customers, answers, or research history in source. Research ends before final comparison; no test "
        "tasks or feedback are available. This command stops for human review and never dispatches final tasks.")
    protocol["comparison"] = dict(
        arm_order=order, native_configuration=native_configuration,
        native_binary_path="private/native-binaries", common_opening="opening/research",
        accounting="Common opening charged once; arm ledgers contain only subsequent dispatches. "
                   "Researcher model usage is separate and is not equalized between systems.",
        evaluation_policy="Only newly proposed, previously unevaluated sources: up to three in batch one, "
                          "two in batch two. No L0/L1 or previous winner reruns; zero new evaluations is valid.",
        selection_interpretation=SELECTION_INTERPRETATION,
        scope="Complete researcher systems, including their model and native harness; "
              "one pair is descriptive and does not isolate a harness effect.")
    if getattr(args, "opening", None):
        imported = _freeze_opening(root, args.opening.resolve())
        protocol["comparison"]["opening_import"] = imported
        protocol["experiment"]["question"] += (
            " The user authorized reuse of the historical common opening. Read opening-provenance.json. "
            + imported["interpretation"])
    if getattr(args, "previous", None):
        amendment = _freeze_previous(root, args.previous.resolve(), protocol)
        protocol["comparison"]["amendment"] = amendment
        protocol["logical_caps"]["task_runs"] = amendment["prior_logical_task_cap"]
    if getattr(args, "recover", None):
        protocol["comparison"]["recovery"] = _freeze_recovery(root, args.recover.resolve(), protocol)
    final = protocol["proposed_final_comparison"]
    final["sources"] = ["L0", "L1", *("L2-" + arm for arm in ARMS)]
    final["max_task_runs"] = len(final["task_ids"]) * final["repeats"] * len(final["sources"])
    protocol["stopping_point"] = "Both researchers closed; awaiting_review. No final task dispatch."
    atomic_json(root / "protocol.json", protocol)
    atomic_json(root / "result.json", dict(status="prepared", opening=None, arms={},
                                           final_task_runs=0, arm_order=order))
    return protocol


def _session(root, protocol, label, *, common_opening=None, research_only=False):
    client, user = clients(protocol)
    manifest = load_suite(root / "suite")
    development, holdout = release_research.release_tasks(root / "suite", manifest)
    if ([task["task_id"] for task in development] != protocol["task_ids"]
            or [task["task_id"] for task in holdout] != protocol["reserved_holdout_task_ids"]):
        raise ValueError("Frozen comparison task membership changed")
    limits = Limits(**protocol["task_limits"])
    # The runner cannot dispatch any official test task, even through a host tool.
    admitted = {**manifest, "tasks": development}
    runner = Tau2Runner(root / "suite", admitted, client, user, protocol["worker_image"], limits,
                       root / "private/environments" / label)
    sources = {}
    for name, source in protocol["sources"].items():
        content = (root / source["path"]).read_text()
        if digest(content.encode()) != source["sha256"]:
            raise ValueError("Frozen supplied source changed: " + name)
        sources[name] = content
    budget = protocol["research_budgets"]
    experiment = copy.deepcopy(protocol["experiment"])
    if research_only:
        experiment["question"] += (
            " USER AMENDMENT: Research-only review. Do not run or request any new Loop evaluation. "
            "Analyze the existing opening and Jev evidence, write conclusions and concrete proposed changes "
            "to notes.md, and optionally save untested source proposals. Then finish with the existing "
            "opening winner. Do not claim new proposals improve scores; no new tasks are authorized.")
    cls = SharedOpeningSession if common_opening else ReleaseResearchSession
    session = cls(output=root / label / "research", development=tuple(protocol["task_ids"]), holdout=(),
        **(dict(common_opening=common_opening,
                opening_import=protocol["comparison"].get("opening_import"), research_only=research_only)
           if common_opening else {}),
        run_task=runner, research_client=client, worker_image=protocol["worker_image"],
        setup=dict(model=protocol["model"], user_model=protocol["user_model"],
                   comparison_protocol_sha256=digest((root / "protocol.json").read_bytes())),
        experiment=experiment, baseline_source=sources["L0"], starting_source=sources["L1"],
        max_task_runs=budget["task_runs"] if common_opening else len(sources) * len(development),
        research_seconds=budget["seconds"], research_output_tokens=budget["output_tokens"],
        research_model_calls=budget["model_calls"], task_limits=limits,
        seed=protocol["seed"], fixed_task_batch=True, opening_n=len(development))
    if session.jev_configuration != protocol["jev"]:
        raise ValueError("Jev configuration differs from the frozen comparison")
    return session


def _usage(session):
    calls = session.meter.calls if hasattr(session, "meter") else []
    groups = {name: [] for name in ("task_agent", "simulated_user", "jev", "researcher", "other")}
    for call in calls:
        role = call["request"].get("role")
        category = ("researcher" if call["scope"] == "researcher" else
                    role if role in {"simulated_user", "jev"} else
                    "task_agent" if role is None else "other")
        groups[category].append(call)
    return dict(host_gateway=model_usage(calls), **{name: model_usage(items) for name, items in groups.items()})


def _opening(root, protocol):
    imported = protocol["comparison"].get("opening_import")
    session = _session(root, protocol, "opening", common_opening=root / imported["path"] if imported else None)
    session.meter = ModelMeter(session.private / "research-usage.json", **session.budgets)
    session.state["status"] = "researching"
    session.save()
    started = time.monotonic()
    result = dict(status="running")
    try:
        receipt = session.evaluate(dict(candidate_ids=session.initial_candidates, n=len(session.development)), 0)
        session.state["status"] = "opening_complete"
        result.update(status="complete", artifact="opening/research/public/" + receipt["artifact"],
                      ranking=receipt["release_ranking"])
    except BaseException as error:
        session.state["status"] = "interrupted"
        result.update(status="interrupted", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        session.save()
        result.update(task_runs=session.state["task_runs_used"], usage=_usage(session),
                      carried_opening_runs=session.state.get("carried_task_runs", 0),
                      **(dict(provenance="opening/research/public/opening-provenance.json") if imported else {}),
                      elapsed_seconds=time.monotonic() - started)
        atomic_json(root / "opening/result.json", result)
    return result


def _arm(root, protocol, arm, auth_path):
    research_only = protocol["comparison"].get("loopblox_research_only") if arm == "loopblox" else None
    session = _session(root, protocol, "arms/" + arm,
        common_opening=root / protocol["comparison"]["common_opening"], research_only=bool(research_only))
    native = None
    if arm == "codex":
        native = _native(protocol["comparison"]["native_configuration"],
                         root / protocol["comparison"]["native_binary_path"],
                         auth_path=auth_path, session=session)
        amendment = protocol["comparison"].get("amendment")
        if amendment:
            recovery = protocol["comparison"].get("recovery")
            native = AmendedCodexResearcher(native, session, root / amendment["path"], amendment,
                recovery=recovery, recovery_root=root / recovery["path"] if recovery else None)
    result = dict(status="running")
    started = time.monotonic()
    try:
        selected = session.research(researcher=native, episode="researcher-comparison",
            input_snapshot=root / (research_only["input_snapshot"] if research_only else "private/shared-research-input.json"))
        submitted = session.state.get("research_status") == "completed" and bool(session.state.get("selection_reason"))
        if not submitted:
            raise HostFault("Research arm closed without an explicit completed submission: " + arm)
        source = session.source(selected)
        path = "controllers/L2-" + arm + ".py"
        atomic_text(root / path, source)
        result.update(status="complete", selected=dict(candidate_id=selected, path=path, sha256=digest(source.encode())),
                      reason=session.state["selection_reason"],
                      ranking=session.selection_ranking(), selection_interpretation=SELECTION_INTERPRETATION)
        if research_only:
            result.update(mode="research_only", notes="arms/loopblox/research/public/notes.md",
                          untested_proposals=session.pending_candidates(),
                          selection_interpretation="Retained opening winner; new proposals are untested and were not selected.")
    except BaseException as error:
        result.update(status="interrupted", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        usage = _usage(session)
        if arm == "codex":
            trace_path = session.private / "research-trace.json"
            trace = read(trace_path) if trace_path.is_file() else {}
            usage["researcher"] = trace.get("native_usage", dict(available=False, model_calls=None,
                input_tokens=None, output_tokens=None, cost=None,
                reason="No complete native researcher usage was recorded."))
        result.update(research_status=session.state.get("research_status"),
            task_runs=session.state["task_runs_used"], carried_opening_runs=session.state.get("carried_task_runs", 0),
            new_candidates=len(session.state["candidates"]) - len(session.initial_candidates),
            unused_candidate_slots=max(0, session.new_candidate_cap - len(session.state["candidates"])
                                       + len(session.initial_candidates)),
            remaining_task_runs=session.remaining_task_runs,
            usage=usage, elapsed_seconds=time.monotonic() - started,
            evidence=f"arms/{arm}/research/public/evidence.json")
        amendment = protocol["comparison"].get("amendment")
        if arm == "codex" and amendment:
            result.update(prior_task_runs=amendment["prior_task_runs"], prior_usage=amendment["prior_usage"],
                          restored_candidates=amendment["candidate_ids"],
                          cumulative_task_runs=amendment["prior_task_runs"] + session.state["task_runs_used"])
        recovery = protocol["comparison"].get("recovery")
        if arm == "codex" and recovery:
            result.update(recovery_prior_task_runs=recovery["prior_task_runs"],
                          recovery_prior_usage=recovery["prior_usage"],
                          carried_development_runs=session.state.get("carried_development_runs", 0),
                          cumulative_task_runs=result["cumulative_task_runs"] + recovery["prior_task_runs"])
        atomic_json(root / "arms" / arm / "result.json", result)
    return result


def _dispatch_stage(root, stage, auth_path):
    """Each stage owns one fresh process and its frozen τ² environment."""
    path = root / ("opening/result.json" if stage == "opening" else f"arms/{stage}/result.json")
    if path.exists():
        raise ValueError("Comparison stage already has a result; use a new recovery campaign")
    try:
        protocol = verify(root)
        if read(root / "result.json")["status"] != "running":
            raise ValueError("Comparison stages require their active campaign launcher")
        return (_opening(root, protocol) if stage == "opening"
                else _arm(root, protocol, stage, Path(auth_path)))
    except BaseException as error:
        # Session construction can fail before _opening/_arm establishes its result.
        if not path.exists():
            atomic_json(path, dict(status="interrupted", error_type=type(error).__name__, error=str(error)))
        raise


def _run_stage(root, stage, auth_path):
    code = run_stage([sys.executable, "-P", "-B", "-m", "loopblox.experiments.researcher_comparison",
                      "stage", str(root), "--stage", stage, "--auth-file", str(Path(auth_path).resolve())],
                     source_root=ROOT)
    path = root / ("opening/result.json" if stage == "opening" else f"arms/{stage}/result.json")
    result = read(path) if path.is_file() else {}
    if code or result.get("status") != "complete":
        detail = result.get("error") or f"child exited with code {code} without a completed result"
        raise HostFault(f"Comparison stage {stage} stopped: {detail}")
    return result


def run(root, *, auth_path):
    protocol = verify(root)
    if "comparison" not in protocol or read(root / "result.json")["status"] != "prepared":
        raise ValueError("Comparison requires its new, prepared campaign; continuations are not resumed")
    comparison = protocol["comparison"]
    completed = comparison.get("completed_recovery")
    preserved = set(completed["stages"]) if completed else set()
    if completed:
        for name, expected in completed["retained_files"].items():
            if digest((root / name).read_bytes()) != expected:
                raise ValueError("Preserved completed evidence changed: " + name)
        if completed.get("not_before") and time.time() < completed["not_before"]:
            raise ValueError("The service_not_ready recovery wait has not elapsed")
    for imported in (comparison.get("opening_import"), comparison.get("amendment"), comparison.get("recovery")):
        if not imported:
            continue
        for name, expected in imported["files"].items():
            if digest((root / imported["path"] / name).read_bytes()) != expected:
                raise ValueError("Frozen imported opening changed: " + name)
    if comparison.get("recovery") and time.time() < comparison["recovery"]["not_before"]:
        raise ValueError("The service_not_ready recovery wait has not elapsed")
    native = _native(comparison["native_configuration"], root / comparison["native_binary_path"], auth_path=auth_path)
    if native.configuration() != comparison["native_configuration"]:
        raise ValueError("Native runtime or configuration differs from the frozen comparison")
    native.validate_auth()
    selection = protocol.get("task_selection")
    if selection and digest((root / selection["path"]).read_bytes()) != selection["sha256"]:
        raise ValueError("Frozen task selection and exposure audit changed")
    state = dict(status="running", opening=None, arms={}, final_task_runs=0, arm_order=comparison["arm_order"])
    if completed:
        original = read(root / completed["source_record"])
        state.update(opening=original["opening"], arms=dict(codex=original["arms"]["codex"]),
                     preserved_completed_stages=completed["stages"],
                     completed_source_campaign=completed["source_campaign"],
                     prior_research_attempts=completed.get("prior_research_attempts", []))
    if comparison.get("amendment"):
        state["prior_task_runs"] = comparison["amendment"]["prior_task_runs"]
    if comparison.get("recovery"):
        state["prior_task_runs"] = state.get("prior_task_runs", 0) + comparison["recovery"]["prior_task_runs"]
    atomic_json(root / "result.json", state)
    stage = "opening"
    try:
        if "opening" not in preserved:
            state["opening"] = _run_stage(root, "opening", auth_path)
        atomic_json(root / "result.json", state)
        for arm in comparison["arm_order"]:
            if arm in preserved:
                continue
            stage = arm
            state["arms"][arm] = _run_stage(root, arm, auth_path)
            atomic_json(root / "result.json", state)
        identities, aliases = {}, {}
        sources = {**protocol["sources"], **{"L2-" + arm: result["selected"] for arm, result in state["arms"].items()}}
        for name, source in sources.items():
            aliases[name] = identities.setdefault(source["sha256"], name)
        input_path = "private/shared-research-input.json"
        state.update(status="awaiting_review", initial_input=dict(path=input_path,
                         sha256=digest((root / input_path).read_bytes()),
                         basis="Shared base task, tools and public files before restoring a researcher's own prior work"),
                     aliases=aliases,
                     development_task_runs=state["opening"]["task_runs"]
                         + sum(result["task_runs"] for result in state["arms"].values()))
        state["cumulative_development_task_runs"] = state["development_task_runs"] + state.get("prior_task_runs", 0)
        state["new_campaign_task_runs"] = (0 if "opening" in preserved else state["opening"]["task_runs"]) + sum(
            result["task_runs"] for arm, result in state["arms"].items() if arm not in preserved)
        if comparison.get("loopblox_research_only"):
            state["research_only_amendment"] = comparison["loopblox_research_only"]
            state["initial_input"]["basis"] = "Original common base retained; LoopBlox has the disclosed research-only amendment."
    except BaseException as error:
        state.update(status="interrupted", failed_stage=stage, error_type=type(error).__name__, error=str(error))
        failure_path = root / ("opening/result.json" if stage == "opening" else f"arms/{stage}/result.json")
        if failure_path.is_file():
            if stage == "opening":
                state["opening"] = read(failure_path)
            else:
                state["arms"][stage] = read(failure_path)
        raise
    finally:
        atomic_json(root / "result.json", state)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "stage"))
    parser.add_argument("output", type=Path)
    parser.add_argument("--stage", choices=("opening", *ARMS))
    parser.add_argument("--suite", type=Path)
    parser.add_argument("--opening", type=Path, help="Explicitly reuse this campaign's historical opening evidence")
    parser.add_argument("--previous", type=Path, help="Preserve the interrupted pre-amendment Codex work and spend")
    parser.add_argument("--recover", type=Path, help="Recover the first candidate batch after a service startup failure")
    parser.add_argument("--completed-from", type=Path,
                        help="Preserve completed opening and Codex stages; recover LoopBlox before candidate work")
    parser.add_argument("--research-only", action="store_true",
                        help="Complete only LoopBlox analysis and untested proposals; disable all new task evaluations")
    parser.add_argument("--worker-image")
    parser.add_argument("--seed", type=int, default=20260921)
    parser.add_argument("--native-binaries", type=Path)
    parser.add_argument("--native-image")
    parser.add_argument("--codex-model", default="gpt-6-astra")
    parser.add_argument("--codex-effort", default="low")
    parser.add_argument("--auth-file", type=Path,
                        default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json")
    args = parser.parse_args()
    if args.command == "prepare" and args.suite is None and args.completed_from is None:
        parser.error("prepare requires --suite or --completed-from")
    if args.research_only and (args.command != "prepare" or args.completed_from is None):
        parser.error("--research-only requires prepare --completed-from")
    if args.command == "stage" and args.stage is None:
        parser.error("stage requires --stage")
    if args.command == "prepare":
        result = prepare(args)
    elif args.command == "stage":
        result = _dispatch_stage(args.output.resolve(), args.stage, args.auth_file)
    else:
        result = run(args.output.resolve(), auth_path=args.auth_file)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
