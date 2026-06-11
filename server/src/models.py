"""Pydantic request and response schemas for Finance-Tracker.

These models spell out the API contract. Every money field (``balance``,
``amount``, ``progress``) is a dollar float here. The database keeps money as
whole integer cents, so the routers convert with
``server.src.money.dollars_to_cents`` and ``cents_to_dollars``.
"""

from datetime import date
from pydantic import BaseModel, EmailStr, Field
from typing import Optional

# Money fields are dollar floats at the API boundary. Reject NaN/Infinity and
# absurd magnitudes (messy/garbage input) while still allowing negative amounts,
# which the app uses for refunds/credits. ~1e12 dollars is a generous ceiling.
_MONEY = dict(allow_inf_nan=False, ge=-1_000_000_000_000, le=1_000_000_000_000)


class Account(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: str = Field(min_length=1, max_length=100)
    balance: float = Field(**_MONEY)
    last_updated: Optional[date] = date.today()


class Transaction(BaseModel):
    account_id: int
    title: str = Field(min_length=1, max_length=200)
    amount: float = Field(**_MONEY)
    date: date
    category: str = Field(default="", max_length=100)


class Expense(Transaction):
    recurrence: Optional[str] = Field(default=None, max_length=50)


class Income(Transaction):
    pass


class Token(BaseModel):
    access_token: str
    token_type: str
    refresh_token: str | None = None  # filled in while we move auth over to cookies


class TokenData(BaseModel):
    username: str | None = None


class NewUser(BaseModel):
    username: str
    email: EmailStr
    full_name: str
    password: str


class User(BaseModel):
    id: int
    username: str
    email: str | None = None
    full_name: str | None = None
    disabled: bool | None = None
    spend_warning: int = 20
    savings_percent: int = 10


class UserInDB(User):
    hashed_password: str


class PublicTokenExchangeRequest(BaseModel):
    name: str
    public_token: str


class PlaidTransactionRequest(BaseModel):
    start_date: str
    end_date: str

class Goal(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    amount: float = Field(gt=0, allow_inf_nan=False, le=1_000_000_000_000)
    date: date
    completed: bool = False
    progress: float = Field(default=0, ge=0, allow_inf_nan=False, le=1_000_000_000_000)


class Budget(BaseModel):
    """One envelope budget for a category. ``monthly_limit`` is in dollars."""

    category: str = Field(min_length=1, max_length=100)
    monthly_limit: float = Field(ge=0, allow_inf_nan=False, le=1_000_000_000_000)
    rollover: bool = False


# ---------------------------------------------------------------------------
# Assistant write actions
# ---------------------------------------------------------------------------
class AssistantActionRequest(BaseModel):
    """A write the user wants to make, either directly or through the assistant."""

    action: str
    params: dict


class AssistantActionProposal(BaseModel):
    """An action that checked out but has not run yet, with the token to commit it."""

    action: str
    params: dict
    summary: str
    token: str


class AssistantActionConfirm(BaseModel):
    """Confirms an action we proposed earlier."""

    token: str


# ---------------------------------------------------------------------------
# Receipt scanning
# ---------------------------------------------------------------------------
class ReceiptLineItem(BaseModel):
    description: Optional[str] = None
    amount: Optional[float] = None


class ReceiptDraft(BaseModel):
    """Fields pulled off a receipt to prefill a transaction form. Nothing is saved yet."""

    merchant: Optional[str] = None
    title: Optional[str] = None
    amount: Optional[float] = None
    date: Optional[str] = None
    category: Optional[str] = None
    line_items: list[ReceiptLineItem] = []

