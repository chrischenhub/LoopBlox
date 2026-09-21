"""Seeded first-generation Python Loops; sampling policy, not a runtime language."""

import collections
import random

from loopblox.runtime.components import catalog, validate

MECHANISM_CAP = 4


def generate_candidates(exposed, count, seed):
    """Sample unique source files without task data or model calls."""
    definitions = catalog(exposed)
    rng = random.Random(seed)
    contexts = [name for name in ("context_full", "context_recent") if name in definitions]
    if "context_full" in definitions and "context_summary" in definitions:
        contexts.append("context_summary")
    observations = [name for name in ("observe_full", "observe_brief") if name in definitions]
    analyses = [name for name in ("think", "plan") if name in definitions]
    if not contexts or "decide" not in definitions or not observations or "execute" not in definitions:
        raise ValueError("The sampler needs context, decision, execution and observation components")
    if count < 1:
        raise ValueError("Candidate count must be positive")
    mechanisms = []
    if analyses:
        mechanisms.extend(("opening_analysis", "turn_analysis"))
    if "reflect" in definitions:
        mechanisms.append("recovery")
    if "critique" in definitions:
        mechanisms.extend(("action_review", "completion_review"))
    if "execute_rule" in definitions:
        mechanisms.extend(("rule_opening", "rule_verify"))
    if "plan" in definitions and "scope" in definitions["decide"]["parameters"]["properties"]:
        mechanisms.append("scoped_plan")
    if "choose" in definitions:
        mechanisms.append("choice")
    if len(observations) == 2:
        mechanisms.append("brief_readback")

    def call(name, **arguments):
        # Tuples pair source expressions with optional schema-shaped validation values.
        validate({key: (value[1] if len(value) > 1 else "reference") if isinstance(value, tuple) else value
                  for key, value in arguments.items()}, definitions[name]["parameters"])
        parts = [repr(name)]
        parts.extend(f"{key}={value[0] if isinstance(value, tuple) else repr(value)}"
                     for key, value in arguments.items())
        return "env.component(" + ", ".join(parts) + ")"

    used = collections.Counter()

    def balanced(options, k=1):
        """Draw the least-used options first, so no exposed choice stays unsampled."""
        return sorted(options, key=lambda name: (used[name], rng.random()))[:k]

    candidates, seen = [], set()
    for attempt in range(max(1000, count * 100)):
        context, = balanced(contexts)
        selection = rng.choice(definitions["decide"]["parameters"]["properties"]["selection"]["enum"])
        observation, = balanced(observations)
        available = [name for name in mechanisms if name != "brief_readback" or observation == "observe_brief"]
        chosen = set(balanced(available, rng.randint(0, min(MECHANISM_CAP, len(available)))))
        opening = balanced(analyses, rng.randint(1, len(analyses))) if "opening_analysis" in chosen else []
        turn = balanced(analyses, rng.randint(1, len(analyses))) if "turn_analysis" in chosen else []
        recovery = rng.choice(("failure", "failure_or_repeat")) if "recovery" in chosen else None
        sampled = dict(context=context, decision="decide", selection=selection, observation=observation,
                       opening_analysis=opening, turn_analysis=turn, recovery=recovery,
                       **{name: name in chosen for name in ("action_review", "completion_review", "rule_opening",
                                                           "rule_verify", "scoped_plan", "choice", "brief_readback")})
        lines = ["def run(env):"]
        if context == "context_summary":
            lines += ["    summary = None", "    summary_turns = 0", "    observed = 0", "    def view():",
                      "        nonlocal summary, summary_turns",
                      "        current = env.component('context_full', base=summary['id']) if summary else env.component('context_full')",
                      "        if summary is None or observed - summary_turns >= 4:",
                      "            summary = " + call("context_summary", context=("current['id']",)),
                      "            summary_turns = observed", "            return summary", "        return current"]
        else:
            lines += ["    def view():", "        return " + call(context)]
        # Observation is one policy shared by model actions and controller-origin rules.
        lines += ["", "    def observe(execution):"]
        if context == "context_summary":
            lines += ["        nonlocal observed", "        observed += 1"]
        lines += ["        result = " + call(observation, execution=("execution['id']",))]
        if "brief_readback" in chosen:
            lines += ["        if any(item['next_offset'] is not None for item in result['value']['outcomes']):",
                      "            result = " + call("observe_full", execution=("execution['id']",))]
        lines += ["        return result", "", "    opening = []"]
        if "rule_opening" in chosen:
            lines += ["    for tool in env.tools:",
                      "        if tool['kind'] != 'inspect' or (tool['parameters'].get('required') or []):",
                      "            continue",
                      "        sweep = env.component('execute_rule', capability_id=tool['capability_id'], arguments={})",
                      "        observe(sweep)"]
        for name in opening:
            lines += ["    context = view()", "    analysis = " + call(name, context=("context['id']",)),
                      "    opening.append(analysis['id'])"]
        lines += ["    guidance = list(opening)"]
        if "scoped_plan" in chosen:
            lines.append("    active_plan = None")
        if recovery == "failure_or_repeat":
            lines.append("    previous = None")
        lines += ["    while True:"]
        for name in turn:
            lines += ["        context = view()", "        analysis = " + call(name, context=("context['id']",)),
                      "        guidance.append(analysis['id'])"]
        if "scoped_plan" in chosen:
            lines += ["        if active_plan is None:", "            context = view()",
                      "            active_plan = " + call("plan", context=("context['id']",)),
                      "            step = 0",
                      "        scope = ({'scope': {'plan': active_plan['id'], 'step': step}}",
                      "                 if step < len(active_plan['value']['steps']) else {})"]
        lines.append("        context = view()")
        decision_call = call("decide", context=("context['id']",), selection=selection,
                             tool_filter="all", inputs=("guidance", []))
        if "scoped_plan" in chosen:
            decision_call = decision_call[:-1] + ", **scope)"
        if "choice" in chosen:
            lines += ["        proposals = [" + decision_call + " for _ in range(2)]",
                      "        choice = " + call("choose", context=("context['id']",),
                                                    candidates=("[item['id'] for item in proposals]", ["first", "second"])),
                      "        selected = choice['value']['selected_ref']",
                      "        if selected is None:", "            continue",
                      "        decision = next(item for item in proposals if item['id'] == selected)"]
        else:
            lines.append("        decision = " + decision_call)
        if "scoped_plan" in chosen:
            lines += ["        if decision['value']['kind'] == 'scope_blocked':",
                      "            active_plan = None", "            guidance = list(opening)",
                      "            context = view()",
                      "            decision = " + call("decide", context=("context['id']",), selection=selection,
                                                        tool_filter="all", inputs=("guidance", []))]
        lines.append("        if decision['value']['kind'] != 'actions':")
        if "completion_review" in chosen:
            lines += ["            context = view()",
                      "            review = " + call("critique", context=("context['id']",), target=("decision['id']",)),
                      "            if review['value']['verdict'] != 'supported':",
                      "                guidance = opening + [review['id']]", "                continue"]
        if "scoped_plan" in chosen:
            lines += ["            if decision['value']['kind'] == 'scope_done_proposed':",
                      "                step += 1", "                guidance = list(opening)", "                continue"]
        lines += ["            return decision['value']['response']"]
        if "action_review" in chosen:
            lines += ["        context = view()",
                      "        review = " + call("critique", context=("context['id']",), target=("decision['id']",)),
                      "        if review['value']['verdict'] != 'supported':",
                      "            guidance = opening + [review['id']]", "            continue"]
        lines += ["        execution = " + call("execute", decision=("decision['id']",), take="remaining"),
                  "        observation = observe(execution)"]
        if "rule_verify" in chosen:
            lines += ["        results = {item['action_id']: item for item in observation['value']['outcomes']}",
                      "        for action in decision['value']['actions']:",
                      "            outcome = results.get(action['action_id'])",
                      "            if not outcome or outcome['status'] != 'ok' or outcome['effects'] != 'applied':",
                      "                continue",
                      "            for tool in env.tools:",
                      "                required = tool['parameters'].get('required') or []",
                      "                if tool['kind'] != 'inspect' or not required:",
                      "                    continue",
                      "                if all(key in action['arguments'] for key in required):",
                      "                    readback = env.component('execute_rule', "
                      "capability_id=tool['capability_id'],",
                      "                                             arguments={key: action['arguments'][key] "
                      "for key in required})",
                      "                    observe(readback)", "                    break"]
        lines += ["        guidance = list(opening)"]
        if recovery:
            condition = "execution['value']['status'] == 'failed'"
            if recovery == "failure_or_repeat":
                lines += ["        signature = (",
                          "            [(a['capability_id'], a['arguments']) for a in decision['value']['actions']],",
                          "            [(o['status'], o['result']) for o in observation['value']['outcomes']],", "        )"]
                condition += " or signature == previous"
            lines += [f"        if {condition}:", "            context = view()",
                      "            reflection = " + call("reflect", context=("context['id']",), inputs=("[observation['id']]", ["reference"])),
                      "            guidance.append(reflection['id'])"]
            if recovery == "failure_or_repeat":
                lines.append("        previous = signature")
        source = "\n".join(lines) + "\n"
        compile(source, "random-loop.py", "exec")
        if source in seen:
            continue
        seen.add(source)
        used.update([context, "decide", observation, *chosen, *opening, *turn])
        candidates.append(dict(source=source, sampling=sampled, attempt=attempt,
            rationale="Untested random composition, sampled without task results. "
                      "No improvement is assumed. Evaluate complete-task success and total cost "
                      "on the same development draws as the other frozen candidates and baseline."))
        if len(candidates) == count:
            return candidates
    raise ValueError("Could not produce the requested number of distinct candidates in the bounded sampling budget")
