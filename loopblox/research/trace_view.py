"""Project one recorded task's Jev measurements and their public trace evidence."""

import json
from pathlib import Path

from loopblox.analysis.jev import feedback
from loopblox.runtime.io import digest


def _metrics(configuration, segments, source):
    """Use the run's frozen questions, or its recorded answer legends, for scales."""
    metrics = {}
    for key, label in (("progress", "Task progress"),
                       ("action_effectiveness", "Action effectiveness"),
                       ("recovery_needed", "Recovery needed")):
        question = configuration.get("questions", {}).get(key, {})
        criteria = question.get("criteria")
        legend = {str(index): text for index, text in enumerate(criteria)} if isinstance(criteria, list) else {}
        position, answer = next(((position, segment["response"]["answers"][key])
                                 for position, segment in enumerate(segments)
                                 if key in segment.get("response", {}).get("answers", {})), (None, {}))
        metric_source = f"{source}/questions/{key}"
        if not legend:
            legend = answer.get("legend", {})
            if legend or (not question and answer):
                metric_source = f'{source.partition("#")[0]}#/segments/{position}/response/answers/{key}'
        if question.get("type", answer.get("type")) == "noul":
            minimum, maximum = 0, 1
        elif legend:
            try:
                scale = [float(value) for value in legend]
                minimum, maximum = min(scale), max(scale)
            except (TypeError, ValueError):
                minimum = maximum = None
        else:
            minimum = maximum = None
        metrics[key] = dict(min=minimum, max=maximum, label=label,
                            description=question.get("instructions", "No recorded question definition."),
                            legend=legend, source=metric_source)
    return metrics


