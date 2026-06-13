"""The shared slowapi rate limiter.

It lives in its own module so two places can import it without creating a
circular import: ``main.py`` registers the limiter and the exception handler,
and the auth router decorates ``/token`` and ``/refresh`` with it.

Proxy-awareness (Step 02): in a realistic deployment the app sits behind a
reverse proxy (nginx/Caddy/Cloud), so every request arrives with the *proxy's*
IP as ``request.client.host``. slowapi's default ``get_remote_address`` keys on
that host, which would collapse all traffic into one client — throttling the
whole app at once or being trivially defeated. ``_client_key`` instead honors
the forwarded client IP, but **only** when ``settings.trust_proxy`` is set.

``trust_proxy=True`` is safe ONLY behind a trusted proxy that *overwrites*
``X-Forwarded-For`` / ``X-Real-IP`` on every request. If the app is directly
reachable, a client can spoof those headers to evade limits, so the default is
``trust_proxy=False`` and forwarded headers are ignored.
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from server.src.settings import settings


def _client_key(request: Request) -> str:
    """Resolve the rate-limit key for a request.

    When ``trust_proxy`` is on, prefer the left-most hop of ``X-Forwarded-For``
    (the original client; intermediate proxies append themselves on the right),
    then ``X-Real-IP``. Malformed/empty headers fall through to the direct peer
    address — never a 500. When ``trust_proxy`` is off, forwarded headers are
    ignored entirely so they cannot be used to evade per-client limits.
    """
    if settings.trust_proxy:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            client = fwd.split(",")[0].strip()
            if client:
                return client
        real = request.headers.get("x-real-ip")
        if real:
            real = real.strip()
            if real:
                return real
    return get_remote_address(request)


limiter = Limiter(
    key_func=_client_key,
    enabled=settings.rate_limit_enabled,
)
