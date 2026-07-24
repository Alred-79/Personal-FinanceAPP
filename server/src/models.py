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
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Literal, Optional

# Money fields are dollar floats at the API boundary. Reject NaN/Infinity and
# absurd magnitudes (messy/garbage input) while still allowing negative amounts,
# which the app uses for refunds/credits. ~1e12 dollars is a generous ceiling.
_MONEY = dict(allow_inf_nan=False, ge=-1_000_000_000_000, le=1_000_000_000_000)
_POSITIVE_MONEY = dict(allow_inf_nan=False, gt=0, le=1_000_000_000_000)
_NONNEGATIVE_MONEY = dict(allow_inf_nan=False, ge=0, le=1_000_000_000_000)
_RECURRENCE_PATTERN = "^(daily|weekly|bi-weekly|monthly|quarterly|annually)$"


def _valid_iso_date(value: Optional[str]) -> Optional[str]:
    """Return a canonical ISO date string or raise a Pydantic validation error."""
    if value is None:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError("must be a valid ISO date (YYYY-MM-DD)") from exc


class Account(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: str = Field(min_length=1, max_length=100)
    balance: float = Field(**_MONEY)
    subtype: Optional[str] = Field(default=None, max_length=100)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    last_updated: Optional[date] = date.today()

    @field_validator("currency")
    @classmethod
    def _currency_upper(cls, value: str) -> str:
        return value.upper()


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
    # Server-confirmed session identity. The client must not infer this from a
    # username string when deciding which shared-demo safeguards to apply.
    is_demo: bool = False


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
    amount: float = Field(**_POSITIVE_MONEY)
    recurrence: str = Field(pattern=_RECURRENCE_PATTERN)
    kind: str = Field(pattern="^(expense|income)$")
    category: str = Field(default="", max_length=100)
    anchor_date: Optional[str] = None

    _validate_anchor_date = field_validator("anchor_date")(_valid_iso_date)


class RecurringOverrideIn(BaseModel):
    """A change to an existing recurring source, keyed by ``(kind, source_id)``."""

    source_id: int
    kind: str = Field(pattern="^(expense|income)$")
    amount: Optional[float] = Field(default=None, **_POSITIVE_MONEY)
    recurrence: Optional[str] = Field(default=None, pattern=_RECURRENCE_PATTERN)


class DiscreteFlowIn(BaseModel):
    """A one-off dated flow inside the scenario (dollar ``amount``)."""

    date: str
    amount: float = Field(**_POSITIVE_MONEY)
    kind: str = Field(pattern="^(expense|income)$")
    title: str = Field(default="", max_length=200)
    category: str = Field(default="", max_length=100)

    _validate_date = field_validator("date")(_valid_iso_date)


class GoalMutationIn(BaseModel):
    """A hypothetical change to a savings goal (dollar amounts)."""

    goal_id: int
    amount: Optional[float] = Field(default=None, **_POSITIVE_MONEY)
    target_date: Optional[str] = None
    progress: Optional[float] = Field(default=None, **_NONNEGATIVE_MONEY)
    name: Optional[str] = Field(default=None, max_length=200)

    _validate_target_date = field_validator("target_date")(_valid_iso_date)


class ScenarioOverlayIn(BaseModel):
    """The dollar-denominated overlay the client sends; the service converts to
    the cents-only :class:`ScenarioOverlay` before it touches storage."""

    added_recurring: list[RecurringAddIn] = []
    excluded_source_ids: list[tuple[Literal["expense", "income"], int]] = []
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
    horizon_days: int = Field(default=90, gt=0, le=365)


class ScenarioEvaluateIn(BaseModel):
    """Evaluate an ad-hoc (unsaved) overlay — the live builder's run seam (doc 07).

    Unlike ``POST /scenarios/{id}/evaluate/``, this takes the overlay inline so the
    Forecast page can diff an in-progress scenario before it is ever saved.
    """

    overlay: ScenarioOverlayIn = ScenarioOverlayIn()
    name: str = Field(default="Scenario", max_length=200)
    horizon_days: int = Field(default=90, gt=0, le=365)


class PlanComposerPreviewIn(BaseModel):
    """Dollar-denominated request for non-persistable soft-allocation drafts."""

    max_allocation: float = Field(
        ge=0, le=1_000_000_000, allow_inf_nan=False
    )
    additional_buffer_floor: float = Field(
        ge=0, le=1_000_000_000, allow_inf_nan=False
    )
    goal_ids: list[int] = Field(default_factory=list, max_length=100)
    priority: str = Field(default="balanced", pattern="^(buffer|balanced|deadlines)$")
    horizon_days: int = Field(default=90, gt=0, le=365)


# ── Messy-data ingestion (Reconciliation Desk / Import Anything) ─────────────
# These are financial endpoints, so they speak dollar floats on the wire (the
# DB stores integer cents; routers convert at the boundary). ``amount`` is
# signed: positive = money in, negative = money out.


class ImportTextIn(BaseModel):
    """Paste / email body to extract transactions from (the non-file path)."""

    account_id: int
    text: str = Field(min_length=1, max_length=200_000)


class ImportRowOut(BaseModel):
    """One parsed line of an import session, in dollars."""

    id: int
    title: str
    amount: float = Field(**_MONEY)  # signed: +in / -out
    date: str
    category: str
    running_balance: Optional[float] = Field(default=None, **_MONEY)
    status: str  # ok | duplicate | exception | needs_category | transfer_candidate
    reason: Optional[str] = None
    included: bool
    match_ref: Optional[int] = None


class BalanceCheckOut(BaseModel):
    """The reconcile headline — does opening + Σtxns equal closing?"""

    opening: Optional[float] = Field(default=None, **_MONEY)
    closing: Optional[float] = Field(default=None, **_MONEY)
    expected_delta: Optional[float] = Field(default=None, **_MONEY)
    actual_delta: float = Field(**_MONEY)
    discrepancy: Optional[float] = Field(default=None, **_MONEY)
    reconciled: bool
    exception_count: int = Field(ge=0)


class ImportSessionOut(BaseModel):
    """A session plus its rows and balance check — the review payload."""

    id: int
    account_id: int
    source_kind: str  # how it was uploaded: pdf | image | text
    detected_kind: Optional[str] = None  # what it was classified as: statement | feed | receipt | unknown
    status: str  # pending_review | committed | discarded
    statement_period: Optional[str] = None
    balance_check: BalanceCheckOut
    rows: list[ImportRowOut]


class ImportRowPatchIn(BaseModel):
    """A single-row edit during review. All fields optional (partial update)."""

    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    amount: Optional[float] = Field(default=None, **_MONEY)
    date: Optional[str] = None
    category: Optional[str] = Field(default=None, max_length=200)
    included: Optional[bool] = None


# ── Pillar 3 — tax & messy-data layer ────────────────────────────────────────


class TaxTagIn(BaseModel):
    """Manual tax-bucket tag (the non-agent path). The tx_type/tx_id come from
    the URL; this is the body. ``bucket`` is canonicalized server-side and a
    ghost bucket is rejected."""

    bucket: str = Field(min_length=1, max_length=100)
    business_personal: str = Field(default="business")
    deductible_bps: Optional[int] = Field(default=None, ge=0, le=10000)
    note: Optional[str] = Field(default=None, max_length=500)


class TaxTagOut(BaseModel):
    """A tax tag as stored (organization only — never an eligibility claim)."""

    id: int
    tx_type: str
    tx_id: int
    tax_year: int
    bucket: str
    bucket_label: str  # human label, e.g. "Office expense (Sch C line 18)"
    irs_line: str
    business_personal: str
    deductible_bps: int
    source: str
    note: Optional[str] = None


class TaxBucketOut(BaseModel):
    """One entry of the Schedule-C bucket registry, for the UI dropdown."""

    key: str
    label: str
    irs_line: str
    default_deductible_bps: int
    kind: str  # 'expense' | 'income'


class MileageLogIn(BaseModel):
    """A business-mileage trip. Miles is a dollar-free float; stored ×1000 as an
    integer server-side to keep integer-only money discipline."""

    trip_date: str
    miles: float = Field(gt=0, le=1_000_000)
    purpose: Optional[str] = Field(default=None, max_length=500)
    business_personal: str = Field(default="business")


class MileageLogOut(BaseModel):
    id: int
    trip_date: str
    miles: float
    purpose: Optional[str] = None
    business_personal: str
    tax_year: int


class TaxDocumentOut(BaseModel):
    """A reviewed tax form. ``fields`` holds money boxes (DOLLARS at the API
    boundary) + non-PII labels ONLY; the full SSN/EIN is never present —
    ``issuer_tin_last4`` is the only identifier echoed."""

    id: int
    tax_year: int
    form_type: str
    issuer_name: str
    issuer_tin_last4: Optional[str] = None
    fields: dict  # money boxes (dollars) + non-PII labels only
    status: str
    source_kind: str


class TaxDocumentPatchIn(BaseModel):
    """Fix a misread box before confirming. Money values are DOLLARS; the server
    re-validates against the PII scrubber before write."""

    tax_year: Optional[int] = Field(default=None, ge=1900, le=2200)
    issuer_name: Optional[str] = Field(default=None, max_length=200)
    fields: Optional[dict] = None  # partial money-box overrides (dollars)
