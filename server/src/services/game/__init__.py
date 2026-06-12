"""The v4 game domain: an append-only event substrate (package 01).

Law 1: ``game_state = fold(event_stream)``. Game code never writes to financial
truth. Everything in here folds over the ``game_events`` log into rebuildable
projections, synchronously in the appending transaction.
"""
