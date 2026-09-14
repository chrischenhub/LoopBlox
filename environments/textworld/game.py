"""Trusted TextWorld process. Its files and scoring state never enter the controller."""

import importlib.metadata
import json
from pathlib import Path
import platform
import sys

import textworld
from textworld.challenges import CHALLENGES


def visible(state):
    # Explicit allowlist: never serialize GameState, metadata, facts or winning policies.
    return {key: state.get(key) for key in
            ("feedback", "description", "inventory", "admissible_commands")}


def verdict(state):
    return {key: state.get(key) for key in ("won", "lost", "score", "max_score", "moves")}


def start(path):
    return textworld.start(str(path), textworld.EnvInfos(
        description=True, inventory=True, admissible_commands=True,
        won=True, lost=True, score=True, max_score=True, moves=True,
    ))


def prepare(directory):
    config = json.loads((directory / "generation.json").read_text())
    validation = []
    for task in config["tasks"]:
        path = directory / "games" / (task["task_id"] + ".z8")
        path.parent.mkdir(exist_ok=True)
        _, make, parser = CHALLENGES[task["challenge"]]
        settings = vars(parser().parse_args(task["arguments"]))
        options = textworld.GameOptions()
        options.seeds, options.path = task["seed"], str(path)
        game = make(settings, options)
        if "objective" in task:
            # Coin Collector's generated default objective narrates its solution route.
            # Replace it before compilation, so ordinary game feedback cannot reveal that route.
            game.objective = task["objective"]
        textworld.generator.compile_game(game, options)
        env = start(path)
        try:
            state = env.reset()
            for action in game.metadata["walkthrough"]:
                state, _, done = env.step(action)
                if done:
                    break
            if not state.won:
                raise RuntimeError("Generated game failed its private walkthrough: " + task["task_id"])
            validation.append({"task_id": task["task_id"], **verdict(state)})
        finally:
            env.close()
        print("Prepared " + task["task_id"], flush=True)
    (directory / "validation.json").write_text(json.dumps(validation, indent=2) + "\n")
    versions = {dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions()}
    (directory / "versions.json").write_text(json.dumps({
        "python": platform.python_version(), "packages": dict(sorted(versions.items())),
    }, indent=2) + "\n")


def serve(path):
    env = start(path)
    try:
        state = env.reset()
        done = False
        print(json.dumps({"observation": visible(state)}), flush=True)
        for line in sys.stdin:
            request = json.loads(line)
            if request["method"] == "finish":
                # Only the host sends this, after the task controller has closed.
                print(json.dumps({"verification": verdict(state)}), flush=True)
                return
            if request["method"] != "step":
                raise ValueError("Unknown environment operation")
            command = request["command"]
            allowed = set(state.admissible_commands or ()) | {"look", "inventory"}
            if done or command not in allowed:
                result = {"status": "failed", "effects": "none", "result": {
                    "error": "Game is over." if done else "Choose a currently admissible command, look, or inventory.",
                    **visible(state),
                }}
            else:
                state, _, done = env.step(command)
                result = {"status": "ok", "effects": "applied", "result": visible(state)}
            print(json.dumps(result), flush=True)
    finally:
        env.close()


if __name__ == "__main__":
    operation, raw_path = sys.argv[1:]
    if operation == "prepare":
        prepare(Path(raw_path))
    elif operation == "serve":
        serve(Path(raw_path))
    else:
        raise ValueError("Expected prepare or serve")
