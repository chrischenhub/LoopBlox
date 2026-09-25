"""Host-owned persistence and bounded process execution, independent of task environments."""

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from contextlib import contextmanager
from contextvars import ContextVar


_cancellation = ContextVar("host_cancellation", default=None)


class EvaluationCancelled(Exception):
    """Internal dispatch cancellation, never a user interrupt."""


@contextmanager
def cancellation_scope(event):
    token = _cancellation.set(event)
    try:
        yield
    finally:
        _cancellation.reset(token)


def check_cancelled():
    event = _cancellation.get()
    if event is not None and event.is_set():
        raise EvaluationCancelled("evaluation_cancelled")


def cancel_dispatch():
    event = _cancellation.get()
    if event is not None:
        event.set()


def wait_seconds(seconds):
    event = _cancellation.get()
    if event is None:
        time.sleep(seconds)
    elif event.wait(seconds):
        check_cancelled()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def image_id(image):
    result = run_process(["docker", "image", "inspect", image, "--format", "{{.Id}}"],
                         timeout=30, capture_output=True, text=True)
    if result.returncode:
        raise ValueError(f"Docker image unavailable: {image}. Prepare it before running. {result.stderr.strip()}")
    return result.stdout.strip()


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value)
    temporary.replace(path)


def atomic_json(path: Path, value: dict) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def run_process(arguments, *, timeout: float | None, on_output=None, **kwargs) -> subprocess.CompletedProcess:
    """Bound a process tree; an output callback may renew the deadline on progress.

    The callback receives newly captured stdout bytes and returns whether meaningful
    progress occurred. Merely receiving bytes does not renew the deadline.
    """
    input_text = kwargs.pop("input", None)
    if kwargs.pop("capture_output", False):
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    if input_text is not None:
        kwargs["stdin"] = subprocess.PIPE
    check_cancelled()
    process = subprocess.Popen(arguments, start_new_session=True, **kwargs)
    deadline = None if timeout is None else time.monotonic() + max(0.001, timeout)
    output_cursor = 0

    def observe(output):
        nonlocal output_cursor, deadline
        if on_output is None:
            return
        data = output.encode(kwargs.get("encoding") or "utf-8") if isinstance(output, str) else output or b""
        if len(data) > output_cursor:
            progress = on_output(data[output_cursor:])
            output_cursor = len(data)
            if progress and timeout is not None:
                deadline = time.monotonic() + timeout

    try:
        while True:
            check_cancelled()
            remaining = None if deadline is None else max(0.001, deadline - time.monotonic())
            try:
                interval = remaining
                if _cancellation.get() is not None or on_output is not None:
                    interval = 0.25 if remaining is None else min(0.25, remaining)
                stdout, stderr = process.communicate(input=input_text, timeout=interval)
                observe(stdout)
                break
            except subprocess.TimeoutExpired as error:
                input_text = None  # communicate retains unsent input across timeout polls.
                observe(error.output)
                if deadline is not None and time.monotonic() >= deadline:
                    raise
        return subprocess.CompletedProcess(arguments, process.returncode, stdout, stderr)
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise
