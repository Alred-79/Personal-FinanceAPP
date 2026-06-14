"""Pillar 3 Phase 3 — the deterministic tax-summary / estimate engine.

The correctness-critical surface: deductions-by-bucket with exact ``deductible_bps``
math (50% meals, home-office %), mileage integer math, the quarterly estimate,
the tax-year boundary, INCOME DEDUP (a ledger row + a 1099 for the same money
counts ONCE; doc-only and ledger-only each count once; provenance surfaced), and
ORPHAN INTEGRITY (a deleted tagged transaction is excluded via the inner join).
"""

from __future__ import annotations

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Income as IncomeORM,
    MileageLog as MileageLogORM,
    User as UserORM,
)
from server.src.services.tax.summary_service import TaxSummaryService
from server.src.services.tax.tagging_service import TaxTaggingService
from server.src.services.tax.tax_document_store import TaxDocumentStore
from server.src.services.transaction_service import TransactionService


def _user(db, username="alice"):
    u = UserORM(username=username, full_name="A", email=f"{username}@e.com",
                hashed_password="x")
    db.add(u)
    db.flush()
    return u


def _account(db, uid):
    a = AccountORM(name="Checking", type="depository", balance=0, user_id=uid)
    db.add(a)
    db.flush()
    return a


def _expense(db, acct_id, title, cents, date):
    e = ExpenseORM(title=title, amount=cents, date=date, category="Shops",
                   account_id=acct_id)
    db.add(e)
    db.flush()
    return e


def _income(db, acct_id, title, cents, date):
    i = IncomeORM(title=title, amount=cents, date=date, category="Work",
                  account_id=acct_id)
    db.add(i)
    db.flush()
    return i


# ── deductions by bucket — exact bps math ────────────────────────────────────

class TestDeductionsByBucket:
    def test_meals_50pct_and_office_100pct(self, db_session):
        db = db_session
        u = _user(db)
        a = _account(db, u.id)
        office = _expense(db, a.id, "Staples", 6000, "2026-03-01")  # $60
        meals = _expense(db, a.id, "Chilis", 10000, "2026-06-01")  # $100
        svc = TaxTaggingService(db)
        svc.tag(u.id, tx_type="expense", tx_id=office.id, tax_year=2026,
                bucket="sch_c_18_office")
        svc.tag(u.id, tx_type="expense", tx_id=meals.id, tax_year=2026,
                bucket="sch_c_24b_meals")
        lines = TaxSummaryService(db).get_deductions_by_bucket(u.id, 2026)
        by = {l["bucket"]: l for l in lines}
        assert by["sch_c_18_office"]["deductible_cents"] == 6000  # 100%
        assert by["sch_c_24b_meals"]["total_cents"] == 10000
        assert by["sch_c_24b_meals"]["deductible_cents"] == 5000  # 50%

    def test_home_office_custom_bps(self, db_session):
        db = db_session
        u = _user(db)
        a = _account(db, u.id)
        e = _expense(db, a.id, "Rent", 100000, "2026-04-01")  # $1000
        TaxTaggingService(db).tag(
            u.id, tx_type="expense", tx_id=e.id, tax_year=2026,
            bucket="sch_c_30_home_office", deductible_bps=1500,  # 15%
        )
        lines = TaxSummaryService(db).get_deductions_by_bucket(u.id, 2026)
        assert lines[0]["deductible_cents"] == 15000  # 15% of $1000

    def test_personal_tag_excluded(self, db_session):
        db = db_session
        u = _user(db)
        a = _account(db, u.id)
        e = _expense(db, a.id, "Dinner", 5000, "2026-01-01")
        TaxTaggingService(db).tag(
            u.id, tx_type="expense", tx_id=e.id, tax_year=2026,
            bucket="sch_c_24b_meals", business_personal="personal",
        )
        assert TaxSummaryService(db).get_deductions_by_bucket(u.id, 2026) == []


# ── orphan integrity via the inner join ──────────────────────────────────────

