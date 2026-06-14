"""Assistant write actions confirmation gate tests.

The safety-critical invariant: the model/tool only *proposes*; a mutation is
applied **only** after an explicit confirm call. These tests exercise the gate
end to end via the API (no Groq needed) plus the tool layer directly.
"""

from sqlalchemy import select

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Income as IncomeORM,
    Goal as GoalORM,
)
from server.src.services.assistant_service import (
    ActionService,
    ActionError,
    AddTransactionTool,
    SUPPORTED_ACTIONS,
    _HANDLED,
)
import pytest


# ── Helpers ────────────────────────────────────────────────────────────────


def _auth_header(client, username="awuser", email="aw@example.com"):
    resp = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "AW User",
            "password": "Test-password1",
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _create_account(client, headers, balance=1000.00):
    resp = client.post(
        "/api/accounts/",
        json={"name": "Checking", "type": "checking", "balance": balance},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return client.get("/api/accounts/", headers=headers).json()[-1]["id"]


def _user_id(db_session, username="awuser"):
    from server.src.db.models import User as UserORM

    return db_session.execute(
        select(UserORM.id).where(UserORM.username == username)
    ).scalar_one()


# ── Propose does not write ───────────────────────────────────────────────────


def test_propose_does_not_write(client, db_session):
    headers = _auth_header(client)
    acct = _create_account(client, headers)

    resp = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "add_transaction",
            "params": {
                "account_id": acct,
                "title": "Coffee",
                "amount": 25.00,
                "date": "2026-05-01",
                "category": "Food and Drink",
            },
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["action"] == "add_transaction"
    assert body["summary"]
    assert body["token"]

    # Nothing committed yet.
    count = db_session.execute(select(ExpenseORM)).scalars().all()
    assert count == []


# ── Confirm executes ─────────────────────────────────────────────────────────


def test_confirm_creates_transaction_and_adjusts_balance(client, db_session):
    headers = _auth_header(client)
    acct = _create_account(client, headers, balance=1000.00)

    proposal = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "add_transaction",
            "params": {
                "account_id": acct,
                "title": "Coffee",
                "amount": 25.00,
                "date": "2026-05-01",
                "category": "Food and Drink",
            },
        },
        headers=headers,
    ).json()

    confirm = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": proposal["token"]},
        headers=headers,
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["status"] == "confirmed"

    db_session.expire_all()
    expense = db_session.execute(select(ExpenseORM)).scalar_one()
    assert expense.title == "Coffee"
    assert expense.amount == 2500  # cents
    assert expense.category == "Food and Drink"

    # Expense subtracts from the account balance: 1000 - 25 = 975.
    balance = db_session.execute(
        select(AccountORM.balance).where(AccountORM.id == acct)
    ).scalar_one()
    assert balance == 97500


def test_confirm_add_goal(client, db_session):
    headers = _auth_header(client)
    proposal = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "add_goal",
            "params": {
                "name": "Emergency Fund",
                "amount": 5000.00,
                "date": "2026-12-31",
            },
        },
        headers=headers,
    ).json()

    confirm = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": proposal["token"]},
        headers=headers,
    )
    assert confirm.status_code == 200, confirm.text

    db_session.expire_all()
    goal = db_session.execute(select(GoalORM)).scalar_one()
    assert goal.name == "Emergency Fund"
    assert goal.amount == 500000  # cents


def test_confirm_recategorize(client, db_session):
    headers = _auth_header(client)
    acct = _create_account(client, headers)
    client.post(
        "/api/expenses/",
        json={
            "account_id": acct,
            "title": "Mystery Charge",
            "amount": 12.00,
            "date": "2026-05-01",
            "category": "Other",
        },
        headers=headers,
    )
    db_session.expire_all()
    expense_id = db_session.execute(select(ExpenseORM.id)).scalar_one()

    proposal = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "recategorize_transaction",
            "params": {"transaction_id": expense_id, "category": "Entertainment"},
        },
        headers=headers,
    ).json()
    confirm = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": proposal["token"]},
        headers=headers,
    )
    assert confirm.status_code == 200, confirm.text

    db_session.expire_all()
    cat = db_session.execute(
        select(ExpenseORM.category).where(ExpenseORM.id == expense_id)
    ).scalar_one()
    assert cat == "Entertainment"


