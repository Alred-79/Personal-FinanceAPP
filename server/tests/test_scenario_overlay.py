"""Pure (no-DB) tests for the scenario overlay primitive.

Covers the identity no-op, the cents-discipline JSON round-trip, and each
``apply_to_projected`` operation: exclude, amount override, recurring add,
in-window discrete flow, and recurrence-change (= exclude + re-add).
"""

from datetime import date

from server.src.services.scenario_overlay import (
    DiscreteFlow,
    GoalMutation,
    RecurringAdd,
    RecurringOverride,
    ScenarioOverlay,
    EMPTY,
    overlay_from_json,
    overlay_to_json,
)

HS = date(2026, 1, 1)
HE = date(2026, 12, 31)


def _row(source_id, amount, d, *, kind="expense", title="X", recurrence="monthly"):
    """A projection row in the dollar-amount shape ``_project_rows`` builds."""
    return {
        "id": source_id,
        "source_id": source_id,
        "title": title,
        "amount": amount,
        "date": d,
        "category": "",
        "recurrence": recurrence,
        "account_id": 1,
        "type": kind,
        "projected": True,
        "source_anchor": "2025-12-15",
    }


class TestIdentity:
    def test_empty_is_identity(self):
        rows = [_row(1, 10.0, "2026-02-15"), _row(2, 20.0, "2026-03-15")]
        out = EMPTY.apply_to_projected(rows, HS, HE, kind="expense")
        assert out == rows

    def test_empty_does_not_mutate_input(self):
        rows = [_row(1, 10.0, "2026-02-15")]
        before = [dict(r) for r in rows]
        EMPTY.apply_to_projected(rows, HS, HE, kind="expense")
        assert rows == before

    def test_is_empty_flag(self):
        assert EMPTY.is_empty()
        assert ScenarioOverlay().is_empty()
        assert not ScenarioOverlay(
            excluded_source_ids=frozenset({("expense", 1)})
        ).is_empty()


class TestRoundTrip:
    def test_full_overlay_round_trips(self):
        overlay = ScenarioOverlay(
            added_recurring=(
                RecurringAdd(
                    title="Gym",
                    amount_cents=4500,
                    recurrence="monthly",
                    kind="expense",
                    category="health",
                    anchor_date="2026-01-10",
                ),
            ),
            excluded_source_ids=frozenset({("expense", 7), ("income", 3)}),
            overridden_recurring=(
                RecurringOverride(source_id=2, kind="expense", amount_cents=9900),
                RecurringOverride(source_id=5, kind="income", recurrence="weekly"),
            ),
            discrete_flows=(
                DiscreteFlow(
                    date="2026-06-01",
                    amount_cents=120000,
                    kind="expense",
                    title="Vacation",
                    category="travel",
                ),
            ),
            goal_mutations=(
                GoalMutation(
                    goal_id=1,
                    amount_cents=500000,
                    target_date="2027-01-01",
                    progress_cents=1000,
                    name="Emergency fund",
                ),
            ),
            balance_override_cents=250000,
            config_overrides={"inflation": "high"},
        )
        assert overlay_from_json(overlay_to_json(overlay)) == overlay

    def test_empty_round_trips(self):
        assert overlay_from_json(overlay_to_json(EMPTY)) == EMPTY

    def test_money_fields_are_ints_in_json(self):
        overlay = ScenarioOverlay(
            added_recurring=(
                RecurringAdd("A", 4500, "monthly", "expense"),
            ),
            discrete_flows=(DiscreteFlow("2026-06-01", 120000, "expense"),),
            balance_override_cents=250000,
        )
        d = overlay_to_json(overlay)
        assert isinstance(d["added_recurring"][0]["amount_cents"], int)
        assert isinstance(d["discrete_flows"][0]["amount_cents"], int)
        assert isinstance(d["balance_override_cents"], int)
        assert d["schema_version"] == 1


class TestExclude:
    def test_excludes_by_kind_and_source_id(self):
        rows = [_row(1, 10.0, "2026-02-15"), _row(2, 20.0, "2026-03-15")]
        overlay = ScenarioOverlay(
            excluded_source_ids=frozenset({("expense", 1)})
        )
        out = overlay.apply_to_projected(rows, HS, HE, kind="expense")
        assert [r["source_id"] for r in out] == [2]

    def test_exclude_is_kind_scoped(self):
        rows = [_row(1, 10.0, "2026-02-15")]
        overlay = ScenarioOverlay(
            excluded_source_ids=frozenset({("income", 1)})
        )
        out = overlay.apply_to_projected(rows, HS, HE, kind="expense")
        assert len(out) == 1


