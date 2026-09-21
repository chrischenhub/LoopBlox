"""Compare two proposals from the same evidence and execute only the selected one."""


def run(env):
    while True:
        context = env.component("context_full")
        proposals = [env.component("decide", context=context["id"]) for _ in range(2)]
        choice = env.component("choose", context=context["id"],
                               candidates=[proposal["id"] for proposal in proposals])
        selected = choice["value"]["selected_ref"]
        if selected is None:
            continue
        decision = next(proposal for proposal in proposals if proposal["id"] == selected)
        if decision["value"]["kind"] == "completion_proposed":
            return decision["value"]["response"]
        execution = env.component("execute", decision=selected)
        observation = env.component("observe_brief", execution=execution["id"])
        if any(outcome["next_offset"] is not None for outcome in observation["value"]["outcomes"]):
            env.component("observe_full", execution=execution["id"])
