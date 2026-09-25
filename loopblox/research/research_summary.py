"""Read-only research narrative and Jev coverage from a campaign's public records."""

from collections import Counter
import json
from pathlib import Path
import re

from loopblox.analysis.jev import feedback, overview
from loopblox.report import summarize_trace


def _sections(text):
    sections, title, lines = [], "Research notebook", []
    for line in text.splitlines():
        if line.startswith("## "):
            sections.append((title, "\n".join(lines).strip()))
            title, lines = line[3:].strip(), []
        else:
            lines.append(line)
    sections.append((title, "\n".join(lines).strip()))
    return sections


def _total(items, key):
    values = [item.get(key) for item in items]
    return sum(values) if all(value is not None for value in values) else None


def research_summary(public, loops):
    """Project public evidence; never read the researcher transcript or dispatch work.

    The generic visualizer owns candidate outcome and incumbent facts. Jev's own
    feedback/overview functions own measurements and schema-aware coverage.
    Narrative excerpts remain the researcher's words, not generated explanations.
    """
    public = Path(public).resolve()
    sources, warnings = set(), []

    def record_path(relative):
        path = (public / relative).resolve()
        if not path.is_relative_to(public) or "private" in path.relative_to(public).parts:
            raise ValueError(f"Record points outside public evidence: {relative}")
        return path

    def read(relative, *, text=False):
        path = record_path(relative)
        if not path.is_file():
            return None
        try:
            raw = path.read_text()
            value = raw if text else json.loads(raw)
        except (OSError, ValueError) as error:
            warnings.append(f"Could not read {relative}: {type(error).__name__}")
            return None
        sources.add(str(path.relative_to(public)))
        return value

    experiment = read("experiment.json") or {}
    configuration = read("jev-config.json") or {}
    notebook = read("notes.md", text=True) or ""
    sections = _sections(notebook)
    history = next((body for title, body in sections if "candidate history" in title.lower()), "")
    excerpts = [dict(title=title, text=paragraph, source="notes.md")
                for title, body in sections
                if not any(word in title.lower() for word in ("protocol", "cost", "candidate history"))
                for paragraph in re.split(r"\n\s*\n", body)
                if re.search(r"\bJev\b", paragraph) and re.search(r"\b(?:segment|progress|recovery|effectiveness)\b", paragraph)]
    progress = loops["progress"]
    candidates = loops["candidates"]
    indexed = {candidate["id"]: candidate for candidate in candidates}
    by_candidate = {candidate["id"]: [] for candidate in candidates}
    analyses, usages = [], []
    online = dict(invocations=0, model_calls=0, runs=0, recorded_runs=0, missing_summaries=0)
    online_candidates = Counter()
    missing_analyses = 0

    for path in sorted((public / "evaluations").glob("*/result.json")):
        evaluation = read(str(path.relative_to(public)))
        if evaluation is None:
            continue
        evaluation_id = evaluation["evaluation_id"]
        for row in evaluation["runs"]:
            if row["status"] == "not_started":
                continue
            run = f'evaluations/{evaluation_id}/{row["directory"]}'
            analysis = row.get("jev")
            trace = None
            if not analysis:
                record = read(f"{run}/jev.json")
                if record:
                    trace = read(f"{run}/trace.json")
                    if trace:
                        analysis = feedback(record, f"{run}/jev.json", trace)
            if analysis:
                analyses.append(analysis)
                usages.append(analysis.get("usage", {}))
                by_candidate.setdefault(row["candidate_id"], []).append(analysis)
                sources.add(str(record_path(analysis["artifact"]).relative_to(public)))
                # Segmentation owns every invocation once, including failed tails.
                judge = [segment["execution"]["components"].get("judge", {})
                         for segment in analysis["segments"]]
                invocations = sum(len(component.get("invocation_ids", [])) for component in judge)
                model_calls = sum(component.get("model_attempts", 0) for component in judge)
            else:
                missing_analyses += 1
                summary = read(f"{run}/summary.json")
                if summary is None:
                    trace = trace or read(f"{run}/trace.json")
                    summary = summarize_trace(trace) if trace else None
                if summary is None:
                    online["missing_summaries"] += 1
                    continue
                judge = summary["components"].get("judge", {})
                invocations = len(judge.get("invocation_ids", []))
                model_calls = judge.get("model_attempts", 0)
            online["recorded_runs"] += 1
            online["invocations"] += invocations
            online["model_calls"] += model_calls
            online["runs"] += bool(invocations)
            online_candidates[row["candidate_id"]] += invocations

    schemas = overview(analyses)
    for schema, group in schemas.items():
        # Preserve reasons from the canonical measurements alongside coverage.
        group["missing_reasons"] = dict(Counter(
            segment.get("action_effectiveness_missing_reason", segment["status"])
            for analysis in analyses if analysis["schema_version"] == schema
            for segment in analysis["segments"] if segment["action_effectiveness"] is None))

    summaries = []
    for candidate in candidates:
        cid = candidate["id"]
        checkpoint = candidate["checkpoint"]
        reference = indexed.get(candidate["reference"])
        comparable = bool(reference and candidate["feedback_ready"] and reference["feedback_ready"]
                          and [row["task_id"] for row in candidate["tasks"]]
                          == [row["task_id"] for row in reference["tasks"]])
        delta = ({key: candidate[key] - reference[key]
                  if candidate[key] is not None and reference[key] is not None else None
                  for key in ("passed", "agent_input_tokens", "agent_model_calls")} if comparable else None)
        current = cid == progress.get("incumbent")
        selection = ("Current incumbent" if current else "Baseline" if candidate["iteration"] == 0
                     else "Selected at checkpoint" if checkpoint and checkpoint["incumbent"] == cid
                     else "Incumbent retained" if checkpoint else "Awaiting checkpoint" if candidate["feedback_ready"]
                     else "Awaiting evaluation" if not candidate["planned"] else "Evaluation incomplete")
        candidate_analyses = by_candidate[cid]
        summaries.append(dict(
            **{key: candidate[key] for key in (
                "id", "iteration", "reference", "rationale", "evaluation_id", "evaluation_status",
                "feedback_ready", "passed", "scored", "planned", "attempted", "missing",
                "agent_input_tokens", "agent_model_calls")},
            rationale_excerpt=candidate["rationale"].split("\n\n", 1)[0],
            researcher_summary="\n\n".join(paragraph for paragraph in re.split(r"\n\s*\n", history)
                                            if re.match(re.escape(cid) + r"\b", paragraph)),
            researcher_summary_source="notes.md" if history else None,
            current=current, selection=selection, delta=delta,
            checkpoint_notes=checkpoint["notes"] if checkpoint else None,
            source=f"candidates/{cid}.json",
            notes_source=f'checkpoints/iteration-{checkpoint["iteration"]:04d}.json' if checkpoint else None,
            evaluation_source=f'evaluations/{candidate["evaluation_id"]}/result.json' if candidate["evaluation_id"] else None,
            jev=dict(runs=len(candidate_analyses),
                     completed=sum(item["status"] == "completed" for item in candidate_analyses),
                     segments=sum(len(item["segments"]) for item in candidate_analyses),
                     model_calls=_total([item.get("usage", {}) for item in candidate_analyses], "model_calls"),
                     online_judge_invocations=online_candidates[cid])))

    sources.update(loops.get("provenance", {}))
    return dict(
        question=experiment.get("question"), ranking_rule=progress.get("ranking_rule"),
        scope="Public evidence in this campaign, including preserved completed evaluations inherited during recovery. "
              "Each recorded run is counted once. Prior interrupted attempts outside this public snapshot are excluded; "
              "the Dashboard's cumulative usage includes recovery spend. Researcher notes and rationales are claims, "
              "while outcomes and selection come from host records.",
        sources=sorted(sources), warnings=warnings,
        overview=dict(baseline=candidates[0]["id"] if candidates else None,
                      incumbent=progress.get("incumbent"),
                      completed_iterations=progress.get("completed_iterations", 0), candidates=len(candidates),
                      evaluated_candidates=sum(candidate["feedback_ready"] for candidate in candidates),
                      planned_runs=sum(candidate["planned"] for candidate in candidates),
                      attempted_runs=sum(candidate["attempted"] for candidate in candidates),
                      scored_runs=sum(candidate["scored"] for candidate in candidates),
                      passed_runs=sum(candidate["passed"] for candidate in candidates),
                      missing_scores=sum(candidate["missing"] for candidate in candidates)),
        candidates=summaries, checkpoints=loops["checkpoints"], notes=dict(text=notebook, source="notes.md"),
        jev=dict(
            configuration={key: configuration[key] for key in (
                "schema_version", "model", "observations_per_segment", "tail_reasoning_calls_per_segment", "questions")
                if key in configuration},
            runs=len(analyses), completed_runs=sum(item["status"] == "completed" for item in analyses),
            missing_runs=missing_analyses, statuses=dict(Counter(item["status"] for item in analyses)),
            segments=sum(len(item["segments"]) for item in analyses),
            model_calls=_total(usages, "model_calls"), input_tokens=_total(usages, "model_input_tokens"),
            output_tokens=_total(usages, "model_output_tokens"),
            incomplete_usage_calls=_total(usages, "incomplete_usage_calls"), schemas=schemas, online_judge=online,
            evidence_use=dict(status="researcher_account" if excerpts else "not_recorded", excerpts=excerpts,
                              explanation=("These are verbatim Jev-related passages from the public research notebook. "
                              "They show the researcher's stated interpretation, not an independently recorded log of "
                              "which artifacts were read. " if excerpts else
                              "No Jev interpretation excerpt was found in the public research notebook. "
                              "This page has no independently recorded public log of which artifacts were read. ")
                              + "Available Jev evidence alone does not establish its use or a causal gain."),
            sources=sorted({"jev-config.json", "jev-guide.md"} & sources
                           | {item["artifact"] for item in analyses})))
