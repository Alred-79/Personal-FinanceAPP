"""SQLAlchemy ORM models for Finance-Tracker.

These mirror the legacy schema created in
``server/src/databridge/base_databridge.py`` exactly (column names, types,
nullability, defaults). The ONE thing we added on purpose is the foreign key
constraints that the hand written DDL was missing:

    accounts.user_id   -> users.id      (ON DELETE CASCADE)
    goals.user_id      -> users.id      (ON DELETE CASCADE)
    tokens.user_id     -> users.id      (ON DELETE CASCADE)
    expenses.account_id-> accounts.id   (ON DELETE CASCADE)
    income.account_id  -> accounts.id   (ON DELETE CASCADE)

Money columns (``amount`` / ``balance``) are stored as **integer cents**.
Conversion to/from dollar floats happens at the API boundary via
``server.src.money.dollars_to_cents`` / ``cents_to_dollars``.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DDL,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    disabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    spend_warning: Mapped[int] = mapped_column(Integer, default=20)
    savings_percent: Mapped[int] = mapped_column(Integer, default=10)
    # Safe-to-Spend configuration (v1). Each component of the number is
    # config-gated; ints are 0/1 flags (SQLite has no native bool) and the
    # buffer is integer cents like every money column.
    s2s_horizon: Mapped[str] = mapped_column(String, nullable=False, default="paycheck")  # 'paycheck' | 'month' | 'week'
    s2s_include_income: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    s2s_include_goals: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    s2s_buffer: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # stored as cents
    # v4 enabler (see docs/v3.md → "v1/v2 enablers"): nullable, unused by v1
    # logic; unlocks percentile/cohort mechanics later with no migration.
    birth_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # v4 package 02: the game mode is one end-to-end variable. 'off' is the
    # default — the app behaves exactly as v1 until the user opts in.
    game_mode: Mapped[str] = mapped_column(
        String, nullable=False, default="off"
    )  # 'off' | 'ambient' | 'full'
    # v4 package 10: experiment cohort, assigned ONCE at first game activation
    # (stable hash bucket). 'holdout' users get the full Money Spine with the
    # game layer locked off — the evidenced features are never withheld.
    experiment_cohort: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    accounts = relationship(
        "Account", back_populates="user", cascade="all, delete-orphan"
    )
    goals = relationship("Goal", back_populates="user", cascade="all, delete-orphan")
    tokens = relationship("Token", back_populates="user", cascade="all, delete-orphan")
    refresh_tokens = relationship(
        "RefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
    budgets = relationship(
        "Budget", back_populates="user", cascade="all, delete-orphan"
    )
    balance_snapshots = relationship(
        "BalanceSnapshot", back_populates="user", cascade="all, delete-orphan"
    )
    merchant_categories = relationship(
        "MerchantCategory", back_populates="user", cascade="all, delete-orphan"
    )
    notifications = relationship(
        "Notification", back_populates="user", cascade="all, delete-orphan"
    )
    used_action_tokens = relationship(
        "UsedActionToken", back_populates="user", cascade="all, delete-orphan"
    )
    mcp_keys = relationship(
        "MCPKey", back_populates="user", cascade="all, delete-orphan"
    )
    rules = relationship("Rule", back_populates="user", cascade="all, delete-orphan")
    scenarios = relationship(
        "Scenario", back_populates="user", cascade="all, delete-orphan"
    )
    plans_of_record = relationship(
        "PlanOfRecord", back_populates="user", cascade="all, delete-orphan"
    )


class Account(Base):
    __tablename__ = "accounts"
    # One account name per user. Two "Checking" accounts under the same user
    # break the legacy name-based matching still used for pre-Step-08 (manually
    # managed) accounts and confuse the UI account picker.
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_account_user_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # stored as cents
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.current_timestamp())
    # Step 08: the Plaid ``account_id`` this local account mirrors, set at
    # exchange time (one local Account per Plaid account). NULL for a
    # manually-managed account. Routing and the transfer guard key on this id
    # instead of the old shared-name match, so a renamed account keeps syncing
    # and is still correctly classified as Plaid-managed.
    plaid_account_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    user = relationship("User", back_populates="accounts")
    expenses = relationship(
        "Expense", back_populates="account", cascade="all, delete-orphan"
    )
    income = relationship(
        "Income", back_populates="account", cascade="all, delete-orphan"
    )


class Expense(Base):
    __tablename__ = "expenses"
    # Step 08: race-safe Plaid dedup. A PARTIAL unique index (NULLs excluded)
    # so manual rows — where ``plaid_transaction_id`` is NULL — are unaffected,
    # while two concurrent syncs can't both insert the same Plaid txn id. A
    # Plaid transaction id is globally unique per item, so the single-column
    # partial index suffices. SQLite honours ``sqlite_where``; the Alembic
    # migration creates the same partial index on a migrated DB.
    __table_args__ = (
        Index(
            "uq_expense_plaid_txn",
            "plaid_transaction_id",
            unique=True,
            sqlite_where=text("plaid_transaction_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # stored as cents
    date: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    recurrence: Mapped[Optional[str]] = mapped_column(String)
    plaid_transaction_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Plaid's own dedup key
    # v4 packages 05/09: was this purchase worth it? 'yes' | 'no' | NULL (unset).
    worth_it: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )

    account = relationship("Account", back_populates="expenses")


class Income(Base):
    __tablename__ = "income"
    # Step 08: partial unique index mirroring Expense (see that note). NULLs are
    # excluded so manual income rows are unaffected.
    __table_args__ = (
        Index(
            "uq_income_plaid_txn",
            "plaid_transaction_id",
            unique=True,
            sqlite_where=text("plaid_transaction_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # stored as cents
    date: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    recurrence: Mapped[Optional[str]] = mapped_column(String)  # mirrors Expense.recurrence
    plaid_transaction_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Plaid's own dedup key
    # v4 packages 05/09: mirrors Expense.worth_it. 'yes' | 'no' | NULL (unset).
    worth_it: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )

    account = relationship("Account", back_populates="income")


class Token(Base):
    __tablename__ = "tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    key: Mapped[str] = mapped_column(String, nullable=False)
    cursor: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Plaid /transactions/sync cursor

    user = relationship("User", back_populates="tokens")


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # stored as cents
    date: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress: Mapped[int] = mapped_column(Integer, default=0)  # stored as cents

    user = relationship("User", back_populates="goals")


class RefreshToken(Base):
    """Hashed refresh tokens with expiry and revocation support."""

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0 = active, 1 = revoked
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.current_timestamp())

    user = relationship("User", back_populates="refresh_tokens")


class Budget(Base):
    """One envelope budget per category.

    One row per (user, category). ``monthly_limit`` is stored as **integer
    cents**.  ``rollover`` is a 0/1 int flag (SQLite has no native bool): when
    set, an unspent surplus from the prior month is added to this month's
    effective limit.
    """

    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("user_id", "category", name="uq_budget_user_category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(String, nullable=False)
    monthly_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # stored as cents
    rollover: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0 = off, 1 = on

    user = relationship("User", back_populates="budgets")


class BalanceSnapshot(Base):
    """A net worth snapshot at a point in time.

    One row per (user, date). ``total`` is the sum of all account balances for
    the user on that date, stored as **integer cents**.  Powers the net worth
    trend chart on the Overview page.
    """

    __tablename__ = "balance_snapshots"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_snapshot_user_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    date: Mapped[str] = mapped_column(String, nullable=False)  # ISO YYYY-MM-DD
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # stored as cents

    user = relationship("User", back_populates="balance_snapshots")


class MerchantCategory(Base):
    """Learned merchant → category mapping.

    Powers the automatic categorization "memory": when a user renames a transaction's
    category (or the Groq fallback resolves an unknown merchant), we persist the
    normalized merchant key here so future transactions for the same merchant
    inherit the category.  One row per (user, merchant).

    ``source`` records where the mapping came from: ``"user"`` (a manual rename,
    the most trusted), ``"rule"`` (a built in keyword rule), or ``"llm"`` (the
    Groq fallback).
    """

    __tablename__ = "merchant_categories"
    __table_args__ = (
        UniqueConstraint("user_id", "merchant", name="uq_merchant_user_merchant"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    merchant: Mapped[str] = mapped_column(String, nullable=False)  # normalized merchant key
    category: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False, default="user")
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    user = relationship("User", back_populates="merchant_categories")


class Notification(Base):
    """A notification or nudge shown in the app.

    Generated by ``NotificationService`` for budget overruns and anomalous
    transactions.  ``ref`` is a stable dedup key (e.g.
    ``"budget_overrun:Food:2026-05"``) so re-running generation doesn't spam the
    user with duplicate unread notifications.  ``read`` is a 0/1 int flag
    (SQLite has no native bool).
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String, nullable=False)  # "budget_overrun" | "anomaly"
    title: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(String, nullable=False)
    ref: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)  # dedup key
    read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0 = unread, 1 = read
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.current_timestamp())

    user = relationship("User", back_populates="notifications")


