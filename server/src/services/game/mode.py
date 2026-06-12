"""The game-mode helper consulted by later packages' generation jobs.

``mode`` is one variable end to end (v4 §10.2). On the server its only job in
package 02 is the gate ``should_generate_flavor``: server-side LLM flavor
generation runs only when the user has opted into ``ambient`` or ``full``. Off
mode is pure finance — no generation, no game state side effects.
"""

from __future__ import annotations

GAME_MODES = ("off", "ambient", "full")


def should_generate_flavor(user) -> bool:
    """Whether to run server-side LLM flavor generation for this user.

    False in ``off`` (and for any unset/unknown mode — fail closed to pure
    finance); True in ``ambient`` and ``full``. Accepts anything with a
    ``game_mode`` attribute (ORM ``User`` or the ``UserInDB`` schema).
    """
    mode = getattr(user, "game_mode", "off") or "off"
    return mode in ("ambient", "full")
