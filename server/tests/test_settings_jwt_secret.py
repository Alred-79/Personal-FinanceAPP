"""The JWT master secret validator — proof for a control that had none.

``Settings._validate_jwt_secret`` has always been real and unconditional (it
raises at settings construction, so a misconfigured deploy cannot boot), but no
test anywhere exercised it. That is a bad combination for a control this
load-bearing: ``jwt_secret_key`` is the HKDF master for EVERY token family
(session / assistant_action / mcp), so a guessable value is not one compromised
surface, it is all of them at once.

These tests are characterization, not red-green — the behaviour predates them.
They exist so the guarantee is verifiable by someone who doesn't trust the
docstring, and so a future refactor cannot quietly soften it.

Note the deliberate asymmetry they pin down: placeholder values are rejected in
EVERY environment, but the >= 32-char length floor applies only in production.
That is why this suite can run with a short non-placeholder secret.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.src.settings import _MIN_JWT_SECRET_LEN, _WEAK_JWT_SECRETS, Settings


def _settings(**overrides):
    """Construct Settings with every required field, overriding as needed.

    Explicit kwargs are pydantic-settings' highest-priority source, so this does
    not read the developer's real .env.
    """
    base = dict(
        groq_api_key="test-key",
        jwt_secret_key="p6Jq2xR9vT4wY7zA1bC3dE5fG8hK0mN2",  # 32 chars, not a placeholder
        jwt_algorithm="HS256",
        tavily_api_key="test-key",
        plaid_client_id="test-id",
        plaid_client_secret="test-secret",
        plaid_environment="sandbox",
        environment="development",
    )
    base.update(overrides)
    return Settings(**base)


@pytest.mark.parametrize("weak", sorted(_WEAK_JWT_SECRETS))
@pytest.mark.parametrize("env", ["development", "production"])
def test_placeholder_secret_is_rejected_in_every_environment(weak, env):
    """A known placeholder must never boot the app — dev included.

    Parametrized over the real frozenset rather than a hardcoded sample, so
    adding a value to _WEAK_JWT_SECRETS automatically gains coverage.
    """
    with pytest.raises(ValidationError, match="weak/placeholder"):
        _settings(jwt_secret_key=weak, environment=env)


def test_placeholder_detection_ignores_case_and_whitespace():
    """``.strip().lower()`` is load-bearing: ' ChangeMe ' is still a placeholder."""
    with pytest.raises(ValidationError, match="weak/placeholder"):
        _settings(jwt_secret_key="  ChangeMe  ", environment="production")


def test_production_rejects_a_secret_below_the_length_floor():
    short = "a" * (_MIN_JWT_SECRET_LEN - 1)
    with pytest.raises(ValidationError, match=f">= {_MIN_JWT_SECRET_LEN} chars"):
        _settings(jwt_secret_key=short, environment="production")


def test_production_accepts_a_secret_at_the_floor():
    """Boundary: exactly _MIN_JWT_SECRET_LEN passes (the check is >=, not >)."""
    s = _settings(jwt_secret_key="b" * _MIN_JWT_SECRET_LEN, environment="production")
    assert len(s.jwt_secret_key) == _MIN_JWT_SECRET_LEN


def test_non_production_allows_a_short_non_placeholder_secret():
    """The length floor is production-only — a deliberate carve-out, pinned here
    so it is a documented decision rather than an accident someone later
    'fixes' without realising the dev/CI suites depend on it."""
    s = _settings(jwt_secret_key="short-dev-key", environment="development")
    assert s.jwt_secret_key == "short-dev-key"
