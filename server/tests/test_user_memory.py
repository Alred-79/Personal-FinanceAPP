"""Tests for the learned user-memory store (Pillar 1A).

Exercises the two writer lanes (trusted ``set_user_fact`` and untrusted
``propose_llm_fact``), the PII + firewall gauntlet on the untrusted lane, the
budgeted/pinned-first render, and forget. The service is pure DB-over-session,
so these use the in-memory ``db_session`` fixture directly.
"""

import pytest

from server.src.db.models import User
from server.src.services import user_memory


def _make_user(db, username="memuser") -> int:
    user = User(
        username=username,
        full_name="Mem User",
        email=f"{username}@example.com",
        hashed_password="x",
    )
    db.add(user)
    db.flush()
    return user.id


def test_set_and_render_trusted_fact(db_session):
    uid = _make_user(db_session)
    user_memory.set_user_fact(
        db_session, uid, "savings_intent", "saving for a house by 2028", source="user"
    )
    rendered = user_memory.render_memory(db_session, uid)
    assert "savings_intent" in rendered
    assert "house" in rendered


def test_empty_memory_renders_empty_string(db_session):
    uid = _make_user(db_session)
    assert user_memory.render_memory(db_session, uid) == ""


def test_upsert_overwrites_same_key(db_session):
    uid = _make_user(db_session)
    user_memory.set_user_fact(db_session, uid, "tone_preference", "gentle", source="user")
    user_memory.set_user_fact(db_session, uid, "tone_preference", "blunt", source="user")
    facts = user_memory.get_facts(db_session, uid)
    assert len([f for f in facts if f.key == "tone_preference"]) == 1
    assert facts[0].value == "blunt"


def test_unknown_key_rejected_in_trusted_lane(db_session):
    uid = _make_user(db_session)
    with pytest.raises(user_memory.MemoryError):
        user_memory.set_user_fact(db_session, uid, "not_a_real_key", "x", source="user")


def test_prefix_key_allowed(db_session):
    uid = _make_user(db_session)
    fact = user_memory.set_user_fact(
        db_session, uid, "category_preference:Food", "prefers Food", source="deterministic"
    )
    assert fact.key == "category_preference:Food"


def test_set_user_fact_rejects_llm_source(db_session):
    """The trusted lane must refuse the ``llm`` source; that lane has its own gate."""
    uid = _make_user(db_session)
    with pytest.raises(user_memory.MemoryError):
        user_memory.set_user_fact(
            db_session, uid, "savings_intent", "x", source="llm"
        )


def test_llm_fact_pii_scrubbed_before_persist(db_session):
    """An LLM-extracted fact carrying a secret is scrubbed before it is stored."""
    uid = _make_user(db_session)
    fact = user_memory.propose_llm_fact(
        db_session,
        uid,
        "recurring_note",
        "card 4111 1111 1111 1111 pays the gym",
        confidence=80,
    )
    assert fact is not None
    assert "4111" not in fact.value  # the card number is redacted
    assert fact.source == "llm"


def test_llm_fact_advice_rejected_by_firewall(db_session):
    """A fact that reads as advice trips the firewall and is never stored."""
    uid = _make_user(db_session)
    fact = user_memory.propose_llm_fact(
        db_session,
        uid,
        "savings_intent",
        "you should invest your savings in stocks",
        confidence=90,
    )
    assert fact is None
    assert user_memory.get_facts(db_session, uid) == []


def test_llm_fact_unknown_key_rejected(db_session):
    uid = _make_user(db_session)
    assert (
        user_memory.propose_llm_fact(db_session, uid, "bogus", "x", confidence=50)
        is None
    )


def test_forget_removes_fact(db_session):
    uid = _make_user(db_session)
    user_memory.set_user_fact(db_session, uid, "tone_preference", "blunt", source="user")
    assert user_memory.forget(db_session, uid, "tone_preference") is True
    assert user_memory.get_facts(db_session, uid) == []
    # forgetting a missing key is a no-op, not an error
    assert user_memory.forget(db_session, uid, "tone_preference") is False


def test_pinned_facts_sort_first(db_session):
    uid = _make_user(db_session)
    user_memory.set_user_fact(db_session, uid, "tone_preference", "blunt", source="user")
    user_memory.set_user_fact(
        db_session, uid, "savings_intent", "house fund", source="user", pinned=True
    )
    facts = user_memory.get_facts(db_session, uid)
    assert facts[0].key == "savings_intent"  # pinned wins regardless of recency


def test_render_respects_char_budget(db_session, monkeypatch):
    uid = _make_user(db_session)
    monkeypatch.setattr(user_memory, "MEMORY_RENDER_CHAR_BUDGET", 60)
    user_memory.set_user_fact(db_session, uid, "savings_intent", "a" * 200, source="user")
    user_memory.set_user_fact(db_session, uid, "tone_preference", "blunt", source="user")
    rendered = user_memory.render_memory(db_session, uid)
    assert len(rendered) <= 60 + 10  # budget plus a small line allowance


def test_render_scrubs_on_the_way_out(db_session):
    """Even a deterministic fact derived from user text is scrubbed at render."""
    uid = _make_user(db_session)
    # Bypass write-time scrubbing by inserting directly, to prove render scrubs too.
    from server.src.db.models import UserMemory

    db_session.add(
        UserMemory(
            user_id=uid,
            key="recurring_note",
            value="ssn 123-45-6789",
            source="deterministic",
            confidence=100,
            pinned=0,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )
    )
    db_session.flush()
    rendered = user_memory.render_memory(db_session, uid)
    assert "123-45-6789" not in rendered
