from pydantic_settings import BaseSettings
from pydantic import model_validator
from functools import lru_cache

# Placeholder/dev secrets that must never reach production. The JWT secret is the
# HKDF master for every token family (session / assistant_action / mcp) and the
# default Plaid Fernet key, so a weak value compromises the whole token + at-rest
# crypto surface at once.
_WEAK_JWT_SECRETS = frozenset(
    {"", "secret", "changeme", "change-me", "dev", "development", "test", "password"}
)
_MIN_JWT_SECRET_LEN = 32


class Settings(BaseSettings):
    groq_api_key: str
    jwt_secret_key: str
    jwt_algorithm: str
    # L3 — token isolation rollout. Each token family (session / assistant_action /
    # mcp) now signs with an HKDF-derived per-purpose key and carries a distinct
    # ``aud``. Short-lived families enforce ``aud`` immediately. SESSION tokens
    # roll out with a grace window: while this is False, verification ALSO accepts
    # a legacy access token (signed with the raw secret, no ``aud``) so in-flight
    # logins survive the deploy. Flip to True once all legacy access tokens have
    # expired (>= access_token_expire_minutes after deploy) to hard-enforce.
    jwt_require_aud: bool = False
    tavily_api_key: str
    plaid_client_id: str
    plaid_client_secret: str
    plaid_environment: str
    # L1 — inbound webhooks. The publicly reachable HTTPS URL Plaid POSTs webhooks
    # to (e.g. https://<host>/api/plaid/webhook). When set, it's registered on the
    # item at link time; when None (local dev — Plaid can't reach localhost) the
    # app stays poll-only and the webhook endpoint simply receives nothing.
    plaid_webhook_url: str | None = None
    # Rate limit for the public webhook endpoint (Plaid can burst; bounds abuse).
    plaid_webhook_rate_limit: str = "120/minute"
    # --- Plaid access-token encryption at rest (Step 08) ---
    # The Plaid access token grants read access to the user's real bank, so it
    # is encrypted (Fernet) before it touches the DB. Supply an explicit Fernet
    # key (urlsafe-base64, 32 bytes) here to rotate independently of the JWT
    # secret; when unset, the key is derived deterministically from
    # ``jwt_secret_key`` so single-user/dev deployments encrypt with no extra
    # config (see server/src/services/plaid_crypto.py).
    plaid_token_key: str | None = None
    # Retired Plaid token keys kept for DECRYPTION ONLY during a graceful key
    # rotation (L6). Comma-separated urlsafe-base64 Fernet keys. New ciphertext is
    # always written with the active ``plaid_token_key``; rows still encrypted
    # under an old key decrypt via this list until the one-shot re-encrypt command
    # (``python -m server.src.services.plaid_reencrypt``) migrates them forward.
    plaid_token_keys_retired: str | None = None
    # Once the one-shot plaintext→ciphertext migration has run everywhere, flip
    # this on to HARD-FAIL on any un-prefixed (legacy plaintext) Plaid token at
    # decrypt time instead of returning it verbatim — closes the legacy path so a
    # plaintext token can never be silently used post-migration. Default off to
    # preserve the half-migrated tolerance during rollout.
    plaid_require_encrypted_tokens: bool = False
    database_url: str = "sqlite:///finance_tracker.db"

    # --- Auth and cookie hardening ---
    environment: str = "development"  # either "development" or "production"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    cookie_domain: str | None = None  # leave as None to let the browser figure it out

    # --- Single-user instance (Step 01) ---
    # This is a one-account instance. ``single_user=True`` means registration
    # closes after the first account exists: the signup guard 409s any second
    # /signup/. ``allow_signup`` is a master switch — set it False to disable
    # registration entirely (the very first signup 403s too), independent of
    # single_user. The cross-user test corpus flips single_user=False so its
    # two-user IDOR flows keep working; the guard's own tests opt back in.
    single_user: bool = True  # one-account instance; blocks a 2nd signup
    allow_signup: bool = True  # master switch; first signup still allowed when single_user

    # CORS: which origins are allowed to send credentialed requests.
    # Set this in env as a JSON array: ALLOWED_ORIGINS=["https://app.example.com"]
    allowed_origins: list[str] = ["http://localhost:5173"]

    # v4 package 10 — kill switches. A comma-separated list of game features
    # whose UI is hidden and whose jobs are paused (e.g. "heat,bestiary").
    # Config, never schema: killing a feature must not require a migration,
    # and folds/rebuilds stay intact (events keep their meaning).
    killed_features: str = ""

    # Step 09 — the production game scheduler (APScheduler). Started in the
    # FastAPI lifespan; runs month-close/rollups/fade/graduation on cron
    # triggers so the game features that have live UI aren't permanently empty.
    # ⚠ FALSE in the test suite (conftest) so no background fire is non-
    # deterministic — tests drive ``scheduler.run_due_game_jobs`` directly.
    # ⚠ SINGLE-WORKER INVARIANT (shared with Steps 02/05): an AsyncIOScheduler
    # starts once PER worker process. >1 uvicorn worker double-fires every job
    # at the boundary. Idempotency keeps a double-fire harmless in OUTCOME but
    # it doubles work and is fragile — run ONE worker until a leader-elected /
    # external trigger exists (production backlog). Enforced at startup in
    # main.py and documented in docs/v5 execution.
    scheduler_enabled: bool = True
    # Multi-worker seam for the single-worker scheduler invariant above. With >1
    # worker, set this False on every worker except one so jobs schedule once
    # cluster-wide instead of once per worker. This is a static gate; the real
    # implementation later is leader election (e.g. a Postgres
    # ``pg_try_advisory_lock``). Default True = current single-worker behavior.
    scheduler_leader: bool = True
    # WS2 — Row-Level Security tenant isolation (Postgres only). Master switch.
    # Default False so the SQLite dev/CI suite is a pure no-op (set_tenant /
    # enable_rls already no-op on SQLite, the create_all RLS listener self-skips,
    # and the enable_rls migration installs no policies). A Postgres deployment
    # opts IN by setting enable_rls=true — at which point the app MUST connect as
    # a non-superuser role and every request sets the tenant (both wired
    # automatically). Read fresh off the singleton so tests can monkeypatch it.
    # See server/src/db/rls.py and docs/MULTI-TENANT-DO-NOW.md.
    enable_rls: bool = False
    # WS2 — optional separate DB URL for the in-process scheduler. APScheduler runs
    # in the app process, so its all-users batch jobs use the app's connection. With
    # enable_rls=true the app connects as a NON-superuser (so RLS enforces requests),
    # but those jobs must NOT be tenant-filtered. Point this at a BYPASSRLS / owner
    # role URL so the scheduler bypasses RLS without per-job set_tenant. None
    # (default) = reuse the app engine (correct whenever enable_rls is off).
    scheduler_database_url: str | None = None
    # The Detangler's nightly pass (transfer/refund/duplicate flagging). On by
    # default; the per-pair notification dedup makes a re-fire harmless. Disable
    # to silence the nightly job without affecting the on-demand endpoint.
    detangle_enabled: bool = True
    # L4 — how far back the detangle + anomaly scans FETCH candidate transactions.
    # Both used to load a user's ENTIRE history and pair/compare O(n²); a transfer/
    # refund/duplicate (and a fresh anomalous charge) is always recent, so bounding
    # the fetch to a recent window keeps the scans ~linear without changing what
    # they find for recent activity. 0 disables the window (scan all — legacy).
    detangle_scan_window_days: int = 90
    anomaly_scan_window_days: int = 365  # a year of history for a stable "normal"

    # L4 — notification retention. The nightly sweep deletes READ notifications
    # older than this many days (unread/actionable rows are NEVER deleted), and
    # caps total rows per user. Keeps the table from growing linearly forever
    # (e.g. one anomaly row per anomalous txn). 0 disables retention.
    notification_retention_enabled: bool = True
    notification_retention_days: int = 90
    notification_retention_max_per_user: int = 500

    # F3 — the nightly Auditor. Composes the detector battery (anomalies, budget
    # overruns, F1 overdraft risk, F2 zombie subs / price creep) into one deduped,
    # ranked, capped, narrated batch of notifications. OFF by default; the per-ref
    # dedup makes a re-fire harmless. The narration is screened by the advice
    # firewall and cached in LlmCache (the chronicler pattern). Runs once per
    # worker (single-worker invariant) after plan_drift + detangle.
    auditor_enabled: bool = False
    # Alert-fatigue guard: max NEW auditor-specific findings (overdraft / lifecycle
    # / price-creep) surfaced per nightly run, ranked by severity. The user's
    # attention is the scarce resource, not the (detector-cheap) compute.
    auditor_max_findings: int = 8
    # Calibrated overdraft probability at/above which the Auditor raises a notice.
    auditor_overdraft_threshold: float = 0.25

    # F2 — the Merchant Lifecycle Engine (pooled BG/NBD over the user's payees).
    # OFF by default: it carries the heaviest dependency in the analytical layer
    # (PyMC), so the fit runs only in F3's nightly batch (never a request path)
    # and only when enabled. When OFF: the nightly fit self-skips, the
    # Subscriptions API omits lifecycle fields, and the Auditor emits no
    # lifecycle/price-creep notices. The deterministic price-creep comparison
    # rides along with the fit (it needs the same snapshot home).
    merchant_lifecycle_enabled: bool = False
    # Horizon (days) for the BG/NBD expected-purchases figure.
    merchant_lifecycle_horizon_days: int = 30
    # Trailing window (days) of charges fed to the fit — generous so annual
    # renewals can show ≥ 2 occurrences.
    merchant_lifecycle_lookback_days: int = 730

    # Pillar 3 — the tax & messy-data layer (tax-bucket tagging, tax-document
    # ingestion, tax-summary/estimate engine, quarterly reminders). OFF by
    # default: the feature ships behind this flag, gated on the measured firewall
    # block-rate of the tax-narration post-processor (see
    # ``services/tax/narration.py`` + ``tests/test_tax_firewall_spike.py``), not
    # just "tests pass". When OFF: the tax agent tools are not registered, the
    # tax router 404s on writes, and the quarterly-reminder job self-skips. The
    # output advice firewall is unaffected (it always runs).
    tax_features_enabled: bool = False

    # W4 — Reconciliation→planning feedback loop (reflection + automation offers).
    # A nightly job aggregates each user's AssistedAction follow-through, writes
    # ONE non-directive ``action_followthrough`` memory fact (firewall-screened),
    # and surfaces ≤1 idempotent ``create_rule`` (allocate) automation offer per
    # repeated verified pattern. OFF by default (ship-dark, guardrail B4): the job
    # no-ops when this is False. Propose-only — nothing auto-moves money (B2).
    assistant_reflection_enabled: bool = False
    # Trailing window (days) of AssistedAction history the reflection job reads.
    reflection_window_days: int = 90
    # Minimum verified repeats of a (kind, goal, ~amount) pattern before an
    # automation offer is surfaced.
    reflection_min_repeats: int = 3

    # W5 — Freelancer wedge. Composes the calibrated Safe-to-Spend (F1) with the
    # tax layer into a 1099 onboarding preset: a self-employment-only income buffer
    # recommendation + a Tax Reserve goal funded as self-employment income arrives
    # (a C1 allocate rule) + the existing quarterly due-date reminders. OFF by
    # default (ship-dark, guardrail B4): the preset only runs when explicitly
    # invoked. Propose-only — nothing auto-moves money beyond the C1 under-threshold
    # earmark, and the buffer recommendation is one-tap accept, never auto-applied.
    freelancer_mode_enabled: bool = False

    # W6 — Honest subscription cancellation. A nightly job reads each user's F2
    # ``MerchantLifecycle`` rows, surfaces ≤1 idempotent honest cancel OFFER per
    # likely-forgotten ("zombie") or silently-hiked subscription, and ABSENCE-
    # verifies a tapped cancel Bridge (it's confirmed only after the next expected
    # charge fails to appear for a full cadence + grace). OFF by default (ship-dark,
    # guardrail B4): the job no-ops when this is False. Propose-only (B2) — the
    # offer never cancels anything, never moves money, and there is NO fee anywhere
    # on this path.
    subscription_actions_enabled: bool = False
    # A ``lapsing``/``dormant`` merchant counts as a forgotten-subscription cancel
    # candidate only when its BG/NBD ``probability_alive`` is below this (a positive
    # ``price_change_pct`` qualifies independently of probability).
    subscription_forgotten_max_probability: float = 0.35

    # W7 — Behavioral features (Tier-1, evidence-graded behavioral-moat F1/F2/F4/F6).
    # FOUR independently-flagged nudges, each forecast-gated so a nudge can never push
    # a user negative, all OFF by default (ship-dark, guardrail B4). All copy is
    # factual / non-directive and screened through the output firewall (B3).
    #
    # F1 — Goal-named reminders. A nightly job names the user's actual goal + its real
    # progress; cadence-capped to ≤``behavioral_reminder_max_per_week`` reminders/week
    # per goal, and suppressed entirely once the user mutes goal reminders. No-op when
    # this flag is off.
    behavioral_goal_reminders_enabled: bool = False
    # Cadence cap: at most this many goal-named reminders per goal per rolling 7 days.
    behavioral_reminder_max_per_week: int = 1
    # Only nudge a goal the user has actually funded but not touched recently — a goal
    # with no progress activity in this many days is "stalled" and reminder-eligible.
    behavioral_reminder_stale_days: int = 7

    # F2 — Save-More-Tomorrow escalation. A monthly job bumps an opt-in ``allocate``
    # rule's ``pct``/``amount`` by a configured step, but ONLY when the forecast says
    # the bumped contribution would NOT push the user negative (the hard forecast veto).
    # Trivially pausable: an escalation is opt-in per rule (``action_params.escalation``)
    # and disabling the rule or clearing the escalation block stops it. No-op when off.
    behavioral_escalation_enabled: bool = False
    # The forecast horizon (days) the escalation veto projects over before a bump.
    behavioral_escalation_horizon_days: int = 35

    # F4 — Soft goal earmarks. A named sub-bucket per goal that sits OVER ``Goal.progress``
    # (it reduces Safe-to-Spend exactly like progress) but is NEVER a hard lock: a
    # pull-back is always allowed, instant, and carries no penalty. The service warns
    # (never blocks) when the forecast sees a near-term bill. The earmark surface is
    # gated by this flag. No-op when off.
    behavioral_earmarks_enabled: bool = False

    # F6 — Landmark re-entry. A month/year-boundary job sends ONE gentle, non-directive
    # re-entry notification to LAPSED users only (no money activity in
    # ``behavioral_lapsed_days`` days), never to engaged users — and it NEVER touches the
    # streak machine (daily.py already rebuilds rather than breaks). No-op when off.
    behavioral_landmark_enabled: bool = False
    # A user with no expense/income activity in this many days is "lapsed" (re-entry
    # eligible). Engaged users (recent activity) are skipped — the "what-the-hell"
    # licensing guard.
    behavioral_lapsed_days: int = 30

    # W8 — Neurodivergent mode. Positions the real strength (no-break streaks +
    # grace + no-shame) for an underserved segment. When ON it (a) widens Grace's
    # deterministic generosity so a hard month is detected sooner / more leniently
    # (``grace.widened_params``), (b) lowers reminder frequency/noise, and (c)
    # tells the CLIENT to default to the single "one thing today" surface.
    #
    # SHIP-DARK (B4): default False. The ``GET /next-action/`` endpoint ALWAYS
    # works regardless of this flag — only the client defaulting to the single
    # surface and the grace widening are gated by it. The grace widening SOFT-LANDS
    # (eases targets earlier); it NEVER voids a challenge verdict.
    neurodivergent_mode: bool = False
    # How much more generous Grace's triggers get under neurodivergent mode. The
    # income floor ratio rises (a smaller dip in income still triggers easing) and
    # the negative-balance horizon lengthens (a shortfall further out still
    # triggers easing). These widen the SOFT-LAND, never disabling any verdict.
    neurodivergent_grace_income_floor_ratio: float = 0.85  # vs 0.70 baseline
    neurodivergent_grace_horizon_days: int = 21  # vs 14 baseline
    neurodivergent_grace_essential_shock_multiple: float = 1.5  # vs 2.0 baseline

    # Rate limiting via slowapi. We turn it off in the test suite so repeated
    # login and refresh calls don't trip the limiter.
    #
    # NOTE on toggling (Step 02): slowapi captures ``enabled`` at ``Limiter(...)``
    # construction time and checks the *instance* attribute per request — it never
    # re-reads this setting. So flipping ``rate_limit_enabled`` at runtime (e.g.
    # via monkeypatch) does NOT reach the live limiter. Tests must flip
    # ``limiter.enabled`` on the instance instead (see the ``rate_limited``
    # fixture in conftest). Contrast ``mcp_rate_limit_enabled``, which the MCP
    # throttle DOES read fresh per request.
    rate_limit_enabled: bool = True
    # Storage backend for the slowapi/``limits`` rate limiter. ``memory://`` is
    # per-process (the single-worker invariant). The multi-worker seam: set this
    # to ``redis://host:6379`` and every worker shares one counter — a config
    # change only, no code change. See server/src/limiter.py.
    ratelimit_storage_uri: str = "memory://"
    login_rate_limit: str = "5/minute"
    refresh_rate_limit: str = "10/minute"
    # Receipt scanning calls the paid Groq vision API, so it gets a limit too.
    receipt_scan_rate_limit: str = "20/minute"
    # Statement / document import (Reconciliation Desk) also calls the paid Groq
    # vision/chat API — a statement is heavier than a receipt, so the limit is
    # tighter. The eventual commit goes through the assistant action budget.
    import_extract_rate_limit: str = "10/minute"
    # Max bytes for an uploaded statement document (PDF/image). Larger than a
    # receipt because statements run multiple pages.
    import_max_bytes: int = 15 * 1024 * 1024  # 15 MB
    # Proxy awareness for the limiter key. ONLY safe when a trusted reverse proxy
    # overwrites X-Forwarded-For / X-Real-IP on every request; if the app is
    # directly reachable, a client could spoof those headers to evade limits, so
    # the default ignores them. See ``server/src/limiter.py::_client_key``.
    trust_proxy: bool = False
    # /signup/ is rate-limited too (denial-of-wallet / enumeration defense).
    signup_rate_limit: str = "5/hour"
    # General assistant surface limit (chat/propose), wired in Steps 03-04.
    assistant_rate_limit: str = "20/hour"

    # --- LLM cost ceiling (denial-of-wallet, OWASP LLM10) ---
    # The HARD cap is REQUESTS/day: it needs no post-stream token count, so it
    # actually enforces on the streaming chat path (astream_events surfaces no
    # usage metadata). Every chat/propose call costs 1 request.
    llm_daily_request_budget: int = 100
    # Token budget is ADVISORY / observability only until a real streaming token
    # source is wired (see Step 03). Do NOT present it to the user as a hard cap
    # while it meters 0 on the streaming path.
    llm_daily_token_budget: int = 200_000
    # --- Per-user daily DOLLAR ceiling (the real cost cap, enforced) ---
    # Tokens alone aren't the bill; dollars are. We now meter actual usage —
    # exact Groq usage_metadata when the response carries it, else a tiktoken
    # count — convert to cents at the prices below, and DENY pre-flight once the
    # day's accumulated cost would exceed this cap. Soft-overshoot: the in-flight
    # turn may exceed by one generation; the NEXT is blocked (same as requests).
    # Prices are per 1M tokens in cents (Groq llama-3.3-70b-versatile, override in
    # env when the model or pricing changes). 0 cost-budget disables the $ cap.
    llm_daily_cost_budget_cents: int = 50  # $0.50/user/day
    groq_input_price_cents_per_mtok: int = 59   # ~$0.59 / 1M input tokens
    groq_output_price_cents_per_mtok: int = 79  # ~$0.79 / 1M output tokens
    # Agent loop guards (denial-of-wallet on a runaway tool loop), used in Step 03.
    assistant_max_iterations: int = 8
    assistant_max_execution_seconds: int = 60

    # --- Receipts and forecasting ---
    # Groq multimodal model we use for reading receipts. Override it in env if needed.
    groq_vision_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    # Moving-block length (days) for the overdraft residual bootstrap. A weekly
    # block preserves day-of-week spending autocorrelation so the band isn't
    # overconfident; 1 reverts to the legacy IID draw. See forecast_sim.py.
    sim_block_days: int = 7
    # F1 — nominal coverage target for the calibrated overdraft trough band. The
    # split-conformal (CQR) step in forecast_sim widens the raw percentile band
    # toward this level; it can only widen, so calibrated coverage is ≥ the raw
    # baseline by construction (see docs/FORECAST-BACKTEST.md). It is a target,
    # not a guarantee, at ~30 residual days. Set to 0 to disable calibration.
    forecast_coverage_level: float = 0.90
    # F1 — change-point router. When True, the burn residual pool is truncated to
    # the current regime (post-shift) before the bootstrap/calibration, so a
    # recent level shift in spending doesn't get averaged away. Detection is a
    # stdlib CUSUM (no new deps); see services/forecast_changepoint.py.
    forecast_changepoint_enabled: bool = True

    # --- Voice input (speech-to-text) ---
    # Groq hosts Whisper, so voice input reuses ``groq_api_key`` — no new vendor.
    # The /assistant/transcribe/ endpoint turns uploaded mic audio into text the
    # user reviews before sending. Its own rate limit caps STT cost independently
    # of the chat budget (transcription makes no LLM/agent call).
    groq_stt_model: str = "whisper-large-v3-turbo"
    assistant_stt_rate_limit: str = "30/hour"

    # --- AI assistant ---
    # Chat model, sampling temperature, and how many prior turns the agent
    # remembers. These used to be hardcoded inside the assistant service.
    groq_chat_model: str = "llama-3.3-70b-versatile"
    assistant_temperature: float = 0.0
    # Per-request timeout (seconds) for the chat LLM on the SSE path. Bounds a
    # provider stall so an agent turn can't hold a request open indefinitely.
    assistant_request_timeout: float = 30.0
    # Wall-clock backstop (seconds) for a whole agent turn, which may chain several
    # LLM + tool calls. Bounds total time so a slow multi-iteration run can't hold
    # the SSE request open beyond this even if each individual call stays under
    # ``assistant_request_timeout``.
    assistant_turn_timeout: float = 120.0
    assistant_memory_window: int = 4
    # --- Context hygiene: cap large tool outputs before they enter agent memory.
    # A "show all transactions" tool call can return up to MAX_TX_LIMIT (500)
    # rows; ConversationBufferWindowMemory keeps them for several turns, bloating
    # context and (paired with the LLM cost cap) the bill. We keep the first N
    # rows and append a truthful ``_truncated`` marker the model is told to relay
    # — never a silent drop. 0 disables capping.
    assistant_tool_max_rows: int = 40
    # --- Privacy: data minimization before the third-party LLM (Groq) ---
    # High-risk tokens (SSN/email/card/account/phone) are ALWAYS scrubbed from
    # tool outputs before they reach Groq (see server/src/services/pii.py) — this
    # is not configurable. ``assistant_minimize_merchants`` is the stricter,
    # opt-in setting: when True, merchant/account *labels* are replaced with a
    # category placeholder so no merchant name leaves the instance. Default False
    # keeps the assistant's merchant-aware answers; privacy-first deployments set
    # it True.
    assistant_minimize_merchants: bool = False
    # --- Safety: advice/crisis firewall on the in-app assistant ---
    # Screens the assistant's OWN output for unlicensed investment/tax advice,
    # shame, and neediness (server/src/services/game/firewall.py), and routes a
    # crisis-language user message to a static 988 resource instead of the LLM.
    # On by default; the same firewall already guards the Chronicler surface.
    assistant_firewall_enabled: bool = True
    # --- W1: deterministic mode-gating tool-router ---
    # A per-turn deterministic classifier (services/assistant_router.py, mirroring
    # the firewall) selects which tool GROUPS the assistant sees: READ (always) +
    # MONEY (standing core), with WEB / TAX gated in only on their intent. Cuts the
    # per-turn token cost and the SSRF/cost surface (web tools only join on look-up
    # intent), and gives headroom as the toolset grows. OFF by default (ship dark):
    # when False, ``chat()`` builds today's full toolset with a single per-user
    # executor + memory — EXACTLY today's behavior, an instant kill switch. The
    # firewall short-circuits (crisis/dispute/tax-advice) always run BEFORE the
    # router regardless of this flag.
    assistant_router_enabled: bool = False
    # --- W3: self-host / no-egress profile (privacy SKU) ---
    # When True, the assistant's WEB tool group (search_web / open_website /
    # get_information) is dropped from EVERY mode — router on or off — and the
    # deterministic router never adds WEB even on explicit look-up intent, so no
    # assistant chat turn can make an outbound Tavily/web HTTP call. The Clerk is
    # told web lookups are disabled (a system-prompt note) so it says so rather
    # than silently failing. OFF by default (ship dark) = exactly today's
    # behavior, web tools present. NOTE the honest scope: this kills the
    # assistant's *web* egress only. Groq is still the LLM and the receipt/tax
    # VISION backend, so a turn still calls Groq for inference; "fully local"
    # additionally requires disabling/replacing those Groq calls (or pointing at a
    # local model). See docker-compose.selfhost.yml + the README self-host recipe.
    egress_disabled: bool = False
    # Models a user may pick from in the UI. The /settings endpoint exposes this
    # list; switching the active model still happens via groq_chat_model for now.
    assistant_available_models: list[str] = [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "openai/gpt-oss-120b",
    ]

    # --- MCP network surface ---
    # Ships dark by default; set mcp_enabled=true in .env to expose /mcp.
    mcp_enabled: bool = False
    mcp_key_rate_limit: str = "20/minute"
    # Per-key throttle on the MCP tool surface, enforced in MCPAuthMiddleware
    # (keyed on the resolved key_id). In-memory / per-process for v1.
    mcp_rate_limit_enabled: bool = True
    # Pre-auth IP throttle (Step 05): rejects a flood of *bad* keys before any
    # DB query, keyed on the proxy-aware client (so it limits the real client
    # behind a trusted proxy, not the proxy IP). Like ``_rate_limiter`` it is a
    # module-level, in-memory, per-process singleton — it does NOT coordinate
    # across workers/hosts and resets on restart (single-worker invariant,
    # shared with Steps 02/09). Default ON (E4): it sheds a bad-key flood before
    # the DB lookup, and only affects deployments with mcp_enabled=true anyway.
    mcp_preauth_rate_limit_enabled: bool = True
    mcp_preauth_ip_rate_limit: str = "60/minute"

    # --- MCP credential store ---
    mcp_allowed_scopes: list[str] = [
        # legacy format: accepted at key creation but normalized to the modern
        # read:* form before storage (see server/src/mcp/scopes.py). Write/chat
        # legacy scopes grant no MCP read tool and are dropped on normalization.
        "transactions:read",
        "transactions:write",
        "budgets:read",
        "budgets:write",
        "accounts:read",
        "assistant:chat",
        # read-tool scopes
        "read:accounts",
        "read:transactions",
        "read:goals",
        "read:budgets",
        # analytical read tools (Tier-1 surface expansion)
        "read:forecast",
        "read:networth",
        "read:subscriptions",
        "read:scenarios",
        # context resource scope
        "read:context",
        # NOTE: the propose-only write scope ("propose:actions", Tier-2) is
        # deliberately NOT in this default allow-list. It is a write scope, so it
        # is mintable only when ``mcp_propose_enabled`` is True — see
        # MCPKeyService.create, which adds it to the effective allow-set then.
        # That keeps the default (feature-off) deployment unable to even mint a
        # propose-capable key.
    ]
    mcp_key_default_ttl_days: int = 90
    mcp_capability_ttl_seconds: int = 60
    mcp_context_forecast_days: int = 30
    # Default horizon (days) for the get_forecast MCP tool when the caller does
    # not specify one.
    mcp_forecast_default_days: int = 30
    # Tier-2 propose door: when False (default) the propose_action tool refuses
    # even for a key that holds the propose:actions scope — the whole write door
    # ships dark, exactly like mcp_enabled gates the read surface.
    mcp_propose_enabled: bool = False

    @model_validator(mode="after")
    def _validate_jwt_secret(self) -> "Settings":
        """Reject weak/placeholder JWT secrets. Always hard-fail on a known
        placeholder; in production additionally require >= 32 chars of entropy.
        This secret is the HKDF master for every token family, so a guessable
        value is a single point of total compromise."""
        secret = self.jwt_secret_key or ""
        is_prod = self.environment.lower() == "production"
        if secret.strip().lower() in _WEAK_JWT_SECRETS:
            raise ValueError(
                "JWT_SECRET_KEY is a known weak/placeholder value; set a random "
                "secret (e.g. `python -c \"import secrets;print(secrets.token_urlsafe(48))\"`)."
            )
        if is_prod and len(secret) < _MIN_JWT_SECRET_LEN:
            raise ValueError(
                f"JWT_SECRET_KEY must be >= {_MIN_JWT_SECRET_LEN} chars in production "
                f"(got {len(secret)})."
            )
        return self

    @property
    def cookie_secure(self) -> bool:
        """Only set the ``Secure`` cookie flag when we're behind HTTPS in production."""
        return self.environment.lower() == "production"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings():
    return Settings()


settings = get_settings()
