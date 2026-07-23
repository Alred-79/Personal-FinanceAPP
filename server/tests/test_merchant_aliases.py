"""Flat merchant aliases: tenant scope, precedence, grouping, and reversibility."""

from datetime import date

import pytest

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    ImportRow as ImportRowORM,
    MerchantAlias as MerchantAliasORM,
    MerchantCategory as MerchantCategoryORM,
    User as UserORM,
)
from server.src.services.categorization_service import (
    CategorizationService,
    normalize_merchant,
)
from server.src.services.auth_service import _to_user_in_db
from server.src.services.matching import MatchRow
from server.src.services.assisted_action_service import AssistedActionService
from server.src.services.import_service import ImportService
from server.src.services.merchant_identity_service import (
    MerchantAliasError,
    MerchantIdentityService,
)
from server.src.services.merchant_lifecycle_service import MerchantLifecycleService
from server.src.services.subscription_service import SubscriptionService
from server.src.services.tax.tagging_service import TaxTaggingService
from server.src.services.receipt_service import ReceiptService
from server.src.routers.subscriptions import get_subscriptions
from server.src.settings import Settings, settings


def _user(db, name: str = "alias-user") -> UserORM:
    row = UserORM(
        username=name,
        full_name="Alias User",
        email=f"{name}@example.com",
        hashed_password="x",
    )
    db.add(row)
    db.flush()
    return row


def _account(db, user_id: int) -> AccountORM:
    row = AccountORM(
        name="Checking", type="depository", balance=0, user_id=user_id
    )
    db.add(row)
    db.flush()
    return row


def _expense(db, account_id: int, title: str, when: str, amount: int = 1000) -> None:
    db.add(
        ExpenseORM(
            account_id=account_id,
            title=title,
            date=when,
            amount=amount,
            category="Other",
        )
    )
    db.flush()


def _observed_pair(db, first: str, second: str):
    user = _user(db)
    account = _account(db, user.id)
    _expense(db, account.id, first, "2026-01-01")
    _expense(db, account.id, second, "2026-02-01")
    return user, account


def test_descriptors_are_owned_capped_and_skip_empty_keys(db_session):
    alice = _user(db_session, "alice-alias")
    bob = _user(db_session, "bob-alias")
    alice_account = _account(db_session, alice.id)
    bob_account = _account(db_session, bob.id)
    _expense(db_session, alice_account.id, "Uber", "2026-01-01")
    _expense(db_session, alice_account.id, "!!!", "2026-01-02")
    _expense(db_session, bob_account.id, "Amazon Web Services", "2026-01-03")

    descriptors = MerchantIdentityService(db_session).descriptors(alice.id, limit=1)
    assert descriptors == [{"descriptor": "Uber", "normalized_key": "uber"}]


def test_only_explicit_exact_aliases_group_uber_or_amazon(db_session):
    user = _user(db_session)
    account = _account(db_session, user.id)
    for i, title in enumerate(
        ("Uber", "Uber Eats", "Amazon", "Amazon Web Services"), start=1
    ):
        _expense(db_session, account.id, title, f"2026-01-0{i}")

    service = MerchantIdentityService(db_session)
    assert service.active_map(user.id) == {}
    service.confirm(user.id, "Uber Eats", "Uber")
    assert service.resolve_key(user.id, normalize_merchant("Uber Eats")) == "uber"
    # No fuzzy or substring inference: Amazon/AWS remain unrelated.
    assert service.resolve_key(user.id, normalize_merchant("Amazon Web Services")) == (
        "amazon web services"
    )


def test_rejects_self_empty_chain_and_reversed_pair(db_session):
    user = _user(db_session)
    account = _account(db_session, user.id)
    for i, title in enumerate(("Uber", "Uber Eats", "Amazon", "!!!"), start=1):
        _expense(db_session, account.id, title, f"2026-01-0{i}")
    service = MerchantIdentityService(db_session)

    with pytest.raises(MerchantAliasError, match="contain letters"):
        service.confirm(user.id, "!!!", "Uber")
    with pytest.raises(MerchantAliasError, match="itself"):
        service.confirm(user.id, "Uber", "UBER #9")

    service.confirm(user.id, "Uber Eats", "Uber")
    with pytest.raises(MerchantAliasError, match="one level deep"):
        service.confirm(user.id, "Amazon", "Uber Eats")  # A → active alias
    with pytest.raises(MerchantAliasError, match="one level deep"):
        service.confirm(user.id, "Uber", "Uber Eats")  # reversed pair


