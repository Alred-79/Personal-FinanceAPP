"""MCP Vault — the only DB read path from the MCP side.

Capability token → scope check → read-only session → data layer → redact → audit.

This is the only ``mcp/`` module that imports ``SessionLocal`` directly.  All
other MCP modules must stay DB-free; the import guard in the test suite enforces
this.

SINGLE-WORKER INVARIANT (read before scaling out)
-------------------------------------------------
``read()`` opens a session from the module-level ``SessionLocal`` per call. With
the default SQLite backend this is safe for concurrent READS *within one worker*
(each call gets its own pooled connection), and the session always rolls back so
nothing is ever written. But the app is a single-uvicorn-worker deployment by
design — the game scheduler and the in-memory rate limiters share the same
invariant (see ``settings.py``). SQLite is a single-writer store; running >1
worker (or moving to a connection setup that shares one connection across
threads) is NOT supported here without first moving to a real RDBMS. The
concurrency isolation is covered by
``test_mcp_failure_modes.py::TestConcurrencyIsolation`` against a file-backed
engine (the production shape), not an in-memory shared connection.
"""

import time
from datetime import date, timedelta

from server.src.dates import parse_iso_date
from server.src.db.rls import set_tenant
from server.src.db.session import SessionLocal
from server.src.money import cents_to_dollars
from server.src.settings import settings
from server.src.mcp.annotations import (
    FORECAST_ASSUMPTIONS,
    FORECAST_CAVEATS,
    FORECAST_METHOD,
    NETWORTH_ASSUMPTIONS,
    NETWORTH_METHOD,
    SPENDABLE_ASSUMPTIONS,
    SPENDABLE_CAVEATS,
    SPENDABLE_METHOD,
    SPENDABLE_PERIOD,
)
from server.src.mcp.audit import record as audit_record
from server.src.mcp.context import ContextBuilder
from server.src.mcp.policy import verify_capability
from server.src.services.budget_service import BudgetService
from server.src.services.forecast_service import ForecastService
from server.src.services.networth_service import NetWorthService
from server.src.services.scenario_overlay import (
    SCHEMA_VERSION as SCENARIO_SCHEMA_VERSION,
    overlay_from_json,
)
from server.src.services.scenario_service import ScenarioService
from server.src.services.subscription_service import SubscriptionService
from server.src.services.read_queries import (
    DEFAULT_TX_LIMIT,
    query_accounts,
    query_categories,
    query_goals,
    query_networth_series,
    query_spend_summary,
    query_transactions_by_category,
    query_transactions_by_date_range,
    query_transactions_per_account,
)


def _parse_iso_date(value: str, field: str) -> str:
    """Validate *value* is a YYYY-MM-DD date, returning it unchanged.

    Raises ``VaultError`` with a clear message on a malformed date so a caller can
    tell bad input from a genuine no-results empty page.
    """
    if parse_iso_date(value) is None:
        raise VaultError(
            f"'{field}' must be a valid date in YYYY-MM-DD format (got {value!r})."
        )
    return value


def _pagination(params: dict) -> tuple[int, int]:
    """Extract and validate optional ``limit`` / ``offset`` pagination params."""
    limit = params.get("limit", DEFAULT_TX_LIMIT)
    offset = params.get("offset", 0)
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise VaultError("'limit' must be an integer.")
    if not isinstance(offset, int) or isinstance(offset, bool):
        raise VaultError("'offset' must be an integer.")
    if offset < 0:
        raise VaultError("'offset' must be zero or positive.")
    return limit, offset


class VaultError(Exception):
    """Raised for invalid tokens, unknown resources, or data-layer failures.

    Callers map this to a clean MCP/HTTP error — never a 500.
    """


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

def _drop(row: dict, *keys: str) -> dict:
    return {k: v for k, v in row.items() if k not in keys}


