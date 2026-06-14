from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    groq_api_key: str
    jwt_secret_key: str
    jwt_algorithm: str
    tavily_api_key: str
    plaid_client_id: str
    plaid_client_secret: str
    plaid_environment: str
    # --- Plaid access-token encryption at rest (Step 08) ---
    # The Plaid access token grants read access to the user's real bank, so it
    # is encrypted (Fernet) before it touches the DB. Supply an explicit Fernet
    # key (urlsafe-base64, 32 bytes) here to rotate independently of the JWT
    # secret; when unset, the key is derived deterministically from
    # ``jwt_secret_key`` so single-user/dev deployments encrypt with no extra
    # config (see server/src/services/plaid_crypto.py).
    plaid_token_key: str | None = None
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
    # The Detangler's nightly pass (transfer/refund/duplicate flagging). On by
    # default; the per-pair notification dedup makes a re-fire harmless. Disable
    # to silence the nightly job without affecting the on-demand endpoint.
    detangle_enabled: bool = True

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
    # Agent loop guards (denial-of-wallet on a runaway tool loop), used in Step 03.
    assistant_max_iterations: int = 8
    assistant_max_execution_seconds: int = 60

    # --- Receipts and forecasting ---
    # Groq multimodal model we use for reading receipts. Override it in env if needed.
    groq_vision_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"

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
    assistant_memory_window: int = 4
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
    # shared with Steps 02/09). Disabled by default to keep existing behaviour;
    # enable in deployment.
    mcp_preauth_rate_limit_enabled: bool = False
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
        # context resource scope
        "read:context",
    ]
    mcp_key_default_ttl_days: int = 90
    mcp_capability_ttl_seconds: int = 60
    mcp_context_forecast_days: int = 30

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
