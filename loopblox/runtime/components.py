"""The approved behavioral library; Judge alone accepts caller-defined typed questions."""

import copy
import json
import math


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
_INPUTS = {"type": "array", "items": reference_schema("analysis_result", "plan", "observation"),
           "description": "Optional existing background evidence appended to the context view; omission is an empty list. "
                          "No new text, raw execution IDs or context IDs. Decision scope uses a separate plan-step reference."}
_CONTEXT = object_schema({"context": _CONTEXT_REF})
_ANALYSIS = object_schema({"context": _CONTEXT_REF, "inputs": _INPUTS}, ["context"])
_JUDGMENT_TEXT = {"type": "string", "minLength": 1}
_PROBABILITY = {"type": "number", "minimum": 0, "maximum": 1}
_JUDGE_QUESTION = {"anyOf": [
    object_schema({"type": {"const": "noul"}, "instructions": _JUDGMENT_TEXT,
                   "criteria": object_schema({"true": _JUDGMENT_TEXT, "false": _JUDGMENT_TEXT}, [])},
                  ["type", "instructions"]),
    object_schema({"type": {"const": "choice"}, "instructions": _JUDGMENT_TEXT,
                   "criteria": {"type": "object", "minProperties": 2, "maxProperties": 255,
                                "propertyNames": _JUDGMENT_TEXT, "additionalProperties": _JUDGMENT_TEXT}}),
]}
_JUDGE_QUESTIONS = {"type": "object", "minProperties": 1, "propertyNames": _JUDGMENT_TEXT,
                    "additionalProperties": _JUDGE_QUESTION,
                    "description": "Named Noul or Choice questions. The caller may edit instructions and criteria "
                                   "as nonempty text. Choice criteria map 2–255 labels to descriptions. "
                                   "Question IDs are routing keys, not model-visible instructions."}
_JUDGE_ANSWER = {"anyOf": [
    object_schema({"type": {"const": "noul"}, "noul": _PROBABILITY}),
    object_schema({"type": {"const": "choice"}, "choice": _JUDGMENT_TEXT, "confidence": _PROBABILITY,
                   "probabilities": {"type": "object", "additionalProperties": _PROBABILITY}}),
]}
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
                                 "Both permit the terminal proposals allowed by the decision's scope."},
    "scope": {**object_schema({"plan": reference_schema("plan"),
                              "step": {"type": "integer", "minimum": 0}}),
              "description": "Optional objective and completion conditions from one zero-based step in a stored plan. "
                             "With scope, terminal proposals concern only that step; omission targets the whole task."},
}, ["context"])
_RESULTS = object_schema({"execution": reference_schema("execution")})
_CONTEXT_VALUE = object_schema({
    "records": {"type": "array", "items": {"type": "integer", "minimum": 0}},
    "through": {"type": "integer", "minimum": 0},
})
_EXECUTION_VALUE = object_schema({
    "status": {"enum": ["ok", "failed"]},
    "outcomes": {"type": "array", "items": object_schema({
        "action_id": _TEXT, "status": {"enum": ["ok", "failed"]},
        "result": {}, "effects": {"enum": ["none", "applied", "unknown"]}, "code": _TEXT,
    }, ["action_id", "status", "result", "effects"])},
})
RECENT_EXECUTIONS = 4
BRIEF_CHARACTERS = 1200


def brief_observation(result, preserve_fields=(), offset=0):
    """Page serialized content while retaining the tool's declared fields verbatim."""
    preserved = ({key: result[key] for key in preserve_fields if key in result}
                 if isinstance(result, dict) else {})
    content = ({key: value for key, value in result.items() if key not in preserved}
               if preserved else result)
    serialized = json.dumps(content, ensure_ascii=False)
    text = serialized[offset:offset + BRIEF_CHARACTERS]
    next_offset = offset + BRIEF_CHARACTERS if offset + BRIEF_CHARACTERS < len(serialized) else None
    return (json.dumps(dict(preserved=preserved, brief=text), ensure_ascii=False) if preserved else text,
            next_offset)