def _redact(rows: list[dict], *drop_keys: str) -> list[dict]:
    """Strip *drop_keys* from every row before it leaves the vault."""
    return [_drop(r, *drop_keys) for r in rows]


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def _dispatch(db, uid: int, resource: str, params: dict, scopes: frozenset[str]) -> object:
    """Route *resource* to the data layer, always scoped to *uid*."""
    if resource == "ping":
        return {"user_id": uid}

    if resource == "context":
        # Compose-by-scope: the snapshot includes only the sections whose granular
        # scope is present in the capability token.
        return ContextBuilder(db).build(uid, scopes=scopes)

    if resource == "accounts":
        # Keep id (needed as account_id for tx_per_account follow-up); drop user_id.
        return _redact(query_accounts(db, uid), "user_id")

    if resource == "tx_by_date":
        start = params.get("start")
        end = params.get("end")
        if not isinstance(start, str) or not isinstance(end, str):
            raise VaultError(
                "tx_by_date requires string params 'start' and 'end' (YYYY-MM-DD)."
            )
        start = _parse_iso_date(start, "start")
        end = _parse_iso_date(end, "end")
        if start > end:
            raise VaultError(
                f"'start' ({start}) must not be after 'end' ({end})."
            )
        limit, offset = _pagination(params)
        # Transaction items carry no user_id, so no redaction is needed.
        return query_transactions_by_date_range(db, uid, start, end, limit, offset)

    if resource == "tx_by_category":
        category = params.get("category")
        if not isinstance(category, str):
            raise VaultError("tx_by_category requires a string 'category' param.")
        limit, offset = _pagination(params)
        return query_transactions_by_category(db, uid, category, limit, offset)

    if resource == "categories":
        return query_categories(db, uid)

    if resource == "tx_per_account":
        account_id = params.get("account_id")
        if not isinstance(account_id, int) or isinstance(account_id, bool):
            raise VaultError("tx_per_account requires an integer 'account_id' param.")
        limit, offset = _pagination(params)
        page = query_transactions_per_account(db, uid, account_id, limit, offset)
        if page is None:
            raise VaultError("Account not found or access denied.")
        return page

    if resource == "goals":
        return _redact(query_goals(db, uid), "user_id")

    if resource == "budgets":
        # Drop internal id; category + amounts are what the agent needs.
        return _redact(BudgetService(db).summarize(uid), "id", "user_id")

    if resource == "spend_summary":
        summary = _drop(query_spend_summary(db, uid), "user_id")
        # Annotate the easily-misread weekly allotment so consumers get the same
        # method / period / caveats as the budget://context resource.
        summary["method"] = SPENDABLE_METHOD
        summary["period"] = SPENDABLE_PERIOD
        summary["assumptions"] = SPENDABLE_ASSUMPTIONS
        summary["caveats"] = SPENDABLE_CAVEATS
        return summary

    if resource == "forecast":
        return _forecast(db, uid, params)

    if resource == "net_worth":
        current = cents_to_dollars(NetWorthService(db).current_total_cents(uid))
        return {
            "current": current,
            "currency": "USD",
            "series": query_networth_series(db, uid),
            "method": NETWORTH_METHOD,
            "assumptions": NETWORTH_ASSUMPTIONS,
        }

    if resource == "subscriptions":
        return SubscriptionService(db).list_subscriptions(uid)

    if resource == "what_if":
        return _what_if(db, uid, params)

    raise VaultError(f"Unknown resource: '{resource}'.")


