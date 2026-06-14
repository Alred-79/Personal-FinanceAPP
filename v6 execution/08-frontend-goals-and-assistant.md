# 08 — Goals entry + shared ConfirmCard + assistant unlock

> Sequential execution doc 8 of 8. Requires docs 01-07 green. Finishes the feature.

## Context
Finish the weave: a per-goal "What if…" entry on Goals, the shared `ConfirmCard` (net-new — the chat
has no confirm UI today, verified), and the assistant `proposal` frame so users can drive what-if in
chat. The propose→confirm BACKEND already exists; the client confirm card, the new SSE `proposal` frame,
**and a net-new what-if LLM tool** are new.

**Premise correction:** there is no "locked" what-if tool to unlock. The LLM tool list in
`assistant_service.py` (`AddTransactionTool`, `AddGoalTool`, `RecategorizeTransactionTool`, the read
tools, etc.) has NO what-if tool. The dead `whatif_commit`/`create_allocation` branches are
confirm-flow ACTION handlers, not LLM tools. So task 4 below builds a **net-new tool class** added to
that list — it is creation, not an unlock. (The `scenario_commit` ACTION is the thing that gets
unlocked, and that happens in doc 05, not here.)

## Tasks (test-first)
1. **`client/src/components/custom/ConfirmCard/ConfirmCard.tsx`** (new, shared by chat + Forecast +
   Goals): renders `summary` + Approve / Decline; Approve POSTs `{token}` to
   `/assistant/actions/confirm/` (reuse the existing 401→`refreshAuth()`→retry path); success shows a
   `Seal tone="approved"`. Test: `client/src/__tests__/components/ConfirmCard.test.tsx` (Approve hits
   confirm + shows seal; Decline dismisses without a POST).
2. **Goals page** (`client/src/pages/Goals/Goals.tsx`): a "What if…" button in the certificate footer
   → `useNavigate('/forecast?goal=<id>')` (Forecast pre-seeds a goal mutation from doc 07). Test: button
   navigates with the goal id.
3. **Assistant** (`client/src/components/custom/AssistantInterface/AssistantInterface.tsx`): handle a new
   `event: "proposal"` SSE frame `{action, summary, confirm_token, diff?}`; render an inline diff card
   (AnimatedNumber + `Sparkline`) + the shared `ConfirmCard`; a "View on Forecast" link deep-links
   `/forecast?scenario=<id>`. Test: `client/src/__tests__/components/AssistantInterface.test.tsx` feeds a
   mocked proposal frame; Approve hits the confirm endpoint.
4. **Server**: add a **net-new what-if LLM tool** to the tool list in
   `server/src/services/assistant_service.py` (alongside `AddGoalTool` etc., same class shape) that builds
   a scenario overlay, runs `ScenarioService.evaluate`, and returns the diff + a `scenario_commit`
   proposal token (the action itself is unlocked in doc 05); the streaming path in
   `server/src/services/assistant_service.py` / `server/src/routers/assistant.py` emits the new
   `proposal` SSE frame (the chat today emits only `crisis`/`token`/`tool`/`done`, verified — `proposal`
   is new). Do NOT touch the firewall or the propose→confirm token model.

## Verification checks
- [ ] `npx vitest run client/src/__tests__/components/ConfirmCard.test.tsx client/src/__tests__/components/AssistantInterface.test.tsx` → green.
- [ ] Backend: `./.venv/bin/pytest server/tests/test_assistant_writes.py server/tests/test_assistant_security.py -q` → green (firewall + propose/confirm intact).
- [ ] Full frontend: `npx vitest run` → green (nav / game-mode snapshots unchanged).
- [ ] Full backend: `./.venv/bin/pytest -q` → green (all prior tests + every test added across docs
      01–08; the v6-start baseline was exactly 863, so the live count is well above it by now).
- [ ] Manual smoke (end to end): create a scenario → evaluate → commit via propose→confirm → confirm a
      Rule + PlanOfRecord + WhatIfCommitted event exist → open Forecast, see the overlay → ask the chat
      "what if I get a $5k raise?" and approve the ConfirmCard.

## Risks
- The `ConfirmCard` is the only large net-new UI; build it first in this doc, then reuse at all three
  call sites.
- Keep the assistant firewall + propose→confirm token model untouched — only add the `proposal` frame
  and unlock the action.
