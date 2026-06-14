# 03 — Persistence + CRUD + router

> Sequential execution doc 3 of 8. Requires docs 01-02 green.

## Context
Saved/named/comparable scenarios need two tables, ORM + Pydantic, a `ScenarioService` CRUD layer, a
`/scenarios` router, and registration. All money inside `overlay_json` is integer cents.

## Tasks (test-first)
1. **Migration `server/migrations/versions/<hex>_scenarios_and_plan_of_record.py`**,
   `down_revision="b1c2d3e4f5a6"` (re-confirm `./.venv/bin/alembic heads` FIRST — head may have moved).
   Tables:
   - `scenarios(id, user_id FK users CASCADE, name NOT NULL, overlay_json String default "{}",
     created_at, updated_at)` + `ix_scenarios_user`.
   - `plans_of_record(id, user_id FK users CASCADE, scenario_id FK scenarios SET NULL nullable,
     rule_ids_json default "[]", baseline_snapshot_json NOT NULL, status default "active",
     committed_at, last_checked_at nullable)` + `ix_plans_of_record_user`.
   - No top-level money cols (money lives in JSON as cents). FKs `ondelete` set, timestamps via
     `sa.text("CURRENT_TIMESTAMP")`.
2. **ORM in `server/src/db/models.py`**: `Scenario`, `PlanOfRecord` matching the migration.
3. **Pydantic in `server/src/models.py`** (dollar floats at boundary; the service converts):
   `ScenarioOverlayIn` (dollar amounts), `ScenarioIn(name, overlay)`, `ScenarioOut`,
   `ScenarioCompareIn(scenario_ids, horizon_days)`. Follow the existing `RuleIn` style + `_MONEY`
   validators.
4. **`server/src/services/scenario_service.py`** CRUD: `create/list/get/update/delete/load_overlay`,
   all ownership-scoped (`user_id`); `overlay_to_json`/`overlay_from_json` at the boundary; dollar→cents
   conversion on the way in.
5. **`server/src/routers/scenarios.py`**: `POST/GET /scenarios/`, `GET/PUT/DELETE /scenarios/{id}/`,
   `Depends(AuthService.get_current_active_user)` + `Depends(get_db)` like forecast.py/rules.py.
   Register in `server/src/main.py`.
6. **`server/tests/test_scenario_api.py`**: CRUD happy path; ownership (other user's id → 404);
   overlay dollar→cents conversion on create; round-trip on get.

## Verification checks
- [ ] `./.venv/bin/alembic upgrade head` succeeds; `./.venv/bin/alembic heads` shows the new head;
      `./.venv/bin/alembic downgrade -1` is clean (then `upgrade head` again).
- [ ] `./.venv/bin/pytest server/tests/test_scenario_api.py -q` → green.
- [ ] `./.venv/bin/pytest server/tests/test_smoke.py -q` (app imports + router registered) → green.

## Risks
- **R6 (migration head):** re-confirm `alembic heads` before writing `down_revision`.
- Cents/dollars conversion guarded by the create+get round-trip test.
