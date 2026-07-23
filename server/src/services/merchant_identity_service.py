"""Flat, reversible merchant grouping owned explicitly by one user.

Aliases are exact normalized keys, never inferred identities. They form a
one-hop sidecar used only by categorization lookup/learning and the read-only
subscription detector. Transactions and other analytical/action paths keep
their original descriptors.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.src.db.models import (
    Expense as ExpenseORM,
    MerchantAlias as MerchantAliasORM,
    User as UserORM,
)


class MerchantAliasError(ValueError):
    """A user-visible alias contract violation."""


def _normalize(value: str) -> str:
    # Local import avoids a module cycle: categorization consumes this service.
    from server.src.services.categorization_service import normalize_merchant

    return normalize_merchant(value)


def _serialize(row: MerchantAliasORM) -> dict[str, object]:
    return {
        "id": row.id,
        "alias_key": row.alias_key,
        "canonical_key": row.canonical_key,
        "canonical_label": row.canonical_label,
        "source": row.source,
        "active": bool(row.active),
        "created_at": row.created_at,
    }


class MerchantIdentityService:
    """Creates and resolves user-confirmed one-hop aliases."""

    DESCRIPTOR_LIMIT = 100

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_aliases(self, user_id: int) -> list[dict[str, object]]:
        rows = (
            self.db.execute(
                select(MerchantAliasORM)
                .where(
                    MerchantAliasORM.user_id == user_id,
                    MerchantAliasORM.active == 1,
                )
                .order_by(MerchantAliasORM.alias_key, MerchantAliasORM.id)
            )
            .scalars()
            .all()
        )
        return [_serialize(row) for row in rows]

    def descriptors(
        self, user_id: int, *, limit: int = DESCRIPTOR_LIMIT
    ) -> list[dict[str, str]]:
        """Return a capped, normalized selection corpus from owned expenses.

        The newest observed spelling becomes the display label for a normalized
        key. Empty/punctuation-only descriptions never become choices.
        """
        safe_limit = max(1, min(int(limit), self.DESCRIPTOR_LIMIT))
        rows = self.db.execute(
            select(ExpenseORM.title)
            .where(ExpenseORM.user_id == user_id)
            .order_by(ExpenseORM.date.desc(), ExpenseORM.id.desc())
        ).scalars()

        result: list[dict[str, str]] = []
        seen: set[str] = set()
        for title in rows:
            key = _normalize(title or "")
            if not key or key in seen:
                continue
            seen.add(key)
            result.append({"descriptor": title.strip(), "normalized_key": key})
            if len(result) >= safe_limit:
                break
        return result

    def _observed_labels(self, user_id: int) -> dict[str, str]:
        """All normalized observed keys for server-side confirmation checks."""
        rows = self.db.execute(
            select(ExpenseORM.title)
            .where(ExpenseORM.user_id == user_id)
            .order_by(ExpenseORM.date.desc(), ExpenseORM.id.desc())
        ).scalars()
        observed: dict[str, str] = {}
        for title in rows:
            key = _normalize(title or "")
            if key and key not in observed:
                observed[key] = title.strip()
        return observed

    def active_map(self, user_id: int) -> dict[str, str]:
        return dict(
            self.db.execute(
                select(MerchantAliasORM.alias_key, MerchantAliasORM.canonical_key).where(
                    MerchantAliasORM.user_id == user_id,
                    MerchantAliasORM.active == 1,
                )
            ).all()
        )

    def resolve_key(self, user_id: int, merchant_key: str) -> str:
        """Resolve exactly one active hop; never follow a chain."""
        if not merchant_key:
            return merchant_key
        canonical = self.db.execute(
            select(MerchantAliasORM.canonical_key).where(
                MerchantAliasORM.user_id == user_id,
                MerchantAliasORM.alias_key == merchant_key,
                MerchantAliasORM.active == 1,
            )
        ).scalar_one_or_none()
        return canonical or merchant_key

    def confirm(
        self, user_id: int, alias_descriptor: str, canonical_descriptor: str
    ) -> dict[str, object]:
        alias_key = _normalize(alias_descriptor)
        canonical_key = _normalize(canonical_descriptor)
        if not alias_key or not canonical_key:
            raise MerchantAliasError(
                "Both descriptors must contain letters after normalization."
            )
        if alias_key == canonical_key:
            raise MerchantAliasError("A descriptor cannot be grouped into itself.")

        # Serialize alias edits for this tenant. On Postgres this prevents two
        # concurrent requests from constructing A→B and B→A between checks; on
        # SQLite the write transaction provides the equivalent serialization.
        owner = self.db.execute(
            select(UserORM.id).where(UserORM.id == user_id).with_for_update()
        ).scalar_one_or_none()
        if owner is None:
            raise MerchantAliasError("The merchant group owner does not exist.")

        observed = self._observed_labels(user_id)
        if alias_key not in observed or canonical_key not in observed:
            raise MerchantAliasError(
                "Choose two descriptors observed in your own expense history."
            )

        existing = self.db.execute(
            select(MerchantAliasORM).where(
                MerchantAliasORM.user_id == user_id,
                MerchantAliasORM.alias_key == alias_key,
            )
        ).scalar_one_or_none()

        # The target cannot itself be an alias, and a key already serving as a
        # canonical target cannot be turned into an alias. Together these keep
        # the active relation flat and reject chains/reversed pairs.
        target_is_alias = self.db.execute(
            select(MerchantAliasORM.id).where(
                MerchantAliasORM.user_id == user_id,
                MerchantAliasORM.alias_key == canonical_key,
                MerchantAliasORM.active == 1,
            )
        ).scalar_one_or_none()
        alias_is_target = self.db.execute(
            select(MerchantAliasORM.id).where(
                MerchantAliasORM.user_id == user_id,
                MerchantAliasORM.canonical_key == alias_key,
                MerchantAliasORM.active == 1,
                MerchantAliasORM.alias_key != alias_key,
            )
        ).scalar_one_or_none()
        if target_is_alias is not None or alias_is_target is not None:
            raise MerchantAliasError(
                "Merchant groups must stay one level deep; chains and reversed pairs are not allowed."
            )

        if existing is None:
            row = MerchantAliasORM(
                user_id=user_id,
                alias_key=alias_key,
                canonical_key=canonical_key,
                canonical_label=observed[canonical_key],
                source="user",
                active=1,
            )
        else:
            row = existing
            row.canonical_key = canonical_key
            row.canonical_label = observed[canonical_key]
            row.source = "user"
            row.active = 1
            row.reverted_at = None

        try:
            with self.db.begin_nested():
                self.db.add(row)
                self.db.flush()
        except IntegrityError as exc:
            raise MerchantAliasError(
                "That merchant grouping changed concurrently; refresh and try again."
            ) from exc
        return _serialize(row)

    def revert(self, user_id: int, alias_id: int) -> bool:
        row = self.db.execute(
            select(MerchantAliasORM).where(
                MerchantAliasORM.id == alias_id,
                MerchantAliasORM.user_id == user_id,
                MerchantAliasORM.active == 1,
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        row.active = 0
        row.reverted_at = datetime.now(timezone.utc)
        self.db.flush()
        return True
