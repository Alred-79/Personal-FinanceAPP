"""MCP read tools and resources exposed over the MCP surface.

Each tool/resource:
1. Calls ``get_principal()`` to identify the requesting user (set by MCPAuthMiddleware).
2. Calls ``policy.require(principal, scope)`` — raises ``PolicyError`` on denial.
3. Mints a short-lived capability token with ``policy.issue_capability``.
4. Delegates to ``vault.read`` which enforces the DB read boundary.

``user_id`` always comes from the Principal, never a tool argument.
Tool errors are returned as MCP error results (``isError: true``) — never raw
tracebacks.
"""

from server.src.mcp import actions, policy, vault
from server.src.mcp.server import get_principal, mcp


def _call(scope: str, resource: str, **params):
    """Shared flow: require scope → mint capability → read vault."""
    principal = get_principal()
    policy.require(principal, scope)
    cap = policy.issue_capability(principal, [scope])
    return vault.read(cap, resource, **params)


# Granular scopes the context resource composes from.  The capability minted for
# `budget://context` carries the intersection of these with the principal's scopes,
# so the vault returns only the sections the key is actually allowed to see.
_CONTEXT_SECTION_SCOPES = frozenset(
    {"read:accounts", "read:budgets", "read:goals"}
)


def _call_context():
    """Compose-by-scope flow for `budget://context`.

    Requires `read:context` to use the resource at all, then mints a capability
    carrying `read:context` plus whichever section scopes the principal holds.
    `issue_capability` rejects any scope not on the principal, so this can never
    escalate.
    """
    principal = get_principal()
    policy.require(principal, "read:context")
    granted = sorted(
        {"read:context"} | (set(principal.scopes) & _CONTEXT_SECTION_SCOPES)
    )
    cap = policy.issue_capability(principal, granted)
    return vault.read(cap, "context")


# ---------------------------------------------------------------------------
# Account tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_accounts() -> list[dict]:
    """Return all accounts belonging to the authenticated user."""
    return _call("read:accounts", "accounts")


# ---------------------------------------------------------------------------
# Transaction tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_transactions_by_date_range(
    start: str, end: str, limit: int = 200, offset: int = 0
) -> dict:
    """Return a page of transactions between start and end (YYYY-MM-DD).

    Results are ordered newest-first and bounded by ``limit`` (default 200, max 500).
    The response is ``{"items": [...], "has_more": bool, "next_offset": int | None}``;
    pass ``next_offset`` back as ``offset`` to fetch the next page.
    """
    return _call(
        "read:transactions", "tx_by_date",
        start=start, end=end, limit=limit, offset=offset,
    )


@mcp.tool()
def get_transactions_by_category(
    category: str, limit: int = 200, offset: int = 0
) -> dict:
    """Return a page of transactions in the given category.

    The category is matched case-insensitively against the app's canonical
    taxonomy (call ``get_categories`` to discover valid values). Paginated like
    ``get_transactions_by_date_range``.
    """
    return _call(
        "read:transactions", "tx_by_category",
        category=category, limit=limit, offset=offset,
    )


@mcp.tool()
def get_transactions_per_account(
    account_id: int, limit: int = 200, offset: int = 0
) -> dict:
    """Return a page of transactions for an account owned by the authenticated user.

    Paginated like ``get_transactions_by_date_range``.
    """
    return _call(
        "read:transactions", "tx_per_account",
        account_id=account_id, limit=limit, offset=offset,
    )


@mcp.tool()
def get_categories() -> dict:
    """Return valid transaction categories for the authenticated user.

    ``{"canonical": [...], "present": [...]}`` — the app's canonical taxonomy plus
    the categories actually used across the user's transactions. Use these as input
    to ``get_transactions_by_category``.
    """
    return _call("read:transactions", "categories")


# ---------------------------------------------------------------------------
# Goal tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_goals() -> list[dict]:
    """Return all savings goals for the authenticated user."""
    return _call("read:goals", "goals")


# ---------------------------------------------------------------------------
# Budget tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_budgets() -> list[dict]:
    """Return budget envelopes and spending status for the authenticated user."""
    return _call("read:budgets", "budgets")


@mcp.tool()
def get_spend_summary() -> dict:
    """Return a spending summary for the authenticated user."""
    return _call("read:budgets", "spend_summary")


# ---------------------------------------------------------------------------
# Analytical tools (Tier-1 surface expansion)
# ---------------------------------------------------------------------------

