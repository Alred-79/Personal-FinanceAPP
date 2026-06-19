"""Step 09 — the production game scheduler (APScheduler).

The dormant game jobs (month-close, weekly rollups, fade, graduation) had NO
production entry point — only tests called them — so months never sealed,
``/game/outcomes/`` stayed empty, and expeditions were drafted but never scored.
This module gives them an unattended, idempotent, kill-switch-respecting cron
home.

Design (the spec's "keep scheduling thin"):

* ``build_scheduler()`` returns an ``AsyncIOScheduler`` with declarative cron
  triggers. ``start_scheduler``/``shutdown_scheduler`` are driven from the
  FastAPI lifespan. Guarded by ``settings.scheduler_enabled`` (FALSE in tests).
* Each trigger calls a PURE, directly-testable job function. A scheduled job
  runs OUTSIDE any request, so there is no ``Depends(get_db)`` session — every
  job opens its OWN ``SessionLocal()`` (the same own-session rule as Step 03's
  reconciliation), runs the idempotent work, commits, and closes.
* Every job skips ``settings.killed_features`` (via ``experiments.is_killed``)
  and is safe to re-run, so a restart or an overlapping fire can't double-seal.

⚠ SINGLE-WORKER INVARIANT (shared with Steps 02/05): an ``AsyncIOScheduler``
starts once PER worker process. Two uvicorn workers fire every job twice at the
boundary — idempotency keeps that harmless in OUTCOME, but it doubles work and
is fragile. Run ONE worker until a leader-elected / external trigger exists
(production backlog). Enforced/announced at startup in ``main.py``.
"""

from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .settings import settings

logger = logging.getLogger("game.scheduler")


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _prev_month_str(today: date) -> str:
    """The ``YYYY-MM`` of the month immediately BEFORE *today*'s month — the
    month a month-boundary run seals."""
    first_of_this = today.replace(day=1)
    last_of_prev = first_of_this - timedelta(days=1)
    return f"{last_of_prev.year}-{last_of_prev.month:02d}"


def _month_end(month: str) -> date:
    year, mon = (int(x) for x in month.split("-"))
    return date(year, mon, monthrange(year, mon)[1])


def _users(db: Session):
    from .db.models import User as UserORM

    return db.execute(select(UserORM)).scalars().all()


def _to_user(user_row):
    from .services.auth_service import _to_user_in_db

    return _to_user_in_db(user_row)


def _tracked_metrics(db: Session, user_id: int) -> list[str]:
    """Metrics worth fading/graduating: the user's confirmed, non-essential
    categories (the ones a baseline can be priced against)."""
    from .db.models import CategorySettings as CategorySettingsORM

    rows = db.execute(
        select(CategorySettingsORM.name).where(
            CategorySettingsORM.user_confirmed == 1,
            CategorySettingsORM.essential == 0,
        )
    ).scalars().all()
    return list(rows)


# ---------------------------------------------------------------------------
# The pure, testable jobs. Each takes an explicit ``db`` + ``now`` and is
# idempotent. They DO NOT commit — ``run_due_game_jobs`` (or the scheduled
# wrapper) owns the transaction boundary.
# ---------------------------------------------------------------------------

def job_close_month(db: Session, now: date) -> dict:
    """Seal the month that just ended, for every user. Idempotent (``close_month``
    is keyed on ``seal:{user}:{month}``).

    RLS (C1): binds the tenant per user (``set_tenant`` + ``user_id_var``, reset
    in ``finally``) before sealing, so under a restricted scheduler role the
    month-close reads/writes the user's own rows instead of zero. No-op on SQLite
    and under a BYPASSRLS role.
    """
    from .db.rls import set_tenant
    from .logging_context import user_id_var
    from .services.game.month_close import close_month

    month = _prev_month_str(now)
    sealed: dict[int, dict] = {}
    for user_row in _users(db):
        user = _to_user(user_row)
        set_tenant(db, user.id)
        _uid_token = user_id_var.set(str(user.id))
        try:
            sealed[user.id] = close_month(db, user, month)
        except Exception:  # noqa: BLE001 — one user's failure can't abort the rest
            logger.exception("close_month failed: user=%s month=%s", user.id, month)
        finally:
            user_id_var.reset(_uid_token)  # load-bearing: no contextvar leak
    return {"month": month, "sealed": sealed}


def job_weekly_rollups(db: Session, now: date) -> int:
    """Write the week's MetricRollup rows (feeds ``/game/outcomes/``). Idempotent
    per (user, week, metric)."""
    from .services.game.metrics import run_weekly_rollups

    return run_weekly_rollups(db, now)


