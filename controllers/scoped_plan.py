"""Work through a plan, replan blocked steps, then assess whole-task completion."""


def run(env):
    plan = None
    guidance = []
    while True:
        context = env.component("context_full")
        if plan is None:
            plan = env.component("plan", context=context["id"])
            step = 0
            context = env.component("context_full")
        scope = ({"scope": {"plan": plan["id"], "step": step}}
                 if step < len(plan["value"]["steps"]) else {})
        decision = env.component("decide", context=context["id"],
                                 inputs=[plan["id"], *guidance], **scope)
        guidance = []
        kind = decision["value"]["kind"]
        if kind == "scope_blocked":
            plan = None
            context = env.component("context_full")
            decision = env.component("decide", context=context["id"])
            kind = decision["value"]["kind"]
        if kind in {"scope_done_proposed", "completion_proposed"}:
            context = env.component("context_full")
            review = env.component("critique", context=context["id"], target=decision["id"])
            if review["value"]["verdict"] != "supported":
                guidance = [review["id"]]
                continue
            if kind == "completion_proposed":
                return decision["value"]["response"]
            step += 1
            continue
        execution = env.component("execute", decision=decision["id"])
        env.component("observe_full", execution=execution["id"])
