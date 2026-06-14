"""Deterministic tax-summary / estimated-tax engine (LLM = narration only).

Pure, integer-cents, no LLM (mirrors ``forecast_service`` / ``scenario_service``
discipline). It ORGANIZES, SUMMARIZES, and ESTIMATES the user's own tagged
numbers; it never gives tax advice. The agent's read tools call into here and
narrate the result; the firewall + narration post-processor keep that factual.

US calendar-year filer assumption throughout (``tax_year`` is the denormalized
``int(date[:4])`` stored on the tag/doc — a date edit after tagging never moves a
row across years).

Two correctness pillars:

1. **Orphan integrity** — every ``TaxTag → Expense/Income`` join is an INNER
   join, so a tag whose transaction was deleted (no FK cascade; id reuse) is
   silently excluded from totals, never mis-attributed to a reused id.

2. **Income dedup (don't double-count)** — a 1099 documents income that is
   USUALLY also already in the ledger (paid → synced via Plaid → AND the user
   uploads the 1099 for the same money). Summing ledger income PLUS document
   income boxes inflates the marquee number. Policy:
     * documents are the AUTHORITY for documented income — for an issuer with a
       confirmed ``TaxDocument``, the form's box is the income figure and matching
       ledger rows are EXCLUDED (match by issuer/payer name + amount within the
       tax year);
     * ledger rows contribute income ONLY when there is no matching confirmed doc
       (cash / untracked 1099-less income);
     * withholding comes ONLY from documents (boxes 2/4/17), never inferred from
       ledger rows.
   The result surfaces provenance (``from_document`` vs ``from_ledger``) so the
   number is auditable and a bad match is correctable.
"""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Income as IncomeORM,
    MileageLog as MileageLogORM,
    TaxDocument as TaxDocumentORM,
    TaxTag as TaxTagORM,
)
from server.src.services.categorization_service import normalize_merchant

from .buckets import bucket_label
from .buckets import TAX_BUCKETS
from .rates import ESTIMATE_FLAT_RATE_BPS, mileage_rate_cents, quarterly_due_dates

# Income boxes per form, in priority order (the documented-income figure).
_INCOME_BOXES = {
    "W-2": "box1_wages",
    "1099-NEC": "box1_compensation",
    "1099-MISC": "box3_other_income",
    "1099-K": "box1a_gross",
}
# Withholding boxes per form (summed across all of a form's withholding boxes).
_WITHHOLDING_BOXES = {
    "W-2": ("box2_fed_withholding", "box17_state_withholding"),
    "1099-NEC": ("box4_fed_withholding",),
    "1099-MISC": ("box4_fed_withholding",),
}

# How close (in cents) a ledger income amount must be to a document's income box
# to count as "the same money" for dedup. Exact match preferred; a tiny tolerance
# absorbs rounding without over-matching unrelated income.
_DEDUP_TOLERANCE_CENTS = 100  # $1