class TestOrphanIntegrityInSummary:
    def test_deleted_transaction_excluded(self, db_session):
        db = db_session
        u = _user(db)
        a = _account(db, u.id)
        e = _expense(db, a.id, "Staples", 6000, "2026-03-01")
        TaxTaggingService(db).tag(u.id, tx_type="expense", tx_id=e.id,
                                  tax_year=2026, bucket="sch_c_18_office")
        # Delete via the service (drops the tag too) — summary must exclude it.
        TransactionService(db).delete(e.id, u.id, ExpenseORM, balance_sign=-1)
        assert TaxSummaryService(db).get_deductions_by_bucket(u.id, 2026) == []


# ── mileage integer math ─────────────────────────────────────────────────────

class TestMileage:
    def test_mileage_deduction_integer(self, db_session):
        db = db_session
        u = _user(db)
        db.add(MileageLogORM(user_id=u.id, trip_date="2026-05-01",
                             miles_milli=100_000, purpose="client",
                             business_personal="business", tax_year=2026))  # 100 mi
        db.flush()
        m = TaxSummaryService(db).get_mileage_deduction(u.id, 2026)
        # 2026 rate 70¢/mi → 100 * 70 = 7000¢
        assert m["rate_cents_per_mile"] == 70
        assert m["deduction_cents"] == 7000
        assert m["miles"] == 100

    def test_no_rate_year_omits(self, db_session):
        db = db_session
        u = _user(db)
        db.add(MileageLogORM(user_id=u.id, trip_date="1999-05-01",
                             miles_milli=100_000, business_personal="business",
                             tax_year=1999))
        db.flush()
        m = TaxSummaryService(db).get_mileage_deduction(u.id, 1999)
        assert m["rate_available"] is False
        assert m["deduction_cents"] == 0


# ── income dedup (the marquee-number correctness bug) ────────────────────────

class TestIncomeDedup:
    def _setup_doc(self, db, uid, issuer, income_cents, wh_cents=0,
                   form="1099-NEC", year=2026):
        store = TaxDocumentStore(db)
        boxes = {"box1_compensation": income_cents}
        if wh_cents:
            boxes["box4_fed_withholding"] = wh_cents
        doc = store.create_pending(uid, form_type=form, issuer_name=issuer,
                                   issuer_tin_last4="6789", tax_year=year,
                                   fields=boxes)
        store.confirm(uid, doc.id)
        return doc

    def test_ledger_and_doc_same_money_counts_once(self, db_session):
        db = db_session
        u = _user(db)
        a = _account(db, u.id)
        self._setup_doc(db, u.id, "Acme", 5800000, wh_cents=410000)
        _income(db, a.id, "Acme Payroll", 5800000, "2026-02-15")  # same money
        inc = TaxSummaryService(db).get_income_by_source(u.id, 2026)
        # Counted ONCE — the document is authoritative.
        assert inc["total_income_cents"] == 5800000
        assert inc["total_withholding_cents"] == 410000
        provs = {s["provenance"] for s in inc["sources"]}
        assert provs == {"from_document"}

    def test_doc_only_and_ledger_only_both_count(self, db_session):
        db = db_session
        u = _user(db)
        a = _account(db, u.id)
        self._setup_doc(db, u.id, "Acme", 5800000)  # doc only
        _income(db, a.id, "Cash gig", 120000, "2026-04-01")  # ledger only (no doc)
        inc = TaxSummaryService(db).get_income_by_source(u.id, 2026)
        assert inc["total_income_cents"] == 5800000 + 120000
        provs = sorted(s["provenance"] for s in inc["sources"])
        assert provs == ["from_document", "from_ledger"]

    def test_withholding_only_from_documents(self, db_session):
        db = db_session
        u = _user(db)
        a = _account(db, u.id)
        # A ledger income row alone contributes NO withholding.
        _income(db, a.id, "Freelance", 300000, "2026-03-01")
        inc = TaxSummaryService(db).get_income_by_source(u.id, 2026)
        assert inc["total_withholding_cents"] == 0


# ── quarterly estimate + tax-year boundary ───────────────────────────────────

