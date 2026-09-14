"""The approved behavioral library. No runtime registration or controller prompts."""

import copy
import json


def object_schema(properties, required=None):
    return dict(type="object", properties=properties,
                required=list(properties) if required is None else required,
                additionalProperties=False)


_TEXT = {"type": "string"}
_TEXTS = {"type": "array", "items": _TEXT}


def reference_schema(*categories):
    return {"type": "string", "reference_categories": list(categories),
            "description": "ID of a completed component invocation in this task run; the host reads its stored original."}


_CONTEXT_REF = reference_schema("context")
_INPUTS = {"type": "array", "items": reference_schema("analysis_result", "observation"),
           "description": "Optional existing background evidence appended to the context view; omission is an empty list. "
                          "No new text, raw execution IDs, context IDs, or independently assigned subgoals."}
_CONTEXT = object_schema({"context": _CONTEXT_REF})
_ANALYSIS = object_schema({"context": _CONTEXT_REF, "inputs": _INPUTS}, ["context"])
_TOOL_FILTERS = {
    "all": ("inspect", "mutate", "test"), "inspect": ("inspect",),
    "inspect_test": ("inspect", "test"), "inspect_mutate": ("inspect", "mutate"), "test": ("test",),
}
_DECISION = object_schema({
    **_ANALYSIS["properties"],
    "tool_filter": {"enum": list(_TOOL_FILTERS), "default": "all",
                    "description": "Filter disclosed tool kinds, not the completion target: "
                                   + "; ".join(f"{name}={','.join(kinds)}" for name, kinds in _TOOL_FILTERS.items())},
    "selection": {"enum": ["one", "sequence"], "default": "one",
                  "description": "one permits exactly one selected action; sequence permits a nonempty ordered list. "
                                 "Both permit a whole-task completion proposal."},
}, ["context"])
_DROP = {"enum": ["none", "failed_results"], "default": "none",
         "description": "none selects every record in scope. failed_results excludes observations whose status "
                        "is failed, and the requesting decision turn when every observation it produced is "
                        "excluded. Recorded history is unchanged; a later view can select those records again."}
_VIEW = object_schema({"drop": _DROP}, [])
_RESULTS = object_schema({"execution": reference_schema("execution")})
_CONTEXT_VALUE = object_schema({"records": {"type": "array", "items": {"type": "integer"}}})
_EXECUTION_VALUE = object_schema({
    "status": {"enum": ["ok", "failed"]},
    "outcomes": {"type": "array", "items": object_schema({
        "action_id": _TEXT, "status": {"enum": ["ok", "failed"]},
        "result": {}, "effects": {"enum": ["none", "applied", "unknown"]}, "code": _TEXT,
    }, ["action_id", "status", "result", "effects"])},
})
RECENT_TURNS = 4
BRIEF_CHARACTERS = 1200
BRIEF_MARKER = "… [omitted]"


def brief_observation(result, preserve_fields=()):
    """Bound optional content while retaining the tool's declared fields verbatim."""
    preserved = ({key: result[key] for key in preserve_fields if key in result}
                 if isinstance(result, dict) else {})
    content = ({key: value for key, value in result.items() if key not in preserved}
               if preserved else result)
    text = json.dumps(content, ensure_ascii=False)
    if len(text) > BRIEF_CHARACTERS:
        text = text[:BRIEF_CHARACTERS - len(BRIEF_MARKER)] + BRIEF_MARKER
    return json.dumps(dict(preserved=preserved, brief=text), ensure_ascii=False) if preserved else text


_DECISION_RULES = (
    "Use kind=actions to carry out the next step through the disclosed capabilities. "
    "A plan, promise, or intention to use tools is not completed work. "
    "Use kind=completion_proposed only for the final task response after performing the work, or to explain an actual blocker. "
    "Follow each capability's exact argument schema. Action IDs are assigned by the host; do not generate them."
)

_MODEL_FAILURES = (
    "Invalid arguments or result references are candidate errors. Invalid model output is an operational "
    "failure, retained with its cost; there is no automatic format-repair call. The fixed gateway may retry "
    "one recognized transient request fault with no effects, using the identical request. Limits, "
    "interruption and host failures propagate; they do not produce a successful result."
)
_EXECUTION_FAILURES = (
    "Invalid requests and unusable references are candidate errors. Ordinary tool failures return "
    "status=failed and their reported effects; unexpected tool exceptions return failed/unknown. "
    "Limits, interruption and host failures propagate, retaining the attempted prefix and any uncertain "
    "in-flight effects. No implicit retry, replay or rollback."
)
_MODEL_STATE = (
    "Appends a model_turn to host history, eligible for later context views. Existing views do not change. "
    "The output is recorded evidence, not a mutation of the plan, workspace or controller policy."
)


