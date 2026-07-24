from datetime import datetime, timezone

from server.src.db.models import Account, User
from server.src.services.account_semantics import AccountSemanticsService


def _user(db_session):
    user = User(
        username="semantics",
        full_name="Semantic Test",
        email="semantics@example.com",
        hashed_password="not-used",
    )
    db_session.add(user)
    db_session.flush()
    return user


def test_purpose_specific_totals_do_not_treat_credit_as_cash(db_session):
    user = _user(db_session)
    observed = datetime.now(timezone.utc)
    db_session.add_all(
        [
            Account(
                name="Linked Checking",
                type="depository",
                subtype="checking",
                balance=10_000,
                current_balance=10_000,
                available_balance=9_000,
                iso_currency_code="USD",
                balance_observed_at=observed,
                semantic_role="liquid_asset",
                review_state="confirmed",
                plaid_account_id="checking-1",
                user_id=user.id,
            ),
            Account(name="Savings", type="savings", balance=5_000, user_id=user.id),
            Account(
                name="Credit Card",
                type="credit",
                balance=2_000,
                current_balance=2_000,
                available_balance=8_000,
                credit_limit=10_000,
                iso_currency_code="USD",
                balance_observed_at=observed,
                semantic_role="liability",
                review_state="confirmed",
                plaid_account_id="credit-1",
                user_id=user.id,
            ),
            Account(
                name="Overpaid Card",
                type="credit",
                balance=-500,
                current_balance=-500,
                iso_currency_code="USD",
                balance_observed_at=observed,
                semantic_role="liability",
                review_state="confirmed",
                plaid_account_id="credit-2",
                user_id=user.id,
            ),
            Account(
                name="Legacy Manual Card",
                type="credit",
                balance=-1_000,
                user_id=user.id,
            ),
            Account(name="Brokerage", type="investment", balance=50_000, user_id=user.id),
        ]
    )
    db_session.commit()

    service = AccountSemanticsService(db_session)
    cash = service.summarize(user.id, "near_term_cash")
    worth = service.summarize(user.id, "net_worth")

    assert cash.total_cents == 14_000
    assert {row["name"] for row in cash.components} == {"Linked Checking", "Savings"}
    assert {row["name"] for row in cash.exclusions} == {
        "Credit Card",
        "Overpaid Card",
        "Legacy Manual Card",
        "Brokerage",
    }
    assert worth.total_cents == 62_500
    credit = next(row for row in worth.components if row["name"] == "Credit Card")
    assert credit["signed_cents"] == -2_000
    overpaid = next(row for row in worth.components if row["name"] == "Overpaid Card")
    assert overpaid["signed_cents"] == 500


def test_unknown_and_non_usd_accounts_are_explicitly_excluded(db_session):
    user = _user(db_session)
    db_session.add_all(
        [
            Account(name="Mystery", type="other", balance=10_000, user_id=user.id),
            Account(
                name="Euro Checking",
                type="depository",
                balance=20_000,
                current_balance=20_000,
                iso_currency_code="EUR",
                semantic_role="liquid_asset",
                review_state="confirmed",
                plaid_account_id="eur-1",
                user_id=user.id,
            ),
        ]
    )
    db_session.commit()

    summary = AccountSemanticsService(db_session).summarize(user.id, "forecast")

    assert summary.total_cents == 0
    assert summary.state == "limited"
    assert {row["reason"] for row in summary.exclusions} == {
        "account_role_unknown",
        "reported_currency",
    }


def test_legacy_linked_currency_remains_usable_but_limited(db_session):
    user = _user(db_session)
    db_session.add(
        Account(
            name="Legacy Checking",
            type="depository",
            balance=7_500,
            current_balance=7_500,
            available_balance=7_000,
            semantic_role="liquid_asset",
            plaid_account_id="legacy-1",
            user_id=user.id,
        )
    )
    db_session.commit()

    summary = AccountSemanticsService(db_session).summarize(user.id, "near_term_cash")

    assert summary.total_cents == 7_000
    assert summary.state == "limited"
