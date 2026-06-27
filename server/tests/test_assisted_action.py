"""The Assisted Action Bridge (Pillar 2C) — service unit tests.

Covers: propose builds the exact action and SCREENS the rationale (R4);
reconcile matches a TWO-LEG transfer (debit at source + credit at dest) →
verified and mirrors the earmark; single-leg kinds match one outflow; a PARTIAL
match (one leg only) stays acknowledged, never verified (R8); a no-match after N
days nudges; ``verify_ref`` dedup prevents double-create; "I did it" is
provisional until the sync verifies (R2).
"""

from datetime import date, timedelta

import pytest

from .conftest import wire_plaid_pages  # L5: bridge sync_transactions → pages
from server.src.db.models import (
    Account as AccountORM,
    Goal as GoalORM,
    Notification as NotificationORM,
    User as UserORM,
)
from server.src.services.assisted_action_service import (
    AssistedActionError,
    AssistedActionService,
)


@pytest.fixture
def bridge_user(db_session):
    user = UserORM(
        username="bridge", full_name="Bridge", email="b@x.com", hashed_password="x"
    )
    db_session.add(user)
    db_session.flush()
    checking = AccountORM(name="Checking", type="checking", balance=500_000, user_id=user.id)
    savings = AccountORM(name="Savings", type="savings", balance=100_000, user_id=user.id)
    goal = GoalORM(
        name="House", amount=1_000_000, date="2030-01-01", user_id=user.id, progress=0
    )
    db_session.add_all([checking, savings, goal])
    db_session.flush()
    return user, checking, savings, goal


def _txn(amount_cents, account_id, d=None, title="Transfer"):
    # Default to today so the synced row sits inside the reconcile window around
    # the Bridge's created_at (which propose() stamps as "now").
    return {
        "amount_cents": amount_cents,  # SIGNED: +in / -out
        "account_id": account_id,
        "date": d or date.today().isoformat(),
        "title": title,
    }


# ── propose ──────────────────────────────────────────────────────────────────


def test_propose_builds_exact_action(db_session, bridge_user):
    user, checking, savings, _ = bridge_user
    svc = AssistedActionService(db_session)
    b = svc.propose(
        user.id,
        kind="transfer",
        amount_cents=34000,
        rationale="House goal is $340 short of this month's target.",
        source_ref=str(checking.id),
        dest_ref=str(savings.id),
        how={"instruction": "Transfer $340 Checking → Savings"},
    )
    assert b.id is not None
    assert b.kind == "transfer"
    assert b.amount_cents == 34000
    assert b.status == "proposed"
    assert b.settlement_status is None  # reserved, NULL in 2C
    assert "340" in b.rationale


def test_propose_screens_advice_rationale(db_session, bridge_user):
    """A rationale that reads as advice is replaced with a neutral factual one (R4)."""
    user, checking, savings, _ = bridge_user
    svc = AssistedActionService(db_session)
    b = svc.propose(
        user.id,
        kind="transfer",
        amount_cents=10000,
        rationale="You should invest this money in index funds.",
        source_ref=str(checking.id),
        dest_ref=str(savings.id),
    )
    assert "invest" not in b.rationale.lower()


def test_propose_rejects_bad_kind_and_amount(db_session, bridge_user):
    user, _, _, _ = bridge_user
    svc = AssistedActionService(db_session)
    with pytest.raises(AssistedActionError):
        svc.propose(user.id, kind="bogus", amount_cents=100, rationale="x")
    with pytest.raises(AssistedActionError):
        svc.propose(user.id, kind="transfer", amount_cents=0, rationale="x")


def test_propose_dedups_by_verify_ref(db_session, bridge_user):
    """Same-day re-propose of an identical intent collapses to one (replay case)."""
    user, checking, savings, _ = bridge_user
    svc = AssistedActionService(db_session)
    a = svc.propose(
        user.id, kind="transfer", amount_cents=34000, rationale="x",
        source_ref=str(checking.id), dest_ref=str(savings.id),
    )
    b = svc.propose(
        user.id, kind="transfer", amount_cents=34000, rationale="x",
        source_ref=str(checking.id), dest_ref=str(savings.id),
    )
    assert a.id == b.id
    assert db_session.query(type(a)).count() == 1


def test_recurring_same_amount_on_different_days_are_distinct(db_session, bridge_user):
    """A recurring $340 transfer proposed on different days must NOT collapse into
    one open Bridge (else the later occurrence is silently swallowed)."""
    user, checking, savings, _ = bridge_user
    svc = AssistedActionService(db_session)
    # Two explicit verify_refs differing only by day (what the default now does).
    ref_d1 = svc._default_verify_ref(
        user.id, "transfer", 34000, str(checking.id), str(savings.id), "2026-06-01T00:00:00"
    )
    ref_d2 = svc._default_verify_ref(
        user.id, "transfer", 34000, str(checking.id), str(savings.id), "2026-07-01T00:00:00"
    )
    assert ref_d1 != ref_d2
    a = svc.propose(
        user.id, kind="transfer", amount_cents=34000, rationale="x",
        source_ref=str(checking.id), dest_ref=str(savings.id), verify_ref=ref_d1,
    )
    b = svc.propose(
        user.id, kind="transfer", amount_cents=34000, rationale="x",
        source_ref=str(checking.id), dest_ref=str(savings.id), verify_ref=ref_d2,
    )
    assert a.id != b.id  # two distinct Bridges