def trace_view(public, candidate=None, task=None, run=None):
    """Read one selected run; selection strings never become filesystem paths.

    The canonical Jev feedback projection owns measurements and invocation joins.
    Split parents remain available as metadata but never enter the plotted series.
    """
    public = Path(public).resolve()
    warnings = []

    def record_path(relative):
        relative = Path(relative)
        path = (public / relative).resolve()
        if (relative.is_absolute() or "private" in relative.parts
                or not path.is_relative_to(public) or "private" in path.relative_to(public).parts):
            raise ValueError(f"Record points outside public evidence: {relative}")
        return path

    def read(relative):
        path = record_path(relative)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return None, None
        except OSError as error:
            warnings.append(f"Could not read {relative}: {type(error).__name__}")
            return None, None
        try:
            return json.loads(raw), raw
        except ValueError:
            warnings.append(f"Record is not complete JSON yet: {relative}")
            return None, raw

    rows = []
    for path in sorted((public / "evaluations").glob("*/result.json")):
        evaluation, _ = read(path.relative_to(public))
        if evaluation is None:
            continue
        for row in evaluation["runs"]:
            directory = path.parent.relative_to(public) / row["directory"]
            record_path(directory)
            rows.append(dict(id=str(directory.relative_to("evaluations")),
                             candidate_id=row["candidate_id"], task_id=row["task_id"],
                             status=row["status"], directory=str(directory), record=row))
    candidates = list(dict.fromkeys(row["candidate_id"] for row in rows))
    tasks = list(dict.fromkeys(row["task_id"] for row in rows))
    if candidate is not None and candidate not in candidates:
        raise ValueError(f"Candidate {candidate!r} is absent from the recorded evaluation plans.")
    if task is not None and task not in tasks:
        raise ValueError(f"Task {task!r} is absent from the recorded evaluation plans.")
    selected = next((row for row in rows if row["id"] == run), None) if run is not None else None
    if run is not None and selected is None:
        raise ValueError(f"Run {run!r} is absent from the recorded evaluation plans.")
    if selected is not None:
        if ((candidate is not None and selected["candidate_id"] != candidate)
                or (task is not None and selected["task_id"] != task)):
            raise ValueError("The selected run does not match the selected candidate and task.")
    else:
        matching = [row for row in rows if (candidate is None or row["candidate_id"] == candidate)
                    and (task is None or row["task_id"] == task)]
        selected = next((row for row in reversed(matching) if row["record"].get("jev")
                         or record_path(f'{row["directory"]}/jev.json').is_file()), None)
        selected = selected or next((row for row in reversed(matching) if row["status"] == "running"), None)
        selected = selected or next((row for row in reversed(matching)
                                     if record_path(f'{row["directory"]}/trace.json').is_file()), None)
        selected = selected or (matching[-1] if matching else None)

    result = dict(candidates=[dict(id=value) for value in candidates],
                  tasks=[dict(id=value) for value in tasks],
                  runs=[{key: row[key] for key in ("id", "candidate_id", "task_id", "status")} for row in rows],
                  selected=dict(candidate_id=selected["candidate_id"] if selected else candidate,
                                task_id=selected["task_id"] if selected else task,
                                run_id=selected["id"] if selected else None),
                  trace=None, warnings=warnings)
    if selected is None:
        return result

    artifact = f'{selected["directory"]}/jev.json'
    trace_artifact = f'{selected["directory"]}/trace.json'
    record, _ = read(artifact)
    trace, trace_bytes = read(trace_artifact)
    # The lane row is finalized after Jev; official scoring may already be recorded.
    run_result, _ = read(f'{selected["directory"]}/result.json') if selected["status"] == "running" else (None, None)
    facts = {**selected["record"], **(run_result or {})}
    configuration = (record["configuration"] if record else read("jev-config.json")[0]) or {}
    configuration_source = f"{artifact}#/configuration" if record else "jev-config.json#"
    raw_segments = record.get("segments", []) if record else []
    task_record = next((event["task"] for event in (trace or {}).get("history", [])
                        if event.get("type") == "task" and "task" in event), None)
    details = dict(id=selected["id"], candidate_id=selected["candidate_id"], task_id=selected["task_id"],
                   status=selected["status"], official_result=facts.get("verification_verdict"),
                   task=task_record, jev_status=record["status"] if record else "not_recorded",
                   schema_version=configuration.get("schema_version"), artifact=artifact,
                   trace_artifact=trace_artifact, source_trace_sha256=record.get("source_trace_sha256") if record else None,
                   metrics=_metrics(configuration, raw_segments, configuration_source), segments=[], split_parents=[])
    result["trace"] = details
    if record is None or trace is None:
        return result
    if digest(trace_bytes) != record.get("source_trace_sha256"):
        warnings.append("The recorded Jev source hash does not match this trace; measurements are not joined.")
        return result
    # Validate the recorded provenance path even though only the selected trace is read.
    recorded_trace = record_path(Path(selected["directory"]) / record["source_trace"])
    if recorded_trace != record_path(trace_artifact):
        warnings.append("Jev references a different trace file; measurements are not joined.")
        return result
    try:
        measured = feedback(record, artifact, trace)
    except (KeyError, TypeError, ValueError) as error:
        warnings.append(f"Could not derive Jev measurements from recorded evidence: {type(error).__name__}")
        return result
    for segment in measured["segments"]:
        position = int(segment["evidence_pointer"].rsplit("/", 1)[1])
        raw = raw_segments[position]
        ids = set(segment["invocation_ids"])
        pointer = f'{artifact}#{segment["evidence_pointer"]}'
        details["segments"].append(dict(
            **segment, id=segment["index"], input=raw["state"], response=raw.get("response"),
            attempts=raw.get("attempts", []), attempts_source=f"{pointer}/attempts",
            invocations=[call for call in trace["component_calls"] if call["id"] in ids],
            input_source=f"{pointer}/state", response_source=f"{pointer}/response" if "response" in raw else None))
    for position, segment in enumerate(raw_segments):
        if segment["status"] == "split":
            details["split_parents"].append(dict(
                **{key: segment[key] for key in ("index", "status", "first_step", "last_step", "ids", "children", "recovery", "error", "attempts")
                   if key in segment}, id=segment["index"], parent_segment=segment.get("parent_segment"),
                source=f"{artifact}#/segments/{position}"))
    return result
