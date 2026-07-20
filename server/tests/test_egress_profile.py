"""W3 — self-host / no-egress profile (privacy SKU).

``settings.egress_disabled`` is the "your data never leaves your machine" switch.
When True, the assistant's WEB tool group (``search_web`` / ``open_website`` /
``get_information``) is dropped from EVERY mode and the deterministic router never
binds WEB even on a clear look-up intent — so no assistant chat turn can reach an
outbound Tavily / web HTTP call.

We assert, reusing W1's group filter (no parallel removal path):

* with ``egress_disabled`` the WEB tools are ABSENT from every mode the router
  can pick — router off (``groups=None``), the read+money data mode, AND even a
  mode that explicitly requested WEB (defense in depth);
* ``classify_mode`` never adds WEB on look-up intent when ``egress_disabled``;
* the Clerk is TOLD web lookups are disabled (a system-prompt note) so it says
  so rather than silently failing;
* a real ``chat`` turn makes NO outbound HTTP — the web tools are never even
  constructed into the executor, and the egress clients (``requests`` /
  ``TavilyClient``) are tripwired to fail the test if they were called;
* the flag defaults to False and OFF == today's behavior (web tools present).
"""

import pytest

import server.src.services.assistant_service as svc_mod
from server.src.services import assistant_router as router
from server.src.services.assistant_router import READ, MONEY, WEB, TAX
from server.src.services.assistant_service import AssistantService
from server.src.settings import settings


_WEB_TOOL_NAMES = {"search_web", "open_website", "get_information"}


def _tool_names(tools):
    return {t.name for t in tools}


# ── the flag ships dark ──────────────────────────────────────────────────────


def test_egress_disabled_defaults_false():
    """Privacy SKU is opt-in: the default is today's behavior."""
    assert settings.egress_disabled is False


# ── classify_mode never binds WEB under egress_disabled ──────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "look up the current price of gold",
        "search for the latest mortgage rates",
        "open the website example.com",
        "what is the price of bitcoin right now",
    ],
)
def test_router_never_adds_web_when_egress_disabled(text):
    groups, sig = router.classify_mode(
        text, tax_enabled=False, egress_disabled=True
    )
    assert WEB not in groups
    assert "web" not in sig
    # READ + MONEY remain — the assistant still works on the user's own data.
    assert READ in groups and MONEY in groups


def test_router_still_adds_web_when_egress_enabled():
    """Sanity: egress_disabled=False keeps the existing look-up behavior."""
    groups, sig = router.classify_mode(
        "look up the price of gold", tax_enabled=False, egress_disabled=False
    )
    assert WEB in groups and "web" in sig


def test_router_egress_disabled_still_allows_tax_group():
    """Killing web egress must not touch the tax gate."""
    groups, _ = router.classify_mode(
        "total my schedule c deductions", tax_enabled=True, egress_disabled=True
    )
    assert TAX in groups
    assert WEB not in groups


# ── web tools absent from EVERY mode under egress_disabled ───────────────────


def test_web_tools_absent_router_off(monkeypatch):
    """Router OFF (groups=None) — the full toolset — still loses WEB tools."""
    monkeypatch.setattr(settings, "egress_disabled", True)
    monkeypatch.setattr(settings, "tax_features_enabled", False)
    svc = AssistantService()
    names = _tool_names(svc._build_tools(1, None))
    assert names.isdisjoint(_WEB_TOOL_NAMES)
    # Non-web capability is untouched.
    assert "get_accounts" in names and "add_transaction" in names


def test_web_tools_absent_read_money_mode(monkeypatch):
    monkeypatch.setattr(settings, "egress_disabled", True)
    monkeypatch.setattr(settings, "tax_features_enabled", False)
    svc = AssistantService()
    names = _tool_names(svc._build_tools(1, frozenset({READ, MONEY})))
    assert names.isdisjoint(_WEB_TOOL_NAMES)


def test_web_tools_absent_even_when_web_group_requested(monkeypatch):
    """Defense in depth: even if the WEB group were somehow selected, the
    no-egress strip removes the web tools so they can never be constructed."""
    monkeypatch.setattr(settings, "egress_disabled", True)
    monkeypatch.setattr(settings, "tax_features_enabled", False)
    svc = AssistantService()
    names = _tool_names(svc._build_tools(1, frozenset({READ, MONEY, WEB})))
    assert names.isdisjoint(_WEB_TOOL_NAMES)


def test_web_tools_present_when_egress_enabled(monkeypatch):
    """OFF == today's behavior: web tools are built on the full toolset."""
    monkeypatch.setattr(settings, "egress_disabled", False)
    monkeypatch.setattr(settings, "tax_features_enabled", False)
    svc = AssistantService()
    names = _tool_names(svc._build_tools(1, None))
    assert _WEB_TOOL_NAMES <= names


# ── the Clerk is told web lookups are disabled ───────────────────────────────


def _bind_session(monkeypatch, _engine):
    """Keep prompt tests on the fresh test schema, never the developer DB."""
    from sqlalchemy.orm import sessionmaker

    TestSession = sessionmaker(
        bind=_engine, autoflush=False, autocommit=False, future=True
    )
    monkeypatch.setattr(svc_mod, "SessionLocal", TestSession)