@mcp.tool()
def get_forecast(days: int = 30) -> dict:
    """Project the authenticated user's cash balance forward ``days`` days.

    Burn-aware: drains an estimated daily discretionary spend on top of scheduled
    income/expenses, so the trough answers "will I dip below zero?" honestly. The
    result carries an ``overdraft_probability`` and a low/median/high
    ``lowest_balance.band`` from a residual-bootstrap simulation, plus the
    ``method`` / ``assumptions`` / ``caveats`` that describe how it was computed.
    """
    return _call("read:forecast", "forecast", days=days)


@mcp.tool()
def get_net_worth() -> dict:
    """Return the authenticated user's net worth: live total plus snapshot trend.

    ``current`` is the live sum of every account balance; ``series`` is the
    previously-recorded daily snapshot history (oldest first). The read path never
    records a new snapshot, so today's point may be absent until the app records it.
    """
    return _call("read:networth", "net_worth")


@mcp.tool()
def get_subscriptions() -> list[dict]:
    """Return recurring charges detected across the authenticated user's transactions.

    Each entry describes a likely subscription (merchant, amount, cadence, and the
    most recent charge) inferred from repeated same-amount transactions.
    """
    return _call("read:subscriptions", "subscriptions")


@mcp.tool()
def run_what_if(overlay: dict) -> dict:
    """Evaluate a hypothetical against the authenticated user's real finances.

    ``overlay`` describes the change to model and may contain any of:
      * ``added_recurring``: new recurring streams — list of
        ``{title, amount_cents, recurrence, kind, category?, anchor_date?}``
        (``kind`` is "income" or "expense"; ``recurrence`` e.g. "monthly").
      * ``discrete_flows``: one-off events — list of
        ``{date, amount_cents, kind, title?, category?}``.
      * ``excluded_source_ids``: existing streams to remove — list of
        ``[kind, source_id]`` pairs.
      * ``overridden_recurring``: tweaks to existing streams — list of
        ``{source_id, kind, amount_cents?, recurrence?}``.
      * ``goal_mutations``: goal changes — list of
        ``{goal_id, amount_cents?, target_date?, progress_cents?, name?}``.
      * ``balance_override_cents``: replace the projection's starting balance.

    Amounts are integer cents. Returns a baseline-vs-scenario diff over a 90-day
    horizon with a ``scenario.delta`` (scenario − baseline) covering ending
    balance, lowest balance, overdraft probability, and days-to-zero. An empty
    overlay (``{}``) diffs to exactly the live baseline. This is read-only — it
    computes a projection and changes nothing.
    """
    return _call("read:scenarios", "what_if", overlay=overlay)


# ---------------------------------------------------------------------------
# Context resource
# ---------------------------------------------------------------------------

@mcp.resource("budget://context")
def context_resource() -> dict:
    """Annotated financial snapshot: every number ships with its method, assumptions, and caveats.

    Composed by scope — only the sections the key is scoped for are populated;
    others come back as ``{"available": False, "required_scope": ...}`` stubs.
    """
    return _call_context()


# ---------------------------------------------------------------------------
# Propose tool (Tier-2 write door) — drafts, never executes
# ---------------------------------------------------------------------------

@mcp.tool()
def propose_action(
    kind: str,
    amount: float,
    rationale: str,
    source_ref: str | None = None,
    dest_ref: str | None = None,
    how: dict | None = None,
) -> dict:
    """Draft a real-world money action for the user to review — never moves money.

    This creates an *Assisted-Action Bridge*: the app computes the exact action
    (e.g. "move $340 from Checking to Savings") and surfaces it for the human to
    execute **in-app with one tap**. This tool only drafts the proposal — it does
    NOT transfer, pay, or execute anything, and the user can dismiss it.

    Requires the ``propose:actions`` scope and is disabled by default
    (``mcp_propose_enabled``); when off it returns an error.

    Args:
      kind: one of ``transfer``, ``bill_payment``, ``goal_funding``,
        ``tax_payment``, ``debt_payment``, ``subscription_cancel``.
      amount: dollars (positive).
      rationale: the factual "why" (e.g. "$340 short of this month's target").
        It is screened so it stays factual, never advice or pressure.
      source_ref / dest_ref: optional account/destination hints for the human.
      how: optional structured steps/links (e.g. a provider cancel URL).

    Returns the created Bridge (id, kind, amount, status="proposed", …).
    """
    principal = get_principal()
    policy.require(principal, "propose:actions")
    cap = policy.issue_capability(principal, ["propose:actions"])
    return actions.propose(
        cap,
        kind=kind,
        amount=amount,
        rationale=rationale,
        source_ref=source_ref,
        dest_ref=dest_ref,
        how=how,
    )
