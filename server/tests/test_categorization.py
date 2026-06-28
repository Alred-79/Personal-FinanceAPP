"""Automatic categorization tests.

Pure helpers (no DB), the learned-mapping service (with a mocked Groq fn, no
live calls), and the manual-entry hooks in ``TransactionService``.
"""

from sqlalchemy import select

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    MerchantCategory as MerchantCategoryORM,
    User as UserORM,
)
from server.src.services.categorization_service import (
    CANONICAL_CATEGORIES,
    CategorizationService,
    canonicalize_category,
    normalize_merchant,
    rule_category,
)
from server.src.services.transaction_service import TransactionService


# ── Fixtures helpers ────────────────────────────────────────────────────────

def _user(db, username="alice"):
    u = UserORM(
        username=username,
        full_name="Alice",
        email=f"{username}@example.com",
        hashed_password="x",
    )
    db.add(u)
    db.flush()
    return u


def _account(db, user_id):
    a = AccountORM(name="Checking", type="depository", balance=0, user_id=user_id)
    db.add(a)
    db.flush()
    return a


def _expense_by_title(db, title):
    return db.execute(
        select(ExpenseORM).where(ExpenseORM.title == title)
    ).scalar_one()


# ── Pure helpers ────────────────────────────────────────────────────────────

class TestNormalizeMerchant:
    def test_strips_digits_and_punctuation(self):
        assert normalize_merchant("NETFLIX.COM #1234") == "netflix com"

    def test_blank(self):
        assert normalize_merchant("  ") == ""
        assert normalize_merchant("") == ""

    def test_stable_across_store_numbers(self):
        assert normalize_merchant("Starbucks 0421") == normalize_merchant(
            "STARBUCKS #9988"
        )


class TestRuleCategory:
    def test_known_keyword(self):
        assert rule_category("UBER trip downtown") == "Transportation"

    def test_longer_keyword_wins(self):
        # "uber eats" should beat the shorter "uber".
        assert rule_category("UBER EATS order") == "Food and Drink"

    def test_unknown_returns_none(self):
        assert rule_category("Zzqq Unknown Merchant") is None

    def test_pharmacy_is_health(self):
        # Regression: pharmacies used to fall into the "Service" catch-all.
        assert rule_category("WALGREENS #4821") == "Health"
        assert rule_category("CVS Pharmacy") == "Health"

    def test_gym_is_fitness(self):
        # Regression: gyms used to fall into the "Service" catch-all.
        assert rule_category("PLANET FITNESS 0420") == "Fitness"
        assert rule_category("LA Fitness") == "Fitness"


class TestCanonicalize:
    def test_health_and_fitness_are_canonical(self):
        assert "Health" in CANONICAL_CATEGORIES
        assert "Fitness" in CANONICAL_CATEGORIES
        assert canonicalize_category("Health") == "Health"
        assert canonicalize_category("Fitness") == "Fitness"

    def test_plaid_medical_maps_to_health(self):
        # Plaid's MEDICAL primary code now lands in Health, not Service.
        assert canonicalize_category("MEDICAL") == "Health"


# ── Service: resolution tiers ───────────────────────────────────────────────

