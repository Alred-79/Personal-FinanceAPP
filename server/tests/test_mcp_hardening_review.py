"""Hardening for the security-review findings on the MCP surface expansion.

  #1  forecast `days` had no upper bound -> resource exhaustion. Now clamped.
  #4  what_if accepted an unbounded overlay -> resource exhaustion. Now capped.
  #2  propose stored agent-supplied rationale/refs/how unvalidated. Now bounded.
  #3  `propose:actions` was mintable by default. Now only when the feature is on.
"""

import pytest

from server.src.db.models import (
    Account as AccountORM,
    AssistedAction as AssistedActionORM,
    User as UserORM,
)
from server.src.mcp import actions, vault
from server.src.mcp.actions import ProposeError
from server.src.mcp.policy import issue_capability
from server.src.mcp.principal import Principal
from server.src.mcp.vault import VaultError
from server.src.services.mcp_key_service import MCPKeyService


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

class _NoClose:
    def __init__(self, s):
        self._s = s

    def __getattr__(self, name):
        return getattr(self._s, name)

    def close(self):
        pass


@pytest.fixture
def vault_db(db_session, monkeypatch):
    monkeypatch.setattr(vault, "SessionLocal", lambda: _NoClose(db_session))
    return db_session


@pytest.fixture
def actions_db(db_session, monkeypatch):
    monkeypatch.setattr(actions, "SessionLocal", lambda: _NoClose(db_session))
    return db_session


@pytest.fixture
def read_token():
    p = Principal(user_id=1, key_id=10, scopes=frozenset(["read"]))
    return issue_capability(p, ["read"])


@pytest.fixture
def propose_cap():
    p = Principal(user_id=1, key_id=10, scopes=frozenset(["propose:actions"]))
    return issue_capability(p, ["propose:actions"])


def _user(db, uid=1):
    u = UserORM(
        id=uid, username=f"u{uid}", full_name="T", email=f"u{uid}@x.com",
        hashed_password="x", disabled=0,
    )
    db.add(u)
    db.flush()
    return u


def _account(db, uid=1, balance=500_00):
    a = AccountORM(name="C", type="checking", balance=balance, user_id=uid)
    db.add(a)
    db.flush()
    return a


# ---------------------------------------------------------------------------
# #1 — forecast days upper bound
# ---------------------------------------------------------------------------

class TestForecastDaysBounded:
    def test_huge_days_is_clamped_not_unbounded(self, vault_db, read_token):
        _user(vault_db)
        _account(vault_db)
        result = vault.read(read_token, "forecast", days=10_000_000)
        # Clamped to a sane maximum — never honours an arbitrarily huge horizon.
        assert result["horizon"]["days"] <= vault.MAX_FORECAST_DAYS
        assert result["horizon"]["days"] == vault.MAX_FORECAST_DAYS

    def test_normal_days_unchanged(self, vault_db, read_token):
        _user(vault_db)
        _account(vault_db)
        assert vault.read(read_token, "forecast", days=30)["horizon"]["days"] == 30


# ---------------------------------------------------------------------------
# #4 — what_if overlay size cap
# ---------------------------------------------------------------------------

class TestWhatIfOverlayBounded:
    def test_oversized_overlay_rejected(self, vault_db, read_token):
        _user(vault_db)
        _account(vault_db)
        huge = {
            "discrete_flows": [
                {"date": "2024-03-10", "amount_cents": 100, "kind": "expense"}
                for _ in range(vault.MAX_OVERLAY_ITEMS + 1)
            ]
        }
        with pytest.raises(VaultError):
            vault.read(read_token, "what_if", overlay=huge)

    def test_reasonable_overlay_ok(self, vault_db, read_token):
        _user(vault_db)
        _account(vault_db)
        ok = {
            "discrete_flows": [
                {"date": "2024-03-10", "amount_cents": 100, "kind": "expense"}
            ]
        }
        result = vault.read(read_token, "what_if", overlay=ok)
        assert "scenario" in result


# ---------------------------------------------------------------------------
# #2 — propose field validation
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _enable_propose(monkeypatch):
    monkeypatch.setattr(actions.settings, "mcp_propose_enabled", True)


class TestProposeFieldValidation:
    def test_overlong_rationale_rejected(self, actions_db, propose_cap):
        _user(actions_db)
        with pytest.raises(ProposeError):
            actions.propose(
                propose_cap, kind="goal_funding", amount=10.0,
                rationale="x" * (actions.MAX_RATIONALE_LEN + 1),
            )
        assert actions_db.query(AssistedActionORM).count() == 0

    def test_non_string_source_ref_rejected(self, actions_db, propose_cap):
        _user(actions_db)
        with pytest.raises(ProposeError):
            actions.propose(
                propose_cap, kind="goal_funding", amount=10.0,
                rationale="ok", source_ref=12345,
            )

    def test_overlong_ref_rejected(self, actions_db, propose_cap):
        _user(actions_db)
        with pytest.raises(ProposeError):
            actions.propose(
                propose_cap, kind="goal_funding", amount=10.0,
                rationale="ok", dest_ref="d" * (actions.MAX_REF_LEN + 1),
            )

    def test_non_dict_how_rejected(self, actions_db, propose_cap):
        _user(actions_db)
        with pytest.raises(ProposeError):
            actions.propose(
                propose_cap, kind="goal_funding", amount=10.0,
                rationale="ok", how="not-a-dict",
            )

    def test_oversized_how_rejected(self, actions_db, propose_cap):
        _user(actions_db)
        big = {f"k{i}": "v" * 100 for i in range(1000)}
        with pytest.raises(ProposeError):
            actions.propose(
                propose_cap, kind="goal_funding", amount=10.0,
                rationale="ok", how=big,
            )

    def test_valid_fields_still_pass(self, actions_db, propose_cap):
        _user(actions_db)
        result = actions.propose(
            propose_cap, kind="goal_funding", amount=10.0, rationale="ok",
            source_ref="Checking", dest_ref="Savings", how={"steps": ["a"]},
        )
        assert result["status"] == "proposed"


# ---------------------------------------------------------------------------
# #3 — propose:actions not mintable unless the feature is enabled
# ---------------------------------------------------------------------------

class TestProposeScopeGatedByFlag:
    def test_not_mintable_when_disabled(self, db_session, monkeypatch):
        monkeypatch.setattr(
            MCPKeyService.create.__globals__["settings"],
            "mcp_propose_enabled", False,
        )
        _user(db_session)
        with pytest.raises(ValueError):
            MCPKeyService.create(db_session, 1, "k", ["propose:actions"])

    def test_mintable_when_enabled(self, db_session, monkeypatch):
        monkeypatch.setattr(
            MCPKeyService.create.__globals__["settings"],
            "mcp_propose_enabled", True,
        )
        _user(db_session)
        raw, row = MCPKeyService.create(db_session, 1, "k", ["propose:actions"])
        assert "propose:actions" in row.scopes

    def test_not_in_default_allowlist(self):
        from server.src.settings import settings
        # Default config has the feature off, so the write scope must NOT be in
        # the statically-allowed set.
        assert "propose:actions" not in set(settings.mcp_allowed_scopes)
