"""Measure four-observation segments using public, untruncated evidence.

Component identities remain trace metadata. Semantic measurements are noisy research
evidence, not task rewards, failure causes or instructions to change a Loop.
"""

import argparse
import collections
import json
import pathlib

SCHEMA_VERSION = "segment-semantics-v11"
OBSERVATIONS_PER_SEGMENT = 4
TAIL_REASONING_CALLS_PER_SEGMENT = 4
_REASONING_COMPONENTS = ("decide", "think_decide", "think", "plan", "decompose", "critique", "reflect", "choose", "judge")


PROGRESS = [
    "No observable progress toward the public request. Repeating known information or an unsupported "
    "claim of completion does not advance the task.",
    "A new relevant detail was obtained or clarified, but no required preparation or verification was "
    "completed and no user-requested outcome was delivered.",
    "A required preparation or verification was completed, such as a prerequisite lookup, an eligibility "
    "check or obtaining authorization, but no user-requested outcome was delivered.",
    "The observed results confirm delivery of at least one outcome explicitly requested by the user: "
    "a requested change took effect, or the answer to the user's information request was delivered. "
    "This need not complete every goal in the task. An intermediate clarification, prerequisite, plan, "
    "promise or unsupported completion claim is not a delivered outcome.",
]
EFFECTIVENESS = [
    "The actions did not achieve their intended immediate effects.",
    "The actions achieved only part of their intended immediate effects: some actions worked, or an "
    "action only partly achieved its purpose.",
    "The actions fully achieved their intended immediate effects. Other steps may still be needed to "
    "fulfill the user's request; this score does not measure task completion or efficiency.",
]


def questions():
    """Canonical questions; each judgment covers the entire segment."""
    from typesafe_sdk import Noul, Score
    return {
        "progress": Score(instructions="How much closer to completing the public request in `task_goal` "
                                       "did this entire segment get, judged by the transition from "
                                       "`start_observation` through all intermediate results in `outcome`? "
                                       "Credit new progress supported by the resulting evidence. Distinguish "
                                       "completing a prerequisite from delivering a user-requested outcome. "
                                       "Retrieving information is preparation unless the user requested that "
                                       "information and the answer was delivered to them. Use `decided` and "
                                       "any `reasoning` as context, not proof of effects. Judge every segment, "
                                       "including one without new observed outcomes. Planning, rereading and "
                                       "completion proposals alone do not establish new task progress; absence "
                                       "of an observation does not prove an attempted action failed.", criteria=PROGRESS),
        "action_effectiveness": Score(instructions="How well did the actions in `decided` achieve "
                                                   "their evident immediate purposes, judged by `outcome` "
                                                   "across the whole segment? Assess whether those purposes "
                                                   "were achieved, independently of task progress or whether "
                                                   "more task steps are needed. Match actions and outcomes by "
                                                   "`execution_id` and `action_id`; `outcome.action` retains "
                                                   "the request even if it was attempted in an earlier segment. "
                                                   "Judge only actions with observed results. "
                                                   "An unobserved action is unknown, not a failed action.", criteria=EFFECTIVENESS),
        "recovery_needed": Noul(instructions="Does this entire segment provide evidence that the current "
                                             "approach needs correction before proceeding? Inspect `outcome`, "
                                             "`component_failures`, `reasoning`, `evidence_reads` and any "
                                             "`completion_proposals` against `task_goal` and `start_observation`. "
                                             "The final segment may also include the public controller "
                                             "`task_stop`, which is not a task score. "
                                             "A denied or failed component call can require correction even "
                                             "without a new environment outcome. Planning, rereading, proposing "
                                             "completion or lacking an observation alone is not evidence of "
                                             "failure. Judge only the recorded public evidence; do not assume "
                                             "unseen failures or history."),
    }


def segment_questions(definitions, state):
    """Always judge progress and recovery; effectiveness needs an observed result."""
    return {key: value for key, value in definitions.items()
            if key != "action_effectiveness" or state["outcome"]}


