"""Prepare and compare reusable Loops on the TextWorld mechanism checks."""

import argparse
import json
from pathlib import Path

from controller_runtime import Limits
from study import run_study, write_report
from textworld_benchmark import ENVIRONMENT_IMAGE, HERE, TextWorldRunner, load_suite, prepare_suite


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Generate and privately validate a frozen two-family suite")
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--development", type=int, default=4)
    prepare.add_argument("--holdout", type=int, default=4)
    prepare.add_argument("--seed", type=int, default=1701)
    prepare.add_argument("--environment-image", default=ENVIRONMENT_IMAGE)
    study = commands.add_parser("study", help="Run independent searches, holdout and cross-family comparisons")
    study.add_argument("--suite", required=True)
    study.add_argument("--output", required=True)
    study.add_argument("--experiment", default=str(HERE / "experiments" / "textworld.json"))
    study.add_argument("--worker-image", default="python:3.12-slim")
    study.add_argument("--seed", type=int, default=0)
    study.add_argument("--development-runs", type=int, default=8)
    study.add_argument("--research-seconds", type=float, default=3600)
    study.add_argument("--research-model-calls", type=int, default=256)
    study.add_argument("--research-output-tokens", type=int, default=262144)
    for name, value in vars(Limits()).items():
        study.add_argument("--task-" + name.replace("_", "-"), type=type(value), default=value)
    report = commands.add_parser("report", help="Regenerate the HTML comparison from recorded facts")
    report.add_argument("output")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare_suite(args.output, development=args.development, holdout=args.holdout,
                      seed=args.seed, environment_image=args.environment_image)
        print(str(Path(args.output) / "manifest.json"))
    elif args.command == "study":
        result = run_study(args, load_suite=load_suite,
                           runner_factory=lambda suite, manifest, client, worker, limits, private: TextWorldRunner(
                               suite, manifest, client, worker, limits),
                           extra_sources=("run_textworld.py", "textworld_benchmark.py"))
        print(json.dumps({"status": result["status"], "report": str(Path(args.output) / "report.html")}))
    else:
        write_report(args.output)


if __name__ == "__main__":
    main()