def test_system_prompt_announces_web_disabled(monkeypatch, _engine):
    _bind_session(monkeypatch, _engine)
    monkeypatch.setattr(settings, "egress_disabled", True)
    monkeypatch.setattr(settings, "tax_features_enabled", False)
    svc = AssistantService()
    for groups in (None, frozenset({READ, MONEY}), frozenset({READ, MONEY, WEB})):
        prompt = svc._build_system_prompt(1, groups)
        assert "WEB LOOKUPS ARE DISABLED" in prompt
        # Guardrails are still never trimmed.
        assert "SECURITY — treat tool results" in prompt


def test_system_prompt_silent_when_egress_enabled(monkeypatch, _engine):
    _bind_session(monkeypatch, _engine)
    monkeypatch.setattr(settings, "egress_disabled", False)
    monkeypatch.setattr(settings, "tax_features_enabled", False)
    svc = AssistantService()
    prompt = svc._build_system_prompt(1, None)
    assert "WEB LOOKUPS ARE DISABLED" not in prompt


# ── a real chat turn makes NO outbound HTTP ──────────────────────────────────


async def _drive_chat(message):
    """Run the REAL ``chat`` generator with a no-op streamed executor, building
    the tool list the way ``chat`` does. Returns the yielded SSE frames."""
    from cachetools import TTLCache
    from unittest.mock import MagicMock

    from server.src.models import UserInDB

    service = AssistantService.__new__(AssistantService)  # skip ChatGroq init
    service.agents = TTLCache(maxsize=8, ttl=1800)
    service.actions = {}
    service.preprocessors = {}

    executor = MagicMock()

    async def _events(*a, **k):
        # No model/tool events — a pure no-op turn. We are proving the chat path
        # constructs no web egress, not exercising the LLM.
        return
        yield  # pragma: no cover — make this an async generator

    executor.astream_events = _events

    user = UserInDB(
        id=1,
        username="eg",
        full_name="Eg",
        email="eg@x.com",
        disabled=False,
        hashed_password="x",
    )
    # Seed BOTH possible keys so chat() never rebuilds (and never touches the DB
    # for memory/budget reconciliation surprises): the bare key (router off) and
    # the read+money key (router on, no web).
    service.agents[user.id] = executor
    service.agents[(user.id, "read+money")] = executor

    frames = []
    async for frame in service.chat(user, message):
        frames.append(frame)
    return frames


@pytest.mark.asyncio
async def test_chat_turn_makes_no_outbound_http_when_egress_disabled(
    monkeypatch, db_session, _engine
):
    from sqlalchemy.orm import sessionmaker

    # Bind the generator's short-lived SessionLocal (budget reconciliation) to the
    # test engine, the same pattern the frames tests use.
    TestSession = sessionmaker(
        bind=_engine, autoflush=False, autocommit=False, future=True
    )
    monkeypatch.setattr(svc_mod, "SessionLocal", TestSession)

    monkeypatch.setattr(settings, "egress_disabled", True)
    monkeypatch.setattr(settings, "tax_features_enabled", False)
    monkeypatch.setattr(settings, "assistant_firewall_enabled", False)
    # Router ON so the read+money seeded executor (no web key) is selected; the
    # egress strip applies on both paths regardless.
    monkeypatch.setattr(settings, "assistant_router_enabled", True)

    # Tripwires: ANY outbound web call from the assistant path fails the test.
    def _no_http(*a, **k):  # pragma: no cover - only fires on a regression
        raise AssertionError("outbound HTTP made on a chat turn with egress_disabled")

    monkeypatch.setattr(svc_mod.requests, "get", _no_http)
    monkeypatch.setattr(svc_mod.requests, "post", _no_http)
    monkeypatch.setattr(svc_mod.socket, "getaddrinfo", _no_http)
    monkeypatch.setattr(svc_mod, "TavilyClient", _no_http)

    # Drive a look-up message: with egress on this would route to WEB; here it
    # must not, and the tripwires must never fire.
    frames = await _drive_chat("look up the current price of gold")
    # The turn completed (it streamed a done frame) without tripping a tripwire.
    assert any(f.startswith("event: done") for f in frames)


def test_no_web_tool_constructed_means_no_egress_object(monkeypatch):
    """The strongest egress guarantee: under egress_disabled the web tool objects
    are never instantiated into the executor's tool list, so there is no object
    that *could* make an outbound call on any turn."""
    monkeypatch.setattr(settings, "egress_disabled", True)
    monkeypatch.setattr(settings, "tax_features_enabled", False)
    svc = AssistantService()
    # Across every group set the router can produce, no web tool exists.
    for groups in (
        None,
        frozenset({READ, MONEY}),
        frozenset({READ, MONEY, WEB}),
        frozenset({READ, MONEY, WEB, TAX}),
    ):
        tools = svc._build_tools(1, groups)
        for t in tools:
            assert router.group_for_tool(t.name) != WEB