class TestAmountOverride:
    def test_overrides_existing_amount(self):
        rows = [_row(1, 10.0, "2026-02-15"), _row(1, 10.0, "2026-03-15")]
        overlay = ScenarioOverlay(
            overridden_recurring=(
                RecurringOverride(source_id=1, kind="expense", amount_cents=2500),
            )
        )
        out = overlay.apply_to_projected(rows, HS, HE, kind="expense")
        assert all(r["amount"] == 25.0 for r in out)
        assert len(out) == 2


class TestRecurringAdd:
    def test_injects_expanded_stream(self):
        overlay = ScenarioOverlay(
            added_recurring=(
                RecurringAdd(
                    title="Gym",
                    amount_cents=4500,
                    recurrence="monthly",
                    kind="expense",
                    anchor_date="2026-01-10",
                ),
            )
        )
        out = overlay.apply_to_projected([], HS, HE, kind="expense")
        # Feb..Dec anchored on the 10th = 11 occurrences (anchor itself excluded).
        assert len(out) == 11
        assert all(r["amount"] == 45.0 for r in out)
        assert all(r["title"] == "Gym" for r in out)
        assert out[0]["date"] == "2026-02-10"

    def test_added_stream_is_kind_scoped(self):
        overlay = ScenarioOverlay(
            added_recurring=(
                RecurringAdd("Pay", 500000, "monthly", "income", anchor_date="2026-01-01"),
            )
        )
        assert overlay.apply_to_projected([], HS, HE, kind="expense") == []
        income = overlay.apply_to_projected([], HS, HE, kind="income")
        # Anchor 2026-01-01 excluded; Feb..Dec inside the year = 11.
        assert len(income) == 11


class TestDiscreteFlow:
    def test_injects_in_window_flow(self):
        overlay = ScenarioOverlay(
            discrete_flows=(
                DiscreteFlow("2026-06-01", 120000, "expense", title="Trip"),
            )
        )
        out = overlay.apply_to_projected([], HS, HE, kind="expense")
        assert len(out) == 1
        assert out[0]["amount"] == 1200.0
        assert out[0]["date"] == "2026-06-01"

    def test_drops_out_of_window_flow(self):
        overlay = ScenarioOverlay(
            discrete_flows=(
                DiscreteFlow("2027-06-01", 120000, "expense"),
                DiscreteFlow("2025-06-01", 120000, "expense"),
            )
        )
        assert overlay.apply_to_projected([], HS, HE, kind="expense") == []


class TestRecurrenceChange:
    def test_recurrence_change_re_expands(self):
        # A monthly stream anchored 2025-12-15 → switch to weekly.
        rows = [
            _row(1, 10.0, "2026-01-15"),
            _row(1, 10.0, "2026-02-15"),
        ]
        overlay = ScenarioOverlay(
            overridden_recurring=(
                RecurringOverride(source_id=1, kind="expense", recurrence="weekly"),
            )
        )
        out = overlay.apply_to_projected(rows, HS, HE, kind="expense")
        # No monthly rows survive; all are weekly re-expansions.
        assert all(r["recurrence"] == "weekly" for r in out)
        # Weekly from 2025-12-15 inside the year → many more than 2 rows.
        assert len(out) > 2
        assert all(r["amount"] == 10.0 for r in out)

    def test_recurrence_change_equals_exclude_plus_add(self):
        rows = [_row(1, 10.0, "2026-01-15"), _row(1, 10.0, "2026-02-15")]
        # Path A: a recurrence-change override.
        changed = ScenarioOverlay(
            overridden_recurring=(
                RecurringOverride(source_id=1, kind="expense", recurrence="weekly"),
            )
        ).apply_to_projected(rows, HS, HE, kind="expense")
        # Path B: exclude the original + add the same stream from the same anchor.
        manual = ScenarioOverlay(
            excluded_source_ids=frozenset({("expense", 1)}),
            added_recurring=(
                RecurringAdd(
                    title="X",
                    amount_cents=1000,
                    recurrence="weekly",
                    kind="expense",
                    anchor_date="2025-12-15",
                ),
            ),
        ).apply_to_projected(rows, HS, HE, kind="expense")
        assert [r["date"] for r in changed] == [r["date"] for r in manual]
        assert [r["amount"] for r in changed] == [r["amount"] for r in manual]