def test_within_fails_closed_on_missing_anchor_date(db_session, bridge_user):
    """A Bridge with no created_at must NOT verify against a same-amount row from
    any date (fail closed, like matching.within_window)."""
    user, checking, _, _ = bridge_user
    svc = AssistedActionService(db_session)
    b = svc.propose(
        user.id, kind="bill_payment", amount_cents=5000, rationale="x",
        source_ref=str(checking.id),
    )
    b.created_at = None  # simulate a malformed/hand-built row
    svc.mark_done(user.id, b.id)
    # A matching-amount row exists, but the anchor has no date → no verify.
    assert svc.reconcile(user.id, [_txn(-5000, checking.id)]) == []
    db_session.refresh(b)
    assert b.status == "confirmed_done"


# ── reconcile: two-leg transfer ──────────────────────────────────────────────


def test_reconcile_two_leg_transfer_verifies_and_mirrors(db_session, bridge_user):
    user, checking, savings, goal = bridge_user
    svc = AssistedActionService(db_session)
    b = svc.propose(
        user.id, kind="transfer", amount_cents=34000,
        rationale="House goal $340 short.",
        source_ref=str(checking.id), dest_ref=str(savings.id),
        how={"goal_id": goal.id},
    )
    svc.mark_done(user.id, b.id)  # provisional

    synced = [
        _txn(-34000, checking.id),  # debit leaves checking
        _txn(+34000, savings.id),   # credit lands in savings
    ]
    verified = svc.reconcile(user.id, synced)
    assert [v.id for v in verified] == [b.id]
    db_session.refresh(b)
    assert b.status == "verified"
    # The verified transfer mirrors the goal earmark to reflect real money.
    db_session.refresh(goal)
    assert goal.progress == 34000


def test_reconcile_one_leg_only_stays_acknowledged(db_session, bridge_user):
    """A partial match (debit seen, credit not) must NOT verify (R8)."""
    user, checking, savings, goal = bridge_user
    svc = AssistedActionService(db_session)
    b = svc.propose(
        user.id, kind="transfer", amount_cents=34000, rationale="x",
        source_ref=str(checking.id), dest_ref=str(savings.id),
        how={"goal_id": goal.id},
    )
    svc.mark_done(user.id, b.id)
    synced = [_txn(-34000, checking.id)]  # only the debit leg
    verified = svc.reconcile(user.id, synced)
    assert verified == []
    db_session.refresh(b)
    assert b.status == "confirmed_done"  # provisional, not verified
    db_session.refresh(goal)
    assert goal.progress == 0  # earmark NOT mirrored on a partial match


# ── reconcile: single-leg ────────────────────────────────────────────────────


def test_reconcile_single_leg_tax_payment_verifies(db_session, bridge_user):
    user, checking, _, _ = bridge_user
    svc = AssistedActionService(db_session)
    b = svc.propose(
        user.id, kind="tax_payment", amount_cents=295000,
        rationale="Q2 estimated tax due.",
        source_ref=str(checking.id), dest_ref="irs.gov/payments",
    )
    svc.mark_done(user.id, b.id)
    synced = [_txn(-295000, checking.id, title="IRS USATAXPYMT")]
    verified = svc.reconcile(user.id, synced)
    assert [v.id for v in verified] == [b.id]
    db_session.refresh(b)
    assert b.status == "verified"


def test_reconcile_wrong_amount_does_not_verify(db_session, bridge_user):
    user, checking, _, _ = bridge_user
    svc = AssistedActionService(db_session)
    b = svc.propose(
        user.id, kind="bill_payment", amount_cents=12000, rationale="x",
        source_ref=str(checking.id),
    )
    svc.mark_done(user.id, b.id)
    synced = [_txn(-11999, checking.id)]  # off by a cent → no match
    assert svc.reconcile(user.id, synced) == []
    db_session.refresh(b)
    assert b.status == "confirmed_done"


def test_proposed_not_reconciled_until_acted_on(db_session, bridge_user):
    """A bare 'proposed' Bridge (user never touched it) is not auto-verified even
    if a matching transaction appears — we only reconcile what the user engaged."""
    user, checking, savings, _ = bridge_user
    svc = AssistedActionService(db_session)
    b = svc.propose(
        user.id, kind="transfer", amount_cents=34000, rationale="x",
        source_ref=str(checking.id), dest_ref=str(savings.id),
    )
    synced = [_txn(-34000, checking.id), _txn(+34000, savings.id)]
    assert svc.reconcile(user.id, synced) == []
    db_session.refresh(b)
    assert b.status == "proposed"


# ── nudge on no-match ────────────────────────────────────────────────────────


