"""Two development batches for the educational release; always stop before final comparison."""

import argparse
import math
from pathlib import Path
import shutil
import time

from loopblox import ROOT, snapshot_implementation
from loopblox.analysis import jev
from loopblox.benchmarks.run_tau2 import user_client
from loopblox.benchmarks.tau2 import Tau2Runner, load_suite
from loopblox.experiments.common import clients, read, verify
from loopblox.experiments.study import BASELINE_CONTROLLER, model_settings, native_researcher_usage
from loopblox.research.session import ResearchSession, evaluation_verdict, validate_experiment
from loopblox.runtime.controller import Limits, model_usage
from loopblox.runtime.io import atomic_json, atomic_text, digest, image_id
from loopblox.runtime.model import BudgetExhausted, ChatCompletionsClient, HostFault


BENCHMARK_DOMAIN = "telecom"
ROUND_CANDIDATE_CAPS = (3, 2)
MANUAL_CONTROLLER = ROOT / "controllers/completion_review.py"
RELEASE_TASK_LIMITS = Limits(seconds=900, actions=60, model_calls=256, output_tokens=65536)
RANKING_RULE = (
    "Rank a complete shared batch by passed tasks descending, then fully known agent input tokens ascending, "
    "then agent model calls ascending, then original candidate creation order. Explicit host-adjudicated "
    "failures count as failures, with missing official scores retained separately. Unknown token totals rank "
    "after known totals; they are never zero. Infrastructure faults or unscored rows cannot produce a winner. "
    "Jev measurements are evidence for investigation, not the score."
)


def rank_evaluation(batch, candidate_order):
    """Rank fully resolved candidates by the release's single selection rule."""
    ranking = []
    for candidate in batch["candidate_ids"]:
        rows = [row for row in batch["runs"] if row["candidate_id"] == candidate]
        if not rows or any(evaluation_verdict(row) not in {"pass", "fail"} for row in rows):
            raise ValueError("Release ranking requires complete scored candidate records")
        inputs = [row.get("agent_usage", {}).get("model_input_tokens") for row in rows]
        calls = [row.get("agent_usage", {}).get("model_calls") for row in rows]
        ranking.append(dict(candidate_id=candidate,
            passed=sum(evaluation_verdict(row) == "pass" for row in rows),
            failed=sum(evaluation_verdict(row) == "fail" for row in rows),
            official_unscored=sum(row.get("verification_verdict") is None for row in rows),
            adjudicated_failures=sum(bool(row.get("adjudication")) for row in rows),
            unscored=0, attempted=len(rows),
            statuses={status: sum(row["status"] == status for row in rows)
                      for status in sorted({row["status"] for row in rows})},
            agent_input_tokens=sum(inputs) if all(value is not None for value in inputs) else None,
            agent_model_calls=sum(calls) if all(value is not None for value in calls) else None))
    ranking.sort(key=lambda row: (-row["passed"],
        *(row[key] if row[key] is not None else float("inf")
          for key in ("agent_input_tokens", "agent_model_calls")),
        candidate_order.index(row["candidate_id"])))
    return ranking


