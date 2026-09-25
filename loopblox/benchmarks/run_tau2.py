"""Prepare telecom tasks and run, inspect, stop or recover continuous Loop research."""

import argparse
import json
from pathlib import Path

from loopblox import ROOT
from loopblox.benchmarks.tau2 import prepare_telecom_suite
from loopblox.research import campaign
from loopblox.runtime.io import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Freeze ten telecom training tasks and the sealed official test split")
    prepare.add_argument("--source", default=str(ROOT / ".artifacts/upstream/tau2-bench"))
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--seed", type=int, required=True, help="Record an explicit task-selection seed")
    prepare.add_argument("--exclude-suite", action="append", default=[],
                         help="Exclude reserved families from training; retain and disclose test overlap")
    run = commands.add_parser("run", help="Freeze and start a new continuous research campaign")
    run.add_argument("--suite", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--worker-image", default="python:3.12-slim")
    run.add_argument("--no-user", action="store_true", help="Use official solo mode with a fixed ticket and no simulated user")
    recover = commands.add_parser("recover", help="Recover an infrastructure failure in a new directory")
    recover.add_argument("--previous", type=Path, required=True)
    recover.add_argument("--output", type=Path, required=True)
    recover.add_argument("--reason", required=True, help="Diagnosis, new evidence or repair justifying recovery")
    recover.add_argument("--resume-stopped", action="store_true",
                         help="Use only after an explicit user request to resume a stopped campaign; retain all prior spend")
    recover.add_argument("--restart-candidate",
                         help="Explicitly authorized full-budget restart of one unfinished candidate; retain historical spend")
    for name, help_text in (("status", "Show current results and cumulative usage"),
                            ("stop", "Interrupt research and retain task cleanup and accounting")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--output", type=Path, required=True)
        if name == "stop":
            command.add_argument("--diagnostic-reason",
                                 help="Close an infrastructure fault for diagnosis; ordinary stop remains a user pause")
    args = parser.parse_args()
    if args.command == "prepare":
        manifest = prepare_telecom_suite(args.output, source=args.source, seed=args.seed,
                                         development=10, exclude_suites=args.exclude_suite)
        print(json.dumps({"tasks": len(manifest["tasks"]), "manifest": str(Path(args.output) / "manifest.json")}))
    elif args.command in {"run", "recover"}:
        options = (dict(suite=args.suite, worker_image=args.worker_image, solo_mode=args.no_user) if args.command == "run" else
                   dict(previous=args.previous, reason=args.reason, resume_stopped=args.resume_stopped,
                        restart_candidate=args.restart_candidate))
        root = campaign.prepare(args.output, **options)
        raise SystemExit(campaign.dispatch(root))
    elif args.command == "status":
        print(json.dumps(campaign.write_report(args.output.resolve()), indent=2))
    else:
        root = args.output.resolve()
        state = campaign.read(root / "result.json")
        if state["status"] not in {"prepared", "researching"}:
            parser.error("This campaign is already closed")
        request = dict(reason="user_stop")
        if args.diagnostic_reason is not None:
            if not args.diagnostic_reason.strip():
                parser.error("A diagnostic stop requires a nonempty reason")
            existing = root / "stop-request.json"
            if existing.exists():
                parser.error("A diagnostic stop cannot replace an existing stop request")
            request = dict(reason="infrastructure_failure", detail=args.diagnostic_reason)
        atomic_json(root / "stop-request.json", request)
        print("Stop requested; the host will interrupt research and retain task cleanup and accounting.")


if __name__ == "__main__":
    main()
