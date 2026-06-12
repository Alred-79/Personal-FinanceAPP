"""Metrics jobs + the internal outcomes page data (v4 §13).

Weekly rollups of the MONEY metrics the whole project is judged on — not
engagement. Every function here is a documented DV query: deterministic reads
over the event log and posted finance data, written to ``metric_rollups``
(observability, never ``game_events``).

The headline metrics:

* **hard-day action rate** — fraction of hard-day triggers (Grace applied, a
  negative-forecast alert) followed by a verified money action within 48h.
  The single most important number: does the layer help on the days that
  matter?
* **alert→fix rate** — AlertFixApplied / AlertFired.
* **end-of-month spend distortion** — the last-3-days discretionary share of
  the month's discretionary spend (the TFI check: a scoring system must NOT
  produce a month-end starve-and-binge pattern; score_run receives no dates,
  and this metric verifies the absence at the spend level).
* **E9 sweep totals** — per-arm (cosmetic vs sweep) Heat outcomes from 09's
  ``arm`` tags.

The outcomes page (internal v0) renders per-cohort comparisons with normal-
approximation confidence intervals and an honesty footer — sample sizes and
caveats, no marketing language. Publishing anything is an owner decision.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import (
    Account as AccountORM,
    CategorySettings as CategorySettingsORM,
    Expense as ExpenseORM,
    GameEvent,
    HeatContract,
    MetricRollup,
    User as UserORM,
)
from ...models import UserInDB

HARD_DAY_ACTION_WINDOW_DAYS = 2  # "within 48h"


def _payload_date(payload: dict) -> Optional[date]:
    raw = payload.get("date") or payload.get("day")
    try:
        return date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None


def _events_with_dates(db: Session, types: tuple[str, ...]) -> list[tuple[str, date]]:
    rows = db.execute(
        select(GameEvent.type, GameEvent.payload).where(GameEvent.type.in_(types))
    ).all()
    out = []
    for ev_type, raw in rows:
        d = _payload_date(json.loads(raw))
        if d is not None:
            out.append((ev_type, d))
    return out


# ── DV: hard-day action rate ────────────────────────────────────────────────


def hard_day_action_rate(
    db: Session, window_start: date, window_end: date
) -> Optional[float]:
    """Fraction of hard-day triggers followed by a verified money action
    within 48h. Triggers: GraceApplied, AlertFired. Actions: the XP_BEARING
    set minus ConsistencyVerb (a check-in is not a money action). None when
    the window has no triggers (no rate exists; never fake a 100%)."""
    from .xp import XP_BEARING

    action_types = tuple(t for t in XP_BEARING if t != "ConsistencyVerb")
    triggers = [
        d for t, d in _events_with_dates(db, ("GraceApplied", "AlertFired"))
        if window_start <= d <= window_end
    ]
    if not triggers:
        return None
    actions = sorted(d for _, d in _events_with_dates(db, action_types))
    hit = sum(
        1 for trig in triggers
        if any(trig <= a <= trig + timedelta(days=HARD_DAY_ACTION_WINDOW_DAYS)
               for a in actions)
    )
    return round(hit / len(triggers), 4)


# ── DV: alert→fix rate ──────────────────────────────────────────────────────


def alert_fix_rate(
    db: Session, window_start: date, window_end: date
) -> Optional[float]:
    """AlertFixApplied / AlertFired inside the window. None when no alerts
    fired (a user with zero alerts has no fix rate)."""
    events = _events_with_dates(db, ("AlertFired", "AlertFixApplied"))
    fired = sum(1 for t, d in events
                if t == "AlertFired" and window_start <= d <= window_end)
    fixed = sum(1 for t, d in events
                if t == "AlertFixApplied" and window_start <= d <= window_end)
    if fired == 0:
        return None
    return round(min(fixed / fired, 1.0), 4)


# ── DV: end-of-month spend distortion (the TFI check) ───────────────────────


def distortion_share(db: Session, user_id: int, month: str) -> Optional[float]:
    """Last-3-days discretionary share of the month's discretionary spend.
    A healthy month has roughly 3/30 ≈ 0.10 here; a scoring-induced starve-
    and-binge pattern shows up as a spike. None when the month had no
    discretionary spend."""
    from calendar import monthrange

    year, mon = (int(x) for x in month.split("-"))
    last_day = monthrange(year, mon)[1]
    month_start = date(year, mon, 1)
    month_end = date(year, mon, last_day)
    tail_start = month_end - timedelta(days=2)

    essentials = {
        n for n in db.execute(
            select(CategorySettingsORM.name).where(
                CategorySettingsORM.essential == 1
            )
        ).scalars()
    }
    acct_ids = list(db.execute(
        select(AccountORM.id).where(AccountORM.user_id == user_id)
    ).scalars())
    if not acct_ids:
        return None
    rows = db.execute(
        select(ExpenseORM.amount, ExpenseORM.date, ExpenseORM.category).where(
            ExpenseORM.account_id.in_(acct_ids),
            ExpenseORM.date >= month_start.isoformat(),
            ExpenseORM.date <= month_end.isoformat(),
        )
    ).all()
    total = 0
    tail = 0
    for amount, d, category in rows:
        if category in essentials:
            continue
        total += amount
        if d >= tail_start.isoformat():
            tail += amount
    if total <= 0:
        return None
    return round(tail / total, 4)


# ── DV: E9 per-arm sweep totals (09's tags) ─────────────────────────────────


def e9_sweep_totals(db: Session, as_of: Optional[date] = None) -> dict:
    """Per-arm Heat outcomes from the ``heat_contracts.arm`` tags: contract
    counts, met counts, and (for the sweep arm) total verified-underspend
    cents recomputed from posted data — never the contracted hope."""
    from .heat import HeatService

    as_of = as_of or date.today()
    contracts = db.execute(select(HeatContract)).scalars().all()
    out: dict[str, dict] = {}
    heat = HeatService(db)
    for c in contracts:
        arm = out.setdefault(
            c.arm, {"contracts": 0, "met": 0, "swept_cents": 0}
        )
        arm["contracts"] += 1
        if c.status == "met":
            arm["met"] += 1
            if c.arm == "sweep":
                user_row = db.get(UserORM, c.user_id)
                if user_row is not None:
                    user = UserInDB(
                        id=user_row.id, username=user_row.username,
                        email=user_row.email, full_name=user_row.full_name,
                        disabled=bool(user_row.disabled), hashed_password="",
                    )
                    arm["swept_cents"] += heat.verified_underspend_cents(
                        user, c, as_of
                    )
    return out


# ── supporting rollups (documented v0 reads) ────────────────────────────────


def paydown_cents(db: Session, window_start: date, window_end: date) -> int:
    """Sum of PaymentPosted amounts in the window (liability paydown)."""
    rows = db.execute(
        select(GameEvent.payload).where(GameEvent.type == "PaymentPosted")
    ).scalars().all()
    total = 0
    for raw in rows:
        payload = json.loads(raw)
        d = _payload_date(payload)
        if d is not None and window_start <= d <= window_end:
            total += int(payload.get("amount_cents", 0))
    return total


def on_time_bill_count(db: Session, window_start: date, window_end: date) -> int:
    return sum(
        1 for _, d in _events_with_dates(db, ("BillPaidOnTime",))
        if window_start <= d <= window_end
    )


# ── the weekly job ──────────────────────────────────────────────────────────

ROLLUP_METRICS = ("hard_day_action_rate", "alert_fix_rate", "distortion_share")


def run_weekly_rollups(db: Session, week_end: date) -> int:
    """Write the week's rollup rows for every user (idempotent per
    (user, week, metric) via the unique constraint). Returns rows written."""
    week_start = week_end - timedelta(days=6)
    month = f"{week_end.year}-{week_end.month:02d}"
    written = 0
    users = db.execute(select(UserORM)).scalars().all()
    for user_row in users:
        cohort = user_row.experiment_cohort or ""
        values = {
            "hard_day_action_rate": hard_day_action_rate(db, week_start, week_end),
            "alert_fix_rate": alert_fix_rate(db, week_start, week_end),
            "distortion_share": distortion_share(db, user_row.id, month),
        }
        for metric, value in values.items():
            if value is None:
                continue  # no rate exists — never write a fake zero/100
            exists = db.execute(
                select(MetricRollup.id).where(
                    MetricRollup.user_id == user_row.id,
                    MetricRollup.week == week_end.isoformat(),
                    MetricRollup.metric == metric,
                )
            ).scalar_one_or_none()
            if exists is not None:
                continue
            db.add(MetricRollup(
                user_id=user_row.id, week=week_end.isoformat(), metric=metric,
                value=float(value), cohort=cohort,
                created_at=datetime.now(timezone.utc).isoformat(),
            ))
            written += 1
    db.flush()
    return written


# ── the outcomes page (internal v0) ─────────────────────────────────────────


def _mean_ci(values: list[float]) -> dict:
    n = len(values)
    mean = sum(values) / n
    if n > 1:
        var = sum((v - mean) ** 2 for v in values) / (n - 1)
        half = 1.96 * math.sqrt(var / n)
    else:
        half = 0.0
    return {
        "n": n,
        "mean": round(mean, 4),
        "ci_low": round(mean - half, 4),
        "ci_high": round(mean + half, 4),
    }


def outcomes_summary(db: Session) -> dict:
    """The internal outcomes page payload: per-cohort, per-metric means with
    95% normal-approximation CIs, plus the honesty footer. No marketing
    language lives here — only numbers and caveats."""
    rows = db.execute(select(MetricRollup)).scalars().all()
    by_metric: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        cohort = r.cohort or "unassigned"
        by_metric.setdefault(r.metric, {}).setdefault(cohort, []).append(r.value)
    comparison = {
        metric: {cohort: _mean_ci(vals) for cohort, vals in cohorts.items()}
        for metric, cohorts in by_metric.items()
    }
    sample_sizes = {
        cohort: len({r.user_id for r in rows if (r.cohort or "unassigned") == cohort})
        for cohort in {(r.cohort or "unassigned") for r in rows}
    }
    return {
        "comparison": comparison,
        "honesty_footer": {
            "sample_sizes": sample_sizes,
            "caveats": [
                "Internal v0. Cohorts are observational until the holdout has "
                "a full campaign cycle of data.",
                "Confidence intervals use a normal approximation; small "
                "samples are wide and shown as such.",
                "No metric here measures engagement; all are money outcomes.",
                "Publishing any of this is an owner decision (v4 §17).",
            ],
        },
    }
