"""Event-driven rules engine (v1 Layer B).

"On transaction X, do Y." Rules are evaluated when a transaction is created
(the single creation path: ``TransactionService.create`` calls
``run_on_transaction`` after flush). All actions are **virtual** — they write
``Goal.progress`` (an earmark bucket that survives Plaid re-syncs and reduces
Safe-to-Spend) or ``Notification`` rows — never account balances and never real
transfers.

Idempotency: every firing is recorded in ``rule_executions`` with a unique
``(rule_id, tx_type, tx_id)``, so re-imports and re-syncs can't double-fire a
money-moving rule. The log stores ``action_type`` + ``amount_cents`` +
``fired_at``, which doubles as the v4 automated-save game-event source.

The target is generic (``target_kind`` + ``target_id``): v1 ships
``target_kind='goal'``; v4 adds ``'liability'`` with no migration.

Conditions (v1): an all-of list of simple predicates over the new transaction.
No expression language. Supported fields/ops:

    {"field": "category", "op": "eq" | "in",       "value": str | [str]}
    {"field": "amount",   "op": "gt" | "lt",       "value": dollars}
    {"field": "title",    "op": "contains",        "value": str}
    {"field": "account_id","op": "eq",             "value": int}
    {"field": "type",     "op": "eq",              "value": "expense"|"income"}
    {"field": "source_type","op": "eq",            "value": "w2"|"self_employment"|"other"}

``source_type`` (W5) is only present on income transactions; it is absent on
expenses and on income with no classification, so a ``source_type == X`` predicate
fails closed there (the income condition still guards against ever matching an
expense). All money math in integer cents.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.src.db.models import (
    Expense as ExpenseORM,
    Goal as GoalORM,
    Notification as NotificationORM,
    Rule as RuleORM,
    RuleExecution as RuleExecutionORM,
    User as UserORM,
)
from server.src.money import cents_to_dollars, dollars_to_cents
from server.src.services.categorization_service import (
    CategorizationService,
    canonicalize_category,
)

# Pillar 2B — the bounded auto-execute default if a user row carries no explicit
# threshold (older rows pre-migration). $100, the market-canonical HITL default.
DEFAULT_AUTO_EXECUTE_THRESHOLD_CENTS = 10000

log = logging.getLogger(__name__)

ACTION_TYPES = ("notify", "allocate", "roundup", "categorize")
ROUNDUP_STEPS_CENTS = {"1": 100, "5": 500}  # round up to nearest $1 / $5


def _loads(text: str | None, fallback):
    try:
        return json.loads(text) if text else fallback
    except (TypeError, ValueError):
        return fallback


def matches(conditions: list[dict[str, Any]], tx: dict[str, Any]) -> bool:
    """True if *tx* satisfies every predicate (all-of). Empty list ⇒ match all.

    Unknown fields/ops fail closed (no match) so a malformed rule can't fire
    on everything by accident.
    """
    for cond in conditions:
        field = cond.get("field")
        op = cond.get("op")
        value = cond.get("value")
        actual = tx.get(field) if field else None

        if field == "category":
            actual_norm = (actual or "").strip().lower()
            if op == "eq":
                ok = actual_norm == str(value).strip().lower()
            elif op == "in":
                ok = actual_norm in [str(v).strip().lower() for v in (value or [])]
            else:
                ok = False
        elif field == "amount":
            if value is None:
                return False
            try:
                amount = float(actual or 0)
                threshold = float(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return False
            if op == "gt":
                ok = amount > threshold
            elif op == "lt":
                ok = amount < threshold
            else:
                ok = False
        elif field == "title":
            ok = op == "contains" and str(value).lower() in str(actual or "").lower()
        elif field == "account_id":
            ok = op == "eq" and actual == value
        elif field == "type":
            ok = op == "eq" and actual == value
        elif field == "source_type":
            # W5: the income's tax/earnings character ('w2'|'self_employment'|
            # 'other'). Lets a Tax-Reserve allocate rule fire on self-employment
            # income ONLY. Fails closed when the tx carries no source_type (None
            # never equals a concrete value), so it can't match a W-2 paycheck or
            # an expense — both of which omit the field.
            ok = op == "eq" and actual == value
        else:
            ok = False

        if not ok:
            return False
    return True


def roundup_cents(amount_cents: int, step_cents: int) -> int:
    """The change from rounding *amount_cents* up to the nearest *step_cents*.

    An exact multiple yields 0 (nothing to sweep).
    >>> roundup_cents(450, 100)
    50
    >>> roundup_cents(400, 100)
    0
    """
    remainder = amount_cents % step_cents
    return (step_cents - remainder) if remainder else 0


class RuleEngine:
    def __init__(self, db: Session) -> None:
        self.db = db
        # Per-user auto-execute threshold cache (Pillar 2B). One engine instance
        # processes one transaction's rules, but a batch sync re-uses the same
        # instance across many transactions for one user, so cache the lookup.
        self._threshold_cache: dict[int, int] = {}

    # ── evaluation ────────────────────────────────────────────────────────

    def run_on_transaction(
        self,
        user_id: int,
        tx_type: str,
        tx_id: int,
        tx: dict[str, Any],
    ) -> list[RuleExecutionORM]:
        """Evaluate every enabled rule against a newly created transaction.

        *tx* carries dollar floats (the API-boundary shape):
        ``{title, amount, date, category, account_id, type}``.

        Never raises: a rules failure must not break transaction creation.
        """
        executions: list[RuleExecutionORM] = []
        try:
            rules = (
                self.db.execute(
                    select(RuleORM)
                    .where(RuleORM.user_id == user_id, RuleORM.enabled == 1)
                    .order_by(RuleORM.priority.desc(), RuleORM.id.asc())
                )
                .scalars()
                .all()
            )
            for rule in rules:
                try:
                    execution = self._run_rule(rule, tx_type, tx_id, tx)
                except Exception:  # noqa: BLE001 — isolate one bad rule
                    log.exception("Rule %s failed on %s:%s", rule.id, tx_type, tx_id)
                    continue
                if execution is not None:
                    executions.append(execution)
        except Exception:  # noqa: BLE001
            log.exception("Rule engine failed on %s:%s", tx_type, tx_id)
        return executions

    def _already_fired(self, rule_id: int, tx_type: str, tx_id: int) -> bool:
        return (
            self.db.execute(
                select(RuleExecutionORM.id).where(
                    RuleExecutionORM.rule_id == rule_id,
                    RuleExecutionORM.tx_type == tx_type,
                    RuleExecutionORM.tx_id == tx_id,
                )
            ).scalar_one_or_none()
            is not None
        )

    def _run_rule(
        self,
        rule: RuleORM,
        tx_type: str,
        tx_id: int,
        tx: dict[str, Any],
    ) -> Optional[RuleExecutionORM]:
        conditions = _loads(rule.conditions, [])
        if not matches(conditions, tx):
            return None
        if self._already_fired(rule.id, tx_type, tx_id):
            return None

        amount_cents, result = self._execute_action(rule, tx)
        execution = RuleExecutionORM(
            rule_id=rule.id,
            tx_type=tx_type,
            tx_id=tx_id,
            action_type=rule.action_type,
            amount_cents=amount_cents,
            result=result,
        )
        try:
            # SAVEPOINT so losing a race on the unique (rule_id, tx_type,
            # tx_id) rolls back only this insert — never the transaction that
            # created the expense/income row itself.
            with self.db.begin_nested():
                self.db.add(execution)
        except IntegrityError:
            return None
        return execution

    # ── actions ───────────────────────────────────────────────────────────

    def _execute_action(self, rule: RuleORM, tx: dict[str, Any]) -> tuple[int, str]:
        """Run the action; return (amount_cents_moved, result_label)."""
        params = _loads(rule.action_params, {})
        tx_amount_cents = dollars_to_cents(float(tx.get("amount") or 0))

        if rule.action_type == "notify":
            self._notify(rule, params, tx)
            return 0, "ok"

        if rule.action_type == "allocate":
            cents = self._allocation_cents(params, tx_amount_cents)
            return self._fund_target(rule, cents)

        if rule.action_type == "roundup":
            step = ROUNDUP_STEPS_CENTS.get(str(params.get("nearest", "1")), 100)
            cents = roundup_cents(tx_amount_cents, step)
            if cents == 0:
                return 0, "noop"
            return self._fund_target(rule, cents)

        if rule.action_type == "categorize":
            return self._categorize(rule, params, tx)

        return 0, f"unknown_action:{rule.action_type}"

    @staticmethod
    def _allocation_cents(params: dict[str, Any], tx_amount_cents: int) -> int:
        """Fixed $X (``amount``) or percent of the transaction (``pct``)."""
        if params.get("amount") is not None:
            return max(dollars_to_cents(float(params["amount"])), 0)
        if params.get("pct") is not None:
            pct = max(min(float(params["pct"]), 100.0), 0.0)
            return int(tx_amount_cents * pct / 100)
        return 0

    def _auto_execute_threshold_cents(self, user_id: int) -> int:
        """The user's bounded auto-execute threshold in cents (Pillar 2B), cached.

        A firing whose amount is at or below this earmarks silently; above it the
        engine proposes instead (HITL). Missing/NULL (older rows) falls back to
        the $100 default.
        """
        cached = self._threshold_cache.get(user_id)
        if cached is not None:
            return cached
        value = self.db.execute(
            select(UserORM.auto_execute_threshold_cents).where(
                UserORM.id == user_id
            )
        ).scalar_one_or_none()
        threshold = (
            int(value) if value is not None else DEFAULT_AUTO_EXECUTE_THRESHOLD_CENTS
        )
        self._threshold_cache[user_id] = threshold
        return threshold

    def _fund_target(self, rule: RuleORM, cents: int) -> tuple[int, str]:
        """Move *cents* into the rule's virtual target — or PROPOSE it (2B).

        v1: ``target_kind='goal'`` → ``Goal.progress`` (the earmark bucket that
        reduces Safe-to-Spend). The kind switch is where v4 plugs in
        ``'liability'`` with no schema change.

        Pillar 2B (bounded auto-execute): a firing whose ``cents`` exceeds the
        user's auto-execute threshold does NOT mutate ``Goal.progress``. Instead
        the engine mints a one-tap confirm token and a ``Notification`` carrying
        it, and reports ``result="needs_confirmation"`` so the ``RuleExecution``
        row is logged. The ``uq_rule_exec_tx`` row is the dedup key, so re-syncing
        the same transaction does NOT mint a second proposal (the caller's
        ``_already_fired`` short-circuits first). Below-threshold firings are
        unchanged — they earmark silently exactly as before. Either way no REAL
        money ever moves; the threshold only decides silent-earmark vs propose.
        """
        if cents <= 0:
            return 0, "noop"
        if rule.target_kind == "goal" and rule.target_id is not None:
            goal = self.db.execute(
                select(GoalORM).where(
                    GoalORM.id == rule.target_id,
                    GoalORM.user_id == rule.user_id,
                )
            ).scalar_one_or_none()
            if goal is None:
                return 0, "target_missing"
            # Above the threshold → propose instead of silently earmarking.
            if cents > self._auto_execute_threshold_cents(rule.user_id):
                self._propose_funding(rule, goal, cents)
                return cents, "needs_confirmation"
            goal.progress = (goal.progress or 0) + cents
            if goal.progress >= goal.amount:
                goal.completed = 1
            return cents, "ok"
        return 0, f"unsupported_target:{rule.target_kind}"

    def _propose_funding(self, rule: RuleORM, goal: GoalORM, cents: int) -> None:
        """Write a Notification proposing an above-threshold earmark (2B / R7).

        Above the auto-execute threshold the engine never moves money — it asks.
        We persist a durable ``Notification`` with a STABLE ``ref`` (the dedup
        key) describing the exact proposed earmark; the matching one-tap confirm
        token is **re-minted on demand** when the user acts on it (the documented
        re-propose policy: "notification persists, token re-minted on demand").
        Re-minting on demand — rather than baking a 10-minute JWT into a durable
        row — means a proposal the user gets to days later still works, and a
        unique-per-mint token never defeats the ref-based dedup.

        Idempotency is layered: the caller logs a ``RuleExecution`` with
        ``result="needs_confirmation"`` whose ``uq_rule_exec_tx`` key makes a
        re-synced transaction a no-op (``_already_fired`` short-circuits before we
        get here), and the stable ``ref`` keeps the bell from stacking dupes even
        if a proposal is regenerated by a different signal. Re-minting itself goes
        through the dependency-free ``action_tokens`` leaf (no assistant import,
        no cycle) — this method doesn't mint, but the confirm path will.
        """
        # Stable dedup key: rule + goal + exact amount. NOT the token (a fresh JWT
        # each mint would make every ref unique and defeat dedup). Check-before-add
        # (like the Bridge nudge): two DIFFERENT transactions in one sync can trip
        # the same rule for the same amount — without this guard each would add a
        # duplicate notification (and, under a unique (user_id, ref) index, the
        # second add would raise an uncaught IntegrityError mid-_execute_action).
        ref = f"rule_proposal:{rule.id}:{goal.id}:{cents}"
        exists = self.db.execute(
            select(NotificationORM.id).where(
                NotificationORM.user_id == rule.user_id,
                NotificationORM.ref == ref,
            )
        ).scalar_one_or_none()
        if exists is not None:
            return
        dollars = cents_to_dollars(cents)
        self.db.add(
            NotificationORM(
                user_id=rule.user_id,
                type="rule_proposal",
                title=rule.name,
                message=(
                    f"Auto-fund rule “{rule.name}” wants to set aside "
                    f"${dollars:,.2f} toward “{goal.name}”. That's above your "
                    f"auto-fund limit, so it needs your approval."
                ),
                ref=ref,
            )
        )

    def _notify(self, rule: RuleORM, params: dict[str, Any], tx: dict[str, Any]) -> None:
        message = params.get("message") or (
            f"Rule “{rule.name}” matched {tx.get('title', 'a transaction')} "
            f"(${float(tx.get('amount') or 0):,.2f})"
        )
        self.db.add(
            NotificationORM(
                user_id=rule.user_id,
                type="rule",
                title=rule.name,
                message=message,
                ref=f"rule:{rule.id}:{tx.get('type')}:{tx.get('id', '')}",
            )
        )

    def _categorize(
        self, rule: RuleORM, params: dict[str, Any], tx: dict[str, Any]
    ) -> tuple[int, str]:
        """v2: user-editable categorization rule — recategorize the new expense.

        Only expenses are recategorized; the mapping is also learned so future
        transactions for the same merchant inherit it without the rule.
        """
        category = (params.get("category") or "").strip()
        if not category or tx.get("type") != "expense" or tx.get("id") is None:
            return 0, "noop"
        category = canonicalize_category(category)
        row = self.db.execute(
            select(ExpenseORM).where(ExpenseORM.id == tx["id"])
        ).scalar_one_or_none()
        if row is None:
            return 0, "target_missing"
        row.category = category
        CategorizationService(self.db).learn(
            rule.user_id, str(tx.get("title") or ""), category, source="rule"
        )
        tx["category"] = category  # later rules see the new category
        return 0, "ok"

    # ── preview (dry-run, no writes) ──────────────────────────────────────

    def preview(
        self, rule_like: dict[str, Any], sample_txns: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Dry-run a rule shape against sample transactions. Writes nothing.

        Returns, per matching transaction, what the action *would* do.
        """
        conditions = rule_like.get("conditions") or []
        params = rule_like.get("action_params") or {}
        action_type = rule_like.get("action_type")
        results: list[dict[str, Any]] = []
        for tx in sample_txns:
            if not matches(conditions, tx):
                continue
            tx_amount_cents = dollars_to_cents(float(tx.get("amount") or 0))
            would_move = 0
            if action_type == "allocate":
                would_move = self._allocation_cents(params, tx_amount_cents)
            elif action_type == "roundup":
                step = ROUNDUP_STEPS_CENTS.get(str(params.get("nearest", "1")), 100)
                would_move = roundup_cents(tx_amount_cents, step)
            results.append(
                {
                    "tx": tx,
                    "action_type": action_type,
                    "amount": cents_to_dollars(would_move),
                }
            )
        return results
