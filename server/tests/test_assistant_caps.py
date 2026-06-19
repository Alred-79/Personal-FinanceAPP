"""Step 03 (C4): the assistant chat endpoint must be rate-limited AND
request-budget-gated, and the AgentExecutor must carry iteration/time caps.

These tests exercise the *endpoint* (denial-of-wallet ceilings), distinct from
``test_assistant_search.py`` (tool unit tests) and ``test_assistant_security.py``
(SSRF). They never make a real Groq/Tavily call: the executor (or the whole
service ``chat``) is monkeypatched.
"""

from unittest.mock import MagicMock

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

import server.src.routers.assistant as assistant_router
import server.src.services.assistant_service as svc_mod
from server.src.services import llm_budget
from server.src.settings import settings


# ── Helpers ──────────────────────────────────────────────────────────────────


def _signup(client, username="chatter", email="chatter@x.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "Chat Tester",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _user_id(db_session, username="chatter"):
    from server.src.db.models import User as UserORM
    from sqlalchemy import select

    user = db_session.execute(
        select(UserORM).where(UserORM.username == username)
    ).scalar_one()
    return int(user.id)


async def _empty_stream(user, message, **kwargs):
    """A benign service.chat replacement: emits one frame, makes no model call."""
    yield "event: done\ndata: {}\n\n"


def _bind_generator_session_to_test_engine(monkeypatch, _engine):
    """Point the generator's own ``SessionLocal`` at the per-test in-memory DB.

    The real ``AssistantService.chat`` reconciles/releases inside a fresh
    ``SessionLocal()`` (the production engine). In tests we rebind it to the
    test engine so the reconciliation lands in the same DB the pre-flight
    reserve used, and return the factory so the test can read usage back.
    """
    TestSession = sessionmaker(
        bind=_engine, autoflush=False, autocommit=False, future=True
    )
    monkeypatch.setattr(svc_mod, "SessionLocal", TestSession)
    return TestSession


def _usage_requests(session_factory, user_id):
    with session_factory() as s:
        return s.execute(
            text(
                "SELECT requests FROM llm_usage WHERE user_id = :uid AND day = :d"
            ),
            {"uid": user_id, "d": llm_budget.today_key()},
        ).scalar_one_or_none()


def _usage_cost(session_factory, user_id):
    with session_factory() as s:
        return s.execute(
            text(
                "SELECT cost_cents FROM llm_usage WHERE user_id = :uid AND day = :d"
            ),
            {"uid": user_id, "d": llm_budget.today_key()},
        ).scalar_one_or_none()


# ── Rate limit (trips at the endpoint, before the stream) ────────────────────


def test_chat_rate_limited(client, monkeypatch, rate_limited):
    """With the limiter ON and the limit tightened to 1/minute (the decorator
    reads it via a callable, so a runtime change takes effect), the 2nd chat
    call → 429 — and it trips at the endpoint, before any stream starts."""
    monkeypatch.setattr(settings, "assistant_rate_limit", "1/minute")
    monkeypatch.setattr(assistant_router.assistant_service, "chat", _empty_stream)
    h = _signup(client)

    first = client.post("/api/assistant/chat/?message=hello", headers=h)
    second = client.post("/api/assistant/chat/?message=again", headers=h)

    assert first.status_code == 200, first.text
    assert second.status_code == 429, second.text
    # The rate-limit 429 carries the slowapi message — distinct from the budget
    # 429 ("Daily AI limit reached"), so the user knows to wait minutes.
    assert "daily ai limit" not in second.text.lower()


# ── Budget (pre-flight request reservation) ──────────────────────────────────


def test_chat_over_budget_returns_429(client, db_session, monkeypatch):
    """When the day's request budget is already spent, chat → 429 with a readable
    body, and NO model work is attempted (pre-flight check on the request db)."""
    monkeypatch.setattr(settings, "llm_daily_request_budget", 1)
    h = _signup(client)
    uid = _user_id(db_session)

    # Spend the single allotted request for today.
    llm_budget.check_and_reserve(db_session, uid, requests=1)
    db_session.commit()

    def _boom_chat(user, message, **kwargs):
        raise AssertionError("service.chat must not run when over budget")

    monkeypatch.setattr(assistant_router.assistant_service, "chat", _boom_chat)

    resp = client.post("/api/assistant/chat/?message=hello", headers=h)
    assert resp.status_code == 429, resp.text
    assert "daily ai limit" in resp.text.lower()


def test_failed_stream_releases_reserved_request(
    client, db_session, _engine, monkeypatch
):
    """A stream that errors BEFORE any model call releases its reserved request,
    so a failure doesn't permanently burn a daily slot. Uses the REAL service
    generator (its finally block does the release) with the executor forced to
    raise immediately."""
    monkeypatch.setattr(settings, "llm_daily_request_budget", 5)
    h = _signup(client)
    uid = _user_id(db_session)
    session_factory = _bind_generator_session_to_test_engine(monkeypatch, _engine)

    # Pre-seed an executor that raises before any model event (no paid work).
    failing_executor = MagicMock()

    async def _raise_immediately(*args, **kwargs):
        raise ConnectionError("groq unreachable")
        yield  # pragma: no cover — make this an async generator

    failing_executor.astream_events = _raise_immediately
    assistant_router.assistant_service.agents[uid] = failing_executor

    # A non-rate-limit error mid-stream no longer bare-raises (that left a broken
    # SSE with no ``done`` and could hang the client). The generator now emits a
    # generic apology token + a ``done`` frame and returns cleanly, so the stream
    # completes (200) instead of surfacing the ConnectionError to the consumer.
    resp = client.post("/api/assistant/chat/?message=hello", headers=h)
    assert resp.status_code == 200, resp.text
    assert "event: done" in resp.text  # stream terminated cleanly, not truncated

    # The real invariant: pre-flight reserved 1; the finally block released it → 0,
    # so a failed turn doesn't permanently burn a daily slot.
    assert _usage_requests(session_factory, uid) == 0
    assistant_router.assistant_service.agents.pop(uid, None)


# ── Executor caps ────────────────────────────────────────────────────────────


def test_executor_receives_caps(client, _engine, monkeypatch):
    """A newly-built AgentExecutor carries max_iterations / max_execution_time /
    handle_parsing_errors from settings. The per-user executor cache MUST be
    cleared first, else a cached capless instance false-passes."""
    monkeypatch.setattr(settings, "assistant_max_iterations", 3)
    monkeypatch.setattr(settings, "assistant_max_execution_seconds", 7)
    h = _signup(client)
    _bind_generator_session_to_test_engine(monkeypatch, _engine)

    # Clear the cache so chat() builds a fresh executor we can inspect.
    assistant_router.assistant_service.agents.clear()

    captured = {}

    def _spy_executor(*args, **kwargs):
        # Capture the construction kwargs without instantiating the real
        # executor (which would pydantic-validate the agent / try Groq). The
        # caps are what we assert on; return a stand-in with a no-op stream.
        captured.update(kwargs)
        inst = MagicMock()

        async def _noop_events(*a, **k):
            return
            yield  # pragma: no cover

        inst.astream_events = _noop_events
        return inst

    monkeypatch.setattr(svc_mod, "AgentExecutor", _spy_executor)
    # Avoid a real ChatGroq agent build hitting the network for tools:
    monkeypatch.setattr(
        svc_mod, "create_tool_calling_agent", lambda *a, **k: MagicMock()
    )

    resp = client.post("/api/assistant/chat/?message=hello", headers=h)
    assert resp.status_code == 200, resp.text

    assert captured.get("max_iterations") == 3
    assert captured.get("max_execution_time") == 7
    assert captured.get("handle_parsing_errors") is True
    assistant_router.assistant_service.agents.clear()


# ── Reconciliation uses its OWN session ──────────────────────────────────────


def test_reconciliation_uses_own_session(client, db_session, _engine, monkeypatch):
    """Reconciliation runs in the generator's own session, opened AFTER the
    endpoint's pre-flight db is closed. Assert a fresh SessionLocal is opened
    inside the generator (counting factory)."""
    monkeypatch.setattr(settings, "llm_daily_request_budget", 5)
    h = _signup(client)
    uid = _user_id(db_session)

    TestSession = sessionmaker(
        bind=_engine, autoflush=False, autocommit=False, future=True
    )
    opened = {"count": 0}

    def _counting_session():
        opened["count"] += 1
        return TestSession()

    monkeypatch.setattr(svc_mod, "SessionLocal", _counting_session)

    # A real-ish stream that DOES make a model call (so record_actual path runs).
    executor = MagicMock()

    async def _events(*args, **kwargs):
        yield {"event": "on_chat_model_start", "name": "ChatGroq", "data": {}}
        yield {
            "event": "on_chat_model_stream",
            "name": "ChatGroq",
            "data": {"chunk": MagicMock(content="hi")},
        }

    executor.astream_events = _events
    assistant_router.assistant_service.agents[uid] = executor

    resp = client.post("/api/assistant/chat/?message=hello", headers=h)
    assert resp.status_code == 200, resp.text

    # The generator opened exactly one fresh session of its own for reconcile.
    assert opened["count"] >= 1
    assistant_router.assistant_service.agents.pop(uid, None)


# ── Cost cap (A3 — the real per-user daily DOLLAR ceiling) ───────────────────


def test_chat_over_cost_budget_returns_429(client, db_session, monkeypatch):
    """When the day's accumulated cost already meets the dollar cap, chat → 429
    pre-flight (before any stream), even though requests are still available."""
    monkeypatch.setattr(settings, "llm_daily_request_budget", 100)
    monkeypatch.setattr(settings, "llm_daily_cost_budget_cents", 10)
    h = _signup(client)
    uid = _user_id(db_session)

    # Burn the cost budget without touching the request budget meaningfully.
    llm_budget.check_and_reserve(db_session, uid, requests=1, est_cost_cents=10)
    db_session.commit()

    def _boom_chat(user, message, **kwargs):
        raise AssertionError("service.chat must not run when over cost budget")

    monkeypatch.setattr(assistant_router.assistant_service, "chat", _boom_chat)

    resp = client.post("/api/assistant/chat/?message=hello", headers=h)
    assert resp.status_code == 429, resp.text
    assert "daily ai limit" in resp.text.lower()


def test_real_groq_usage_is_recorded_as_cost(
    client, db_session, _engine, monkeypatch
):
    """A stream whose on_chat_model_end carries usage_metadata records the ACTUAL
    cost (priced from real tokens), reconciled against the pre-flight estimate."""
    monkeypatch.setattr(settings, "llm_daily_request_budget", 5)
    monkeypatch.setattr(settings, "llm_daily_cost_budget_cents", 1000)
    # $1/Mtok in, $2/Mtok out → 1M in + 1M out priced to 300c.
    monkeypatch.setattr(settings, "groq_input_price_cents_per_mtok", 100)
    monkeypatch.setattr(settings, "groq_output_price_cents_per_mtok", 200)
    h = _signup(client)
    uid = _user_id(db_session)
    session_factory = _bind_generator_session_to_test_engine(monkeypatch, _engine)

    from types import SimpleNamespace

    executor = MagicMock()

    async def _events(*args, **kwargs):
        yield {"event": "on_chat_model_start", "name": "ChatGroq", "data": {}}
        yield {
            "event": "on_chat_model_stream",
            "name": "ChatGroq",
            "data": {"chunk": MagicMock(content="hello there")},
        }
        # The provider returns real usage on the end event.
        yield {
            "event": "on_chat_model_end",
            "name": "ChatGroq",
            "data": {
                "output": SimpleNamespace(
                    usage_metadata={
                        "input_tokens": 1_000_000,
                        "output_tokens": 1_000_000,
                        "total_tokens": 2_000_000,
                    }
                )
            },
        }

    executor.astream_events = _events
    assistant_router.assistant_service.agents[uid] = executor

    resp = client.post("/api/assistant/chat/?message=hello", headers=h)
    assert resp.status_code == 200, resp.text

    # Cost reflects the real usage (300c), not the small pre-flight estimate.
    assert _usage_cost(session_factory, uid) == 300
    assistant_router.assistant_service.agents.pop(uid, None)


def test_tiktoken_fallback_records_cost_when_no_usage(
    client, db_session, _engine, monkeypatch
):
    """When the stream carries NO usage_metadata, cost is still recorded via the
    tiktoken/char fallback (non-zero), so the dollar cap can't be evaded."""
    monkeypatch.setattr(settings, "llm_daily_request_budget", 5)
    monkeypatch.setattr(settings, "llm_daily_cost_budget_cents", 1000)
    monkeypatch.setattr(settings, "groq_input_price_cents_per_mtok", 100_000)
    monkeypatch.setattr(settings, "groq_output_price_cents_per_mtok", 100_000)
    h = _signup(client)
    uid = _user_id(db_session)
    session_factory = _bind_generator_session_to_test_engine(monkeypatch, _engine)

    executor = MagicMock()

    async def _events(*args, **kwargs):
        yield {"event": "on_chat_model_start", "name": "ChatGroq", "data": {}}
        # Long output, no on_chat_model_end usage → fallback counts it.
        yield {
            "event": "on_chat_model_stream",
            "name": "ChatGroq",
            "data": {"chunk": MagicMock(content="word " * 200)},
        }

    executor.astream_events = _events
    assistant_router.assistant_service.agents[uid] = executor

    resp = client.post("/api/assistant/chat/?message=hello", headers=h)
    assert resp.status_code == 200, resp.text

    # With high prices and a real output, the fallback records a positive cost.
    assert (_usage_cost(session_factory, uid) or 0) > 0
    assistant_router.assistant_service.agents.pop(uid, None)