class UsedActionToken(Base):
    """Used up assistant action confirmation tokens.

    Records the ``jti`` of every confirm token that has run, so a replayed token
    (a double click, a retry, or a token reused across workers) can't commit the
    same change twice. It survives across processes and restarts: the unique
    constraint on ``jti`` is the real guard that keeps each token to one use.
    Rows are short lived (tokens expire within minutes) and can be pruned.
    """

    __tablename__ = "used_action_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jti: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.current_timestamp())

    user = relationship("User", back_populates="used_action_tokens")


class Rule(Base):
    """An event-driven automation rule (v1 Layer B).

    ``conditions`` and ``action_params`` are JSON-serialized text. The target is
    deliberately generic — ``target_kind`` (``'goal'`` today) plus ``target_id``
    — so later layers (v4 gamification: ``target_kind='liability'``) need no
    migration. ``enabled`` is a 0/1 int flag.
    """

    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    conditions: Mapped[str] = mapped_column(String, nullable=False, default="[]")  # JSON list of predicates
    action_type: Mapped[str] = mapped_column(String, nullable=False)  # 'notify' | 'allocate' | 'roundup' | 'categorize'
    action_params: Mapped[str] = mapped_column(String, nullable=False, default="{}")  # JSON object
    target_kind: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # 'goal' | (v4: 'liability', …)
    target_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    user = relationship("User", back_populates="rules")
    executions = relationship(
        "RuleExecution", back_populates="rule", cascade="all, delete-orphan"
    )


