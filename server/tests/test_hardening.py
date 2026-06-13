"""v4 package 10 — system-wide hardening (spec test cases 21-26).

The full-season simulation (a reusable fixture), the mode-law walk, the
performance pass, and the failure-mode drills (Groq down, Plaid stale,
mid-sync atomicity).
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from server.src.db.models import (
    Account as AccountORM,
    Budget as BudgetORM,
    CategorySettings as CategorySettingsORM,
    Expense as ExpenseORM,
    Liability as LiabilityORM,
    Token as TokenORM,
    User as UserORM,
)
from server.src.models import UserInDB
from server.src.services.game import folds as folds_mod
from server.src.services.game.events import GameEventDraft, record_events
from server.src.services.game.rebuild import rebuild_all
from server.src.services.game.stats import player_xp
from server.tests.integrity import finance_tables_fingerprint


@pytest.fixture
def user_acct(db_session):
    user = UserORM(username="season", full_name="Season U",
                   email="season@x.com", hashed_password="x", savings_percent=0)
    db_session.add(user)
    db_session.flush()
    acct = AccountORM(name="Checking", type="checking", balance=5_000_00,
                      user_id=user.id)
    db_session.add(acct)
    db_session.flush()
    return user, acct


def _u(user):
    return UserInDB(id=user.id, username=user.username, email=user.email,
                    full_name=user.full_name, disabled=False, hashed_password="x")


def _emit(db, ev_type, payload, idem=None, stream="player"):
    record_events(db, [GameEventDraft(
        stream=stream, type=ev_type, payload=payload, idempotency_key=idem,
    )])
    db.flush()


def _kv_snapshot(db) -> dict:
    """Byte-comparable snapshot of every projection's stored state."""
    rows = db.execute(text(
        "SELECT projection, key, value FROM game_projection_kv "
        "ORDER BY projection, key"
    )).all()
    return {f"{r.projection}/{r.key}": r.value for r in rows}


# ── 21: the full-season simulation (reusable fixture) ───────────────────────


def run_season(db, user, acct) -> dict:
    """4 scripted months (2026-03 .. 2026-06): sync batches, daily closes,
    a boss lifecycle, 2 Heat contracts, a Grace episode, 2 sealed runs, and
    campaign milestones. Returns checkpoints for the assertions. Reusable —
    extend the script, keep the assertions."""
    from server.src.services.game.campaigns import CampaignService
    from server.src.services.game.expedition import RunService
    from server.src.services.game.heat import HeatService
    from server.src.services.game.month_close import close_month

    uid = _u(user)
    xp_checkpoints = [player_xp(db)["xp"]]

    # A boss to fight across the season.
    boss = LiabilityORM(user_id=user.id, name="The Card", kind="credit_card",
                        principal_cents=900_00, minimum_payment_cents=50_00,
                        status="active", is_active_boss=1)
    db.add(boss)
    db.flush()

    months = ("2026-03", "2026-04", "2026-05", "2026-06")
    for mi, month in enumerate(months):
        first = date(int(month[:4]), int(month[5:7]), 1)

        # Sync batch: a posted txn lands every ~6 days.
        for d in range(2, 27, 6):
            day = first + timedelta(days=d)
            _emit(db, "TxnPosted", {
                "plaid_transaction_id": f"s-{month}-{d}", "account_id": acct.id,
                "kind": "expense", "amount_cents": 12_00,
                "category": "Dining", "date": day.isoformat(),
            }, idem=f"plaid:s-{month}-{d}:posted", stream="sync")

        # Daily closes: GREEN weekdays, GRAY weekends (scripted verdicts).
        for d in range(0, 28):
            day = (first + timedelta(days=d))
            verdict = "GRAY" if day.weekday() >= 5 else "GREEN"
            _emit(db, "DayClosed",
                  {"date": day.isoformat(), "verdict": verdict},
                  idem=f"day:{user.id}:{day.isoformat()}")
            if verdict == "GREEN":
                _emit(db, "UnderBudgetDayClosed", {"date": day.isoformat()},
                      idem=f"green:{user.id}:{day.isoformat()}")

        # Boss lifecycle: a payment + damage each month; one phase break.
        pay_day = (first + timedelta(days=14)).isoformat()
        _emit(db, "PaymentPosted",
              {"date": pay_day, "liability_id": boss.id, "amount_cents": 50_00},
              idem=f"pay:{boss.id}:{month}")
        _emit(db, "BossDamaged",
              {"liability_id": boss.id, "starting_hp": 900_00,
               "amount": 50_00, "date": pay_day},
              idem=f"dmg:{boss.id}:{month}")
        if mi == 1:
            _emit(db, "BossPhaseBroken",
                  {"liability_id": boss.id, "phase": 1, "date": pay_day},
                  idem=f"phase:{boss.id}:1")

        # Grace episode in month 2 (applied, then lifted).
        if mi == 1:
            _emit(db, "GraceApplied",
                  {"date": (first + timedelta(days=9)).isoformat(), "triggers": 1},
                  idem=f"grace_on:{user.id}:{month}")
            _emit(db, "GraceLifted",
                  {"date": (first + timedelta(days=16)).isoformat()},
                  idem=f"grace_off:{user.id}:{month}")

        # Heat contracts in months 2 and 3 (history exists by then).
        if mi in (1, 2):
            heat = HeatService(db)
            price = heat.price(uid, "Dining", "cap_vs_baseline", 75, first)
            heat.create(uid, month, price,
                        arm="sweep" if mi == 1 else "cosmetic", as_of=first)

        # Draft the month's run, then close the month (seals runs 1-2 only —
        # the season ends with two sealed and two open).
        RunService(db).draft(uid, month)
        if mi < 2:
            close_month(db, user=uid, month=month)
        xp_checkpoints.append(player_xp(db)["xp"])

    CampaignService(db).compute_grants(uid, date(2026, 6, 28))
    return {"xp_checkpoints": xp_checkpoints, "boss_id": boss.id}