class TestCategorizeService:
    def test_rule_tier(self, db_session):
        user = _user(db_session)
        svc = CategorizationService(db_session)
        cat, source = svc.categorize(user.id, "NETFLIX.COM")
        assert (cat, source) == ("Entertainment", "rule")

    def test_default_when_unknown(self, db_session):
        user = _user(db_session)
        svc = CategorizationService(db_session)
        cat, source = svc.categorize(user.id, "Zzqq Unknown")
        assert (cat, source) == ("Other", "default")

    def test_learned_beats_rule(self, db_session):
        user = _user(db_session)
        svc = CategorizationService(db_session)
        # Netflix would normally be a rule (Entertainment); a learned mapping wins.
        svc.learn(user.id, "NETFLIX.COM", "Subscriptions", source="user")
        cat, source = svc.categorize(user.id, "netflix.com #55")
        assert (cat, source) == ("Subscriptions", "learned")

    def test_llm_fallback_is_persisted(self, db_session):
        user = _user(db_session)
        calls = []

        def fake_llm(titles):
            calls.append(list(titles))
            return {t: "Travel" for t in titles}

        svc = CategorizationService(db_session, llm_fn=fake_llm)
        cat, source = svc.categorize(user.id, "Mystery Lodge XYZ", use_llm=True)
        assert (cat, source) == ("Travel", "llm")
        assert calls == [["Mystery Lodge XYZ"]]

        # Second lookup is served from the learned mapping, no new LLM call.
        cat2, source2 = svc.categorize(user.id, "mystery lodge xyz")
        assert (cat2, source2) == ("Travel", "learned")
        assert len(calls) == 1

    def test_user_mapping_not_clobbered_by_llm(self, db_session):
        user = _user(db_session)
        svc = CategorizationService(db_session)
        svc.learn(user.id, "Corner Shop", "Groceries", source="user")
        svc.learn(user.id, "Corner Shop", "Other", source="llm")
        row = db_session.execute(
            select(MerchantCategoryORM).where(
                MerchantCategoryORM.merchant == normalize_merchant("Corner Shop")
            )
        ).scalar_one()
        assert row.category == "Groceries"
        assert row.source == "user"

    def test_batch_groups_unknowns_into_one_call(self, db_session):
        user = _user(db_session)
        calls = []

        def fake_llm(titles):
            calls.append(list(titles))
            return {t: "Travel" for t in titles}

        svc = CategorizationService(db_session, llm_fn=fake_llm)
        result = svc.categorize_batch(
            user.id,
            ["UBER ride", "Spotify", "Weird Co A", "Weird Co B"],
            use_llm=True,
        )
        assert result["UBER ride"] == "Transportation"
        assert result["Spotify"] == "Entertainment"
        assert result["Weird Co A"] == "Travel"
        # Exactly one batched call, containing only the unknowns.
        assert len(calls) == 1
        assert set(calls[0]) == {"Weird Co A", "Weird Co B"}


# ── Manual entry hooks ──────────────────────────────────────────────────────

class TestTransactionServiceCategorization:
    def test_blank_category_is_inferred(self, db_session):
        user = _user(db_session)
        acct = _account(db_session, user.id)
        svc = TransactionService(db_session)
        svc.create(
            user.id,
            ExpenseORM,
            -1,
            title="UBER ride home",
            amount=20.0,
            tx_date="2026-05-01",
            category="",
            account_id=acct.id,
        )
        assert _expense_by_title(db_session, "UBER ride home").category == "Transportation"

    def test_chosen_category_is_remembered(self, db_session):
        user = _user(db_session)
        acct = _account(db_session, user.id)
        svc = TransactionService(db_session)
        svc.create(
            user.id,
            ExpenseORM,
            -1,
            title="Bodega XYZ",
            amount=8.0,
            tx_date="2026-05-01",
            category="Groceries",
            account_id=acct.id,
        )
        # A later, blank category charge for the same merchant inherits it.
        svc.create(
            user.id,
            ExpenseORM,
            -1,
            title="BODEGA XYZ #99",
            amount=12.0,
            tx_date="2026-05-08",
            category="",
            account_id=acct.id,
        )
        assert _expense_by_title(db_session, "BODEGA XYZ #99").category == "Groceries"

    def test_rename_sticks_for_future(self, db_session):
        user = _user(db_session)
        acct = _account(db_session, user.id)
        svc = TransactionService(db_session)
        svc.create(
            user.id,
            ExpenseORM,
            -1,
            title="Cafe Luna",
            amount=5.0,
            tx_date="2026-05-01",
            category="Other",
            account_id=acct.id,
        )
        row = _expense_by_title(db_session, "Cafe Luna")
        # User renames the category.
        svc.update(
            row.id,
            user.id,
            ExpenseORM,
            -1,
            title="Cafe Luna",
            amount=5.0,
            tx_date="2026-05-01",
            category="Food and Drink",
            account_id=acct.id,
        )
        cat, source = CategorizationService(db_session).categorize(
            user.id, "cafe luna"
        )
        assert (cat, source) == ("Food and Drink", "learned")
