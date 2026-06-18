"""Per-request logging context: ``request_id`` + ``user_id``.

A middleware stamps a ``request_id`` on every HTTP request and the auth
dependency stamps the resolved ``user_id``; both live in ``contextvars`` so any
log line emitted during the request — however deep in the service/query layer —
carries them without threading arguments through every call.

``RequestContextFilter`` injects the current values onto every log record so the
formatter can render them. Outside a request (startup, the scheduler) the values
default to ``"-"``. This is the on-ramp for later observability (Sentry/OTel/
per-tenant cost) — see docs/MULTI-TENANT-DEFERRED.md (Item 5).

Format note: we enrich the existing human-readable line with ``req=`` / ``user=``
fields. Switching to JSON later is a formatter swap only — the context plumbing
here does not change.
"""

import contextvars
import logging

# Default ``"-"`` so a record emitted outside any request still renders cleanly
# and the formatter never KeyErrors on a missing attribute.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)
user_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "user_id", default="-"
)


class RequestContextFilter(logging.Filter):
    """Attach the current request_id / user_id to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.user_id = user_id_var.get()
        return True


def set_user_id(value) -> None:
    """Stamp the authenticated user's id into the request context.

    Called from the auth dependency once a request resolves to a user. Accepts
    None (unauthenticated) which renders as ``"-"``.
    """
    user_id_var.set("-" if value is None else str(value))