def test_no_match_after_n_days_nudges_once(db_session, bridge_user):
    user, checking, savings, _ = bridge_user
    svc = AssistedActionService(db_session)
    b = svc.propose(
        user.id, kind="transfer", amount_cents=34000, rationale="x",
        source_ref=str(checking.id), dest_ref=str(savings.id),
    )
    svc.mark_done(user.id, b.id)
    # Backdate creation so it's past the nudge window.
    b.created_at = (date.today() - timedelta(days=10)).isoformat()
    db_session.flush()
    # No matching transactions in the sync.
    svc.reconcile(user.id, [], today=date.today())
    svc.reconcile(user.id, [], today=date.today())  # run twice — nudge must not stack
    nudges = (
        db_session.query(NotificationORM)
        .filter_by(user_id=user.id, type="bridge_nudge")
        .all()
    )
    assert len(nudges) == 1


# ── lifecycle ────────────────────────────────────────────────────────────────


def test_mark_done_is_provisional(db_session, bridge_user):
    user, checking, savings, _ = bridge_user
    svc = AssistedActionService(db_session)
    b = svc.propose(
        user.id, kind="transfer", amount_cents=100, rationale="x",
        source_ref=str(checking.id), dest_ref=str(savings.id),
    )
    svc.acknowledge(user.id, b.id)
    assert svc._own(user.id, b.id).status == "acknowledged"
    svc.mark_done(user.id, b.id)
    assert svc._own(user.id, b.id).status == "confirmed_done"  # NOT verified
    svc.dismiss(user.id, b.id)
    assert svc._own(user.id, b.id).status == "dismissed"


# ── Agent path: validate / confirm / frame (Pillar 2C wiring) ─────────────────


def test_propose_assisted_action_in_both_action_sets():
    from server.src.services.assistant_service import SUPPORTED_ACTIONS, _HANDLED

    assert "propose_assisted_action" in SUPPORTED_ACTIONS
    assert _HANDLED == set(SUPPORTED_ACTIONS)


def test_validate_assisted_action_shape():
    from server.src.services.assistant_service import ActionService, ActionError

    norm, summary = ActionService.validate(
        "propose_assisted_action",
        {
            "kind": "transfer",
            "amount": 340.0,
            "rationale": "House goal is $340 short of this month's target.",
            "source_ref": "1",
            "dest_ref": "2",
        },
    )
    assert norm["kind"] == "transfer"
    assert norm["amount"] == 340.0
    assert "$340.00" in summary

    import pytest as _pytest

    # A transfer needs both endpoints.
    with _pytest.raises(ActionError):
        ActionService.validate(
            "propose_assisted_action",
            {"kind": "transfer", "amount": 10.0, "rationale": "x", "source_ref": "1"},
        )
    # rationale is required.
    with _pytest.raises(ActionError):
        ActionService.validate(
            "propose_assisted_action",
            {"kind": "tax_payment", "amount": 10.0, "source_ref": "1"},
        )


def test_confirm_creates_bridge_but_moves_no_money(client, db_session):
    """Confirming the action creates the Bridge object — nothing moves."""
    from server.src.db.models import AssistedAction as AAORM

    # Sign up + an account to reference.
    headers = _api_auth(client)
    client.post(
        "/api/accounts/",
        json={"name": "Checking", "type": "checking", "balance": 1000.0},
        headers=headers,
    )
    acct_id = client.get("/api/accounts/", headers=headers).json()[-1]["id"]
    client.post(
        "/api/accounts/",
        json={"name": "Savings", "type": "savings", "balance": 0.0},
        headers=headers,
    )
    dest_id = client.get("/api/accounts/", headers=headers).json()[-1]["id"]

    proposal = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "propose_assisted_action",
            "params": {
                "kind": "transfer",
                "amount": 340.0,
                "rationale": "House goal is $340 short.",
                "source_ref": str(acct_id),
                "dest_ref": str(dest_id),
                "how": {"instruction": "Transfer $340 Checking → Savings"},
            },
        },
        headers=headers,
    )
    assert proposal.status_code == 200, proposal.text
    # No Bridge yet (propose mints a token only).
    assert db_session.query(AAORM).count() == 0

    confirm = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": proposal.json()["token"]},
        headers=headers,
    )
    assert confirm.status_code == 200, confirm.text
    db_session.expire_all()
    bridge = db_session.query(AAORM).one()
    assert bridge.kind == "transfer"
    assert bridge.amount_cents == 34000
    assert bridge.status == "proposed"
    assert bridge.settlement_status is None


def test_assisted_action_frame_builder():
    """The Bridge tool output yields an assisted_action SSE frame with the bridge
    display block and a decodable token."""
    import json

    from server.src.services.assistant_service import (
        _assisted_action_frame,
        ActionService,
    )

    token = ActionService.make_token(
        1, "propose_assisted_action", {"kind": "transfer", "amount": 340.0}
    )
    envelope = json.dumps(
        {
            "status": "needs_confirmation",
            "kind": "proposal",
            "action": "propose_assisted_action",
            "summary": "Set up a transfer of $340.00 …",
            "confirm_token": token,
            "bridge": {
                "kind": "transfer",
                "amount": 340.0,
                "rationale": "House goal is $340 short.",
                "source_ref": "1",
                "dest_ref": "2",
                "how": {"instruction": "Transfer $340"},
            },
        }
    )
    frame = _assisted_action_frame({"data": {"output": envelope}})
    assert frame is not None
    assert frame.startswith("event: assisted_action\n")
    body = json.loads(frame.split("data: ", 1)[1])
    assert body["bridge"]["kind"] == "transfer"
    assert ActionService.decode_token(body["confirm_token"])["action"] == (
        "propose_assisted_action"
    )
    # A non-bridge proposal envelope yields no assisted_action frame.
    plain = json.dumps({"kind": "proposal", "action": "create_rule"})
    assert _assisted_action_frame({"data": {"output": plain}}) is None