def analysis_contract(scope, behavior, returns):
    """Shared execution contract for the five analysis components."""
    return dict(surfaces=["Turn Control"], scope=scope, behavior=behavior,
                model_calls="One logical model request; no tool calls. Transport attempts are counted separately.",
                state_effects=_MODEL_STATE, returns=returns, failures=_MODEL_FAILURES)


def decision_contract(behavior):
    return dict(
        surfaces=["Turn Control"], scope="One decision about the whole disclosed task.", behavior=behavior,
        model_calls="One logical model request; no tool calls. Transport attempts are counted separately.",
        state_effects="Appends a model_turn and registers host-assigned action IDs with immutable arguments. "
                      "Registration does not execute actions or modify the environment.",
        returns="ActionsSelected with a nonempty action list, or CompletionProposed with response text. "
                "If the tool filter matches no tools, only a completion proposal is available. The caller owns execution, "
                "observation, another decision, review and final return. No fixed number of rounds.",
        failures=_MODEL_FAILURES)


_FAMILIES = {
    "context": dict(
        id="context", label="Context / Evidence",
        description="Select, summarize and publish task evidence for later model calls. "
                    "Views and observations retain the host's original records."),
    "propose": dict(
        id="propose", label="Propose",
        description="Produce analysis, hypotheses, plans, subtasks or action/completion proposals. "
                    "Proposals do not execute tools or end the controller."),
    "assess": dict(
        id="assess", label="Assess",
        description="Review a selected target or diagnose observed failures. Current members return "
                    "model judgments, not verified facts; tool-based checks use Act and observed evidence."),
    "act": dict(
        id="act", label="Act",
        description="Execute approved tools from model-selected actions or explicit controller requests. "
                    "Record actual results and effects; the controller owns observation and recovery."),
}


