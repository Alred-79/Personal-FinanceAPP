"""Context-hygiene guard: large tool outputs are capped before agent memory.

A read tool can return up to MAX_TX_LIMIT (500) rows; the conversation buffer
keeps each turn's output for several turns, so an unbounded "show everything"
result bloats context (and, with the LLM cost cap, the bill). ``_safe_for_llm``
keeps the first ``assistant_tool_max_rows`` rows and appends a truthful
``_truncated`` marker — never a silent drop. These run fully offline.
"""

import pytest

import server.src.services.assistant_service as svc_mod
from server.src.services.assistant_service import _safe_for_llm, _cap_rows


def _rows(n: int) -> list[dict]:
    return [{"id": i, "title": f"txn {i}", "amount": 1.0, "category": "Food"} for i in range(n)]


def test_large_list_is_capped_with_truthful_marker(monkeypatch):
    monkeypatch.setattr(svc_mod.settings, "assistant_tool_max_rows", 40)
    out = _safe_for_llm(_rows(312))
    # 40 kept rows + 1 marker.
    assert len(out) == 41
    marker = out[-1]
    assert marker["_truncated"] is True
    assert marker["shown"] == 40
    assert marker["total"] == 312
    # The kept rows are the real data, in order.
    assert out[0]["id"] == 0 and out[39]["id"] == 39


def test_small_list_is_untouched(monkeypatch):
    monkeypatch.setattr(svc_mod.settings, "assistant_tool_max_rows", 40)
    rows = _rows(5)
    out = _safe_for_llm(rows)
    assert len(out) == 5
    assert all("_truncated" not in r for r in out)


def test_cap_zero_disables_truncation(monkeypatch):
    monkeypatch.setattr(svc_mod.settings, "assistant_tool_max_rows", 0)
    out = _safe_for_llm(_rows(500))
    assert len(out) == 500


def test_redaction_still_applies_to_kept_rows(monkeypatch):
    """Cap runs AFTER redaction, so PII in a kept row is still scrubbed and the
    marker carries no user data."""
    monkeypatch.setattr(svc_mod.settings, "assistant_tool_max_rows", 2)
    rows = [
        {"title": "leak ssn 123-45-6789", "amount": 1.0, "category": "X"},
        {"title": "ok", "amount": 2.0, "category": "Y"},
        {"title": "dropped 999-88-7777", "amount": 3.0, "category": "Z"},
    ]
    out = _safe_for_llm(rows)
    assert len(out) == 3  # 2 kept + marker
    assert "123-45-6789" not in out[0]["title"]
    assert "REDACTED" in out[0]["title"]
    assert out[-1]["_truncated"] is True


def test_non_list_payloads_pass_through(monkeypatch):
    monkeypatch.setattr(svc_mod.settings, "assistant_tool_max_rows", 1)
    # The "no data" string reply and dict payloads are not row lists.
    assert _cap_rows("No transactions found.") == "No transactions found."
    assert _cap_rows({"safe_to_spend": 100.0}) == {"safe_to_spend": 100.0}
