"""Bounded lifecycle properties for the MCP credential/capability boundary.

The state machine deliberately stays at the service layer.  PostgreSQL RLS has
its own deterministic integration suite; mixing it into randomized sequences
would make the normal CI suite slow and environment-dependent.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging

import jwt
import pytest
from hypothesis import HealthCheck, settings as hypothesis_settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule, run_state_machine_as_test
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from server.src.db.models import Account, MCPKey, MCPAuditLog, User
from server.src.mcp import vault
from server.src.mcp.audit import _canonical_params_hash, record
from server.src.mcp.policy import PolicyError, issue_capability, require, verify_capability
from server.src.mcp.vault import VaultError
from server.src.services.mcp_key_service import MCPKeyService
from server.src.settings import settings


READ_SCOPES = ("read:accounts", "read:transactions", "read:goals")
CLOCK = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
SCOPE_SUBSETS = st.sampled_from(
    [
        ["read:accounts"],
        ["read:transactions"],
        ["read:goals"],
        ["read:accounts", "read:transactions"],
        list(READ_SCOPES),
    ]
)


def _user(uid: int) -> User:
    return User(
        id=uid,
        username=f"mcp-prop-{uid}",
        full_name=f"Owner {uid}",
        email=f"mcp-prop-{uid}@example.test",
        hashed_password="unused",
        disabled=0,
    )


def test_mcp_key_and_capability_lifecycle_is_bounded(db_session, monkeypatch):
    """Generated sequences cannot widen scopes or cross an owner boundary."""

    original_propose = settings.mcp_propose_enabled
    # Key creation/resolution runs against an injected UTC clock. Generated
    # expiry paths never wait for wall time or use sleep.
    monkeypatch.setattr(
        "server.src.services.mcp_key_service._utcnow", lambda: CLOCK
    )
    db_session.add_all([_user(1), _user(2)])
    db_session.flush()
    db_session.add_all(
        [
            Account(
                name="OWNER-1",
                type="checking",
                balance=10_000,
                user_id=1,
            ),
            Account(
                name="OWNER-2",
                type="checking",
                balance=20_000,
                user_id=2,
            ),
        ]
    )
    db_session.flush()

    class _ReadOnlyView:
        """Let vault exercise dispatch without rolling back machine state.

        The production vault owns and rolls back its session. This generated
        model deliberately shares the lifecycle fixture session, so its wrapper
        makes those ownership methods no-ops while forwarding every read/query.
        """

        def __getattr__(self, name):
            return getattr(db_session, name)

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(vault, "SessionLocal", _ReadOnlyView)
    monkeypatch.setattr(vault, "audit_record", lambda **_kwargs: None)

    class Lifecycle(RuleBasedStateMachine):
        def __init__(self):
            super().__init__()
            self.keys: list[tuple[str, MCPKey]] = []
            self.capabilities: list[tuple[str, frozenset[str], int]] = []

        @rule(owner=st.sampled_from([1, 2]), scopes=SCOPE_SUBSETS)
        def create_subset_key(self, owner: int, scopes: list[str]):
            raw, row = MCPKeyService.create(
                db_session, owner, f"generated-{len(self.keys)}", scopes, ttl_days=1
            )
            self.keys.append((raw, row))
            assert set(row.scopes.split(",")).issubset(set(READ_SCOPES))

        @rule(index=st.integers(min_value=0, max_value=100))
        def resolve_and_issue_subset(self, index: int):
            if not self.keys:
                return
            raw, _ = self.keys[index % len(self.keys)]
            principal = MCPKeyService.resolve(db_session, raw)
            if principal is None:
                return
            chosen = sorted(principal.scopes)[:1]
            token = issue_capability(principal, chosen)
            claims = verify_capability(token)
            assert set(claims["scopes"]).issubset(principal.scopes)
            self.capabilities.append((token, principal.scopes, principal.user_id))

        @rule(index=st.integers(min_value=0, max_value=100))
        def capability_vault_read_is_scope_and_owner_bound(self, index: int):
            if not self.keys:
                return
            raw, _ = self.keys[index % len(self.keys)]
            principal = MCPKeyService.resolve(db_session, raw)
            if principal is None:
                return

            if "read:accounts" in principal.scopes:
                token = issue_capability(principal, ["read:accounts"])
                rows = vault.read(token, "accounts")
                assert {row["name"] for row in rows} == {
                    f"OWNER-{principal.user_id}"
                }

            # Spend a valid capability on a resource requiring a different
            # scope. This reaches the vault gate rather than only policy.issue.
            chosen = sorted(principal.scopes)[0]
            wrong_resource = "goals" if chosen == "read:accounts" else "accounts"
            wrong_token = issue_capability(principal, [chosen])
            with pytest.raises(VaultError):
                vault.read(wrong_token, wrong_resource)

        @rule(index=st.integers(min_value=0, max_value=100))
        def escalation_is_denied(self, index: int):
            if not self.keys:
                return
            raw, _ = self.keys[index % len(self.keys)]
            principal = MCPKeyService.resolve(db_session, raw)
            if principal is None:
                return
            with pytest.raises(PolicyError):
                issue_capability(principal, [*principal.scopes, "read:not-real"])

        @rule(index=st.integers(min_value=0, max_value=100))
        def revoke_blocks_new_resolution_but_not_issued_capability(self, index: int):
            if not self.keys:
                return
            raw, row = self.keys[index % len(self.keys)]
            principal = MCPKeyService.resolve(db_session, raw)
            token = None
            if principal is not None:
                token = issue_capability(principal, [sorted(principal.scopes)[0]])
            assert MCPKeyService.revoke(db_session, row.user_id, row.id)
            assert MCPKeyService.resolve(db_session, raw) is None
            # Revocation is checked at raw-key resolution. A capability already
            # issued before revocation retains its deliberately short JWT TTL.
            if token is not None:
                assert verify_capability(token)["uid"] == row.user_id

        @rule(index=st.integers(min_value=0, max_value=100))
        def expired_key_cannot_start_request(self, index: int):
            if not self.keys:
                return
            raw, row = self.keys[index % len(self.keys)]
            row.revoked = 0
            row.expires_at = CLOCK - timedelta(seconds=1)
            db_session.flush()
            assert MCPKeyService.resolve(db_session, raw) is None

        @rule(index=st.integers(min_value=0, max_value=100))
        def disabled_owner_cannot_start_request(self, index: int):
            if not self.keys:
                return
            raw, row = self.keys[index % len(self.keys)]
            owner = db_session.get(User, row.user_id)
            assert owner is not None
            owner.disabled = 1
            row.revoked = 0
            row.expires_at = CLOCK + timedelta(days=1)
            db_session.flush()
            assert MCPKeyService.resolve(db_session, raw) is None
            owner.disabled = 0

        @rule(index=st.integers(min_value=0, max_value=100))
        def other_owner_cannot_list_or_revoke(self, index: int):
            if not self.keys:
                return
            _, row = self.keys[index % len(self.keys)]
            other = 2 if row.user_id == 1 else 1
            assert row.id not in {item["id"] for item in MCPKeyService.list_keys(db_session, other)}
            assert MCPKeyService.revoke(db_session, other, row.id) is False

        @rule(enabled=st.booleans())
        def proposal_scope_requires_scope_and_flag(self, enabled: bool):
            settings.mcp_propose_enabled = enabled
            if enabled:
                raw, row = MCPKeyService.create(
                    db_session, 1, f"proposal-{len(self.keys)}", ["propose:actions"], 1
                )
                principal = MCPKeyService.resolve(db_session, raw)
                assert principal is not None
                require(principal, "propose:actions")
                self.keys.append((raw, row))
            else:
                with pytest.raises(ValueError):
                    MCPKeyService.create(db_session, 1, "disabled-proposal", ["propose:actions"], 1)

        @rule()
        def unknown_key_is_opaque(self):
            assert MCPKeyService.resolve(db_session, "bdgt_live_unknown") is None

        @invariant()
        def stored_scopes_never_exceed_allow_list(self):
            allowed = set(READ_SCOPES) | {"propose:actions"}
            rows = db_session.execute(select(MCPKey)).scalars().all()
            assert all(set(row.scopes.split(",")).issubset(allowed) for row in rows)

        def teardown(self):
            settings.mcp_propose_enabled = original_propose

    try:
        run_state_machine_as_test(
            Lifecycle,
            settings=hypothesis_settings(
                max_examples=18,
                stateful_step_count=22,
                deadline=None,
                suppress_health_check=[HealthCheck.too_slow],
                derandomize=True,
            ),
        )
    finally:
        settings.mcp_propose_enabled = original_propose


def test_expired_capability_without_sleep():
    """A negative TTL gives a deterministic expired token; the test never sleeps."""
    from server.src.mcp.principal import Principal

    principal = Principal(1, 1, frozenset({"read:accounts"}))
    prior = settings.mcp_capability_ttl_seconds
    settings.mcp_capability_ttl_seconds = -1
    try:
        token = issue_capability(principal, ["read:accounts"])
    finally:
        settings.mcp_capability_ttl_seconds = prior
    with pytest.raises(jwt.ExpiredSignatureError):
        verify_capability(token)


def test_audit_failure_is_observable_and_non_blocking(monkeypatch, caplog):
    from server.src.db import session as db_session_module

    def fail_to_open():
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(db_session_module, "SessionLocal", fail_to_open)
    with caplog.at_level(logging.WARNING, logger="server.src.services.mcp_audit_store"):
        record(
            user_id=1,
            key_id=2,
            resource="forecast",
            params={"account": "sensitive-value"},
            decision="allow",
        )
    assert "mcp audit row discarded" in caplog.text
    assert "sensitive-value" not in caplog.text


def test_healthy_audit_persists_only_metadata(_engine, monkeypatch):
    from server.src.db import session as db_session_module

    factory = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    monkeypatch.setattr(db_session_module, "SessionLocal", factory)
    db = factory()
    db.add(_user(1))
    db.commit()
    db.close()

    params = {"merchant": "a raw merchant", "amount": 12345}
    record(user_id=1, key_id=None, resource="transactions", params=params, decision="allow")

    check = factory()
    row = check.execute(select(MCPAuditLog)).scalar_one()
    assert row.params_hash == _canonical_params_hash(params)
    assert "raw merchant" not in row.params_hash
    assert row.resource == "transactions"
    assert row.decision == "allow"
    check.close()