def job_fade_and_graduation(db: Session, now: date) -> dict:
    """Advance each user's metric-fade state machine for the week, and detect
    graduation candidates. Skipped while the ``bestiary`` (fade surface) feature
    is killed. Idempotent — fade events are keyed per (user, metric, week)."""
    from .services.game import experiments
    from .services.game.fade import FadeService
    from .services.game.graduation import detect_graduation_candidates

    if experiments.is_killed("bestiary"):
        return {"skipped": "bestiary_killed"}

    from .db.rls import set_tenant
    from .logging_context import user_id_var

    faded: dict[int, dict[str, str]] = {}
    grad: dict[int, int] = {}
    fade = FadeService(db)
    for user_row in _users(db):
        user = _to_user(user_row)
        # RLS (C1): bind the tenant for THIS user before reading/writing fade +
        # graduation rows; reset in finally so the contextvar never leaks.
        set_tenant(db, user.id)
        _uid_token = user_id_var.set(str(user.id))
        try:
            states: dict[str, str] = {}
            for metric in _tracked_metrics(db, user.id):
                try:
                    states[metric] = fade.evaluate_week(user, metric, now)
                except Exception:  # noqa: BLE001 — best-effort per metric
                    logger.exception(
                        "fade evaluate_week failed: user=%s metric=%s", user.id, metric
                    )
            faded[user.id] = states
            try:
                grad[user.id] = len(
                    detect_graduation_candidates(db, user.id, as_of=now)
                )
            except Exception:  # noqa: BLE001
                logger.exception("graduation detect failed: user=%s", user.id)
        finally:
            user_id_var.reset(_uid_token)  # load-bearing: no contextvar leak
    return {"faded": faded, "graduation_candidates": grad}


def run_due_game_jobs(db: Session, now: Optional[datetime | date] = None) -> dict:
    """Run every game job that is due as of *now*, idempotently, in one
    transaction.

    This is the SINGLE pure entry point both the monthly and weekly cron
    triggers (and the tests) call — the cron wrappers just open a session and
    invoke this. Re-running it is a no-op (every underlying job is idempotent),
    so an overlapping fire or a scheduler restart can't double-seal.

    Month-close runs only at a month boundary (when ``now`` is on the 1st), so a
    daily/weekly fire doesn't re-seal mid-month. Weekly rollups + fade run every
    invocation (idempotent per week).
    """
    now = now or datetime.now()
    today = now.date() if isinstance(now, datetime) else now

    result: dict = {"weekly_rollups": job_weekly_rollups(db, today)}
    result["fade"] = job_fade_and_graduation(db, today)
    # Month-close only at the boundary — a job firing on the 1st seals the month
    # that just ended.
    if today.day == 1:
        result["month_close"] = job_close_month(db, today)
    db.flush()
    return result


# ---------------------------------------------------------------------------
# Plan-of-record drift (v6 doc 06) — the FIRST notification producer in the
# scheduler. It does not sit alongside an existing one; the game ticks above
# produce game events, not notifications. Same idempotent + own-session rules.
# ---------------------------------------------------------------------------

def job_check_plan_drift(db: Session, now: Optional[datetime | date] = None) -> int:
    """Re-check every user's ACTIVE plans against their locked snapshots.

    Pure and idempotent: ``ScenarioService.check_drift`` dedups its notifications
    by ``ref`` (``plan_drift:{plan_id}:{period}``), so an overlapping fire or a
    restart cannot double-notify. Kept light (R7): active-only scope and the
    fixed-seed cheap sim path live inside ``check_drift``. Returns the total
    number of plans that produced a notification across all users.
    """
    from .db.rls import set_tenant
    from .logging_context import user_id_var
    from .services.scenario_service import ScenarioService

    now = now or datetime.now()
    today = now.date() if isinstance(now, datetime) else now

    svc = ScenarioService(db)
    total = 0
    for user in _users(db):
        # RLS (C1): bind the tenant per user before the drift re-check; reset in
        # finally. Also adds the per-user try/except so one user can't abort all.
        set_tenant(db, user.id)
        _uid_token = user_id_var.set(str(user.id))
        try:
            total += len(svc.check_drift(user.id, as_of=today))
        except Exception:  # noqa: BLE001 — one user's failure can't abort the rest
            logger.exception("check_drift failed: user=%s", user.id)
        finally:
            user_id_var.reset(_uid_token)  # load-bearing: no contextvar leak
    db.flush()
    return total


# ---------------------------------------------------------------------------
# The Detangler (messy-data ingestion) — a second notification producer. Flags
# transfer/refund/duplicate pairs across every user's transactions. Idempotent
# per pairing ``ref`` like the drift job, so a re-fire never double-notifies.
# ---------------------------------------------------------------------------

