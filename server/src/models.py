"""Pydantic request and response schemas for Finance-Tracker.

These models spell out the API contract. Every money field (``balance``,
``amount``, ``progress``) is a dollar float here. The database keeps money as
whole integer cents, so the routers convert with
``server.src.money.dollars_to_cents`` and ``cents_to_dollars``.

The money contract is split, and the split is deliberate:

* **Financial endpoints** — accounts, expenses, income, goals, budgets,
  ``/forecast``, ``/spend`` — speak **dollar floats** on the wire. Their values
  pass through ``cents_to_dollars`` at the response boundary, and these Pydantic
  models describe them.
* **Game endpoints** — ``/game`` (homestead, expedition, heat, bosses) — speak
  **integer cents** directly and never pass through ``cents_to_dollars``. Their
  payloads are hand-built dicts, not the models here, and name every money field
  with a ``_cents`` suffix. The canonical example is ``homestead.py``'s
  ``projection_cents`` / ``accrual_line_cents``: raw cents on the wire, by design,
  because the game UI does its own ``/ 100`` formatting.

So: if a field is described by a model in this file it is dollars; if it ends in
``_cents`` and comes from a ``/game`` payload it is integer cents. New fields must
follow whichever side of the seam they sit on.
"""

from datetime import date, datetime
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
    recurrence: Optional[str] = Field(default=None, max_length=50)


class Token(BaseModel):
    # The refresh token is intentionally NOT a field here: it travels ONLY in the
    # httpOnly refresh cookie (set via AuthService.set_auth_cookies). Echoing it in
    # the body would make it readable by JavaScript/XSS and defeat the cookie's
    # protection. The access token stays in the body for the SPA Bearer header /
    # Swagger /docs.
    access_token: str
    token_type: str


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
    # v4 package 02: game intensity dial; 'off' keeps the app pure-finance.
    game_mode: str = "off"


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


# ---------------------------------------------------------------------------
# Scenarios (v6) — saved, named, comparable hypotheticals.
#
# Money is dollar floats here at the API boundary (every ``amount`` field uses
# the ``_MONEY`` ceiling); ``ScenarioService`` converts dollars → integer cents
# on the way into ``overlay_json`` and back to dollars on the way out, so no
# float ever reaches storage.
# ---------------------------------------------------------------------------
class RecurringAddIn(BaseModel):
    """A brand-new recurring stream the scenario injects (dollar ``amount``)."""

    title: str = Field(min_length=1, max_length=200)
    amount: float = Field(**_MONEY)
    recurrence: str = Field(min_length=1, max_length=50)
    kind: str = Field(pattern="^(expense|income)$")
    category: str = Field(default="", max_length=100)
    anchor_date: Optional[str] = None


class RecurringOverrideIn(BaseModel):
    """A change to an existing recurring source, keyed by ``(kind, source_id)``."""

    source_id: int
    kind: str = Field(pattern="^(expense|income)$")
    amount: Optional[float] = Field(default=None, **_MONEY)
    recurrence: Optional[str] = Field(default=None, max_length=50)


class DiscreteFlowIn(BaseModel):
    """A one-off dated flow inside the scenario (dollar ``amount``)."""

    date: str
    amount: float = Field(**_MONEY)
    kind: str = Field(pattern="^(expense|income)$")
    title: str = Field(default="", max_length=200)
    category: str = Field(default="", max_length=100)


class GoalMutationIn(BaseModel):
    """A hypothetical change to a savings goal (dollar amounts)."""

    goal_id: int
    amount: Optional[float] = Field(default=None, **_MONEY)
    target_date: Optional[str] = None
    progress: Optional[float] = Field(default=None, **_MONEY)
    name: Optional[str] = Field(default=None, max_length=200)


class ScenarioOverlayIn(BaseModel):
    """The dollar-denominated overlay the client sends; the service converts to
    the cents-only :class:`ScenarioOverlay` before it touches storage."""

    added_recurring: list[RecurringAddIn] = []
    excluded_source_ids: list[tuple[str, int]] = []
    overridden_recurring: list[RecurringOverrideIn] = []
    discrete_flows: list[DiscreteFlowIn] = []
    goal_mutations: list[GoalMutationIn] = []
    balance_override: Optional[float] = Field(default=None, **_MONEY)
    config_overrides: dict = {}


class ScenarioIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    overlay: ScenarioOverlayIn = ScenarioOverlayIn()


class ScenarioOut(BaseModel):
    id: int
    name: str
    overlay: ScenarioOverlayIn
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ScenarioCompareIn(BaseModel):
    scenario_ids: list[int] = Field(min_length=1)
    horizon_days: int = Field(default=90, gt=0, le=3650)