_DEFINITIONS = {
    "context_full": dict(
        family=_FAMILIES["context"],
        category="context", parameters=_VIEW, output=_CONTEXT_VALUE,
        description="Freeze all model turns and explicit observations; always include the task. "
                    "An optional drop rule can leave failed results out of this view.",
        contract=dict(
            surfaces=["State / Context"], scope="One immutable view of the current task history.",
            behavior="Select the indices of every model_turn and explicit observation currently recorded. "
                     "The task is supplied separately in every model request; raw tool events "
                     "are not selected. All model turns count, including summaries and analyses. "
                     "drop is applied last, after the records in scope are selected.",
            model_calls="Zero model or tool calls.", state_effects="Stores the view as an invocation result; adds no history entry.",
            returns="Returns records (history indices), not copied messages. Later events require a new view.",
            failures="Unexpected arguments are candidate errors. Time limits and host interruption propagate.")),
    "context_recent": dict(
        family=_FAMILIES["context"],
        category="context", parameters=_VIEW, output=_CONTEXT_VALUE,
        description=f"Freeze the last {RECENT_TURNS} model turns and their observations; always include the task. "
                    "An optional drop rule can leave failed results out of this view.",
        contract=dict(
            surfaces=["State / Context"], scope="One immutable recent-history view within the current task.",
            behavior=f"With more than {RECENT_TURNS} model_turn entries, select model turns and observations "
                     f"from the {RECENT_TURNS}th-last model turn onward; otherwise select all of them. "
                     "These are model turns, not user messages or tool rounds: analysis and summary calls "
                     "also consume the window. The task is always supplied separately. drop is applied last, "
                     "to the records already inside the window; it does not pull in older records.",
            model_calls="Zero model or tool calls.", state_effects="Stores a view without deleting or changing history.",
            returns="Returns records (history indices). Explicit analysis_result/observation inputs may supplement the view.",
            failures="Unexpected arguments are candidate errors. Time limits and host interruption propagate.")),
    "context_summary": dict(
        family=_FAMILIES["context"],
        category="context", parameters=_CONTEXT,
        model_output=object_schema({"summary": _TEXT}),
        output=object_schema({**_CONTEXT_VALUE["properties"], "summary": _TEXT}),
        description="Summarize a frozen view in one model call; retain original factual records.",
        contract=dict(
            surfaces=["State / Context"], scope="The supplied frozen context view, within the current task.",
            behavior="Send the task and selected context records to the fixed summarizer. Return a new view "
                     "whose only history index points to that summary model turn. A supplied summary view "
                     "is summarized again; this component never selects a compression threshold.",
            model_calls="One logical model request; no tool calls. Every invocation summarizes, including empty views.",
            state_effects="Appends the summary model_turn and stores the new view. Original records remain. "
                          "Later full/recent views may include both original turns and the summary.",
            returns="Returns records and summary text. Passing this context ID uses the summary plus the task; "
                    "it does not automatically include the original selected records.",
            failures=_MODEL_FAILURES),
        prompt="Summarize the supplied task evidence for subsequent task work. Preserve established facts, "
               "decisions, action outcomes, unresolved questions, and relevant references. Do not solve a new "
               "step or invent evidence. Return the summary."),
    "think": dict(
        family=_FAMILIES["propose"],
        category="analysis_result", parameters=_ANALYSIS,
        output=object_schema({"observations": _TEXTS, "hypotheses": _TEXTS, "unknowns": _TEXTS}),
        description="Analyze the current evidence without selecting executable actions.",
        contract=analysis_contract(
            "Analysis of the whole task through the supplied evidence.",
            "Separate observations, hypotheses and unknowns. No action registration or implicit subsequent Decide. "
            "This is an observable analysis result, not access to hidden model reasoning.",
            "Returns observations, hypotheses and unknowns as text lists. The caller decides how to use them."),
        prompt="Analyze the task evidence. Separate observations, plausible hypotheses, and unknowns. "
               "Do not issue tool calls or claim work has been executed."),
    "decompose": dict(
        family=_FAMILIES["propose"],
        category="analysis_result", parameters=_ANALYSIS, output=object_schema({"subtasks": _TEXTS}),
        description="Break the remaining task into concrete subtasks.",
        contract=analysis_contract(
            "Decomposition of the remaining whole task.",
            "Produce textual subtasks. Does not create workers, assign independent goals or execute subtasks.",
            "Returns a subtasks list. Subtask text is advisory; it is not an executable action or subagent handle."),
        prompt="Decompose the remaining task into concrete subtasks grounded in the evidence. "
               "Return subtasks, not executable tool requests."),
    "plan": dict(
        family=_FAMILIES["propose"],
        category="analysis_result", parameters=_ANALYSIS,
        output=object_schema({"steps": _TEXTS, "completion_checks": _TEXTS}),
        description="Write an ordered plan and checks for completion, without executing it.",
        contract=analysis_contract(
            "Planning for the remaining whole task.",
            "Produce ordered textual steps and proposed completion checks. Does not register actions, "
            "run the checks or replace a persistent plan. A revised plan is another invocation result.",
            "Returns steps and completion_checks. The caller decides whether to critique or supply the plan to work."),
        prompt="Write an ordered plan for the remaining task and concrete completion checks. "
               "Use provided analysis and feedback. The plan is an analysis result, not a tool request."),
    "critique": dict(
        family=_FAMILIES["assess"],
        category="analysis_result", parameters=object_schema({
            **_ANALYSIS["properties"],
            "target": {**reference_schema("analysis_result", "decision"),
                       "description": "Required review target: one completed analysis result, decision (actions or "
                                      "completion). The host supplies its ID, component, "
                                      "category and original value separately from background evidence."},
        }, ["context", "target"]),
        output=object_schema({"accept": {"type": "boolean"}, "issues": _TEXTS}),
        description="Review one explicitly selected analysis result or decision against the available evidence.",
        contract=analysis_contract(
            "Review of one target in relation to the whole task's requirements.",
            "The required target reference selects the object being judged. The host includes its identity "
            "and stored value even if it is already in context or absent from that view. Context and optional "
            "inputs are background evidence, not alternative targets. Selecting a target does not hide other "
            "analysis results in context. No tools or hidden verifier are called.",
            "Returns accept and issues. accept is a model opinion, not verified success or a termination signal. "
            "The caller owns acceptance, revision and repetition."),
        prompt="Critique only the explicit target's value against task requirements and available evidence. "
               "The target identifies the object under review; context and inputs are background evidence, "
               "not other review targets. Accept only if this target has no material issue needing revision. "
               "List actionable issues about this target. "
               "Do not claim hidden verification or execute actions."),
    "reflect": dict(
        family=_FAMILIES["assess"],
        category="analysis_result", parameters=_ANALYSIS,
        output=object_schema({"causes": _TEXTS, "adjustments": _TEXTS}),
        description="Diagnose observed failures and propose changes to the approach.",
        contract=analysis_contract(
            "Diagnosis of failures present in the supplied whole-task evidence.",
            "Propose causes and adjustments. The caller supplies relevant failure evidence; the host does not "
            "require a preceding failed action. Reflection does not change policy or retry a tool by itself.",
            "Returns causes and adjustments. Both are model-produced text lists, not verified root causes or applied changes."),
        prompt="Diagnose failures in the supplied evidence. Separate plausible causes from established facts "
               "and propose concrete adjustments to the approach. Do not execute actions."),
    "decide": dict(
        family=_FAMILIES["propose"],
        category="decision", parameters=_DECISION, output="decision",
        description="Select the next action(s) or propose completion from the supplied evidence and analysis results.",
        contract=decision_contract(
            "Use the task, frozen view, optional result references, remaining limits and filtered capabilities "
            "to select actions or completion. No separate analysis result is returned."),
        prompt="Choose the next executable action or sequence using the supplied evidence and analysis results. "
               + _DECISION_RULES),
    "think_decide": dict(
        family=_FAMILIES["propose"],
        category="decision", parameters=_DECISION, output="decision",
        description="Analyze the task and select actions or completion jointly in one model call.",
        contract=decision_contract(
            "The fixed prompt asks for reasoning and selection jointly. The returned schema is exactly the "
            "Decide schema, with no separate Think output. Think then Decide uses two calls and is not a visual expansion of this call."),
        prompt="Reason about the task, current evidence, and alternatives, then choose the next executable "
               "action or sequence in this same turn. " + _DECISION_RULES),
    "execute": dict(
        family=_FAMILIES["act"],
        category="execution", output=_EXECUTION_VALUE,
        parameters=object_schema({"decision": reference_schema("decision"), "take": {
            "enum": ["one", "remaining"], "default": "remaining",
            "description": "Select the next unattempted action or all remaining actions from this decision."}}, ["decision"]),
        description="Execute pending registered model actions serially, stopping at the first failure.",
        contract=dict(
            surfaces=["Action Runtime"], scope="The unattempted prefix of one action decision.",
            behavior="Require an actions decision; execute selected registered requests in order. Stop at "
                     "the first ordinary failure. Unattempted siblings remain available to another Execute; "
                     "already attempted IDs cannot be executed again, even after failure.",
            model_calls="Zero direct model requests. Up to the selected number of tool calls, subject to failure and limits.",
            state_effects="Mark each dispatched action attempted; record tool_call, tool_result and actual effects. "
                          "May modify the environment. Raw tool results do not enter context views until observed.",
            returns="Returns status and outcomes for the attempted prefix. A tool failure yields a completed "
                    "component invocation with value.status=failed. The caller chooses observation and recovery.",
            failures=_EXECUTION_FAILURES)),
    "execute_rule": dict(
        family=_FAMILIES["act"],
        category="execution", output=_EXECUTION_VALUE,
        parameters=object_schema({"capability_id": {**_TEXT, "description": "An available tool from env.tools."},
                                  "arguments": {"type": "object", "description": "Must satisfy that tool's parameter schema."}}),
        description="Execute a fresh controller rule action directly, with no model endorsement.",
        contract=dict(
            surfaces=["Action Runtime"], scope="One fresh controller-origin tool request.",
            behavior="Validate and dispatch the supplied capability and arguments through the same host gateway. "
                     "No decision reference or model endorsement is needed. Each invocation creates a new action ID; "
                     "repeating identical arguments is a new action, not an idempotent replay.",
            model_calls="Zero direct model requests; one tool call if validation and limits allow dispatch.",
            state_effects="Record origin=controller, tool events and effects; may modify the environment. "
                          "Results require an Observation before context views include them.",
            returns="Returns status and one outcome on normal return, including ordinary tool failure.",
            failures=_EXECUTION_FAILURES)),
    "observe_full": dict(
        family=_FAMILIES["context"],
        category="observation", parameters=_RESULTS, output=_EXECUTION_VALUE,
        description="Append full execution results to model-visible history once.",
        contract=dict(
            surfaces=["State / Context"], scope="One completed Execute or ExecuteRule result, including status=failed.",
            behavior="Copy the execution's status and outcomes without shortening results. Only one observation "
                     "of either policy is allowed per execution ID.",
            model_calls="Zero model or tool calls.",
            state_effects="Append one observation eligible for new context views and explicit inputs. "
                          "Existing views and raw execution records remain unchanged.",
            returns="Returns the full status/outcomes value. Does not judge success, recover or continue the loop.",
            failures="Invalid or already-observed execution references are candidate errors. An interrupted "
                     "execution is not a completed reference; its partial results remain in the trace. Limits and host faults propagate.")),
    "observe_brief": dict(
        family=_FAMILIES["context"],
        category="observation", parameters=_RESULTS, output=_EXECUTION_VALUE,
        description=f"Append results once, retaining tool-declared observation fields in full and bounding "
                    f"the remaining serialized content to {BRIEF_CHARACTERS} characters; retain IDs, statuses, and effects.",
        contract=dict(
            surfaces=["State / Context"], scope="One completed Execute or ExecuteRule result, including status=failed.",
            behavior="For object results, extract any present top-level fields named by the originating tool's "
                     "preserve_observation_fields declaration. JSON-serialize the remaining content, even if short, "
                     f"and cut it to {BRIEF_CHARACTERS} characters including '{BRIEF_MARKER}' when needed. "
                     "If fields were extracted, return a JSON string containing preserved (their full original values) "
                     "and brief (the bounded content string); otherwise return only the bounded string. "
                     "Preserved fields and wrapper overhead are outside the character bound. The host fixes this "
                     "tool declaration; candidate code cannot override it. Preserve action IDs, status, effects "
                     "and optional error code. The bounded content need not be valid JSON. "
                     "No semantic summarization; one observation per execution ID.",
            model_calls="Zero model or tool calls.",
            state_effects="Append one shortened observation; raw results remain unchanged in execution history. "
                          "New full context includes the shortened observation, not the omitted raw tool result.",
            returns="Returns status/outcomes with every result represented as a string. No success judgment or recovery.",
            failures="Invalid or already-observed execution references are candidate errors. An interrupted "
                     "execution is not a completed reference; its partial results remain in the trace. Limits and host faults propagate.")),
}

