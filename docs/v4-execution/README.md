# v4 Execution Plan — sequential work packages

This folder breaks [../v4.md](../v4.md) into **10 work packages, executed strictly in order**
(01 → 10). Each file is self-contained: context recap, preconditions, scope, step-by-step tasks,
guardrails, test cases, and exit criteria. **Do not start a file until the previous file's exit
criteria all pass.**

| # | File | Delivers | v4 sections |
| --- | --- | --- | --- |
| 01 | [01-preflight-and-event-substrate.md](./01-preflight-and-event-substrate.md) | v1-dependency gate; event log, folds, corrections, rebuild tooling | §3, §12 |
| 02 | [02-game-mode-system.md](./02-game-mode-system.md) | Off/Ambient/Full as one end-to-end variable; visual foundation | §10.2, §11 |
| 03 | [03-money-spine.md](./03-money-spine.md) | Glanceable number, action-moment alerts, what-if commit, graduation rail | §5 |
| 04 | [04-stat-engine-and-keeper-sheet.md](./04-stat-engine-and-keeper-sheet.md) | Baselines, stats, XP hygiene, character sheet | §6.1 |
| 05 | [05-daily-skeleton.md](./05-daily-skeleton.md) | Streaks/wards/revival, daily verb, overnight tick, basic Grace | §6.2–6.3, §9.1 |
| 06 | [06-debt-boss.md](./06-debt-boss.md) | Liability, closure-framed boss, habit monsters, juice, closure card | §7.1 |
| 07 | [07-chronicler-and-saga.md](./07-chronicler-and-saga.md) | REPL overlay, canon, advice firewall, weekly saga chapter, daily beat | §7.4, §8.1–8.5 |
| 08 | [08-expedition.md](./08-expedition.md) | Forecast→month-map, draft, fog, run scoring, two-homes IA | §7.2, §10.1 |
| 09 | [09-heat-grace-homestead.md](./09-heat-grace-homestead.md) | Self-funding Heat, full Grace, Homestead clocks, bestiary, regret-monster | §6.4–6.5, §8.2 |
| 10 | [10-campaigns-experiments-hardening.md](./10-campaigns-experiments-hardening.md) | Campaigns, challenges, fade, holdout/experiments, final hardening | §7.3, §8.6, §9.4, §13 |

**MVP = packages 01–07.** Packages 08–10 only start if the MVP exit metrics are green.

## Global rules (apply to every package — re-read before each one)

### The Three Laws (short form; full text v4 §3)
1. **The fold:** `game_state = fold(event_stream)`. Game code NEVER writes to financial truth
   (accounts, transactions, balances, budgets, goals). Game tables are rebuildable projections.
2. **Two layers:** the deterministic engine computes every number and awards every XP. LLM output
   is flavor/judgment only and NEVER feeds engine state.
3. **The charter:** XP only on verified financial actions (never opens/checks/taps/logging); XP
   never decreases; no celebration of transactions or near-misses; no variable-ratio rewards on
   money actions; no fictional money and no trivial-sum money theater; data errors resolve
   pro-player; notifications never nudge a transaction; nothing is ever purchasable.

### Working rules for the executing agent
- **Run the full test suite before starting a package** (regression gate) and after finishing it.
  A package is done only when ALL tests — new and old — pass.
- **Additive migrations only.** Never drop or rename existing columns/tables. Never edit an
  applied Alembic migration; add a new one.
- **Inspect before assuming.** Before touching any existing model/service, read it. File paths in
  these docs were verified at plan time but the codebase moves; if a named symbol doesn't exist,
  STOP and search for its replacement rather than creating a duplicate.
- **STOP conditions** (stop and report rather than improvise): a precondition fails; a task
  requires writing to a financial-truth table; a task seems to require violating a Law or an
  anti-feature (v4 §14); two consecutive attempts to fix the same failing test have failed.
- **No scope creep.** Each file has an explicit OUT OF SCOPE list. Things listed there are
  handled by a later package — do not build them early, even partially.
- **Conventions:** backend tests in `server/tests/test_game_*.py` (pytest, fixtures over mocks
  where a real SQLite tmp DB works); frontend tests in `client/src/__tests__/` (vitest). Run
  backend tests from repo root with the project venv. Use plain, descriptive test names.
- **The DB lives on the local tree only.** Never point SQLite (or its `-wal`/`-shm` files) at the
  OneDrive copy of this project. (WAL mode is incompatible with network filesystems.)
- Copy that users see goes through the term catalog (after package 02) — no hardcoded game
  vocabulary in components.

### Definition of done (every package)
- [ ] All new tests listed in the file exist and pass.
- [ ] Full pre-existing suite still passes (`pytest` + `npx vitest run`).
- [ ] No new writes to financial-truth tables from game code (verify with the Law-1 integrity
      test from package 01 — it runs in every package).
- [ ] Exit criteria checklist at the bottom of the file is fully checked.
- [ ] A short handoff note is appended at the bottom of the executed file: what was built, any
      deviations, anything the next package must know.