def job_detangle(db: Session, now: Optional[datetime | date] = None) -> int:
    """Run the Detangler for every user. Returns total new pairings flagged.

    Pure and idempotent: ``DetangleService.run`` dedups its notifications by
    ``ref`` (``detangle:{kind}:{a}:{b}``), so an overlapping fire or a restart
    cannot double-notify. Gated by ``settings.detangle_enabled`` at the tick.
    """
    from .db.rls import set_tenant
    from .logging_context import user_id_var
    from .services.detangle_service import DetangleService

    svc = DetangleService(db)
    total = 0
    for user in _users(db):
        # RLS (C1): bind the tenant per user before the Detangler reads their
        # transactions; reset in finally. Adds the per-user try/except too.
        set_tenant(db, user.id)
        _uid_token = user_id_var.set(str(user.id))
        try:
            total += len(svc.run(user.id))
        except Exception:  # noqa: BLE001 — one user's failure can't abort the rest
            logger.exception("detangle failed: user=%s", user.id)
        finally:
            user_id_var.reset(_uid_token)  # load-bearing: no contextvar leak
    db.flush()
    return total


# ---------------------------------------------------------------------------
# Pillar 3 — quarterly estimated-tax reminder. Clones the drift/detangle shape:
# pure, idempotent per ``ref``, self-gated on ``settings.tax_features_enabled``.
# FACTUAL and NON-DIRECTIVE — it states the approaching due date and the user's
# own tagged YTD numbers, never "you should pay". Carries a Pillar-2 Bridge hook
# in spirit ("pay $X at irs.gov/payments") but the notification itself is just a
# factual nudge.
# ---------------------------------------------------------------------------

# Fire the reminder when a due date is within this many days.
_TAX_REMINDER_WINDOW_DAYS = 14


def job_tax_quarterly_reminder(
    db: Session, now: Optional[datetime | date] = None
) -> int:
    """Notify each user when a quarterly estimated-tax due date is approaching.

    Idempotent per ``ref`` (``tax_estimate:{user}:{year}:{quarter}``) so a re-fire
    within the window adds no duplicate. Self-gates on ``tax_features_enabled``.
    Returns the number of reminder notifications created across all users. The
    message is factual and non-directive (it never tells the user to pay).
    """
    if not settings.tax_features_enabled:
        return 0

    from .db.rls import set_tenant
    from .logging_context import user_id_var
    from .money import cents_to_dollars
    from .services.notification_service import NotificationService
    from .services.tax.rates import quarterly_due_dates
    from .services.tax.summary_service import TaxSummaryService

    now = now or datetime.now()
    today = now.date() if isinstance(now, datetime) else now

    created = 0
    notif = NotificationService(db)
    for user in _users(db):
        # RLS (C1): bind the tenant per user before the summary engine reads that
        # user's tagged income/deductions; reset in finally.
        set_tenant(db, user.id)
        _uid_token = user_id_var.set(str(user.id))
        try:
            created += _tax_reminder_for_user(
                db, notif, user.id, today, cents_to_dollars,
                quarterly_due_dates, TaxSummaryService,
            )
        except Exception:  # noqa: BLE001 — one user's failure can't abort the rest
            logger.exception("tax_quarterly_reminder failed: user=%s", user.id)
        finally:
            user_id_var.reset(_uid_token)  # load-bearing: no contextvar leak
    db.flush()
    return created


def _tax_reminder_for_user(
    db, notif, user_id, today, cents_to_dollars, quarterly_due_dates,
    TaxSummaryService,
) -> int:
    """Emit any in-window quarterly-tax reminders for one user; returns the count.

    Extracted from ``job_tax_quarterly_reminder`` so the per-user RLS/context
    binding wraps a single call (cleaner reset-in-finally) — behavior unchanged.
    """
    created = 0
    # Look at the due dates for both the current and prior calendar year (Q4 of a
    # tax year falls in January of the next year).
    for tax_year in (today.year, today.year - 1):
        summary = None  # computed lazily only when a due date is in window
        for quarter, iso in quarterly_due_dates(tax_year):
            due = date.fromisoformat(iso)
            delta = (due - today).days
            if 0 <= delta <= _TAX_REMINDER_WINDOW_DAYS:
                if summary is None:
                    summary = TaxSummaryService(db).get_tax_summary(
                        user_id, tax_year
                    )
                income = cents_to_dollars(
                    summary["income_by_source"]["total_income_cents"]
                )
                deductible = cents_to_dollars(
                    sum(
                        d["deductible_cents"]
                        for d in summary["deductions_by_bucket"]
                    )
                )
                row = notif._add_if_new(
                    user_id,
                    type="tax_estimate_reminder",
                    title=f"Estimated-tax due date {due:%b %d} is approaching",
                    message=(
                        f"Quarterly estimated-tax due date {due:%b %d} is "
                        f"approaching. Your tagged YTD business income is "
                        f"${income:,.2f}, deductions ${deductible:,.2f}. "
                        "Estimate for organization only — consult a tax "
                        "professional. You can pay at irs.gov/payments."
                    ),
                    ref=f"tax_estimate:{user_id}:{tax_year}:{quarter}",
                )
                if row is not None:
                    created += 1
    return created


