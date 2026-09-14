def run(env):
    while True:
        context = env.component("context_full")
        plan = env.component("plan", context=context["id"])
        while True:
            review = env.component("critique", context=context["id"], target=plan["id"])
            if review["value"]["accept"]:
                break
            plan = env.component("plan", context=context["id"], inputs=[plan["id"], review["id"]])
        decision = env.component("decide", context=context["id"], inputs=[plan["id"], review["id"]],
                                 selection="sequence")
        if decision["value"]["kind"] == "completion_proposed":
            return decision["value"]["response"]
        execution = env.component("execute", decision=decision["id"])
        env.component("observe_full", execution=execution["id"])
