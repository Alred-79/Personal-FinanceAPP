"""Scenario overlays: a pure, DB-free description of stacked hypotheticals.

A ``ScenarioOverlay`` is applied at the single projection seam
(:meth:`RecurringService._project_rows`) so forecast / safe-to-spend / what-if all
gain hypotheticals with ZERO behavior change when no overlay is passed. It is the
keystone primitive — everything else in v6 builds on it.

Money discipline: every money field in an overlay is whole integer cents
(``*_cents``), so no float ever enters overlay storage. The projection dicts that
``_project_rows`` builds carry *dollar* amounts, so :meth:`apply_to_projected`
emits ``cents_to_dollars(amount_cents)`` when it injects or overrides a row.

The module is pure: no DB, no I/O, no clock. It reuses
:func:`project_occurrences` from ``recurring_service`` for the date math rather
than reimplementing it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from server.src.dates import parse_iso_date
from server.src.money import cents_to_dollars

# Bumped if the JSON shape changes; ``overlay_from_json`` rejects mismatches.
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RecurringAdd:
    """A brand-new recurring stream injected into the projection."""

    title: str
    amount_cents: int
    recurrence: str
    kind: str  # "expense" | "income"
    category: str = ""
    anchor_date: str | None = None  # ISO date the cadence steps from


@dataclass(frozen=True)
class RecurringOverride:
    """A change to an existing recurring source, keyed by ``(kind, source_id)``.

    ``amount_cents`` overrides the per-instance amount in place.  ``recurrence``
    changes the cadence — modelled downstream as exclude-original + re-expand from
    the original anchor, so a cadence change re-expands correctly.
    """

    source_id: int
    kind: str
    amount_cents: int | None = None
    recurrence: str | None = None


@dataclass(frozen=True)
class DiscreteFlow:
    """A one-off dated flow (e.g. a planned big purchase or bonus)."""

    date: str  # ISO date
    amount_cents: int
    kind: str  # "expense" | "income"
    title: str = ""
    category: str = ""


@dataclass(frozen=True)
class GoalMutation:
    """A hypothetical change to a savings goal (consumed by later docs)."""

    goal_id: int
    amount_cents: int | None = None
    target_date: str | None = None
    progress_cents: int | None = None
    name: str | None = None


@dataclass(frozen=True)
class ScenarioOverlay:
    """A stack of hypotheticals applied at the projection seam.

    All collections are immutable defaults so the dataclass stays hashable and
    safe to share.  ``EMPTY`` (module-level) is the identity overlay.
    """

    added_recurring: tuple[RecurringAdd, ...] = ()
    excluded_source_ids: frozenset[tuple[str, int]] = frozenset()
    overridden_recurring: tuple[RecurringOverride, ...] = ()
    discrete_flows: tuple[DiscreteFlow, ...] = ()
    goal_mutations: tuple[GoalMutation, ...] = ()
    balance_override_cents: int | None = None
    config_overrides: dict[str, Any] = field(default_factory=dict)

    def is_empty(self) -> bool:
        """True when applying this overlay is a guaranteed no-op for projection."""
        return (
            not self.added_recurring
            and not self.excluded_source_ids
            and not self.overridden_recurring
            and not self.discrete_flows
        )

    def apply_to_projected(
        self,
        projected: list[dict[str, Any]],
        horizon_start: date,
        horizon_end: date,
        *,
        kind: str,
    ) -> list[dict[str, Any]]:
        """Apply this overlay to one ``_project_rows`` output list.

        Operates on the dollar-amount dict shape ``_project_rows`` builds, for a
        single ``kind`` ("expense" | "income"). Steps, in order:

        1. drop rows whose ``(kind, source_id)`` is excluded — explicitly or as
           the original half of a recurrence-change override;
        2. apply in-place amount overrides;
        3. for recurrence-change overrides, re-expand from the original anchor;
        4. append expanded ``added_recurring`` streams of this kind;
        5. append in-window ``discrete_flows`` of this kind;
        6. re-sort by date so injected/overridden rows land in order.

        Returns a new list; the input is not mutated.  A no-op overlay returns a
        list equal to the input (identity).
        """
        # Local import avoids a module-load cycle (recurring_service imports
        # nothing from here, but keep the dependency one-directional and lazy).
        from server.src.services.recurring_service import project_occurrences

        # Amount overrides and recurrence-change overrides, indexed by source_id.
        amount_overrides: dict[int, int] = {}
        recurrence_changes: dict[int, RecurringOverride] = {}
        for ov in self.overridden_recurring:
            if ov.kind != kind:
                continue
            if ov.recurrence is not None:
                recurrence_changes[ov.source_id] = ov
            elif ov.amount_cents is not None:
                amount_overrides[ov.source_id] = ov.amount_cents

        # A recurrence change drops the original stream then re-expands it.
        excluded = {sid for (k, sid) in self.excluded_source_ids if k == kind}
        excluded |= set(recurrence_changes)

        result: list[dict[str, Any]] = []
        # The anchor each source's series stepped from, captured before we drop
        # excluded rows, so a recurrence change can re-expand from it.
        anchors: dict[int, str] = {}

        for row in projected:
            sid = row.get("source_id")
            if sid in recurrence_changes and "source_anchor" in row:
                anchors.setdefault(sid, row["source_anchor"])
            if sid in excluded:
                continue
            if sid in amount_overrides:
                row = {
                    **row,
                    "amount": cents_to_dollars(amount_overrides[sid]),
                }
            result.append(row)

        # Re-expand recurrence-changed streams from their original anchor.
        for sid, ov in recurrence_changes.items():
            new_recurrence = ov.recurrence
            if new_recurrence is None:  # populated only with a recurrence set
                continue
            anchor_iso = anchors.get(sid)
            anchor = parse_iso_date(anchor_iso) if anchor_iso else None
            if anchor is None:
                continue
            amount_cents = ov.amount_cents
            template = _find_template(projected, sid)
            amount = (
                cents_to_dollars(amount_cents)
                if amount_cents is not None
                else (template or {}).get("amount", 0.0)
            )
            for occ in project_occurrences(
                anchor, new_recurrence, horizon_start, horizon_end
            ):
                result.append(
                    _make_row(
                        source_id=sid,
                        title=(template or {}).get("title", ""),
                        amount=amount,
                        occ=occ,
                        category=(template or {}).get("category", ""),
                        recurrence=new_recurrence,
                        kind=kind,
                    )
                )

        # Inject newly-added recurring streams of this kind.
        for add in self.added_recurring:
            if add.kind != kind:
                continue
            anchor = parse_iso_date(add.anchor_date) if add.anchor_date else None
            if anchor is None:
                anchor = horizon_start
            for occ in project_occurrences(
                anchor, add.recurrence, horizon_start, horizon_end
            ):
                result.append(
                    _make_row(
                        source_id=None,
                        title=add.title,
                        amount=cents_to_dollars(add.amount_cents),
                        occ=occ,
                        category=add.category,
                        recurrence=add.recurrence,
                        kind=kind,
                    )
                )

        # Inject one-off discrete flows of this kind that fall inside the window.
        for flow in self.discrete_flows:
            if flow.kind != kind:
                continue
            occ = parse_iso_date(flow.date)
            if occ is None or occ < horizon_start or occ > horizon_end:
                continue
            result.append(
                _make_row(
                    source_id=None,
                    title=flow.title,
                    amount=cents_to_dollars(flow.amount_cents),
                    occ=occ,
                    category=flow.category,
                    recurrence=None,
                    kind=kind,
                )
            )

        result.sort(key=lambda d: d["date"])
        return result


def _make_row(
    *,
    source_id: int | None,
    title: str,
    amount: float,
    occ: date,
    category: str,
    recurrence: str | None,
    kind: str,
) -> dict[str, Any]:
    """An injected/synthesized projection row matching ``_project_rows`` shape."""
    return {
        "id": source_id,
        "source_id": source_id,
        "title": title,
        "amount": amount,
        "date": occ.isoformat(),
        "category": category,
        "recurrence": recurrence,
        "account_id": None,
        "type": kind,
        "projected": True,
    }


def _find_template(projected: list[dict[str, Any]], source_id: int) -> dict | None:
    """The first projected row for *source_id*, used as a re-expansion template."""
    for row in projected:
        if row.get("source_id") == source_id:
            return row
    return None


# The identity overlay: applying it changes nothing.
EMPTY = ScenarioOverlay()


# --------------------------------------------------------------------------- #
# JSON (de)serialization — schema-versioned, cents-only money.
# --------------------------------------------------------------------------- #
def overlay_to_json(overlay: ScenarioOverlay) -> dict[str, Any]:
    """Serialize an overlay to a plain JSON-safe dict (schema-versioned)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "added_recurring": [
            {
                "title": a.title,
                "amount_cents": a.amount_cents,
                "recurrence": a.recurrence,
                "kind": a.kind,
                "category": a.category,
                "anchor_date": a.anchor_date,
            }
            for a in overlay.added_recurring
        ],
        "excluded_source_ids": [
            [kind, sid] for (kind, sid) in sorted(overlay.excluded_source_ids)
        ],
        "overridden_recurring": [
            {
                "source_id": o.source_id,
                "kind": o.kind,
                "amount_cents": o.amount_cents,
                "recurrence": o.recurrence,
            }
            for o in overlay.overridden_recurring
        ],
        "discrete_flows": [
            {
                "date": f.date,
                "amount_cents": f.amount_cents,
                "kind": f.kind,
                "title": f.title,
                "category": f.category,
            }
            for f in overlay.discrete_flows
        ],
        "goal_mutations": [
            {
                "goal_id": g.goal_id,
                "amount_cents": g.amount_cents,
                "target_date": g.target_date,
                "progress_cents": g.progress_cents,
                "name": g.name,
            }
            for g in overlay.goal_mutations
        ],
        "balance_override_cents": overlay.balance_override_cents,
        "config_overrides": dict(overlay.config_overrides),
    }


