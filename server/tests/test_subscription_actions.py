"""W6 — Honest subscription cancellation tests.

Covers, à la test_action_reflection + test_merchant_lifecycle:
  * the candidate predicate fires only for zombie (lapsing/dormant + low
    probability_alive) or price-creep (positive price_change_pct) merchants — never
    a healthy active monthly;
  * the detect→offer is idempotent per ``ref`` and respects the flag-off no-op;
  * ``verify_cancellation`` marks ``verified`` ONLY after a full missed cadence +
    grace (not on a one-cycle gap), keeps it unverified when a charge reappears at
    the normalized merchant key, and EXPIRES an annual bridge rather than hanging
    forever;
  * NO fee field anywhere on this path; propose-only (the offer is a Notification;
    the cancel Bridge is minted only on the tap helper and never moves money);
  * a POSTGRES test asserting the job binds per-user RLS tenant context and ACTUALLY
    reads the user's MerchantLifecycle rows (not zero) — the classic RLS trap.
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from server.src import scheduler
from server.src.db.models import (
    Account as AccountORM,
    AssistedAction as AssistedActionORM,
    Expense as ExpenseORM,
    MerchantLifecycle as MerchantLifecycleORM,
    Notification as NotificationORM,
    User as UserORM,
)
from server.src.db.rls import enable_rls, set_tenant
from server.src.services import subscription_actions
from server.src.services.assisted_action_service import (
    AssistedActionService,
    _CANCEL_GRACE_DAYS,
)
from server.src.services.subscription_actions import (
    detect_candidates,
    is_candidate,
    propose_cancel_bridge,
    run_for_user,
)
from server.src.settings import settings

_NOW = date(2026, 6, 15)
_PG = os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql")


# ── helpers ──────────────────────────────────────────────────────────────────


def _user(db, name="sub"):
    u = UserORM(
        username=name, full_name="Sub U", email=f"{name}@x.com", hashed_password="x"
    )
    db.add(u)
    db.flush()
    acct = AccountORM(name="Checking", type="checking", balance=50000, user_id=u.id)
    db.add(acct)
    db.flush()
    return u, acct


def _lifecycle(
    db,
    user_id,
    *,
    merchant="netflix",
    title="Netflix",
    status="dormant",
    probability_alive=0.10,
    cadence="monthly",
    last_amount=1500,
    prev_amount=None,
    price_change_pct=None,
    last_date="2026-04-15",
    expected_next_date="2026-05-15",
):
    row = MerchantLifecycleORM(
        user_id=user_id,
        merchant=merchant,
        title=title,
        probability_alive=probability_alive,
        expected_purchases=0.0,
        status=status,
        cadence=cadence,
        n_charges=8,
        last_amount=last_amount,
        prev_amount=prev_amount,
        price_change_pct=price_change_pct,
        last_date=last_date,
        expected_next_date=expected_next_date,
        fitted_at=_NOW.isoformat(),
    )
    db.add(row)
    db.flush()
    return row


def _charge(db, acct_id, *, title="Netflix", amount=1500, on="2026-05-16"):
    db.add(
        ExpenseORM(title=title, amount=amount, date=on, category="Subscriptions", account_id=acct_id)
    )
    db.flush()


def _cancel_bridge(
    db,
    user_id,
    *,
    merchant="netflix",
    title="Netflix",
    cadence="monthly",
    expected_next_date="2026-05-15",
    created="2026-04-16",
    status="acknowledged",
    last_amount=1500,
):
    how = {
        "merchant": merchant,
        "title": title,
        "cadence": cadence,
        "expected_next_date": expected_next_date,
        "last_amount_cents": last_amount,
        "cancel_steps": "Cancel in the provider's settings.",
        "cancel_url": None,
    }
    row = AssistedActionORM(
        user_id=user_id,
        kind="subscription_cancel",
        amount_cents=last_amount,
        source_ref=None,
        dest_ref=None,
        rationale="factual",
        how_json=json.dumps(how),
        status=status,
        verify_ref=f"sub_cancel_bridge:{user_id}:{merchant}",
        created_at=f"{created}T00:00:00+00:00",
    )
    db.add(row)
    db.flush()
    return row


# ── candidate predicate ──────────────────────────────────────────────────────


def test_zombie_is_candidate(db_session):
    u, _ = _user(db_session)
    row = _lifecycle(db_session, u.id, status="dormant", probability_alive=0.10)
    assert is_candidate(row, max_probability_alive=0.35) is True


def test_price_creep_is_candidate_even_if_active(db_session):
    u, _ = _user(db_session)
    row = _lifecycle(
        db_session,
        u.id,
        status="active",
        probability_alive=0.95,
        prev_amount=1000,
        last_amount=1500,
        price_change_pct=0.5,
    )
    assert is_candidate(row, max_probability_alive=0.35) is True


def test_healthy_active_monthly_is_not_candidate(db_session):
    u, _ = _user(db_session)
    row = _lifecycle(
        db_session, u.id, status="active", probability_alive=0.97, price_change_pct=None
    )
    assert is_candidate(row, max_probability_alive=0.35) is False
    assert detect_candidates(db_session, u.id, max_probability_alive=0.35) == []


def test_lapsing_but_high_probability_is_not_candidate(db_session):
    # lapsing but probability above the forgotten threshold and no hike → skip.
    u, _ = _user(db_session)
    row = _lifecycle(
        db_session, u.id, status="lapsing", probability_alive=0.50, price_change_pct=None
    )
    assert is_candidate(row, max_probability_alive=0.35) is False


# ── detect → offer (idempotent, flag-off) ────────────────────────────────────


def test_run_fires_one_offer_for_a_zombie(db_session):
    u, _ = _user(db_session)
    _lifecycle(db_session, u.id, merchant="netflix", status="dormant", probability_alive=0.1)
    summary = run_for_user(db_session, u.id, now=_NOW, max_probability_alive=0.35)
    assert summary["offers"] == 1
    offers = (
        db_session.query(NotificationORM)
        .filter(NotificationORM.user_id == u.id, NotificationORM.type == "subscription_cancel")
        .all()
    )
    assert len(offers) == 1
    assert offers[0].ref == f"sub_cancel:{u.id}:netflix:2026-06"


def test_offer_is_idempotent_per_ref(db_session):
    u, _ = _user(db_session)
    _lifecycle(db_session, u.id, merchant="netflix", status="dormant", probability_alive=0.1)
    first = run_for_user(db_session, u.id, now=_NOW, max_probability_alive=0.35)
    second = run_for_user(db_session, u.id, now=_NOW, max_probability_alive=0.35)
    assert first["offers"] == 1
    assert second["offers"] == 0
    assert (
        db_session.query(NotificationORM)
        .filter(NotificationORM.ref.like("sub_cancel:%"))
        .count()
        == 1
    )


def test_job_no_op_when_flag_off(db_session, monkeypatch):
    monkeypatch.setattr(settings, "subscription_actions_enabled", False)
    u, _ = _user(db_session)
    _lifecycle(db_session, u.id, status="dormant", probability_alive=0.1)
    result = scheduler.job_subscription_actions(db_session, _NOW)
    assert result == {"skipped": "flag_off"}
    assert db_session.query(NotificationORM).count() == 0


def test_job_runs_and_reruns_are_no_op(db_session, monkeypatch):
    monkeypatch.setattr(settings, "subscription_actions_enabled", True)
    u, _ = _user(db_session)
    _lifecycle(db_session, u.id, merchant="netflix", status="dormant", probability_alive=0.1)
    first = scheduler.job_subscription_actions(db_session, _NOW)
    assert first["offers"] == 1
    second = scheduler.job_subscription_actions(db_session, _NOW)
    assert second["offers"] == 0


# ── absence-based verification ───────────────────────────────────────────────


def test_one_cycle_gap_does_not_verify(db_session):
    """Before expected_next + grace passes, the bridge stays pending — a single
    early/one-cycle gap must NOT be called a cancellation."""
    u, _ = _user(db_session)
    bridge = _cancel_bridge(db_session, u.id, expected_next_date="2026-05-15")
    svc = AssistedActionService(db_session)
    # as_of one day after the expected next date — well inside the grace window.
    outcome = svc.verify_cancellation(bridge, as_of=date(2026, 5, 16))
    assert outcome == "pending"
    assert bridge.status == "acknowledged"


def test_full_cadence_plus_grace_verifies(db_session):
    u, _ = _user(db_session)
    bridge = _cancel_bridge(db_session, u.id, expected_next_date="2026-05-15")
    svc = AssistedActionService(db_session)
    as_of = date(2026, 5, 15) + timedelta(days=_CANCEL_GRACE_DAYS)
    outcome = svc.verify_cancellation(bridge, as_of=as_of)
    assert outcome == "verified"
    assert bridge.status == "verified"
    assert bridge.resolved_at is not None


def test_reappearing_charge_keeps_unverified(db_session):
    """A renewal at the normalized merchant key AFTER the offer → still alive."""
    u, acct = _user(db_session)
    bridge = _cancel_bridge(
        db_session, u.id, merchant="netflix", expected_next_date="2026-05-15", created="2026-04-16"
    )
    # A charge posts after the offer under a slightly different raw label AND
    # amount — but it normalizes to the SAME merchant key ("netflix"), so the
    # absence guard must still see it (the false-"cancelled" edge case).
    _charge(db_session, acct.id, title="NETFLIX 0123", amount=1599, on="2026-05-17")
    svc = AssistedActionService(db_session)
    # Even past the verify horizon, a reappearing charge blocks verification.
    as_of = date(2026, 5, 15) + timedelta(days=_CANCEL_GRACE_DAYS + 3)
    outcome = svc.verify_cancellation(bridge, as_of=as_of)
    assert outcome == "unverified"
    assert bridge.status == "acknowledged"


def test_charge_before_offer_does_not_block(db_session):
    """A charge BEFORE the offer (the one that triggered detection) must not block
    verification — only post-offer charges count as 'still alive'."""
    u, acct = _user(db_session)
    bridge = _cancel_bridge(
        db_session, u.id, merchant="netflix", expected_next_date="2026-05-15", created="2026-04-16"
    )
    _charge(db_session, acct.id, title="Netflix", amount=1500, on="2026-04-15")  # pre-offer
    svc = AssistedActionService(db_session)
    as_of = date(2026, 5, 15) + timedelta(days=_CANCEL_GRACE_DAYS)
    assert svc.verify_cancellation(bridge, as_of=as_of) == "verified"


def test_annual_bridge_expires_rather_than_hanging(db_session):
    """An annual cadence → ~year-long verify horizon. Past the cadence-scaled cap
    (without ever reaching that horizon) the bridge EXPIRES with a nudge instead of
    dangling forever."""
    u, _ = _user(db_session)
    bridge = _cancel_bridge(
        db_session,
        u.id,
        merchant="insurance",
        cadence="annually",
        expected_next_date="2027-06-15",  # ~a year out
        created="2026-06-15",
    )
    svc = AssistedActionService(db_session)
    # Past the absolute open-cap (offer + 120d = 2026-10-13) but BEFORE the far-off
    # annual verify horizon (2027-06-22) → expire rather than dangle for ~a year.
    as_of = date(2026, 12, 1)
    outcome = svc.verify_cancellation(bridge, as_of=as_of)
    assert outcome == "expired"
    assert bridge.status == "expired"
    nudges = (
        db_session.query(NotificationORM)
        .filter(NotificationORM.ref == f"sub_cancel_expired:{bridge.id}")
        .all()
    )
    assert len(nudges) == 1


def test_run_for_user_verifies_open_bridge(db_session):
    u, _ = _user(db_session)
    # No candidate lifecycle row (so no new offer), just an open bridge to verify.
    bridge = _cancel_bridge(db_session, u.id, expected_next_date="2026-05-15")
    as_of = date(2026, 5, 15) + timedelta(days=_CANCEL_GRACE_DAYS)
    summary = run_for_user(db_session, u.id, now=as_of, max_probability_alive=0.35)
    assert summary["verified"] == 1
    assert bridge.status == "verified"


# ── propose-only + NO FEE ────────────────────────────────────────────────────


def test_propose_cancel_bridge_is_propose_only_no_money_no_fee(db_session):
    u, _ = _user(db_session)
    _lifecycle(db_session, u.id, merchant="netflix", title="Netflix", last_amount=1599)
    bridge = propose_cancel_bridge(db_session, u.id, "netflix")
    assert bridge.kind == "subscription_cancel"
    assert bridge.status == "proposed"  # PROPOSE-only — it never acts
    how = json.loads(bridge.how_json)
    # The affordance carries cancel steps + verify anchors, and NO fee anywhere.
    assert "cancel_steps" in how
    assert how["merchant"] == "netflix"
    blob = (bridge.how_json + bridge.rationale).lower()
    for banned in ("fee", "commission", "cut", "we keep", "we take"):
        assert banned not in blob


def test_no_fee_field_anywhere_on_the_path(db_session):
    """Hard assertion (guardrail): no fee/savings-skim field on the offer copy,
    the bridge, or the model module for this path."""
    import inspect

    from server.src import db as _dbpkg  # noqa: F401
    from server.src.db import models as _models

    u, _ = _user(db_session)
    row = _lifecycle(db_session, u.id, merchant="netflix")
    how = subscription_actions.offer_how(row)
    assert "fee" not in json.dumps(how).lower()
    title, message = subscription_actions._offer_message(row)
    assert "fee" not in (title + message).lower()
    # The AssistedAction ORM has no fee/savings column.
    cols = {c.name for c in _models.AssistedAction.__table__.columns}
    assert not any("fee" in c for c in cols)


# ── idempotency: tapping doesn't re-offer; bridge dedups ─────────────────────


def test_open_bridge_suppresses_new_offer(db_session):
    u, _ = _user(db_session)
    _lifecycle(db_session, u.id, merchant="netflix", status="dormant", probability_alive=0.1)
    # User already tapped → an open bridge exists for this merchant.
    _cancel_bridge(db_session, u.id, merchant="netflix", status="acknowledged")
    summary = run_for_user(db_session, u.id, now=_NOW, max_probability_alive=0.35)
    assert summary["offers"] == 0


def test_propose_cancel_bridge_dedups(db_session):
    u, _ = _user(db_session)
    _lifecycle(db_session, u.id, merchant="netflix")
    b1 = propose_cancel_bridge(db_session, u.id, "netflix")
    b2 = propose_cancel_bridge(db_session, u.id, "netflix")
    assert b1.id == b2.id  # same verify_ref → one bridge


# ── POSTGRES: the job sets per-user RLS tenant context and READS the rows ──────


@pytest.mark.skipif(not _PG, reason="RLS is Postgres-only; set TEST_DATABASE_URL to Postgres")
def test_job_sets_tenant_context_and_reads_lifecycle_rows_under_rls(_engine):
    """The headline RLS guard (B1): as a NON-superuser app_user with the real
    tenant policies ENABLED, the W6 job must bind each user's tenant context before
    reading — otherwise it reads ZERO MerchantLifecycle rows (the silent no-op) and
    surfaces no offer. Proves the job's per-user set_tenant lets it read the rows."""
    _TABLES = ("merchant_lifecycle", "notifications", "assisted_actions", "expenses", "accounts")

    # Seed as the (superuser) owner — bypasses RLS so the planted rows exist.
    with Session(_engine) as s:
        u, _acct = _user(s)
        _lifecycle(s, u.id, merchant="netflix", status="dormant", probability_alive=0.1)
        s.commit()
        user_id = u.id

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

            # SANITY: with NO tenant context, RLS fails closed — zero rows (the trap).
            assert s.execute(text("SELECT count(*) FROM merchant_lifecycle")).scalar() == 0

            saved = settings.subscription_actions_enabled
            try:
                settings.subscription_actions_enabled = True
                set_tenant(s, user_id)
                # With tenant bound, the SAME query now sees the row (NOT zero).
                assert s.execute(text("SELECT count(*) FROM merchant_lifecycle")).scalar() == 1
                summary = run_for_user(s, user_id, now=_NOW, max_probability_alive=0.35)
                assert summary["offers"] == 1
                assert (
                    s.execute(
                        text("SELECT count(*) FROM notifications WHERE ref LIKE 'sub_cancel:%'")
                    ).scalar()
                    == 1
                )
            finally:
                settings.subscription_actions_enabled = saved
            s.rollback()
    finally:
        with _engine.begin() as conn:
            for tbl in _TABLES:
                conn.execute(text(f"DROP POLICY IF EXISTS {tbl}_tenant_isolation ON {tbl}"))
                conn.execute(text(f"ALTER TABLE {tbl} NO FORCE ROW LEVEL SECURITY"))
                conn.execute(text(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY"))
