"""OpenTelemetry setup for the chat backend (ADR-0009).

Exports to Application Insights when APPLICATIONINSIGHTS_CONNECTION_STRING is set and is a
no-op otherwise, so local runs need nothing. Message content is never recorded.
"""

import contextvars
import os

from opentelemetry import trace
from opentelemetry.trace import Span

_enabled = False
current_turn: contextvars.ContextVar[Span | None] = contextvars.ContextVar("current_turn", default=None)


def setup() -> None:
    global _enabled
    if not os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        return
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(logger_name="fcc")
    _enabled = True


def tracer() -> trace.Tracer:
    return trace.get_tracer("fcc.chat")


def start_turn(member_id: str) -> Span:
    span = tracer().start_span("chat_turn", attributes={"member_id": member_id})
    current_turn.set(span)
    return span


def child(name: str, **attrs) -> Span:
    """Child of the current turn. Ended by the caller; never attached to the context."""
    parent = current_turn.get()
    ctx = trace.set_span_in_context(parent) if parent else None
    return tracer().start_span(name, context=ctx, attributes=attrs)


def traceparent() -> str | None:
    """W3C header so agent-side telemetry can join this turn's trace."""
    span = current_turn.get()
    if not span:
        return None
    sc = span.get_span_context()
    if not sc.is_valid:
        return None
    return f"00-{sc.trace_id:032x}-{sc.span_id:016x}-{int(sc.trace_flags):02x}"


def finish(span: Span, error: bool = False, **attrs) -> None:
    for key, value in attrs.items():
        if value is not None:
            span.set_attribute(key, value if not isinstance(value, list) else ",".join(value))
    if error:
        span.set_status(trace.StatusCode.ERROR)
    span.end()