def _forecast(db, uid: int, params: dict) -> dict:
    """Annotated burn-aware cashflow projection for the get_forecast tool."""
    days = params.get("days", settings.mcp_forecast_default_days)
    if not isinstance(days, int) or isinstance(days, bool):
        raise VaultError("'days' must be an integer number of days.")
    if days <= 0:
        raise VaultError("'days' must be a positive number of days.")
    today = date.today()
    raw = ForecastService(db).forecast(
        uid, today, today + timedelta(days=days), include_burn=True
    )
    return {
        "horizon": {
            "start": raw["horizon_start"],
            "end": raw["horizon_end"],
            "days": days,
        },
        "starting_balance": raw["starting_balance"],
        "ending_balance": raw["ending_balance"],
        "lowest_balance": {
            "value": raw["lowest_balance"],
            "date": raw["lowest_date"],
            "band": raw["trough_band"],
        },
        "will_go_negative": raw["will_go_negative"],
        "overdraft_probability": raw["overdraft_probability"],
        "daily_discretionary_burn": raw["daily_discretionary_burn"],
        "method": FORECAST_METHOD,
        "assumptions": FORECAST_ASSUMPTIONS,
        "caveats": FORECAST_CAVEATS,
    }


def _what_if(db, uid: int, params: dict) -> dict:
    """Baseline-vs-scenario diff from an agent-supplied overlay spec.

    The agent passes only the meaningful overlay keys (added_recurring,
    discrete_flows, goal_mutations, balance_override_cents, …); the internal
    ``schema_version`` is injected here so the tool surface stays clean. ``{}``
    means the EMPTY overlay, which diffs to exactly the live baseline. Any
    malformed spec becomes a clean VaultError, never a 500.
    """
    overlay = params.get("overlay")
    if not isinstance(overlay, dict):
        raise VaultError("what_if requires an 'overlay' object.")
    spec = dict(overlay)
    spec.setdefault("schema_version", SCENARIO_SCHEMA_VERSION)
    try:
        parsed = overlay_from_json(spec)
    except VaultError:
        raise
    except Exception as exc:  # malformed overlay → clean error
        raise VaultError(f"Invalid overlay spec: {exc}") from exc
    return ScenarioService(db).evaluate(uid, parsed)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def read(capability_token: str, resource: str, **params) -> object:
    """Execute a read request through the vault.

    Steps:
    1. Verify the capability token — raises ``VaultError`` on failure.
    2. Open a read-only session (never commits; always rolled back).
    3. Dispatch by *resource* to the data layer, scoped to ``claims.uid``.
    4. Redact the result.
    5. Record an audit entry with decision and latency.

    Returns the redacted payload on success. Raises ``VaultError`` on any
    failure so callers always get a clean error, never a raw traceback.
    """
    t0 = time.monotonic()

    # Step 1 — verify capability
    try:
        claims = verify_capability(capability_token)
    except Exception as exc:
        audit_record(
            user_id=0,
            key_id=0,
            resource=resource,
            params=params or None,
            decision="deny:invalid_token",
            latency_ms=(time.monotonic() - t0) * 1000,
        )
        raise VaultError(f"Invalid capability token: {exc}") from exc

    uid: int = int(claims["uid"])
    key_id: int = int(claims.get("kid", 0))
    scopes: frozenset[str] = frozenset(claims.get("scopes", []))

    # Step 2 — read-only session
    db = SessionLocal()
    # WS2: bind the RLS tenant to the authenticated key's user (uid is authoritative
    # from the verified capability claims). The finally-block rollback ends this
    # transaction, so the SET LOCAL cannot leak to the next pooled use.
    if settings.enable_rls:
        set_tenant(db, uid)
    try:
        result = _dispatch(db, uid, resource, params, scopes)
        audit_record(
            user_id=uid,
            key_id=key_id,
            resource=resource,
            params=params or None,
            decision="allow",
            latency_ms=(time.monotonic() - t0) * 1000,
        )
        return result

    except VaultError:
        audit_record(
            user_id=uid,
            key_id=key_id,
            resource=resource,
            params=params or None,
            decision="deny:vault_error",
            latency_ms=(time.monotonic() - t0) * 1000,
        )
        raise

    except Exception as exc:
        audit_record(
            user_id=uid,
            key_id=key_id,
            resource=resource,
            params=params or None,
            decision="deny:data_error",
            latency_ms=(time.monotonic() - t0) * 1000,
        )
        raise VaultError("Data layer error.") from exc

    finally:
        db.rollback()
        db.close()