def overlay_from_json(d: dict[str, Any]) -> ScenarioOverlay:
    """Deserialize an overlay produced by :func:`overlay_to_json`.

    Round-trips exactly (``overlay_from_json(overlay_to_json(x)) == x``).
    """
    version = d.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported scenario overlay schema_version: {version!r}"
        )
    return ScenarioOverlay(
        added_recurring=tuple(
            RecurringAdd(
                title=a["title"],
                amount_cents=a["amount_cents"],
                recurrence=a["recurrence"],
                kind=a["kind"],
                category=a.get("category", ""),
                anchor_date=a.get("anchor_date"),
            )
            for a in d.get("added_recurring", [])
        ),
        excluded_source_ids=frozenset(
            (kind, sid) for (kind, sid) in d.get("excluded_source_ids", [])
        ),
        overridden_recurring=tuple(
            RecurringOverride(
                source_id=o["source_id"],
                kind=o["kind"],
                amount_cents=o.get("amount_cents"),
                recurrence=o.get("recurrence"),
            )
            for o in d.get("overridden_recurring", [])
        ),
        discrete_flows=tuple(
            DiscreteFlow(
                date=f["date"],
                amount_cents=f["amount_cents"],
                kind=f["kind"],
                title=f.get("title", ""),
                category=f.get("category", ""),
            )
            for f in d.get("discrete_flows", [])
        ),
        goal_mutations=tuple(
            GoalMutation(
                goal_id=g["goal_id"],
                amount_cents=g.get("amount_cents"),
                target_date=g.get("target_date"),
                progress_cents=g.get("progress_cents"),
                name=g.get("name"),
            )
            for g in d.get("goal_mutations", [])
        ),
        balance_override_cents=d.get("balance_override_cents"),
        config_overrides=dict(d.get("config_overrides", {})),
    )