def test_reconfirmation_reactivates_same_row_and_user_delete_cascades(db_session):
    user = _user(db_session)
    account = _account(db_session, user.id)
    for i, title in enumerate(("Acme Hosting", "Acme Cloud", "Acme Services"), 1):
        _expense(db_session, account.id, title, f"2026-01-0{i}")
    service = MerchantIdentityService(db_session)

    first = service.confirm(user.id, "Acme Hosting", "Acme Cloud")
    assert service.revert(user.id, int(first["id"]))
    second = service.confirm(user.id, "Acme Hosting", "Acme Services")
    assert second["id"] == first["id"]
    assert second["canonical_key"] == "acme services"
    assert second["active"] is True

    db_session.delete(user)
    db_session.flush()
    assert db_session.query(MerchantAliasORM).count() == 0


def test_exact_user_category_on_raw_alias_wins(db_session, monkeypatch):
    monkeypatch.setattr(settings, "merchant_aliases_enabled", True)
    user, _ = _observed_pair(db_session, "Uber Eats", "Uber")
    identity = MerchantIdentityService(db_session)
    identity.confirm(user.id, "Uber Eats", "Uber")
    categorize = CategorizationService(db_session)

    categorize.learn(user.id, "Uber", "Transportation", source="user")
    categorize.learn(user.id, "Uber Eats", "Dining", source="user")
    assert categorize.categorize(user.id, "Uber Eats #44") == (
        "Dining",
        "learned",
    )

    # A lower-trust exact memory on the raw alias cannot override the confirmed
    # relationship; the canonical user's category is used.
    raw = categorize.learned_mapping(user.id, "uber eats")
    assert raw is not None
    raw.source = "llm"
    raw.category = "Other"
    db_session.flush()
    assert categorize.categorize(user.id, "Uber Eats") == (
        "Transportation",
        "learned",
    )


def test_undo_restores_pre_alias_category_and_subscription_grouping(
    db_session, monkeypatch
):
    monkeypatch.setattr(settings, "merchant_aliases_enabled", True)
    user = _user(db_session)
    account = _account(db_session, user.id)
    _expense(db_session, account.id, "Acme Cloud", "2026-01-15")
    _expense(db_session, account.id, "Acme Hosting", "2026-02-15")
    _expense(db_session, account.id, "Acme Cloud", "2026-03-15")
    categorize = CategorizationService(db_session)
    categorize.learn(user.id, "Acme Cloud", "Utilities", source="user")
    identity = MerchantIdentityService(db_session)

    before_category = categorize.categorize(user.id, "Acme Hosting")
    before_subs = SubscriptionService(db_session).list_subscriptions(
        user.id, as_of=date(2026, 3, 20)
    )
    alias = identity.confirm(user.id, "Acme Hosting", "Acme Cloud")
    assert categorize.categorize(user.id, "Acme Hosting") == (
        "Utilities",
        "learned",
    )
    grouped = SubscriptionService(db_session).list_subscriptions(
        user.id, as_of=date(2026, 3, 20)
    )
    assert len(grouped) == 1
    assert grouped[0]["merchant"] == "acme cloud"
    assert grouped[0]["occurrences"] == 3
    assert grouped[0]["identity_grouped"] is True

    monkeypatch.setattr(settings, "merchant_lifecycle_enabled", True)
    monkeypatch.setattr(
        MerchantLifecycleService,
        "list_snapshots",
        lambda _self, _uid: [
            {
                "merchant": "acme cloud",
                "probability_alive": 0.1,
                "status": "dormant",
                "expected_purchases": 0.0,
                "price_change_pct": None,
            }
        ],
    )
    enriched = get_subscriptions(_to_user_in_db(user), db_session)
    assert len(enriched) == 1
    assert "lifecycle_status" not in enriched[0]
    monkeypatch.setattr(settings, "merchant_lifecycle_enabled", False)

    assert identity.revert(user.id, int(alias["id"]))
    assert categorize.categorize(user.id, "Acme Hosting") == before_category
    assert (
        SubscriptionService(db_session).list_subscriptions(
            user.id, as_of=date(2026, 3, 20)
        )
        == before_subs
    )


