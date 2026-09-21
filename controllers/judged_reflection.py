"""Example: Jev classification triggers reflection on apparent semantic repetition."""


def run(env):
    guidance = []
    cooling_down = False
    while True:
        context = env.component("context_full")
        decision = env.component("decide", context=context["id"], inputs=guidance)
        guidance = []
        if decision["value"]["kind"] == "completion_proposed":
            return decision["value"]["response"]
        execution = env.component("execute", decision=decision["id"])
        observation = env.component("observe_full", execution=execution["id"])
        if cooling_down:
            cooling_down = False
            continue
        recent = env.component("context_recent")
        judgment = env.component("judge", context=recent["id"], questions={
            "situation": {
                "type": "choice",
                "instructions": "Classify the latest observed action in its preceding context. "
                                "Relevant new information or state change takes precedence over repetition.",
                "criteria": {
                    "progress": "New relevant information, a state change or an observed task outcome.",
                    "justified_retry": "No relevant change, but an explicit reason to check or wait again.",
                    "redundant": "Already answered or completed work with no relevant change or retry reason.",
                    "unclear": "Insufficient evidence or none of the other descriptions fits.",
                },
            },
        })
        answer = judgment["value"]["answers"]["situation"]
        # Illustrative threshold and one-action cooldown; neither is empirically calibrated.
        if answer["choice"] == "redundant" and answer["probabilities"]["redundant"] >= 0.8:
            recovery = env.component("reflect", context=recent["id"],
                                     inputs=[observation["id"], judgment["id"]])
            guidance = [recovery["id"]]
            cooling_down = True
