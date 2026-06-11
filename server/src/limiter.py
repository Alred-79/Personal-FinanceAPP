"""The shared slowapi rate limiter.

It lives in its own module so two places can import it without creating a
circular import: ``main.py`` registers the limiter and the exception handler,
and the auth router decorates ``/token`` and ``/refresh`` with it.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from server.src.settings import settings

limiter = Limiter(
    key_func=get_remote_address,
    enabled=settings.rate_limit_enabled,
)
