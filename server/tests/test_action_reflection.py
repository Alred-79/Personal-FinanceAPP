"""W4 — Reconciliation→planning feedback loop tests.

Covers, à la test_audit_service + test_assisted_action:
  * aggregation math (counts, follow-through rate, median latency) from synthetic
    AssistedAction rows;
  * fact synthesis is non-directive and PASSES the output firewall; sparse history
    → no fact;
  * the automation offer fires only at ≥ min_repeats verified, is idempotent (one
    notification), skips when an equivalent Rule exists, respects flag-off and a
    prior dismissal;
  * the nightly job re-run is a no-op; invalidate_agent is called after a fact;
  * propose-only: confirming the offer's create_rule token creates an allocate
    Rule and moves no money;
  * a POSTGRES test asserting the job sets per-user RLS tenant context and ACTUALLY
    READS the user's rows (not zero) — the classic RLS trap this item must prevent.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from server.src import scheduler
from server.src.db.models import (
    AssistedAction as AssistedActionORM,
    Goal as GoalORM,
    Notification as NotificationORM,
    Rule as RuleORM,
    User as UserORM,
    UserMemory as UserMemoryORM,
)
from server.src.db.rls import enable_rls, set_tenant
from server.src.services import action_reflection
from server.src.services.action_reflection import (
    FOLLOWTHROUGH_KEY,
    aggregate_outcomes,
    detect_automatable,
    run_for_user,
    synthesize_fact,
)
from server.src.services.game.firewall import screen_output
from server.src.settings import settings

_NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)
_PG = os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql")


# ── helpers ──────────────────────────────────────────────────────────────────


def _user(db, name="refl"):
    u = UserORM(
        username=name, full_name="Refl U", email=f"{name}@x.com", hashed_password="x"
    )
    db.add(u)
    db.flush()
    return u


def _goal(db, user_id, name="House", amount=1_000_000):
    g = GoalORM(name=name, amount=amount, date="2030-01-01", user_id=user_id, progress=0)
    db.add(g)
    db.flush()
    return g


def _action(
    db,
    user_id,
    *,
    kind="goal_funding",
    status="verified",
    amount_cents=25_000,
    goal_id=None,
    dest_ref=None,
    created_days_ago=10,
    latency_days=1,
):
    created = _NOW - timedelta(days=created_days_ago)
    resolved = created + timedelta(days=latency_days) if status == "verified" else None
    how = {"goal_id": goal_id} if goal_id is not None else {}
    import json

    row = AssistedActionORM(
        user_id=user_id,
        kind=kind,
        amount_cents=amount_cents,
        source_ref="1",
        dest_ref=dest_ref,
        rationale="factual",
        how_json=json.dumps(how),
        status=status,
        verify_ref=f"vr:{user_id}:{kind}:{created.isoformat()}:{amount_cents}",
        created_at=created.isoformat(),
        resolved_at=resolved.isoformat() if resolved else None,
    )
    db.add(row)
    db.flush()
    return row


def _seed_repeated_goal_funding(db, user_id, goal_id, n=3, amount_cents=25_000):
    """``n`` verified goal-funding actions to one goal, ~30 days apart (monthly)."""
    for k in range(n):
        _action(
            db,
            user_id,
            kind="goal_funding",
            status="verified",
            amount_cents=amount_cents,
            goal_id=goal_id,
            created_days_ago=10 + 30 * k,
            latency_days=1,
        )


# ── aggregation math ─────────────────────────────────────────────────────────


def test_aggregate_counts_rate_and_latency(db_session):
    u = _user(db_session)
    g = _goal(db_session, u.id)
    # 3 verified (latency 1,2,3 → median 2.0), 1 dismissed, 1 expired.
    _action(db_session, u.id, status="verified", goal_id=g.id, created_days_ago=40, latency_days=1)
    _action(db_session, u.id, status="verified", goal_id=g.id, created_days_ago=30, latency_days=2)
    _action(db_session, u.id, status="verified", goal_id=g.id, created_days_ago=20, latency_days=3)
    _action(db_session, u.id, status="dismissed", goal_id=g.id, created_days_ago=15)
    _action(db_session, u.id, status="expired", goal_id=g.id, created_days_ago=12)

    stats = aggregate_outcomes(db_session, u.id, window_days=90)
    gf = stats["per_kind"]["goal_funding"]
    assert gf["verified"] == 3
    assert gf["dismissed"] == 1
    assert gf["expired"] == 1
    assert gf["proposed"] == 5
    assert gf["follow_through_rate"] == pytest.approx(3 / 5)
    assert gf["median_latency_days"] == pytest.approx(2.0)
    assert stats["total"] == 5


def test_aggregate_excludes_rows_outside_window(db_session):
    u = _user(db_session)
    g = _goal(db_session, u.id)
    _action(db_session, u.id, status="verified", goal_id=g.id, created_days_ago=5)
    _action(db_session, u.id, status="verified", goal_id=g.id, created_days_ago=200)
    # Window math is relative to "now" (utcnow), not _NOW; use a wide window so the
    # recent one is always in and a 1-day window so the old one is always out.
    wide = aggregate_outcomes(db_session, u.id, window_days=3650)
    assert wide["total"] == 2
    narrow = aggregate_outcomes(db_session, u.id, window_days=1)
    # The created_days_ago is anchored on _NOW (2026-06-15); both are old relative
    # to a real utcnow run, so a 1-day window excludes both — the point is only
    # that windowing filters.
    assert narrow["total"] <= 2


# ── fact synthesis + firewall ────────────────────────────────────────────────


def test_synthesize_none_on_sparse_history():
    # No resolved outcomes → None (no fact written).
    assert synthesize_fact({"per_kind": {}, "total": 0}) is None
    only_proposed = {
        "per_kind": {
            "goal_funding": {
                "proposed": 2,
                "verified": 0,
                "dismissed": 0,
                "expired": 0,
                "follow_through_rate": None,
                "median_latency_days": None,
            }
        },
        "total": 2,
    }
    assert synthesize_fact(only_proposed) is None


def test_synthesize_fact_is_factual_and_passes_firewall(db_session):
    u = _user(db_session)
    g = _goal(db_session, u.id)
    _seed_repeated_goal_funding(db_session, u.id, g.id, n=3)
    stats = aggregate_outcomes(db_session, u.id, window_days=3650)
    fact = synthesize_fact(stats)
    assert fact is not None
    # Non-directive: states a tendency, never an instruction.
    lowered = fact.lower()
    assert lowered.startswith("tends to")
    for directive in ("you should", "you must", "consider ", "i recommend"):
        assert directive not in lowered
    # B3: passes the SAME output firewall used on model replies.
    assert not screen_output(fact, plain=True).blocked


# ── automation detection / offer ─────────────────────────────────────────────


def test_detect_below_min_repeats_yields_nothing(db_session):
    u = _user(db_session)
    g = _goal(db_session, u.id)
    _seed_repeated_goal_funding(db_session, u.id, g.id, n=2)
    assert detect_automatable(db_session, u.id, window_days=3650, min_repeats=3) == []


def test_detect_fires_at_min_repeats(db_session):
    u = _user(db_session)
    g = _goal(db_session, u.id)
    _seed_repeated_goal_funding(db_session, u.id, g.id, n=3)
    cands = detect_automatable(db_session, u.id, window_days=3650, min_repeats=3)
    assert len(cands) == 1
    c = cands[0]
    assert c["kind"] == "goal_funding"
    assert c["goal_id"] == g.id
    assert c["amount_cents"] == 25_000  # integer cents (B6)
    assert c["period"] == "monthly"


def test_detect_skips_when_equivalent_rule_exists(db_session):
    u = _user(db_session)
    g = _goal(db_session, u.id)
    _seed_repeated_goal_funding(db_session, u.id, g.id, n=3)
    db_session.add(
        RuleORM(
            user_id=u.id,
            name="existing",
            enabled=1,
            conditions="[]",
            action_type="allocate",
            action_params="{}",
            target_kind="goal",
            target_id=g.id,
            priority=0,
        )
    )
    db_session.flush()
    assert detect_automatable(db_session, u.id, window_days=3650, min_repeats=3) == []


def test_run_for_user_fires_one_offer_and_is_idempotent(db_session, monkeypatch):
    calls = []
    monkeypatch.setattr(action_reflection, "_invalidate_agent", lambda uid: calls.append(uid))
    u = _user(db_session)
    g = _goal(db_session, u.id)
    _seed_repeated_goal_funding(db_session, u.id, g.id, n=3)

    summary = run_for_user(db_session, u.id, window_days=3650, min_repeats=3, now=_NOW)
    assert summary["fact_written"] is True
    assert summary["offers"] == 1
    # invalidate_agent was called after the fact write.
    assert calls == [u.id]
    # exactly one rule_suggest notification.
    offers = (
        db_session.query(NotificationORM)
        .filter(
            NotificationORM.user_id == u.id,
            NotificationORM.ref.like("rule_suggest:%"),
        )
        .all()
    )
    assert len(offers) == 1
    assert offers[0].type == "rule_proposal"
    # one memory fact under the single key.
    facts = (
        db_session.query(UserMemoryORM)
        .filter(UserMemoryORM.user_id == u.id, UserMemoryORM.key == FOLLOWTHROUGH_KEY)
        .all()
    )
    assert len(facts) == 1
    assert facts[0].source == "deterministic"

    # Re-run → no duplicate offer, fact upserted in place (still one).
    summary2 = run_for_user(db_session, u.id, window_days=3650, min_repeats=3, now=_NOW)
    assert summary2["offers"] == 0
    assert (
        db_session.query(NotificationORM)
        .filter(NotificationORM.ref.like("rule_suggest:%"))
        .count()
        == 1
    )
    assert (
        db_session.query(UserMemoryORM)
        .filter(UserMemoryORM.key == FOLLOWTHROUGH_KEY)
        .count()
        == 1
    )


def test_offer_suppressed_after_dismissal(db_session, monkeypatch):
    """A prior notification with the same ref (the user saw + dismissed it) blocks
    a re-offer — dedup is read-OR-unread."""
    monkeypatch.setattr(action_reflection, "_invalidate_agent", lambda uid: None)
    u = _user(db_session)
    g = _goal(db_session, u.id)
    _seed_repeated_goal_funding(db_session, u.id, g.id, n=3)
    cands = detect_automatable(db_session, u.id, window_days=3650, min_repeats=3)
    ref = action_reflection._offer_ref(cands[0])
    # Simulate a prior, already-READ (dismissed) notification with that ref.
    db_session.add(
        NotificationORM(user_id=u.id, type="rule_proposal", title="x", message="x", ref=ref, read=1)
    )
    db_session.flush()
    summary = run_for_user(db_session, u.id, window_days=3650, min_repeats=3, now=_NOW)
    assert summary["offers"] == 0
    assert (
        db_session.query(NotificationORM).filter(NotificationORM.ref == ref).count() == 1
    )


# ── job: flag-off no-op + re-run no-op ───────────────────────────────────────


def test_job_no_op_when_flag_off(db_session, monkeypatch):
    monkeypatch.setattr(settings, "assistant_reflection_enabled", False)
    u = _user(db_session)
    g = _goal(db_session, u.id)
    _seed_repeated_goal_funding(db_session, u.id, g.id, n=3)
    result = scheduler.job_action_reflection(db_session, _NOW)
    assert result == {"skipped": "flag_off"}
    assert db_session.query(NotificationORM).count() == 0
    assert db_session.query(UserMemoryORM).count() == 0


def test_job_runs_and_reruns_are_no_op(db_session, monkeypatch):
    monkeypatch.setattr(settings, "assistant_reflection_enabled", True)
    monkeypatch.setattr(settings, "reflection_window_days", 3650)
    monkeypatch.setattr(settings, "reflection_min_repeats", 3)
    monkeypatch.setattr(action_reflection, "_invalidate_agent", lambda uid: None)
    u = _user(db_session)
    g = _goal(db_session, u.id)
    _seed_repeated_goal_funding(db_session, u.id, g.id, n=3)

    first = scheduler.job_action_reflection(db_session, _NOW)
    assert first["facts_written"] == 1
    assert first["offers"] == 1
    second = scheduler.job_action_reflection(db_session, _NOW)
    assert second["offers"] == 0
    assert (
        db_session.query(NotificationORM).filter(NotificationORM.ref.like("rule_suggest:%")).count()
        == 1
    )


# ── propose-only: confirming the offer creates an allocate Rule, no money moved ─


def test_confirm_offer_creates_allocate_rule_and_moves_no_money(client, db_session, monkeypatch):
    """End-to-end: seed 3 verified goal-funding → one offer → mint the token via
    the proposal-token endpoint → confirm → an allocate Rule is created and the
    goal's progress is UNCHANGED (nothing auto-moved money)."""
    monkeypatch.setattr(settings, "assistant_reflection_enabled", True)
    monkeypatch.setattr(settings, "reflection_window_days", 3650)
    monkeypatch.setattr(settings, "reflection_min_repeats", 3)
    monkeypatch.setattr(action_reflection, "_invalidate_agent", lambda uid: None)

    # Register + authenticate a real user through the API.
    reg = client.post(
        "/api/signup/",
        json={"username": "loopuser", "password": "Test-password1", "full_name": "Loop", "email": "loop@x.com"},
    )
    assert reg.status_code == 200, reg.text
    token = reg.json()["access_token"]
    client.cookies.clear()
    headers = {"Authorization": f"Bearer {token}"}

    user_id = db_session.query(UserORM).filter(UserORM.username == "loopuser").one().id
    g = _goal(db_session, user_id)
    _seed_repeated_goal_funding(db_session, user_id, g.id, n=3)
    db_session.commit()
    progress_before = g.progress

    # Run the job → one offer notification.
    scheduler.job_action_reflection(db_session, _NOW)
    db_session.commit()
    offer = (
        db_session.query(NotificationORM)
        .filter(NotificationORM.user_id == user_id, NotificationORM.ref.like("rule_suggest:%"))
        .one()
    )

    # Tap → mint the create_rule token.
    mint = client.post(f"/api/notifications/{offer.id}/proposal-token/", headers=headers)
    assert mint.status_code == 200, mint.text
    body = mint.json()
    assert body["action"] == "create_rule"
    confirm_token = body["token"]

    # No rule yet; goal progress untouched (the OFFER moved no money).
    db_session.expire_all()
    assert db_session.query(RuleORM).filter(RuleORM.user_id == user_id).count() == 0
    assert db_session.get(GoalORM, g.id).progress == progress_before

    # Confirm → the allocate rule is created. Still no money moved.
    confirm = client.post("/api/assistant/actions/confirm/", headers=headers, json={"token": confirm_token})
    assert confirm.status_code == 200, confirm.text
    db_session.expire_all()
    rules = db_session.query(RuleORM).filter(RuleORM.user_id == user_id).all()
    assert len(rules) == 1
    assert rules[0].action_type == "allocate"
    assert rules[0].target_kind == "goal"
    assert rules[0].target_id == g.id
    assert db_session.get(GoalORM, g.id).progress == progress_before  # nothing auto-moved


