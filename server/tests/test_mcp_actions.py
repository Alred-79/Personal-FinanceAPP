"""Tests for the Tier-2 MCP propose door (``server/src/mcp/actions.py``).

The propose door is the SECOND sanctioned DB door (alongside the read-only
vault). It is deliberately narrow: it drafts an Assisted-Action *Bridge* the
human must still execute in-app. It never moves money and never executes — so
its whole risk surface is "can an agent create a proposal it shouldn't, for
someone it isn't?"

Covered:
  * scope ``propose:actions`` survives key normalization (so a key can carry it)
  * a valid capability creates AND commits a Bridge, scoped to the token's user
  * the user id comes from the capability, never a tool argument
  * the door ships dark: with ``mcp_propose_enabled`` False it refuses
  * a capability lacking ``propose:actions`` is refused
  * bad input (unknown kind, non-positive amount) → clean ProposeError, no write
  * an allow is audited
"""

import pytest

from server.src.db.models import (
    AssistedAction as AssistedActionORM,
    User as UserORM,
)
from server.src.mcp import actions
from server.src.mcp.actions import ProposeError
from server.src.mcp.policy import issue_capability
from server.src.mcp.principal import Principal
from server.src.mcp.scopes import normalize_scopes


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def principal_a():
    return Principal(user_id=1, key_id=10, scopes=frozenset(["propose:actions"]))


@pytest.fixture
def cap_a(principal_a):
    return issue_capability(principal_a, ["propose:actions"])


@pytest.fixture
def read_only_cap():
    p = Principal(user_id=1, key_id=10, scopes=frozenset(["read:accounts"]))
    return issue_capability(p, ["read:accounts"])


@pytest.fixture
def patched_db(db_session, monkeypatch):
    """Patch actions.SessionLocal to the test session; keep its commit, no-op close."""
    class _NoClose:
        def __init__(self, s):
            self._s = s

        def __getattr__(self, name):
            return getattr(self._s, name)

        def close(self):
            pass

    monkeypatch.setattr(actions, "SessionLocal", lambda: _NoClose(db_session))
    return db_session


@pytest.fixture(autouse=True)
def _enable_propose(monkeypatch):
    """Most tests need the door on; the ships-dark test overrides this."""
    monkeypatch.setattr(actions.settings, "mcp_propose_enabled", True)


def _user(db, uid, username="alice", email="a@x.com"):
    u = UserORM(
        id=uid, username=username, full_name="Test", email=email,
        hashed_password="x", disabled=0,
    )
    db.add(u)
    db.flush()
    return u


# ---------------------------------------------------------------------------
# Scope normalization
# ---------------------------------------------------------------------------

class TestProposeScopeSurvives:
    def test_propose_scope_is_not_dropped(self):
        assert normalize_scopes(["propose:actions"]) == ["propose:actions"]

    def test_propose_scope_passes_through_alongside_reads(self):
        out = normalize_scopes(["read:forecast", "propose:actions"])
        assert "propose:actions" in out


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestProposeCreatesBridge:
    def test_creates_and_returns_bridge(self, patched_db, cap_a):
        _user(patched_db, 1)
        result = actions.propose(
            cap_a,
            kind="goal_funding",
            amount=340.00,
            rationale="$340 short of this month's target",
        )
        assert result["kind"] == "goal_funding"
        assert result["amount"] == 340.00
        assert result["status"] == "proposed"
        assert isinstance(result["id"], int)

    def test_bridge_is_committed(self, patched_db, cap_a):
        """The door COMMITS — unlike the read-only vault — so the row persists."""
        _user(patched_db, 1)
        actions.propose(
            cap_a, kind="goal_funding", amount=50.0, rationale="catch up",
        )
        rows = patched_db.query(AssistedActionORM).all()
        assert len(rows) == 1
        assert rows[0].user_id == 1
        assert rows[0].status == "proposed"

    def test_user_id_comes_from_capability_not_argument(self, patched_db, cap_a):
        """A user_id passed as a tool argument must be ignored — uid is the token's."""
        _user(patched_db, 1)
        _user(patched_db, 2, "bob", "bob@x.com")
        actions.propose(
            cap_a, kind="goal_funding", amount=10.0, rationale="x", user_id=2,
        )
        rows = patched_db.query(AssistedActionORM).all()
        assert [r.user_id for r in rows] == [1]


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------

class TestProposeGating:
    def test_ships_dark_when_flag_off(self, patched_db, cap_a, monkeypatch):
        monkeypatch.setattr(actions.settings, "mcp_propose_enabled", False)
        _user(patched_db, 1)
        with pytest.raises(ProposeError):
            actions.propose(
                cap_a, kind="goal_funding", amount=10.0, rationale="x",
            )
        assert patched_db.query(AssistedActionORM).count() == 0

    def test_capability_without_scope_refused(self, patched_db, read_only_cap):
        _user(patched_db, 1)
        with pytest.raises(ProposeError):
            actions.propose(
                read_only_cap, kind="goal_funding", amount=10.0, rationale="x",
            )
        assert patched_db.query(AssistedActionORM).count() == 0

    def test_forged_token_refused(self, patched_db):
        _user(patched_db, 1)
        with pytest.raises(ProposeError):
            actions.propose(
                "not.a.token", kind="goal_funding", amount=10.0, rationale="x",
            )


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestProposeValidation:
    def test_unknown_kind_rejected(self, patched_db, cap_a):
        _user(patched_db, 1)
        with pytest.raises(ProposeError):
            actions.propose(
                cap_a, kind="steal_money", amount=10.0, rationale="x",
            )
        assert patched_db.query(AssistedActionORM).count() == 0

    def test_non_positive_amount_rejected(self, patched_db, cap_a):
        _user(patched_db, 1)
        with pytest.raises(ProposeError):
            actions.propose(
                cap_a, kind="goal_funding", amount=0, rationale="x",
            )

    def test_non_numeric_amount_rejected(self, patched_db, cap_a):
        _user(patched_db, 1)
        with pytest.raises(ProposeError):
            actions.propose(
                cap_a, kind="goal_funding", amount="lots", rationale="x",
            )


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

class TestProposeAudit:
    def test_allow_is_audited(self, patched_db, cap_a, caplog):
        import logging
        _user(patched_db, 1)
        with caplog.at_level(logging.INFO, logger="mcp.audit"):
            actions.propose(
                cap_a, kind="goal_funding", amount=10.0, rationale="x",
            )
        assert any("allow" in r.message for r in caplog.records)
