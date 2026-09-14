"""Shared campaign process control, frozen-input checks and model settings."""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess

from loopblox import ROOT
from loopblox.runtime.model import ChatCompletionsClient
from loopblox.runtime.io import digest
from loopblox.experiments.study import model_settings
from loopblox.benchmarks.tau2 import load_suite


def read(path):
    return json.loads(Path(path).read_text())


def run_stage(arguments, *, source_root=ROOT):
    """Give the serial child time to persist interruption and release its workers."""
    environment = {**os.environ, "PYTHONPATH": str(source_root)}
    process = subprocess.Popen(arguments, start_new_session=True, env=environment)
    try:
        return process.wait()
    except KeyboardInterrupt:
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            try:
                os.killpg(process.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        finally:
            signal.signal(signal.SIGINT, previous)
        raise


def verify(root):
    protocol = read(root / "protocol.json")
    for name, expected in protocol["implementation_sha256"].items():
        if digest((root / "implementation" / name).read_bytes()) != expected:
            raise ValueError("Frozen implementation changed: " + name)
    if ROOT != root / "implementation":
        raise ValueError("Run the frozen implementation, not the mutable checkout")
    if digest((root / "suite/manifest.json").read_bytes()) != protocol["suite_manifest_sha256"]:
        raise ValueError("Frozen task manifest changed")
    for name, expected in protocol.get("recovery", {}).get("imported_files", {}).items():
        if digest((root / name).read_bytes()) != expected:
            raise ValueError("An imported research record changed: " + name)
    load_suite(root / "suite")
    return protocol


def clients(protocol):
    from loopblox.benchmarks.run_tau2 import user_client
    client = ChatCompletionsClient.from_env()
    user = user_client(argparse.Namespace(user_model=protocol["user_model"]["model"],
                        user_output_allowance=protocol["user_model"]["max_tokens"]), client)
    if model_settings(client) != protocol["model"] or model_settings(user) != protocol["user_model"]:
        raise ValueError("Model settings differ from the frozen protocol")
    return client, user
