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

    # Rate limiting via slowapi. We turn it off in the test suite so repeated
    # login and refresh calls don't trip the limiter.
    rate_limit_enabled: bool = True
    login_rate_limit: str = "5/minute"
    refresh_rate_limit: str = "10/minute"
    # Receipt scanning calls the paid Groq vision API, so it gets a limit too.
    receipt_scan_rate_limit: str = "20/minute"

    # --- Receipts and forecasting ---
    # Groq multimodal model we use for reading receipts. Override it in env if needed.
    groq_vision_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"

    # --- AI assistant ---
    # Chat model, sampling temperature, and how many prior turns the agent
    # remembers. These used to be hardcoded inside the assistant service.
    groq_chat_model: str = "llama-3.3-70b-versatile"
    assistant_temperature: float = 0.0
    assistant_memory_window: int = 4
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
