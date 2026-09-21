"""Mandatory post-run Jev evidence, using the shared research ledger and gateway."""

import importlib.metadata
from collections import Counter
import json
from pathlib import Path
import sys
import time

from loopblox.analysis.segments import (OBSERVATIONS_PER_SEGMENT, SCHEMA_VERSION, TAIL_REASONING_CALLS_PER_SEGMENT,
                                       measurements, questions, segment_questions, turns)
from loopblox.runtime.controller import model_call, model_usage
from loopblox.runtime import jev as transport
from loopblox.report import summarize_trace
from loopblox.runtime.io import atomic_json, digest
from loopblox.runtime.model import BudgetExhausted


def configuration():
    """Check local dependencies before task dispatch and freeze the exact question definitions."""
    metadata = transport.configuration(describe_module=__name__)
    return dict(schema_version=SCHEMA_VERSION, observations_per_segment=OBSERVATIONS_PER_SEGMENT,
                tail_reasoning_calls_per_segment=TAIL_REASONING_CALLS_PER_SEGMENT,
                **metadata, questions_sha256=digest(json.dumps(metadata["questions"], sort_keys=True).encode()))


def analyze_run(trace_path, *, configuration, meter, scope):
    """Persist each attempt and finish all segment judgments before releasing a run's feedback."""
    trace_path = Path(trace_path)
    trace_bytes = trace_path.read_bytes()
    segments = [dict(**segment, status="not_started") for segment in turns(json.loads(trace_bytes))]
    record = dict(status="running", source_trace=trace_path.name, source_trace_sha256=digest(trace_bytes),
                  configuration=configuration, segments=segments)
    path = trace_path.with_name("jev.json")
    started = time.monotonic()
    calls = []

    def save():
        record.update(usage=model_usage(calls), elapsed_seconds=time.monotonic() - started)
        atomic_json(path, record)

    save()
    try:
        for segment in segments:
            body = dict(model=configuration["model"], state=segment["state"],
                        questions=segment_questions(configuration["questions"], segment["state"]))
            request = dict(role="jev", **body)
            segment.update(status="running", attempts=[])
            save()

            def attempted(call):
                calls.append(call)
                segment["attempts"].append(call)
                save()

            def invoke(allowance):
                turn = transport.complete(body, configuration, allowance)
                segment["response"] = turn.raw
                return turn

            if meter.remaining()["output_tokens"] < configuration["output_reservation"]:
                raise BudgetExhausted("jev_output_reservation")
            model_call(meter=meter, scope=f"{scope}:jev:s{segment['index']:04d}", request=request,
                       max_tokens=configuration["output_reservation"], remaining=meter.remaining,
                       invoke=invoke, time_origin=meter.started, record_attempt=attempted)
            segment["status"] = "completed"
            save()
        record["status"] = "completed"
    except BaseException as error:
        status = ("budget_exhausted" if isinstance(error, BudgetExhausted) else
                  "failed" if isinstance(error, Exception) else "interrupted")
        record.update(status=status, error=type(error).__name__ + ": " + str(error))
        for segment in segments:
            if segment["status"] == "running":
                segment["status"] = status
        raise
    finally:
        save()
    return record


def _segment_summary(segments):
    coverage = {}
    for key in ("progress", "action_effectiveness", "recovery_needed"):
        values = [segment[key] for segment in segments if segment[key] is not None]
        coverage[key] = dict(measured=len(values), missing=len(segments) - len(values),
                             minimum=min(values) if values else None, maximum=max(values) if values else None)
    participation = Counter()
    for segment in segments:
        for name, component in segment["execution"]["components"].items():
            participation[name] += len(component["invocation_ids"])
    return dict(segments=len(segments), statuses=dict(Counter(segment["status"] for segment in segments)),
                measurements=coverage, component_invocations=dict(participation))


def overview(feedbacks):
    """Summarize an evaluation's analyses without combining incompatible measurement schemas."""
    groups = {}
    for item in feedbacks:
        groups.setdefault(item["schema_version"], []).append(item)
    return {schema: dict(runs=len(items), run_statuses=dict(Counter(item["status"] for item in items)),
                         **_segment_summary([segment for item in items for segment in item["segments"]]))
            for schema, items in groups.items()}


def feedback(record, artifact, trace):
    """Join existing judgments to their public invocation evidence, without another model call.

    The evaluation stores the full navigation view; a receipt can show only its summary.
    Costs belong to actual agent attempts in these invocations, not Jev or simulator calls.
    """
    segments = []
    for position, segment in enumerate(record["segments"]):
        ids = set(segment["ids"])
        scoped = dict(
            component_calls=[call for call in trace["component_calls"] if call["id"] in ids],
            model_calls=[call for call in trace["model_calls"] if call["request"]["component_id"] in ids],
            history=[event for event in trace["history"] if event.get("component_id") in ids])
        execution = summarize_trace(scoped)
        segments.append(dict(
            index=segment["index"], first_step=segment["first_step"], last_step=segment["last_step"],
            evidence_pointer=f"/segments/{position}", invocation_ids=segment["ids"],
            facts=segment["facts"], **measurements(segment),
            execution=dict(components=execution["components"], tools=execution["tools"],
                           agent_usage=model_usage(scoped["model_calls"]))))
    return dict(
        status=record["status"], artifact=artifact,
        trace_artifact=str(Path(artifact).with_name(record["source_trace"])),
        source_trace_sha256=record["source_trace_sha256"],
        schema_version=record["configuration"]["schema_version"], usage=record["usage"],
        summary=_segment_summary(segments),
        segments=segments)


def main():
    """Describe the fixed analysis questions in the configured SDK interpreter."""
    definitions = questions()
    schema = {key: value.model_dump(mode="json") for key, value in definitions.items()}
    if sys.argv[1] == "describe":
        result = dict(sdk_version=importlib.metadata.version("typesafe-sdk"), questions=schema)
    else:
        raise ValueError("Expected describe")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