# Brief observation changes the representation of result, even when nothing is cut.
_DEFINITIONS["observe_brief"]["output"] = copy.deepcopy(_EXECUTION_VALUE)
_DEFINITIONS["observe_brief"]["output"]["properties"]["outcomes"]["items"]["properties"]["result"] = _TEXT


def catalog(exposed=None):
    """Derive a public catalog, optionally narrowing the root composition boundary."""
    result = {name: copy.deepcopy(spec) for name, spec in _DEFINITIONS.items()}
    if exposed is not None and (not isinstance(exposed, dict) or not exposed):
        raise ValueError("The exposed boundary must name at least one approved component")
    narrowed = {}
    for name, options in (exposed if exposed is not None else {name: {} for name in result}).items():
        if name not in result or not isinstance(options, dict):
            raise ValueError(f"Invalid exposed component: {name!r}")
        spec = result[name]
        parameters = spec["parameters"]
        for parameter, choices in options.items():
            schema = parameters["properties"].get(parameter, {})
            if ("enum" not in schema or not isinstance(choices, list) or not choices
                    or any(choice not in schema["enum"] for choice in choices)
                    or len(choices) != len(set(choices))):
                raise ValueError(f"Boundary must narrow discrete options: {name}.{parameter}")
            schema["enum"] = list(choices)
            if "default" in schema and schema["default"] not in choices:
                del schema["default"]
                if parameter not in parameters["required"]:
                    parameters["required"].append(parameter)
        if spec["category"] == "decision":
            selection = "sequence" if "sequence" in parameters["properties"]["selection"]["enum"] else "one"
            spec["output"] = decision_schema(None, selection)
            action = spec["output"]["anyOf"][0]["properties"]["actions"]["items"]
            action["properties"]["action_id"] = _TEXT.copy()
            action["required"].append("action_id")
        narrowed[name] = spec
    return narrowed