# ---------------------------------------------------------------------------
# F3 — the nightly Auditor. Composes the whole detector battery (anomalies,
# budget overruns, F1 overdraft risk, F2 zombie subs / price creep) into one
# deduped/ranked/capped/narrated batch. Same shape as drift/detangle: pure,
# idempotent per ``ref``, self-gated on ``settings.auditor_enabled``. Runs LAST
# (00:50) so plan_drift + detangle have already written today's notices, and so
# it owns the periodic refresh of F2's MerchantLifecycle snapshot.
# ---------------------------------------------------------------------------


def job_auditor(db: Session, now: Optional[datetime | date] = None) -> int:
    """Run the nightly Auditor for every user. Returns total new notifications.

    Pure and idempotent: ``AuditService.run`` dedups every finding by ``ref`` and
    caps the batch, so an overlapping fire or a restart cannot double-notify.
    Self-gates on ``settings.auditor_enabled``.
    """
    if not settings.auditor_enabled:
        return 0

    from .db.rls import set_tenant
    from .logging_context import user_id_var
    from .services.audit_service import AuditService

    now = now or datetime.now()
    today = now.date() if isinstance(now, datetime) else now

    svc = AuditService(db)
    total = 0
    for user in _users(db):
        # RLS (C1): bind the tenant per user before the detector battery reads
        # that user's rows; reset in finally.
        set_tenant(db, user.id)
        _uid_token = user_id_var.set(str(user.id))
        try:
            total += svc.run(user.id, as_of=today)["created"]
        except Exception:  # noqa: BLE001 — one user's failure can't abort the rest
            logger.exception("auditor failed: user=%s", user.id)
        finally:
            user_id_var.reset(_uid_token)  # load-bearing: no contextvar leak
    db.flush()
    return total


# ---------------------------------------------------------------------------
# W4 — Reconciliation→planning feedback loop. Nightly, per-user: aggregate
# AssistedAction follow-through into ONE non-directive memory fact + ≤1
# idempotent ``create_rule`` (allocate) automation offer per repeated verified
# pattern. Same shape as auditor/drift: pure, idempotent per ``ref``, self-gated
# on ``settings.assistant_reflection_enabled``. Propose-only (B2) — no money moves.
#
# RLS (guardrail B1): this job ESTABLISHES TENANT CONTEXT PER USER before reading
# that user's rows — it calls ``set_tenant(db, user.id)`` (binds the Postgres
# ``app.user_id`` GUC, transaction-scoped) AND ``user_id_var.set(...)`` (request-
# logging context) inside the per-user loop. A job that read zero rows because it
# set no tenant context is the exact failure this item must prevent; the Postgres
# test asserts the bound context lets the job actually read the user's rows. The
# ``_users(db)`` enumeration reads the owner ``users`` table (no RLS policy), so
# it is not tenant-filtered. Under the BYPASSRLS scheduler role the set_tenant
# call is a harmless no-op; under a restricted role it is load-bearing.
# ---------------------------------------------------------------------------


def job_action_reflection(
    db: Session, now: Optional[datetime | date] = None
) -> dict:
    """Run the reflection feedback loop for every user. Returns per-user counts.

    Self-gates on ``settings.assistant_reflection_enabled`` (B4 ship-dark): a
    no-op when the flag is off. Idempotent: the fact is upserted under one key and
    each automation offer dedups by stable ``ref`` (``rule_suggest:{kind}:{dest}:
    {period}``), so an overlapping fire or a restart can't double-write.
    """
    if not settings.assistant_reflection_enabled:
        return {"skipped": "flag_off"}

    from .db.rls import set_tenant
    from .logging_context import user_id_var
    from .services import action_reflection

    now = now or datetime.now()
    now_dt = now if isinstance(now, datetime) else datetime(now.year, now.month, now.day)

    facts = 0
    offers = 0
    for user in _users(db):
        # B1: bind the RLS tenant for THIS user before reading their rows.
        set_tenant(db, user.id)
        _uid_token = user_id_var.set(str(user.id))
        try:
            summary = action_reflection.run_for_user(
                db,
                user.id,
                window_days=settings.reflection_window_days,
                min_repeats=settings.reflection_min_repeats,
                now=now_dt,
            )
            facts += 1 if summary["fact_written"] else 0
            offers += summary["offers"]
        except Exception:  # noqa: BLE001 — one user's failure can't abort the rest
            logger.exception("action_reflection failed: user=%s", user.id)
        finally:
            # Don't leak this user's id into the contextvar after the loop — the
            # log filter must fall back to '-' outside a request context.
            user_id_var.reset(_uid_token)
    db.flush()
    return {"facts_written": facts, "offers": offers}