def _unwrap(value, depth=6):
    """Brief observations nest JSON inside JSON strings; unwrap so the text is not re-escaped.

    Only strings that parse to a container are unwrapped, so an ordinary message that happens
    to look like a literal stays a message.
    """
    if depth <= 0:
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            # Code stdout can interleave complete JSON documents with labels.
            # Unwrap only whole container documents at line boundaries, keeping
            # every intervening character and the document order as evidence.
            decoder = json.JSONDecoder()
            parts, cursor, offset = [], 0, 0
            for line in value.splitlines(keepends=True):
                start = offset
                offset += len(line)
                if start < cursor or not line.startswith(("{", "[")):
                    continue
                try:
                    document, end = decoder.raw_decode(value, start)
                except ValueError:
                    continue
                if not isinstance(document, (dict, list)) or (end < len(value) and value[end] not in "\r\n"):
                    continue
                if start > cursor:
                    parts.append(value[cursor:start])
                parts.append(document)
                cursor = end
            if not parts:
                return value
            if cursor < len(value):
                parts.append(value[cursor:])
            return {"text_and_json_parts": parts}
        return _unwrap(parsed, depth - 1) if isinstance(parsed, (dict, list)) else value
    if isinstance(value, dict):
        return {key: _unwrap(item, depth - 1) for key, item in value.items()}
    if isinstance(value, list):
        return [_unwrap(item, depth - 1) for item in value]
    return value


def _user_messages(observation):
    value = _unwrap(observation)
    if isinstance(value, dict) and isinstance(value.get("preserved"), dict):
        value = value["preserved"]
    return [message["content"] for message in value.get("messages", [])
            if message.get("role") == "user" and isinstance(message.get("content"), str)] if isinstance(value, dict) else []


def _observation(component):
    return component.startswith("observe_")


def turns(trace, *, observations_per_segment=OBSERVATIONS_PER_SEGMENT,
          tail_reasoning_calls_per_segment=TAIL_REASONING_CALLS_PER_SEGMENT):
    """Group four observation-delimited cycles without overlapping executed steps.

    A supplementary page or full reread cannot create another environment transition.
    Only host-recorded tool requests count as attempted actions; unselected proposals
    remain reasoning evidence. Frozen traces may still name think_decide or decompose.
    Retain the last partial group. Split the trailing calls after the final observed
    execution into groups of at most four reasoning/decision invocations, without
    truncating evidence. The preceding observation is context, not another step.
    """
    rows, current, observed = [], [], set()
    requests = collections.defaultdict(list)
    for entry in trace["history"]:
        if entry["type"] == "tool_call":
            requests[entry["component_id"]].append(entry)
    actions = {entry["action_id"]: {key: entry[key] for key in ("capability_id", "arguments")}
               for entries in requests.values() for entry in entries}
    for call in trace["component_calls"]:
        current.append(call)
        if _observation(call["component"]) and call.get("status") == "completed":
            execution = call["arguments"]["execution"]
            if execution not in observed:
                observed.add(execution)
                rows.append(current)
                current = []
    groups = [list(enumerate(rows[offset:offset + observations_per_segment], offset + 1))
              for offset in range(0, len(rows), observations_per_segment)]
    tail, reasoning_calls = [], 0
    for call in current:
        if call["component"] in _REASONING_COMPONENTS:
            if reasoning_calls == tail_reasoning_calls_per_segment:
                groups.append([(len(rows) + 1, tail)])
                tail, reasoning_calls = [], 0
            reasoning_calls += 1
        tail.append(call)
    if tail:
        groups.append([(len(rows) + 1, tail)])

    task = next((entry["task"] for entry in trace["history"] if entry["type"] == "task"), {})
    initial = _unwrap(task.get("initial_observation"))
    opening = [dict(status="ok", effects="none", result=initial)]
    initial_messages = _user_messages(initial)
    latest_message = initial_messages[-1] if initial_messages else None
    cut, fingerprints, observed = [], {}, set()
    for index, group in enumerate(groups):
        decided, outcomes, notes, reads, failures, completions = [], [], [], [], [], []
        calls = [call for _, cycle in group for call in cycle]
        start = opening
        goal = dict(initial_user_request=initial_messages or task.get("problem") or task.get("instruction"),
                    latest_user_message_before_segment=latest_message)
        executed = {call["arguments"]["decision"] for call in calls
                    if call["component"] == "execute" and requests[call["id"]]}
        observation_count = 0
        for step, cycle in group:
            for call in cycle:
                value = call.get("value") or {}
                name = call["component"]
                if call.get("status") in ("failed", "interrupted"):
                    failures.append(dict(step=step, **{key: call[key] for key in
                                         ("id", "component", "status", "arguments", "error", "error_type")
                                         if key in call}))
                if name in ("execute", "execute_rule"):
                    decided += [dict(step=step, execution_id=call["id"],
                                     action_id=request["action_id"],
                                     capability_id=request["capability_id"], arguments=request["arguments"])
                                for request in requests[call["id"]]]
                elif call.get("status") in ("failed", "interrupted"):
                    continue
                elif name in ("decide", "think_decide"):
                    if value.get("kind") == "completion_proposed":
                        completions.append(dict(step=step, id=call["id"], component=name, value=_unwrap(value)))
                    elif call["id"] not in executed:
                        notes.append(dict(step=step, id=call["id"], component=name, value=_unwrap(value)))
                elif _observation(name) and call.get("status") == "completed":
                    execution = call["arguments"]["execution"]
                    evidence = [dict(execution_id=execution, action_id=item.get("action_id"),
                                     action=actions.get(item.get("action_id")),
                                     status=item.get("status"), effects=item.get("effects"),
                                     result=_unwrap(item.get("result")))
                                for item in value.get("outcomes") or []]
                    if execution in observed:
                        reads.append(dict(step=step, execution_id=execution, observation_id=call["id"], outcomes=evidence))
                    else:
                        observed.add(execution)
                        observation_count += 1
                        outcomes += [dict(step=step, **item) for item in evidence]
                        opening = evidence or opening
                        for outcome in evidence:
                            messages = _user_messages(outcome["result"])
                            if messages:
                                latest_message = messages[-1]
                elif name in _REASONING_COMPONENTS:
                    notes.append(dict(step=step, id=call["id"], component=name, value=_unwrap(value)))
        first_step, last_step = group[0][0], group[-1][0]
        # Absolute step numbers locate evidence; only relative order belongs in repeat identity.
        fingerprint = json.dumps([[{**{key: value for key, value in item.items()
                                       if key not in ("execution_id", "action_id")},
                                    "step": item["step"] - first_step} for item in items]
                                  for items in (decided, outcomes)], sort_keys=True)
        first = fingerprints.setdefault(fingerprint, index) if decided or outcomes else index
        cut.append(dict(
            index=index, first_step=first_step, last_step=last_step,
            ids=[call["id"] for call in calls], shape=[call["component"] for call in calls],
            facts=dict(identical_repeat_of=None if first == index else first,
                       failed=any(item.get("status") == "failed" for item in outcomes + failures),
                       duplicate_within_segment=len(decided) != len({json.dumps(
                           {key: value for key, value in action.items()
                            if key not in ("step", "execution_id", "action_id")}, sort_keys=True)
                           for action in decided}),
                       actions=len(decided), observations=observation_count, supplementary_reads=len(reads)),
            state=dict(task_goal=goal, start_observation=start, decided=decided, outcome=outcomes,
                       **(dict(task_stop={key: trace[key] for key in ("status", "stop_reason") if key in trace})
                          if index == len(groups) - 1 else {}),
                       **(dict(completion_proposals=completions) if completions else {}),
                       **(dict(reasoning=notes) if notes else {}),
                       **(dict(component_failures=failures) if failures else {}),
                       **(dict(evidence_reads=reads) if reads else {}))))
    return cut


