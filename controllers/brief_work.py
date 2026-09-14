def run(env):
    while True:
        context = env.component("context_full")
        decision = env.component("think_decide", context=context["id"])
        if decision["value"]["kind"] == "completion_proposed":
            return decision["value"]["response"]
        execution = env.component("execute", decision=decision["id"])
        env.component("observe_brief", execution=execution["id"])
