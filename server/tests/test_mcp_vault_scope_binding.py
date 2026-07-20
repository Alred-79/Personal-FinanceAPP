"""The vault binds each capability token to the resource it may read.

``vault.py``'s module docstring has always advertised the pipeline as
``Capability token → scope check → read-only session → …``, but ``read()``
performed no scope check: it extracted ``scopes`` from the claims and passed
them to ``_dispatch``, which consulted them ONLY for the ``context`` resource's
compose-by-scope gating. Every other resource — accounts, transactions, goals,
budgets, forecast, net worth, subscriptions, scenarios — was reachable with a
capability minted for any other resource.

That was never exploitable from outside: the tool layer calls
``policy.require`` before minting, and ``issue_capability`` refuses to mint a
scope the principal does not hold, so no caller could obtain a capability
carrying scopes it wasn't entitled to. The gap was defense-in-depth — the vault
trusted its caller to have checked. These tests move the check to the boundary
that actually guards the data, so a future tool (or a mistake in an existing
one) cannot reach past it.

Fail-closed by construction: a resource with no entry in the map is denied
rather than allowed, so adding a resource without deciding its scope breaks the
request instead of silently exposing it.
"""

from __future__ import annotations

import pytest

from server.src.mcp import vault
from server.src.mcp.policy import issue_capability
from server.src.mcp.principal import Principal
from server.src.mcp.vault import VaultError


@pytest.fixture
def patched_db(db_session, monkeypatch):
    """Point vault.SessionLocal at the test session without closing it.

    Mirrors the fixture in test_mcp_vault.py; duplicated rather than shared
    because that one is module-local, not a conftest fixture.
    """

    class _NoClose:
        def __init__(self, s):
            self._s = s

        def __getattr__(self, name):
            return getattr(self._s, name)

        def close(self):
            pass

    monkeypatch.setattr(vault, "SessionLocal", lambda: _NoClose(db_session))
    return db_session


def _cap(scopes: list[str], uid: int = 1) -> str:
    """Mint a capability carrying exactly *scopes* (no escalation possible)."""
    principal = Principal(user_id=uid, key_id=10, scopes=frozenset(scopes))
    return issue_capability(principal, scopes)


def test_accounts_capability_cannot_read_transactions():
    """The core cross-resource case: a token minted for one resource must not
    open another."""
    cap = _cap(["read:accounts"])
    with pytest.raises(VaultError, match="scope"):
        vault.read(cap, "tx_by_date", start="2026-01-01", end="2026-01-31")


def test_transactions_capability_cannot_read_net_worth():
    """A second pairing, so the guard can't pass by hardcoding one resource."""
    cap = _cap(["read:transactions"])
    with pytest.raises(VaultError, match="scope"):
        vault.read(cap, "net_worth")


def test_budgets_capability_cannot_run_what_if():
    """Scenario projection is the most computationally expensive resource; it
    must not be reachable on an unrelated scope."""
    cap = _cap(["read:budgets"])
    with pytest.raises(VaultError, match="scope"):
        vault.read(cap, "what_if", overlay={})


def test_unknown_resource_fails_closed():
    """An unmapped resource is denied, not passed through to _dispatch."""
    cap = _cap(["read:accounts"])
    with pytest.raises(VaultError):
        vault.read(cap, "not_a_real_resource")


def test_ping_needs_no_scope():
    """``ping`` echoes only the uid the verified token already establishes, so
    it stays scope-free — pinned here so the map's one None is deliberate."""
    cap = _cap(["read:accounts"])
    assert vault.read(cap, "ping") == {"user_id": 1}


def test_correct_scope_still_reads(patched_db):
    """The guard must not break the legitimate path."""
    from server.tests.test_mcp_vault import _account, _user

    _user(patched_db, 1)
    _account(patched_db, 1)
    patched_db.flush()

    cap = _cap(["read:accounts"])
    result = vault.read(cap, "accounts")
    assert isinstance(result, list) and len(result) == 1


def test_missing_scope_denial_is_audited(caplog):
    """A refused read must land in the owner's audit trail with a specific
    reason — a denial nobody can see is not a control."""
    import logging

    cap = _cap(["read:accounts"])
    with caplog.at_level(logging.INFO, logger="mcp.audit"):
        with pytest.raises(VaultError):
            vault.read(cap, "net_worth")

    lines = [r.getMessage() for r in caplog.records if r.name == "mcp.audit"]
    assert any("missing_scope" in line for line in lines), lines


def test_every_dispatchable_resource_has_a_scope_decision():
    """Structural: every resource _dispatch can serve must appear in the map.

    This is the test that keeps the guard honest over time — add a resource to
    _dispatch without a scope decision and this fails, rather than the resource
    quietly becoming reachable on any capability.
    """
    import re
    from pathlib import Path

    src = Path("server/src/mcp/vault.py").read_text()
    dispatched = set(re.findall(r'resource == "([a-z_]+)"', src))
    assert dispatched, "could not parse resources out of vault.py"
    missing = dispatched - set(vault._RESOURCE_SCOPES)
    assert not missing, f"resources with no scope decision: {sorted(missing)}"