class TestEstimateAndYearBoundary:
    def test_estimate_has_disclaimer_and_methodology(self, db_session):
        db = db_session
        u = _user(db)
        est = TaxSummaryService(db).estimate_quarterly(u.id, 2026)
        assert "disclaimer" in est and "methodology" in est
        assert est["per_quarter_cents"] == 0  # no data → zero
        assert len(est["due_dates"]) == 4

    def test_dec31_vs_jan1_land_in_own_year(self, db_session):
        db = db_session
        u = _user(db)
        a = _account(db, u.id)
        dec = _expense(db, a.id, "Staples", 6000, "2026-12-31")
        jan = _expense(db, a.id, "Staples", 7000, "2027-01-01")
        svc = TaxTaggingService(db)
        svc.tag(u.id, tx_type="expense", tx_id=dec.id, tax_year=2026,
                bucket="sch_c_18_office")
        svc.tag(u.id, tx_type="expense", tx_id=jan.id, tax_year=2027,
                bucket="sch_c_18_office")
        s = TaxSummaryService(db)
        assert s.get_deductions_by_bucket(u.id, 2026)[0]["total_cents"] == 6000
        assert s.get_deductions_by_bucket(u.id, 2027)[0]["total_cents"] == 7000

    def test_estimate_default_no_data_still_zero_2025(self, db_session):
        db = db_session
        u = _user(db)
        est = TaxSummaryService(db).estimate_quarterly(u.id, 2025)
        assert est["per_quarter_cents"] == 0
        assert est["se_tax_cents"] == 0
        assert est["income_tax_cents"] == 0


# ── the two-lane estimate (SE tax + bracketed income tax) ────────────────────

