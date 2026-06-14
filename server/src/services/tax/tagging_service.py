"""Learned tax-bucket mapping + tag upsert. Mirrors ``CategorizationService``.

The learned tier (``MerchantTaxBucket``) carries the same source precedence as
``MerchantCategory``: a ``"user"`` tag is never clobbered by a ``"rule"``/``"llm"``
guess. ``suggest_bucket`` is 2-tier (learned → keyword); there is deliberately
NO Groq tier here — the agent's ``tag_transaction_tax`` propose tool is the LLM
path and always goes through confirm.

This ORGANIZES; it never asserts eligibility.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.src.db.models import (
    Expense as ExpenseORM,
    Income as IncomeORM,
    MerchantTaxBucket as MerchantTaxBucketORM,
    TaxTag as TaxTagORM,
)
from server.src.dates import parse_iso_date
from server.src.services.categorization_service import normalize_merchant

from .buckets import (
    canonicalize_bucket,
    default_deductible_bps,
    suggest_bucket as keyword_suggest_bucket,
)


def tax_year_for(date_str: str) -> int:
    """The denormalized tax year for a bare ISO date (calendar-year US filer).

    Validates with ``parse_iso_date`` first (so a junk string can't poison the
    stored year), then takes ``int(date[:4])`` — exactly the IRS cash-basis
    convention for a calendar-year filer. A Dec-31/Jan-1 transaction lands in its
    own date's year; we do NOT attempt fiscal-year/timezone correctness the bare
    date model can't support.
    """
    if not parse_iso_date(date_str):
        raise ValueError(f"invalid transaction date: {date_str!r}")
    return int(date_str[:4])


class TaxTaggingService:
    """Per-user tax-bucket memory + the tag upsert. Mirrors
    ``CategorizationService`` (learned mapping, source precedence)."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── learned mapping ──────────────────────────────────────────────────────

    def learned_bucket(self, user_id: int, merchant_key: str) -> Optional[str]:
        if not merchant_key:
            return None
        return self.db.execute(
            select(MerchantTaxBucketORM.bucket).where(
                MerchantTaxBucketORM.user_id == user_id,
                MerchantTaxBucketORM.merchant == merchant_key,
            )
        ).scalar_one_or_none()

    def learn(
        self, user_id: int, title: str, bucket: str, source: str = "user"
    ) -> None:
        """Upsert a merchant → bucket mapping. A ``"user"`` tag always wins; a
        less-trusted source (``"rule"``/``"llm"``) never overwrites a ``"user"``
        mapping. Mirrors ``CategorizationService.learn`` exactly."""
        key = normalize_merchant(title)
        canon = canonicalize_bucket(bucket)
        if not key or not canon:
            return
        existing = self.db.execute(
            select(MerchantTaxBucketORM).where(
                MerchantTaxBucketORM.user_id == user_id,
                MerchantTaxBucketORM.merchant == key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            if source != "user" and existing.source == "user":
                return  # don't let an LLM/rule guess clobber a manual tag
            existing.bucket = canon
            existing.source = source
        else:
            self.db.add(
                MerchantTaxBucketORM(
                    user_id=user_id, merchant=key, bucket=canon, source=source
                )
            )
        self.db.flush()

    def suggest_bucket(self, user_id: int, title: str) -> Optional[str]:
        """2-tier suggestion: learned mapping → keyword map. None on a miss.

        No Groq tier — the agent's propose tool covers the LLM path (behind
        confirm). Returns a real registry key or None; never a ghost bucket.
        """
        key = normalize_merchant(title)
        learned = self.learned_bucket(user_id, key)
        if learned:
            return learned
        return keyword_suggest_bucket(title)

    # ── the tag upsert (one tag per transaction) ─────────────────────────────

    def tag(
        self,
        user_id: int,
        *,
        tx_type: str,
        tx_id: int,
        tax_year: int,
        bucket: str,
        business_personal: str = "business",
        deductible_bps: Optional[int] = None,
        source: str = "user",
        note: Optional[str] = None,
    ) -> TaxTagORM:
        """Upsert the single ``TaxTag`` for a transaction (re-tag replaces).

        Assumes ``bucket`` is already canonicalized and the transaction is owned
        by the user (the caller — the action ``execute`` or the router — does the
        ownership check). ``deductible_bps`` defaults to the bucket's registry
        default when not given. Also records the learned mapping when a title is
        derivable (the caller passes ``source``)."""
        canon = canonicalize_bucket(bucket)
        if not canon:
            raise ValueError(f"unknown tax bucket: {bucket!r}")
        if business_personal not in ("business", "personal"):
            raise ValueError("business_personal must be 'business' or 'personal'")
        bps = (
            default_deductible_bps(canon)
            if deductible_bps is None
            else int(deductible_bps)
        )
        if bps < 0 or bps > 10000:
            raise ValueError("deductible_bps must be between 0 and 10000")

        existing = self.db.execute(
            select(TaxTagORM).where(
                TaxTagORM.tx_type == tx_type,
                TaxTagORM.tx_id == tx_id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.user_id = user_id
            existing.tax_year = tax_year
            existing.bucket = canon
            existing.business_personal = business_personal
            existing.deductible_bps = bps
            existing.source = source
            existing.note = note
            tag = existing
        else:
            tag = TaxTagORM(
                user_id=user_id,
                tx_type=tx_type,
                tx_id=tx_id,
                tax_year=tax_year,
                bucket=canon,
                business_personal=business_personal,
                deductible_bps=bps,
                source=source,
                note=note,
            )
            self.db.add(tag)
        self.db.flush()
        return tag

    def untag(self, user_id: int, tx_type: str, tx_id: int) -> bool:
        """Remove a transaction's tax tag. Returns True if one was removed."""
        existing = self.db.execute(
            select(TaxTagORM).where(
                TaxTagORM.tx_type == tx_type,
                TaxTagORM.tx_id == tx_id,
                TaxTagORM.user_id == user_id,
            )
        ).scalar_one_or_none()
        if existing is None:
            return False
        self.db.delete(existing)
        self.db.flush()
        return True

    # ── ownership helper (join-through-account, mirrors recategorize) ────────

    def owned_transaction(self, user_id: int, tx_type: str, tx_id: int):
        """Load the owned Expense/Income row or None (join through account).

        Mirrors ``recategorize_transaction``'s ownership check so a tag can never
        be applied to another user's transaction.
        """
        from server.src.db.models import Account as AccountORM

        model = ExpenseORM if tx_type == "expense" else IncomeORM
        return self.db.execute(
            select(model)
            .join(AccountORM, model.account_id == AccountORM.id)
            .where(model.id == tx_id, AccountORM.user_id == user_id)
        ).scalar_one_or_none()
