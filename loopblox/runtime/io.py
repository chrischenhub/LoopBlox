"""Host-owned persistence and bounded process execution, independent of task environments."""

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess


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


def run_process(arguments, *, timeout: float, **kwargs) -> subprocess.CompletedProcess:
    """Bound the whole process tree, including shells and their child commands."""
    input_text = kwargs.pop("input", None)
    if kwargs.pop("capture_output", False):
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    if input_text is not None:
        kwargs["stdin"] = subprocess.PIPE
    process = subprocess.Popen(arguments, start_new_session=True, **kwargs)
    try:
        stdout, stderr = process.communicate(input=input_text, timeout=max(0.001, timeout))
        return subprocess.CompletedProcess(arguments, process.returncode, stdout, stderr)
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise
