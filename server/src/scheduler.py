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
    is keyed on ``seal:{user}:{month}``)."""
    from .services.game.month_close import close_month

    month = _prev_month_str(now)
    sealed: dict[int, dict] = {}
    for user_row in _users(db):
        user = _to_user(user_row)
        try:
            sealed[user.id] = close_month(db, user, month)
        except Exception:  # noqa: BLE001 — one user's failure can't abort the rest
            logger.exception("close_month failed: user=%s month=%s", user.id, month)
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

    faded: dict[int, dict[str, str]] = {}
    grad: dict[int, int] = {}
    fade = FadeService(db)
    for user_row in _users(db):
        user = _to_user(user_row)
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
            grad[user.id] = len(detect_graduation_candidates(db, user.id, as_of=now))
        except Exception:  # noqa: BLE001
            logger.exception("graduation detect failed: user=%s", user.id)
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
    from .services.scenario_service import ScenarioService

    now = now or datetime.now()
    today = now.date() if isinstance(now, datetime) else now

    svc = ScenarioService(db)
    total = 0
    for user in _users(db):
        total += len(svc.check_drift(user.id, as_of=today))
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
    from .services.detangle_service import DetangleService

    svc = DetangleService(db)
    total = 0
    for user in _users(db):
        total += len(svc.run(user.id))
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

    from .money import cents_to_dollars
    from .services.notification_service import NotificationService
    from .services.tax.rates import quarterly_due_dates
    from .services.tax.summary_service import TaxSummaryService

    now = now or datetime.now()
    today = now.date() if isinstance(now, datetime) else now

    created = 0
    notif = NotificationService(db)
    for user in _users(db):
        # Look at the due dates for both the current and prior calendar year (Q4
        # of a tax year falls in January of the next year).
        for tax_year in (today.year, today.year - 1):
            summary = None  # computed lazily only when a due date is in window
            for quarter, iso in quarterly_due_dates(tax_year):
                due = date.fromisoformat(iso)
                delta = (due - today).days
                if 0 <= delta <= _TAX_REMINDER_WINDOW_DAYS:
                    if summary is None:
                        summary = TaxSummaryService(db).get_tax_summary(
                            user.id, tax_year
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
                        user.id,
                        type="tax_estimate_reminder",
                        title=f"Estimated-tax due date {due:%b %d} is approaching",
                        message=(
                            f"Quarterly estimated-tax due date {due:%b %d} is "
                            f"approaching. Your tagged YTD business income is "
                            f"${income:,.2f}, deductions ${deductible:,.2f}. "
                            "Estimate for organization only — consult a tax "
                            "professional. You can pay at irs.gov/payments."
                        ),
                        ref=f"tax_estimate:{user.id}:{tax_year}:{quarter}",
                    )
                    if row is not None:
                        created += 1
    db.flush()
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

    from .services.audit_service import AuditService

    now = now or datetime.now()
    today = now.date() if isinstance(now, datetime) else now

    svc = AuditService(db)
    total = 0
    for user in _users(db):
        try:
            total += svc.run(user.id, as_of=today)["created"]
        except Exception:  # noqa: BLE001 — one user's failure can't abort the rest
            logger.exception("auditor failed: user=%s", user.id)
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
