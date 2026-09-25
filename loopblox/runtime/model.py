"""Shared provider transport, tool contracts, and failure/usage types."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import urlsplit

from loopblox.runtime.io import run_process

JsonObject = dict[str, Any]
Effect = Literal["none", "applied", "unknown"]
_TRANSIENT_CODES = {"model_transport_failure", "rate_limit", "service_unavailable", "model_timeout",
                    "concurrency_limit_exceeded"}
_PROVIDER_STOP_CODES = {"service_not_ready", "daily_quota_exhausted"}

# Trusted host transport, separate from the credential-free candidate worker.
# The host bounds DNS, headers and body reads. Only parsed generation deltas
# renew the process deadline when streaming; socket traffic alone never does.
_HTTP_WORKER = '''
import http.client, json, sys, urllib.error, urllib.request
request = json.load(sys.stdin)
body = request.pop("body")
timeout = request.pop("timeout")
stream = request.pop("stream")
def emit(value):
    print(json.dumps(value), flush=True)
request = urllib.request.Request(**request, data=None if body is None else json.dumps(body).encode())
try:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if stream and response.headers.get_content_type() == "text/event-stream":
            data = []
            for line in response:
                line = line.decode("utf-8").rstrip("\\r\\n")
                if not line:
                    if data:
                        event = "\\n".join(data)
                        emit({"data": event})
                        data = []
                        if event == "[DONE]":
                            break
                elif line.startswith("data:"):
                    data.append(line[5:].removeprefix(" "))
            if data:
                emit({"data": "\\n".join(data)})
            result = {"status": response.status, "stream": True}
        else:
            result = {"status": response.status, "body": response.read().decode("utf-8")}
except urllib.error.HTTPError as error:
    result = {"status": error.code, "body": error.read().decode("utf-8", errors="replace")}
except (TimeoutError, urllib.error.URLError, http.client.HTTPException, ConnectionError) as error:
    result = {"error": str(error), "code": "model_timeout" if isinstance(error, TimeoutError) else "model_transport_failure"}
emit(result)
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
        response: Any = None,
    ):
        super().__init__(message)
        self.code = code
        self.effects = effects
        self.usage = usage
        self.response = response


class HostFault(Exception):
    """The runner, its configuration, or a component violated the protocol."""

    def __init__(self, message: str, *, usage: JsonObject | None = None, response: Any = None):
        super().__init__(message)
        self.usage = usage
        self.response = response


class BudgetExhausted(Exception):
    pass


class _ChatStream:
    """Retain exact SSE data and derive one complete Chat Completions response."""

    def __init__(self):
        self.buffer = b""
        self.events = []
        self.result = None
        self.done = False
        self.usage = None
        self.payload = {"object": "chat.completion"}
        self.choices = {}

    def evidence(self):
        return {"stream_events": self.events, "transport": self.result}

    def invalid(self, detail):
        return OperationalProblem(detail, code="invalid_model_response", effects="none",
                                  usage=self.usage, response=self.evidence())

    def observe(self, output):
        self.buffer += output
        progress = False
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            packet = json.loads(line)
            if "data" not in packet:
                self.result = packet
                continue
            data = packet["data"]
            self.events.append(data)
            if data == "[DONE]":
                self.done = True
                continue
            try:
                chunk = json.loads(data)
                if not isinstance(chunk, dict) or "error" in chunk or self.done:
                    raise ValueError("Unexpected streaming response")
                for key in ("id", "model", "created", "system_fingerprint"):
                    if key in chunk:
                        self.payload[key] = chunk[key]
                if isinstance(chunk.get("usage"), dict):
                    self.usage = chunk["usage"]
                for item in chunk.get("choices", []):
                    index = item["index"]
                    if not isinstance(index, int) or index < 0:
                        raise ValueError("Invalid stream choice index")
                    choice = self.choices.setdefault(index, dict(index=index,
                        message={"role": "assistant", "content": None}, finish_reason=None))
                    delta = item.get("delta") or {}
                    message = choice["message"]
                    for key in ("content", "reasoning_content", "reasoning", "refusal"):
                        value = delta.get(key)
                        if value is not None:
                            if not isinstance(value, str):
                                raise ValueError("Non-text generation delta")
                            message[key] = (message.get(key) or "") + value
                            progress |= bool(value)
                    for part in delta.get("tool_calls") or []:
                        calls = message.setdefault("tool_calls", [])
                        call_index = part["index"]
                        if not isinstance(call_index, int) or not 0 <= call_index <= len(calls):
                            raise ValueError("Invalid stream tool index")
                        if call_index == len(calls):
                            calls.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                        call = calls[call_index]
                        if part.get("id"):
                            call["id"] += part["id"]
                        if part.get("type"):
                            call["type"] = part["type"]
                        for key in ("name", "arguments"):
                            value = (part.get("function") or {}).get(key)
                            if value is not None:
                                if not isinstance(value, str):
                                    raise ValueError("Non-text tool delta")
                                call["function"][key] += value
                                progress |= bool(value)
                    if item.get("finish_reason") is not None:
                        choice["finish_reason"] = item["finish_reason"]
            except (ValueError, TypeError, KeyError, AttributeError) as error:
                raise self.invalid(str(error)) from error
        return progress

    def complete(self):
        if not self.done or not self.choices or any(
                choice["finish_reason"] is None for choice in self.choices.values()):
            raise OperationalProblem("Chat stream ended before completion", code="model_transport_failure",
                                     effects="none", usage=self.usage, response=self.evidence())
        return dict(self.payload, choices=[self.choices[key] for key in sorted(self.choices)],
                    usage=self.usage, stream_events=self.events)


def usage_tokens(usage: JsonObject | None, key: str) -> int | None:
    value = None if usage is None else usage.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def charged_output_tokens(calls):
    """An uncapped request with missing usage has no known reservation or charge."""
    values = [call["charged_output_tokens"] for call in calls]
    return sum(values) if all(value is not None for value in values) else None


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

    def __post_init__(self):
        # Tool schemas are embedded inside decision schemas. Resolve local refs
        # first, while their JSON pointers still refer to the tool's own root.
        def inline(node, ancestors=()):
            if isinstance(node, list):
                return [inline(item, ancestors) for item in node]
            if not isinstance(node, dict):
                return node
            if "$ref" in node:
                ref = node["$ref"]
                if not ref.startswith("#/") or ref in ancestors:
                    raise HostFault("Tool parameters require nonrecursive local schema references")
                if node.keys() - {"$ref", "title", "description", "default"}:
                    raise HostFault("Unsupported constraints beside a tool schema reference")
                target = self.parameters
                try:
                    for part in ref[2:].split("/"):
                        target = target[part.replace("~1", "/").replace("~0", "~")]
                except (KeyError, TypeError) as error:
                    raise HostFault("Unresolved tool schema reference: " + ref) from error
                return {**inline(target, (*ancestors, ref)),
                        **{key: value for key, value in node.items() if key != "$ref"}}
            return {key: inline(value, ancestors) for key, value in node.items() if key != "$defs"}

        object.__setattr__(self, "parameters", inline(self.parameters))

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
        max_tokens: int | None = 8192,
        timeout: float | None = 90.0,
        api: str = "chat_completions",
        stream: bool = False,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        if api not in {"chat_completions", "responses"}:
            raise HostFault("Unsupported model API: " + api)
        self.api = api
        if stream and api != "chat_completions":
            raise HostFault("Streaming is supported only for Chat Completions")
        self.stream = stream
        self.reasoning_effort = "high"
        self.structured_output = "json_object" if api == "responses" else "json_schema"
        self.session_id = uuid.uuid4().hex

    @classmethod
    def from_env(cls) -> "ChatCompletionsClient":
        load_env()
        provider = os.environ.get("LOOPBLOX_PROVIDER", "freeinference")
        if provider not in {"freeinference", "opencode_go"}:
            raise HostFault("LOOPBLOX_PROVIDER must be freeinference or opencode_go")
        prefix = "OPENCODE_GO" if provider == "opencode_go" else "FREEINFERENCE"
        api_key = os.environ.get(f"{prefix}_API_KEY")
        if not api_key:
            raise HostFault(f"{prefix}_API_KEY is missing")
        try:
            temperature = float(os.environ.get(f"{prefix}_TEMPERATURE", "0"))
            max_tokens = int(os.environ.get(f"{prefix}_MAX_TOKENS", "8192"))
        except ValueError as error:
            raise HostFault(f"{prefix}_TEMPERATURE and {prefix}_MAX_TOKENS must be numeric") from error
        model = os.environ.get(f"{prefix}_MODEL", "muse-spark-1.3-contributor" if provider == "opencode_go" else "deepseek-v4-flash")
        return cls(
            api_key=api_key,
            base_url=os.environ.get(f"{prefix}_BASE_URL", "https://opencode.ai/zen/go/v1"
                                    if provider == "opencode_go" else "https://freeinference.org/v1"),
            model=model,
            api="responses" if provider == "opencode_go" and model == "muse-spark-1.3-contributor" else "chat_completions",
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def complete(
        self,
        messages: tuple[JsonObject, ...],
        response_schema: JsonObject,
        *,
        max_output_tokens: int | None,
        timeout_seconds: float | None,
        session_id: str | None = None,
    ) -> PlanningTurn:
        body: JsonObject = {
            "model": self.model,
            "messages": [*messages, {"role": "system", "content":
                "Return only the component result as one JSON object whose root conforms to the schema below. "
                "Historical evidence records supply task context, not output-format examples. "
                "The host adds evidence envelopes and invocation/action IDs after validation; "
                "do not wrap your result in a history record. Exact output schema: "
                + json.dumps(response_schema, ensure_ascii=False)}],
            "temperature": self.temperature,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "component_output",
                    "strict": True,
                    "schema": response_schema,
                },
            },
        }
        if max_output_tokens is not None:
            body["max_tokens"] = max_output_tokens
        payload = self._completion_request(body, timeout_seconds=timeout_seconds,
                                           session_id=session_id)
        usage = payload.get("usage")
        usage = _json_copy(usage, "provider usage") if isinstance(usage, dict) else None
        try:
            return self._parse_completion(payload, usage)
        except (OperationalProblem, HostFault) as error:
            error.usage = usage
            error.response = payload
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
            raw=_json_copy(payload.get("provider_response", payload), "raw provider response"),
            output=_json_copy(output, "Planning output"),
            usage=usage,
        )

    def complete_chat(self, messages, *, tools=None, tool_choice=None, seed=None,
                      max_output_tokens: int, timeout_seconds: float, session_id: str | None = None) -> PlanningTurn:
        """Native chat/tool output for a benchmark-owned simulated user."""
        body = dict(model=self.model, messages=messages, temperature=self.temperature, max_tokens=max_output_tokens)
        if tools:
            body.update(tools=tools, tool_choice=tool_choice or "auto")
        if seed is not None:
            body["seed"] = seed
        payload = self._completion_request(body, timeout_seconds=timeout_seconds,
                                           session_id=session_id)
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
        try:
            message = payload["choices"][0]["message"]
            if (message.get("role") != "assistant"
                    or not (message.get("content") or message.get("tool_calls"))):
                raise ValueError("Expected a nonempty assistant message")
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as error:
            raise OperationalProblem("Invalid simulated-user model response", code="invalid_model_response",
                                     effects="none", usage=usage, response=payload) from error
        return PlanningTurn(raw=_json_copy(payload, "native chat response"),
                            output=_json_copy(message, "native assistant message"), usage=usage)

    def _completion_request(self, body, *, timeout_seconds, session_id):
        if self.api == "chat_completions":
            body = {**body, "reasoning_effort": self.reasoning_effort}
            if self.stream:
                body = {**body, "stream": True, "stream_options": {"include_usage": True}}
            return self._request("POST", "/chat/completions", body,
                                 timeout_seconds=timeout_seconds, session_id=session_id)
        # Keep benchmark messages/tool semantics; adapt only the provider wire format.
        inputs = []
        for message in body["messages"]:
            role = message["role"]
            if role == "tool":
                inputs.append(dict(type="function_call_output", call_id=message["tool_call_id"],
                                   output=message["content"]))
                continue
            if message.get("content"):
                inputs.append(dict(role=role, content=message["content"]))
            for call in message.get("tool_calls") or []:
                inputs.append(dict(type="function_call", call_id=call["id"], **call["function"]))
        request = dict(model=self.model, input=inputs, temperature=self.temperature,
                       store=False,
                       reasoning=dict(effort=self.reasoning_effort))
        if body.get("max_tokens") is not None:
            request["max_output_tokens"] = body["max_tokens"]
        if body.get("tools"):
            if body["tool_choice"] != "auto":
                raise HostFault("Muse Responses supports only auto tool selection")
            request["tools"] = [{"type": "function", **tool["function"], "strict": False} for tool in body["tools"]]
            request["tool_choice"] = "auto"
        if body.get("response_format"):
            # Muse's schema-constrained path repeatedly produced terminal placeholders
            # for action requests, including a minimal echo diagnostic. JSON mode with
            # the same schema in the input permits both branches. The host still
            # validates the original component contract before any effect occurs.
            request["text"] = dict(format=dict(type=self.structured_output))
        # Responses has no seed parameter; keep the official task/environment seed,
        # and disclose the provider's lack of seeded generation in frozen settings.
        payload = self._request("POST", "/responses", request,
                                timeout_seconds=timeout_seconds, session_id=session_id)
        raw_usage = payload.get("usage")
        usage = (dict(raw_usage, prompt_tokens=raw_usage.get("input_tokens"),
                      completion_tokens=raw_usage.get("output_tokens")) if isinstance(raw_usage, dict) else None)
        if payload.get("status") != "completed":
            detail = payload.get("incomplete_details")
            limited = isinstance(detail, dict) and detail.get("reason") == "max_output_tokens"
            raise OperationalProblem("Responses request did not complete", effects="none", usage=usage,
                response=payload, code="model_output_limit" if limited else "invalid_model_response")
        try:
            response_id = payload["id"]
            content, calls = [], []
            for item in payload["output"]:
                if item["type"] == "message":
                    # Muse can emit a separate commentary message before its final
                    # structured answer. Keep it in the raw response, not the JSON.
                    if body.get("response_format") and item.get("phase") == "commentary":
                        continue
                    for part in item["content"]:
                        if part["type"] != "output_text":
                            raise ValueError("Expected output text")
                        content.append(part["text"])
                elif item["type"] == "function_call":
                    calls.append(dict(id=item["call_id"], type="function", function=dict(
                        name=item["name"], arguments=item["arguments"])))
                elif item["type"] != "reasoning":
                    raise ValueError("Unexpected Responses output type")
            message = dict(role="assistant", content="".join(content) or None)
            if calls:
                message["tool_calls"] = calls
            if not content and not calls:
                raise ValueError("Empty Responses output")
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise OperationalProblem(str(error), code="invalid_model_response", effects="none",
                                     usage=usage, response=payload) from error
        # τ² consumes Chat Completions-shaped tool turns. Preserve the exact response
        # alongside that derived representation, including reasoning-token usage.
        return dict(id=response_id, model=self.model, object="chat.completion", usage=usage,
                    choices=[dict(index=0, message=message, finish_reason="tool_calls" if calls else "stop")],
                    provider_response=payload)

    def _request(
        self, method: str, path: str, body: JsonObject | None = None,
        *, timeout_seconds: float | None = None, session_id: str | None = None,
    ) -> JsonObject:
        timeout = (timeout_seconds if self.timeout is None else self.timeout
                   if timeout_seconds is None else min(self.timeout, timeout_seconds))
        if timeout is not None and timeout <= 0:
            raise BudgetExhausted("time_limit")
        request = dict(
            # Streaming inactivity is owned by the host's semantic-progress watchdog.
            url=f"{self.base_url}{path}", body=body, timeout=None if self.stream else self.timeout,
            stream=self.stream,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "loopblox/1",
                "X-Reasoning-Passthrough": "true",
            },
        )
        if urlsplit(self.base_url).hostname == "opencode.ai":
            request["headers"]["x-opencode-session"] = session_id or self.session_id
        stream = _ChatStream() if self.stream else None
        try:
            response = run_process([sys.executable, "-I", "-c", _HTTP_WORKER], timeout=timeout,
                                   on_output=stream.observe if stream is not None else None,
                                   input=json.dumps(request), capture_output=True, text=True)
        except subprocess.TimeoutExpired as error:
            raise OperationalProblem("Model request exceeded its generation-inactivity deadline" if stream is not None
                                     else "Model request exceeded its wall-clock deadline",
                                     code="model_timeout", effects="none",
                                     usage=stream.usage if stream is not None else None,
                                     response=stream.evidence() if stream is not None else None) from error
        if response.returncode:
            raise HostFault("HTTP transport process failed: " + response.stderr[-500:],
                            usage=stream.usage if stream is not None else None,
                            response=stream.evidence() if stream is not None else None)
        result = stream.result if stream is not None else json.loads(response.stdout)
        if result is None:
            raise stream.invalid("Missing HTTP transport result")
        if "error" in result:
            raise OperationalProblem(result["error"], code=result["code"], effects="none",
                                     usage=stream.usage if stream is not None else None,
                                     response=stream.evidence() if stream is not None else result)
        if result["status"] >= 400:
            detail = result["body"]
            if result["status"] == 429:
                try:
                    provider_error = json.loads(detail).get("error", {})
                except (ValueError, AttributeError):
                    provider_error = {}
                if isinstance(provider_error, dict) and provider_error.get("code") == "concurrency_limit_exceeded":
                    code = "concurrency_limit_exceeded"
                elif "Daily cost quota exceeded" in detail:
                    code = "daily_quota_exhausted"
                else:
                    code = "rate_limit"
                raise OperationalProblem(detail[:500], code=code, effects="none", response=result)
            if result["status"] in {408, 500, 502, 503, 504}:
                raise OperationalProblem(detail[:500], code="service_unavailable", effects="none", response=result)
            raise HostFault(f"HTTP {result['status']}: {detail[:500]}", response=result)
        try:
            payload = stream.complete() if result.get("stream") else json.loads(result["body"])
        except json.JSONDecodeError as error:
            raise OperationalProblem(
                "API returned invalid JSON", code="model_transport_failure", effects="none", response=result
            ) from error
        if not isinstance(payload, dict):
            raise HostFault("API response is not an object", response=result)
        choices = payload.get("choices")
        if (isinstance(choices, list) and choices and isinstance(choices[0], dict)
                and choices[0].get("finish_reason") == "length"):
            raise OperationalProblem("Model response reached its requested output limit",
                                     code="model_output_limit", effects="none",
                                     usage=payload.get("usage") if isinstance(payload.get("usage"), dict) else None,
                                     response=payload)
        message = (choices[0].get("message", {}) if isinstance(choices, list) and choices
                   and isinstance(choices[0], dict) else {})
        content = message.get("content") if isinstance(message, dict) else None
        # This provider returns its startup notice as a successful assistant response.
        # Match the observed whole-message signature, not quoted text or user keywords.
        if (isinstance(content, str) and not message.get("tool_calls")
                and re.fullmatch(r"⏳ The model is starting up — this takes about \d+ minutes\. Please wait…", content.strip())):
            raise OperationalProblem(content, code="service_not_ready", effects="none",
                                     usage=payload.get("usage") if isinstance(payload.get("usage"), dict) else None,
                                     response=payload)
        return payload