# ---------------------------------------------------------------------------
# W6 — Honest subscription cancellation. Nightly, per-user: over the F2
# MerchantLifecycle snapshot, surface ≤1 idempotent honest cancel OFFER per
# zombie / price-creep subscription, and ABSENCE-verify each open
# subscription_cancel Bridge (verified only after the next expected charge fails
# to appear for a full cadence + grace; expired if it dangles past the cap).
# Propose-only (B2) — the offer never cancels anything, never moves money, NO fee.
# Self-gates on ``settings.subscription_actions_enabled`` (B4 ship-dark).
#
# RLS (guardrail B1): mirrors job_action_reflection EXACTLY — per user it calls
# ``set_tenant(db, user.id)`` AND ``user_id_var.set(...)`` before reading that
# user's rows, with ``user_id_var.reset(...)`` in a ``finally`` so the contextvar
# never leaks into a later iteration/test (the load-bearing reset). ``_users(db)``
# reads the un-policied owner ``users`` table. The Postgres test asserts the bound
# tenant context actually lets the job read the user's lifecycle rows (not zero).
# ---------------------------------------------------------------------------


def job_subscription_actions(
    db: Session, now: Optional[datetime | date] = None
) -> dict:
    """Run the W6 detect→offer + absence-verify pass for every user.

    Self-gates on ``settings.subscription_actions_enabled`` (B4): a no-op when off.
    Idempotent: each offer dedups by ``ref`` (``sub_cancel:{user}:{merchant}:
    {period}``) and each cancel Bridge by its ``verify_ref``, so an overlapping
    fire or a restart can't double-write. Propose-only — no money moves (B2)."""
    if not settings.subscription_actions_enabled:
        return {"skipped": "flag_off"}

    from .db.rls import set_tenant
    from .logging_context import user_id_var
    from .services import subscription_actions

    now = now or datetime.now()
    as_of = now.date() if isinstance(now, datetime) else now

    offers = 0
    verified = 0
    expired = 0
    for user in _users(db):
        # B1: bind the RLS tenant for THIS user before reading their rows.
        set_tenant(db, user.id)
        _uid_token = user_id_var.set(str(user.id))
        try:
            summary = subscription_actions.run_for_user(db, user.id, now=as_of)
            offers += summary["offers"]
            verified += summary["verified"]
            expired += summary["expired"]
        except Exception:  # noqa: BLE001 — one user's failure can't abort the rest
            logger.exception("subscription_actions failed: user=%s", user.id)
        finally:
            # Load-bearing: don't leak this user's id into the contextvar after the
            # loop — without the reset the log filter (and later tests) see a stale
            # tenant. (The exact bug a prior W4 pass hit.)
            user_id_var.reset(_uid_token)
    db.flush()
    return {"offers": offers, "verified": verified, "expired": expired}


# ---------------------------------------------------------------------------
# W7 — Behavioral features (Tier-1, evidence-graded). THREE nightly/boundary jobs,
# each mirroring the W4/W6 RLS shape EXACTLY: per user ``set_tenant(db, user.id)``
# AND ``user_id_var.set(...)`` before reading that user's rows, with
# ``user_id_var.reset(...)`` in a ``finally`` (the load-bearing reset — without it
# the contextvar leaks and ``test_logging_context`` fails). Each self-gates on its
# OWN feature flag (B4 ship-dark) and is idempotent per ``ref``. F4 (soft earmarks)
# is a request-path service, not a job. ``_users(db)`` reads the un-policied owner
# ``users`` table. The forecast veto for F2 lives inside ``behavioral.run_escalation``.
# ---------------------------------------------------------------------------


def _run_behavioral_per_user(db: Session, runner, accumulate) -> dict:
    """Shared per-user driver for the W7 jobs: bind the RLS tenant + logging context
    per user (reset-in-finally, B1), call ``runner(db, user.id, now=...)``, and fold
    each user's summary into a totals dict via ``accumulate``."""
    from .db.rls import set_tenant
    from .logging_context import user_id_var

    totals: dict = {}
    for user in _users(db):
        set_tenant(db, user.id)
        _uid_token = user_id_var.set(str(user.id))
        try:
            accumulate(totals, runner(db, user.id))
        except Exception:  # noqa: BLE001 — one user's failure can't abort the rest
            logger.exception("behavioral job failed: user=%s", user.id)
        finally:
            # Load-bearing: don't leak this user's id into the contextvar after the
            # loop (the exact bug the W4 reset prevents; test_logging_context proves it).
            user_id_var.reset(_uid_token)
    db.flush()
    return totals


def _accumulate_counts(totals: dict, summary: dict) -> None:
    for key, value in summary.items():
        if isinstance(value, int):
            totals[key] = totals.get(key, 0) + value