def definition(name):
    if not isinstance(name, str) or name not in _DEFINITIONS:
        raise ValueError(f"Unknown approved component: {name!r}")
    return copy.deepcopy(_DEFINITIONS[name])


def capability_kinds(tool_filter):
    return _TOOL_FILTERS[tool_filter]


def decision_schema(capabilities, selection):
    capability = {"type": "string"}
    if capabilities is not None:
        capability["enum"] = [item["capability_id"] for item in capabilities]
    action = object_schema({
        "capability_id": capability,
        "arguments": {"type": "object"},
    })
    if capabilities:
        action = {"anyOf": [object_schema({
            "capability_id": {"const": item["capability_id"]},
            "arguments": copy.deepcopy(item["parameters"]),
        }) for item in capabilities]}
    actions = dict(type="array", items=action, minItems=1)
    if selection == "one":
        actions["maxItems"] = 1
    choices = [object_schema({"kind": {"const": "completion_proposed"}, "response": _TEXT})]
    if capabilities is None or capabilities:
        choices.insert(0, object_schema({"kind": {"const": "actions"}, "actions": actions}))
    return {"anyOf": choices}


def schema_shape(schema):
    """Readable shape of the existing JSON schema; not another validation language."""
    if "anyOf" in schema:
        return " | ".join(schema_shape(choice) for choice in schema["anyOf"])
    if "const" in schema:
        return json.dumps(schema["const"], ensure_ascii=False)
    if "enum" in schema:
        return " | ".join(json.dumps(value, ensure_ascii=False) for value in schema["enum"])
    if "reference_categories" in schema:
        return "ref<" + "/".join(schema["reference_categories"]) + ">"
    kind = schema.get("type", "any")
    if kind == "object" and "properties" in schema:
        required = schema.get("required", [])
        fields = [name + ("" if name in required else "?") + ": " + schema_shape(value)
                  for name, value in schema["properties"].items()]
        return "{" + ", ".join(fields) + "}"
    if kind == "array":
        shape = "[" + schema_shape(schema.get("items", {})) + "]"
        if "minItems" in schema:
            shape += f" (min {schema['minItems']})"
        if "maxItems" in schema:
            shape += f" (max {schema['maxItems']})"
        return shape
    return kind