def test_confirm_recategorize_canonicalizes_category(client, db_session):
    """Regression: recategorize must canonicalize the label like manual create,
    so a non-canonical/Plaid-coded string can't mint a ghost category that
    breaks budget matching and reports."""
    headers = _auth_header(client)
    acct = _create_account(client, headers)
    client.post(
        "/api/expenses/",
        json={
            "account_id": acct,
            "title": "Mystery Charge",
            "amount": 12.00,
            "date": "2026-05-01",
            "category": "Other",
        },
        headers=headers,
    )
    db_session.expire_all()
    expense_id = db_session.execute(select(ExpenseORM.id)).scalar_one()

    proposal = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "recategorize_transaction",
            # Plaid PFC primary code — must fold to the canonical "Food and Drink".
            "params": {"transaction_id": expense_id, "category": "food_and_drink"},
        },
        headers=headers,
    ).json()
    confirm = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": proposal["token"]},
        headers=headers,
    )
    assert confirm.status_code == 200, confirm.text

    db_session.expire_all()
    cat = db_session.execute(
        select(ExpenseORM.category).where(ExpenseORM.id == expense_id)
    ).scalar_one()
    assert cat == "Food and Drink"  # canonicalized, not the raw "food_and_drink"


# ── Gate rejections ──────────────────────────────────────────────────────────


def test_confirm_token_is_single_use(client, db_session):
    """A confirm token must commit at most once (replay / double click guard)."""
    headers = _auth_header(client)
    acct = _create_account(client, headers, balance=1000.00)
    proposal = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "add_transaction",
            "params": {
                "account_id": acct,
                "title": "Coffee",
                "amount": 25.00,
                "date": "2026-05-01",
                "category": "Food and Drink",
            },
        },
        headers=headers,
    ).json()

    first = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": proposal["token"]},
        headers=headers,
    )
    second = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": proposal["token"]},
        headers=headers,
    )
    assert first.status_code == 200
    assert second.status_code == 409  # replay rejected

    db_session.expire_all()
    expenses = db_session.execute(select(ExpenseORM)).scalars().all()
    assert len(expenses) == 1  # exactly one write, not two


def test_recategorize_ambiguous_id_rejected(client, db_session):
    """When an expense and income share an id, an untyped recategorize errors."""
    headers = _auth_header(client)
    acct = _create_account(client, headers)
    client.post(
        "/api/expenses/",
        json={
            "account_id": acct,
            "title": "Charge",
            "amount": 10.0,
            "date": "2026-05-01",
            "category": "Other",
        },
        headers=headers,
    )
    client.post(
        "/api/income/",
        json={
            "account_id": acct,
            "title": "Paycheck",
            "amount": 500.0,
            "date": "2026-05-01",
            "category": "Salary",
        },
        headers=headers,
    )
    db_session.expire_all()
    exp_id = db_session.execute(select(ExpenseORM.id)).scalars().first()
    inc_id = db_session.execute(select(IncomeORM.id)).scalars().first()
    assert exp_id == inc_id  # the id spaces overlap

    proposal = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "recategorize_transaction",
            "params": {"transaction_id": exp_id, "category": "Food and Drink"},
        },
        headers=headers,
    ).json()
    confirm = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": proposal["token"]},
        headers=headers,
    )
    assert confirm.status_code == 400  # ambiguous → refuse to guess

    # Disambiguating with an explicit type succeeds.
    proposal2 = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "recategorize_transaction",
            "params": {
                "transaction_id": inc_id,
                "type": "income",
                "category": "Bonus",
            },
        },
        headers=headers,
    ).json()
    confirm2 = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": proposal2["token"]},
        headers=headers,
    )
    assert confirm2.status_code == 200


def test_unknown_action_rejected(client):
    headers = _auth_header(client)
    resp = client.post(
        "/api/assistant/actions/propose/",
        json={"action": "delete_everything", "params": {}},
        headers=headers,
    )
    assert resp.status_code == 400


def test_invalid_amount_rejected(client):
    headers = _auth_header(client)
    resp = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "add_goal",
            "params": {"name": "Bad", "amount": -5, "date": "2026-01-01"},
        },
        headers=headers,
    )
    assert resp.status_code == 400


def test_invalid_confirm_token_rejected(client):
    headers = _auth_header(client)
    resp = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": "not-a-real-token"},
        headers=headers,
    )
    assert resp.status_code == 400


