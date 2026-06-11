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
from server.src.services.assistant_service import ActionService, AddTransactionTool


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