class RuleExecution(Base):
    """Idempotency log for rule firings.

    The unique ``(rule_id, tx_type, tx_id)`` constraint is what keeps re-imports
    and re-syncs from double-firing a money-moving rule. Storing ``action_type``
    + ``amount_cents`` + ``fired_at`` makes this log double as the v4
    automated-save game-event source — no extra table.
    """

    __tablename__ = "rule_executions"
    __table_args__ = (
        UniqueConstraint("rule_id", "tx_type", "tx_id", name="uq_rule_exec_tx"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("rules.id", ondelete="CASCADE"),
        nullable=False,
    )
    tx_type: Mapped[str] = mapped_column(String, nullable=False)  # 'expense' | 'income'
    tx_id: Mapped[int] = mapped_column(Integer, nullable=False)
    fired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result: Mapped[str] = mapped_column(String, nullable=False, default="ok")

    rule = relationship("Rule", back_populates="executions")


class MCPKey(Base):
    """Scoped, hashed, revocable API key for MCP clients.

    The raw key is returned to the caller exactly once on creation and is
    **never** stored.  Only the SHA-256 ``key_hash`` is persisted so that
    ``resolve`` can look it up by hash.
    """

    __tablename__ = "mcp_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)  # human label, duplicates OK
    key_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String, nullable=False)  # first 12 chars for UI
    scopes: Mapped[str] = mapped_column(String, nullable=False)  # comma-joined
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 0 = active, 1 = revoked
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user = relationship("User", back_populates="mcp_keys")


class LlmUsage(Base):
    """Per-user, per-day LLM cost meter (Step 02 — denial-of-wallet).

    One row per ``(user_id, day)``. ``requests`` is the HARD-cap unit: every
    chat/propose call reserves 1 request via a conditional UPDATE, so the cap is
    enforced even on the streaming path (which surfaces no token count).
    ``tokens`` is ADVISORY/observability only — a best-effort estimate until a
    real streaming usage source is wired (see Step 03); it must NOT be presented
    to the user as a working hard cap while it can record 0.

    ``day`` is a server-local date string produced by a single canonical helper
    (``llm_budget.today_key``) so chat and actions agree on the day boundary.
    No FK to users on purpose: this is a cost ledger, not financial truth, and a
    deleted user's meter rows are harmless and pruneable.
    """

    __tablename__ = "llm_usage"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[str] = mapped_column(String, primary_key=True)  # server-local YYYY-MM-DD
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # advisory
    requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # hard-cap unit


# ---------------------------------------------------------------------------
# v4 game domain (package 01) — the event substrate.
#
# Law 1: game_state = fold(event_stream). These tables are rebuildable
# projections of an append-only log; game code NEVER writes to financial truth
# (accounts/expenses/income/budgets/goals/rules). The single write path is
# ``server.src.services.game.events.record_events`` — nothing else inserts into
# game_events.
# ---------------------------------------------------------------------------


