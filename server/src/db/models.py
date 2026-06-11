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
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
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


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # stored as cents
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime, server_default=func.current_timestamp())
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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # stored as cents
    date: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    recurrence: Mapped[Optional[str]] = mapped_column(String)
    plaid_transaction_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Plaid's own dedup key
    account_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )

    account = relationship("Account", back_populates="expenses")


class Income(Base):
    __tablename__ = "income"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # stored as cents
    date: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    plaid_transaction_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Plaid's own dedup key
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