def job_goal_reminders(db: Session, now: Optional[datetime | date] = None) -> dict:
    """W7 F1: surface goal-named, cadence-capped, mute-respecting reminders for every
    user. Self-gates on ``behavioral_goal_reminders_enabled`` (B4). Idempotent per
    week-stamped ``ref``. Per-user RLS tenant context (B1)."""
    if not settings.behavioral_goal_reminders_enabled:
        return {"skipped": "flag_off"}
    from .services import behavioral

    now = now or datetime.now()
    as_of = now.date() if isinstance(now, datetime) else now
    return _run_behavioral_per_user(
        db, lambda d, uid: behavioral.run_goal_reminders(d, uid, now=as_of),
        _accumulate_counts,
    )


def job_escalation(db: Session, now: Optional[datetime | date] = None) -> dict:
    """W7 F2: bump each opt-in escalating ``allocate`` rule's contribution by its step —
    forecast-VETOED so a bump can never push the user negative. Self-gates on
    ``behavioral_escalation_enabled`` (B4). One bump per rule per month. Per-user RLS
    tenant context (B1) — the Postgres test proves this job reads the user's rules
    under RLS."""
    if not settings.behavioral_escalation_enabled:
        return {"skipped": "flag_off"}
    from .services import behavioral

    now = now or datetime.now()
    as_of = now.date() if isinstance(now, datetime) else now
    return _run_behavioral_per_user(
        db, lambda d, uid: behavioral.run_escalation(d, uid, now=as_of),
        _accumulate_counts,
    )


def job_landmark_reentry(db: Session, now: Optional[datetime | date] = None) -> dict:
    """W7 F6: at a month/year boundary, send ONE gentle re-entry notification to LAPSED
    users only (engaged users skipped; never resets streaks). Self-gates on
    ``behavioral_landmark_enabled`` (B4). Idempotent per ``ref``. Per-user RLS tenant
    context (B1). Intended to fire on the 1st of a month (the scheduler triggers it
    there); a non-boundary fire still no-ops harmlessly via the ref dedup."""
    if not settings.behavioral_landmark_enabled:
        return {"skipped": "flag_off"}
    from .services import behavioral

    now = now or datetime.now()
    as_of = now.date() if isinstance(now, datetime) else now
    return _run_behavioral_per_user(
        db, lambda d, uid: behavioral.run_landmark_reentry(d, uid, now=as_of),
        _accumulate_counts,
    )


# ---------------------------------------------------------------------------
# The scheduled wrappers — own-session, commit, close (no request context).
# ---------------------------------------------------------------------------

_scheduler_session_factory = None


def _scheduler_sessions():
    """Session factory for scheduler jobs. Uses ``settings.scheduler_database_url``
    (e.g. a BYPASSRLS role, so all-users batch jobs aren't tenant-filtered under
    RLS) when set; otherwise reuses the app's ``SessionLocal``. Lazily built and
    cached. See WS2 in docs/MULTI-TENANT-DO-NOW.md."""
    global _scheduler_session_factory
    if _scheduler_session_factory is None:
        from .db.session import SessionLocal

        if settings.scheduler_database_url:
            from sqlalchemy.orm import sessionmaker

            from .db.session import _make_engine

            _scheduler_session_factory = sessionmaker(
                bind=_make_engine(settings.scheduler_database_url),
                autoflush=False,
                autocommit=False,
                future=True,
            )
        else:
            _scheduler_session_factory = SessionLocal
    return _scheduler_session_factory


def _run_in_own_session(fn) -> None:
    """Run a job in its OWN session — there is no request ``get_db`` session under
    the scheduler. Commit on success, roll back + log on failure; a job failure
    must never crash the scheduler thread."""
    db = _scheduler_sessions()()
    try:
        fn(db)
        db.commit()
    except Exception:  # noqa: BLE001 — never let a job kill the scheduler loop
        db.rollback()
        logger.exception("scheduled game job failed")
    finally:
        db.close()


async def _monthly_tick() -> None:
    """Monthly cron: month-close + fade/graduation + that week's rollups."""
    _run_in_own_session(lambda db: run_due_game_jobs(db, datetime.now()))


async def _weekly_tick() -> None:
    """Weekly cron: rollups + fade (no month seal unless it's also the 1st)."""
    _run_in_own_session(lambda db: run_due_game_jobs(db, datetime.now()))


async def _drift_tick() -> None:
    """Daily cron: re-check active plans-of-record for drift. Idempotent per
    ``ref`` so a re-fire within the same month adds no duplicate notification."""
    _run_in_own_session(lambda db: job_check_plan_drift(db, datetime.now()))


async def _detangle_tick() -> None:
    """Daily cron: flag transfer/refund/duplicate pairs. Gated by
    ``detangle_enabled``; idempotent per ``ref`` so a re-fire adds no duplicate."""
    if not settings.detangle_enabled:
        return
    _run_in_own_session(lambda db: job_detangle(db, datetime.now()))


async def _tax_reminder_tick() -> None:
    """Daily cron: quarterly estimated-tax reminders. Gated by
    ``tax_features_enabled`` (the job self-checks too); idempotent per ``ref``."""
    if not settings.tax_features_enabled:
        return
    _run_in_own_session(lambda db: job_tax_quarterly_reminder(db, datetime.now()))