class TestDualLaneEstimate:
    """The engine splits self-employment tax from a bracketed federal income tax
    so it serves both a W-2 employee with side income and a 1099 sole proprietor.
    Hand-computed against published 2025 figures (single filer)."""

    def _doc(self, db, uid, issuer, income_cents, *, form, year=2025,
             wh_cents=0):
        store = TaxDocumentStore(db)
        income_box = {
            "W-2": "box1_wages",
            "1099-NEC": "box1_compensation",
        }[form]
        boxes = {income_box: income_cents}
        if wh_cents and form == "W-2":
            boxes["box2_fed_withholding"] = wh_cents
        elif wh_cents:
            boxes["box4_fed_withholding"] = wh_cents
        doc = store.create_pending(uid, form_type=form, issuer_name=issuer,
                                   issuer_tin_last4="6789", tax_year=year,
                                   fields=boxes)
        store.confirm(uid, doc.id)
        return doc

    def test_pure_1099_freelancer_se_plus_income_tax(self, db_session):
        # $80,000 1099-NEC, single, no W-2, no deductions, no withholding (2025).
        db = db_session
        u = _user(db)
        self._doc(db, u.id, "BigCo", 8_000_000, form="1099-NEC", year=2025)
        est = TaxSummaryService(db).estimate_quarterly(
            u.id, 2025, filing_status="single"
        )
        # SE: 80000 × 0.9235 = 73,880 base → 12.4% + 2.9% (under wage base).
        assert est["se_net_earnings_cents"] == 8_000_000
        assert est["se_tax_cents"] == 1_130_364  # $11,303.64
        # Income tax on AGI ($80,000 − half-SE $5,651.82) − std ded $15,000 =
        # $59,348.18 taxable. 2025 single brackets: 10% to $11,925, 12% to
        # $48,475, 22% above → $7,970.59.
        assert est["taxable_base_cents"] == 5_934_818  # $59,348.18
        assert est["income_tax_cents"] == 797_059      # $7,970.59
        assert est["annual_estimate_cents"] == 1_130_364 + 797_059
        assert est["per_quarter_cents"] == (1_130_364 + 797_059) // 4

    def test_w2_employee_no_se_tax(self, db_session):
        # A pure W-2 wage earner owes NO self-employment tax.
        db = db_session
        u = _user(db)
        self._doc(db, u.id, "Employer", 6_000_000, form="W-2", year=2025,
                  wh_cents=600_000)
        est = TaxSummaryService(db).estimate_quarterly(
            u.id, 2025, filing_status="single"
        )
        assert est["se_tax_cents"] == 0
        assert est["wages_cents"] == 6_000_000
        # Withholding reduces what's still owed.
        assert est["total_withholding_cents"] == 600_000
        assert est["remaining_estimate_cents"] == max(
            0, est["annual_estimate_cents"] - 600_000
        )

    def test_w2_plus_side_1099_only_se_on_side_income(self, db_session):
        # Wages consume the SS wage base first; SE tax is only on the side gig.
        db = db_session
        u = _user(db)
        self._doc(db, u.id, "Employer", 5_000_000, form="W-2", year=2025)
        self._doc(db, u.id, "SideGig", 1_000_000, form="1099-NEC", year=2025)
        est = TaxSummaryService(db).estimate_quarterly(
            u.id, 2025, filing_status="single"
        )
        assert est["wages_cents"] == 5_000_000
        assert est["se_income_cents"] == 1_000_000
        # SE base 10000×0.9235 = 9235; under the remaining cap → full 15.3%.
        assert est["se_tax_cents"] == 923_500 * 1530 // 10000

    def test_safe_harbor_uses_lesser_of_90pct_or_110pct_prior(self, db_session):
        db = db_session
        u = _user(db)
        self._doc(db, u.id, "BigCo", 8_000_000, form="1099-NEC", year=2025)
        est = TaxSummaryService(db).estimate_quarterly(
            u.id, 2025, filing_status="single",
            prior_year_tax_cents=1_000_000,  # $10,000 last year
        )
        ninety = est["annual_estimate_cents"] * 9000 // 10000
        prior_safe = 1_000_000 * 11000 // 10000  # $11,000
        assert est["safe_harbor_annual_cents"] == min(ninety, prior_safe)
        assert est["safe_harbor_per_quarter_cents"] == (
            est["safe_harbor_remaining_cents"] // 4
        )

    def test_filing_status_changes_the_estimate(self, db_session):
        db = db_session
        u = _user(db)
        self._doc(db, u.id, "BigCo", 8_000_000, form="1099-NEC", year=2025)
        svc = TaxSummaryService(db)
        single = svc.estimate_quarterly(u.id, 2025, filing_status="single")
        mfj = svc.estimate_quarterly(u.id, 2025, filing_status="mfj")
        # MFJ's larger std deduction + wider brackets → lower income tax.
        assert mfj["income_tax_cents"] < single["income_tax_cents"]
        # SE tax is identical (it doesn't depend on filing status).
        assert mfj["se_tax_cents"] == single["se_tax_cents"]

    def test_deductions_reduce_se_net(self, db_session):
        db = db_session
        u = _user(db)
        a = _account(db, u.id)
        self._doc(db, u.id, "BigCo", 8_000_000, form="1099-NEC", year=2025)
        e = _expense(db, a.id, "Staples", 1_000_000, "2025-03-01")
        TaxTaggingService(db).tag(u.id, tx_type="expense", tx_id=e.id,
                                  tax_year=2025, bucket="sch_c_18_office")
        est = TaxSummaryService(db).estimate_quarterly(u.id, 2025)
        assert est["se_net_earnings_cents"] == 8_000_000 - 1_000_000

    def test_date_edit_after_tag_does_not_move_year(self, db_session):
        """tax_year is denormalized at tag time — re-dating the tx doesn't move it
        unless the tag is recomputed."""
        db = db_session
        u = _user(db)
        a = _account(db, u.id)
        e = _expense(db, a.id, "Staples", 6000, "2026-12-31")
        TaxTaggingService(db).tag(u.id, tx_type="expense", tx_id=e.id,
                                  tax_year=2026, bucket="sch_c_18_office")
        e.date = "2027-01-01"  # user edits the date later
        db.flush()
        # The tag's stored tax_year is still 2026 — the summary follows the tag.
        s = TaxSummaryService(db)
        assert s.get_deductions_by_bucket(u.id, 2026)[0]["total_cents"] == 6000
        assert s.get_deductions_by_bucket(u.id, 2027) == []
