"""The extracted action-token leaf (Pillar 2B / R7).

``action_tokens`` is the dependency-free home of ``make_token``/``decode_token``,
pulled out of ``assistant_service`` so the rule engine can mint a money-affecting
proposal from an unattended Plaid sync WITHOUT importing the assistant layer
(which already imports the engine — that would be a cycle).

These tests pin two things:
  1. mint→decode round-trips, ``typ`` discrimination, and expiry behave;
  2. the import graph has no engine↔assistant cycle, and ``ActionService`` still
     re-exports the pair so every existing caller is unchanged.
"""

import importlib
import sys
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from server.src.services.action_tokens import (
    ACTION_TOKEN_TYPE,
    ActionTokenError,
    decode_token,
    make_token,
)
from server.src.settings import settings


# ── mint / decode round-trip ────────────────────────────────────────────────


def test_make_then_decode_round_trips():
    tok = make_token(7, "create_rule", {"name": "Payday", "amount": 50.0})
    claims = decode_token(tok)
    assert claims["uid"] == 7
    assert claims["action"] == "create_rule"
    assert claims["params"] == {"name": "Payday", "amount": 50.0}
    assert claims["typ"] == ACTION_TOKEN_TYPE
    # A fresh single-use id every mint (replay guard keys on it).
    assert claims["jti"]
    assert decode_token(make_token(7, "create_rule", {}))["jti"] != claims["jti"]


def test_decode_rejects_wrong_typ():
    """An auth-style token (no/!= action ``typ``) is never accepted as a confirm."""
    fake = jwt.encode(
        {
            "uid": 1,
            "typ": "access",  # not an action token
            "action": "add_goal",
            "params": {},
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(ActionTokenError):
        decode_token(fake)


def test_decode_rejects_expired():
    expired = jwt.encode(
        {
            "uid": 1,
            "typ": ACTION_TOKEN_TYPE,
            "action": "add_goal",
            "params": {},
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(ActionTokenError):
        decode_token(expired)


def test_decode_rejects_garbage():
    with pytest.raises(ActionTokenError):
        decode_token("not-a-jwt")


# ── No import cycle: the engine can depend on the leaf ───────────────────────


def test_action_tokens_is_a_leaf():
    """The leaf *imports* neither the engine nor the assistant layer.

    If it did, ``rule_engine`` (which we want to import it) would pull in
    ``assistant_service`` transitively and re-create the very cycle the
    extraction exists to break. We parse the AST and inspect import statements
    only — prose in the module docstring may legitimately name both modules.
    """
    import ast

    mod = importlib.import_module("server.src.services.action_tokens")
    with open(mod.__file__, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
            imported += [f"{node.module}.{a.name}" for a in node.names]
    joined = " ".join(imported)
    assert "assistant_service" not in joined
    assert "rule_engine" not in joined


def test_engine_does_not_import_the_assistant_layer():
    """The rule engine must not import ``assistant_service`` (that's the cycle).

    2B's unattended above-threshold lane lives in the engine + the notifications
    router; the actual token mint goes through the dependency-free leaf (the
    router) or is re-minted on demand. Either way the engine must stay free of the
    assistant layer so the leaf extraction's no-cycle guarantee holds.
    """
    sys.modules.pop("server.src.services.rule_engine", None)
    engine = importlib.import_module("server.src.services.rule_engine")
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(engine))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
        elif isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
    assert not any("assistant_service" in m for m in imported)


def test_action_service_reexports_the_pair():
    """Back-compat: ``ActionService.make_token``/``decode_token`` still work and
    interoperate with the leaf (a token minted via the service decodes via the
    leaf and vice versa)."""
    from server.src.services.assistant_service import ActionService

    tok = ActionService.make_token(3, "add_goal", {"name": "Vault"})
    # leaf decodes a service-minted token
    assert decode_token(tok)["uid"] == 3
    # service decodes a leaf-minted token
    leaf_tok = make_token(3, "add_goal", {"name": "Vault"})
    assert ActionService.decode_token(leaf_tok)["action"] == "add_goal"
