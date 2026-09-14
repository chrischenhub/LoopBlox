"""Shared provider transport, tool contracts, and failure/usage types."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from loopblox.runtime.io import run_process

JsonObject = dict[str, Any]
Effect = Literal["none", "applied", "unknown"]
_TRANSIENT_CODES = {"model_transport_failure", "rate_limit", "service_unavailable", "model_timeout"}
_PROVIDER_STOP_CODES = {"service_not_ready", "daily_quota_exhausted"}

# Trusted host transport, separate from the credential-free candidate worker.
# A process deadline bounds DNS, headers and the entire response body, including
# servers that keep a socket alive by sending small chunks indefinitely.
_HTTP_WORKER = '''
import http.client, json, sys, urllib.error, urllib.request
request = json.load(sys.stdin)
body = request.pop("body")
timeout = request.pop("timeout")
request = urllib.request.Request(**request, data=None if body is None else json.dumps(body).encode())
try:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = {"status": response.status, "body": response.read().decode("utf-8")}
except urllib.error.HTTPError as error:
    result = {"status": error.code, "body": error.read().decode("utf-8", errors="replace")}
except (TimeoutError, urllib.error.URLError, http.client.HTTPException, ConnectionError) as error:
    result = {"error": str(error), "code": "model_timeout" if isinstance(error, TimeoutError) else "model_transport_failure"}
json.dump(result, sys.stdout)
'''


class OperationalProblem(Exception):
    """A recognized runtime problem that leaves the runner state valid."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "service_unavailable",
        effects: Effect = "unknown",
        usage: JsonObject | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.effects = effects
        self.usage = usage


class HostFault(Exception):
    """The runner, its configuration, or a component violated the protocol."""

    def __init__(self, message: str, *, usage: JsonObject | None = None):
        super().__init__(message)
        self.usage = usage


class BudgetExhausted(Exception):
    pass


def usage_tokens(usage: JsonObject | None, key: str) -> int | None:
    value = None if usage is None else usage.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


@dataclass(frozen=True)
class PlanningTurn:
    """One complete provider response and its provider-independent JSON output."""

    raw: JsonObject
    output: JsonObject
    usage: JsonObject | None = None


@dataclass(frozen=True)
class ToolResult:
    status: Literal["ok", "failed"]
    result_or_error: Any
    effects: Effect


@dataclass(frozen=True)
class Tool:
    capability_id: str
    description: str
    parameters: JsonObject
    kind: Literal["inspect", "mutate", "test"]
    execute: Callable[[JsonObject, float], Any]
    # Present top-level result fields that brief observations must retain in full.
    preserve_observation_fields: tuple[str, ...] = ()

    def disclosure_record(self) -> JsonObject:
        record = {
            "capability_id": self.capability_id,
            "description": self.description,
            "parameters": _json_copy(self.parameters, f"parameters for {self.capability_id}"),
            "kind": self.kind,
        }
        if self.preserve_observation_fields:
            record["preserve_observation_fields"] = list(self.preserve_observation_fields)
        return record


def _json_copy(value: Any, label: str) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise HostFault(f"{label} must be valid JSON: {error}") from error