def test_auth_token_cannot_confirm(client):
    """A session access token (no action ``typ``) must not commit a change."""
    headers = _auth_header(client)
    session_token = headers["Authorization"].split(" ", 1)[1]
    resp = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": session_token},
        headers=headers,
    )
    assert resp.status_code == 400


def test_cross_user_token_rejected(client, db_session):
    headers_a = _auth_header(client, username="alice", email="alice@example.com")
    acct_a = _create_account(client, headers_a)
    proposal = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "add_transaction",
            "params": {
                "account_id": acct_a,
                "title": "Coffee",
                "amount": 5.0,
                "date": "2026-05-01",
                "category": "Food and Drink",
            },
        },
        headers=headers_a,
    ).json()

    headers_b = _auth_header(client, username="bob", email="bob@example.com")
    resp = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": proposal["token"]},
        headers=headers_b,
    )
    assert resp.status_code == 403


# ── Tool layer: the LLM tool only proposes, never writes ─────────────────────


def test_write_tool_only_proposes(client, db_session):
    import json

    tool = AddTransactionTool(user_id=999)
    out = tool._run(
        account_id=1,
        title="Coffee",
        amount=25.0,
        date="2026-05-01",
        category="Food and Drink",
    )
    payload = json.loads(out)
    assert payload["status"] == "needs_confirmation"
    assert payload["confirm_token"]
    # The tool produced a valid, decodable proposal token but wrote nothing.
    claims = ActionService.decode_token(payload["confirm_token"])
    assert claims["action"] == "add_transaction"
    assert db_session.execute(select(ExpenseORM)).scalars().all() == []


# ── C5: allowlist is the single, enforced source of truth ────────────────────


def test_validate_rejects_unlisted_actions():
    """The two money-moving extras must NOT be reachable through validate.

    ``create_allocation`` / ``whatif_commit`` have handler branches in the code
    but are deliberately out of ``SUPPORTED_ACTIONS``/``_HANDLED``: the top-of-
    ``validate`` allowlist guard rejects them before any param coercion.
    """
    for action in ("create_allocation", "whatif_commit"):
        with pytest.raises(ActionError) as exc:
            ActionService.validate(action, {"goal_id": 1, "amount": 10.0})
        assert "Unsupported action" in str(exc.value)
        assert action in str(exc.value)


def test_supported_actions_matches_handlers():
    """Anti-drift: the explicit handled-set mirrors the advertised allowlist.

    A dev adding a handler branch (or an allowlist entry) without updating both
    sets fails here. Explicit-set comparison — no AST parsing of method bodies.
    """
    assert _HANDLED == set(SUPPORTED_ACTIONS)


def test_propose_unlisted_action_400(client):
    """A disabled money-moving action is rejected at the propose endpoint."""
    headers = _auth_header(client)
    resp = client.post(
        "/api/assistant/actions/propose/",
        json={"action": "whatif_commit", "params": {"goal_id": 1, "amount": 10.0}},
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
    assert "Unsupported action" in resp.json()["detail"]


def test_propose_confirm_happy_path(client, db_session):
    """End-to-end through the real endpoints: propose → confirm → row + balance."""
    headers = _auth_header(client)
    acct = _create_account(client, headers, balance=1000.00)
    proposal = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "add_transaction",
            "params": {
                "account_id": acct,
                "title": "Lunch",
                "amount": 30.00,
                "date": "2026-05-02",
                "category": "Food and Drink",
            },
        },
        headers=headers,
    )
    assert proposal.status_code == 200, proposal.text
    token = proposal.json()["token"]

    confirm = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": token},
        headers=headers,
    )
    assert confirm.status_code == 200, confirm.text

    db_session.expire_all()
    expense = db_session.execute(select(ExpenseORM)).scalar_one()
    assert expense.title == "Lunch"
    assert expense.amount == 3000  # cents
    balance = db_session.execute(
        select(AccountORM.balance).where(AccountORM.id == acct)
    ).scalar_one()
    assert balance == 97000  # 1000 - 30


