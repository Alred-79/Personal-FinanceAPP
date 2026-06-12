"""AI assistant service. Hands LangChain tools a session factory.

The tool classes call ``_get_session()`` to grab a short lived session per
call instead of the old ``BaseDatabridge`` singleton.

Money amounts are stored as integer cents in the DB. This module converts them
to dollar floats wherever the assistant needs values a person can read.
"""

import json
import re as _re
import socket
import secrets
import threading
import ipaddress
import requests
import jwt
from tavily import TavilyClient
from textwrap import dedent
from urllib.parse import urlparse, urljoin
from datetime import date, timedelta, datetime, timezone
from cachetools import TTLCache
from langchain_groq import ChatGroq
from langchain_classic.memory import ConversationBufferWindowMemory
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.tools import BaseTool
from langchain_classic.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from pydantic import BaseModel, Field
from typing import Any, AsyncGenerator, List, Dict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import UserInDB
from ..services.read_queries import (
    query_accounts,
    query_goals,
    query_spend_summary,
    query_transactions_by_category,
    query_transactions_by_date_range,
    query_transactions_per_account,
)
from ..services.transaction_service import TransactionService
from ..services.categorization_service import CategorizationService
from ..settings import settings
from ..db.session import SessionLocal
from ..db.models import (
    Account as AccountORM,
    Expense as ExpenseORM,
    Goal as GoalORM,
    Income as IncomeORM,
    Rule as RuleORM,
    UsedActionToken as UsedActionTokenORM,
)
from ..money import cents_to_dollars, dollars_to_cents


def _get_session() -> Session:
    """Return a new short lived session for tool invocations."""
    return SessionLocal()


def _sse(event: str, data: Any) -> str:
    """Format a Server-Sent Events frame.

    ``data`` is JSON-encoded so token text with newlines or the SSE delimiters
    can't corrupt the stream. The client splits on the blank line between frames
    and JSON-parses each ``data:`` payload.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


class _NoArgs(BaseModel):
    """Schema for tools that take no real input.

    Groq returns ``arguments: null`` for a parameter-less function, which the
    LangChain tool-call parser can't handle. Exposing a single optional,
    ignored field forces a parseable arguments object instead.
    """

    # Accepted and ignored; the tools read nothing from it.
    noop: str | None = Field(default=None, description="Not used. Leave empty.")


class _DateRangeArgs(BaseModel):
    start_date: str = Field(description="Start date, formatted YYYY-MM-DD.")
    end_date: str = Field(description="End date, formatted YYYY-MM-DD.")


class TransactionsByDateRangeTool(BaseTool):
    """Tool for getting transactional data within a date range"""

    user_id: int
    name: str = "get_transactions_by_date_range"
    description: str = (
        "Get the user's transactions (income and expenses) between two dates. "
        f"Today's date is {datetime.now().strftime('%Y-%m-%d')}; use it when "
        "resolving relative dates like 'last month'."
    )
    args_schema: type[BaseModel] | None = _DateRangeArgs

    def _run(self, start_date: str, end_date: str, *args, **kwargs) -> Any:
        with _get_session() as session:
            # Shared read layer is paginated; unwrap the items for the assistant.
            transactions = query_transactions_by_date_range(
                session, self.user_id, start_date, end_date
            )["items"]
        if not transactions:
            return "No transactions found for the date range."
        return transactions


def _get_category_list() -> str:
    """Build a comma separated list of known categories (lazily, at first call)."""
    try:
        with _get_session() as session:
            expense_cats = (
                session.execute(
                    select(ExpenseORM.category).distinct()
                )
                .scalars()
                .all()
            )
            income_cats = (
                session.execute(
                    select(IncomeORM.category).distinct()
                )
                .scalars()
                .all()
            )
            return ", ".join(sorted(set(expense_cats) | set(income_cats)))
    except Exception:
        return "Food, Transport, Entertainment, Work, Other"


class _CategoryArgs(BaseModel):
    category: str = Field(description="Name of the category to retrieve.")


class TransactionsByCategoryTool(BaseTool):
    """Tool for getting transactional data by category"""

    user_id: int
    name: str = "get_transactions_by_category"
    description: str = "Get the user's transactions for a given category."
    args_schema: type[BaseModel] | None = _CategoryArgs

    def model_post_init(self, __context: Any) -> None:
        super().model_post_init(__context)
        cats = _get_category_list()
        self.description = (
            "Get the user's transactions for a given category. "
            f"Known categories: {cats}."
        )

    def _run(self, category: str, *args, **kwargs) -> Any:
        with _get_session() as session:
            transactions = query_transactions_by_category(
                session, self.user_id, category
            )["items"]
        if not transactions:
            return "No transactions found for the category."
        return transactions


class AccountsTool(BaseTool):
    """Tool for getting account data"""

    user_id: int
    name: str = "get_accounts"
    description: str = "Get the user's accounts and their balances."
    args_schema: type[BaseModel] | None = _NoArgs

    def _run(self, *args, **kwargs) -> Any:
        with _get_session() as session:
            accounts = query_accounts(session, self.user_id)
        if not accounts:
            return "This user has no accounts."
        return accounts


class _AccountIdArgs(BaseModel):
    account_id: int = Field(
        description="Numeric account id. Get it first from get_accounts."
    )


class TransactionsPerAccountTool(BaseTool):
    """Tool for getting transactional data per account"""

    user_id: int
    name: str = "get_transactions_per_account"
    description: str = (
        "Get the transactions for a single account. Get the account_id first "
        "from the get_accounts tool."
    )
    args_schema: type[BaseModel] | None = _AccountIdArgs

    def _run(self, account_id: int, *args, **kwargs) -> Any:
        with _get_session() as session:
            page = query_transactions_per_account(
                session, self.user_id, account_id
            )
        if page is None:
            return "No accounts of this ID found for the user."
        transactions = page["items"]
        if not transactions:
            return "No transactions found for this account."
        return transactions


class SpendTool(BaseTool):
    """Tool for getting spend data"""

    user_id: int
    name: str = "get_spend_details"
    description: str = (
        "Get the user's weekly budgeting details: the maximum they can spend "
        "this week (from income and fixed expenses) and what they've spent over "
        "the last week."
    )
    args_schema: type[BaseModel] | None = _NoArgs

    def _run(self, *args, **kwargs) -> Any:
        with _get_session() as session:
            return query_spend_summary(session, self.user_id)


class GoalsTool(BaseTool):
    """Tool for getting user's financial goals"""

    user_id: int
    name: str = "get_goals"
    description: str = (
        "Get the user's financial goals: name, description, target amount, "
        "target date, completion status, and current progress."
    )
    args_schema: type[BaseModel] | None = _NoArgs

    def _run(self, *args, **kwargs) -> Any:
        with _get_session() as session:
            goals = query_goals(session, self.user_id)
        if not goals:
            return "No goals found for this user."
        return goals
    

