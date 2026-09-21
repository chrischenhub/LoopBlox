def run(env):
    context = env.component("context_full")
    plan = env.component("plan", context=context["id"])
    while True:
        context = env.component("context_full")
        decision = env.component("decide", context=context["id"], inputs=[plan["id"]])
        if decision["value"]["kind"] == "completion_proposed":
            return decision["value"]["response"]
        execution = env.component("execute", decision=decision["id"])
        env.component("observe_full", execution=execution["id"])
