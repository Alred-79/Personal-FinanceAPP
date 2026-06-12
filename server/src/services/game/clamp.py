"""XP clamp — the one-sided ratchet that enforces "XP never decreases" (Law 3).

Every XP-touching fold MUST route its delta through :func:`clamped_xp_delta`.
A negative true delta (a correction that would claw XP back) applies as 0 but
the *true* delta is preserved so the event payload — and any later audit — can
see what the engine actually computed. The clamp is one-sided: positive deltas
pass through untouched.
"""

from __future__ import annotations


def clamped_xp_delta(true_delta: int) -> tuple[int, int]:
    """Return ``(applied, true)`` for an XP change.

    ``applied = max(true_delta, 0)`` — XP never decreases. ``true`` is the
    unclamped value, stored alongside so corrections remain auditable.

    >>> clamped_xp_delta(10)
    (10, 10)
    >>> clamped_xp_delta(-30)
    (0, -30)
    """
    return (max(true_delta, 0), true_delta)