def runs(root, limit=None):
    """Canonical task runs under root, prior-campaign copies skipped, balanced across host statuses.

    Balancing matters: completed runs outnumber exhausted ones, and the check below asks whether
    the labels separate them.
    """
    groups, seen = collections.defaultdict(list), set()
    for path in sorted(pathlib.Path(root).rglob("run-*/result.json")):
        if "prior-campaign" in path.parts:
            continue
        record = json.loads(path.read_text())
        if "usage" not in record or not (path.parent / "trace.json").exists():
            continue
        key = (record.get("task_id"), record.get("status"), record["usage"].get("model_calls"),
               round(record.get("elapsed_seconds") or 0, 6))
        if key in seen:
            continue
        seen.add(key)
        groups[record["status"]].append((path.parent, record))
    found = []
    while groups and (limit is None or len(found) < limit):
        for status in sorted(groups):
            if groups[status]:
                found.append(groups[status].pop(0))
            if limit and len(found) >= limit:
                break
        groups = {status: items for status, items in groups.items() if items}
    return found


def measurements(segment):
    """Derive display values from a completed response; missing measurements remain missing."""
    if segment["status"] != "completed":
        return dict(progress=None, action_effectiveness=None, recovery_needed=None, status=segment["status"])
    answers = segment["response"]["answers"]
    effectiveness = answers.get("action_effectiveness")
    return dict(progress=answers["progress"]["score"], progress_confidence=answers["progress"]["confidence"],
                action_effectiveness=effectiveness["score"] if effectiveness else None,
                action_effectiveness_confidence=effectiveness["confidence"] if effectiveness else None,
                **(dict(action_effectiveness_missing_reason="unobserved_actions" if segment["state"]["decided"]
                        else "no_attempted_actions") if effectiveness is None else {}),
                recovery_needed=answers["recovery_needed"]["noul"], status="completed")


