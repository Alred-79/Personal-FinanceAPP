"""WS5 — per-request logging context (request_id + user_id).

Covers the edge cases the multi-tenant readiness brief calls for: default values
outside a request, set_user_id (incl. None), contextvar isolation across
concurrent async tasks, and the middleware stamping/echoing X-Request-ID on both
unauthenticated and provided-id requests.
"""

import asyncio
import logging

import pytest

from server.src.logging_context import (
    RequestContextFilter,
    request_id_var,
    set_user_id,
    user_id_var,
)


def _record() -> logging.LogRecord:
    return logging.LogRecord(
        name="t", level=logging.INFO, pathname=__file__, lineno=1,
        msg="m", args=(), exc_info=None,
    )


def test_filter_defaults_outside_request():
    """Outside any request the filter injects the '-' defaults (no KeyError when
    the formatter renders request_id/user_id)."""
    rec = _record()
    assert RequestContextFilter().filter(rec) is True
    assert rec.request_id == "-"
    assert rec.user_id == "-"


def test_set_user_id_and_none():
    token = user_id_var.set("-")
    try:
        set_user_id(42)
        assert user_id_var.get() == "42"
        set_user_id(None)
        assert user_id_var.get() == "-"
    finally:
        user_id_var.reset(token)


def test_filter_reflects_current_context():
    rid_tok = request_id_var.set("abc123")
    uid_tok = user_id_var.set("7")
    try:
        rec = _record()
        RequestContextFilter().filter(rec)
        assert rec.request_id == "abc123"
        assert rec.user_id == "7"
    finally:
        request_id_var.reset(rid_tok)
        user_id_var.reset(uid_tok)


@pytest.mark.asyncio
async def test_concurrent_tasks_get_isolated_context():
    """Two concurrent tasks must not see each other's request_id — each asyncio
    task runs with its own contextvar snapshot (the property the middleware
    relies on to skip an explicit reset)."""
    seen = {}

    async def worker(name: str):
        request_id_var.set(name)
        await asyncio.sleep(0)  # force interleave
        seen[name] = request_id_var.get()

    await asyncio.gather(worker("req-A"), worker("req-B"))
    assert seen == {"req-A": "req-A", "req-B": "req-B"}


def test_middleware_stamps_request_id_header(client):
    """An unauthenticated request still flows through the middleware and gets an
    X-Request-ID echoed back."""
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID")


def test_middleware_honors_inbound_request_id(client):
    resp = client.get("/openapi.json", headers={"X-Request-ID": "client-supplied-id"})
    assert resp.headers.get("X-Request-ID") == "client-supplied-id"
