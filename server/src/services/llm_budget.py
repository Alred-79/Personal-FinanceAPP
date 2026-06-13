"""DB-backed, race-safe LLM cost budget (Step 02 — denial-of-wallet, OWASP LLM10).

The assistant calls paid Groq + Tavily. Without a per-user daily ceiling, a
runaway agent loop or an over-eager user can run up a real bill — and the owner
of a personal-finance app is exactly the person who cares about a surprise API
charge. This module is the shared primitive Steps 03 (chat) and 04
(propose/confirm) reserve against, so cost control is consistent instead of
reinvented per endpoint.

Unit honesty (the crux):
- ``requests`` is the ONLY genuinely-enforced cap. The chat path streams via
  ``astream_events(version="v2")``, which surfaces no usage metadata, so there
  is no real post-stream token count to meter. Every chat/propose call costs
  exactly 1 request; ``settings.llm_daily_request_budget`` is the real ceiling.
- ``tokens`` is ADVISORY / observability only — a best-effort pre-flight
  estimate. It is NEVER used to deny a request here, because a token cap that
  silently records 0 on streaming would read to the user as a working cap while
  metering nothing. Keep it for the day a real usage source lands (Step 03).

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
            "INSERT INTO llm_usage (user_id, day, tokens, requests) "
            "VALUES (:uid, :day, 0, 0) "
            "ON CONFLICT(user_id, day) DO NOTHING"
        ),
        {"uid": user_id, "day": day},
    )


def check_and_reserve(
    db: Session, user_id: int, *, est_tokens: int = 0, requests: int = 1
) -> None:
    """Atomically reserve ``requests`` against today's request budget.

    Adds ``requests`` (and ``est_tokens`` for observability) in one conditional
    UPDATE whose WHERE clause enforces the cap. If the UPDATE matches no row
    (the increment would exceed the budget), the reservation does NOT persist
    and ``BudgetExceeded`` is raised. The request was either fully reserved or
    not at all — never a partial/over-cap write.

    ``est_tokens`` rides along on the same statement purely as an advisory
    estimate; it never gates the reservation (see module docstring).
    """
    day = today_key()
    budget = settings.llm_daily_request_budget

    _ensure_row(db, user_id, day)

    result = db.execute(
        text(
            "UPDATE llm_usage "
            "SET requests = requests + :req, tokens = tokens + :est "
            "WHERE user_id = :uid AND day = :day "
            "AND requests + :req <= :budget"
        ),
        {
            "req": requests,
            "est": est_tokens,
            "uid": user_id,
            "day": day,
            "budget": budget,
        },
    )

    if result.rowcount == 0:
        # The row exists (we just seeded it), so a zero rowcount means the cap
        # clause rejected the increment — over budget.
        raise BudgetExceeded(
            f"Daily AI request budget of {budget} reached for today."
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