async def _auditor_tick() -> None:
    """Daily cron: the nightly Auditor. Gated by ``auditor_enabled`` (the job
    self-checks too); idempotent per ``ref`` so a re-fire adds no duplicate."""
    if not settings.auditor_enabled:
        return
    _run_in_own_session(lambda db: job_auditor(db, datetime.now()))


async def _reflection_tick() -> None:
    """Daily cron: the W4 reflection feedback loop. Gated by
    ``assistant_reflection_enabled`` (the job self-checks too); per-user RLS
    tenant context (B1) is set inside the job; idempotent per memory key + ``ref``
    so a re-fire adds no duplicate fact or offer."""
    if not settings.assistant_reflection_enabled:
        return
    _run_in_own_session(lambda db: job_action_reflection(db, datetime.now()))


async def _subscription_actions_tick() -> None:
    """Daily cron: the W6 honest-subscription detect→offer + absence-verify pass.
    Gated by ``subscription_actions_enabled`` (the job self-checks too); per-user
    RLS tenant context (B1) is set inside the job; idempotent per ``ref`` +
    ``verify_ref`` so a re-fire adds no duplicate offer or bridge."""
    if not settings.subscription_actions_enabled:
        return
    _run_in_own_session(lambda db: job_subscription_actions(db, datetime.now()))


async def _goal_reminders_tick() -> None:
    """Daily cron: W7 F1 goal-named reminders. Gated by
    ``behavioral_goal_reminders_enabled`` (the job self-checks too); per-user RLS
    tenant context (B1) is set inside the job; cadence-capped + mute-respecting +
    week-stamped ``ref`` so a daily re-fire adds at most one reminder/goal/week."""
    if not settings.behavioral_goal_reminders_enabled:
        return
    _run_in_own_session(lambda db: job_goal_reminders(db, datetime.now()))


async def _escalation_tick() -> None:
    """Monthly cron: W7 F2 Save-More-Tomorrow escalation. Gated by
    ``behavioral_escalation_enabled`` (the job self-checks too); per-user RLS tenant
    context (B1); the FORECAST VETO inside the job skips any bump that would push the
    user negative; one bump per rule per month (``last_escalated_period``)."""
    if not settings.behavioral_escalation_enabled:
        return
    _run_in_own_session(lambda db: job_escalation(db, datetime.now()))


async def _landmark_reentry_tick() -> None:
    """Monthly cron (the 1st): W7 F6 landmark re-entry. Gated by
    ``behavioral_landmark_enabled`` (the job self-checks too); per-user RLS tenant
    context (B1); LAPSED users only (engaged skipped); never touches the streak
    machine; idempotent per ``ref``."""
    if not settings.behavioral_landmark_enabled:
        return
    _run_in_own_session(lambda db: job_landmark_reentry(db, datetime.now()))


# ---------------------------------------------------------------------------
# APScheduler wiring
# ---------------------------------------------------------------------------

