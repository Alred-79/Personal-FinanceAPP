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

from server.src.mcp import policy, vault
from server.src.mcp.policy import PolicyError
from server.src.mcp.server import get_principal, mcp
from server.src.mcp.vault import VaultError


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
# Context resource
# ---------------------------------------------------------------------------

@mcp.resource("budget://context")
def context_resource() -> dict:
    """Annotated financial snapshot: every number ships with its method, assumptions, and caveats.

    Composed by scope — only the sections the key is scoped for are populated;
    others come back as ``{"available": False, "required_scope": ...}`` stubs.
    """
    return _call_context()