class GameEvent(Base):
    """One append-only event in the game domain.

    ``id`` (rowid) is the global order under a single writer. ``(stream, seq)``
    is the per-stream order, ``seq`` starting at 1. ``payload`` is JSON owned by
    the event ``type``. ``idempotency_key`` is nullable but REQUIRED for any
    event derived from external data (a Plaid txn id, a backfill stream) so a
    replay inserts nothing. ``caused_by`` links a correction/reversal back to the
    event it compensates. The table is append-only — enforced by DB triggers
    (see ``_install_append_only_triggers`` below); ``record_events`` is the only
    code that inserts.
    """

    __tablename__ = "game_events"
    __table_args__ = (
        UniqueConstraint("stream", "seq", name="uq_game_events_stream_seq"),
        UniqueConstraint("idempotency_key", name="uq_game_events_idem"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stream: Mapped[str] = mapped_column(String, nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    v: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload: Mapped[str] = mapped_column(String, nullable=False)  # JSON
    idempotency_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    caused_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("game_events.id"), nullable=True
    )
    created_at: Mapped[str] = mapped_column(String, nullable=False)  # ISO 8601


class ProjectionMeta(Base):
    """Per-projection watermark + rebuild status.

    ``last_event_id`` is the highest ``game_events.id`` this projection has
    folded. ``status`` round-trips ``live`` → ``rebuilding`` → ``live`` during a
    rebuild so readers can tell a half-built projection apart from a live one.
    """

    __tablename__ = "projection_meta"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    last_event_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rebuilt_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="live")


class LlmCache(Base):
    """Cache for LLM flavor output (Law 2: flavor never feeds engine state).

    Keyed by ``sha256(model|template_ver|input_hash|mode)``. The table exists
    from package 01 so the caching seam is in place; package 07 fills it.
    """

    __tablename__ = "llm_cache"

    cache_key: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class CategorySettings(Base):
    """Per-category flags. Categories are plain strings on expenses/income (no
    categories table), so essentials are tracked here keyed by category name.

    ``essential`` marks rent/groceries/etc — categories later packages treat
    leniently. ``user_confirmed`` is 0 for a seeded default, 1 once the user has
    reviewed it.
    """

    __tablename__ = "category_settings"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    essential: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    user_confirmed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Liability(Base):
    """A debt account — one boss in the game layer (v4 package 06).

    This is the ONE financial-truth-adjacent table that game code may write, but
    only via ``liability_service`` — never from a fold handler (folds project,
    the service mutates). The displayed balance derives from posted payments and
    corrections; a manual "reconcile" action writes an adjustment record rather
    than silently editing ``principal_cents``.

    Money columns are integer cents; ``apr_bps`` is basis points (2400 = 24%).
    ``status`` transitions active → defeated_sealed | defeated_banished and a
    defeated boss is permanent (no event resurrects it).
    """

    __tablename__ = "liabilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(
        String, nullable=False, default="credit_card"
    )  # credit_card | loan | bnpl | other
    principal_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    apr_bps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    minimum_payment_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    due_day: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    linked_account_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    linked_plaid_account: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="active"
    )  # active | dormant | defeated_sealed | defeated_banished
    is_active_boss: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # the one concentration boss; 0/1
    ordering_choice: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )  # 'snowball' | 'avalanche' once the one-time override is made
    opened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    defeated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Run(Base):
    """An Expedition run — one month rendered as a 3-act map (v4 §7.2, pkg 08).

    ``map_json`` is the IMMUTABLE draft snapshot: forecast drift after the draft
    must never move nodes (world stability). Mid-run re-derivations (defeat-by-
    date, Grace scaling) write to ``overlay_json``, never the snapshot. Scoring
    on month-seal writes ``score_json`` once.
    """

    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("user_id", "month", name="uq_run_user_month"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    month: Mapped[str] = mapped_column(String, nullable=False)  # 'YYYY-MM'
    map_json: Mapped[str] = mapped_column(String, nullable=False)  # immutable snapshot
    overlay_json: Mapped[str] = mapped_column(String, nullable=False, default="{}")
    modifier_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    started_at: Mapped[str] = mapped_column(String, nullable=False)
    sealed_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    score_json: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class HeatContract(Base):
    """A user-composed constraint contract priced in Heat (v4 §6.2, pkg 09).

    The bridge between game and money spine: priced against the user's OWN
    baselines, and the payoff is real — verified underspend can sweep (opt-in,
    propose→confirm, forecast-vetoed) into the active boss or a goal via the v1
    rule engine. A sweep NEVER executes for more than the verified underspend.
    """

    __tablename__ = "heat_contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(
        String, nullable=False
    )  # cap_vs_baseline | extra_to_boss | zero_dips
    target_param: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # e.g. cap pct
    heat_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    month: Mapped[str] = mapped_column(String, nullable=False)  # 'YYYY-MM'
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="active"
    )  # active | met | unmet | abandoned
    arm: Mapped[str] = mapped_column(
        String, nullable=False, default="cosmetic"
    )  # cosmetic | sweep  (E9 experiment flag)
    sweep_rule_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sweep_paused: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    auto_extended: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )


