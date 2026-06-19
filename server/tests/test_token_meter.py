"""Token metering for the LLM dollar cap (A3): pricing, usage extraction, fallback."""

from types import SimpleNamespace

import pytest

from server.src.services import token_meter
from server.src.settings import settings


def test_count_tokens_nonzero_for_text():
    assert token_meter.count_tokens("hello world, this is a sentence") > 0
    assert token_meter.count_tokens("") == 0


def test_cost_cents_rounds_up_and_prices_both_directions(monkeypatch):
    monkeypatch.setattr(settings, "groq_input_price_cents_per_mtok", 100)   # $1/Mtok
    monkeypatch.setattr(settings, "groq_output_price_cents_per_mtok", 200)  # $2/Mtok
    # 1,000,000 in + 1,000,000 out = 100c + 200c = 300c.
    assert token_meter.cost_cents(1_000_000, 1_000_000) == 300
    # Tiny usage rounds UP to 1c (never under-charge), never 0 for real usage.
    assert token_meter.cost_cents(10, 10) == 1


def test_usage_from_message_reads_usage_metadata():
    msg = SimpleNamespace(
        usage_metadata={"input_tokens": 123, "output_tokens": 45, "total_tokens": 168}
    )
    assert token_meter.usage_from_message(msg) == (123, 45)


def test_usage_from_message_reads_legacy_token_usage():
    msg = SimpleNamespace(
        usage_metadata=None,
        response_metadata={"token_usage": {"prompt_tokens": 10, "completion_tokens": 7}},
    )
    assert token_meter.usage_from_message(msg) == (10, 7)


def test_usage_from_message_none_when_absent():
    assert token_meter.usage_from_message(None) is None
    assert token_meter.usage_from_message(SimpleNamespace()) is None


def test_estimate_cost_is_conservative():
    # The pre-flight estimate prices the prompt + a generous output assumption,
    # so it should be a positive reservation, not zero.
    assert token_meter.estimate_cost_cents("how much did I spend on coffee?") > 0


def test_message_text_handles_str_list_and_none():
    """L2 — fallback per-sub-run output counting needs the message's text."""
    assert token_meter.message_text(SimpleNamespace(content="hello")) == "hello"
    assert token_meter.message_text(None) == ""
    # list-of-parts content (concatenate text parts, ignore non-text)
    parts_msg = SimpleNamespace(
        content=[{"type": "text", "text": "abc"}, {"type": "image"}, "def"]
    )
    assert token_meter.message_text(parts_msg) == "abcdef"
    # a bare string is returned as-is
    assert token_meter.message_text("plain") == "plain"
    # countable output for a usage-less sub-run
    assert token_meter.count_tokens(
        token_meter.message_text(SimpleNamespace(content="some output text"))
    ) > 0
