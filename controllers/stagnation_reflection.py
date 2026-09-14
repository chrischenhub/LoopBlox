def run(env):
    guidance = []
    previous = None
    while True:
        context = env.component("context_full")
        decision = env.component("think_decide", context=context["id"], inputs=guidance)
        if decision["value"]["kind"] == "completion_proposed":
            return decision["value"]["response"]
        execution = env.component("execute", decision=decision["id"])
        observation = env.component("observe_full", execution=execution["id"])
        signature = (
            [(action["capability_id"], action["arguments"]) for action in decision["value"]["actions"]],
            [(outcome["status"], outcome["result"]) for outcome in observation["value"]["outcomes"]],
        )
        guidance = []
        if execution["value"]["status"] == "failed" or signature == previous:
            context = env.component("context_full")
            reflection = env.component("reflect", context=context["id"])
            guidance = [reflection["id"]]
        previous = signature