def _correlation(left, right):
    n = len(left)
    if not n:
        return float("nan")
    mean_l, mean_r = sum(left) / n, sum(right) / n
    cov = sum((a - mean_l) * (b - mean_r) for a, b in zip(left, right))
    spread = (sum((a - mean_l) ** 2 for a in left) * sum((b - mean_r) ** 2 for b in right)) ** 0.5
    return cov / spread if spread else 0.0


def report(labelled):
    """Does each predicate separate run outcomes, and do the two Scores duplicate each other?"""
    labelled = [item for item in labelled if item[3].get("status") == "completed"]
    if not labelled:
        print("No applicable semantic measurements")
        return
    groups = collections.defaultdict(list)
    for directory, record, row, answer in labelled:
        groups[record.get("verification_verdict") or record["status"]].append((row, answer))
    print(f'{"run outcome":18} {"segments":>8} {"progress":>9} {"effect.":>9} {"recovery":>9} '
          f'{"repeat":>7} {"failed":>7}')
    for name, items in sorted(groups.items()):
        def mean(get):
            values = [value for row, answer in items if (value := get(row, answer)) is not None]
            return sum(values) / len(values) if values else float("nan")
        print(f"{name:18} {len(items):8} {mean(lambda r, a: a['progress']):9.2f} "
              f"{mean(lambda r, a: a['action_effectiveness']):9.2f} "
              f"{mean(lambda r, a: a['recovery_needed']):9.2f} "
              f"{mean(lambda r, a: r['facts']['identical_repeat_of'] is not None):6.1%} "
              f"{mean(lambda r, a: r['facts']['failed']):6.1%}")
    answers = [answer for _, _, _, answer in labelled]
    paired = [answer for answer in answers if answer["action_effectiveness"] is not None]
    print(f"\nScore correlation  progress vs action_effectiveness: "
          f"{_correlation([a['progress'] for a in paired], [a['action_effectiveness'] for a in paired]):+.2f} "
          f"({len(paired)} paired measurements)")
    print(f"recovery_needed vs progress: "
          f"{_correlation([a['recovery_needed'] for a in answers], [a['progress'] for a in answers]):+.2f}")
    rows = [row for _, _, row, _ in labelled]
    print(f"recovery_needed vs code-detected identical repeat: "
          f"{_correlation([a['recovery_needed'] for a in answers], [float(r['facts']['identical_repeat_of'] is not None) for r in rows]):+.2f}")


def evaluation_runs(directory):
    """Pair every recorded run of one evaluation with its directory, in host order."""
    settled = json.loads((directory / "result.json").read_text())
    return [(directory / row["directory"], row) for row in settled["runs"]
            if (directory / row["directory"] / "trace.json").exists()]


def _turn_table(rows, answers):
    lines = [f"| segment | steps | observations | progress (0–{len(PROGRESS) - 1}) | "
             f"effectiveness (0–{len(EFFECTIVENESS) - 1}) | recovery probability | invocation IDs |",
             "| ---: | --- | ---: | ---: | ---: | ---: | --- |"]
    for row, answer in zip(rows, answers):
        values = [answer.get(key + "_missing_reason", answer["status"]) if answer[key] is None else f"{answer[key]:.2f}"
                  for key in ("progress", "action_effectiveness", "recovery_needed")]
        lines.append(f"| {row['index']} | {row['first_step']}–{row['last_step']} | {row['facts']['observations']} | "
                     + " | ".join(values) + " | " + ", ".join(row['ids']) + " |")
    return "\n".join(lines)


