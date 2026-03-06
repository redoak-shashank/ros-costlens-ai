"""
Tracing helpers for AgentCore Observability.

Uses OpenTelemetry API spans when available (safe no-op fallback otherwise),
plus structured logs so traces remain debuggable even if span export is limited.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from functools import wraps
from typing import Callable

try:
    from opentelemetry import trace as otel_trace
except Exception:  # pragma: no cover - defensive import for runtime variance
    otel_trace = None

logger = logging.getLogger(__name__)
_tracer = otel_trace.get_tracer("agentcore-billing") if otel_trace else None


def trace_operation(operation_name: str):
    """
    Decorator to trace agent operations (tool calls, agent steps, etc).
    
    Usage:
        @trace_operation("supervisor_routing")
        def supervisor_node(state):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()

            with trace_span(operation_name):
                # Log operation start (still useful even when spans are present)
                logger.info(
                    f"[TRACE] {operation_name} - START",
                    extra={
                        "trace.operation": operation_name,
                        "trace.event": "start",
                    },
                )
                print(f"[TRACE] {operation_name} - START", flush=True)

                try:
                    result = func(*args, **kwargs)
                    duration_ms = (time.time() - start_time) * 1000

                    logger.info(
                        f"[TRACE] {operation_name} - COMPLETE ({duration_ms:.0f}ms)",
                        extra={
                            "trace.operation": operation_name,
                            "trace.event": "complete",
                            "trace.duration_ms": duration_ms,
                        },
                    )
                    print(
                        f"[TRACE] {operation_name} - COMPLETE ({duration_ms:.0f}ms)",
                        flush=True,
                    )
                    trace_event("operation.complete", duration_ms=duration_ms)
                    return result

                except Exception as e:
                    duration_ms = (time.time() - start_time) * 1000

                    logger.error(
                        f"[TRACE] {operation_name} - ERROR ({duration_ms:.0f}ms): {e}",
                        extra={
                            "trace.operation": operation_name,
                            "trace.event": "error",
                            "trace.duration_ms": duration_ms,
                            "trace.error": str(e),
                        },
                    )
                    print(f"[TRACE] {operation_name} - ERROR: {e}", flush=True)
                    trace_event(
                        "operation.error",
                        duration_ms=duration_ms,
                        error_type=type(e).__name__,
                        error=str(e),
                    )
                    raise

        return wrapper

    return decorator


@contextmanager
def trace_span(name: str, **attrs):
    """
    Create a best-effort OTEL span for AgentCore trace visibility.

    Falls back to no-op when OTEL tracer is unavailable.
    """
    span = None
    ctx = None
    try:
        if _tracer:
            ctx = _tracer.start_as_current_span(name)
            span = ctx.__enter__()
            for k, v in attrs.items():
                if v is not None:
                    span.set_attribute(f"agent.{k}", v)
        yield span
    finally:
        if ctx:
            ctx.__exit__(None, None, None)


def trace_event(name: str, **attrs):
    """Add an event to current span (if available) and emit structured log."""
    try:
        if otel_trace:
            span = otel_trace.get_current_span()
            if span is not None:
                span.add_event(name, attributes={f"agent.{k}": v for k, v in attrs.items()})
    except Exception:
        # Never let observability break business logic.
        pass

    logger.info(
        f"[TRACE_EVENT] {name}",
        extra={"trace.event_name": name, **{f"trace.{k}": v for k, v in attrs.items()}},
    )


def log_llm_call(model_id: str, prompt_tokens: int = 0, completion_tokens: int = 0):
    """Log LLM invocation for observability."""
    trace_event(
        "llm.call",
        model_id=model_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    logger.info(
        f"[TRACE] LLM call - {model_id}",
        extra={
            "trace.operation": "llm_invocation",
            "trace.model_id": model_id,
            "trace.prompt_tokens": prompt_tokens,
            "trace.completion_tokens": completion_tokens,
        }
    )
    print(f"[TRACE] LLM call - {model_id} ({prompt_tokens + completion_tokens} tokens)", flush=True)


def log_tool_call(tool_name: str, duration_ms: float, success: bool = True):
    """Log tool execution for observability."""
    trace_event(
        "tool.call",
        tool_name=tool_name,
        duration_ms=duration_ms,
        success=success,
    )
    logger.info(
        f"[TRACE] Tool call - {tool_name} ({duration_ms:.0f}ms)",
        extra={
            "trace.operation": "tool_execution",
            "trace.tool_name": tool_name,
            "trace.duration_ms": duration_ms,
            "trace.success": success,
        }
    )
    print(f"[TRACE] Tool call - {tool_name} ({duration_ms:.0f}ms)", flush=True)