def test_confirm_token_replay_409(client, db_session):
    """Confirming the same token twice → second is 409 (reserve_jti backstop)."""
    headers = _auth_header(client)
    acct = _create_account(client, headers, balance=1000.00)
    token = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "add_transaction",
            "params": {
                "account_id": acct,
                "title": "Coffee",
                "amount": 5.00,
                "date": "2026-05-01",
                "category": "Food and Drink",
            },
        },
        headers=headers,
    ).json()["token"]

    first = client.post(
        "/api/assistant/actions/confirm/", json={"token": token}, headers=headers
    )
    second = client.post(
        "/api/assistant/actions/confirm/", json={"token": token}, headers=headers
    )
    assert first.status_code == 200
    assert second.status_code == 409
    db_session.expire_all()
    assert len(db_session.execute(select(ExpenseORM)).scalars().all()) == 1


def test_confirm_token_wrong_user_403(client):
    """A token minted for user A cannot be confirmed while authed as B."""
    headers_a = _auth_header(client, username="useraa", email="aa@example.com")
    acct_a = _create_account(client, headers_a)
    token = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "add_transaction",
            "params": {
                "account_id": acct_a,
                "title": "Coffee",
                "amount": 5.0,
                "date": "2026-05-01",
                "category": "Food and Drink",
            },
        },
        headers=headers_a,
    ).json()["token"]

    headers_b = _auth_header(client, username="userbb", email="bb@example.com")
    resp = client.post(
        "/api/assistant/actions/confirm/", json={"token": token}, headers=headers_b
    )
    assert resp.status_code == 403


def test_propose_rate_limited(client, rate_limited, monkeypatch):
    """With a 1/minute limit, the 2nd propose in the window → 429.

    Uses the Step 02 ``rate_limited`` fixture (flips ``limiter.enabled``, the
    instance, never the setting). The limit is read live via the callable, so
    monkeypatching the setting tightens the live decorator.
    """
    from server.src import settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "assistant_rate_limit", "1/minute")
    headers = _auth_header(client)

    body = {
        "action": "add_goal",
        "params": {"name": "Fund", "amount": 100.0, "date": "2026-12-31"},
    }
    first = client.post(
        "/api/assistant/actions/propose/", json=body, headers=headers
    )
    second = client.post(
        "/api/assistant/actions/propose/", json=body, headers=headers
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 429


def test_add_transaction_rejects_plaid_account(client, db_session):
    """add_transaction onto a Plaid-synced account is refused (422), not double-counted.

    Pins the cross-step 06↔08 coupling: the guard reuses the transfer endpoint's
    ``_is_plaid_managed`` (name-keyed today, plaid_account_id after Step 08), so
    if Step 08's de-name-keying breaks the guard this test fails. A manual
    account still works.
    """
    from server.src.db.models import Token as TokenORM

    headers = _auth_header(client)
    # A manually-managed account works.
    manual = _create_account(client, headers, balance=1000.00)

    # A Plaid-linked account: same name + user as a Token row (the link key).
    client.post(
        "/api/accounts/",
        json={"name": "Plaid Checking", "type": "checking", "balance": 500.0},
        headers=headers,
    )
    plaid_acct = client.get("/api/accounts/", headers=headers).json()[-1]["id"]
    uid = _user_id(db_session, username="awuser")
    db_session.add(TokenORM(user_id=uid, name="Plaid Checking", key="tok"))
    db_session.commit()

    # Proposing onto the Plaid account is refused at propose time with 422 + a
    # human explanation (not a silent generic error).
    resp = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "add_transaction",
            "params": {
                "account_id": plaid_acct,
                "title": "Starbucks",
                "amount": 5.0,
                "date": "2026-05-01",
                "category": "Food and Drink",
            },
        },
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert "manually-managed" in resp.json()["detail"]

    # No write happened.
    db_session.expire_all()
    assert db_session.execute(select(ExpenseORM)).scalars().all() == []

    # A manual account still proposes + confirms fine (don't over-tighten).
    proposal = client.post(
        "/api/assistant/actions/propose/",
        json={
            "action": "add_transaction",
            "params": {
                "account_id": manual,
                "title": "Lunch",
                "amount": 10.0,
                "date": "2026-05-01",
                "category": "Food and Drink",
            },
        },
        headers=headers,
    )
    assert proposal.status_code == 200, proposal.text
    confirm = client.post(
        "/api/assistant/actions/confirm/",
        json={"token": proposal.json()["token"]},
        headers=headers,
    )
    assert confirm.status_code == 200, confirm.text
    db_session.expire_all()
    expense = db_session.execute(select(ExpenseORM)).scalar_one()
    assert expense.account_id == manual
