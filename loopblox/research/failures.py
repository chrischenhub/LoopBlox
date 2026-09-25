"""Host-owned routing; model judgments never grant repair or evaluation authority."""

from loopblox.runtime.model import BudgetExhausted
from loopblox.runtime.io import digest
import json


def fingerprint(failure):
    """Group recurrence by fault kind, independently of task and provider request IDs."""
    identity = {key: failure.get(key) for key in ("stage", "code", "http_status", "error_type")}
    if not identity["code"]:
        identity["detail"] = failure.get("detail")
    return digest(json.dumps(identity, sort_keys=True).encode())


def incident(error=None, *, stage, status=None, code=None, response=None):
    code = code or getattr(error, "code", None)
    response = response if response is not None else getattr(error, "response", None)
    http_status = response.get("status") if isinstance(response, dict) else None
    # Native CLI failures carry a typed error inside the turn.failed event.
    native_error = response.get("error", response) if isinstance(response, dict) else {}
    native_code = native_error.get("codex_error_info") or native_error.get("code") if isinstance(native_error, dict) else None
    if isinstance(native_code, str):
        code = code or native_code
    message = native_error.get("message", "") if isinstance(native_error, dict) else ""
    if not code and isinstance(message, str) and any(phrase in message.lower() for phrase in (
        "you've hit your usage limit", "usage limit reached", "insufficient quota",
    )):
        code = "usage_limit_reached"
    if isinstance(error, ValueError) and str(error) in {
        "Codex requires an explicit ChatGPT auth file",
        "Cannot read the supplied native Codex auth file",
        "The supplied Codex auth file must contain an existing ChatGPT subscription login",
    }:
        code = "credentials_required"
    if stage == "task" and status in {"completed", "budget_exhausted", "candidate_error"}:
        route, action = "researcher", "continue_batch"
    elif isinstance(error, BudgetExhausted) or code in {
        "daily_quota_exhausted", "credentials_required", "usage_limit_reached", "insufficient_quota",
        "unauthorized", "authentication_error", "refresh_token_expired", "refresh_token_reused",
    } or http_status in {401, 402, 403}:
        route, action = "human", "supply_budget_or_access"
    else:
        route, action = "infra", "repair_and_recover"
    return dict(route=route, action=action, stage=stage, status=status,
                code=code, http_status=http_status,
                error_type=type(error).__name__ if error is not None else None,
                detail=str(error) if error is not None else status)