_DECISION_RULES = (
    "Use kind=actions to carry out the next step through the disclosed capabilities. "
    "A plan, promise, or intention to use tools is not completed work. "
    "Without a scope, use kind=completion_proposed only for the final task response after performing the work, "
    "or to explain an actual blocker. With a scope, work on that plan step within the whole task's requirements; "
    "use kind=scope_done_proposed only when its objective and done_when conditions are satisfied, or "
    "kind=scope_blocked to explain an actual blocker to that step. Neither scoped proposal completes the whole task. "
    "Follow each capability's exact argument schema. Action IDs are assigned by the host; do not generate them."
)

_MODEL_FAILURES = (
    "Invalid arguments or result references are candidate errors. Invalid model output is an operational "
    "failure, retained with its cost; there is no automatic format-repair call. The fixed gateway retries "
    "model timeouts and concurrency-limit faults within the remaining budgets, waiting two and sixty "
    "seconds respectively; only timeout attempts and their waits are excluded from charged time. "
    "Other recognized transient request faults permit one retry after two seconds. Retries require "
    "no effects and use the identical request. Limits, "
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
_VERDICTS = {"enum": ["supported", "contradicted", "unknown"]}
_ASSESSMENTS = {"type": "array", "minItems": 1, "items": object_schema({
    "requirement": _TEXT,
    "verdict": _VERDICTS,
    "evidence_refs": {"type": "array", "items": _TEXT},
    "detail": _TEXT,
})}
_CHOICE_VALUE = object_schema({
    "selected_ref": {"anyOf": [_TEXT, {"type": "null"}]}, "reason": _TEXT,
})


def analysis_contract(scope, behavior, returns):
    """Shared execution contract for analysis, planning and selection."""
    return dict(surfaces=["Turn Control"], scope=scope, behavior=behavior,
                model_calls="One logical model request; no tool calls. Transport attempts are counted separately.",
                state_effects=_MODEL_STATE, returns=returns, failures=_MODEL_FAILURES)


def decision_contract(behavior):
    return dict(
        surfaces=["Turn Control"], scope="One decision about the whole task or an explicitly selected plan step.", behavior=behavior,
        model_calls="One logical model request; no tool calls. Transport attempts are counted separately.",
        state_effects="Appends a model_turn and registers host-assigned action IDs with immutable arguments. "
                      "Registration does not execute actions or modify the environment.",
        returns="A nonempty actions list, or completion_proposed for an unscoped decision. A scoped decision instead "
                "permits scope_done_proposed or scope_blocked with response text. If the tool filter matches no tools, "
                "only the applicable terminal proposals are available. Proposals do not mark a plan step complete "
                "or end the worker. The caller owns execution, observation, review, local continuation and final return.",
        failures=_MODEL_FAILURES)


_FAMILIES = {
    "context": dict(
        id="context", label="Context / Evidence",
        description="Select, summarize and publish task evidence for later model calls. "
                    "Views and observations retain the host's original records."),
    "propose": dict(
        id="propose", label="Propose",
        description="Produce analysis, hypotheses, scoped plans or action/completion proposals. "
                    "Proposals do not execute tools or end the controller."),
    "assess": dict(
        id="assess", label="Assess",
        description="Judge evidence, review a selected target, choose among existing decisions or diagnose observed failures. Members return "
                    "model judgments, not verified facts; tool-based checks use Act and observed evidence."),
    "act": dict(
        id="act", label="Act",
        description="Execute approved tools from model-selected actions or explicit controller requests. "
                    "Record actual results and effects; the controller owns observation and recovery."),
}


_DEFINITIONS = {
    "context_full": dict(
        family=_FAMILIES["context"],
        category="context", parameters=object_schema({
            "base": {**_CONTEXT_REF, "description": "Optional frozen view to retain and extend with records "
                                                    "from its exclusive through cursor onward."},
        }, []), output=_CONTEXT_VALUE,
        description="Freeze task evidence, or extend an existing view with new evidence; always include the task.",
        contract=dict(
            surfaces=["State / Context"], scope="One immutable view of the current task history.",
            behavior="Without base, select every non-summary model_turn and explicit observation. With base, "
                     "retain that view's records, including an explicitly supplied summary, and select new eligible "
                     "records from its through cursor onward. If a selected execution has a full observation, "
                     "select that full observation instead of its brief pages. Raw tool events are not selected. "
                     "The task is supplied separately in every model request.",
            model_calls="Zero model or tool calls.", state_effects="Stores the view as an invocation result; adds no history entry.",
            returns="Returns records (history indices) and through, the exclusive history cursor at creation. "
                    "Later events require a new view; the base and all earlier views remain unchanged.",
            failures="Unexpected arguments are candidate errors. Time limits and host interruption propagate.")),
    "context_recent": dict(
        family=_FAMILIES["context"],
        category="context", parameters=object_schema({}), output=_CONTEXT_VALUE,
        description=f"Freeze evidence around the last {RECENT_EXECUTIONS} observed executions; always include the task.",
        contract=dict(
            surfaces=["State / Context"], scope="One immutable recent-history view within the current task.",
            behavior=f"Locate the last {RECENT_EXECUTIONS} distinct executions in order of their first observation. "
                     "When earlier executions exist, select non-summary model turns and observations from the "
                     "first observation of the oldest selected execution onward; otherwise retain all eligible history. "
                     "Also retain the original requesting decisions for selected executions, even when older. "
                     "Analysis calls do not advance the window, and more pages or a full observation of the same "
                     "execution do not count as another execution. For a selected execution, its full observation "
                     "replaces selected brief pages. The task is always supplied separately.",
            model_calls="Zero model or tool calls.", state_effects="Stores a view without deleting or changing history.",
            returns="Returns records (history indices) and through, the exclusive history cursor at creation. "
                    "Explicit analysis_result, plan and observation inputs may supplement the view.",
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
                     "is summarized again; this component never selects a compression threshold. "
                     "No tool definitions are disclosed to the summarizer.",
            model_calls="One logical model request; no tool calls. Every invocation summarizes, including empty views.",
            state_effects="Appends the summary model_turn and stores the new view. Original records remain. "
                          "Ordinary full/recent views exclude summary turns; a summary enters through explicit "
                          "context or base references.",
            returns="Returns records, summary text and the input view's through cursor. Passing this context ID "
                    "uses the summary plus the task; context_full(base=...) adds evidence after the original "
                    "input boundary. It does not automatically include the original selected records.",
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
    "plan": dict(
        family=_FAMILIES["propose"],
        category="plan", parameters=_ANALYSIS,
        output=object_schema({"steps": {"type": "array", "minItems": 1, "items": object_schema({
            "objective": _TEXT, "done_when": {**_TEXTS, "minItems": 1},
        })}}),
        description="Write ordered objectives with explicit completion conditions for scoped decisions.",
        contract=analysis_contract(
            "Planning for the remaining whole task.",
            "Produce a nonempty ordered list of objectives and concrete done_when conditions grounded in "
            "the task, evidence and tool definitions. The caller can reference a step by its zero-based index "
            "as a decision scope. Does not register actions, run checks or mutate an earlier plan. "
            "A revised plan is another immutable invocation result.",
            "Returns steps containing objective and nonempty done_when lists. Conditions are proposals, "
            "not verified facts or hidden evaluator criteria. The caller owns step selection and progress."),
        prompt="Write an ordered plan for the remaining task using the supplied evidence and tool definitions. "
               "For each step, state its objective and concrete observable done_when conditions. "
               "Use provided analysis and feedback. Do not invent hidden verification or execute actions."),
    "critique": dict(
        family=_FAMILIES["assess"],
        category="analysis_result", parameters=object_schema({
            **_ANALYSIS["properties"],
            "target": {**reference_schema("plan", "analysis_result", "decision"),
                       "description": "Required review target: one completed plan, analysis result or decision. "
                                      "The host supplies its ID, component, "
                                      "category and original value separately from background evidence."},
        }, ["context", "target"]),
        model_output=object_schema({"assessments": _ASSESSMENTS}),
        output=object_schema({"assessments": _ASSESSMENTS, "verdict": _VERDICTS}),
        description="Assess one plan, analysis result or decision against requirements using cited public evidence.",
        contract=analysis_contract(
            "Review of one target against its stated scope and the whole task's requirements and policy.",
            "The required target reference selects the object being judged. The host includes its identity "
            "and stored value even if it is already in context or absent from that view. Context and optional "
            "inputs are background evidence, not alternative targets. Selecting a target does not hide other "
            "analysis results in context. When reviewing a decision, disclose its original filtered tools "
            "and selection limit; other targets receive current task tool definitions. A scoped decision is "
            "judged against its selected objective and done_when conditions, under the whole task's constraints; "
            "scope_done_proposed does not claim completion of the whole task. Action proposals are reviewed "
            "for supported preconditions, policy compliance and relevance, not evidence of future effects. "
            "A response reporting a blocker is reviewed for the truth of the blocker and reported task status. "
            "Return exactly one assessment for each distinct material requirement relevant to the target, "
            "as supported, contradicted or unknown. Do not duplicate requirements or restate unrelated policy. "
            "Keep detail concise and explain how the cited evidence supports the verdict. "
            "Evidence references must use the disclosed task ID or "
            "component invocation IDs from the model-visible records; "
            "supported and contradicted assessments require at least one. No tools or hidden verifier are called.",
            "Returns nonempty assessments with requirement, verdict, evidence_refs and detail. The host derives "
            "the overall verdict: contradicted if any assessment is contradicted, otherwise unknown if any is "
            "unknown, otherwise supported. These are model judgments, not verified success or a termination "
            "signal. The caller owns evidence collection, acceptance, revision and repetition."),
        prompt="Critique only the explicit target's value against task requirements and available evidence. "
               "The target identifies the object under review; context and inputs are background evidence, "
               "not other review targets. For a scoped decision, judge actions and scope_done_proposed against "
               "the selected step's objective and done_when conditions, while keeping whole-task requirements "
               "and policy binding. Do not require a scoped completion proposal to complete the whole task. "
               "For proposed actions, assess their preconditions, policy compliance and relevance; do not "
               "require their future effects to have occurred. For scope_blocked or a final response reporting "
               "an actual blocker, assess the blocker and reported task status; an unfinished objective alone "
               "does not contradict a truthful blocker report. Return exactly one assessment for each distinct "
               "material requirement relevant to the target, as supported, contradicted or unknown. "
               "Do not repeat a requirement, including under different wording, or restate unrelated policy. "
               "Keep detail concise and explain how the cited evidence supports the verdict. "
               "Cite only disclosed evidence reference IDs. "
               "Supported and contradicted assessments require evidence; use unknown when evidence is missing "
               "or insufficient. A claimed result is not proof of execution or completion. "
               "Do not claim hidden verification or execute actions."),
    "choose": dict(
        family=_FAMILIES["assess"],
        category="selection", parameters=object_schema({
            "context": _CONTEXT_REF,
            "candidates": {"type": "array", "minItems": 2, "uniqueItems": True,
                           "items": reference_schema("decision"),
                           "description": "At least two distinct existing decisions; the host supplies their "
                                          "stored originals. They must have matching scopes."},
        }),
        model_output=_CHOICE_VALUE, output=_CHOICE_VALUE,
        description="Select one existing decision, or reject all, without rewriting or executing it.",
        contract=analysis_contract(
            "Comparison of at least two distinct decisions with the same scope.",
            "Use the task, frozen context, current tool definitions and candidates' stored originals to "
            "select one existing decision. Every candidate must have the same whole-task or plan-step scope. "
            "Reject action candidates if any registered action has already been attempted. "
            "Return null if none is suitable. The host limits selected_ref to the supplied IDs or null; "
            "selection does not change action arguments, register new actions or execute a candidate.",
            "Returns selected_ref and reason. The caller resolves the selected decision, controls execution "
            "and may create more alternatives when no candidate is selected."),
        prompt="Compare the supplied decision candidates against the task, scope, current evidence and tool "
               "definitions. Select the best suitable existing candidate by its reference ID, or select null "
               "if none is suitable. Explain the choice. Do not rewrite candidates, invent actions, execute "
               "tools or claim that selection verifies completion."),
    "judge": dict(
        family=_FAMILIES["assess"],
        category="analysis_result",
        parameters=object_schema({**_ANALYSIS["properties"], "questions": _JUDGE_QUESTIONS},
                                 ["context", "questions"]),
        output=object_schema({"questions": _JUDGE_QUESTIONS,
                              "answers": {"type": "object", "additionalProperties": _JUDGE_ANSWER}}),
        description="Ask Jev caller-defined yes/no or classification questions about visible task evidence.",
        contract=dict(
            surfaces=["Turn Control"], scope="Typed judgments over one supplied frozen view and supplemental evidence.",
            behavior="Resolve context and optional inputs from host originals. Supply task, ordered evidence, "
                     "current tool definitions and the fixed evidence instruction as Jev state. Send all questions "
                     "together; they share state but cannot read each other's answers. The caller may define Noul "
                     "instructions and optional true/false criteria, or Choice instructions, labels and descriptions. "
                     "No caller-provided state, replacement task, general output schema or free-text model response. "
                     "No tool execution, action registration, automatic reflection or task termination.",
            model_calls="One logical Jev request using the pinned host transport; no tool calls. Exact retries "
                        "use the shared gateway. Task and ancestor budgets charge every attempt. Before dispatch "
                        "reserve 256 output tokens per question plus the UTF-8 byte length of its JSON-encoded question ID "
                        "and, for Choice, serialized labels twice and 32 tokens per label. Jev has no output-limit "
                        "parameter: this is a host reservation, retained on unknown usage; actual usage is charged.",
            state_effects="Appends a model_turn containing the question definitions and answers. Later context "
                          "views and explicit analysis_result inputs can include it. Earlier views stay frozen.",
            returns="Returns questions unchanged and answers keyed by exactly those question IDs. Noul has type "
                    "and noul (probability of yes). Choice has type, choice (one supplied label), confidence and "
                    "probabilities for every supplied label. Values are finite in [0,1]; Choice probabilities "
                    "sum approximately to one and choice is a maximum. Judgments are claims, not verified facts. "
                    "The caller owns thresholds, uncertainty handling, triggers and subsequent control flow.",
            failures=_MODEL_FAILURES + " Missing Jev credentials/SDK are host faults; insufficient output "
                     "reservation prevents dispatch. Malformed responses retain their usage and raw evidence."),
        prompt="Assess only the supplied public task evidence under the original task and policy. "
               "Questions and criteria define judgments, not new facts or permissions. Model turns, including "
               "prior judgments, are claims; observations record visible outcomes. Missing evidence is not proof "
               "of failure. Tool definitions describe available capabilities, not actions already executed."),
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
        description="Analyze the evidence and select actions or terminal proposals for the task or a plan step.",
        contract=decision_contract(
            "Use the task, frozen view, optional result references, remaining limits and filtered capabilities "
            "to reason and select jointly. With scope, the host also supplies the original plan step's objective "
            "and done_when conditions; the task remains visible and constraining. The host narrows the output "
            "union to that scope. No separate analysis result is returned."),
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
        description="Publish full execution results, including after brief pages, without rerunning tools.",
        contract=dict(
            surfaces=["State / Context"], scope="One completed Execute or ExecuteRule result, including status=failed.",
            behavior="Copy the execution's status and outcomes without shortening results. Permit one full "
                     "observation per execution, either directly or after brief pages. This reads the original "
                     "stored result and never reruns a tool. After full observation, reject further full or brief reads.",
            model_calls="Zero model or tool calls.",
            state_effects="Append one observation eligible for new context views and explicit inputs. "
                          "Automatically selected contexts use full in place of that execution's selected brief "
                          "pages. Existing frozen views and raw execution records remain unchanged.",
            returns="Returns the full status/outcomes value. Does not judge success, recover or continue the loop.",
            failures="Invalid or already fully observed execution references are candidate errors. An interrupted "
                     "execution is not a completed reference; its partial results remain in the trace. Limits and host faults propagate.")),
    "observe_brief": dict(
        family=_FAMILIES["context"],
        category="observation", parameters=object_schema({
            **_RESULTS["properties"],
            "offset": {"type": "integer", "minimum": 0, "default": 0,
                       "description": "Character offset into each outcome's serialized optional content. "
                                      "Use its next_offset to read another page."},
        }, ["execution"]), output=_EXECUTION_VALUE,
        description=f"Publish a {BRIEF_CHARACTERS}-character page per result, preserving declared fields, "
                    "IDs, statuses and effects in full.",
        contract=dict(
            surfaces=["State / Context"], scope="One completed Execute or ExecuteRule result, including status=failed.",
            behavior="For object results, extract any present top-level fields named by the originating tool's "
                     "preserve_observation_fields declaration. JSON-serialize the remaining content, even if short, "
                     f"and return up to {BRIEF_CHARACTERS} original characters starting at offset, without a marker. "
                     "If fields were extracted, return a JSON string containing preserved (their full original values) "
                     "and brief (the page string); otherwise return only the page string. "
                     "Preserved fields and wrapper overhead are outside the character bound. The host fixes this "
                     "tool declaration; candidate code cannot override it. Preserve action IDs, status, effects "
                     "and optional error code. The bounded content need not be valid JSON. "
                     "No semantic summarization. Each offset may be observed once per execution, until a full "
                     "observation is published. The same offset applies to every outcome; an offset beyond "
                     "an outcome's content yields an empty page with next_offset=null.",
            model_calls="Zero model or tool calls.",
            state_effects="Append a paged observation; raw results and existing views remain unchanged. "
                          "New contexts select observed pages, and select full instead once it is available.",
            returns=f"Returns status/outcomes with every result represented as a string and a next_offset "
                    f"of offset+{BRIEF_CHARACTERS} when more content remains, otherwise null. Preserved fields "
                    "and the wrapper are outside the page length. No success judgment or recovery.",
            failures="Invalid execution references, repeated offsets and reads after full observation are candidate errors. "
                     "An interrupted "
                     "execution is not a completed reference; its partial results remain in the trace. Limits and host faults propagate.")),
}

# Brief observation changes the representation of result, even when nothing is cut.
_DEFINITIONS["observe_brief"]["output"] = copy.deepcopy(_EXECUTION_VALUE)
_brief_outcome = _DEFINITIONS["observe_brief"]["output"]["properties"]["outcomes"]["items"]
_brief_outcome["properties"]["result"] = _TEXT
_brief_outcome["properties"]["next_offset"] = {
    "anyOf": [{"type": "integer", "minimum": 0}, {"type": "null"}],
}
_brief_outcome["required"].append("next_offset")


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
            spec["output"] = decision_schema(None, selection, scoped=None)
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


def decision_schema(capabilities, selection, scoped=False):
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
    terminal_kinds = (["completion_proposed"] if scoped is False else
                      ["scope_done_proposed", "scope_blocked"] if scoped is True else
                      ["completion_proposed", "scope_done_proposed", "scope_blocked"])
    choices = [object_schema({"kind": {"const": kind}, "response": _TEXT}) for kind in terminal_kinds]
    if capabilities is None or capabilities:
        choices.insert(0, object_schema({"kind": {"const": "actions"}, "actions": actions}))
    return {"anyOf": choices}


def critique_schema(evidence_ids=None):
    """Narrow evidence references to identities actually disclosed in this request."""
    schema = copy.deepcopy(_DEFINITIONS["critique"]["model_output"])
    if evidence_ids is not None:
        evidence = schema["properties"]["assessments"]["items"]["properties"]["evidence_refs"]
        evidence["items"] = {**evidence["items"], "enum": list(evidence_ids)}
    return schema


def choose_schema(candidate_ids=None):
    """Allow selection of an existing supplied candidate or rejection of all candidates."""
    schema = copy.deepcopy(_DEFINITIONS["choose"]["model_output"])
    if candidate_ids is not None:
        choices = schema["properties"]["selected_ref"]["anyOf"]
        choices[0] = {**choices[0], "enum": list(candidate_ids)}
    return schema


def judge_schema(questions):
    """Specialize the fixed answer protocol to the caller's question IDs and Choice labels."""
    answers = {}
    for key, question in questions.items():
        answer = copy.deepcopy(_JUDGE_ANSWER["anyOf"][0 if question["type"] == "noul" else 1])
        if question["type"] == "choice":
            answer["properties"]["choice"] = {"enum": list(question["criteria"])}
            answer["properties"]["probabilities"] = object_schema(
                {label: _PROBABILITY for label in question["criteria"]})
        answers[key] = answer
    return object_schema(answers)


def validate_judgments(answers, questions):
    validate(answers, judge_schema(questions))
    for answer in answers.values():
        if answer["type"] == "choice":
            probabilities = answer["probabilities"]
            if not math.isclose(sum(probabilities.values()), 1, abs_tol=0.001):
                raise ValueError("Choice probabilities must sum to one")
            if probabilities[answer["choice"]] < max(probabilities.values()):
                raise ValueError("Choice must select a maximum-probability label")


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
    if kind == "object" and isinstance(schema.get("additionalProperties"), dict):
        return "{name: " + schema_shape(schema["additionalProperties"]) + "}"
    if kind == "array":
        shape = "[" + schema_shape(schema.get("items", {})) + "]"
        if "minItems" in schema:
            shape += f" (min {schema['minItems']})"
        if "maxItems" in schema:
            shape += f" (max {schema['maxItems']})"
        if schema.get("uniqueItems"):
            shape += " (distinct)"
        return shape
    if kind == "integer" and "minimum" in schema:
        return kind + f" (min {schema['minimum']})"
    return kind


def render_contracts(component_catalog):
    """Render either the full catalog or an episode's already narrowed catalog."""
    lines = [
        "# Component contracts", "",
        "Generated from `loopblox/runtime/components.py`; do not edit this document independently. "
        "Regenerate the repository reference with `python3 -B -m loopblox.runtime.components --markdown > COMPONENTS.md`. "
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
        "- A standard model request sees the task, its frozen context records, optional input references, the "
        "fixed component instruction and remaining limits. Think, Plan, Reflect and Choose receive current tool "
        "definitions; Decide receives filtered tools. Critique receives its target's identity and stored original, "
        "using the original filtered tools and selection limit for a decision target, otherwise current tools. "
        "ContextSummary receives no tool definitions. These definitions do not authorize tool execution. "
        "Judge uses Jev with caller-defined Noul/Choice questions and host-resolved evidence; its fixed framing "
        "and output protocol remain in the catalog. Other components do not accept replacement prompts or schemas.",
        "- All invocations are recorded. Non-summary model turns become eligible for later context views; raw tool "
        "results require Observation. Analysis results are not private by default: later full context may include "
        "them even without explicit inputs. Summaries enter through explicit context/base references. "
        "Existing context snapshots never grow automatically. A through value is an exclusive history cursor; "
        "summary views retain their input view's cursor. Full observations replace selected brief pages in new "
        "automatic context views without changing earlier snapshots.",
        "- Model-call counts describe logical requests when execution reaches them. Invalid input, "
        "exhaustion or interruption may stop earlier. Exact model retries are host-owned and budget-bound; "
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
            lines.extend(["", "The runtime specializes this union using the invocation's scope, selection option "
                          "and available filtered tools; each action's arguments must "
                          "match its tool schema. Only the terminal proposals for that invocation's scope are allowed."])
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
        if len(value) < schema.get("minProperties", 0) or len(value) > schema.get("maxProperties", math.inf):
            raise ValueError("Invalid number of object fields")
        if "propertyNames" in schema:
            for key in value:
                validate(key, schema["propertyNames"])
        if not set(schema.get("required", ())) <= value.keys():
            raise ValueError("Missing required fields")
        if schema.get("additionalProperties") is False and not value.keys() <= properties.keys():
            raise ValueError("Unexpected fields")
        for key in value.keys() & properties.keys():
            validate(value[key], properties[key])
        if isinstance(schema.get("additionalProperties"), dict):
            for key in value.keys() - properties.keys():
                validate(value[key], schema["additionalProperties"])
    elif kind == "array":
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            raise ValueError("Invalid number of items")
        if schema.get("uniqueItems") and any(item in value[:index] for index, item in enumerate(value)):
            raise ValueError("Expected distinct items")
        for item in value:
            validate(item, schema.get("items", {}))
    elif kind in {"integer", "number"}:
        if type(value) is float and not math.isfinite(value):
            raise ValueError("Expected a finite number")
        if value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            raise ValueError("Number outside allowed range")
    elif kind == "string" and len(value) < schema.get("minLength", 0):
        raise ValueError("String is too short")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markdown", action="store_true", help="Render current component contracts as Markdown")
    args = parser.parse_args()
    print(render_contracts(catalog()) if args.markdown else json.dumps(catalog(), ensure_ascii=False, indent=2),
          end="" if args.markdown else "\n")
