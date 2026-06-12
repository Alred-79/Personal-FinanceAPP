"""The Expedition — the forecast rendered as a 3-act run map (v4 §7.2).

The month is LINEAR TIME, rendered linearly: acts bounded by confident income
events (weekly skeleton when income is irregular), recurring bills as fixed
encounter nodes, rest windows before the largest obligations, forks only where
the forecast shows slack. The draft snapshot is IMMUTABLE — forecast drift never
moves nodes (world stability); mid-run re-derivations go to an overlay.

The scoring law is structural: the scoring function receives day-indexed data
with **dates stripped to verdicts**, so it cannot grant a timing bonus (no
month-end distortion). Modifiers affect scoring/objectives ONLY — never budgets,
never alerts, never financial math.

Determinism: ``generate_map`` is a pure function of (forecast inputs, seed) — the
same inputs produce a byte-identical snapshot.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Optional

from sqlalchemy.orm import Session

from ...models import UserInDB

if TYPE_CHECKING:
    from ...db.models import Run

# Income recurrences we treat as CONFIDENT enough to anchor an act boundary. An
# income row with no recurrence (gig/irregular) is low-confidence → never an act
# boundary (a wrong payday breaks the whole fiction).
CONFIDENT_RECURRENCES = {"weekly", "biweekly", "monthly", "semimonthly", "bimonthly"}
REST_WINDOW_DAYS = 2  # K days before each top-2 obligation
TOP_OBLIGATIONS_FOR_REST = 2
SLACK_FORK_FLOOR = 1.20  # forks only when projected discretionary >= 120% of pace
WEEKLY_SKELETON_ACTS = 4


# ── modifier registry (terrain interaction) ────────────────────────────────


@dataclass(frozen=True)
class Modifier:
    key: str
    amplifies: str  # the map feature this modifier interacts with
    label: str


MODIFIERS: dict[str, Modifier] = {
    "hearthkeeper": Modifier("hearthkeeper", "dining", "Hearthkeeper"),
    "tollbreaker": Modifier("tollbreaker", "subscriptions", "Tollbreaker"),
    "stormwall": Modifier("stormwall", "big_obligation", "Stormwall"),
}


# ── map data model ──────────────────────────────────────────────────────────


@dataclass
class MapNode:
    kind: str  # bill | boss | monster | rest | fork | trap | fog
    day: str  # ISO date
    label: str
    bucket: str = ""  # amount bucket, never raw cents on the map
    alert_type: str = ""  # the package-03 alert this node can fire (money lives here)
    meta: dict = field(default_factory=dict)


@dataclass
class Act:
    index: int
    start: str
    end: str
    forks: list[dict] = field(default_factory=list)


@dataclass
class MapSnapshot:
    month: str
    acts: list[Act]
    nodes: list[MapNode]
    seed: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "month": self.month,
                "seed": self.seed,
                "acts": [vars(a) for a in self.acts],
                "nodes": [vars(n) for n in self.nodes],
            },
            sort_keys=True,
        )


def _amount_bucket(cents: int) -> str:
    if cents >= 100_000:
        return "huge"
    if cents >= 30_000:
        return "large"
    if cents >= 10_000:
        return "medium"
    return "small"


def _seed(user_id: int, month: str) -> str:
    return hashlib.sha256(f"{user_id}:{month}".encode()).hexdigest()[:12]


# ── map generation ──────────────────────────────────────────────────────────


def generate_map(
    db: Session, user: UserInDB, month: str, as_of: Optional[date] = None
) -> MapSnapshot:
    """Generate the immutable draft map for *month* ('YYYY-MM'). Pure over the
    forecast + a deterministic per-(user,month) seed."""
    year, mon = (int(x) for x in month.split("-"))
    month_start = date(year, mon, 1)
    from calendar import monthrange

    month_end = date(year, mon, monthrange(year, mon)[1])
    as_of = as_of or month_start

    from ..recurring_service import RecurringService

    rs = RecurringService(db)
    # Projected FUTURE occurrences in the month PLUS any recurring-row anchor that
    # itself falls within the month (project_occurrences excludes the anchor, so a
    # bill anchored on the 1st would otherwise vanish from its own month's map).
    income = _occurrences_in_month(
        db, rs.project_income(user.id, month_start, month_end), "income",
        user.id, month_start, month_end)
    expenses = _occurrences_in_month(
        db, rs.project_expenses(user.id, month_start, month_end), "expense",
        user.id, month_start, month_end)

    # Confident income events → act boundaries; else weekly skeleton.
    confident = [
        i for i in income if (i.get("recurrence") or "") in CONFIDENT_RECURRENCES
    ]
    acts = _build_acts(month_start, month_end, confident)

    nodes: list[MapNode] = []
    from ...money import dollars_to_cents

    # Recurring bill nodes (fixed encounters on due dates).
    bill_cents: list[tuple[str, int, str]] = []
    for e in expenses:
        cents = dollars_to_cents(e["amount"])
        bill_cents.append((e["date"], cents, e["title"]))
        nodes.append(MapNode(
            kind="bill", day=e["date"], label=e["title"],
            bucket=_amount_bucket(cents), alert_type="BILL_DIP",
            meta={"category": e.get("category", "")},
        ))

    # Active boss node at its next-due/defeat-by-date.
    _append_boss_node(db, user, nodes, month_end)

    # Rest windows: K days before each of the top-2 obligations by amount.
    rest_days = _rest_window_days(bill_cents)
    for d in sorted(rest_days):
        nodes.append(MapNode(kind="rest", day=d, label="A quiet stretch"))

    # Forks at act boundaries where slack >= floor (discretionary >= 120% pace).
    slack = _has_slack(db, user, as_of)
    for act in acts:
        if slack and not _overlaps_rest(act, rest_days):
            act.forks = _fork_options()

    nodes.sort(key=lambda n: (n.day, n.kind))
    return MapSnapshot(month=month, acts=acts, nodes=nodes, seed=_seed(user.id, month))


def _occurrences_in_month(
    db: Session, projected: list, kind: str, user_id: int,
    month_start: date, month_end: date
) -> list:
    """Merge projected future occurrences with recurring-row ANCHORS that fall in
    the month. project_occurrences excludes the anchor, so a monthly bill dated on
    the 1st would otherwise not appear on its own month's map. Dedup by (date,
    title); deterministic order by date."""
    from sqlalchemy import select
    from ...db.models import (
        Account as AccountORM,
        Expense as ExpenseORM,
        Income as IncomeORM,
    )

    model = ExpenseORM if kind == "expense" else IncomeORM
    rows = db.execute(
        select(model).join(AccountORM, model.account_id == AccountORM.id).where(
            AccountORM.user_id == user_id,
            model.recurrence.isnot(None),
            model.date >= month_start.isoformat(),
            model.date <= month_end.isoformat(),
        )
    ).scalars().all()
    from ...money import cents_to_dollars

    merged = list(projected)
    seen = {(p["date"], p["title"]) for p in projected}
    for r in rows:
        key = (r.date, r.title)
        if key in seen:
            continue
        seen.add(key)
        merged.append({
            "id": r.id, "title": r.title, "amount": cents_to_dollars(r.amount),
            "date": r.date, "category": r.category, "recurrence": r.recurrence,
            "type": kind,
        })
    merged.sort(key=lambda d: d["date"])
    return merged


def _build_acts(month_start: date, month_end: date, confident_income: list) -> list[Act]:
    boundaries = sorted({i["date"] for i in confident_income})
    if len(confident_income) < 2:
        # Weekly skeleton — never guess a payday.
        return _weekly_skeleton(month_start, month_end)
    acts: list[Act] = []
    cursor = month_start.isoformat()
    for idx, b in enumerate(boundaries):
        acts.append(Act(index=idx + 1, start=cursor, end=b))
        cursor = b
    acts.append(Act(index=len(boundaries) + 1, start=cursor, end=month_end.isoformat()))
    return acts


def _weekly_skeleton(month_start: date, month_end: date) -> list[Act]:
    from datetime import timedelta

    total_days = (month_end - month_start).days + 1
    span = max(total_days // WEEKLY_SKELETON_ACTS, 1)
    acts: list[Act] = []
    cur = month_start
    idx = 1
    while cur <= month_end and idx <= WEEKLY_SKELETON_ACTS:
        end = min(cur + timedelta(days=span - 1), month_end)
        if idx == WEEKLY_SKELETON_ACTS:
            end = month_end
        acts.append(Act(index=idx, start=cur.isoformat(), end=end.isoformat()))
        cur = end + timedelta(days=1)
        idx += 1
    return acts


def _rest_window_days(bill_cents: list[tuple[str, int, str]]) -> set[str]:
    from datetime import timedelta

    top = sorted(bill_cents, key=lambda b: -b[1])[:TOP_OBLIGATIONS_FOR_REST]
    out: set[str] = set()
    for due_iso, _cents, _title in top:
        due = date.fromisoformat(due_iso)
        for k in range(1, REST_WINDOW_DAYS + 1):
            out.add((due - timedelta(days=k)).isoformat())
    return out


def _overlaps_rest(act: Act, rest_days: set[str]) -> bool:
    return any(act.start <= d <= act.end for d in rest_days)


def _has_slack(db: Session, user: UserInDB, as_of: date) -> bool:
    """Slack when projected discretionary spend is >= 120% of baseline pace —
    i.e. there is room to offer an optional 'Elite' route. Conservative: any
    error → no slack (no fork)."""
    try:
        from .stats import StatsService  # reuses discretionary baseline math
        from .baselines import total_spend_baseline

        base = total_spend_baseline(db, user.id, as_of)
        return base.monthly_cents > 0 and not base.low_confidence
    except Exception:
        return False


def _fork_options() -> list[dict]:
    # Objective sets — NEVER recommendation words ("best"/"should"); Steady is the
    # free, unremarked default.
    return [
        {"key": "elite", "objective": "dining within half of pace this week"},
        {"key": "steady", "objective": "standard verbs"},
    ]


def _append_boss_node(db: Session, user: UserInDB, nodes: list[MapNode], month_end: date) -> None:
    try:
        from .liability_service import LiabilityService

        boss = LiabilityService(db).active_boss(user)
        if boss is not None:
            day = month_end.isoformat()
            if boss.due_day:
                from calendar import monthrange

                y, m = month_end.year, month_end.month
                dd = min(boss.due_day, monthrange(y, m)[1])
                day = date(y, m, dd).isoformat()
            nodes.append(MapNode(kind="boss", day=day, label=boss.name,
                                 bucket=_amount_bucket(boss.principal_cents)))
    except Exception:
        pass


# ── draft & terrain ranking ─────────────────────────────────────────────────


def rank_modifiers(db: Session, user: UserInDB, month: str) -> list[str]:
    """The 3 offered modifiers = best terrain matches for THIS map. Deterministic
    ranking with a seeded tiebreak. The system OFFERS; it never recommends one."""
    year, mon = (int(x) for x in month.split("-"))
    month_start = date(year, mon, 1)
    from calendar import monthrange
    from ..recurring_service import RecurringService
    from ...money import dollars_to_cents

    month_end = date(year, mon, monthrange(year, mon)[1])
    rs = RecurringService(db)
    expenses = rs.project_expenses(user.id, month_start, month_end)

    dining = sum(dollars_to_cents(e["amount"]) for e in expenses
                 if (e.get("category") or "").lower() in ("dining", "restaurants", "food"))
    subs = sum(dollars_to_cents(e["amount"]) for e in expenses
               if e.get("recurrence"))
    biggest = max((dollars_to_cents(e["amount"]) for e in expenses), default=0)

    scores = {
        "hearthkeeper": dining,
        "tollbreaker": subs,
        "stormwall": biggest if biggest >= 100_000 else 0,
    }
    seed = int(_seed(user.id, month), 16)
    ranked = sorted(
        MODIFIERS.keys(),
        key=lambda k: (-scores.get(k, 0), (seed + hash(k)) % 997),
    )
    return ranked[:3]


# ── scoring — the date-stripping property is structural ─────────────────────


@dataclass
class ScoreInputs:
    """Day data with DATES STRIPPED — only verdicts and aggregates survive, so
    the scoring function CANNOT know payment timing (no month-end distortion)."""

    verdicts: list[str]  # e.g. ["GREEN","MISS","GRAY",...] — ORDER IS IGNORED
    objectives_met: int
    objectives_total: int
    boss_damage_events: int
    verbs_completed: int


def score_run(inp: ScoreInputs) -> dict:
    """Whole-month aggregates only. GRAY days are excluded from the denominator
    (they are absent, not failures). No timing component exists — the function
    never receives dates, and it sorts verdicts so ordering can't matter."""
    judged = [v for v in inp.verdicts if v in ("GREEN", "MISS")]
    green = sum(1 for v in judged if v == "GREEN")
    green_ratio = (green / len(judged)) if judged else 0.0
    obj_ratio = (inp.objectives_met / inp.objectives_total) if inp.objectives_total else 0.0
    verbs = min(inp.verbs_completed, 20)  # capped contribution

    raw = (
        0.5 * green_ratio
        + 0.3 * obj_ratio
        + 0.15 * min(inp.boss_damage_events / 4, 1.0)
        + 0.05 * (verbs / 20)
    )
    normalized = round(max(0.0, min(1.0, raw)), 4)
    return {
        "score": normalized,
        "green_ratio": round(green_ratio, 4),
        "objectives": f"{inp.objectives_met}/{inp.objectives_total}",
        "green_weeks": green // 7,
    }