def _api_auth(client, username="bridgeapi", email="bapi@x.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "Bridge API",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


# ── Router lifecycle endpoints ───────────────────────────────────────────────


def test_bridge_router_lifecycle(client, db_session):
    from server.src.db.models import AssistedAction as AAORM, User as UORM
    from sqlalchemy import select as _select

    headers = _api_auth(client, username="brt", email="brt@x.com")
    user = db_session.execute(
        _select(UORM).where(UORM.username == "brt")
    ).scalar_one()
    bridge = AAORM(
        user_id=user.id,
        kind="transfer",
        amount_cents=34000,
        source_ref="1",
        dest_ref="2",
        rationale="House goal is $340 short.",
        how_json="{}",
        status="proposed",
    )
    db_session.add(bridge)
    db_session.commit()

    # List shows it.
    listed = client.get("/api/assisted-actions/?open_only=true", headers=headers)
    assert listed.status_code == 200
    assert any(b["id"] == bridge.id for b in listed.json())

    # Acknowledge → done → still provisional (not verified).
    assert (
        client.post(
            f"/api/assisted-actions/{bridge.id}/acknowledge/", headers=headers
        ).json()["status"]
        == "acknowledged"
    )
    done = client.post(f"/api/assisted-actions/{bridge.id}/done/", headers=headers)
    assert done.json()["status"] == "confirmed_done"

    # Dismiss resolves it.
    dismissed = client.post(
        f"/api/assisted-actions/{bridge.id}/dismiss/", headers=headers
    )
    assert dismissed.json()["status"] == "dismissed"

    # A foreign / missing id 404s.
    assert (
        client.post(
            "/api/assisted-actions/999999/done/", headers=headers
        ).status_code
        == 404
    )


# ── Reconcile on Plaid sync (the trust loop closes) ──────────────────────────


def test_reconcile_verifies_on_plaid_sync(db_session):
    """A two-leg transfer the user marked done is VERIFIED when the next Plaid
    sync imports both legs (Pillar 2C — the loop closes deterministically)."""
    from datetime import date
    from unittest.mock import MagicMock, patch

    from server.src.databridge.plaid_client import SyncResult
    from server.src.db.models import (
        Account as AcctORM,
        AssistedAction as AAORM,
        Token as TokenORM,
        User as UORM,
    )
    from server.src.models import UserInDB
    from server.src.services import plaid_crypto
    from server.src.services.plaid_service import PlaidService

    user = UORM(username="rsync", full_name="R", email="r@x.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    token = TokenORM(
        user_id=user.id, name="Bank", key=plaid_crypto.encrypt("access-fake")
    )
    checking = AcctORM(
        name="Checking", type="depository", balance=0,
        plaid_account_id="acct_chk", user_id=user.id,
    )
    savings = AcctORM(
        name="Savings", type="depository", balance=0,
        plaid_account_id="acct_sav", user_id=user.id,
    )
    db_session.add_all([token, checking, savings])
    db_session.flush()

    bridge = AAORM(
        user_id=user.id, kind="transfer", amount_cents=34000,
        source_ref=str(checking.id), dest_ref=str(savings.id),
        rationale="House goal is $340 short.", how_json="{}",
        status="confirmed_done",  # user said "I did it" — provisional
        created_at=date.today().isoformat(),
    )
    db_session.add(bridge)
    db_session.flush()

    user_indb = UserInDB(
        id=user.id, username=user.username, email=user.email,
        full_name=user.full_name, disabled=False, hashed_password="x",
    )
    today = date.today().isoformat()
    with patch("server.src.services.plaid_service.PlaidClient") as MockPDB:
        mock_plaid = MagicMock()
        MockPDB.return_value = wire_plaid_pages(mock_plaid)
        mock_plaid.sync_transactions.return_value = SyncResult(
            added=[
                # Checking debit (+ = money out) and Savings credit (- = money in).
                _plaid_txn("leg_out", "Transfer to Savings", 340.00, today, "acct_chk"),
                _plaid_txn("leg_in", "Transfer from Checking", -340.00, today, "acct_sav"),
            ],
            modified=[], removed=[], next_cursor="c1",
        )
        mock_plaid.get_balance.return_value = []
        PlaidService(db_session).sync_all_tokens(user_indb)
        db_session.flush()

    db_session.refresh(bridge)
    assert bridge.status == "verified"


def _plaid_txn(txn_id, name, amount, d, account_id):
    return {
        "transaction_id": txn_id,
        "name": name,
        "amount": amount,
        "date": d,
        "category": ["Transfer"],
        "personal_finance_category": None,
        "account_id": account_id,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2a–2b — rail origination (SANDBOX ONLY, flag-off by default)
# docs/PHASE2A-SANDBOX-IMPLEMENTATION.md
# ══════════════════════════════════════════════════════════════════════════════

from server.src.services import action_tokens
from server.src.services.assisted_action_service import EXECUTE_TOKEN_ACTION
from server.src.services.rails.base import (
    FundingDest,
    FundingSource,
    OriginationResult,
    RailError,
    UnresolvedFundingResolver,
)
from server.src.settings import settings as _settings


@pytest.fixture
def rail_on(monkeypatch):
    """Enable rail origination (sandbox) for a test + set a webhook secret."""
    monkeypatch.setattr(_settings, "rail_origination_enabled", True)
    monkeypatch.setattr(_settings, "increase_webhook_secret", "whsec_test")
    yield


class FakeRail:
    """In-memory ``RailAdapter`` double — records originate() calls; never a live
    sandbox call. Can be told to raise ``RailError`` or to return a fixed ref."""

    name = "increase"

    def __init__(self, *, ref="txn_fake", raise_error=False):
        self.calls = []
        self._ref = ref
        self._raise = raise_error

    def originate(self, *, amount_cents, source, dest, idempotency_key, memo):
        self.calls.append(
            {
                "amount_cents": amount_cents,
                "source": source,
                "dest": dest,
                "idempotency_key": idempotency_key,
                "memo": memo,
            }
        )
        if self._raise:
            raise RailError("sandbox boom")
        return OriginationResult(
            rail="increase", rail_ref=self._ref, settlement_status="submitted"
        )


class FakeFunding:
    """Resolves every account to a deterministic sandbox handle (the happy path)."""

    def resolve_source(self, rail, account_ref):
        return FundingSource(rail=rail, external_id=f"src_{account_ref}")

    def resolve_dest(self, rail, account_ref):
        return FundingDest(rail=rail, external_id=f"dst_{account_ref}")


def _exec_token(user_id, action_id, amount_cents):
    return action_tokens.make_token(
        user_id,
        EXECUTE_TOKEN_ACTION,
        {"action_id": action_id, "amount_cents": amount_cents},
    )


def _acked_transfer(svc, user, checking, savings, goal=None, amount=34000):
    how = {"goal_id": goal.id} if goal is not None else {}
    b = svc.propose(
        user.id, kind="transfer", amount_cents=amount, rationale="x",
        source_ref=str(checking.id), dest_ref=str(savings.id), how=how,
    )
    svc.acknowledge(user.id, b.id)
    return b


# ── config defaults ───────────────────────────────────────────────────────────


def test_rail_origination_flag_defaults_off():
    """Fresh settings: flag OFF and the base URL is the Increase sandbox host."""
    from server.src.settings import Settings

    s = Settings(
        groq_api_key="x", jwt_secret_key="z" * 40, jwt_algorithm="HS256",
        tavily_api_key="x", plaid_client_id="x", plaid_client_secret="x",
        plaid_environment="sandbox",
    )
    assert s.rail_origination_enabled is False
    assert s.increase_sandbox_base_url == "https://sandbox.increase.com"
    assert s.rail_per_txn_cap_cents == 50_000
    assert s.rail_daily_cap_cents == 100_000


# ── flag gate ─────────────────────────────────────────────────────────────────


def test_execute_raises_when_flag_off(db_session, bridge_user):
    """With the flag off (default), execute() raises before any rail call."""
    user, checking, savings, _ = bridge_user
    svc = AssistedActionService(db_session)
    b = _acked_transfer(svc, user, checking, savings)
    with pytest.raises(RailError):
        svc.execute(
            user.id, b.id, rail=FakeRail(),
            confirmation_token=_exec_token(user.id, b.id, b.amount_cents),
            funding=FakeFunding(),
        )


def test_execute_endpoint_404s_when_flag_off(client, db_session):
    """The execute + token endpoints do not exist unless the flag is on."""
    headers = _api_auth(client, username="exoff", email="exoff@x.com")
    assert client.post(
        "/api/assisted-actions/1/execute/",
        json={"confirmation_token": "x"}, headers=headers,
    ).status_code == 404
    assert client.post(
        "/api/assisted-actions/1/execute-token/", headers=headers
    ).status_code == 404


# ── happy path: originate → submitted (never verified, never mirrored) ─────────


def test_execute_submits_without_verifying_or_mirroring(db_session, bridge_user, rail_on):
    user, checking, savings, goal = bridge_user
    svc = AssistedActionService(db_session)
    b = _acked_transfer(svc, user, checking, savings, goal=goal)
    rail = FakeRail(ref="txn_1")
    out = svc.execute(
        user.id, b.id, rail=rail,
        confirmation_token=_exec_token(user.id, b.id, b.amount_cents),
        funding=FakeFunding(),
    )
    assert out.settlement_status == "submitted"
    assert out.rail == "increase"
    assert out.rail_ref == "txn_1"
    assert out.status == "acknowledged"  # NEVER verified by execute()
    db_session.refresh(goal)
    assert goal.progress == 0  # NEVER mirrored by execute()
    # The rail idempotency key is the Bridge's stable verify_ref.
    assert rail.calls[0]["idempotency_key"] == b.verify_ref
    assert len(rail.calls) == 1


# ── idempotency: a replayed execute originates at most once ────────────────────


def test_execute_is_idempotent(db_session, bridge_user, rail_on):
    user, checking, savings, _ = bridge_user
    svc = AssistedActionService(db_session)
    b = _acked_transfer(svc, user, checking, savings)
    rail = FakeRail(ref="txn_2")
    svc.execute(
        user.id, b.id, rail=rail,
        confirmation_token=_exec_token(user.id, b.id, b.amount_cents),
        funding=FakeFunding(),
    )
    # Second call short-circuits at the idempotency guard (before the token).
    again = svc.execute(
        user.id, b.id, rail=rail, confirmation_token="",
        funding=FakeFunding(),
    )
    assert again.settlement_status == "submitted"
    assert len(rail.calls) == 1  # originated exactly once


# ── guard rejections ──────────────────────────────────────────────────────────


def test_execute_rejects_non_originable_kind(db_session, bridge_user, rail_on):
    user, checking, _, _ = bridge_user
    svc = AssistedActionService(db_session)
    b = svc.propose(
        user.id, kind="bill_payment", amount_cents=5000, rationale="x",
        source_ref=str(checking.id),
    )
    svc.acknowledge(user.id, b.id)
    with pytest.raises(RailError):
        svc.execute(
            user.id, b.id, rail=FakeRail(),
            confirmation_token=_exec_token(user.id, b.id, 5000),
            funding=FakeFunding(),
        )


def test_execute_rejects_unengaged_status(db_session, bridge_user, rail_on):
    """A bare 'proposed' Bridge (user never engaged it) is not executable."""
    user, checking, savings, _ = bridge_user
    svc = AssistedActionService(db_session)
    b = svc.propose(
        user.id, kind="transfer", amount_cents=34000, rationale="x",
        source_ref=str(checking.id), dest_ref=str(savings.id),
    )
    with pytest.raises(RailError):
        svc.execute(
            user.id, b.id, rail=FakeRail(),
            confirmation_token=_exec_token(user.id, b.id, 34000),
            funding=FakeFunding(),
        )


def test_execute_rejects_over_per_txn_cap(db_session, bridge_user, rail_on):
    user, checking, savings, _ = bridge_user
    svc = AssistedActionService(db_session)
    b = _acked_transfer(svc, user, checking, savings, amount=60000)  # > $500 cap
    rail = FakeRail()
    with pytest.raises(RailError):
        svc.execute(
            user.id, b.id, rail=rail,
            confirmation_token=_exec_token(user.id, b.id, 60000),
            funding=FakeFunding(),
        )
    assert rail.calls == []  # never reached the rail
    db_session.refresh(b)
    assert b.settlement_status is None


def test_execute_rejects_over_daily_cap(db_session, bridge_user, rail_on, monkeypatch):
    """Two same-day originations that together exceed the rolling daily cap; the
    second is refused. ``today`` is injected (determinism — no Date.now())."""
    monkeypatch.setattr(_settings, "rail_daily_cap_cents", 50_000)
    user, checking, savings, _ = bridge_user
    svc = AssistedActionService(db_session)
    day = date(2026, 6, 26)
    # Distinct amounts → distinct verify_refs → two distinct Bridges (no dedup).
    a = _acked_transfer(svc, user, checking, savings, amount=40000)
    svc.execute(
        user.id, a.id, rail=FakeRail(ref="d1"),
        confirmation_token=_exec_token(user.id, a.id, 40000),
        funding=FakeFunding(), today=day,
    )
    b = _acked_transfer(svc, user, checking, savings, amount=30000)
    with pytest.raises(RailError):  # 40000 + 30000 > 50000
        svc.execute(
            user.id, b.id, rail=FakeRail(ref="d2"),
            confirmation_token=_exec_token(user.id, b.id, 30000),
            funding=FakeFunding(), today=day,
        )
    # A DIFFERENT day resets the rolling total → the second txn now succeeds.
    svc.execute(
        user.id, b.id, rail=FakeRail(ref="d2"),
        confirmation_token=_exec_token(user.id, b.id, 30000),
        funding=FakeFunding(), today=date(2026, 6, 27),
    )
    db_session.refresh(b)
    assert b.settlement_status == "submitted"


def test_execute_rejects_missing_funding_source(db_session, bridge_user, rail_on):
    """The 2a resolver raises for every account → execute() falls back to manual."""
    user, checking, savings, _ = bridge_user
    svc = AssistedActionService(db_session)
    b = _acked_transfer(svc, user, checking, savings)
    rail = FakeRail()
    with pytest.raises(RailError):
        svc.execute(
            user.id, b.id, rail=rail,
            confirmation_token=_exec_token(user.id, b.id, b.amount_cents),
            funding=UnresolvedFundingResolver(),
        )
    assert rail.calls == []
    db_session.refresh(b)
    assert b.settlement_status is None


def test_execute_rejects_mismatched_token(db_session, bridge_user, rail_on):
    """A confirmation token bound to a different amount is rejected (guard 6)."""
    user, checking, savings, _ = bridge_user
    svc = AssistedActionService(db_session)
    b = _acked_transfer(svc, user, checking, savings, amount=34000)
    with pytest.raises(RailError):
        svc.execute(
            user.id, b.id, rail=FakeRail(),
            confirmation_token=_exec_token(user.id, b.id, 99999),  # wrong amount
            funding=FakeFunding(),
        )


def test_confirmation_token_is_single_use(db_session, bridge_user, rail_on):
    """The same token cannot be consumed twice (one-use jti replay guard)."""
    user, checking, savings, _ = bridge_user
    svc = AssistedActionService(db_session)
    b = _acked_transfer(svc, user, checking, savings)
    token = _exec_token(user.id, b.id, b.amount_cents)
    svc._consume_confirmation_token(user.id, b.id, b.amount_cents, token)
    with pytest.raises(RailError):
        svc._consume_confirmation_token(user.id, b.id, b.amount_cents, token)


# ── origination failure leaves no half-state ──────────────────────────────────


def test_origination_failure_leaves_no_half_state(db_session, bridge_user, rail_on):
    user, checking, savings, _ = bridge_user
    svc = AssistedActionService(db_session)
    b = _acked_transfer(svc, user, checking, savings)
    with pytest.raises(RailError):
        svc.execute(
            user.id, b.id, rail=FakeRail(raise_error=True),
            confirmation_token=_exec_token(user.id, b.id, b.amount_cents),
            funding=FakeFunding(),
        )
    db_session.refresh(b)
    assert b.settlement_status is None       # not advanced
    assert b.status == "acknowledged"        # status unchanged
    assert b.rail is None and b.rail_ref is None
    import json as _json
    assert "error" in _json.loads(b.settlement_detail_json)  # failure recorded


# ── settlement webhook: settled mirrors once ──────────────────────────────────


def _submit(svc, user, b, ref):
    svc.execute(
        user.id, b.id, rail=FakeRail(ref=ref),
        confirmation_token=_exec_token(user.id, b.id, b.amount_cents),
        funding=FakeFunding(),
    )


def test_settled_webhook_mirrors_once(db_session, bridge_user, rail_on):
    user, checking, savings, goal = bridge_user
    svc = AssistedActionService(db_session)
    b = _acked_transfer(svc, user, checking, savings, goal=goal)
    _submit(svc, user, b, "txn_s1")

    svc.apply_settlement("increase", "txn_s1", "settled", event_id="evt_1")
    db_session.refresh(b)
    db_session.refresh(goal)
    assert b.settlement_status == "settled"
    assert b.status == "verified"
    assert goal.progress == 34000
    # A redelivered identical webhook is a no-op (no double mirror).
    svc.apply_settlement("increase", "txn_s1", "settled", event_id="evt_1")
    db_session.refresh(goal)
    assert goal.progress == 34000


# ── settlement webhook: returned after settled reverses to the cent ───────────


def test_returned_after_settled_reverses_mirror(db_session, bridge_user, rail_on):
    user, checking, savings, goal = bridge_user
    svc = AssistedActionService(db_session)
    b = _acked_transfer(svc, user, checking, savings, goal=goal)
    _submit(svc, user, b, "txn_r1")
    svc.apply_settlement("increase", "txn_r1", "settled", event_id="evt_a")
    db_session.refresh(goal)
    assert goal.progress == 34000

    # ACH return days later → reverse the mirror exactly, clear the flag.
    svc.apply_settlement("increase", "txn_r1", "returned", event_id="evt_b")
    db_session.refresh(b)
    db_session.refresh(goal)
    assert b.settlement_status == "returned"
    assert goal.progress == 0  # reversed to the cent, never negative
    import json as _json
    assert _json.loads(b.how_json).get("_mirrored") is False
    # A replayed return is a no-op (progress stays at 0, not negative).
    svc.apply_settlement("increase", "txn_r1", "returned", event_id="evt_c")
    db_session.refresh(goal)
    assert goal.progress == 0


def test_failed_webhook_reverses_nothing(db_session, bridge_user, rail_on):
    user, checking, savings, goal = bridge_user
    svc = AssistedActionService(db_session)
    b = _acked_transfer(svc, user, checking, savings, goal=goal)
    _submit(svc, user, b, "txn_f1")
    svc.apply_settlement("increase", "txn_f1", "failed", event_id="evt_f")
    db_session.refresh(b)
    db_session.refresh(goal)
    assert b.settlement_status == "failed"
    assert b.status == "acknowledged"  # actionable again; nothing mirrored
    assert goal.progress == 0


# ── convergence with Plaid reconcile (both reach verified exactly once) ────────


def test_convergence_plaid_first_then_settled_webhook(db_session, bridge_user, rail_on):
    user, checking, savings, goal = bridge_user
    svc = AssistedActionService(db_session)
    b = _acked_transfer(svc, user, checking, savings, goal=goal)
    _submit(svc, user, b, "txn_c1")
    # Plaid sees both legs first → reconcile verifies + mirrors.
    svc.reconcile(user.id, [_txn(-34000, checking.id), _txn(+34000, savings.id)])
    db_session.refresh(b)
    db_session.refresh(goal)
    assert b.status == "verified"
    assert goal.progress == 34000
    # Later settled webhook is a no-op (already resolved; no double mirror).
    svc.apply_settlement("increase", "txn_c1", "settled", event_id="evt_c1")
    db_session.refresh(goal)
    assert goal.progress == 34000


def test_convergence_webhook_first_then_reconcile(db_session, bridge_user, rail_on):
    user, checking, savings, goal = bridge_user
    svc = AssistedActionService(db_session)
    b = _acked_transfer(svc, user, checking, savings, goal=goal)
    _submit(svc, user, b, "txn_c2")
    # Settled webhook resolves first → verify + mirror.
    svc.apply_settlement("increase", "txn_c2", "settled", event_id="evt_c2")
    db_session.refresh(b)
    db_session.refresh(goal)
    assert b.status == "verified"
    assert goal.progress == 34000
    # Later reconcile is a no-op (the Bridge is no longer open).
    assert svc.reconcile(
        user.id, [_txn(-34000, checking.id), _txn(+34000, savings.id)]
    ) == []
    db_session.refresh(goal)
    assert goal.progress == 34000


def test_apply_settlement_unknown_ref_ignored(db_session, bridge_user, rail_on):
    svc = AssistedActionService(db_session)
    assert svc.apply_settlement("increase", "nope", "settled") is None


# ── webhook security (HMAC + endpoint flag gate) ──────────────────────────────


def test_webhook_verify_hmac():
    import json as _json

    from server.src.services.rails.webhook import (
        SettlementEvent,
        WebhookVerificationError,
        sign,
        verify,
    )

    body = _json.dumps(
        {"id": "evt_1", "rail": "increase", "rail_ref": "txn_1", "event": "settled"}
    ).encode()
    good = sign(body, "whsec_test")
    evt = verify(body, good, "whsec_test")
    assert isinstance(evt, SettlementEvent)
    assert evt.rail_ref == "txn_1" and evt.event == "settled"
    # Wrong signature, missing header, bad event, no secret → all rejected.
    with pytest.raises(WebhookVerificationError):
        verify(body, "deadbeef", "whsec_test")
    with pytest.raises(WebhookVerificationError):
        verify(body, None, "whsec_test")
    with pytest.raises(WebhookVerificationError):
        verify(body, good, "")
    bad_event = _json.dumps(
        {"id": "e", "rail": "increase", "rail_ref": "t", "event": "bogus"}
    ).encode()
    with pytest.raises(WebhookVerificationError):
        verify(bad_event, sign(bad_event, "whsec_test"), "whsec_test")


def test_webhook_endpoint_flag_gate_and_signature(client, rail_on):
    import json as _json

    from server.src.services.rails.webhook import SIGNATURE_HEADER, sign

    body = _json.dumps(
        {"id": "evt_1", "rail": "increase", "rail_ref": "txn_x", "event": "settled"}
    )
    raw = body.encode()
    # Bad signature → 401.
    bad = client.post(
        "/api/rails/webhook", content=raw,
        headers={SIGNATURE_HEADER: "deadbeef", "content-type": "application/json"},
    )
    assert bad.status_code == 401
    # Good signature, unknown ref → 200 (ignored, the rail won't retry).
    good = client.post(
        "/api/rails/webhook", content=raw,
        headers={
            SIGNATURE_HEADER: sign(raw, "whsec_test"),
            "content-type": "application/json",
        },
    )
    assert good.status_code == 200


def test_webhook_endpoint_404s_when_flag_off(client):
    assert client.post(
        "/api/rails/webhook", content=b"{}",
        headers={"content-type": "application/json"},
    ).status_code == 404


# ── execute endpoint (real wiring; funding-unresolved → manual fallback) ───────


def test_execute_endpoint_mints_token_and_falls_back_to_manual(
    client, db_session, rail_on
):
    from server.src.db.models import AssistedAction as AAORM, User as UORM
    from sqlalchemy import select as _select

    headers = _api_auth(client, username="exep", email="exep@x.com")
    user = db_session.execute(
        _select(UORM).where(UORM.username == "exep")
    ).scalar_one()
    bridge = AAORM(
        user_id=user.id, kind="transfer", amount_cents=34000,
        source_ref="1", dest_ref="2", rationale="x", how_json="{}",
        status="acknowledged",
    )
    db_session.add(bridge)
    db_session.commit()

    # Mint the single-use confirmation token server-side.
    minted = client.post(
        f"/api/assisted-actions/{bridge.id}/execute-token/", headers=headers
    )
    assert minted.status_code == 200, minted.text
    token = minted.json()["confirmation_token"]

    # Execute: the 2a funding resolver always raises → 422 manual fallback.
    resp = client.post(
        f"/api/assisted-actions/{bridge.id}/execute/",
        json={"confirmation_token": token}, headers=headers,
    )
    assert resp.status_code == 422, resp.text
    db_session.expire_all()
    refreshed = db_session.get(AAORM, bridge.id)
    assert refreshed.settlement_status is None  # nothing half-done


# ── MCP / assistant surface exclusion (the model proposes, never sends) ───────


def test_execute_absent_from_mcp_and_assistant_surface():
    import asyncio

    from server.src.mcp.tools import mcp
    from server.src.services.assistant_service import SUPPORTED_ACTIONS

    tool_names = [t.name for t in asyncio.run(mcp.list_tools())]
    assert not any("execute" in n for n in tool_names)
    assert "execute_assisted_action" not in SUPPORTED_ACTIONS
    assert not any("execute" in a for a in SUPPORTED_ACTIONS)
