def run(env):
    context = env.component("context_full")
    plan = env.component("plan", context=context["id"])
    guidance = [plan["id"]]
    while True:
        context = env.component("context_full")
        decision = env.component("decide", context=context["id"], inputs=guidance)
        if decision["value"]["kind"] == "completion_proposed":
            context = env.component("context_full")
            review = env.component("critique", context=context["id"], target=decision["id"])
            if review["value"]["verdict"] == "supported":
                return decision["value"]["response"]
            guidance = [plan["id"], review["id"]]
            continue
        execution = env.component("execute", decision=decision["id"])
        env.component("observe_full", execution=execution["id"])
