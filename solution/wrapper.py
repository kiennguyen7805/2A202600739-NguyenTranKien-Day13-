"""Observability and mitigation boundary for the opaque commerce agent."""
from __future__ import annotations

import copy
import re
import time
import unicodedata

try:
    from telemetry.cost import cost_from_usage
    from telemetry.logger import logger, new_correlation_id, set_correlation_id
    from telemetry.redact import redact
except Exception:
    logger = None

    def cost_from_usage(model, usage):
        return 0.0

    def new_correlation_id():
        return "wrapper-request"

    def set_correlation_id(correlation_id):
        return None

    def redact(value):
        return value, 0


_NOTE_BLOCK = re.compile(
    r"(?is)(?:\bghi\s*ch(?:u|\u00fa)\b|\border\s*notes?\b|\bnotes?\b)\s*[:=-].*$"
)


def _sanitize_question(question):
    """Remove untrusted note blocks while preserving the actual order request."""
    if not isinstance(question, str):
        return question, False
    cleaned, count = _NOTE_BLOCK.subn("[UNTRUSTED NOTE REMOVED]", question)
    return cleaned, count > 0


def _cache_key(question):
    question = str(question)
    normalized = unicodedata.normalize("NFKC", question)
    return "observathon:v1:" + " ".join(normalized.casefold().split())


def _walk_errors(value):
    """Collect tool/agent errors from an arbitrarily nested trace."""
    errors = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() == "error" and child:
                errors.append(str(child))
            else:
                errors.extend(_walk_errors(child))
    elif isinstance(value, list):
        for child in value:
            errors.extend(_walk_errors(child))
    return errors


def _action_signature(step):
    if not isinstance(step, dict):
        return None
    action = step.get("action") or step.get("tool") or step.get("name")
    if not action:
        return None
    args = step.get("args") or step.get("arguments") or step.get("input")
    return repr((action, args))


def _repeated_actions(trace):
    if not isinstance(trace, list):
        return 0
    signatures = [_action_signature(step) for step in trace]
    signatures = [sig for sig in signatures if sig]
    return len(signatures) - len(set(signatures))


def _call_with_retry(call_next, question, config):
    result = call_next(question, config)
    attempts = 1
    if not isinstance(result, dict):
        raise TypeError("call_next() must return a result dictionary")
    if result.get("status") in {"wrapper_error", "no_action"}:
        time.sleep(0.15)
        result = call_next(question, config)
        attempts += 1
        if not isinstance(result, dict):
            raise TypeError("call_next() must return a result dictionary")
    return result, attempts


def _priced_model(model):
    """Map OpenRouter-style provider/model IDs to the bundled price table."""
    return str(model or "").split("/", 1)[-1]


def _safe_cost(model, usage):
    if not isinstance(usage, dict):
        return 0.0
    clean_usage = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key, 0)
        clean_usage[key] = value if isinstance(value, (int, float)) else 0
    try:
        return cost_from_usage(_priced_model(model), clean_usage)
    except (TypeError, ValueError):
        return 0.0


def _log(event_type, data):
    if logger is None:
        return
    try:
        logger.log_event(event_type, data)
    except Exception:
        pass


def mitigate(call_next, question, config, context):
    context = context if isinstance(context, dict) else {}
    config = config if isinstance(config, dict) else {}
    correlation_id = str(
        context.get("qid")
        or context.get("session_id")
        or new_correlation_id()
    )
    set_correlation_id(correlation_id)

    safe_question, injection_removed = _sanitize_question(question)
    key = _cache_key(safe_question)
    cache = context.get("cache")
    cache_lock = context.get("cache_lock")

    if cache is not None and cache_lock is not None:
        with cache_lock:
            cached = copy.deepcopy(cache.get(key))
        if cached is not None:
            cached.setdefault("meta", {})["wrapper_cache_hit"] = True
            _log("AGENT_CACHE_HIT", {
                "qid": context.get("qid"),
                "session_id": context.get("session_id"),
                "turn_index": context.get("turn_index"),
                "injection_removed": injection_removed,
            })
            return cached

    started = time.perf_counter()
    try:
        result, attempts = _call_with_retry(
            call_next, safe_question, dict(config)
        )
    except Exception as exc:
        wall_ms = int((time.perf_counter() - started) * 1000)
        _log("WRAPPER_FAILURE", {
            "qid": context.get("qid"),
            "session_id": context.get("session_id"),
            "turn_index": context.get("turn_index"),
            "wall_ms": wall_ms,
            "error_type": type(exc).__name__,
            "error": str(exc),
        })
        return {
            "answer": None,
            "status": "wrapper_error",
            "steps": 0,
            "trace": [],
            "meta": {
                "latency_ms": wall_ms,
                "usage": {},
                "model": config.get("model"),
                "provider": config.get("provider"),
                "tools_used": [],
            },
        }
    wall_ms = int((time.perf_counter() - started) * 1000)

    answer = result.get("answer")
    clean_answer, pii_redactions = redact(answer or "")
    if answer is not None:
        result["answer"] = clean_answer

    meta = result.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    usage = meta.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    trace = result.get("trace")
    trace = trace if isinstance(trace, list) else []
    errors = _walk_errors(trace)

    _log("AGENT_CALL", {
        "qid": context.get("qid"),
        "session_id": context.get("session_id"),
        "turn_index": context.get("turn_index"),
        "status": result.get("status"),
        "steps": result.get("steps"),
        "wall_ms": wall_ms,
        "reported_latency_ms": meta.get("latency_ms"),
        "provider": meta.get("provider"),
        "model": meta.get("model"),
        "usage": usage,
        "cost_usd": _safe_cost(meta.get("model"), usage),
        "tools_used": meta.get("tools_used") or [],
        "tool_errors": errors,
        "repeated_actions": _repeated_actions(trace),
        "pii_redactions": pii_redactions,
        "injection_removed": injection_removed,
        "attempts": attempts,
        "trace": trace,
    })

    if (
        result.get("status") == "ok"
        and cache is not None
        and cache_lock is not None
    ):
        with cache_lock:
            cache[key] = copy.deepcopy(result)

    return result