def write_evidence(out, per_run):
    """Emit one rollup the researcher always sees and per-run detail it opens on demand.

    Verdicts and counts come from host records. Every label is a model judgment and is
    labelled as a claim, like a candidate rationale.
    """
    out.mkdir(parents=True, exist_ok=True)
    (out / "labels").mkdir(exist_ok=True)
    table = ["| candidate | task | verdict | segments | measured | detail |",
             "| --- | --- | --- | ---: | ---: | --- |"]
    for directory, record, rows, answers in per_run:
        name = directory.name
        (out / "labels" / f"{name}.md").write_text(
            f"# {name} — model-judged segment labels (claims, not host outcomes)\n\n"
            f"Host record: candidate {record['candidate_id']}, task {record['task_id']}, "
            f"status {record['status']}, verdict {record['verification_verdict']}.\n\n"
            + _turn_table(rows, answers) + "\n")
        table.append(f"| {record['candidate_id']} | {record['task_id']} | {record['verification_verdict']} "
                     f"| {len(rows)} | {sum(a.get('status') == 'completed' for a in answers)} "
                     f"| labels/{name}.md |")
    (out / "labels.md").write_text(
        "# Model-judged segment labels\n\n"
        f"Schema: {SCHEMA_VERSION}. Each measurement covers up to {OBSERVATIONS_PER_SEGMENT} "
        "distinct observed executions, without overlapping steps; the last group may be shorter. "
        "Supplementary observation pages are evidence, not additional executed steps. "
        "Verdicts and segment counts are host records. Measurements use public segment evidence; "
        "final task scores are not model inputs. Treat measurements as claims, not verified causes. "
        "Every segment receives progress and recovery judgments, including tails without a new observed outcome. "
        "Action effectiveness is missing when no new action outcome was observed; missing values are not zeros.\n\n"
        + "\n".join(table) + "\n")
    return out / "labels.md"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", help="campaign directory under .artifacts/")
    parser.add_argument("--evaluation", help="label one settled evaluation directory and write researcher evidence")
    parser.add_argument("--out-dir", help="new directory for analysis records and researcher evidence")
    parser.add_argument("--runs", type=int, default=20, help="task runs to label")
    parser.add_argument("--dry-run", action="store_true", help="count segments and estimate input size without calling Jev")
    arguments = parser.parse_args()

    selected = (evaluation_runs(pathlib.Path(arguments.evaluation)) if arguments.evaluation
                else runs(arguments.root, arguments.runs))
    pairs = [(directory, record, turns(json.loads((directory / "trace.json").read_text())))
             for directory, record in selected]
    total = sum(len(rows) for _, _, rows in pairs)
    sizes = [len(json.dumps(row["state"])) for _, _, rows in pairs for row in rows]
    observed = sum(bool(row["state"]["outcome"]) for _, _, rows in pairs for row in rows)
    characters = sum(sizes)
    print(f"{SCHEMA_VERSION}: up to {OBSERVATIONS_PER_SEGMENT} observations per segment")
    print(f"{len(pairs)} runs, {total} segments to analyze ({observed} with observed outcomes, "
          f"{total - observed} without), "
          f"~{characters // 4:,} state tokens by characters / 4, excluding questions; dollar price not frozen")
    if arguments.dry_run or not total:
        if sizes:
            print(f"segment size: min {min(sizes) // 4} / median {sorted(sizes)[len(sizes) // 2] // 4} / "
                  f"max {max(sizes) // 4} tokens")
        if total:
            shapes = collections.Counter(" → ".join(row["shape"])
                                         for _, _, rows in pairs for row in rows)
            print("\n--- segment shapes seen ---")
            for shape, count in shapes.most_common(8):
                print(f"  {count:4}  {shape}")
            directory, record, rows = next(pair for pair in pairs if pair[2])
            print(f"\n--- {directory.name} ({record['task_id']}, {record['status']}): "
                  f"{len(rows)} segments; segment {min(1, len(rows) - 1)} input preview ---")
            print(json.dumps(rows[min(1, len(rows) - 1)]["state"], indent=1, ensure_ascii=False)[:1400])
        return
    if not arguments.out_dir:
        parser.error("--out-dir is required to preserve Jev inputs, responses and usage outside the source campaign")
    from loopblox.analysis.jev import analyze_run, configuration
    from loopblox.runtime.controller import ModelMeter
    config = configuration()
    output = pathlib.Path(arguments.out_dir)
    output.mkdir(parents=True, exist_ok=False)
    meter = ModelMeter(output / "usage.json", seconds=None, output_tokens=None, model_calls=None)
    labelled, per_run = [], []
    for index, (directory, record, _) in enumerate(pairs):
        destination = output / f"run-{index:04d}"
        destination.mkdir()
        trace = destination / "trace.json"
        trace.write_bytes((directory / "trace.json").read_bytes())
        result = analyze_run(trace, configuration=config, meter=meter, scope=f"analysis-{index}")
        rows = [segment for segment in result["segments"] if segment["status"] != "split"]
        answers = [measurements(segment) for segment in rows]
        per_run.append((destination, record, rows, answers))
        labelled.extend((destination, record, row, answer) for row, answer in zip(rows, answers))
    print("wrote", write_evidence(output, per_run))
    report(labelled)


if __name__ == "__main__":
    main()
