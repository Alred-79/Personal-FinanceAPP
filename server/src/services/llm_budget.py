"""DB-backed, race-safe LLM cost budget (Step 02 — denial-of-wallet, OWASP LLM10).

The assistant calls paid Groq + Tavily. Without a per-user daily ceiling, a
runaway agent loop or an over-eager user can run up a real bill — and the owner
of a personal-finance app is exactly the person who cares about a surprise API
charge. This module is the shared primitive Steps 03 (chat) and 04
(propose/confirm) reserve against, so cost control is consistent instead of
reinvented per endpoint.

Units (the crux):
- ``requests`` — a hard cap (``settings.llm_daily_request_budget``). Every
  chat/propose call reserves exactly 1.
- ``cost_cents`` — a hard cap (``settings.llm_daily_cost_budget_cents``), the
  real DOLLAR ceiling (A3). Pre-flight reserves a conservative estimate; the
  chat stream reconciles it to the ACTUAL cost — exact Groq ``usage_metadata``
  when the response carries it, else a tiktoken count — priced via
  ``token_meter.cost_cents``. Both caps are checked in one conditional UPDATE.
- ``tokens`` — ADVISORY / observability only (a token total for dashboards);
  the dollar figure, not this, is what gates spend.

Concurrency: ``check_and_reserve`` is TOCTOU-free. The cap check and the
increment are a SINGLE conditional UPDATE whose WHERE clause carries the cap
(``requests + :req <= :budget``), so there is no read-then-write window. Under
SQLite's single-writer serialization this is the same atomic pattern Step 06
uses for transfers — it does NOT rely on "increment then roll back."
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from server.src.settings import settings


class BudgetExceeded(Exception):
    """Raised when a reservation would push a user over the daily request cap."""


def today_key() -> str:
    """The single canonical server-local date string for the day boundary.

    Chat and actions MUST both call this (never their own ``date.today``) so a
    user isn't blocked at 23:59 by one date function then mysteriously unblocked
    at 00:01 by a different one. Server-local by design (see report caveat); one
    helper keeps the boundary deterministic across the whole app.
    """
    return date.today().isoformat()


def _ensure_row(db: Session, user_id: int, day: str) -> None:
    """Seed the (user_id, day) meter row if absent. Idempotent."""
    db.execute(
        text(
            "INSERT INTO llm_usage (user_id, day, tokens, requests, cost_cents) "
            "VALUES (:uid, :day, 0, 0, 0) "
            "ON CONFLICT(user_id, day) DO NOTHING"
        ),
        {"uid": user_id, "day": day},
    )


def check_and_reserve(
    db: Session,
    user_id: int,
    *,
    est_tokens: int = 0,
    est_cost_cents: int = 0,
    requests: int = 1,
) -> None:
    """Atomically reserve ``requests`` (and an estimated cost) against today.

    TWO hard caps are enforced in ONE conditional UPDATE: the day's requests
    must stay ``<= llm_daily_request_budget`` AND the day's accumulated cost must
    stay ``<= llm_daily_cost_budget_cents`` (when that budget is > 0). If the
    UPDATE matches no row, neither counter is written and ``BudgetExceeded`` is
    raised — all-or-nothing, no partial/over-cap write, no read-then-write window.

    ``est_cost_cents`` is a conservative pre-flight estimate reserved up front;
    the stream later reconciles it to the actual figure via ``record_cost``.
    ``est_tokens`` still rides along as the advisory token figure.
    """
    day = today_key()
    req_budget = settings.llm_daily_request_budget
    cost_budget = settings.llm_daily_cost_budget_cents

    _ensure_row(db, user_id, day)

    # The cost clause is only enforced when a cost budget is configured (> 0);
    # ``:cost_budget`` is bound either way so the SQL is static.
    cost_clause = (
        "AND cost_cents + :est_cost <= :cost_budget" if cost_budget > 0 else ""
    )
    result = db.execute(
        text(
            "UPDATE llm_usage "
            "SET requests = requests + :req, tokens = tokens + :est, "
            "    cost_cents = cost_cents + :est_cost "
            "WHERE user_id = :uid AND day = :day "
            "AND requests + :req <= :req_budget "
            f"{cost_clause}"
        ),
        {
            "req": requests,
            "est": est_tokens,
            "est_cost": est_cost_cents,
            "uid": user_id,
            "day": day,
            "req_budget": req_budget,
            "cost_budget": cost_budget,
        },
    )

    if result.rowcount == 0:
        # The row exists (we just seeded it), so a zero rowcount means one of the
        # cap clauses rejected the increment — over the request or the cost cap.
        raise BudgetExceeded(
            "Daily AI budget reached for today "
            f"(requests <= {req_budget}, cost <= {cost_budget}c)."
        )


def release_request(
    db: Session, user_id: int, requests: int = 1, *, reserved_cost_cents: int = 0
) -> None:
    """Give back ``requests`` (and any reserved cost) when a call did no paid work.

    The chat endpoint reserves one request + an estimated cost **pre-flight**
    (the real hard caps). If the stream then errors *before any model call*, no
    paid Groq/Tavily work happened, so permanently consuming the user's daily
    slot or charging the estimate would be unfair — a buggy client retry could
    exhaust the cap on errors alone. This decrements the request counter and the
    reserved cost (both clamped at 0). Call it only on the "no model call" path.
    """
    if requests <= 0 and reserved_cost_cents <= 0:
        return
    day = today_key()
    db.execute(
        text(
            "UPDATE llm_usage "
            "SET requests = MAX(0, requests - :req), "
            "    cost_cents = MAX(0, cost_cents - :cost) "
            "WHERE user_id = :uid AND day = :day"
        ),
        {"req": max(0, requests), "cost": max(0, reserved_cost_cents),
         "uid": user_id, "day": day},
    )


def record_cost(
    db: Session, user_id: int, actual_cost_cents: int, *, reserved_cost_cents: int = 0
) -> None:
    """Reconcile the pre-flight cost estimate to the ACTUAL cost after a run.

    Pre-flight reserved ``reserved_cost_cents``; the real run cost
    ``actual_cost_cents`` (from Groq usage or a tiktoken count). Apply the delta
    so the day's ``cost_cents`` reflects truth — over-estimates are refunded,
    under-estimates are topped up. Clamped at 0; never touches the request count.
    """
    delta = actual_cost_cents - reserved_cost_cents
    if delta == 0:
        return
    day = today_key()
    _ensure_row(db, user_id, day)
    db.execute(
        text(
            "UPDATE llm_usage SET cost_cents = MAX(0, cost_cents + :delta) "
            "WHERE user_id = :uid AND day = :day"
        ),
        {"delta": delta, "uid": user_id, "day": day},
    )


def record_actual(db: Session, user_id: int, tokens: int) -> None:
    """Reconcile the TOKEN estimate after a run, iff a real count is available.

    A no-op when no real token count exists (the request was already counted at
    reserve time, so the hard cap is intact regardless). ``record_actual(.., 0)``
    therefore does nothing — by design, the request count is never touched here.
    Token totals never go negative.
    """
    if tokens <= 0:
        return
    day = today_key()
    _ensure_row(db, user_id, day)
    db.execute(
        text(
            "UPDATE llm_usage SET tokens = MAX(0, tokens + :tok) "
            "WHERE user_id = :uid AND day = :day"
        ),
        {"tok": tokens, "uid": user_id, "day": day},
    )


def remaining(db: Session, user_id: int) -> int:
    """Requests remaining today, for surfacing "near your daily AI limit" in UI.

    Clamped at 0. This is the request count (the real cap) — deliberately NOT a
    token "remaining", which would always read full off a 0-metering source and
    mislead the user.
    """
    day = today_key()
    used = db.execute(
        text(
            "SELECT requests FROM llm_usage WHERE user_id = :uid AND day = :day"
        ),
        {"uid": user_id, "day": day},
    ).scalar_one_or_none()
    used = used or 0
    return max(0, settings.llm_daily_request_budget - used)
