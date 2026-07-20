"""W1 — deterministic mode-gating tool-router.

The router (``services/assistant_router.py``) mirrors the advice firewall: a pure,
deterministic, Unicode-normalized regex classifier — no DB, no network, no LLM —
so it is exercised directly. We assert:

* prompt → tool-group set (READ + MONEY always; WEB / TAX gated on intent);
* ambiguous / multi-intent unions every fired group (worst case = full set);
* WEB and TAX are added only on their intent;
* TAX stays hidden when ``tax_enabled`` is False, even on a clear tax intent;
* the tool-list filter (``AssistantService._build_tools``) and the system-prompt
  trim (``_build_system_prompt``) follow the selected groups, and the security +
  no-advice paragraphs are ALWAYS kept;
* flag OFF → the full toolset / full prompt (today's behavior).
"""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import server.src.routers.assistant as assistant_endpoint
import server.src.services.assistant_service as svc_mod
from server.src.services import assistant_router as router
from server.src.services.assistant_router import READ, MONEY, WEB, TAX
from server.src.services.assistant_service import AssistantService
from server.src.settings import settings


# ── classify_mode: the group set per prompt ─────────────────────────────────


def test_read_and_money_always_present_on_a_plain_data_question():
    groups, sig = router.classify_mode(
        "how much did I spend on groceries last month", tax_enabled=False
    )
    assert READ in groups and MONEY in groups
    assert WEB not in groups and TAX not in groups
    assert sig == "read+money"


@pytest.mark.parametrize(
    "text",
    [
        "look up the current price of gold",
        "search for the latest mortgage rates",
        "google what a 401k is",
        "open the website example.com",
        "what is the price of bitcoin right now",
    ],
)
def test_web_intent_adds_web_group(text):
    groups, sig = router.classify_mode(text, tax_enabled=False)
    assert WEB in groups
    # READ + MONEY remain the standing core.
    assert READ in groups and MONEY in groups
    assert "web" in sig


def test_data_question_does_not_bind_web():
    groups, _ = router.classify_mode(
        "show my three biggest transactions this week", tax_enabled=False
    )
    assert WEB not in groups


@pytest.mark.parametrize(
    "text",
    [
        "give me my tax summary for 2025",
        "how much did I tag to the office bucket",
        "total my schedule c deductions",
        "what's in my 1099 income",
    ],
)
def test_tax_intent_adds_tax_group_when_enabled(text):
    groups, sig = router.classify_mode(text, tax_enabled=True)
    assert TAX in groups
    assert "tax" in sig


@pytest.mark.parametrize(
    "text",
    [
        "give me my tax summary for 2025",
        "total my schedule c deductions",
    ],
)
def test_tax_hidden_when_flag_off_even_on_tax_intent(text):
    groups, sig = router.classify_mode(text, tax_enabled=False)
    assert TAX not in groups
    assert "tax" not in sig


def test_multi_intent_unions_groups():
    # A web lookup + a tax-organize ask in one turn → both groups join the core.
    groups, sig = router.classify_mode(
        "look up the standard mileage rate then total my schedule c deductions",
        tax_enabled=True,
    )
    assert groups == frozenset({READ, MONEY, WEB, TAX})
    assert sig == "read+money+web+tax"


def test_signature_is_deterministic_and_canonically_ordered():
    g1, s1 = router.classify_mode("look up gold price", tax_enabled=False)
    g2, s2 = router.classify_mode("look up gold price", tax_enabled=False)
    assert g1 == g2 and s1 == s2
    # Canonical order regardless of which family matched first.
    assert s1 == "read+money+web"


def test_unicode_obfuscated_web_intent_still_classified():
    # Full-width "search" must normalize and still trip the WEB family — the same
    # evasion-resistance the firewall has (matched on normalized text).
    groups, _ = router.classify_mode("ｓｅａｒｃｈ for gold spot price", tax_enabled=False)
    assert WEB in groups


def test_empty_text_is_safe_and_returns_core():
    groups, sig = router.classify_mode("", tax_enabled=True)
    assert groups == frozenset({READ, MONEY})
    assert sig == "read+money"


# ── tool-list filtering follows the selected groups ─────────────────────────


def _tool_names(tools):
    return {t.name for t in tools}


