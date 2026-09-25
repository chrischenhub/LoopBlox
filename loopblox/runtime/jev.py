"""Trusted Jev transport shared by online judgments and post-run trace analysis."""

import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

from loopblox import ROOT
from loopblox.runtime.io import run_process
from loopblox.runtime.model import HostFault, OperationalProblem, PlanningTurn, load_env


MODEL = "jev-1.13.0"
REQUEST_SECONDS = 30
OUTPUT_RESERVATION = 256


def judge_output_reservation(questions):
    """Reserve for typed answers and caller-defined identifiers, never truncate a request."""
    return sum(OUTPUT_RESERVATION + len(json.dumps(key, ensure_ascii=False).encode("utf-8")) +
               (2 * len(json.dumps(list(question["criteria"]), ensure_ascii=False).encode("utf-8"))
                + 32 * len(question["criteria"]) if question["type"] == "choice" else 0)
               for key, question in questions.items())


def sdk_process(python, mode, payload=None, *, module="loopblox.runtime.jev"):
    result = run_process([python, "-B", "-m", module, mode], input=json.dumps(payload),
                         timeout=REQUEST_SECONDS, capture_output=True, text=True, cwd=ROOT,
                         env={**os.environ, "PYTHONPATH": str(ROOT)})
    if result.returncode:
        raise HostFault("Jev SDK process failed: " + result.stderr.strip())
    try:
        return json.loads(result.stdout)
    except ValueError as error:
        raise HostFault("Jev SDK process returned invalid JSON", response=result.stdout) from error


def configuration(*, describe_module="loopblox.runtime.jev"):
    load_env()
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise HostFault("TYPESAFE_API_KEY is required for Jev")
    # Resolving a virtualenv interpreter symlink loses its installed SDK.
    python = str(Path(os.environ.get("LOOPBLOX_JEV_PYTHON") or sys.executable).absolute())
    return dict(model=MODEL, python=python, request_seconds=REQUEST_SECONDS,
                output_reservation=OUTPUT_RESERVATION,
                **sdk_process(python, "describe", module=describe_module))


def complete(body, configuration, allowance):
    """One attempt only; callers own shared gateway retries, budgets and recording."""
    try:
        result = sdk_process(configuration["python"], "request", body)
    except subprocess.TimeoutExpired as error:
        raise OperationalProblem("Jev request deadline exceeded", code="model_timeout", effects="none") from error
    if "error" in result:
        raise OperationalProblem(result["error"], code=result["code"], effects="none",
                                 response=result.get("response"))
    usage = result.get("usage") or {}
    usage = dict(prompt_tokens=usage.get("input_tokens"), completion_tokens=usage.get("output_tokens"))
    if not isinstance(result.get("answers"), dict) or set(result["answers"]) != set(body["questions"]):
        raise OperationalProblem("Jev response answers differ from the requested questions",
                                 code="invalid_model_response", effects="none", usage=usage, response=result)
    if usage["completion_tokens"] is not None and usage["completion_tokens"] > allowance:
        raise HostFault("Jev response exceeded its host output reservation", usage=usage, response=result)
    return PlanningTurn(raw=result, output=result["answers"], usage=usage)


def main():
    from typesafe_sdk import (RetryPolicy, TypeSafeClient, TypeSafeAPIConnectionError,
                             TypeSafeAPITimeoutError, TypeSafeAPIError, TypeSafeRateLimitError)
    if sys.argv[1] == "describe":
        result = dict(sdk_version=importlib.metadata.version("typesafe-sdk"))
    elif sys.argv[1] == "request":
        body = json.load(sys.stdin)
        try:
            with TypeSafeClient(model=body["model"], timeout=REQUEST_SECONDS, retry=RetryPolicy(max_retries=0)) as client:
                result = client.system_one(state=body["state"], questions=body["questions"]).model_dump(mode="json")
        except Exception as error:
            detail = error.body.get("detail", {}) if isinstance(error, TypeSafeAPIError) and isinstance(error.body, dict) else {}
            code = ("jev_input_limit" if isinstance(detail, dict) and detail.get("error_type") == "max_tokens_exceeded" else
                    "model_timeout" if isinstance(error, TypeSafeAPITimeoutError) else
                    "model_transport_failure" if isinstance(error, TypeSafeAPIConnectionError) else
                    "rate_limit" if isinstance(error, TypeSafeRateLimitError) else
                    "service_unavailable" if isinstance(error, TypeSafeAPIError)
                    and error.status in {408, 500, 502, 503, 504, 529} else "jev_request_failed")
            result = dict(error=type(error).__name__ + ": " + str(error), code=code)
            if isinstance(error, TypeSafeAPIError):
                result["response"] = dict(status=error.status, body=error.body)
    else:
        raise ValueError("Expected describe or request")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
