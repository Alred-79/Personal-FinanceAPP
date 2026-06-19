"""Pillar 3 Phase 1 — tax-bucket tagging.

Covers the orthogonal tax axis: the bucket registry + ``canonicalize_bucket``
(rejects ghosts, never mints a key), the learned ``MerchantTaxBucket`` mapping
with the same source precedence as ``MerchantCategory`` (``"user"`` is never
clobbered by ``"llm"``), the tag upsert (one tag per transaction), and the
ORPHAN-INTEGRITY guard (deleting a tagged transaction drops its tag, so a reused
autoincrement id can never inherit a stale tag).
"""

from __future__ import annotations

from sqlalchemy import select

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    MerchantTaxBucket as MerchantTaxBucketORM,
    TaxTag as TaxTagORM,
    User as UserORM,
)
from server.src.services.tax import buckets
from server.src.services.tax.tagging_service import TaxTaggingService, tax_year_for
from server.src.services.transaction_service import TransactionService


# ── helpers ──────────────────────────────────────────────────────────────────

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


def _expense(db, account_id, title="Staples", amount_cents=6000, date="2026-03-04"):
    e = ExpenseORM(
        title=title,
        amount=amount_cents,
        date=date,
        category="Shops",
        account_id=account_id,
    )
    db.add(e)
    db.flush()
    return e


# ── bucket registry / canonicalize ───────────────────────────────────────────

class TestBucketRegistry:
    def test_canonicalize_exact_key(self):
        assert buckets.canonicalize_bucket("sch_c_18_office") == "sch_c_18_office"

    def test_canonicalize_case_space_insensitive(self):
        assert buckets.canonicalize_bucket("SCH C 18 OFFICE") == "sch_c_18_office"

    def test_canonicalize_label(self):
        assert (
            buckets.canonicalize_bucket("Office expense (Sch C line 18)")
            == "sch_c_18_office"
        )

    def test_canonicalize_rejects_ghost(self):
        # Never mints a new key — a ghost bucket would silently corrupt the summary.
        assert buckets.canonicalize_bucket("totally made up bucket") is None
        assert buckets.canonicalize_bucket("") is None
        assert buckets.canonicalize_bucket(None) is None

    def test_meals_default_is_50_percent(self):
        assert buckets.default_deductible_bps("sch_c_24b_meals") == 5000

    def test_office_default_is_100_percent(self):
        assert buckets.default_deductible_bps("sch_c_18_office") == 10000

    def test_keyword_suggester_hits_and_misses(self):
        assert buckets.suggest_bucket("STAPLES #1423") == "sch_c_18_office"
        assert buckets.suggest_bucket("Some Random Cafe") is None


# ── learned mapping precedence (mirrors MerchantCategory) ────────────────────

class TestLearnedBucketPrecedence:
    def test_user_not_clobbered_by_llm(self, db_session):
        db = db_session
        u = _user(db)
        svc = TaxTaggingService(db)
        svc.learn(u.id, "Staples #14", "sch_c_18_office", source="user")
        # An LLM guess must NOT overwrite the user's tag.
        svc.learn(u.id, "Staples #99", "sch_c_22_supplies", source="llm")
        assert svc.learned_bucket(u.id, "staples") == "sch_c_18_office"
        row = db.execute(
            select(MerchantTaxBucketORM).where(MerchantTaxBucketORM.user_id == u.id)
        ).scalar_one()
        assert row.source == "user"

    def test_user_overwrites_llm(self, db_session):
        db = db_session
        u = _user(db)
        svc = TaxTaggingService(db)
        svc.learn(u.id, "Staples", "sch_c_22_supplies", source="llm")
        svc.learn(u.id, "Staples", "sch_c_18_office", source="user")
        assert svc.learned_bucket(u.id, "staples") == "sch_c_18_office"

    def test_learn_rejects_ghost_bucket(self, db_session):
        db = db_session
        u = _user(db)
        svc = TaxTaggingService(db)
        svc.learn(u.id, "Weird", "ghost_bucket", source="user")
        assert svc.learned_bucket(u.id, "weird") is None

    def test_suggest_uses_learned_then_keyword(self, db_session):
        db = db_session
        u = _user(db)
        svc = TaxTaggingService(db)
        # No learned mapping yet → keyword tier.
        assert svc.suggest_bucket(u.id, "STAPLES #1") == "sch_c_18_office"
        # Learn a different bucket → learned tier wins.
        svc.learn(u.id, "Staples", "sch_c_22_supplies", source="user")
        assert svc.suggest_bucket(u.id, "STAPLES #2") == "sch_c_22_supplies"


# ── tag upsert ───────────────────────────────────────────────────────────────