class CanonFact(Base):
    """The Chronicler's canon — durable facts about the user's saga (v4 §7.4).

    Written ONLY by engine event subscriptions (boss defeated → roster; streak
    best; active modifier; persona prefs). The LLM NEVER writes canon (Law 2:
    flavor never feeds engine state). ``value`` is TEXT/JSON; ``source_event_id``
    links the engine event that produced the fact (NULL for settings-derived).
    """

    __tablename__ = "canon_facts"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_canon_user_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
    source_event_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class LiabilityAdjustment(Base):
    """A manual balance reconciliation on a liability (v4 package 06).

    Drift between the derived balance and reality is corrected by appending an
    adjustment (never by silently editing the liability), so the ledger of how
    the balance got where it is stays auditable.
    """

    __tablename__ = "liability_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    liability_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("liabilities.id", ondelete="CASCADE"), nullable=False
    )
    delta_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )


# Append-only enforcement, mirrored from the Alembic migration so that a DB
# built with ``Base.metadata.create_all`` (the test suite) gets the same guard
# as a migrated DB. SQLite fires these BEFORE any UPDATE/DELETE on game_events
# and aborts the statement.
_NO_UPDATE_TRIGGER = DDL(
    "CREATE TRIGGER IF NOT EXISTS game_events_no_update "
    "BEFORE UPDATE ON game_events "
    "BEGIN SELECT RAISE(ABORT, 'game_events is append-only'); END"
)
_NO_DELETE_TRIGGER = DDL(
    "CREATE TRIGGER IF NOT EXISTS game_events_no_delete "
    "BEFORE DELETE ON game_events "
    "BEGIN SELECT RAISE(ABORT, 'game_events is append-only'); END"
)

event.listen(
    GameEvent.__table__,
    "after_create",
    _NO_UPDATE_TRIGGER.execute_if(dialect="sqlite"),
)
event.listen(
    GameEvent.__table__,
    "after_create",
    _NO_DELETE_TRIGGER.execute_if(dialect="sqlite"),
)

# runs.map_json is an immutable draft snapshot (v4 package 08). Mirror the
# migration's trigger so a create_all DB (the test suite) gets the same guard:
# any UPDATE that changes map_json aborts. overlay_json/score_json stay mutable.
_RUNS_MAP_IMMUTABLE = DDL(
    "CREATE TRIGGER IF NOT EXISTS runs_map_json_immutable "
    "BEFORE UPDATE OF map_json ON runs "
    "FOR EACH ROW WHEN OLD.map_json IS NOT NULL AND NEW.map_json <> OLD.map_json "
    "BEGIN SELECT RAISE(ABORT, 'runs.map_json is an immutable draft snapshot'); END"
)
event.listen(
    Run.__table__,
    "after_create",
    _RUNS_MAP_IMMUTABLE.execute_if(dialect="sqlite"),
)


# ── v4 package 10: campaigns, challenges, experiments ───────────────────────


class Campaign(Base):
    """A quarterly arc instance (v4 §7.3). NON-EXPIRING by construction: the
    status enum is 'active' | 'paused' | 'complete' — there is no 'expired'
    status and no code path that could set one. An unfinished track pauses at
    quarter end and resumes on the user's next activity; its milestones remain
    claimable forever (grants derive from the event log, so catch-up is free).
    """

    __tablename__ = "campaigns"
    __table_args__ = (
        UniqueConstraint("user_id", "quarter", name="uq_campaigns_user_quarter"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    quarter: Mapped[str] = mapped_column(String, nullable=False)  # '2026-Q2'
    arc_key: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="active"
    )  # active | paused | complete — NO 'expired' exists
    started_at: Mapped[str] = mapped_column(String, nullable=False)


class CampaignProgress(Base):
    """One granted campaign milestone. Every milestone derives from real
    events (GREEN weeks, boss phases, sealed months) — never logins/opens."""

    __tablename__ = "campaign_progress"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "milestone_key", name="uq_campaign_progress_milestone"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    milestone_key: Mapped[str] = mapped_column(String, nullable=False)
    granted_at: Mapped[str] = mapped_column(String, nullable=False)
    source_event_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("game_events.id"), nullable=True
    )