def build_scheduler():
    """Build the ``AsyncIOScheduler`` with declarative cron triggers. Importing
    apscheduler lazily so the module imports cleanly even where the optional
    dependency is absent (the scheduler simply won't be built)."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = AsyncIOScheduler()
    # Month-close + fade + graduation: just after midnight on the 1st.
    scheduler.add_job(
        _monthly_tick,
        CronTrigger(day=1, hour=0, minute=5, timezone="UTC"),
        id="game_monthly",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    # Weekly rollups (the unattended path; ``weekly_reveal`` is the request
    # path): early Monday.
    scheduler.add_job(
        _weekly_tick,
        CronTrigger(day_of_week="mon", hour=0, minute=10, timezone="UTC"),
        id="game_weekly",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    # Plan-of-record drift (v6 doc 06): a daily re-check of active plans. Gated
    # cadence + active-only scope + ref dedup keep it cheap and double-fire safe.
    scheduler.add_job(
        _drift_tick,
        CronTrigger(hour=0, minute=20, timezone="UTC"),
        id="plan_drift",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    # The Detangler (messy-data ingestion): a daily pass flagging transfer /
    # refund / duplicate pairs. The tick self-gates on ``detangle_enabled``; ref
    # dedup keeps a double-fire harmless.
    scheduler.add_job(
        _detangle_tick,
        CronTrigger(hour=0, minute=30, timezone="UTC"),
        id="detangle",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    # Pillar 3: quarterly estimated-tax reminders. The tick self-gates on
    # ``tax_features_enabled``; ref dedup keeps a daily re-fire within the window
    # harmless (one reminder per user/year/quarter).
    scheduler.add_job(
        _tax_reminder_tick,
        CronTrigger(hour=0, minute=40, timezone="UTC"),
        id="tax_quarterly_reminder",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    # F3: the nightly Auditor. Runs LAST (00:50) so drift + detangle have written
    # today's notices first; the tick self-gates on ``auditor_enabled`` and ref
    # dedup keeps a re-fire harmless.
    scheduler.add_job(
        _auditor_tick,
        CronTrigger(hour=0, minute=50, timezone="UTC"),
        id="auditor",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    # W4: the reflection feedback loop. Runs at 01:00 (after the Auditor at 00:50)
    # so the night's notifications are already written. The tick self-gates on
    # ``assistant_reflection_enabled``; one memory key + per-ref dedup keep a
    # re-fire harmless. Per-user RLS tenant context is set inside the job (B1).
    scheduler.add_job(
        _reflection_tick,
        CronTrigger(hour=1, minute=0, timezone="UTC"),
        id="action_reflection",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    # W6: the honest-subscription detect→offer + absence-verify pass. Runs at 01:10
    # (after reflection at 01:00) so the night's notifications are already written.
    # The tick self-gates on ``subscription_actions_enabled``; per-ref + per-bridge
    # dedup keep a re-fire harmless. Per-user RLS tenant context is set inside the
    # job (B1). Absence-verification is intentionally here (knowable only over time)
    # and NOT in the sync hook (which only matches APPEARING transactions, C6).
    scheduler.add_job(
        _subscription_actions_tick,
        CronTrigger(hour=1, minute=10, timezone="UTC"),
        id="subscription_actions",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    # W7 F1: goal-named reminders. Daily at 01:20 (after the night's other notices).
    # The tick self-gates on ``behavioral_goal_reminders_enabled``; cadence cap + mute
    # + week-stamped ref keep a daily re-fire to ≤1 reminder/goal/week. Per-user RLS.
    scheduler.add_job(
        _goal_reminders_tick,
        CronTrigger(hour=1, minute=20, timezone="UTC"),
        id="goal_reminders",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    # W7 F2: Save-More-Tomorrow escalation. MONTHLY on the 1st at 01:30. The tick
    # self-gates on ``behavioral_escalation_enabled``; the forecast veto inside the job
    # skips any bump that would push the user negative; one bump per rule per month.
    scheduler.add_job(
        _escalation_tick,
        CronTrigger(day=1, hour=1, minute=30, timezone="UTC"),
        id="behavioral_escalation",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    # W7 F6: landmark re-entry. MONTHLY on the 1st at 01:40 (the month/year boundary).
    # The tick self-gates on ``behavioral_landmark_enabled``; LAPSED users only; never
    # resets streaks; idempotent per ref.
    scheduler.add_job(
        _landmark_reentry_tick,
        CronTrigger(day=1, hour=1, minute=40, timezone="UTC"),
        id="behavioral_landmark",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    return scheduler


def start_scheduler():
    """Start the scheduler IFF enabled. Returns the live scheduler, or None when
    disabled (tests) or apscheduler is unavailable. ``main.py``'s lifespan keeps
    the handle so it can shut it down on teardown."""
    if not settings.scheduler_enabled:
        logger.info("game scheduler disabled (scheduler_enabled=false)")
        return None
    if not settings.scheduler_leader:
        # Multi-worker seam: only the elected leader schedules jobs. Until real
        # leader election exists, set scheduler_leader=False on all-but-one worker.
        logger.info("game scheduler skipped on this worker (scheduler_leader=false)")
        return None
    try:
        scheduler = build_scheduler()
        scheduler.start()
    except Exception:  # noqa: BLE001 — a missing optional dep must not block boot
        logger.exception("failed to start game scheduler; continuing without it")
        return None
    logger.warning(
        "game scheduler started (in-process, per-worker). SINGLE-WORKER ONLY: "
        ">1 worker double-fires month-close/rollups (idempotent but doubled work)."
    )
    # C1 belt-and-suspenders: with RLS on but no dedicated scheduler session, the
    # batch jobs run on the restricted request-engine role. Each job now binds the
    # tenant per user (so it still works), but a BYPASSRLS scheduler_database_url
    # is the intended seam for all-users maintenance — warn loudly if it's missing.
    if settings.enable_rls and not settings.scheduler_database_url:
        logger.warning(
            "ENABLE_RLS=true but SCHEDULER_DATABASE_URL is unset: batch jobs run "
            "on the restricted app role and rely on per-user set_tenant. Set a "
            "BYPASSRLS SCHEDULER_DATABASE_URL for all-users maintenance jobs."
        )
    return scheduler


def shutdown_scheduler(scheduler) -> None:
    """Stop the scheduler on lifespan teardown. ``wait=False`` so shutdown
    doesn't block on an in-flight job."""
    if scheduler is None:
        return
    try:
        scheduler.shutdown(wait=False)
    except Exception:  # noqa: BLE001
        logger.exception("error shutting down game scheduler")