class TestTagUpsert:
    def test_tag_uses_bucket_default_bps(self, db_session):
        db = db_session
        u = _user(db)
        a = _account(db, u.id)
        e = _expense(db, a.id, title="Chili's", date="2026-06-01")
        svc = TaxTaggingService(db)
        tag = svc.tag(
            u.id,
            tx_type="expense",
            tx_id=e.id,
            tax_year=tax_year_for(e.date),
            bucket="sch_c_24b_meals",
        )
        assert tag.deductible_bps == 5000  # meals default 50%
        assert tag.tax_year == 2026

    def test_retag_replaces(self, db_session):
        db = db_session
        u = _user(db)
        a = _account(db, u.id)
        e = _expense(db, a.id)
        svc = TaxTaggingService(db)
        svc.tag(u.id, tx_type="expense", tx_id=e.id, tax_year=2026, bucket="sch_c_18_office")
        svc.tag(
            u.id,
            tx_type="expense",
            tx_id=e.id,
            tax_year=2026,
            bucket="sch_c_22_supplies",
            deductible_bps=8000,
        )
        tags = db.execute(
            select(TaxTagORM).where(TaxTagORM.tx_id == e.id)
        ).scalars().all()
        assert len(tags) == 1  # one tag per transaction (upsert)
        assert tags[0].bucket == "sch_c_22_supplies"
        assert tags[0].deductible_bps == 8000

    def test_tax_year_validates_bad_date(self, db_session):
        import pytest

        with pytest.raises(ValueError):
            tax_year_for("not-a-date")

    def test_two_users_same_tx_id_get_separate_tags(self, db_session):
        """C2: the id spaces of expenses/income overlap across users. Two users
        tagging their OWN transaction that happens to share a numeric id must get
        two independent tags — tagging one never overwrites or reassigns the
        other's (the latent IDOR the per-user scope + constraint close)."""
        db = db_session
        alice = _user(db, "alice")
        bob = _user(db, "bob")
        a_acct = _account(db, alice.id)
        # One expense; both users tag the SAME tx_id value to model the overlap.
        ae = _expense(db, a_acct.id, title="Alice Staples")
        svc = TaxTaggingService(db)

        svc.tag(alice.id, tx_type="expense", tx_id=ae.id, tax_year=2026,
                bucket="sch_c_18_office")
        # Bob tags a row with the SAME id value (simulate overlap by reusing ae.id).
        svc.tag(bob.id, tx_type="expense", tx_id=ae.id, tax_year=2026,
                bucket="sch_c_22_supplies")

        tags = db.execute(
            select(TaxTagORM).where(TaxTagORM.tx_id == ae.id)
        ).scalars().all()
        # Two separate tags — one per user — not one overwritten/reassigned tag.
        assert len(tags) == 2
        by_user = {t.user_id: t.bucket for t in tags}
        assert by_user[alice.id] == "sch_c_18_office"  # Alice's unchanged
        assert by_user[bob.id] == "sch_c_22_supplies"

    def test_retag_scoped_to_owner_does_not_touch_other_user(self, db_session):
        """A user's re-tag upserts only their own row; the other user's identical-id
        tag is left exactly as it was."""
        db = db_session
        alice = _user(db, "alice")
        bob = _user(db, "bob")
        a_acct = _account(db, alice.id)
        ae = _expense(db, a_acct.id)
        svc = TaxTaggingService(db)
        svc.tag(alice.id, tx_type="expense", tx_id=ae.id, tax_year=2026,
                bucket="sch_c_18_office")
        svc.tag(bob.id, tx_type="expense", tx_id=ae.id, tax_year=2026,
                bucket="sch_c_18_office")
        # Alice re-tags hers; Bob's must be untouched.
        svc.tag(alice.id, tx_type="expense", tx_id=ae.id, tax_year=2026,
                bucket="sch_c_22_supplies")

        tags = db.execute(
            select(TaxTagORM).where(TaxTagORM.tx_id == ae.id)
        ).scalars().all()
        by_user = {t.user_id: t.bucket for t in tags}
        assert by_user[alice.id] == "sch_c_22_supplies"  # re-tagged
        assert by_user[bob.id] == "sch_c_18_office"  # untouched


# ── orphan integrity (the no-FK guard) ───────────────────────────────────────

class TestOrphanIntegrity:
    def test_delete_transaction_drops_tag(self, db_session):
        db = db_session
        u = _user(db)
        a = _account(db, u.id)
        e = _expense(db, a.id)
        svc = TaxTaggingService(db)
        svc.tag(u.id, tx_type="expense", tx_id=e.id, tax_year=2026, bucket="sch_c_18_office")
        assert db.execute(select(TaxTagORM)).scalars().all()  # tag exists

        # The single delete path must drop the matching tag (no FK cascade).
        TransactionService(db).delete(e.id, u.id, ExpenseORM, balance_sign=-1)

        remaining = db.execute(select(TaxTagORM)).scalars().all()
        assert remaining == [], "tag should be gone after its transaction is deleted"

    def test_delete_only_drops_matching_tx_type(self, db_session):
        """An expense delete must not drop an income tag with the same id value."""
        db = db_session
        u = _user(db)
        a = _account(db, u.id)
        e = _expense(db, a.id)
        svc = TaxTaggingService(db)
        # Tag the expense, and separately a (hypothetical) income with the SAME id
        # value — the overlapping id space the no-FK design must handle.
        svc.tag(u.id, tx_type="expense", tx_id=e.id, tax_year=2026, bucket="sch_c_18_office")
        svc.tag(u.id, tx_type="income", tx_id=e.id, tax_year=2026, bucket="income_1099_nec")

        TransactionService(db).delete(e.id, u.id, ExpenseORM, balance_sign=-1)

        remaining = db.execute(select(TaxTagORM)).scalars().all()
        assert len(remaining) == 1
        assert remaining[0].tx_type == "income"  # income tag survives