class ReleaseResearchSession(ResearchSession):
    """Constrain existing saves, evaluations and submission to the frozen release protocol."""

    def __init__(self, *, new_candidate_cap=sum(ROUND_CANDIDATE_CAPS), opening=None, **arguments):
        self.new_candidate_cap = new_candidate_cap
        self.opening = opening
        super().__init__(**arguments)
        atomic_json(self.public / "release-policy.json", dict(
            task_ids=self.development, controls=self.initial_candidates,
            candidate_caps=ROUND_CANDIDATE_CAPS, new_candidate_cap=new_candidate_cap,
            task_cap=self.max_task_runs, ranking=RANKING_RULE,
            finish="Submit the best source in the latest complete batch; early finish is allowed.",
            evaluation="Save the complete batch before evaluate. Include L0, L1, and in round two "
                       "the first research batch's host-ranked best. Omit duplicate IDs. n=10, repeats=1."))

    def import_opening(self):
        """Carry public evidence into a fresh host session; never resume a task worker."""
        previous, amendment = self.opening
        directory = self.public / "evaluations/e0000"
        shutil.copytree(previous, directory)
        batch = read(directory / "result.json")
        self.state["evaluations"].append(batch)
        self.state["carried_task_runs"] = sum(row["status"] != "not_started" for row in batch["runs"])
        self.save()
        for row in batch["runs"]:
            if row["status"] == "not_started":
                continue
            run = directory / row["directory"]
            # The per-run result retains usage even when interruption prevented its return to evaluate.
            row.update(read(run / "result.json"))
            row["execution_limits"] = read(run / "trace.json")["limits"]
            if row["directory"] != amendment["directory"]:
                continue
            row["adjudication"] = amendment["adjudication"]
            atomic_json(run / "adjudication.json", row["adjudication"])
            try:
                jev.analyze_run(run / "trace.json", configuration=self.jev_configuration, meter=self.meter,
                                scope="e0000-" + str(batch["runs"].index(row)))
            except BudgetExhausted:
                self.state["research_status"] = "budget_exhausted"
                raise
            except Exception as error:
                self.state["research_status"] = "operational_failure"
                raise HostFault("Carried interrupted-run Jev analysis failed: " + str(error)) from error
            finally:
                if (run / "jev.json").is_file():
                    row["jev"] = jev.feedback(read(run / "jev.json"),
                        str((run / "jev.json").relative_to(self.public)), read(run / "trace.json"))
                self.save()
                atomic_json(directory / "result.json", batch)
        batch["continuation"] = amendment
        return batch

    def pending_candidates(self):
        evaluated = {candidate for batch in self.state["evaluations"] for candidate in batch["candidate_ids"]}
        return [candidate for candidate in self.state["candidates"] if candidate not in evaluated]

    def next_batch(self):
        round_index = len(self.state["evaluations"]) - 1
        required = list(self.initial_candidates)
        if round_index == 1:
            best = self.state["evaluations"][1]["release_ranking"][0]["candidate_id"]
            if best not in required:
                required.append(best)
        remaining = self.remaining_task_runs
        slots = ROUND_CANDIDATE_CAPS[round_index] if 0 <= round_index < len(ROUND_CANDIDATE_CAPS) else 0
        if remaining is not None:
            slots = max(0, min(slots, remaining // len(self.development) - len(required)))
        new_remaining = max(0, self.new_candidate_cap - len(self.state["candidates"]) + len(self.initial_candidates))
        return dict(required_candidate_ids=required, additional_candidate_slots=slots,
                    new_candidate_allowance=max(0, min(slots - len(self.pending_candidates()), new_remaining)),
                    remaining_task_runs=remaining, remaining_new_candidates=new_remaining,
                    remaining_research_batches=max(0, len(ROUND_CANDIDATE_CAPS) - round_index),
                    can_evaluate=0 <= round_index < len(ROUND_CANDIDATE_CAPS)
                        and (remaining is None or remaining >= len(required) * len(self.development)))

    def save_candidate(self, arguments, timeout):
        # ResearchSession also uses this method to save its two supplied sources.
        if hasattr(self, "initial_candidates") and self.state["evaluations"]:
            duplicate = any(self.source(cid) == arguments.get("source") for cid in self.state["candidates"])
            if not duplicate and self.next_batch()["new_candidate_allowance"] <= 0:
                self.reject("The next batch has no remaining new-source allowance. Evaluate its saved candidates "
                            "within any frozen task budget, or finish.")
        return super().save_candidate(arguments, timeout)

    def evaluate(self, arguments, timeout):
        completed_batches = len(self.state["evaluations"])
        ids = arguments.get("candidate_ids")
        required = list(self.initial_candidates)
        if completed_batches == 0:
            if ids != required:
                self.reject("The opening must evaluate exactly the two supplied sources, omitting duplicates.")
        else:
            round_index = completed_batches - 1
            if round_index >= len(ROUND_CANDIDATE_CAPS):
                self.reject("Both research batches are closed. Finish with the latest batch's best source.")
            options = self.next_batch()
            required = options["required_candidate_ids"]
            if (not isinstance(ids, list) or ids[:len(required)] != required
                    or len(ids) > len(required) + options["additional_candidate_slots"]
                    or any(cid not in ids for cid in self.pending_candidates())):
                self.reject(f"Evaluate {required} followed by this batch's saved candidates, omitting duplicate IDs; "
                            f"at most {options['additional_candidate_slots']} additional sources. "
                            "Every newly saved source must be included before another batch can start.")
        feedback = (self.run_evaluation(self.import_opening())
                    if completed_batches == 0 and self.opening else super().evaluate(arguments, timeout))
        batch = self.state["evaluations"][-1]
        if any(evaluation_verdict(row) not in {"pass", "fail"} for row in batch["runs"]):
            self.state["research_status"] = "budget_exhausted" if any(
                row["status"] == "not_started" for row in batch["runs"]) else "incomplete_evaluation"
            self.save()
            if self.state["research_status"] == "budget_exhausted":
                raise BudgetExhausted("release_batch_incomplete")
            raise HostFault("A release batch contains unscored attempts and cannot determine selection")
        ranking = rank_evaluation(batch, self.state["candidates"])
        batch["release_ranking"] = ranking
        self.state["selected"] = ranking[0]["candidate_id"]
        self.save()
        atomic_json(self.public / feedback["artifact"], batch)
        feedback.update(release_ranking=ranking, best_candidate=ranking[0]["candidate_id"],
                        remaining_research_batches=len(ROUND_CANDIDATE_CAPS) - completed_batches,
                        next_batch=self.next_batch())
        return feedback

    def initial_selection(self):
        """The release ranking owns the opening choice as well as later choices."""
        return self.state["evaluations"][0]["release_ranking"][0]["candidate_id"]

    def finish(self, arguments, timeout):
        ranking = self.state["evaluations"][-1].get("release_ranking", []) if self.state["evaluations"] else []
        if not ranking or arguments.get("candidate_id") != ranking[0]["candidate_id"]:
            self.reject("Finish requires the host-ranked best candidate from the latest complete shared batch.")
        return super().finish(arguments, timeout)


def attempt_spend(root):
    """Account only this attempt's shared ledger, never its copied predecessors."""
    protocol, result = read(root / "protocol.json"), read(root / "result.json")
    state = read(root / "research/private/state.json")
    usage = model_usage(read(root / "research/private/research-usage.json")["calls"])
    if "budget_seconds" in result:
        seconds, basis = result["budget_seconds"], "Recorded charged duration, rounded up to whole seconds"
    else:
        seconds = max(0, (root / "result.json").stat().st_mtime
                         - (root / "research/private/setup.json").stat().st_mtime
                         - usage["timeout_wait_seconds"])
        basis = "Result minus research setup file modification times, minus recorded timeout waits, rounded up"
    supplied = {entry["sha256"] for entry in protocol["sources"].values()}
    new_candidates = 0
    for candidate in state["candidates"]:
        path = root / "research/public/candidates" / (candidate + ".py")
        sha = digest(path.read_bytes())
        if sha != read(path.with_suffix(".json"))["source_sha256"]:
            raise ValueError("Prior candidate source changed: " + candidate)
        new_candidates += sha not in supplied
    return dict(spent=dict(task_runs=state["task_runs_used"], seconds=math.ceil(seconds),
                          model_calls=usage["model_calls"], output_tokens=usage["charged_output_tokens"],
                          new_candidates=new_candidates), seconds_basis=basis, usage=usage)


def previous_protocol(root):
    """Admit a stopped episode for a fresh researcher, never a Python continuation."""
    protocol, result = read(root / "protocol.json"), read(root / "result.json")
    state = read(root / "research/private/state.json")
    researcher_started = (root / "research/private/research-trace.json").exists()
    if (result["status"] != "interrupted" or state["status"] != "interrupted"
            or "budget_exhausted" in {result.get("research_status"), state.get("research_status")}
            or state.get("selection_reason")
            or (researcher_started and state.get("research_status") not in {
                "operational_failure", "host_fault", "verifier_failure"})):
        raise ValueError("Recovery requires a stopped, unsubmitted infrastructure failure; "
                         "budget exhaustion and ordinary researcher failures do not qualify")
    for name, expected in protocol["implementation_sha256"].items():
        if digest((root / "implementation" / name).read_bytes()) != expected:
            raise ValueError("Prior implementation changed: " + name)
    if digest((root / "suite/manifest.json").read_bytes()) != protocol["suite_manifest_sha256"]:
        raise ValueError("Prior suite manifest changed")
    load_suite(root / "suite")
    for entry in protocol["sources"].values():
        if digest((root / entry["path"]).read_bytes()) != entry["sha256"]:
            raise ValueError("Prior supplied source changed: " + entry["path"])
    selection = protocol.get("task_selection")
    if selection and digest((root / selection["path"]).read_bytes()) != selection["sha256"]:
        raise ValueError("Prior task selection audit changed")
    for name, expected in protocol.get("recovery", {}).get("imported_files", {}).items():
        if digest((root / name).read_bytes()) != expected:
            raise ValueError("Prior imported record changed: " + name)
    return protocol


def opening_continuation(previous, protocol):
    """Validate the explicit decision to fail one interrupted row and keep its predecessors."""
    batch = read(previous / "research/public/evaluations/e0000/result.json")
    state = read(previous / "research/private/state.json")
    ids = state["candidates"]
    if (len(state["evaluations"]) != 1 or len(ids) != 2 or batch["candidate_ids"] != ids
            or batch["sampled_tasks"] != protocol["task_ids"] or batch["repeats"] != 1):
        raise ValueError("Opening continuation requires the original fixed two-source opening")
    expected = [(cid, task, draw, 0, f"run-{draw * 2 + offset:04d}")
                for draw, task in enumerate(protocol["task_ids"])
                for offset, cid in enumerate(ids[draw % 2:] + ids[:draw % 2])]
    actual = [(row["candidate_id"], row["task_id"], row["draw"], row["repeat"], row["directory"])
              for row in batch["runs"]]
    if actual != expected:
        raise ValueError("The original opening order changed")
    for candidate, name in zip(ids, ("L0", "L1")):
        source = previous / "research/public/evaluations/e0000" / batch["sources"][candidate]["path"]
        if digest(source.read_bytes()) != protocol["sources"][name]["sha256"]:
            raise ValueError("The opening source differs from its supplied Loop")
    started = [row for row in batch["runs"] if row["status"] != "not_started"]
    if (not started or started != batch["runs"][:len(started)] or len(started) == len(actual)
            or started[-1]["status"] != "interrupted" or started[-1].get("verification_verdict") is not None
            or state["task_runs_used"] != len(started)):
        raise ValueError("Continue only a completed prefix followed by one interrupted, unscored run")
    for row in started[:-1]:
        if (row["status"] != "completed" or row.get("verification_verdict") not in {"pass", "fail"}
                or row.get("jev", {}).get("status") != "completed"):
            raise ValueError("Every earlier opening run must retain its score and completed Jev analysis")
        raw = read(previous / "research/public/evaluations/e0000" / row["directory"] / "result.json")
        if any(raw.get(key) != row.get(key) for key in ("task_id", "status", "verification_verdict")):
            raise ValueError("A completed opening row differs from its original result")
    interrupted = started[-1]
    raw = read(previous / "research/public/evaluations/e0000" / interrupted["directory"] / "result.json")
    if (raw["status"] != "interrupted" or raw.get("verification_verdict") is not None
            or raw["task_id"] != interrupted["task_id"]):
        raise ValueError("The interrupted run's raw result does not match the requested disposition")
    return dict(directory=interrupted["directory"], candidate_id=interrupted["candidate_id"],
        task_id=interrupted["task_id"], retained_runs=len(started), next_directory=batch["runs"][len(started)]["directory"],
        adjudication=dict(verdict="fail", authority="user",
            reason="User instructed that the interrupted repetitive run counts as failure; continue from the next unstarted run.",
            official_verification="Not performed; original verification_verdict remains null."),
        previous_task_limits=protocol["task_limits"], next_task_limits=vars(RELEASE_TASK_LIMITS),
        interpretation="Opening combines historical and new limits and one user-adjudicated failure. "
                       "It is exploratory evidence, not a uniform-budget comparison. Later batches share the new limits.")


def release_tasks(suite, manifest):
    """Admit only the frozen telecom development design and deterministic official scoring."""
    development = [task for task in manifest["tasks"] if task["split"] == "development"]
    holdout = [task for task in manifest["tasks"] if task["split"] == "holdout"]
    if len(development) != 10 or any(task["family"] != BENCHMARK_DOMAIN for task in manifest["tasks"]):
        raise ValueError("Use a frozen telecom suite with exactly ten official training development tasks")
    splits = read(Path(suite) / "upstream/data/tau2/domains" / BENCHMARK_DOMAIN / "split_tasks.json")
    if not splits["test"] or [task["upstream_id"] for task in holdout] != splits["test"]:
        raise ValueError("Reserve every official telecom test task in its frozen original order")
    development_groups = {task["group"] for task in development}
    if len(development_groups) != len(development) or development_groups & {task["group"] for task in holdout}:
        raise ValueError("Development requires distinct families disjoint from the official test families")
    for task in manifest["tasks"]:
        criteria = task["task"].get("evaluation_criteria") or {}
        basis = set(criteria.get("reward_basis", []))
        allowed = {"ENV_ASSERTION"} if task["split"] == "development" else {"ENV_ASSERTION", "ACTION"}
        if ("ENV_ASSERTION" not in basis or not basis <= allowed or not criteria.get("env_assertions")
                or criteria.get("nl_assertions") or criteria.get("communicate_info")):
            raise ValueError("Telecom release requires environment assertions and only the allowed deterministic "
                             "reward basis, with no NL or communication criteria: " + task["task_id"])
    return development, holdout


def prepare(args):
    previous = Path(args.previous).resolve() if getattr(args, "previous", None) else None
    continuing = getattr(args, "continue_opening", False)
    if continuing and previous is None:
        raise ValueError("--continue-opening requires --previous")
    if previous:
        if read(previous / "protocol.json").get("benchmark_domain") != BENCHMARK_DOMAIN:
            raise ValueError("The active release benchmark is telecom; retail campaigns retain their frozen "
                             "implementation and cannot become telecom recoveries. Prepare a new telecom suite.")
    old = previous_protocol(previous) if previous else None
    continuation = opening_continuation(previous, old) if continuing else None
    if old:
        args.suite, args.worker_image, args.seed = previous / "suite", old["worker_image"], old["seed"]
    else:
        args.worker_image = args.worker_image or "python:3.12-slim"
        args.seed = args.seed if args.seed is not None else 20260920
    manifest = load_suite(args.suite)
    development, holdout = release_tasks(args.suite, manifest)
    if old:
        client, user = clients(old)
    else:
        client = ChatCompletionsClient.from_env()
        user = user_client(argparse.Namespace(user_model=None, user_output_allowance=2048), client)
    limits = Limits(**old["task_limits"]) if old and not continuing else RELEASE_TASK_LIMITS
    worker = image_id(args.worker_image)
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(args.suite, root / "suite")
    Tau2Runner(root / "suite", manifest, client, user, worker, limits, root / "private/preflight")
    jev_configuration = jev.configuration()
    sources = {"L0": BASELINE_CONTROLLER.read_text(), "L1": MANUAL_CONTROLLER.read_text()}
    if old and (jev_configuration != old["jev"] or worker != old["worker_image"]
                or any(digest(source.encode()) != old["sources"][name]["sha256"] for name, source in sources.items())):
        raise ValueError("Recovery must retain Jev configuration, worker and the supplied L0/L1 sources")
    source_records = {}
    for name, source in sources.items():
        compile(source, name + ".py", "exec")
        path = "controllers/" + name + ".py"
        atomic_text(root / path, source)
        source_records[name] = dict(path=path, sha256=digest(source.encode()))
    experiment = read(ROOT / "experiments/tau2.json")
    if old and experiment["exposed"] != old["experiment"]["exposed"]:
        raise ValueError("Recovery must retain the exposed component boundary")
    experiment["question"] = (
        f"Research a reusable {BENCHMARK_DOMAIN} Loop for an educational open-source release using these ten official train tasks. "
        "L0 is reactive; L1 critiques completion proposals and returns on explicit terminal observations. "
        "This is a joint Loop contrast, not a pure Critique ablation. Both supplied sources are measured on all ten "
        "tasks before your worker starts. Read release-policy.json "
        "and component-contracts.md. Use Jev's noisy segment judgments to locate evidence worth inspecting; inspect "
        "raw outcomes before explaining failures. There are at most two research evaluations, both n=10, repeats=1. "
        "Before the first, save up to three candidates and evaluate [L0, L1, saved candidates]. Before the second, "
        "use the first batch's evidence to save up to two more candidates and evaluate [L0, L1, first batch best, "
        "saved candidates]. The host supplies best_candidate and release_ranking in each evaluation receipt. "
        "Omit duplicate IDs and put the required controls first. All newly saved sources must enter their batch. "
        "The next_batch receipt states required sources, candidate slots and remaining task runs; null means no "
        "resource limit. The frozen two-batch design and its per-batch candidate allowances still apply. "
        "Recovery retains all prior usage and subtracts it only from finite frozen caps. "
        "Consider different behavioral hypotheses where evidence supports them; component diversity and new-source "
        "counts are not quotas. You may continue an initially losing mechanism, repair a candidate, reuse an existing "
        "source, or finish early. No fixed component sequence is preferred. "
        + RANKING_RULE + " Submit the best source from the latest complete batch with finish and an evidence-based "
        "reason. Retaining L0 or L1 is valid; explain untested directions and uncertainty. Do not encode task IDs, "
        "customers, answers or research history in source. Research ends before final comparison; no test tasks or "
        "feedback are available. This command stops for human review and never dispatches final tasks.")
    validate_experiment(experiment)
    allowances = None
    budget = dict(task_runs=None, seconds=None, model_calls=None, output_tokens=None)
    logical_caps = {**budget, "new_candidates": sum(ROUND_CANDIDATE_CAPS)}
    recovery = None
    if old:
        logical_caps = old.get("logical_caps", {**old["research_budgets"], "new_candidates": sum(ROUND_CANDIDATE_CAPS)})
        allowances = old.get("budget_allowances")
        prior = root / "private/prior-attempts"
        if (previous / "private/prior-attempts").exists():
            shutil.copytree(previous / "private/prior-attempts", prior)
        attempts = []
        for entry in old.get("recovery", {}).get("attempts", []):
            attempts.append(dict(directory=entry["directory"], **attempt_spend(root / entry["directory"])))
        directory = f"private/prior-attempts/attempt-{len(attempts) + 1:02d}"
        destination = root / directory
        shutil.copytree(previous / "research", destination / "research")
        for name in ("protocol.json", "result.json"):
            shutil.copy2(previous / name, destination / name)
        attempts.append(dict(directory=directory, **attempt_spend(destination)))
        spent = {key: sum(attempt["spent"][key] for attempt in attempts) for key in logical_caps}
        remaining = {key: None if cap is None else cap - spent[key] for key, cap in logical_caps.items()}
        opening_runs = len({digest(source.encode()) for source in sources.values()}) * len(development)
        if continuation:
            opening_runs -= continuation["retained_runs"]
        if ((remaining["task_runs"] is not None and remaining["task_runs"] < opening_runs)
                or any(remaining[key] is not None and remaining[key] <= 0
                       for key in ("seconds", "model_calls", "output_tokens"))):
            raise ValueError("Remaining logical budget cannot admit a fresh complete opening")
        if remaining["new_candidates"] < 0:
            raise ValueError("Prior attempts exceeded the logical new-source cap")
        budget = {key: remaining[key] for key in budget}
        recovery = dict(previous=str(previous), attempts=attempts, spent=spent, remaining=remaining,
            imported_files={str(path.relative_to(root)): digest(path.read_bytes())
                            for path in sorted(prior.rglob("*")) if path.is_file()})
        if continuation:
            recovery["opening"] = dict(path=directory + "/research/public/evaluations/e0000", **continuation)
            experiment["question"] += (
                " The user authorized continuation of a stopped opening with new per-task caps. "
                + continuation["interpretation"] + " The interrupted run counts as a user-adjudicated failure, "
                "not an official evaluator result; read its adjudication metadata. Its trace and new Jev analysis "
                "remain available. Completed runs retain their original scores and limits, and are not rerun. "
                "All later research evaluations run the full fixed batch under the new per-task caps.")
        else:
            experiment["question"] += (
                f" This fresh recovery has {remaining['new_candidates']} new sources remaining across both batches. "
                "Its release policy and next_batch receipts report the remaining frozen task allowance, including the "
                "repeated opening; null remains unlimited. Finite remaining caps can require fewer candidates or early "
                "finish. Prior unsuccessful-episode feedback is not inherited.")
    selection = root / "suite/selection.json"
    selection_record = dict(path="suite/selection.json", sha256=digest(selection.read_bytes())) if selection.is_file() else None
    final_sources, final_repeats = ["L0", "L1", "L2"], 2
    protocol = dict(benchmark_domain=BENCHMARK_DOMAIN, task_ids=[task["task_id"] for task in development],
        reserved_holdout_task_ids=[task["task_id"] for task in manifest["tasks"] if task["split"] == "holdout"],
        seed=args.seed, worker_image=worker, model=model_settings(client), user_model=model_settings(user),
        task_limits=vars(limits), research_budgets=budget, logical_caps=logical_caps, budget_allowances=allowances,
        experiment=experiment, sources=source_records, task_selection=selection_record, jev=jev_configuration,
        ranking=RANKING_RULE, candidate_caps=ROUND_CANDIDATE_CAPS,
        proposed_final_comparison=dict(status="requires_review", authorized_task_runs=0,
            task_ids=[task["task_id"] for task in holdout], official_split=BENCHMARK_DOMAIN + "/test",
            repeats=final_repeats, sources=final_sources,
            source_identity="Deduplicate exact source; preserve aliases",
            max_task_runs=len(holdout) * final_repeats * len(final_sources)),
        suite_manifest_sha256=digest((root / "suite/manifest.json").read_bytes()),
        implementation_sha256=snapshot_implementation(root),
        stopping_point="awaiting_review; no final evaluation is implemented by this command")
    if recovery:
        recovery["implementation_changes"] = {name: dict(previous=old["implementation_sha256"].get(name),
                                                        current=protocol["implementation_sha256"].get(name))
            for name in sorted(set(old["implementation_sha256"]) | set(protocol["implementation_sha256"]))
            if old["implementation_sha256"].get(name) != protocol["implementation_sha256"].get(name)}
        protocol["recovery"] = recovery
    atomic_json(root / "protocol.json", protocol)
    atomic_json(root / "result.json", dict(status="prepared", development_task_runs=0, selected=None))
    return protocol


def run(root):
    protocol = verify(root)
    if protocol["benchmark_domain"] != BENCHMARK_DOMAIN:
        raise ValueError("This frozen release implementation requires its telecom protocol")
    state = read(root / "result.json")
    if state["status"] != "prepared":
        raise ValueError("Research requires a new prepared output; do not resume a Python continuation")
    selection = protocol.get("task_selection")
    if selection and digest((root / selection["path"]).read_bytes()) != selection["sha256"]:
        raise ValueError("Frozen task selection and exposure audit changed")
    sources = {}
    for name, source in protocol["sources"].items():
        content = (root / source["path"]).read_text()
        if digest(content.encode()) != source["sha256"]:
            raise ValueError("Frozen supplied source changed: " + name)
        sources[name] = content
    client, user = clients(protocol)
    manifest = load_suite(root / "suite")
    development, holdout = release_tasks(root / "suite", manifest)
    if ([task["task_id"] for task in development] != protocol["task_ids"]
            or [task["task_id"] for task in holdout] != protocol["reserved_holdout_task_ids"]):
        raise ValueError("Frozen release task IDs differ from the admitted suite")
    # Even the host runner for this command only admits the frozen development IDs.
    development_manifest = {**manifest, "tasks": [task for task in manifest["tasks"]
                                                   if task["task_id"] in protocol["task_ids"]]}
    limits = Limits(**protocol["task_limits"])
    runner = Tau2Runner(root / "suite", development_manifest, client, user,
                       protocol["worker_image"], limits, root / "private/environments")
    budget = protocol["research_budgets"]
    recovery = protocol.get("recovery", {})
    session = ReleaseResearchSession(output=root / "research", development=tuple(protocol["task_ids"]), holdout=(),
        opening=(root / recovery["opening"]["path"], recovery["opening"]) if recovery.get("opening") else None,
        new_candidate_cap=recovery.get("remaining", {}).get("new_candidates", sum(ROUND_CANDIDATE_CAPS)),
        run_task=runner, research_client=client, worker_image=protocol["worker_image"],
        setup=dict(model=protocol["model"], user_model=protocol["user_model"],
                   release_protocol_sha256=digest((root / "protocol.json").read_bytes())),
        experiment=protocol["experiment"], baseline_source=sources["L0"], starting_source=sources["L1"],
        max_task_runs=budget["task_runs"], research_seconds=budget["seconds"],
        research_output_tokens=budget["output_tokens"], research_model_calls=budget["model_calls"],
        task_limits=limits, seed=protocol["seed"], fixed_task_batch=True, opening_n=10)
    if session.jev_configuration != protocol["jev"]:
        raise ValueError("Jev configuration differs from the frozen protocol")
    state["status"] = "researching"
    atomic_json(root / "result.json", state)
    started = time.monotonic()
    try:
        selected = session.research()
        source = session.source(selected)
        atomic_text(root / "controllers/L2.py", source)
        state.update(selected=dict(candidate_id=selected, path="controllers/L2.py", sha256=digest(source.encode())),
                     selection_reason=session.state.get("selection_reason"))
        identities, aliases = {}, {}
        for name, content in {**sources, "L2": source}.items():
            sha = digest(content.encode())
            aliases[name] = identities.setdefault(sha, name)
        state["aliases"] = aliases
        submitted = session.state.get("research_status") == "completed" and bool(session.state.get("selection_reason"))
        state["status"] = "awaiting_review" if submitted else "research_incomplete"
    except BaseException as error:
        state.update(status="interrupted", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        calls = session.meter.calls if hasattr(session, "meter") else []
        usage = model_usage(calls)
        previous_calls = [call for attempt in recovery.get("attempts", [])
                          for call in read(root / attempt["directory"] / "research/private/research-usage.json")["calls"]]
        native_attempts = []
        for directory in [*(root / attempt["directory"] / "research" for attempt in recovery.get("attempts", [])),
                          session.output]:
            native = native_researcher_usage(directory)
            if native is not None:
                native_attempts.append(dict(directory=str(directory.relative_to(root)), usage=native))
        elapsed = time.monotonic() - started
        charged = max(0, elapsed - usage["timeout_wait_seconds"])
        state.update(research_status=session.state.get("research_status"),
            development_task_runs=session.state["task_runs_used"],
            research_usage=usage, cumulative_usage=model_usage(previous_calls + calls),
            native_researcher_usage=native_researcher_usage(session.output),
            cumulative_native_researcher_usage=native_attempts,
            cumulative_task_runs=recovery.get("spent", {}).get("task_runs", 0) + session.state["task_runs_used"],
            elapsed_seconds=elapsed, budget_seconds=charged,
            cumulative_budget_seconds=recovery.get("spent", {}).get("seconds", 0) + charged,
            new_candidates=len(session.state["candidates"]) - len(session.initial_candidates),
            cumulative_new_candidates=recovery.get("spent", {}).get("new_candidates", 0)
                + len(session.state["candidates"]) - len(session.initial_candidates),
            research_state="research/private/state.json", evidence="research/public/evidence.json",
            final_comparison="Not started. Human review is required; this command has no final-evaluation path.")
        atomic_json(root / "result.json", state)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run"))
    parser.add_argument("output", type=Path)
    parser.add_argument("--suite", type=Path)
    parser.add_argument("--previous", type=Path, help="Restart a failed opening in a new output, charging prior attempts")
    parser.add_argument("--continue-opening", action="store_true",
        help="With --previous: retain completed runs, count the interrupted run as user-adjudicated failure, "
             "and dispatch only unstarted rows under the current release task caps")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--worker-image")
    args = parser.parse_args()
    if args.command == "prepare":
        if (args.suite is None) == (args.previous is None):
            parser.error("prepare requires exactly one of --suite or --previous")
        if args.previous is not None and (args.seed is not None or args.worker_image is not None):
            parser.error("--previous retains its frozen seed and worker image")
        prepare(args)
    elif run(args.output.resolve())["status"] != "awaiting_review":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