def render_contracts(component_catalog):
    """Render either the full catalog or an episode's already narrowed catalog."""
    lines = [
        "# Component contracts", "",
        "Generated from `components.py`; do not edit this document independently. "
        "Regenerate the repository reference with `python3 -B components.py --markdown > COMPONENTS.md`. "
        "Episode copies are generated from that episode's exposed, narrowed catalog.", "",
        "These are current executable contracts, not a universal Harness taxonomy. "
        "Concepts and composition boundaries are defined in `loop.md`. The JSON catalog retains "
        "the exact schemas and fixed prompts; the shapes below are reading aids, not executable syntax.", "",
        "## Shared invocation rules", "",
        "- Call `env.component(name, **arguments)`; normal return is `{'id': ..., 'value': ...}`. "
        "Each output below describes `value`. References use the invocation ID and resolve the host's "
        "original result within this run. Local dictionary edits cannot change it.",
        "- Each callable subcomponent has a `family` with an ID, label and description. Families organize "
        "the catalog; they are not callable stages, reference types or permission groups. The controller "
        "can mix, skip and repeat exposed subcomponents in ordinary Python. Parameters belong to each "
        "subcomponent; there is no family-level mode dispatcher or mandatory work-loop component.",
        "- The parameter schema owns accepted reference categories; each component's category owns its "
        "returned reference type, shown in the catalog. Equal value shapes do not make reference types "
        "interchangeable. These categories are API result "
        "types, not Harness surfaces or expansion levels. Optional fields have `?`; omitted inputs "
        "mean no supplemental result references. Only listed arguments and approved options are accepted.",
        "- A model request sees the task, its frozen context records, optional input references, the "
        "fixed component instruction, remaining limits and (for decisions only) filtered capabilities. "
        "Critique also receives its required target's identity and original value separately from background evidence. "
        "Controllers cannot provide replacement prompts or schemas. Component prompts are in the JSON catalog.",
        "- All invocations are recorded. Model turns become eligible for later context views; raw tool "
        "results require Observation. Analysis results are not private by default: later full context may include "
        "them even without explicit inputs. Existing context snapshots never grow automatically.",
        "- Model-call counts describe logical requests when execution reaches them. Invalid input, "
        "exhaustion or interruption may stop earlier. One exact transient transport retry is host-owned; "
        "every attempt is charged. Work performed inside "
        "an environment tool follows that tool's own contract.",
        "- A normal component return is not task termination or verified success. An execution can "
        "return value.status=failed while its invocation status is completed. Exceptions instead mark "
        "the invocation failed/interrupted and propagate; incurred costs and effects remain recorded.",
        "- The caller owns trigger conditions, repetition, branches and final return. Components have "
        "no permanent D-level. Implementations stay fixed even when visible; an episode may expose "
        "only a subset of components and narrow their options. Only the episode catalog grants root-call access.",
        "", "## Component families", "",
        "Only the supplied catalog's subcomponents appear below. Family membership does not expose "
        "siblings or change argument/reference validation.",
    ]
    groups = {}
    for name, spec in component_catalog.items():
        groups.setdefault(spec["family"]["id"], []).append((name, spec))
    for members in groups.values():
        family = members[0][1]["family"]
        lines.extend(["", f"### {family['label']} (`{family['id']}`)", "", family["description"], "",
                      "| Subcomponent | Returned reference type | Surfaces |", "| --- | --- | --- |"])
        for name, spec in members:
            lines.append(f"| [{name}](#{name}) | `ref<{spec['category']}>` | {', '.join(spec['contract']['surfaces'])} |")
    for name, spec in component_catalog.items():
        lines.extend(["", f"## {name}", "", spec["description"], "",
                      f"**Family:** {spec['family']['label']} (`{spec['family']['id']}`).", ""])
        for field, title in (("scope", "Scope"), ("behavior", "Internal behavior"),
                             ("model_calls", "Calls"), ("state_effects", "State and effects"),
                             ("returns", "Return and caller responsibility"), ("failures", "Failure contract")):
            lines.extend([f"**{title}:** {spec['contract'][field]}", ""])
        parameters = spec["parameters"]
        if parameters["properties"]:
            lines.extend(["**Inputs and allowed options:**", ""])
            for parameter, schema in parameters["properties"].items():
                presence = "required" if parameter in parameters["required"] else "optional"
                default = "; default=" + json.dumps(schema["default"]) if "default" in schema else ""
                lines.append(f"- `{parameter}` — `{schema_shape(schema)}`; {presence}{default}. "
                             + schema.get("description", ""))
            lines.append("")
        else:
            lines.extend(["**Inputs:** none.", ""])
        lines.extend(["**Returned value:**", "", "```text", schema_shape(spec["output"]), "```"])
        if spec["category"] == "decision":
            lines.extend(["", "The runtime specializes this union using the invocation's selection option "
                          "and available filtered tools; each action's arguments must match its tool schema."])
    return "\n".join(lines) + "\n"


