def run(env):
    guidance = []
    while True:
        context = env.component("context_full")
        decision = env.component("think_decide", context=context["id"], inputs=guidance)
        if decision["value"]["kind"] == "completion_proposed":
            return decision["value"]["response"]
        execution = env.component("execute", decision=decision["id"])
        env.component("observe_full", execution=execution["id"])
        guidance = []
        if execution["value"]["status"] == "failed":
            context = env.component("context_full")
            reflection = env.component("reflect", context=context["id"])
            guidance = [reflection["id"]]
