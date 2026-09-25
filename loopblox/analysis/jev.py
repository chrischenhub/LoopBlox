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
from loopblox.runtime.model import BudgetExhausted, OperationalProblem


def configuration():
    """Check local dependencies before task dispatch and freeze the exact question definitions."""
    metadata = transport.configuration(describe_module=__name__)
    return dict(schema_version=SCHEMA_VERSION, observations_per_segment=OBSERVATIONS_PER_SEGMENT,
                tail_reasoning_calls_per_segment=TAIL_REASONING_CALLS_PER_SEGMENT,
                input_implementation_sha256=digest(Path(__file__).read_bytes() + b"\0" +
                                                   Path(__file__).with_name("segments.py").read_bytes()),
                oversized_segments="Split rejected groups into single observation cycles or tail reasoning calls; never truncate evidence",
                **metadata, questions_sha256=digest(json.dumps(metadata["questions"], sort_keys=True).encode()))


def analyze_run(trace_path, *, configuration, meter, scope):
    """Persist each attempt and finish all segment judgments before releasing a run's feedback."""
    trace_path = Path(trace_path)
    trace_bytes = trace_path.read_bytes()
    trace = json.loads(trace_bytes)
    segments = [dict(**segment, status="not_started") for segment in turns(trace)]
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
        position = 0
        while position < len(segments):
            segment = segments[position]
            position += 1
            # Factor exact repeated containers and long strings only; references preserve every occurrence.
            # Keep the original state in the segment and the wire state in each attempt.
            state = segment["state"]
            marker = "$evidence_ref"
            serialized = json.dumps(state, ensure_ascii=False)
            while marker in serialized:
                marker += "_"
            seen = {}

            def pack(value, pointer=""):
                if isinstance(value, (dict, list, str)):
                    identity = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                    if len(identity) >= 128:
                        if identity in seen:
                            return {marker: seen[identity]}
                        seen[identity] = pointer
                    if isinstance(value, str):
                        return value
                    if isinstance(value, dict):
                        return {key: pack(item, pointer + "/" + key.replace("~", "~0").replace("/", "~1"))
                                for key, item in value.items()}
                    return [pack(item, pointer + "/" + str(index)) for index, item in enumerate(value)]
                return value

            packed = pack(state)
            encoding_key = "_evidence_encoding"
            while encoding_key in state:
                encoding_key += "_"
            packed[encoding_key] = (
                "Lossless repeated evidence encoding: an object with the single key " + marker +
                " denotes the complete value at its RFC 6901 JSON Pointer in this state. "
                "Resolve references recursively at every occurrence; repeated evidence retains "
                "its original position and multiplicity. All other values are literal.")
            if len(json.dumps(packed, ensure_ascii=False)) < len(serialized):
                state = packed
            body = dict(model=configuration["model"], state=state,
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
            try:
                model_call(meter=meter, scope=f"{scope}:jev:s{segment['index']:04d}", request=request,
                           max_tokens=configuration["output_reservation"], remaining=meter.remaining,
                           invoke=invoke, time_origin=meter.started, record_attempt=attempted)
            except OperationalProblem as error:
                if error.code != "jev_input_limit":
                    raise
                ids = set(segment["ids"])
                pieces = [piece for piece in turns(trace, observations_per_segment=1,
                    tail_reasoning_calls_per_segment=1) if set(piece["ids"]).issubset(ids)]
                if len(pieces) < 2 or set().union(*(set(piece["ids"]) for piece in pieces)) != ids:
                    raise  # A single oversized observation needs repair, not silent truncation.
                next_index = max(item["index"] for item in segments) + 1
                children = [dict(piece, index=next_index + index, parent_segment=segment["index"],
                                 status="not_started") for index, piece in enumerate(pieces)]
                indices = {piece["index"]: child["index"] for piece, child in zip(pieces, children)}
                for child in children:
                    child["facts"]["identical_repeat_of"] = indices.get(child["facts"]["identical_repeat_of"])
                segment.update(status="split", children=[item["index"] for item in children],
                    recovery=dict(route="infra", action="split_segment", code=error.code))
                segments[position:position] = children
                save()
                continue
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
        if segment["status"] == "split":
            continue  # Keep parent attempts in raw evidence without counting participation twice.
        ids = set(segment["ids"])
        scoped = dict(
            component_calls=[call for call in trace["component_calls"] if call["id"] in ids],
            model_calls=[call for call in trace["model_calls"] if call["request"]["component_id"] in ids],
            history=[event for event in trace["history"] if event.get("component_id") in ids])
        execution = summarize_trace(scoped)
        segments.append(dict(
            index=segment["index"], first_step=segment["first_step"], last_step=segment["last_step"],
            parent_segment=segment.get("parent_segment"),
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