def validate(value, schema):
    """Validate the JSON contract subset used by this library and its capabilities."""
    if "anyOf" in schema:
        for choice in schema["anyOf"]:
            try:
                validate(value, choice)
                return
            except ValueError:
                pass
        raise ValueError("Value does not match an allowed output")
    if "const" in schema and value != schema["const"]:
        raise ValueError("Unexpected constant")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"Expected one of {schema['enum']}")
    kind = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool, "null": type(None)}
    if kind in types and type(value) is not types[kind]:
        raise ValueError(f"Expected {kind}")
    if kind == "number" and type(value) not in {int, float}:
        raise ValueError("Expected number")
    if kind == "object":
        properties = schema.get("properties", {})
        if not set(schema.get("required", ())) <= value.keys():
            raise ValueError("Missing required fields")
        if schema.get("additionalProperties") is False and not value.keys() <= properties.keys():
            raise ValueError("Unexpected fields")
        for key in value.keys() & properties.keys():
            validate(value[key], properties[key])
    elif kind == "array":
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            raise ValueError("Invalid number of items")
        for item in value:
            validate(item, schema.get("items", {}))
    elif kind == "integer" and value < schema.get("minimum", -float("inf")):
        raise ValueError("Value below minimum")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markdown", action="store_true", help="Render current component contracts as Markdown")
    args = parser.parse_args()
    print(render_contracts(catalog()) if args.markdown else json.dumps(catalog(), ensure_ascii=False, indent=2),
          end="" if args.markdown else "\n")
