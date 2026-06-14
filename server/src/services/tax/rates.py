"""Per-year IRS rate constants for the tax-summary engine.

Pure data + small lookups, no LLM, integer cents throughout (mirrors the
integer-cents discipline of ``money.py`` / ``forecast_service``). These are
FACTS the user's own arithmetic is run against — not advice. US calendar-year
filer assumption.

If a tax year is not in a table the engine treats the figure as unavailable and
says so, rather than guessing — the summary must never fabricate a rate.
"""

from __future__ import annotations

from typing import Optional

# ── standard mileage rate (business), cents per mile, by tax year ────────────
# Source: IRS standard mileage rates (business use), stored as INTEGER cents per
# mile. Add a new year here as the IRS publishes it; an unknown year returns None
# (engine omits mileage rather than guessing). 2023's 65.5¢ is rounded to the
# integer cent the engine arithmetic uses (documented; sub-cent precision is not
# meaningful against integer-cent ledger math).
MILEAGE_CENTS_PER_MILE: dict[int, int] = {
    2023: 66,   # 65.5¢ → 66¢ (integer-cent arithmetic)
    2024: 67,   # 67¢
    2025: 70,   # 70¢
    2026: 70,   # 70¢ (placeholder until IRS publishes 2026)
}


def mileage_rate_cents(tax_year: int) -> Optional[int]:
    """Business standard mileage rate in cents per mile for *tax_year*, or None."""
    return MILEAGE_CENTS_PER_MILE.get(tax_year)


# ── quarterly estimated-tax due dates, by tax year ───────────────────────────
# (quarter label, due date ISO string). The dates are the IRS estimated-tax due
# dates for that tax year (Q4 falls in January of the following year).
_QUARTERLY_DUE_DATES: dict[int, list[tuple[str, str]]] = {
    2025: [
        ("Q1", "2025-04-15"),
        ("Q2", "2025-06-16"),
        ("Q3", "2025-09-15"),
        ("Q4", "2026-01-15"),
    ],
    2026: [
        ("Q1", "2026-04-15"),
        ("Q2", "2026-06-16"),
        ("Q3", "2026-09-15"),
        ("Q4", "2027-01-15"),
    ],
}


def quarterly_due_dates(tax_year: int) -> list[tuple[str, str]]:
    """The four ``(quarter, iso_date)`` estimated-tax due dates for *tax_year*.

    Empty list if the year isn't tabulated (engine omits the reminder rather
    than fabricating a date).
    """
    return list(_QUARTERLY_DUE_DATES.get(tax_year, []))


# ── a deliberately simple effective rate for the ESTIMATE only ───────────────
# RETAINED for back-compat / the no-bracket-table fallback only. The real engine
# (``estimate_quarterly``) now splits self-employment tax from a bracketed income
# tax (below). A flat blended rate is only used if a year has no bracket table.
ESTIMATE_FLAT_RATE_BPS: int = 2500  # 25%, blended SE + income (fallback only)

# ─────────────────────────────────────────────────────────────────────────────
# Real (still ESTIMATE, never advice) federal parameters by tax year.
#
# These are PUBLISHED IRS figures the user's OWN arithmetic is run against — the
# same stance as the mileage rate above: a fact, not a recommendation. The engine
# is transparent (it returns its breakdown + methodology) and loudly disclaimed.
# An UNTABULATED year falls back to the flat rate above rather than guessing.
#
# Scope (matches the two target users: a W-2 employee with side income, and a
# 1099 sole proprietor): federal income tax via marginal brackets + the standard
# deduction, plus self-employment tax (Social Security capped at the wage base,
# Medicare uncapped) on net SE earnings. NO credits, NO QBI, NO itemizing, NO
# AMT, NO additional-Medicare surtax — each would need inputs we don't collect,
# and adding a wrong one is worse than omitting it. State is an optional flat rate
# the user supplies (0 = skip). This is an ESTIMATE for setting aside money, not a
# return.
# ─────────────────────────────────────────────────────────────────────────────

# Self-employment tax (Schedule SE). Net SE earnings are first multiplied by
# 92.35% (the employer-equivalent deduction), then taxed at 15.3% — but the
# 12.4% Social Security portion only applies up to the annual wage base, and W-2
# wages consume that base FIRST. The 2.9% Medicare portion is uncapped.
SE_NET_EARNINGS_BPS: int = 9235          # 92.35% of net SE earnings is the SE base
SE_SOCIAL_SECURITY_BPS: int = 1240       # 12.4% OASDI portion (capped)
SE_MEDICARE_BPS: int = 290               # 2.9% Medicare portion (uncapped)
HALF_SE_TAX_BPS: int = 5000              # half of SE tax is an above-the-line adjustment

# Social Security wage base (the OASDI cap), in INTEGER CENTS, by tax year.
SS_WAGE_BASE_CENTS: dict[int, int] = {
    2025: 17_610_000,   # $176,100
    2026: 18_450_000,   # $184,500 (placeholder until SSA publishes; update on release)
}

