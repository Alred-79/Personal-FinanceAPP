"""Analytics router (v2): slice spending like a database.

One aggregation endpoint — totals by category × time bucket — powering the
analytics view that evolves the Transactions page filters (not a new page).
Buckets are computed with SQLite ``strftime`` over the ISO ``date`` strings the
schema already stores. Money aggregates in integer cents; dollars out.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.src.db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Income as IncomeORM,
)
from server.src.db.session import get_db
from server.src.models import UserInDB
from server.src.money import cents_to_dollars
from server.src.services.auth_service import AuthService

router = APIRouter(prefix="/analytics", tags=["analytics"])

_BUCKET_FORMATS = {
    "month": "%Y-%m",
    "week": "%Y-W%W",
    "day": "%Y-%m-%d",
}


@router.get("/spending/")
async def spending_aggregation(
    current_user: Annotated[UserInDB, Depends(AuthService.get_current_active_user)],
    start: Optional[date] = None,
    end: Optional[date] = None,
    bucket: Literal["month", "week", "day"] = Query("month"),
    tx_type: Literal["expense", "income"] = Query("expense"),
    include_recurring: bool = Query(True),
    db: Session = Depends(get_db),
):
    """Totals by category × time bucket over a date range.

    Returns both the flat rows (``cells``) and per-axis totals so the UI can
    render a pivot without re-aggregating client-side.
    """
    model = ExpenseORM if tx_type == "expense" else IncomeORM
    fmt = _BUCKET_FORMATS[bucket]
    # Date bucketing is dialect-aware. ``func.strftime`` is SQLite-only; Postgres
    # has no such function. Because ``date`` is a date-only ISO string
    # (``YYYY-MM-DD``), the month/day buckets are a plain substring on PG, and the
    # week bucket uses ISO-week ``to_char``. NOTE: Postgres ISO week (``IW``)
    # differs from SQLite ``%W`` numbering near year boundaries — validate the
    # week-bucket keys against a live Postgres before relying on them.
    if db.get_bind().dialect.name == "sqlite":
        bucket_expr = func.strftime(fmt, model.date).label("bucket")
    elif bucket == "day":
        bucket_expr = func.substr(model.date, 1, 10).label("bucket")
    elif bucket == "month":
        bucket_expr = func.substr(model.date, 1, 7).label("bucket")
    else:  # week
        bucket_expr = func.to_char(
            func.to_date(model.date, "YYYY-MM-DD"), 'IYYY-"W"IW'
        ).label("bucket")

    query = (
        select(
            bucket_expr,
            model.category,
            func.sum(model.amount).label("total_cents"),
            func.count(model.id).label("count"),
        )
        .join(AccountORM, model.account_id == AccountORM.id)
        .where(AccountORM.user_id == current_user.id)
        .group_by("bucket", model.category)
        .order_by("bucket")
    )
    if start is not None:
        query = query.where(model.date >= start.isoformat())
    if end is not None:
        # HOUSE RULE: ranges are conceptually half-open ``[start, nextday)``. For
        # the date-only ISO strings stored here, an inclusive ``<= end`` is
        # exactly equivalent (it includes the whole ``end`` day) and is kept for
        # clarity; any future range over a *time-bearing* column must use the
        # half-open form ``< (end + 1 day)`` so the last day isn't dropped.
        query = query.where(model.date <= end.isoformat())
    if not include_recurring:
        query = query.where(model.recurrence.is_(None))

    rows = db.execute(query).all()

    cells = []
    by_category: dict[str, int] = {}
    by_bucket: dict[str, int] = {}
    grand_total = 0
    for bucket_key, category, total_cents, count in rows:
        total_cents = int(total_cents or 0)
        cells.append(
            {
                "bucket": bucket_key,
                "category": category,
                "total": cents_to_dollars(total_cents),
                "count": count,
            }
        )
        by_category[category] = by_category.get(category, 0) + total_cents
        by_bucket[bucket_key] = by_bucket.get(bucket_key, 0) + total_cents
        grand_total += total_cents

    return {
        "bucket": bucket,
        "tx_type": tx_type,
        "cells": cells,
        "totals_by_category": {
            k: cents_to_dollars(v)
            for k, v in sorted(by_category.items(), key=lambda kv: -kv[1])
        },
        "totals_by_bucket": {
            k: cents_to_dollars(v) for k, v in sorted(by_bucket.items())
        },
        "grand_total": cents_to_dollars(grand_total),
    }