class TaxSummaryService:
    """Pure tax-organization summaries over the user's own tagged data."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── deductions by bucket (INNER join — orphan guard) ─────────────────────

    def get_deductions_by_bucket(self, user_id: int, tax_year: int) -> list[dict]:
        """Deductible totals grouped by Schedule-C bucket for the year.

        INNER-joins ``TaxTag → Expense`` so a tag whose expense is gone drops out.
        Only ``business`` expense tags count; ``deductible_bps`` is applied EXACTLY
        in cents (50% meals, home-office %). Each line:
        ``{bucket, label, irs_line, total_cents, deductible_cents}``.
        """
        rows = self.db.execute(
            select(
                TaxTagORM.bucket,
                TaxTagORM.deductible_bps,
                ExpenseORM.amount,
            )
            .join(ExpenseORM, TaxTagORM.tx_id == ExpenseORM.id)  # INNER join
            .join(AccountORM, ExpenseORM.account_id == AccountORM.id)
            .where(
                TaxTagORM.user_id == user_id,
                TaxTagORM.tx_type == "expense",
                TaxTagORM.tax_year == tax_year,
                TaxTagORM.business_personal == "business",
                AccountORM.user_id == user_id,
            )
        ).all()

        by_bucket: dict[str, dict] = {}
        for bucket, bps, amount_cents in rows:
            # Expense amounts are stored as positive cents in this app's ledger.
            total = abs(int(amount_cents))
            deductible = total * int(bps) // 10000  # exact integer-cent math
            line = by_bucket.setdefault(
                bucket,
                {
                    "bucket": bucket,
                    "label": bucket_label(bucket),
                    "irs_line": TAX_BUCKETS.get(bucket, {}).get("irs_line", ""),
                    "total_cents": 0,
                    "deductible_cents": 0,
                },
            )
            line["total_cents"] += total
            line["deductible_cents"] += deductible

        return sorted(by_bucket.values(), key=lambda x: x["bucket"])

    # ── mileage deduction (integer math) ─────────────────────────────────────

    def get_mileage_deduction(self, user_id: int, tax_year: int) -> dict:
        """Business mileage → IRS-rate deduction (integer cents). 0 if no rate."""
        total_milli = self.db.execute(
            select(MileageLogORM.miles_milli).where(
                MileageLogORM.user_id == user_id,
                MileageLogORM.tax_year == tax_year,
                MileageLogORM.business_personal == "business",
            )
        ).scalars().all()
        miles_milli = sum(int(m) for m in total_milli)
        rate = mileage_rate_cents(tax_year)
        if rate is None:
            return {
                "miles": miles_milli / 1000,
                "rate_cents_per_mile": None,
                "deduction_cents": 0,
                "rate_available": False,
            }
        deduction = miles_milli * int(rate) // 1000  # integer-only
        return {
            "miles": miles_milli / 1000,
            "rate_cents_per_mile": rate,
            "deduction_cents": deduction,
            "rate_available": True,
        }

    # ── income by source, with document-authoritative dedup ──────────────────

    def get_income_by_source(self, user_id: int, tax_year: int) -> dict:
        """Income by source + withholding, deduping ledger income against docs.

        Returns ``{sources, total_income_cents, total_withholding_cents,
        wages_cents, se_income_cents}`` where each source carries ``provenance``
        (``from_document`` / ``from_ledger``). Documents are authoritative;
        matching ledger income is excluded; withholding comes only from documents.

        Income CHARACTER (for the dual-lane estimate): W-2 documents are *wages*
        (no SE tax); 1099-* documents and untracked ledger income are *self-
        employment* earnings (SE tax applies). The split is what lets one engine
        serve both a W-2 employee with side income and a 1099 sole proprietor.
        """
        # 1. Confirmed income documents are the authority.
        docs = self.db.execute(
            select(TaxDocumentORM).where(
                TaxDocumentORM.user_id == user_id,
                TaxDocumentORM.tax_year == tax_year,
                TaxDocumentORM.status == "confirmed",
            )
        ).scalars().all()

        sources: list[dict] = []
        total_income = 0
        total_withholding = 0
        wages_cents = 0       # W-2 income — no SE tax
        se_income_cents = 0   # 1099-* + untracked ledger income — SE tax applies
        # (normalized_issuer, income_cents) pairs for dedup against the ledger.
        documented: list[tuple[str, int]] = []

        for doc in docs:
            boxes = json.loads(doc.fields_json or "{}")
            income_box = _INCOME_BOXES.get(doc.form_type)
            income_cents = int(boxes.get(income_box, 0)) if income_box else 0
            wh_cents = 0
            for wbox in _WITHHOLDING_BOXES.get(doc.form_type, ()):
                wh_cents += int(boxes.get(wbox, 0))
            if income_cents:
                sources.append(
                    {
                        "issuer": doc.issuer_name,
                        "form_type": doc.form_type,
                        "income_cents": income_cents,
                        "withholding_cents": wh_cents,
                        "provenance": "from_document",
                    }
                )
                total_income += income_cents
                if doc.form_type == "W-2":
                    wages_cents += income_cents
                else:
                    se_income_cents += income_cents
                documented.append((normalize_merchant(doc.issuer_name), income_cents))
            total_withholding += wh_cents

        # 2. Ledger income rows contribute ONLY when no confirmed doc covers the
        #    same money (match by issuer/title + amount within tolerance).
        ledger_rows = self.db.execute(
            select(IncomeORM.title, IncomeORM.amount)
            .join(AccountORM, IncomeORM.account_id == AccountORM.id)
            .where(
                AccountORM.user_id == user_id,
                IncomeORM.date.like(f"{tax_year}-%"),
            )
        ).all()

        for title, amount_cents in ledger_rows:
            amt = abs(int(amount_cents))
            key = normalize_merchant(title or "")
            if self._is_documented(key, amt, documented):
                continue  # the doc is the authority — don't double-count
            sources.append(
                {
                    "issuer": title,
                    "form_type": None,
                    "income_cents": amt,
                    "withholding_cents": 0,
                    "provenance": "from_ledger",
                }
            )
            total_income += amt
            # Untracked ledger income (no covering 1099) is treated as self-
            # employment earnings — the conservative default for a sole proprietor,
            # and the only sensible character for cash income with no W-2.
            se_income_cents += amt

        return {
            "sources": sources,
            "total_income_cents": total_income,
            "total_withholding_cents": total_withholding,
            "wages_cents": wages_cents,
            "se_income_cents": se_income_cents,
        }

    @staticmethod
    def _is_documented(
        ledger_key: str, ledger_amount: int, documented: list[tuple[str, int]]
    ) -> bool:
        """True if a confirmed doc covers this ledger income (same payer + amount).

        Match is issuer-name (normalized) overlap AND amount within tolerance.
        Conservative: requires BOTH so unrelated same-amount income isn't dropped.
        """
        for doc_key, doc_amount in documented:
            if abs(doc_amount - ledger_amount) > _DEDUP_TOLERANCE_CENTS:
                continue
            if not ledger_key or not doc_key:
                continue
            # name overlap either direction (a ledger "ACME PAYROLL" vs doc "Acme").
            if ledger_key in doc_key or doc_key in ledger_key:
                return True
        return False

    # ── estimated quarterly (clearly an ESTIMATE) ────────────────────────────

    def estimate_quarterly(
        self,
        user_id: int,
        tax_year: int,
        *,
        filing_status: str = "single",
        state_rate_bps: int = 0,
        prior_year_tax_cents: Optional[int] = None,
        payments_made_cents: int = 0,
    ) -> dict:
        """A transparent two-lane ESTIMATE — arithmetic on the user's own numbers,
        NOT a recommendation. Splits self-employment tax (on net SE earnings) from
        a bracketed federal income tax (on wages + SE income), so it serves both a
        W-2 employee with side income and a 1099 sole proprietor. Carries an
        explicit breakdown, methodology, and disclaimer. NEVER a filing claim.

        Optional inputs (all defaulted so a bare call still works):
        * ``filing_status`` — single / mfj / mfs / hoh (drives brackets + std ded).
        * ``state_rate_bps`` — a flat state rate the user supplies (0 = skip state).
        * ``prior_year_tax_cents`` — enables the SAFE-HARBOR target (pay the lesser
          of 90% of this year or 100%/110% of last year to dodge the underpayment
          penalty); omitted → safe harbor is null.
        * ``payments_made_cents`` — estimated payments already sent this year.

        An untabulated year (no bracket table) falls back to the legacy flat rate
        and says so in the methodology, rather than guessing a bracket.
        """
        from .rates import (
            federal_income_tax_cents,
            self_employment_tax_cents,
            standard_deduction_cents,
        )

        if filing_status not in ("single", "mfj", "mfs", "hoh"):
            filing_status = "single"

        income = self.get_income_by_source(user_id, tax_year)
        deductions = self.get_deductions_by_bucket(user_id, tax_year)
        mileage = self.get_mileage_deduction(user_id, tax_year)

        total_income = income["total_income_cents"]
        wages = income.get("wages_cents", 0)
        se_income = income.get("se_income_cents", 0)
        withholding = income["total_withholding_cents"]

        # Schedule-C deductions + mileage reduce NET SE earnings (they're business
        # expenses against self-employment income, not against W-2 wages).
        total_deductible = sum(d["deductible_cents"] for d in deductions)
        total_deductible += mileage["deduction_cents"]
        se_net = max(0, se_income - total_deductible)

        # ── Lane 1: self-employment tax (Schedule SE) ────────────────────────
        se = self_employment_tax_cents(se_net, wages, tax_year)
        se_tax = se["se_tax_cents"]

        # ── Lane 2: federal income tax (marginal brackets) ───────────────────
        # AGI = wages + net SE earnings − the above-the-line half-of-SE-tax.
        agi = max(0, wages + se_net - se["half_se_tax_cents"])
        std_ded = standard_deduction_cents(tax_year, filing_status)
        bracketed = std_ded is not None
        taxable_base = max(0, agi - (std_ded or 0))
        income_tax = federal_income_tax_cents(taxable_base, tax_year, filing_status)

        if income_tax is None or not bracketed:
            # Fallback: no bracket/std-ded table for this year → flat estimate on
            # (income − deductions), and no SE split is meaningful. Honest about it.
            flat_base = max(0, total_income - total_deductible)
            annual_estimate = flat_base * ESTIMATE_FLAT_RATE_BPS // 10000
            taxable_base = flat_base
            se_tax = 0
            income_tax = annual_estimate
            state_tax = 0
            methodology = (
                f"No published federal bracket table for {tax_year} yet, so a flat "
                "blended rate is applied to your tagged income minus deductions. "
                "A crude arithmetic estimate for setting money aside."
            )
        else:
            state_tax = taxable_base * max(0, int(state_rate_bps)) // 10000
            annual_estimate = se_tax + income_tax + state_tax
            methodology = (
                "Self-employment tax (Social Security up to the wage base + "
                "uncapped Medicare) on your net 1099/cash earnings, PLUS marginal "
                f"federal income tax for a {filing_status} filer on wages + net SE "
                "income after the standard deduction"
                + (", PLUS a flat state rate" if state_rate_bps else "")
                + ". An estimate of your own numbers for setting money aside."
            )

        # Already-withheld + payments already made reduce what's still owed.
        remaining = max(0, annual_estimate - withholding - max(0, payments_made_cents))

        # ── Safe-harbor target (penalty avoidance), if prior-year tax given ──
        # Pay the LESSER of 90% of this year's estimate or 100%/110% of last year
        # (110% when prior-year AGI was high; we use 110% as the safe default).
        safe_harbor_annual = None
        safe_harbor_remaining = None
        safe_harbor_per_quarter = None
        if prior_year_tax_cents is not None and prior_year_tax_cents >= 0:
            ninety_pct = annual_estimate * 9000 // 10000
            prior_safe = prior_year_tax_cents * 11000 // 10000  # 110%
            safe_harbor_annual = min(ninety_pct, prior_safe)
            safe_harbor_remaining = max(
                0, safe_harbor_annual - withholding - max(0, payments_made_cents)
            )
            safe_harbor_per_quarter = safe_harbor_remaining // 4

        per_quarter = remaining // 4

        return {
            "tax_year": tax_year,
            "filing_status": filing_status,
            "total_income_cents": total_income,
            "wages_cents": wages,
            "se_income_cents": se_income,
            "total_deductible_cents": total_deductible,
            "se_net_earnings_cents": se_net,
            "se_tax_cents": se_tax,
            "income_tax_cents": income_tax,
            "state_tax_cents": state_tax,
            "taxable_base_cents": taxable_base,
            "total_withholding_cents": withholding,
            "payments_made_cents": max(0, payments_made_cents),
            "annual_estimate_cents": annual_estimate,
            "remaining_estimate_cents": remaining,
            "per_quarter_cents": per_quarter,
            "safe_harbor_annual_cents": safe_harbor_annual,
            "safe_harbor_remaining_cents": safe_harbor_remaining,
            "safe_harbor_per_quarter_cents": safe_harbor_per_quarter,
            "due_dates": quarterly_due_dates(tax_year),
            "methodology": methodology,
            "disclaimer": (
                "Estimate only — not tax advice. It omits credits, QBI, itemized "
                "deductions, and other situations. Consult a tax professional or "
                "irs.gov before filing or paying."
            ),
        }

    # ── the full summary ─────────────────────────────────────────────────────

    def get_tax_summary(
        self,
        user_id: int,
        tax_year: int,
        *,
        filing_status: str = "single",
        state_rate_bps: int = 0,
        prior_year_tax_cents: Optional[int] = None,
        payments_made_cents: int = 0,
    ) -> dict:
        """The full tax-organization summary for a year. All figures are the
        user's own tagged numbers; the quarterly figure is a labelled estimate.

        The estimate inputs (filing status, optional state rate, prior-year tax for
        safe harbor, payments already made) flow through to ``estimate_quarterly``.
        """
        income = self.get_income_by_source(user_id, tax_year)
        deductions = self.get_deductions_by_bucket(user_id, tax_year)
        mileage = self.get_mileage_deduction(user_id, tax_year)
        estimate = self.estimate_quarterly(
            user_id,
            tax_year,
            filing_status=filing_status,
            state_rate_bps=state_rate_bps,
            prior_year_tax_cents=prior_year_tax_cents,
            payments_made_cents=payments_made_cents,
        )
        return {
            "tax_year": tax_year,
            "income_by_source": income,
            "deductions_by_bucket": deductions,
            "mileage": mileage,
            "estimated_quarterly": estimate,
            "disclaimer": (
                "Organization only — not tax advice. These are your own tagged "
                "numbers; consult a tax professional before filing."
            ),
        }