# Standard deduction in INTEGER CENTS, by tax year and filing status. The four
# IRS statuses; "mfj" = married filing jointly, "mfs" = married filing separately,
# "hoh" = head of household.
STANDARD_DEDUCTION_CENTS: dict[int, dict[str, int]] = {
    2025: {
        "single": 1_500_000,   # $15,000
        "mfj": 3_000_000,      # $30,000
        "mfs": 1_500_000,      # $15,000
        "hoh": 2_250_000,      # $22,500
    },
    2026: {
        "single": 1_600_000,   # $16,000  (placeholder; update on IRS release)
        "mfj": 3_200_000,      # $32,000
        "mfs": 1_600_000,      # $16,000
        "hoh": 2_400_000,      # $24,000
    },
}

# Federal income-tax brackets, INTEGER CENTS, by tax year and filing status. Each
# entry is ``(lower_bound_cents, rate_bps)`` sorted ascending; the bracket runs
# from its lower bound up to the NEXT entry's lower bound (the last is open-ended).
# Marginal: each slice of taxable income is taxed at its own bracket's rate.
_BRACKETS_2025: dict[str, list[tuple[int, int]]] = {
    "single": [
        (0, 1000), (1_192_500, 1200), (4_847_500, 2200),
        (10_335_000, 2400), (19_730_000, 3200),
        (25_052_500, 3500), (62_635_000, 3700),
    ],
    "mfj": [
        (0, 1000), (2_385_000, 1200), (9_695_000, 2200),
        (20_670_000, 2400), (39_460_000, 3200),
        (50_105_000, 3500), (75_160_000, 3700),
    ],
    "hoh": [
        (0, 1000), (1_700_000, 1200), (6_485_000, 2200),
        (10_335_000, 2400), (19_730_000, 3200),
        (25_050_000, 3500), (62_635_000, 3700),
    ],
}
# mfs mirrors half of mfj at the top; for an estimate we reuse the single schedule
# for the lower brackets (close enough for set-aside purposes, and labelled).
_BRACKETS_2025["mfs"] = _BRACKETS_2025["single"]

# 2026 placeholder: reuse 2025's structure until the IRS publishes inflation-
# adjusted figures (documented; an estimate, not a filing figure).
_BRACKETS_2026 = {k: list(v) for k, v in _BRACKETS_2025.items()}

FEDERAL_BRACKETS_CENTS: dict[int, dict[str, list[tuple[int, int]]]] = {
    2025: _BRACKETS_2025,
    2026: _BRACKETS_2026,
}

FILING_STATUSES: frozenset[str] = frozenset(
    {"single", "mfj", "mfs", "hoh"}
)


def standard_deduction_cents(tax_year: int, filing_status: str) -> Optional[int]:
    """Standard deduction for a year+status in cents, or None if untabulated."""
    return STANDARD_DEDUCTION_CENTS.get(tax_year, {}).get(filing_status)


def ss_wage_base_cents(tax_year: int) -> Optional[int]:
    """Social Security wage base (OASDI cap) for a year in cents, or None."""
    return SS_WAGE_BASE_CENTS.get(tax_year)


def federal_income_tax_cents(taxable_cents: int, tax_year: int, filing_status: str) -> Optional[int]:
    """Marginal federal income tax on ``taxable_cents`` (integer cents).

    Returns None if the year/status has no bracket table (caller falls back to the
    flat estimate). Pure integer arithmetic: each income slice is taxed at its
    own bracket's rate and the parts are summed.
    """
    table = FEDERAL_BRACKETS_CENTS.get(tax_year, {}).get(filing_status)
    if not table:
        return None
    if taxable_cents <= 0:
        return 0
    tax = 0
    for i, (lower, rate_bps) in enumerate(table):
        if taxable_cents <= lower:
            break
        upper = table[i + 1][0] if i + 1 < len(table) else taxable_cents
        slice_top = min(taxable_cents, upper)
        tax += (slice_top - lower) * rate_bps // 10000
    return tax


def self_employment_tax_cents(
    se_net_cents: int, wages_cents: int, tax_year: int
) -> dict:
    """Schedule-SE tax on net self-employment earnings, integer cents.

    W-2 wages consume the Social Security wage base FIRST, so only the remaining
    headroom of the SE base is hit with the 12.4% OASDI portion; the 2.9%
    Medicare portion is uncapped. Returns ``{se_tax_cents, se_base_cents,
    half_se_tax_cents, ss_wage_base_cents}``. A year with no published wage base
    falls back to an UNcapped SS portion (conservative — never under-estimates).
    """
    if se_net_cents <= 0:
        return {
            "se_tax_cents": 0,
            "se_base_cents": 0,
            "half_se_tax_cents": 0,
            "ss_wage_base_cents": ss_wage_base_cents(tax_year),
        }
    se_base = se_net_cents * SE_NET_EARNINGS_BPS // 10000
    base = ss_wage_base_cents(tax_year)
    if base is None:
        ss_taxable = se_base  # no cap known → don't under-estimate
    else:
        # Wages already used up part of the OASDI cap (wages are not ×92.35%).
        remaining_cap = max(0, base - max(0, wages_cents))
        ss_taxable = min(se_base, remaining_cap)
    ss_tax = ss_taxable * SE_SOCIAL_SECURITY_BPS // 10000
    medicare_tax = se_base * SE_MEDICARE_BPS // 10000
    se_tax = ss_tax + medicare_tax
    return {
        "se_tax_cents": se_tax,
        "se_base_cents": se_base,
        "half_se_tax_cents": se_tax * HALF_SE_TAX_BPS // 10000,
        "ss_wage_base_cents": base,
    }