# ---------------------------------------------------------------------------
# URL validation that's safe against SSRF
# ---------------------------------------------------------------------------
_MAX_RESPONSE_BYTES = 512 * 1024  # 512 KB
_REQUEST_TIMEOUT = 10  # seconds
_MAX_REDIRECTS = 3
_GENERIC_FETCH_ERROR = "Could not fetch the requested URL."
_GENERIC_SEARCH_ERROR = "Could not complete the search request."

# Guards the temporary ``socket.getaddrinfo`` override used to pin a request to
# an IP we already validated (see ``_fetch_and_strip``).  The override mutates the
# shared stdlib ``socket`` module, so concurrent fetches must serialise.
_resolver_lock = threading.Lock()


def _is_blocked_ip(ip: "ipaddress.IPv4Address | ipaddress.IPv6Address") -> bool:
    """True if *ip* is in a range we must never fetch from (SSRF)."""
    return (
        ip.is_private
        or ip.is_reserved
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolve_validated(hostname: str, port: int) -> "tuple[int, str]":
    """Resolve *hostname* and reject if ANY record is a blocked IP.

    Returns ``(address_family, ip_str)`` for the first record, to be **pinned**
    for the actual connection.  Validating every record (not just the one we
    connect to) defends against multi-record rebinding.
    """
    try:
        addr_infos = socket.getaddrinfo(hostname, port)
    except socket.gaierror:
        raise ValueError(_GENERIC_FETCH_ERROR)
    if not addr_infos:
        raise ValueError(_GENERIC_FETCH_ERROR)

    chosen: "tuple[int, str] | None" = None
    for family, _type, _proto, _canon, sockaddr in addr_infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if _is_blocked_ip(ip):
            raise ValueError(_GENERIC_FETCH_ERROR)
        if chosen is None:
            chosen = (int(family), str(sockaddr[0]))
    assert chosen is not None
    return chosen


def _validate_url(url: str) -> str:
    """Validate *url* for safe outbound fetching.

    Raises ``ValueError`` with a generic message if the URL uses a
    disallowed scheme or resolves to a private / loopback / link-local
    address (SSRF protection).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(_GENERIC_FETCH_ERROR)

    hostname = parsed.hostname
    if not hostname:
        raise ValueError(_GENERIC_FETCH_ERROR)

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    _resolve_validated(hostname, port)
    return url


def _read_capped(response) -> str:
    """Read a streamed response body, capping size, and strip to plain text."""
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=8192):
        total += len(chunk)
        if total > _MAX_RESPONSE_BYTES:
            raise ValueError(_GENERIC_FETCH_ERROR)
        chunks.append(chunk)
    raw_html = b"".join(chunks).decode("utf-8", errors="replace")
    # Strip HTML tags down to a text only version.
    text = _re.sub(r"<[^>]+>", "", raw_html)
    # Collapse whitespace.
    text = _re.sub(r"\s+", " ", text).strip()
    return text


def _fetch_and_strip(url: str) -> str:
    """Fetch *url* safely and return plain text.

    SSRF hardening:
    * **Redirects** are followed manually (``allow_redirects=False``) and every
      hop is re-validated, so a public URL cannot 302 to an internal address.
    * **DNS rebinding** is mitigated by resolving + validating the host and
      pinning the connection to that exact IP for the duration of the request,
      so the IP we validate is the IP we connect to.  TLS SNI / cert
      verification still use the original hostname.
    """
    for _hop in range(_MAX_REDIRECTS + 1):
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(_GENERIC_FETCH_ERROR)
        hostname = parsed.hostname
        if not hostname:
            raise ValueError(_GENERIC_FETCH_ERROR)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        family, pinned_ip = _resolve_validated(hostname, port)

        # Pin the connection to the validated IP. urllib3 resolves via the
        # shared stdlib ``socket.getaddrinfo``; override it (under a lock) so
        # the socket connects to ``pinned_ip`` while TLS keeps using *hostname*.
        with _resolver_lock:
            _orig_getaddrinfo = socket.getaddrinfo

            def _pinned_getaddrinfo(host, prt, *args, **kwargs):
                if host == hostname:
                    return [(family, socket.SOCK_STREAM, 6, "", (pinned_ip, prt or port))]
                return _orig_getaddrinfo(host, prt, *args, **kwargs)

            socket.getaddrinfo = _pinned_getaddrinfo  # type: ignore[assignment]
            try:
                response = requests.get(
                    url,
                    timeout=_REQUEST_TIMEOUT,
                    stream=True,
                    allow_redirects=False,
                )
            finally:
                socket.getaddrinfo = _orig_getaddrinfo  # type: ignore[assignment]

        status = getattr(response, "status_code", None)
        if isinstance(status, int) and status in (301, 302, 303, 307, 308):
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise ValueError(_GENERIC_FETCH_ERROR)
            # Resolve relative redirects; the next loop checks the new target again.
            url = urljoin(url, location)
            continue

        return _read_capped(response)

    # Exhausted the redirect budget.
    raise ValueError(_GENERIC_FETCH_ERROR)


class _QueryArgs(BaseModel):
    query: str = Field(description="Search query; keep it general.")


class _UrlArgs(BaseModel):
    url: str = Field(description="Full http(s) URL to fetch.")


class WebSearchTool(BaseTool):
    """Tool for searching the internet and getting websites"""
    name: str = "search_web"
    description: str = (
        "Search the internet and get a list of matching websites. Keep the query "
        "general. Follow up with the open_website tool to read a result."
    )
    args_schema: type[BaseModel] | None = _QueryArgs

    def _run(self, query: str, *args, **kwargs) -> str:
        try:
            client = TavilyClient(api_key=settings.tavily_api_key)
            resp = client.search(query=query, max_results=5)
            results = resp.get("results", [])
            if not results:
                return "No results found for that query."
            lines: list[str] = []
            for i, r in enumerate(results, 1):
                title = r.get("title", "")
                url = r.get("url", "")
                content = r.get("content", "")
                lines.append(f"{i}. {title}\n   URL: {url}\n   {content}")
            return "\n\n".join(lines)
        except Exception:
            return _GENERIC_SEARCH_ERROR
    

class OpenWebsiteTool(BaseTool):
    """Tool for getting the contents of a website based on the URL"""
    name: str = "open_website"
    description: str = "Fetch and return the text contents of a website, given its URL."
    args_schema: type[BaseModel] | None = _UrlArgs

    def _run(self, url: str, *args, **kwargs) -> str:
        try:
            url = _validate_url(url)
            return _fetch_and_strip(url)
        except (ValueError, requests.RequestException):
            return _GENERIC_FETCH_ERROR

class InformationTool(BaseTool):
    """Tool for getting information about the Finance-Tracker application"""
    name: str = "get_information"
    description: str = "Explain how to do things in the Finance-Tracker app. Use it when the user asks how the app works."
    args_schema: type[BaseModel] | None = _NoArgs

    def _run(self, *args, **kwargs) -> str:
        return """
        Finance-Tracker is a financial assistant that helps you manage your finances. 
        It allows you to track your income and expenses, set financial goals, and get insights on your spending habits.
        
        Here are some brief tutorials users may need to know:
        - Overview Page: An overview on recent spending habits and distributions of spending data. 
        - Accounts Page: Displays all accounts a user current has linked/created. Accounts can be created manually or linked via the Connect Bank button in the user's settings dropdown in the top right corner of the webpage.
        - Transactions Page: Displays all transactions a user has made. Can be filtered by name, date, category, amount, etc. Shows three columns for the most recent transactions, past transactions, and future expected transactions.
        - Goals Page: Displays goals a user has set. Will be factored in when determining budget/weekly spending allowance. A user can create a goal by pressing the "Create New Goal" button in the bottom right.
        
        A user can delete a transaction by clicking the trash icon when hovering over a transaction.
        
        A user can connect a bank account by clicking the "Connect Bank" button in the dropdown when they click their name in the top right
        
        New transactions can be added on the Overview or the Transactions page."""

# ---------------------------------------------------------------------------
# Assistant write actions: mutations that need a confirmation step
# ---------------------------------------------------------------------------
#
# Safety model: the LLM never writes. A write "tool" only *proposes* a change
# and mints a short lived, signed token that describes it. The change happens
# only when the user sends that token back to the explicit
# ``/assistant/actions/confirm`` endpoint. Model proposes, user approves, server runs it.

SUPPORTED_ACTIONS = ("add_transaction", "add_goal", "recategorize_transaction")

_ACTION_TOKEN_TYPE = "assistant_action"
_ACTION_TOKEN_TTL = timedelta(minutes=10)


class ActionError(ValueError):
    """A proposed action is malformed or cannot be executed."""


def _coerce_amount(value: Any) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise ActionError("amount must be a number")
    if amount <= 0:
        raise ActionError("amount must be greater than 0")
    return round(amount, 2)


def _coerce_date(value: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        raise ActionError("date must be a YYYY-MM-DD string")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ActionError("date must be in YYYY-MM-DD format")
    return value


def _coerce_int(value: Any, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ActionError(f"{field} must be an integer")


class ActionService:
    """Validate, sign, and run assistant write actions that need confirmation."""

    # One use guard: save the ``jti`` of every confirm token we spend, so a
    # replayed token (a double click, a retry, or reuse across workers) can't
    # duplicate a write. The DB UNIQUE constraint on ``jti`` is the authority,
    # which keeps this tight across processes and hosts, not just one worker.
    @staticmethod
    def reserve_jti(db: Session, user_id: int, jti: str | None) -> bool:
        """Claim *jti* in the current transaction. False if already spent.

        The insert shares the request transaction with ``execute`` (see the
        confirm endpoint): both commit together on success, and both roll back
        together on failure, so a failed action leaves the token reusable.
        """
        if not jti:
            return False
        db.add(UsedActionTokenORM(jti=jti, user_id=user_id))
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return False
        return True

    # ── Validation + human summary ────────────────────────────────────────
    @staticmethod
    def validate(action: str, params: dict) -> tuple[dict, str]:
        """Return ``(normalized_params, human_summary)`` or raise ``ActionError``.

        Performs NO writes and does not touch the database.
        """
        if not isinstance(params, dict):
            raise ActionError("params must be an object")

        if action == "add_transaction":
            ttype = (params.get("type") or "expense").lower()
            if ttype not in ("expense", "income"):
                raise ActionError("type must be 'expense' or 'income'")
            title = (params.get("title") or "").strip()
            if not title:
                raise ActionError("title is required")
            norm = {
                "type": ttype,
                "account_id": _coerce_int(params.get("account_id"), "account_id"),
                "title": title,
                "amount": _coerce_amount(params.get("amount")),
                "date": _coerce_date(params.get("date")),
                "category": (params.get("category") or "").strip(),
            }
            if ttype == "expense":
                norm["recurrence"] = params.get("recurrence") or None
            cat = f" in '{norm['category']}'" if norm["category"] else ""
            summary = (
                f"Add {ttype} '{norm['title']}' of ${norm['amount']:.2f}"
                f"{cat} on {norm['date']}"
            )
            return norm, summary

        if action == "add_goal":
            name = (params.get("name") or "").strip()
            if not name:
                raise ActionError("name is required")
            norm = {
                "name": name,
                "description": (params.get("description") or "").strip(),
                "amount": _coerce_amount(params.get("amount")),
                "date": _coerce_date(params.get("date")),
                "progress": round(float(params.get("progress") or 0), 2),
            }
            summary = (
                f"Add goal '{norm['name']}' targeting ${norm['amount']:.2f} "
                f"by {norm['date']}"
            )
            return norm, summary

        if action == "recategorize_transaction":
            # ``type`` is optional but disambiguates the expense/income id spaces
            # (they share id values). When omitted it's resolved at execute time,
            # which errors if the id is ambiguous rather than guessing.
            ttype = (params.get("type") or "").lower() or None
            if ttype is not None and ttype not in ("expense", "income"):
                raise ActionError("type must be 'expense' or 'income'")
            category = (params.get("category") or "").strip()
            if not category:
                raise ActionError("category is required")
            norm = {
                "type": ttype,
                "transaction_id": _coerce_int(
                    params.get("transaction_id"), "transaction_id"
                ),
                "category": category,
            }
            summary = (
                f"Recategorize {ttype or 'transaction'} #{norm['transaction_id']} "
                f"to '{norm['category']}'"
            )
            return norm, summary

        if action == "create_allocation":
            # v4 package 03: an alert/what-if "fix" — move money into a goal's
            # virtual earmark (Goal.progress). In-app only; never moves real
            # money between banks.
            norm = {
                "goal_id": _coerce_int(params.get("goal_id"), "goal_id"),
                "amount": _coerce_amount(params.get("amount")),
            }
            summary = (
                f"Set aside ${norm['amount']:.2f} toward goal #{norm['goal_id']}"
            )
            return norm, summary

        if action == "whatif_commit":
            # v4 package 03: commit a what-if as a standing allocation rule.
            norm = {
                "goal_id": _coerce_int(params.get("goal_id"), "goal_id"),
                "amount": _coerce_amount(params.get("amount")),
                "name": (params.get("name") or "What-if commitment").strip(),
            }
            summary = (
                f"Make ${norm['amount']:.2f} toward goal #{norm['goal_id']} a "
                f"standing rule"
            )
            return norm, summary

        raise ActionError(f"Unsupported action: {action}")

    # ── Signed pending action tokens ──────────────────────────────────────
    @staticmethod
    def make_token(user_id: int, action: str, params: dict) -> str:
        payload = {
            "uid": int(user_id),
            "typ": _ACTION_TOKEN_TYPE,
            "jti": secrets.token_urlsafe(16),  # one use id (replay guard)
            "action": action,
            "params": params,
            "exp": datetime.now(timezone.utc) + _ACTION_TOKEN_TTL,
        }
        return jwt.encode(
            payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
        )

    @staticmethod
    def decode_token(token: str) -> dict:
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
            )
        except jwt.ExpiredSignatureError:
            raise ActionError("This proposed action has expired; please ask again.")
        except jwt.PyJWTError:
            raise ActionError("Invalid confirmation token.")
        # Reject anything that isn't an action token (e.g. an auth access token),
        # so the two token types can never be substituted for one another.
        if payload.get("typ") != _ACTION_TOKEN_TYPE:
            raise ActionError("Not an action-confirmation token.")
        return payload

    # ── Execution (only ever called from the confirm endpoint) ────────────
    @staticmethod
    def execute(db: Session, user_id: int, action: str, params: dict) -> dict:
        if action == "add_transaction":
            svc = TransactionService(db)
            if params.get("type") == "income":
                result = svc.create(
                    user_id,
                    IncomeORM,
                    1,
                    title=params["title"],
                    amount=params["amount"],
                    tx_date=params["date"],
                    category=params.get("category") or "Income",
                    account_id=params["account_id"],
                )
            else:
                result = svc.create(
                    user_id,
                    ExpenseORM,
                    -1,
                    title=params["title"],
                    amount=params["amount"],
                    tx_date=params["date"],
                    category=params.get("category") or "",
                    account_id=params["account_id"],
                    extra_fields={"recurrence": params.get("recurrence")},
                )
            return result

        if action == "add_goal":
            goal = GoalORM(
                user_id=user_id,
                name=params["name"],
                description=params.get("description") or "",
                amount=dollars_to_cents(params["amount"]),
                date=params["date"],
                completed=0,
                progress=dollars_to_cents(params.get("progress", 0)),
            )
            db.add(goal)
            db.flush()
            return {"message": "Goal created successfully", "goal_id": goal.id}

        if action == "recategorize_transaction":
            tx_id = params["transaction_id"]
            requested = params.get("type")

            def _find(model):
                return db.execute(
                    select(model)
                    .join(AccountORM, model.account_id == AccountORM.id)
                    .where(model.id == tx_id, AccountORM.user_id == user_id)
                ).scalar_one_or_none()

            if requested == "expense":
                row = _find(ExpenseORM)
            elif requested == "income":
                row = _find(IncomeORM)
            else:
                # No type given: resolve across both tables. Expense and income
                # ids overlap, so refuse to guess when both match.
                expense_row = _find(ExpenseORM)
                income_row = _find(IncomeORM)
                if expense_row is not None and income_row is not None:
                    raise ActionError(
                        "Ambiguous transaction id; specify type "
                        "('expense' or 'income')."
                    )
                row = expense_row or income_row
            if row is None:
                raise ActionError("Transaction not found.")
            row.category = params["category"]
            # Make the recategorization "stick" for this merchant.
            CategorizationService(db).learn(
                user_id, row.title, params["category"], source="user"  # type: ignore[arg-type]
            )
            db.flush()
            return {
                "message": "Transaction recategorized",
                "transaction_id": row.id,
                "category": row.category,
            }

        if action == "create_allocation":
            # Move money into the goal's virtual earmark (Goal.progress) — the
            # same write the rule engine's allocate action performs — and record
            # the fix as a game event. No bank money moves.
            from server.src.services.game.events import (
                GameEventDraft,
                record_events,
            )

            goal = db.execute(
                select(GoalORM).where(
                    GoalORM.id == params["goal_id"], GoalORM.user_id == user_id
                )
            ).scalar_one_or_none()
            if goal is None:
                raise ActionError("Goal not found.")
            cents = dollars_to_cents(params["amount"])
            goal.progress = (goal.progress or 0) + cents
            if goal.progress >= goal.amount:
                goal.completed = 1
            db.flush()
            record_events(
                db,
                [
                    GameEventDraft(
                        stream=f"user:{user_id}",
                        type="AlertFixApplied",
                        payload={
                            "fix_kind": "create_allocation",
                            "goal_id": goal.id,
                            "amount_cents": cents,
                        },
                    )
                ],
            )
            return {
                "message": "Allocation created",
                "goal_id": goal.id,
                "progress": cents_to_dollars(goal.progress),
            }

        if action == "whatif_commit":
            # Create a standing allocate Rule targeting the goal, and record the
            # what-if commit. The Rule is the durable commitment; future income
            # the rule engine sees will fund the goal.
            from server.src.services.game.events import (
                GameEventDraft,
                record_events,
            )

            goal = db.execute(
                select(GoalORM).where(
                    GoalORM.id == params["goal_id"], GoalORM.user_id == user_id
                )
            ).scalar_one_or_none()
            if goal is None:
                raise ActionError("Goal not found.")
            rule = RuleORM(
                user_id=user_id,
                name=params["name"],
                enabled=1,
                conditions=json.dumps([{"field": "type", "op": "eq", "value": "income"}]),
                action_type="allocate",
                action_params=json.dumps({"amount": params["amount"]}),
                target_kind="goal",
                target_id=goal.id,
                priority=0,
            )
            db.add(rule)
            db.flush()
            record_events(
                db,
                [
                    GameEventDraft(
                        stream=f"user:{user_id}",
                        type="WhatIfCommitted",
                        payload={
                            "goal_id": goal.id,
                            "amount": params["amount"],
                            "rule_id": rule.id,
                        },
                    )
                ],
            )
            return {"message": "Commitment created", "rule_id": rule.id}

        raise ActionError(f"Unsupported action: {action}")


def _propose_action(action: str, user_id: int, raw: str | dict) -> str:
    """Shared body for the write tools: validate + mint a confirmation token.

    Returns a JSON string for the LLM. Crucially, this never changes anything;
    it only describes what *would* happen and how to confirm it.
    """
    try:
        params = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return "Invalid input. Provide a JSON object with the action parameters."
    try:
        norm, summary = ActionService.validate(action, params)
        token = ActionService.make_token(user_id, action, norm)
    except ActionError as exc:
        return f"Cannot prepare this action: {exc}"
    return json.dumps(
        {
            "status": "needs_confirmation",
            "summary": summary,
            "confirm_token": token,
            "note": (
                "This is NOT done yet. Tell the user exactly what will happen and "
                "ask them to confirm. The change is applied only after they "
                "explicitly confirm it."
            ),
        }
    )


class _AddTransactionArgs(BaseModel):
    account_id: int
    title: str
    amount: float
    date: str = Field(description="Transaction date, formatted YYYY-MM-DD.")
    category: str | None = None
    type: str | None = Field(
        default="expense", description="'expense' or 'income'."
    )
    recurrence: str | None = None


class _AddGoalArgs(BaseModel):
    name: str
    amount: float
    date: str = Field(description="Target date, formatted YYYY-MM-DD.")
    description: str | None = None
    progress: float | None = 0


class _RecategorizeArgs(BaseModel):
    transaction_id: int
    category: str
    type: str | None = Field(
        default=None, description="'expense' or 'income' to disambiguate the id."
    )


class AddTransactionTool(BaseTool):
    """Propose adding a transaction (does not save until confirmed)."""

    user_id: int
    name: str = "add_transaction"
    description: str = (
        "Propose adding a new transaction. This does NOT save anything; it "
        "returns a confirmation request the user must approve."
    )
    args_schema: type[BaseModel] | None = _AddTransactionArgs

    def _run(self, *args, **kwargs) -> str:
        return _propose_action("add_transaction", self.user_id, kwargs)


class AddGoalTool(BaseTool):
    """Propose adding a financial goal (does not save until confirmed)."""

    user_id: int
    name: str = "add_goal"
    description: str = (
        "Propose adding a financial goal. This does NOT save anything; it "
        "returns a confirmation request the user must approve."
    )
    args_schema: type[BaseModel] | None = _AddGoalArgs

    def _run(self, *args, **kwargs) -> str:
        return _propose_action("add_goal", self.user_id, kwargs)


class RecategorizeTransactionTool(BaseTool):
    """Propose changing a transaction's category (does not save until confirmed)."""

    user_id: int
    name: str = "recategorize_transaction"
    description: str = (
        "Propose changing a transaction's category. Get the transaction_id from "
        "get_transactions_by_category. This does NOT save anything; it returns a "
        "confirmation request the user must approve."
    )
    args_schema: type[BaseModel] | None = _RecategorizeArgs

    def _run(self, *args, **kwargs) -> str:
        return _propose_action("recategorize_transaction", self.user_id, kwargs)


class AssistantService:
    def __init__(self):
        self.llm = ChatGroq(
            groq_api_key=settings.groq_api_key,
            model=settings.groq_chat_model,
            streaming=True,
            temperature=settings.assistant_temperature,
        )

        # Initialize the agent
        self.agents: TTLCache[int, AgentExecutor] = TTLCache(
            maxsize=128, ttl=1800,
        )
        self.actions = {
            "get_transactions_by_date_range": "Retrieving transaction data from {start_date} to {end_date}...",
            "get_transactions_by_category": "Retrieving transaction data for {category}...",
            "get_accounts": "Retrieving account data...",
            "get_transactions_per_account": "Retrieving transaction data for {account_name}...",
            "get_spend_details": "Retrieving spend data...",
            "get_goals": "Retrieving goals data...",
            "search_web": "Searching the internet for {query}...",
            "open_website": "Opening website {url}...",
            "get_information": "",
            "add_transaction": "Preparing to add a transaction...",
            "add_goal": "Preparing to add a goal...",
            "recategorize_transaction": "Preparing to recategorize a transaction...",
        }

        # Map tools to their preprocessing functions
        self.preprocessors = {
            "get_transactions_per_account": self._preprocess_account_data,
            # Add more preprocessors here as needed
        }

    def _preprocess_account_data(self, input_data: dict) -> dict:
        """Preprocesses account data by adding account name."""
        if "account_id" in input_data:
            with _get_session() as session:
                account = session.execute(
                    select(AccountORM.name).where(
                        AccountORM.id == input_data["account_id"]
                    )
                ).scalar_one_or_none()
                if account:
                    input_data["account_name"] = account
                else:
                    input_data["account_name"] = f"account {input_data['account_id']}"
        return input_data

    async def chat(self, user: UserInDB, message: str) -> AsyncGenerator[str, None]:
        """
        Process a chat message and stream the response using the agent
        """
        if user.id not in self.agents:
            tools = [
                TransactionsByDateRangeTool(user_id=user.id),
                TransactionsByCategoryTool(user_id=user.id),
                AccountsTool(user_id=user.id),
                TransactionsPerAccountTool(user_id=user.id),
                SpendTool(user_id=user.id),
                GoalsTool(user_id=user.id),
                WebSearchTool(),
                OpenWebsiteTool(),
                InformationTool(),
                AddTransactionTool(user_id=user.id),
                AddGoalTool(user_id=user.id),
                RecategorizeTransactionTool(user_id=user.id),
            ]

            memory = ConversationBufferWindowMemory(
                memory_key="chat_history",
                return_messages=True,
                k=settings.assistant_memory_window,
            )
            system_text = dedent(
                """
                You are a financial assistant helping the user with their personal budgeting and finances. You have access to tools to retrieve transaction and account data.
                In general, unless otherwise specified or the use-case determines otherwise, you should check data from within the last month.

                ALWAYS make an attempt to use the tools to get the data you need. If you cannot use the tools, then inform the user that you cannot answer the question.
                NEVER respond with an ID of data. If you have an ID, find the name the ID corresponds to.

                Some tools change the user's data: add_transaction, add_goal, and recategorize_transaction. These tools do NOT save anything; they only PROPOSE a change and return a confirmation request. When the user asks you to add or change something, call the matching tool, then clearly tell the user exactly what will happen and ask them to confirm. NEVER claim a change was made; it is only applied after the user explicitly confirms it.
                """
            )
            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", system_text),
                    MessagesPlaceholder(variable_name="chat_history"),
                    ("human", "{input}"),
                    MessagesPlaceholder(variable_name="agent_scratchpad"),
                ]
            )
            agent = create_tool_calling_agent(self.llm, tools, prompt)
            self.agents[user.id] = AgentExecutor(
                agent=agent,
                tools=tools,
                memory=memory,
                verbose=True,
            )

        executor = self.agents[user.id]
        try:
            async for event in executor.astream_events(
                {"input": message}, version="v2"
            ):
                kind = event["event"]
                if kind == "on_tool_start":
                    tool_name = event.get("name", "")
                    template = self.actions.get(tool_name, "")
                    if not template:
                        continue
                    raw_input = event["data"].get("input", {})
                    input_data = dict(raw_input) if isinstance(raw_input, dict) else {}
                    if tool_name in self.preprocessors:
                        input_data = self.preprocessors[tool_name](input_data)
                    try:
                        text = template.format(**input_data)
                    except (KeyError, IndexError):
                        text = template
                    yield _sse("tool", {"text": text})
                elif kind == "on_chat_model_stream":
                    chunk = event["data"].get("chunk")
                    content = getattr(chunk, "content", "") if chunk else ""
                    if content:
                        yield _sse("token", content)
            yield _sse("done", {})

        except Exception as e:
            error_msg = str(e).lower()
            if "rate limit" in error_msg:
                wait_time = "a little bit"
                if match := _re.search(r"please try again in (.*?)\.", error_msg):
                    wait_time = match.group(1)
                yield _sse(
                    "token",
                    f"Rate limit has been reached, please try again in {wait_time}s.",
                )
                yield _sse("done", {})
            else:
                raise e

    def get_chat_history(self, user: UserInDB) -> List[Dict[str, str]]:
        """
        Get the conversation history
        """
        history = []
        if user.id in self.agents:
            for message in self.agents[user.id].memory.chat_memory.messages:  # type: ignore[union-attr]
                if isinstance(message, HumanMessage):
                    history.append({"role": "user", "content": message.content})
                elif isinstance(message, AIMessage):
                    history.append({"role": "assistant", "content": message.content})
        return history

    def clear_history(self, user: UserInDB) -> None:
        """
        Clear the conversation history
        """
        if user.id in self.agents:
            self.agents[user.id].memory.clear()  # type: ignore[union-attr]
