"""Seeded first-generation Python Loops; sampling policy, not a runtime language."""

import random

from loopblox.runtime.components import catalog, validate


def generate_candidates(exposed, count, seed):
    """Sample unique source files without task data or model calls."""
    definitions = catalog(exposed)
    rng = random.Random(seed)
    contexts = [name for name in ("context_full", "context_recent") if name in definitions]
    if "context_full" in definitions and "context_summary" in definitions:
        contexts.append("context_summary")
    decisions = [name for name in ("decide", "think_decide") if name in definitions]
    observations = [name for name in ("observe_full", "observe_brief") if name in definitions]
    analyses = [name for name in ("think", "decompose", "plan") if name in definitions]
    if not contexts or not decisions or not observations or "execute" not in definitions:
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

    def call(name, **arguments):
        # Reference values here are source expressions, not fabricated host results.
        validate({key: value if not isinstance(value, tuple) else "reference"
                  for key, value in arguments.items()}, definitions[name]["parameters"])
        parts = [repr(name)]
        parts.extend(f"{key}={value[0] if isinstance(value, tuple) else repr(value)}"
                     for key, value in arguments.items())
        return "env.component(" + ", ".join(parts) + ")"

    candidates, seen = [], set()
    for attempt in range(max(1000, count * 100)):
        context = rng.choice(contexts)
        decision = rng.choice(decisions)
        selection = rng.choice(definitions[decision]["parameters"]["properties"]["selection"]["enum"])
        observation = rng.choice(observations)
        chosen = set(rng.sample(mechanisms, rng.randrange(min(2, len(mechanisms)) + 1)))
        opening = rng.sample(analyses, rng.randint(1, min(2, len(analyses)))) if "opening_analysis" in chosen else []
        turn = rng.sample(analyses, rng.randint(1, min(2, len(analyses)))) if "turn_analysis" in chosen else []
        recovery = rng.choice(("failure", "failure_or_repeat")) if "recovery" in chosen else None
        sampled = dict(context=context, decision=decision, selection=selection, observation=observation,
                       opening_analysis=opening, turn_analysis=turn, recovery=recovery,
                       action_review="action_review" in chosen, completion_review="completion_review" in chosen)
        lines = ["def run(env):", "    def view():"]
        if context == "context_summary":
            lines += ["        original = " + call("context_full", drop="none"),
                      "        return " + call("context_summary", context=("original['id']",))]
        else:
            lines.append("        return " + call(context, drop="none"))
        lines += ["", "    opening = []"]
        for name in opening:
            lines += ["    context = view()", "    analysis = " + call(name, context=("context['id']",)),
                      "    opening.append(analysis['id'])"]
        lines += ["    guidance = list(opening)"]
        if recovery == "failure_or_repeat":
            lines.append("    previous = None")
        lines += ["    while True:"]
        for name in turn:
            lines += ["        context = view()", "        analysis = " + call(name, context=("context['id']",)),
                      "        guidance.append(analysis['id'])"]
        lines += ["        context = view()",
                  "        decision = " + call(decision, context=("context['id']",), selection=selection, tool_filter="all")[:-1]
                  + ", inputs=guidance)",
                  "        if decision['value']['kind'] == 'completion_proposed':"]
        if "completion_review" in chosen:
            lines += ["            context = view()",
                      "            review = " + call("critique", context=("context['id']",), target=("decision['id']",)),
                      "            if not review['value']['accept']:",
                      "                guidance = opening + [review['id']]", "                continue"]
        lines += ["            return decision['value']['response']"]
        if "action_review" in chosen:
            lines += ["        context = view()",
                      "        review = " + call("critique", context=("context['id']",), target=("decision['id']",)),
                      "        if not review['value']['accept']:",
                      "            guidance = opening + [review['id']]", "            continue"]
        lines += ["        execution = " + call("execute", decision=("decision['id']",), take="remaining"),
                  "        observation = " + call(observation, execution=("execution['id']",)),
                  "        guidance = list(opening)"]
        if recovery:
            condition = "execution['value']['status'] == 'failed'"
            if recovery == "failure_or_repeat":
                lines += ["        signature = (",
                          "            [(a['capability_id'], a['arguments']) for a in decision['value']['actions']],",
                          "            [(o['status'], o['result']) for o in observation['value']['outcomes']],", "        )"]
                condition += " or signature == previous"
            lines += [f"        if {condition}:", "            context = view()",
                      "            reflection = " + call("reflect", context=("context['id']",))[:-1]
                      + ", inputs=[observation['id']])", "            guidance.append(reflection['id'])"]
            if recovery == "failure_or_repeat":
                lines.append("        previous = signature")
        source = "\n".join(lines) + "\n"
        compile(source, "random-loop.py", "exec")
        if source in seen:
            continue
        seen.add(source)
        candidates.append(dict(source=source, sampling=sampled, attempt=attempt,
            rationale="Untested random composition, sampled without task results. "
                      "No improvement is assumed. Evaluate complete-task success and total cost "
                      "on the same development draws as the other frozen candidates and baseline."))
        if len(candidates) == count:
            return candidates
    raise ValueError("Could not produce the requested number of distinct candidates in the bounded sampling budget")