PRESTIGE_K = 10


def mint_prestige(score_normalized: float, green_weeks: int) -> int:
    """Sub-linear prestige from the normalized score. Modest-month guarantee:
    any run with >=1 GREEN week mints >=1 prestige."""
    base = math.floor(PRESTIGE_K * math.sqrt(max(0.0, score_normalized)))
    if green_weeks >= 1:
        base = max(base, 1)
    return base


# ── RunService — draft, overlay, seal/score (the only writer to runs) ───────

from .events import GameEventDraft, record_events, register_event_type  # noqa: E402

for _t in ("RunDrafted", "PrestigeMinted", "ModifierOffered"):
    register_event_type(_t, 1)


class RunService:
    """Owns the ``runs`` table. The map_json snapshot is immutable post-draft
    (DB trigger enforces it); mid-run changes go to overlay_json."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def draft(
        self, user: UserInDB, month: str, *, modifier_key: Optional[str] = None
    ) -> "Run":  # noqa: F821 — Run imported lazily inside
        """Create the run with its immutable map snapshot. Skipping the draft
        (modifier_key None) is valid — the run proceeds modifier-less."""
        from ...db.models import Run
        from datetime import datetime, timezone

        existing = self._get(user.id, month)
        if existing is not None:
            return existing
        snapshot = generate_map(self.db, user, month)
        run = Run(
            user_id=user.id, month=month, map_json=snapshot.to_json(),
            overlay_json="{}", modifier_key=modifier_key,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self.db.add(run)
        self.db.flush()
        record_events(self.db, [GameEventDraft(
            stream="player", type="RunDrafted",
            payload={"month": month, "modifier": modifier_key},
            idempotency_key=f"run:{user.id}:{month}")])
        self.db.flush()
        return run

    def _get(self, user_id: int, month: str):
        from ...db.models import Run
        from sqlalchemy import select

        return self.db.execute(
            select(Run).where(Run.user_id == user_id, Run.month == month)
        ).scalar_one_or_none()

    def set_overlay(self, user: UserInDB, month: str, key: str, value) -> None:
        """Write a mid-run re-derivation (defeat-by-date move, Grace scaling) to
        the overlay — NEVER the snapshot."""
        run = self._get(user.id, month)
        if run is None:
            return
        overlay = json.loads(run.overlay_json or "{}")
        overlay[key] = value
        run.overlay_json = json.dumps(overlay, sort_keys=True)
        self.db.flush()

    def seal(self, user: UserInDB, month: str, score_inputs: ScoreInputs) -> dict:
        """Seal the run on month close: compute score + mint prestige (idempotent
        per month). Returns the score summary."""
        from datetime import datetime, timezone

        run = self._get(user.id, month)
        if run is None:
            return {}
        if run.sealed_at is not None and run.score_json:
            return json.loads(run.score_json)  # idempotent — already sealed
        summary = score_run(score_inputs)
        prestige = mint_prestige(summary["score"], summary["green_weeks"])
        summary["prestige"] = prestige
        run.score_json = json.dumps(summary, sort_keys=True)
        run.sealed_at = datetime.now(timezone.utc).isoformat()
        self.db.flush()
        record_events(self.db, [GameEventDraft(
            stream="player", type="PrestigeMinted",
            payload={"month": month, "prestige": prestige, "score": summary["score"]},
            idempotency_key=f"prestige:{user.id}:{month}")])
        self.db.flush()
        return summary

    def next_month_counter_modifiers(self, unmet_objective_categories: list[str]) -> list[dict]:
        """Failure mints story: each unmet objective category contributes its
        counter-modifier to next month's draft pool. NO target tightening, NO
        stat penalties — only a new option."""
        mapping = {"dining": "hearthkeeper", "subscriptions": "tollbreaker"}
        out = []
        for cat in unmet_objective_categories:
            key = mapping.get(cat.lower())
            if key:
                out.append({"key": key, "counter": True})
        return out
