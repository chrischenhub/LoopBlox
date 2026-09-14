"""Fixed researcher Loop: a successful submission is followed by outer return."""


def run(env):
    missing_paths = set()
    previous_duplicate = None
    duplicate_saves = 0
    guidance = []
    while True:
        context = env.component("context_full")
        decision = env.component("think_decide", context=context["id"], selection="sequence", inputs=guidance)
        guidance = []
        if decision["value"]["kind"] == "completion_proposed":
            return decision["value"]["response"]
        # Execute singly so no later action in a submitted batch runs after finish.
        for action in decision["value"]["actions"]:
            execution = env.component("execute", decision=decision["id"], take="one")
            observation = env.component("observe_full", execution=execution["id"])
            outcome = observation["value"]["outcomes"][0]
            if (action["capability_id"] == "finish" and outcome["action_id"] == action["action_id"]
                    and outcome["status"] == "ok"):
                return outcome["result"]
            result = outcome["result"]
            if (action["capability_id"] == "read_artifact" and outcome["status"] == "failed"
                    and isinstance(result, dict) and result.get("code") == "artifact_not_found"):
                path = result["path"]
                if path in missing_paths:
                    raise RuntimeError("Research stopped after repeating a missing-artifact read: " + path)
                missing_paths.add(path)
            if (action["capability_id"] == "save_candidate" and outcome["status"] == "ok"
                    and isinstance(result, dict) and result.get("created") is False):
                candidate = result["candidate_id"]
                duplicate_saves = duplicate_saves + 1 if candidate == previous_duplicate else 1
                previous_duplicate = candidate
                if duplicate_saves >= 3:
                    raise RuntimeError("Research stopped after consecutive duplicate saves persisted after reflection: "
                                       + candidate)
                if duplicate_saves == 2:
                    # Reconsider before executing any later actions from this stale decision.
                    context = env.component("context_full")
                    reflection = env.component("reflect", context=context["id"])
                    guidance = [reflection["id"]]
                    break
            else:
                previous_duplicate = None
                duplicate_saves = 0
            if execution["value"]["status"] == "failed":
                break