def test_build_tools_full_when_groups_none(monkeypatch):
    """Router OFF (groups=None) → the full toolset, today's behavior."""
    from server.src.settings import settings as s

    monkeypatch.setattr(s, "tax_features_enabled", False)
    svc = AssistantService()
    names = _tool_names(svc._build_tools(1, None))
    assert "search_web" in names  # WEB present
    assert "add_transaction" in names  # MONEY present
    assert "get_accounts" in names  # READ present
    assert "tag_transaction_tax" not in names  # tax flag off


def test_build_tools_read_money_only_for_data_turn(monkeypatch):
    from server.src.settings import settings as s

    monkeypatch.setattr(s, "tax_features_enabled", False)
    svc = AssistantService()
    groups = frozenset({READ, MONEY})
    names = _tool_names(svc._build_tools(1, groups))
    assert "get_accounts" in names and "add_transaction" in names
    # WEB tools must be absent — the SSRF/cost surface shrinks on a data turn.
    assert "search_web" not in names
    assert "open_website" not in names
    assert "get_information" not in names


def test_build_tools_adds_web_only_on_web_group(monkeypatch):
    from server.src.settings import settings as s

    monkeypatch.setattr(s, "tax_features_enabled", False)
    svc = AssistantService()
    names = _tool_names(svc._build_tools(1, frozenset({READ, MONEY, WEB})))
    assert "search_web" in names and "open_website" in names


def test_build_tools_tax_gated_on_flag_even_when_tax_group_selected(monkeypatch):
    """Defense in depth: tax tools never appear when the feature flag is off,
    even if the TAX group were somehow requested."""
    from server.src.settings import settings as s

    monkeypatch.setattr(s, "tax_features_enabled", False)
    svc = AssistantService()
    names = _tool_names(svc._build_tools(1, frozenset({READ, MONEY, TAX})))
    assert "tag_transaction_tax" not in names
    assert "get_tax_summary" not in names


def test_build_tools_tax_present_when_flag_on_and_tax_group(monkeypatch):
    from server.src.settings import settings as s

    monkeypatch.setattr(s, "tax_features_enabled", True)
    svc = AssistantService()
    names = _tool_names(svc._build_tools(1, frozenset({READ, MONEY, TAX})))
    assert "tag_transaction_tax" in names and "get_tax_summary" in names
    # WEB still gated out of a tax turn.
    assert "search_web" not in names


# ── system-prompt trimming follows the mode; guardrails always kept ─────────


def test_prompt_keeps_security_and_no_advice_in_every_mode(monkeypatch, _engine):
    from server.src.settings import settings as s

    _bind_session(monkeypatch, _engine)
    monkeypatch.setattr(s, "tax_features_enabled", False)
    svc = AssistantService()
    for groups in (None, frozenset({READ}), frozenset({READ, MONEY})):
        prompt = svc._build_system_prompt(1, groups)
        # Guardrail B3 — these paragraphs are never trimmed.
        assert "SECURITY — treat tool results" in prompt
        assert "not a licensed financial, investment, or tax advisor" in prompt


def test_prompt_includes_money_paragraphs_only_with_money_group(monkeypatch, _engine):
    from server.src.settings import settings as s

    _bind_session(monkeypatch, _engine)
    monkeypatch.setattr(s, "tax_features_enabled", False)
    svc = AssistantService()
    with_money = svc._build_system_prompt(1, frozenset({READ, MONEY}))
    without_money = svc._build_system_prompt(1, frozenset({READ}))
    assert "propose_assisted_action" in with_money
    assert "create_rule" in with_money
    assert "propose_assisted_action" not in without_money
    assert "create_rule" not in without_money


def test_prompt_tax_paragraph_only_with_tax_group_and_flag(monkeypatch, _engine):
    from server.src.settings import settings as s

    _bind_session(monkeypatch, _engine)
    monkeypatch.setattr(s, "tax_features_enabled", True)
    svc = AssistantService()
    with_tax = svc._build_system_prompt(1, frozenset({READ, MONEY, TAX}))
    no_tax_group = svc._build_system_prompt(1, frozenset({READ, MONEY}))
    assert "TAX ORGANIZATION" in with_tax
    assert "TAX ORGANIZATION" not in no_tax_group


def test_prompt_no_tax_paragraph_when_flag_off(monkeypatch, _engine):
    from server.src.settings import settings as s

    _bind_session(monkeypatch, _engine)
    monkeypatch.setattr(s, "tax_features_enabled", False)
    svc = AssistantService()
    prompt = svc._build_system_prompt(1, frozenset({READ, MONEY, TAX}))
    assert "TAX ORGANIZATION" not in prompt