class Challenge(Base):
    """A challenge INSTANCE (v4 §8.6); the registry of kinds lives in code.

    Challenges never stake anything, so the StepBet anti-pattern (losers ending
    below baseline) is structurally impossible: the status enum has no state
    that records a loss — failure/abandon is 'soft_landed' (status only).
    """

    __tablename__ = "challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String, nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 | 2 | 3
    category: Mapped[str] = mapped_column(String, nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="active"
    )  # active | met | void | soft_landed
    starts_on: Mapped[str] = mapped_column(String, nullable=False)
    ends_on: Mapped[str] = mapped_column(String, nullable=False)
    params_json: Mapped[str] = mapped_column(String, nullable=False, default="{}")
    verdict_json: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    cosmetic_credit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    suppressed_until: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )


class ExperimentExposure(Base):
    """OBSERVABILITY, not game state (v4 §13). Exposure logging never lands in
    ``game_events`` — the event log is domain history, not analytics."""

    __tablename__ = "experiment_exposures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    flag: Mapped[str] = mapped_column(String, nullable=False)
    arm: Mapped[str] = mapped_column(String, nullable=False)
    surface: Mapped[str] = mapped_column(String, nullable=False, default="")
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class MetricRollup(Base):
    """Weekly per-user metric rollups (observability; v4 §13 metrics jobs)."""

    __tablename__ = "metric_rollups"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "week", "metric", name="uq_metric_rollups_user_week_metric"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    week: Mapped[str] = mapped_column(String, nullable=False)  # ISO Monday
    metric: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cohort: Mapped[str] = mapped_column(String, nullable=False, default="")
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class MetricFade(Base):
    """Per-metric graduation/fade state + the user pin (v4 §9.4 graduation).

    Fade quiets the GAME layer for a stable metric (quests/monsters drop to a
    weekly-summary altitude). It NEVER touches Money Spine alerts, the
    glanceable number, or Grace — those are the product, not the game.
    """

    __tablename__ = "metric_fade"
    __table_args__ = (
        UniqueConstraint("user_id", "metric", name="uq_metric_fade_user_metric"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    metric: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(
        String, nullable=False, default="active"
    )  # active | graduated
    stable_weeks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    regressed_weeks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    graduated_on: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    pin: Mapped[str] = mapped_column(
        String, nullable=False, default="none"
    )  # none | always_active | always_faded


class Scenario(Base):
    """A named, owned ``ScenarioOverlay`` (v6 doc 03).

    The overlay itself lives in ``overlay_json`` as a schema-versioned dict whose
    every money field is integer cents — there are deliberately NO top-level
    money columns, so the cents discipline lives entirely inside the JSON. The
    service converts dollar floats → cents at the API boundary on the way in.
    """

    __tablename__ = "scenarios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    overlay_json: Mapped[str] = mapped_column(String, nullable=False, default="{}")  # ScenarioOverlay as JSON (cents)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )

    user = relationship("User", back_populates="scenarios")
    plans_of_record = relationship(
        "PlanOfRecord", back_populates="scenario", passive_deletes=True
    )


class PlanOfRecord(Base):
    """A committed plan: the rule ids that make it up plus a baseline snapshot to
    drift-check against later (v6 doc 06).

    ``scenario_id`` is SET NULL when the source scenario is deleted, so a
    committed plan is never pinned to a still-existing scenario. Both JSON columns
    hold integer cents where they hold money. ``status`` is ``'active'`` until the
    plan is retired.
    """

    __tablename__ = "plans_of_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    scenario_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("scenarios.id", ondelete="SET NULL"), nullable=True
    )
    rule_ids_json: Mapped[str] = mapped_column(String, nullable=False, default="[]")
    baseline_snapshot_json: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    committed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, server_default=func.current_timestamp()
    )
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    user = relationship("User", back_populates="plans_of_record")
    scenario = relationship("Scenario", back_populates="plans_of_record")
