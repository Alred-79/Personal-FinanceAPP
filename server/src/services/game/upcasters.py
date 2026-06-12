"""Event upcasters — the versioning seam.

Stored event payloads are immutable (the log is append-only). When an event
type's payload shape changes, we bump its ``v`` for *new* writes and register an
upcaster that lifts old payloads to the current shape **at read time** during
folds and rebuilds. Stored rows are never rewritten.

For package 01 every type is at v1, so every upcaster is the identity. The
registry and :func:`upcast` exist now so the seam is in place and tested (a
fixture ``TestEvt.v1 -> v2`` upcaster exercises it in the rebuild tests).
"""

from __future__ import annotations

from typing import Callable

# (type, from_version) -> function lifting that payload to from_version + 1.
# Chained: upcast() applies steps until the payload reaches the registered
# current version for the type.
_UPCASTERS: dict[tuple[str, int], Callable[[dict], dict]] = {}

# The current (latest) version known for each event type. Unregistered types
# default to 1.
_CURRENT_VERSION: dict[str, int] = {}


def register_upcaster(
    event_type: str, from_version: int, fn: Callable[[dict], dict]
) -> None:
    """Register a step lifting ``event_type`` payloads from ``from_version`` to
    ``from_version + 1``. Registering bumps the type's current version if needed.
    """
    _UPCASTERS[(event_type, from_version)] = fn
    target = from_version + 1
    if _CURRENT_VERSION.get(event_type, 1) < target:
        _CURRENT_VERSION[event_type] = target


def current_version(event_type: str) -> int:
    """The latest payload version registered for ``event_type`` (default 1)."""
    return _CURRENT_VERSION.get(event_type, 1)


def upcast(event_type: str, v: int, payload: dict) -> dict:
    """Lift ``payload`` (stored at version ``v``) to the current shape.

    Applies each registered step in order. Identity when no upcaster is
    registered — the common case in package 01.
    """
    target = current_version(event_type)
    current = dict(payload)
    while v < target:
        step = _UPCASTERS.get((event_type, v))
        if step is None:
            # No step for this gap — stop rather than silently guess. The fold
            # will receive the payload at the highest version we could reach.
            break
        current = step(current)
        v += 1
    return current


def _reset_for_tests() -> None:
    """Clear the registry. Used by tests that register fixture upcasters so they
    don't leak into other tests."""
    _UPCASTERS.clear()
    _CURRENT_VERSION.clear()