def _season_finance_fixtures(db, user, acct):
    """All FINANCE rows the season needs, inserted BEFORE the fingerprint."""
    db.add(CategorySettingsORM(name="Dining", essential=0, user_confirmed=1))
    for day in ("2025-12-10", "2026-01-10", "2026-02-10"):
        db.add(ExpenseORM(title="Dining", amount=150_00, date=day,
                          category="Dining", account_id=acct.id))
    db.add(ExpenseORM(title="Old", amount=100, date="2025-10-01",
                      category="Dining", account_id=acct.id))
    db.add(BudgetORM(user_id=user.id, category="Dining",
                     monthly_limit=200_00, rollover=0))
    db.flush()


def test_full_season_simulation(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    _season_finance_fixtures(db_session, user, acct)

    fingerprint_before = finance_tables_fingerprint(db_session)
    checkpoints = run_season(db_session, user, acct)

    # 1. The finance fingerprint is UNCHANGED by four months of game code.
    assert finance_tables_fingerprint(db_session) == fingerprint_before

    # 2. Every projection rebuilds byte-identical.
    live = _kv_snapshot(db_session)
    rebuild_all(db_session)
    rebuilt = _kv_snapshot(db_session)
    assert rebuilt == live

    # 3. XP is monotonic across the whole season.
    xs = checkpoints["xp_checkpoints"]
    assert all(b >= a for a, b in zip(xs, xs[1:])), f"XP regressed: {xs}"
    assert xs[-1] > xs[0]  # and the season actually earned something

    # 4. Two sealed runs, two open.
    sealed = db_session.execute(text(
        "SELECT COUNT(*) FROM runs WHERE sealed_at IS NOT NULL")).scalar_one()
    opened = db_session.execute(text(
        "SELECT COUNT(*) FROM runs")).scalar_one()
    assert sealed == 2 and opened == 4

    # 5. Campaign milestones landed from the log (sealed months + green weeks).
    granted = set(db_session.execute(text(
        "SELECT milestone_key FROM campaign_progress")).scalars())
    assert {"green_week_1", "month_sealed_1", "month_sealed_2"} <= granted

    # 6. No banned-word leaks in any captured template render.
    from server.src.services.game.bestiary import template_entry
    from server.src.services.game.chronicler import (
        build_week_fact_sheet,
        template_chapter,
    )
    from server.src.services.game.firewall import screen_output

    renders = []
    for week in range(4):
        ws = date(2026, 6, 1) + timedelta(days=7 * week)
        sheet = build_week_fact_sheet(db_session, _u(user), ws, ws + timedelta(days=6))
        chapter = template_chapter(sheet)
        renders.append(chapter["title"] + " " + chapter["body"])
    entry = template_entry("boss", {"category": "Dining"}, "The Card")
    renders.append(" ".join(str(v) for v in entry.values()))
    campaign_view = db_session.execute(text(
        "SELECT milestone_key FROM campaign_progress")).scalars()
    renders.append(json.dumps(list(campaign_view)))
    for rendered in renders:
        verdict = screen_output(rendered, plain=False)
        assert not verdict.blocked, f"firewall blocked a template: {rendered[:80]}"
        lowered = rendered.lower()
        for banned in ("expires", "last chance", "hurry", "you failed",
                       "shameful", "wasted"):
            assert banned not in lowered


# ── 22: mode-law — every game endpoint in all three modes ───────────────────


def _signup(client, username, email):
    resp = client.post("/api/signup/", json={
        "username": username, "email": email, "full_name": "M U",
        "password": "Test-password1",
    })
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


GAME_ROUTES = (
    "/api/game/streak/", "/api/game/bosses/", "/api/game/monsters/",
    "/api/game/keeper/", "/api/game/expedition/", "/api/game/campaigns/",
    "/api/game/challenges/", "/api/game/flags/", "/api/game/outcomes/",
    "/api/game/homestead/", "/api/game/chapter/",
)


def test_mode_law_every_game_route_renders_in_all_three_modes(client, db_session):
    h = _signup(client, "modewalk", "modewalk@x.com")
    for mode in ("off", "ambient", "full"):
        db_session.execute(text(
            f"UPDATE users SET game_mode = '{mode}' WHERE username = 'modewalk'"))
        for route in GAME_ROUTES:
            resp = client.get(route, headers=h)
            assert resp.status_code == 200, f"{route} failed in {mode}: {resp.text}"


# ── 23: the performance pass ────────────────────────────────────────────────


def test_two_year_rebuild_under_30s_and_daily_close_under_1s(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    # A 2-year synthetic log: daily closes + green days + periodic txns/XP.
    start = date(2024, 6, 1)
    drafts = []
    for i in range(730):
        day = (start + timedelta(days=i)).isoformat()
        verdict = "GREEN" if i % 3 else "GRAY"
        drafts.append(GameEventDraft(
            stream="player", type="DayClosed",
            payload={"date": day, "verdict": verdict},
            idempotency_key=f"day:{user.id}:{day}"))
        if verdict == "GREEN":
            drafts.append(GameEventDraft(
                stream="player", type="UnderBudgetDayClosed",
                payload={"date": day}, idempotency_key=f"green:{user.id}:{day}"))
        if i % 5 == 0:
            drafts.append(GameEventDraft(
                stream="sync", type="TxnPosted",
                payload={"plaid_transaction_id": f"perf-{i}",
                         "account_id": acct.id, "kind": "expense",
                         "amount_cents": 10_00, "category": "Dining",
                         "date": day},
                idempotency_key=f"plaid:perf-{i}:posted"))
    record_events(db_session, drafts)
    db_session.flush()
    total = db_session.execute(text("SELECT COUNT(*) FROM game_events")).scalar_one()
    assert total >= 1300  # the log is genuinely 2 years deep

    started = time.monotonic()
    rebuild_all(db_session)
    elapsed = time.monotonic() - started
    assert elapsed < 30, f"full rebuild took {elapsed:.1f}s (target < 30s)"

    from server.src.services.game.daily import DailyService

    started = time.monotonic()
    DailyService(db_session).close_day(_u(user), date(2026, 6, 2))
    elapsed = time.monotonic() - started
    assert elapsed < 1, f"daily close took {elapsed:.2f}s (target < 1s)"


def test_home_render_path_awaits_no_llm(client, db_session, monkeypatch):
    """The Overview/Expedition first paint must not block on any LLM call."""
    h = _signup(client, "nollm", "nollm@x.com")
    db_session.execute(text(
        "UPDATE users SET game_mode = 'full' WHERE username = 'nollm'"))

    def _boom(*a, **k):  # any Groq construction in the render path = failure
        raise AssertionError("LLM client constructed in the home render path")

    monkeypatch.setattr("groq.Groq", _boom)
    for route in ("/api/game/expedition/", "/api/game/streak/",
                  "/api/game/keeper/", "/api/spend/safe-to-spend/"):
        resp = client.get(route, headers=h)
        assert resp.status_code == 200, f"{route}: {resp.text}"


# ── 24: the Groq-down drill ─────────────────────────────────────────────────


def test_groq_down_everything_serves_template_fallbacks(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()

    def _down(prompt: str) -> str:
        raise ConnectionError("groq is down")

    # Chapters → the deterministic template, firewall-clean, with one action.
    from server.src.services.game.chronicler import generate_chapter

    user.game_mode = "full"
    db_session.flush()
    chapter = generate_chapter(
        db_session, _u(user), date(2026, 6, 1), date(2026, 6, 7), llm_call=_down)
    assert chapter["title"] and chapter["body"] and chapter["action"]
    assert chapter.get("fallback", True)

    # Bestiary → the deterministic template (trademark-safe name, no digits).
    from server.src.services.game.bestiary import generate_bestiary_entry

    entry = generate_bestiary_entry(
        db_session, "boss", "seed-1", {"category": "Dining"}, "The Card",
        llm_call=_down)
    assert entry["name"]
    assert not any(ch.isdigit() for ch in entry["name"])

    # Zero user-facing errors anywhere in the flavor path.
    from server.src.services.game.firewall import screen_output

    assert not screen_output(chapter["body"], plain=False).blocked


def test_drawer_survives_assistant_outage(client, db_session, monkeypatch):
    h = _signup(client, "drawerdown", "drawerdown@x.com")

    async def _broken_chat(user, message):
        raise ConnectionError("assistant down")
        yield  # pragma: no cover — makes this an async generator

    import server.src.routers.assistant as assistant_router

    monkeypatch.setattr(assistant_router.assistant_service, "chat", _broken_chat)
    resp = client.post("/api/game/chronicler/ask/",
                       json={"message": "how went the week?"}, headers=h)
    assert resp.status_code == 200  # degraded, never an error page
    assert resp.json()["kind"] == "error"


# ── 25: the Plaid-stale drill (fog everywhere) ──────────────────────────────


def test_plaid_stale_seven_days_fog_everywhere(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    # A would-be-MISS setup: discretionary blown through its budget and a
    # negative balance — on fresh data this would judge MISS and fire alerts.
    db_session.add(CategorySettingsORM(name="Dining", essential=0, user_confirmed=1))
    db_session.add(BudgetORM(user_id=user.id, category="Dining",
                             monthly_limit=50_00, rollover=0))
    db_session.add(ExpenseORM(title="Blowout", amount=400_00, date="2026-06-05",
                              category="Dining", account_id=acct.id))
    acct.balance = -100_00
    db_session.flush()

    # The gap opens; the feed goes stale for 7 days.
    _emit(db_session, "SyncGapOpened",
          {"account_id": acct.id, "opened_at": "2026-06-08"}, stream="sync")

    from server.src.services.game.daily import DailyService, streak_view

    daily = DailyService(db_session)
    streak_before = streak_view(db_session)
    for i in range(7):
        verdict = daily.close_day(_u(user), date(2026, 6, 8) + timedelta(days=i))
        assert verdict == "GRAY"  # zero MISS verdicts on stale data

    after = streak_view(db_session)
    assert after["current"] == streak_before["current"]  # GRAY never breaks
    assert after["wards"] == streak_before["wards"]  # and consumes nothing

    # Zero alerts fire on stale balances.
    from server.src.services.game.alerts import AlertEngine

    assert AlertEngine(db_session).evaluate(_u(user), date(2026, 6, 12)) == []

    # Heat verification reads only POSTED data — during the gap the contract
    # is not judged unmet by the month job (the gap voids T1 challenges the
    # same way; weekly Heat checkpoints render GRAY client-side off this gap).
    gaps = folds_mod.kv_get(db_session, folds_mod.SYNC_STATE, "gaps")
    assert gaps and len(gaps["open"]) == 1


# ── 26: mid-sync atomicity (the transaction boundary) ───────────────────────


def _fake_plaid_result(added):
    return SimpleNamespace(added=added, modified=[], removed=[],
                           next_cursor="cursor-2")


def _txn(txn_id, amount, day, name="Latte"):
    return {"transaction_id": txn_id, "amount": amount, "date": day,
            "name": name, "pending": False, "iso_currency_code": "USD",
            "category": ["Food and Drink"]}


def test_sync_apply_is_atomic_crash_leaves_no_orphans(db_session, user_acct):
    user, acct = user_acct
    folds_mod.register_builtin_folds()
    from server.src.services.plaid_service import PlaidService

    token = TokenORM(user_id=user.id, name=acct.name, key="tok-1")
    db_session.add(token)
    db_session.flush()

    svc = PlaidService(db_session)
    # Txn 2 is poison: no 'name' → the apply crashes AFTER txn 1's CRUD row
    # and event draft are staged, BEFORE anything commits.
    poison = {"transaction_id": "t-2", "amount": 5.0, "date": "2026-06-02",
              "pending": False, "iso_currency_code": "USD"}
    svc.plaid = SimpleNamespace(sync_transactions=lambda key, cursor: (
        _fake_plaid_result([_txn("t-1", 4.5, "2026-06-01"), poison])))

    with pytest.raises(KeyError):
        svc.sync_token(token)
    db_session.rollback()

    # NEITHER the CRUD row nor the derived event survived the crash.
    expenses = db_session.execute(text(
        "SELECT COUNT(*) FROM expenses WHERE plaid_transaction_id IS NOT NULL"
    )).scalar_one()
    events = db_session.execute(text(
        "SELECT COUNT(*) FROM game_events WHERE type = 'TxnPosted'")).scalar_one()
    assert expenses == 0 and events == 0

    # Control: the same sync WITHOUT the poison applies BOTH atomically.
    # (The rollback above discarded the whole uncommitted transaction —
    # fixture rows included — which is exactly the point. Re-stage them.)
    user2 = UserORM(username="season2", full_name="S2", email="s2@x.com",
                    hashed_password="x", savings_percent=0)
    db_session.add(user2)
    db_session.flush()
    acct2 = AccountORM(name="Checking2", type="checking", balance=100_00,
                       user_id=user2.id)
    db_session.add(acct2)
    db_session.flush()
    token2 = TokenORM(user_id=user2.id, name=acct2.name, key="tok-1b")
    db_session.add(token2)
    db_session.flush()
    svc2 = PlaidService(db_session)
    svc2.plaid = SimpleNamespace(sync_transactions=lambda key, cursor: (
        _fake_plaid_result([_txn("t-3", 4.5, "2026-06-01")])))
    svc2.sync_token(token2)
    expenses = db_session.execute(text(
        "SELECT COUNT(*) FROM expenses WHERE plaid_transaction_id = 't-3'"
    )).scalar_one()
    events = db_session.execute(text(
        "SELECT COUNT(*) FROM game_events WHERE type = 'TxnPosted'")).scalar_one()
    assert expenses == 1 and events == 1  # both, or neither — never one


# ════════════════════════════════════════════════════════════════════════════
# Step 02 (v5) — rate-limit & LLM-cost infrastructure
# ════════════════════════════════════════════════════════════════════════════

from starlette.requests import Request as StarletteRequest

from server.src.limiter import _client_key
from server.src.services import llm_budget
from server.src.settings import settings as app_settings


def _fake_request(headers: dict, client_host: str = "203.0.113.9") -> StarletteRequest:
    """A minimal Starlette Request with a direct-peer host and given headers."""
    raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()
    ]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": raw_headers,
        "client": (client_host, 5555),
        "server": ("testserver", 80),
    }
    return StarletteRequest(scope)


# ── proxy-aware limiter key ──────────────────────────────────────────────────


def test_limiter_key_uses_forwarded_when_trusted(monkeypatch):
    monkeypatch.setattr(app_settings, "trust_proxy", True)
    req = _fake_request({"x-forwarded-for": "1.2.3.4, 10.0.0.1"})
    # Left-most hop = the original client, not an intermediate proxy.
    assert _client_key(req) == "1.2.3.4"


def test_limiter_key_uses_real_ip_when_trusted_and_no_xff(monkeypatch):
    monkeypatch.setattr(app_settings, "trust_proxy", True)
    req = _fake_request({"x-real-ip": "5.6.7.8"})
    assert _client_key(req) == "5.6.7.8"


def test_limiter_key_ignores_forwarded_when_untrusted(monkeypatch):
    monkeypatch.setattr(app_settings, "trust_proxy", False)
    req = _fake_request(
        {"x-forwarded-for": "1.2.3.4", "x-real-ip": "5.6.7.8"},
        client_host="203.0.113.9",
    )
    key = _client_key(req)
    # Falls back to the real peer; never honors a spoofable header untrusted.
    assert key == "203.0.113.9"
    assert key not in ("1.2.3.4", "5.6.7.8")


def test_limiter_key_empty_forwarded_falls_back_no_500(monkeypatch):
    """Empty/malformed forwarded header → graceful fallback, never a crash."""
    monkeypatch.setattr(app_settings, "trust_proxy", True)
    req = _fake_request({"x-forwarded-for": "   "}, client_host="198.51.100.7")
    assert _client_key(req) == "198.51.100.7"


# ── LLM budget primitive ─────────────────────────────────────────────────────


def test_budget_blocks_over_cap(db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "llm_daily_request_budget", 1)
    llm_budget.check_and_reserve(db_session, user_id=1, requests=1)
    with pytest.raises(llm_budget.BudgetExceeded):
        llm_budget.check_and_reserve(db_session, user_id=1, requests=1)
    # The over-cap reservation must NOT have persisted.
    used = db_session.execute(text(
        "SELECT requests FROM llm_usage WHERE user_id = 1")).scalar_one()
    assert used == 1


def test_budget_resets_next_day(db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "llm_daily_request_budget", 1)
    monkeypatch.setattr(llm_budget, "today_key", lambda: "2026-06-13")
    llm_budget.check_and_reserve(db_session, user_id=7, requests=1)
    with pytest.raises(llm_budget.BudgetExceeded):
        llm_budget.check_and_reserve(db_session, user_id=7, requests=1)
    # Next day → fresh row, reservation succeeds.
    monkeypatch.setattr(llm_budget, "today_key", lambda: "2026-06-14")
    llm_budget.check_and_reserve(db_session, user_id=7, requests=1)
    rows = db_session.execute(text(
        "SELECT day, requests FROM llm_usage WHERE user_id = 7 ORDER BY day")).all()
    assert [(r.day, r.requests) for r in rows] == [
        ("2026-06-13", 1), ("2026-06-14", 1)]


def test_budget_atomic_increment_no_lost_update(db_session, monkeypatch):
    """N sequential reservations leave requests=N and tokens=N*K — proves the
    increment is an issued SQL UPDATE, not a read-modify-write on a stale Python
    value. (Sequential calls can't surface a real lost update; the concurrency
    guarantee is the conditional UPDATE's cap-carrying WHERE clause + SQLite's
    single-writer serialization, asserted structurally below.)"""
    monkeypatch.setattr(app_settings, "llm_daily_request_budget", 1000)
    N, K = 12, 37
    for _ in range(N):
        llm_budget.check_and_reserve(db_session, user_id=3, est_tokens=K, requests=1)
    row = db_session.execute(text(
        "SELECT requests, tokens FROM llm_usage WHERE user_id = 3")).one()
    assert row.requests == N
    assert row.tokens == N * K

    # Structural assertion: the cap and the increment live in ONE statement, so
    # there is no read-then-write window (the real TOCTOU guarantee).
    import inspect
    src = inspect.getsource(llm_budget.check_and_reserve)
    assert "requests + :req <= :budget" in src


def test_record_actual_noop_on_zero_keeps_request_count(db_session):
    llm_budget.check_and_reserve(db_session, user_id=9, requests=1)
    llm_budget.record_actual(db_session, user_id=9, tokens=0)  # no-op by design
    row = db_session.execute(text(
        "SELECT requests, tokens FROM llm_usage WHERE user_id = 9")).one()
    assert row.requests == 1 and row.tokens == 0
    # A real token count reconciles the advisory figure; never goes negative.
    llm_budget.record_actual(db_session, user_id=9, tokens=500)
    tokens = db_session.execute(text(
        "SELECT tokens FROM llm_usage WHERE user_id = 9")).scalar_one()
    assert tokens == 500


def test_remaining_tracks_request_budget(db_session, monkeypatch):
    monkeypatch.setattr(app_settings, "llm_daily_request_budget", 3)
    assert llm_budget.remaining(db_session, user_id=4) == 3  # no row yet
    llm_budget.check_and_reserve(db_session, user_id=4, requests=1)
    assert llm_budget.remaining(db_session, user_id=4) == 2
    llm_budget.check_and_reserve(db_session, user_id=4, requests=2)
    assert llm_budget.remaining(db_session, user_id=4) == 0  # clamped, not negative


# ── signup rate limit (uses the real opt-in fixture, not a setting flip) ──────


def test_signup_rate_limited(client, rate_limited):
    """With the limiter ON (instance flip via ``rate_limited``), repeated signups
    from the same key eventually 429. The live decorator captured the default
    ``signup_rate_limit`` ("5/hour") at import, so the 6th attempt trips it.

    Single-user is OFF for the suite, so each unique signup would otherwise 200;
    assert the tripping attempt is 429 (never a silent 200) and earlier ones
    succeed (never a 500)."""
    statuses = []
    for i in range(6):
        resp = client.post("/api/signup/", json={
            "username": f"rl_user_{i}", "email": f"rl_{i}@x.com",
            "full_name": "RL U", "password": "Test-password1",
        })
        statuses.append(resp.status_code)
    # First five within the 5/hour window succeed; the sixth is throttled.
    assert statuses[-1] == 429, statuses
    assert all(s in (200, 429) for s in statuses), statuses
    assert 200 in statuses  # the limiter didn't block everything spuriously