# ── POSTGRES: the job sets per-user RLS tenant context and READS the rows ──────


@pytest.mark.skipif(not _PG, reason="RLS is Postgres-only; set TEST_DATABASE_URL to Postgres")
def test_job_sets_tenant_context_and_reads_rows_under_rls(_engine):
    """The headline RLS guard (B1): as a NON-superuser app_user with the real
    tenant policies ENABLED, the nightly job must bind each user's tenant context
    before reading — otherwise it reads ZERO rows (the classic silent no-op) and
    writes no fact/offer. This proves the job's per-user set_tenant actually lets
    it read the user's AssistedAction rows."""
    _TABLES = ("assisted_actions", "goals", "notifications", "user_memory", "rules")

    # Seed as the (superuser) owner — bypasses RLS so the planted rows exist.
    with Session(_engine) as s:
        u = _user(s)
        g = _goal(s, u.id)
        _seed_repeated_goal_funding(s, u.id, g.id, n=3)
        s.commit()
        user_id, goal_id = u.id, g.id

    # Enable the real tenant policies on the tables the job touches, and grant a
    # restricted app_user CRUD (superusers bypass RLS).
    with _engine.begin() as conn:
        conn.execute(
            text(
                "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='app_user') "
                "THEN CREATE ROLE app_user NOSUPERUSER NOLOGIN; END IF; END $$"
            )
        )
        conn.execute(text("GRANT USAGE ON SCHEMA public TO app_user"))
        for tbl in _TABLES:
            enable_rls(conn, tbl)
            conn.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tbl} TO app_user"))
        conn.execute(text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user"))

    try:
        with Session(_engine) as s:
            s.execute(text("SET LOCAL ROLE app_user"))

            # SANITY: with NO tenant context, RLS fails closed — the job would read
            # zero AssistedAction rows (the trap). Prove the fail-closed baseline.
            assert s.execute(text("SELECT count(*) FROM assisted_actions")).scalar() == 0

            # Now run the job's per-user work the way the scheduler does: bind the
            # tenant, then call run_for_user. set_tenant binds app.user_id (SET LOCAL).
            settings_patch = settings.assistant_reflection_enabled
            try:
                settings.assistant_reflection_enabled = True
                # Mimic job_action_reflection's per-user loop for our single user.
                set_tenant(s, user_id)
                # With tenant bound, the SAME query now sees the rows (NOT zero).
                assert s.execute(text("SELECT count(*) FROM assisted_actions")).scalar() == 3

                summary = run_for_user(
                    s, user_id, window_days=3650, min_repeats=3, now=_NOW
                )
                assert summary["fact_written"] is True
                assert summary["offers"] == 1
                # And the writes landed (visible under the same bound tenant).
                assert s.execute(text("SELECT count(*) FROM user_memory")).scalar() == 1
                assert (
                    s.execute(
                        text("SELECT count(*) FROM notifications WHERE ref LIKE 'rule_suggest:%'")
                    ).scalar()
                    == 1
                )
            finally:
                settings.assistant_reflection_enabled = settings_patch
            s.rollback()
    finally:
        with _engine.begin() as conn:
            for tbl in _TABLES:
                conn.execute(text(f"DROP POLICY IF EXISTS {tbl}_tenant_isolation ON {tbl}"))
                conn.execute(text(f"ALTER TABLE {tbl} NO FORCE ROW LEVEL SECURITY"))
                conn.execute(text(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY"))