def test_alias_has_no_effect_on_lifecycle_matching_tax_or_source_rows(
    db_session, monkeypatch
):
    monkeypatch.setattr(settings, "merchant_aliases_enabled", True)
    user, account = _observed_pair(db_session, "Uber Eats", "Uber")
    _expense(db_session, account.id, "Uber Eats", "2026-03-01")
    lifecycle = MerchantLifecycleService(db_session)._summaries(
        user.id, date(2026, 3, 1), 365
    )
    match_key = MatchRow(1, "Uber Eats", -1000, "2026-01-01").merchant_key
    tax_bucket = TaxTaggingService(db_session).suggest_bucket(user.id, "Uber Eats")
    charged_as_uber = AssistedActionService(db_session)._charged_since(
        user.id, "uber", after=date(2026, 2, 15)
    )
    monkeypatch.setattr(
        ReceiptService,
        "extract",
        lambda self, *_args, **_kwargs: {
            "title": "Uber Eats",
            "amount": 10,
            "date": "2026-03-02",
            "category": "Food and Drink",
        },
    )
    import_service = ImportService(db_session, classify_fn=lambda *_: "receipt")
    before_import = import_service._ingest_receipt(
        user.id, account.id, b"before", "image/png"
    )
    before_import_key = (
        db_session.query(ImportRowORM)
        .filter(ImportRowORM.session_id == before_import.id)
        .one()
        .merchant_key
    )
    original_titles = [
        row.title
        for row in db_session.query(ExpenseORM)
        .filter(ExpenseORM.account_id == account.id)
        .order_by(ExpenseORM.id)
    ]

    MerchantIdentityService(db_session).confirm(user.id, "Uber Eats", "Uber")
    after_import = import_service._ingest_receipt(
        user.id, account.id, b"after", "image/png"
    )
    after_import_key = (
        db_session.query(ImportRowORM)
        .filter(ImportRowORM.session_id == after_import.id)
        .one()
        .merchant_key
    )

    assert MerchantLifecycleService(db_session)._summaries(
        user.id, date(2026, 3, 1), 365
    ) == lifecycle
    assert MatchRow(1, "Uber Eats", -1000, "2026-01-01").merchant_key == match_key
    assert TaxTaggingService(db_session).suggest_bucket(user.id, "Uber Eats") == tax_bucket
    assert (
        AssistedActionService(db_session)._charged_since(
            user.id, "uber", after=date(2026, 2, 15)
        )
        == charged_as_uber
        is False
    )
    assert before_import_key == after_import_key == "uber eats"
    assert [
        row.title
        for row in db_session.query(ExpenseORM)
        .filter(ExpenseORM.account_id == account.id)
        .order_by(ExpenseORM.id)
    ] == original_titles


def _auth(client, username: str = "alias-api", email: str = "alias-api@example.com"):
    response = client.post(
        "/api/signup/",
        json={
            "username": username,
            "email": email,
            "full_name": "Alias API",
            "password": "Test-password1",
        },
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


def _api_expense(client, headers, title: str, when: str) -> None:
    accounts = client.get("/api/accounts/", headers=headers).json()
    if accounts:
        account_id = accounts[0]["id"]
    else:
        created = client.post(
            "/api/accounts/",
            json={"name": "Checking", "type": "checking", "balance": 1000},
            headers=headers,
        )
        assert created.status_code == 200, created.text
        account_id = client.get("/api/accounts/", headers=headers).json()[0]["id"]
    response = client.post(
        "/api/expenses/",
        json={
            "account_id": account_id,
            "title": title,
            "amount": 10,
            "date": when,
            "category": "Other",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text


def test_routes_ship_dark_and_surface_flag(client, monkeypatch):
    headers = _auth(client)
    monkeypatch.setattr(settings, "merchant_aliases_enabled", False)
    assert client.get("/api/merchant-aliases/", headers=headers).status_code == 404

    monkeypatch.setattr(settings, "merchant_aliases_enabled", True)
    settings_response = client.get("/api/settings/", headers=headers)
    assert settings_response.json()["features"]["merchant_aliases_enabled"] is True


def test_api_confirm_list_and_tenant_scoped_undo(client, monkeypatch):
    monkeypatch.setattr(settings, "merchant_aliases_enabled", True)
    alice = _auth(client, "alias-alice", "alias-alice@example.com")
    _api_expense(client, alice, "Acme Hosting", "2026-01-01")
    _api_expense(client, alice, "Acme Cloud", "2026-02-01")
    created = client.post(
        "/api/merchant-aliases/",
        json={
            "alias_descriptor": "Acme Hosting",
            "canonical_descriptor": "Acme Cloud",
            "confirmed": True,
        },
        headers=alice,
    )
    assert created.status_code == 201, created.text
    alias_id = created.json()["id"]

    bob = _auth(client, "alias-bob", "alias-bob@example.com")
    assert client.get("/api/merchant-aliases/", headers=bob).json() == []
    assert (
        client.delete(f"/api/merchant-aliases/{alias_id}/", headers=bob).status_code
        == 404
    )
    assert client.delete(
        f"/api/merchant-aliases/{alias_id}/", headers=alice
    ).status_code == 204
    assert client.get("/api/merchant-aliases/", headers=alice).json() == []


def test_manual_confirmation_is_required(client, monkeypatch):
    monkeypatch.setattr(settings, "merchant_aliases_enabled", True)
    headers = _auth(client, "alias-confirm", "alias-confirm@example.com")
    response = client.post(
        "/api/merchant-aliases/",
        json={
            "alias_descriptor": "Uber Eats",
            "canonical_descriptor": "Uber",
            "confirmed": False,
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_alias_flag_defaults_off_and_postgres_rls_is_opt_in():
    from pathlib import Path

    assert Settings.model_fields["merchant_aliases_enabled"].default is False
    migration = Path(
        "server/migrations/versions/d4a120260723_merchant_aliases.py"
    ).read_text()
    assert "if not settings.enable_rls" in migration
