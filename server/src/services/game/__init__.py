"""The v4 game domain: an append-only event substrate (package 01).

Law 1: ``game_state = fold(event_stream)``. Game code never writes to financial
truth. Everything in here folds over the ``game_events`` log into rebuildable
projections, synchronously in the appending transaction.

Single-user invariant (Step 01) — READ BEFORE "fixing" the global keys
----------------------------------------------------------------------
Every game projection (XP, streak, grace, boss, homestead) and
``CategorySettings`` is keyed *globally*, not per user: ``GameEvent`` has no
``user_id`` column, the projection KV is keyed ``(projection, key)`` only, and
event scans don't filter by user. This is DELIBERATE and CORRECT, because this
is a single-user instance: registration closes after the first account (see the
signup guard in ``server/src/routers/auth.py`` + ``settings.single_user``), so
there is exactly one owner and the global state belongs to them.

Do **not** "fix" this by adding a ``user_id`` column to ``GameEvent`` or
per-user KV keys to some modules. A partial change creates split-brain
projections (some folds user-scoped, some not) that silently corrupt XP/streak
math. If multi-user is ever truly needed, it requires revisiting the signup
guard AND a full, all-at-once per-user migration of the event log + every fold +
a projection rebuild — not a piecemeal edit.
"""