def load_env(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


class ChatCompletionsClient:
    """OpenAI-compatible adapter for the approved component output contracts."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 8192,
        timeout: float = 90.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "ChatCompletionsClient":
        load_env()
        api_key = os.environ.get("FREEINFERENCE_API_KEY")
        if not api_key:
            raise HostFault("FREEINFERENCE_API_KEY is missing")
        try:
            temperature = float(os.environ.get("FREEINFERENCE_TEMPERATURE", "0"))
            max_tokens = int(os.environ.get("FREEINFERENCE_MAX_TOKENS", "8192"))
        except ValueError as error:
            raise HostFault("FREEINFERENCE_TEMPERATURE and FREEINFERENCE_MAX_TOKENS must be numeric") from error
        return cls(
            api_key=api_key,
            base_url=os.environ.get("FREEINFERENCE_BASE_URL", "https://freeinference.org/v1"),
            model=os.environ.get("FREEINFERENCE_MODEL", "deepseek-v4-flash"),
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def complete(
        self,
        messages: tuple[JsonObject, ...],
        response_schema: JsonObject,
        *,
        max_output_tokens: int,
        timeout_seconds: float,
    ) -> PlanningTurn:
        body: JsonObject = {
            "model": self.model,
            "messages": list(messages),
            "temperature": self.temperature,
            "max_tokens": max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "component_output",
                    "strict": True,
                    "schema": response_schema,
                },
            },
        }
        payload = self._request("POST", "/chat/completions", body, timeout_seconds=timeout_seconds)
        usage = payload.get("usage")
        usage = _json_copy(usage, "provider usage") if isinstance(usage, dict) else None
        try:
            return self._parse_completion(payload, usage)
        except (OperationalProblem, HostFault) as error:
            error.usage = usage
            raise

    @staticmethod
    def _parse_completion(payload: JsonObject, usage: JsonObject | None) -> PlanningTurn:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise OperationalProblem(
                "chat completion response has no first choice",
                code="invalid_model_response",
                effects="none",
            )
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise OperationalProblem(
                "chat completion response has no assistant message",
                code="invalid_model_response",
                effects="none",
            )
        content = message.get("content")
        if not isinstance(content, str):
            raise OperationalProblem(
                "assistant message content is not a JSON string",
                code="invalid_model_response",
                effects="none",
            )
        try:
            output = json.loads(content)
        except json.JSONDecodeError as error:
            raise OperationalProblem(
                "assistant message is not valid JSON",
                code="invalid_model_response",
                effects="none",
            ) from error
        if not isinstance(output, dict):
            raise OperationalProblem(
                "assistant Planning output must be a JSON object",
                code="invalid_model_response",
                effects="none",
            )
        return PlanningTurn(
            raw=_json_copy(message, "raw assistant turn"),
            output=_json_copy(output, "Planning output"),
            usage=usage,
        )

    def complete_chat(self, messages, *, tools=None, tool_choice=None, seed=None,
                      max_output_tokens: int, timeout_seconds: float) -> PlanningTurn:
        """Native chat/tool output for a benchmark-owned simulated user."""
        body = dict(model=self.model, messages=messages, temperature=self.temperature, max_tokens=max_output_tokens)
        if tools:
            body.update(tools=tools, tool_choice=tool_choice or "auto")
        if seed is not None:
            body["seed"] = seed
        payload = self._request("POST", "/chat/completions", body, timeout_seconds=timeout_seconds)
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
        try:
            message = payload["choices"][0]["message"]
            if (message.get("role") != "assistant"
                    or not (message.get("content") or message.get("tool_calls"))):
                raise ValueError("Expected a nonempty assistant message")
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as error:
            raise OperationalProblem("Invalid simulated-user model response", code="invalid_model_response",
                                     effects="none", usage=usage) from error
        return PlanningTurn(raw=_json_copy(payload, "native chat response"),
                            output=_json_copy(message, "native assistant message"), usage=usage)

    def _request(
        self, method: str, path: str, body: JsonObject | None = None,
        *, timeout_seconds: float | None = None,
    ) -> JsonObject:
        timeout = self.timeout if timeout_seconds is None else min(self.timeout, timeout_seconds)
        budget_limited = timeout_seconds is not None and timeout_seconds <= self.timeout
        if timeout <= 0:
            raise BudgetExhausted("time_limit")
        request = dict(
            # The process owns the task deadline; the socket owns the client timeout.
            url=f"{self.base_url}{path}", body=body, timeout=self.timeout,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "loopblox/1",
                "X-Reasoning-Passthrough": "false",
            },
        )
        try:
            response = run_process([sys.executable, "-I", "-c", _HTTP_WORKER], timeout=timeout,
                                   input=json.dumps(request), capture_output=True, text=True)
        except subprocess.TimeoutExpired as error:
            if budget_limited:
                raise BudgetExhausted("time_limit") from error
            raise OperationalProblem("Model request exceeded its wall-clock deadline",
                                     code="model_timeout", effects="none") from error
        if response.returncode:
            raise HostFault("HTTP transport process failed: " + response.stderr[-500:])
        result = json.loads(response.stdout)
        if "error" in result:
            raise OperationalProblem(result["error"], code=result["code"], effects="none")
        if result["status"] >= 400:
            detail = result["body"]
            if result["status"] == 429:
                code = (
                    "daily_quota_exhausted"
                    if "Daily cost quota exceeded" in detail
                    else "rate_limit"
                )
                raise OperationalProblem(detail[:500], code=code, effects="none")
            if result["status"] in {408, 500, 502, 503, 504}:
                raise OperationalProblem(detail[:500], code="service_unavailable", effects="none")
            raise HostFault(f"HTTP {result['status']}: {detail[:500]}")
        try:
            payload = json.loads(result["body"])
        except json.JSONDecodeError as error:
            raise OperationalProblem(
                "API returned invalid JSON", code="model_transport_failure", effects="none"
            ) from error
        if not isinstance(payload, dict):
            raise HostFault("API response is not an object")
        choices = payload.get("choices")
        if (isinstance(choices, list) and choices and isinstance(choices[0], dict)
                and choices[0].get("finish_reason") == "length"):
            raise OperationalProblem("Model response reached its requested output limit",
                                     code="model_output_limit", effects="none",
                                     usage=payload.get("usage") if isinstance(payload.get("usage"), dict) else None)
        message = (choices[0].get("message", {}) if isinstance(choices, list) and choices
                   and isinstance(choices[0], dict) else {})
        content = message.get("content") if isinstance(message, dict) else None
        # This provider returns its startup notice as a successful assistant response.
        # Match the observed whole-message signature, not quoted text or user keywords.
        if (isinstance(content, str) and not message.get("tool_calls")
                and re.fullmatch(r"⏳ The model is starting up — this takes about \d+ minutes\. Please wait…", content.strip())):
            raise OperationalProblem(content, code="service_not_ready", effects="none",
                                     usage=payload.get("usage") if isinstance(payload.get("usage"), dict) else None)
        return payload
