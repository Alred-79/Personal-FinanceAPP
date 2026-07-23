"""Integration contract for the production demo bootstrap."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from server.src.db.models import (
    GameEvent,
    Account,
    BalanceSnapshot,
    Budget,
    Goal,
    MCPAuditLog,
    MCPKey,
    MerchantAlias,
    Notification,
    Rule,
    RuleExecution,
    Scenario,
    User,
)
from server.src.services.demo_readiness import (
    DEMO_DATASET_MARKER_REF,
    assess_demo_readiness,
)
from server.src.services.recurring_service import RecurringService
from server.scripts.seed_demo import seed_user_config


def test_demo_reset_converges_a_legacy_identity_to_the_canonical_persona():
    user = User(
        username="demo",
        email="old-demo@example.com",
        full_name="Demo Saver",
        hashed_password="unused",
    )

    seed_user_config(user)

    assert user.full_name == "Maya Chen"
    assert user.email == "demo@example.com"
    assert user.game_mode == "off"


def _run(command: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_fresh_bootstrap_is_ready_truthful_and_idempotent(tmp_path, monkeypatch):
    db_path = tmp_path / "showcase.db"
    env = os.environ.copy()
    env.update({
        "DATABASE_URL": f"sqlite:///{db_path}",
        "DEMO_MODE_ENABLED": "true",
    })
    _run([sys.executable, "-m", "alembic", "upgrade", "head"], env)
    _run(
        [sys.executable, "-m", "server.scripts.seed_demo", "--bootstrap"],
        env,
    )

    before = hashlib.sha256(db_path.read_bytes()).hexdigest()
    second = _run(
        [sys.executable, "-m", "server.scripts.seed_demo", "--bootstrap"],
        env,
    )
    after = hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert before == after
    assert "already ready; no changes" in second.stderr

    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as db:
        assert assess_demo_readiness(db, enabled=True).ready is True
        user = db.execute(select(User).where(User.username == "demo")).scalar_one()
        assert user.full_name == "Maya Chen"
        assert user.game_mode == "off"
        assert db.execute(select(func.count(Goal.id)).where(Goal.user_id == user.id)).scalar_one() >= 6
        assert db.execute(select(func.count(Rule.id)).where(Rule.user_id == user.id)).scalar_one() >= 3
        assert db.execute(select(func.count(RuleExecution.id)).where(RuleExecution.user_id == user.id)).scalar_one() >= 3
        assert db.execute(select(func.count(MerchantAlias.id)).where(MerchantAlias.user_id == user.id)).scalar_one() >= 2
        assert db.execute(select(func.count(GameEvent.id))).scalar_one() == 0
        assert db.execute(select(func.count(MCPKey.id)).where(MCPKey.user_id == user.id)).scalar_one() == 0
        assert db.execute(select(func.count(MCPAuditLog.id)).where(MCPAuditLog.user_id == user.id)).scalar_one() == 0

        # The authenticated-router guard rejects a command before route code can
        # touch this real canonical seed; readiness therefore remains true.
        from fastapi import HTTPException
        from starlette.requests import Request

        from server.src.db.tenant import _enforce_shared_demo_read_only
        from server.src.services.auth_service import _to_user_in_db
        from server.src.settings import settings

        monkeypatch.setattr(settings, "demo_mode_enabled", True)
        request = Request({
            "type": "http",
            "method": "DELETE",
            "path": f"/api/goals/{user.id}/",
            "headers": [],
        })
        with pytest.raises(HTTPException) as blocked:
            _enforce_shared_demo_read_only(request, _to_user_in_db(user))
        assert blocked.value.status_code == 403
        assert blocked.value.detail["code"] == "demo_read_only"
        assert assess_demo_readiness(db, enabled=True).ready is True

        visible_total = db.execute(
            select(func.sum(Account.balance)).where(Account.user_id == user.id)
        ).scalar_one()
        latest = db.execute(
            select(BalanceSnapshot)
            .where(BalanceSnapshot.user_id == user.id)
            .order_by(BalanceSnapshot.date.desc(), BalanceSnapshot.id.desc())
            .limit(1)
        ).scalar_one()
        assert latest.total == visible_total

        projected = RecurringService(db).project_expenses(
            user.id, date.today(), date.today() + timedelta(days=62)
        )
        assert "Hulu" not in {row["title"] for row in projected}

        # Shared-demo mutations must fail readiness instead of presenting a
        # partially blank showcase as canonical.
        canonical_rows = [
            lambda: db.execute(select(Goal).where(Goal.user_id == user.id, Goal.name == "Tax Reserve")).scalar_one(),
            lambda: db.execute(select(Rule).where(Rule.user_id == user.id, Rule.name == "Big purchase heads-up")).scalar_one(),
            lambda: db.execute(select(Scenario).where(Scenario.user_id == user.id, Scenario.name == "Add freelance retainer")).scalar_one(),
            lambda: db.execute(select(Budget).where(Budget.user_id == user.id, Budget.category == "Food")).scalar_one(),
            lambda: db.execute(select(Notification).where(Notification.user_id == user.id, Notification.ref == DEMO_DATASET_MARKER_REF)).scalar_one(),
            lambda: db.execute(select(BalanceSnapshot).where(BalanceSnapshot.id == latest.id)).scalar_one(),
        ]
        for load_row in canonical_rows:
            db.delete(load_row())
            db.flush()
            assert assess_demo_readiness(db, enabled=True).ready is False
            db.rollback()
