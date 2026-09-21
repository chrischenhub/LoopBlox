def run(env):
    initial_observation = env.task.get("initial_observation")
    if isinstance(initial_observation, dict) and initial_observation.get("conversation_done") is True:
        return "Conversation ended."
    guidance = []
    while True:
        context = env.component("context_full")
        decision = env.component("decide", context=context["id"], inputs=guidance)
        guidance = []
        if decision["value"]["kind"] == "completion_proposed":
            review = env.component("critique", context=context["id"], target=decision["id"])
            if review["value"]["verdict"] == "supported":
                return decision["value"]["response"]
            guidance = [review["id"]]
            continue
        execution = env.component("execute", decision=decision["id"])
        observation = env.component("observe_full", execution=execution["id"])
        if any(isinstance(outcome["result"], dict)
               and outcome["result"].get("conversation_done") is True
               for outcome in observation["value"]["outcomes"]):
            return "Conversation ended."