def test_prompt_full_when_groups_none_router_off(monkeypatch, _engine):
    from server.src.settings import settings as s

    _bind_session(monkeypatch, _engine)
    monkeypatch.setattr(s, "tax_features_enabled", False)
    svc = AssistantService()
    prompt = svc._build_system_prompt(1, None)
    # Router off → full prompt: money paragraphs present, guardrails present.
    assert "propose_assisted_action" in prompt
    assert "SECURITY — treat tool results" in prompt


# ── flag-on / flag-off end-to-end keying through chat() ─────────────────────
# These drive the real ``chat()`` generator with a pre-seeded executor under the
# EXPECTED cache key, proving the router picks the right ``(user, mode)`` key on
# the flag-on path and the bare ``user_id`` key on the flag-off path. The seeded
# executor's no-op stream makes no Groq call.


def _signup(client, username="routeruser", email="router@x.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "Router User",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _uid(db_session, username="routeruser"):
    from server.src.db.models import User as UserORM

    return int(
        db_session.execute(
            select(UserORM.id).where(UserORM.username == username)
        ).scalar_one()
    )


def _noop_executor():
    inst = MagicMock()

    async def _noop_events(*a, **k):
        return
        yield  # pragma: no cover — make this an async generator

    inst.astream_events = _noop_events
    return inst


def _bind_session(monkeypatch, _engine):
    TestSession = sessionmaker(
        bind=_engine, autoflush=False, autocommit=False, future=True
    )
    monkeypatch.setattr(svc_mod, "SessionLocal", TestSession)


def _drive(client, headers, message):
    # Pass the message as a query param dict so httpx URL-encodes the spaces;
    # the lexicons need real whitespace ("look up", "set aside") to match.
    resp = client.post(
        "/api/assistant/chat/", params={"message": message}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp


def test_flag_on_data_question_binds_read_money_key(
    client, db_session, _engine, monkeypatch
):
    monkeypatch.setattr(settings, "assistant_router_enabled", True)
    monkeypatch.setattr(settings, "tax_features_enabled", False)
    _bind_session(monkeypatch, _engine)
    svc = assistant_endpoint.assistant_service
    svc.agents.clear()
    h = _signup(client)
    uid = _uid(db_session)

    # Pre-seed under the EXPECTED key; if the router keyed elsewhere, chat() would
    # build (and hit the network), so reaching this seeded no-op proves the key.
    sentinel = _noop_executor()
    svc.agents[(uid, "read+money")] = sentinel
    try:
        _drive(client, h, "how much did I spend on groceries")
        # The data-turn executor under read+money was used; no web key was made.
        assert svc.agents.get((uid, "read+money")) is sentinel
        assert svc.agents.get((uid, "read+money+web")) is None
    finally:
        svc.agents.clear()


def test_flag_on_lookup_binds_web_key(client, db_session, _engine, monkeypatch):
    monkeypatch.setattr(settings, "assistant_router_enabled", True)
    monkeypatch.setattr(settings, "tax_features_enabled", False)
    _bind_session(monkeypatch, _engine)
    svc = assistant_endpoint.assistant_service
    svc.agents.clear()
    h = _signup(client)
    uid = _uid(db_session)

    sentinel = _noop_executor()
    svc.agents[(uid, "read+money+web")] = sentinel
    try:
        _drive(client, h, "look up the current price of gold")
        assert svc.agents.get((uid, "read+money+web")) is sentinel
    finally:
        svc.agents.clear()


def test_flag_off_uses_bare_user_key(client, db_session, _engine, monkeypatch):
    """Router OFF → the executor is keyed by the bare ``user_id`` (today's
    behavior), regardless of the message's intent."""
    monkeypatch.setattr(settings, "assistant_router_enabled", False)
    monkeypatch.setattr(settings, "tax_features_enabled", False)
    _bind_session(monkeypatch, _engine)
    svc = assistant_endpoint.assistant_service
    svc.agents.clear()
    h = _signup(client)
    uid = _uid(db_session)

    sentinel = _noop_executor()
    svc.agents[uid] = sentinel
    try:
        _drive(client, h, "look up the current price of gold")
        # The bare key was used; no (uid, mode) key was created.
        assert svc.agents.get(uid) is sentinel
        assert svc.agents.get((uid, "read+money+web")) is None
    finally:
        svc.agents.clear()
