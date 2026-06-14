"""Pillar 3 — the firewall boundary (factual organization vs filing advice).

Two enforcement layers, both tested here:
  1. ``is_tax_advice_request`` (INPUT screen) routes filing/eligibility-advice
     questions to ``TAX_RESOURCE`` BEFORE the model is called, while factual
     "how much did I tag?" questions still reach the tools.
  2. ``screen_output`` (the backstop) still blocks genuine advice the model might
     emit ("you should claim…"), while the tax-narration post-processor keeps
     factual summaries from being wrongly blocked.

The EIN redaction additions live in ``test_tax_documents.py``; here we cover the
advice/factual boundary the pillar's top risk turns on.
"""

from __future__ import annotations

from server.src.services.game.firewall import (
    TAX_RESOURCE,
    is_tax_advice_request,
    screen_output,
)
from server.src.services.tax.narration import soften_tax_narration


# ── input screen: advice intent routed, factual questions pass ───────────────

class TestIsTaxAdviceRequest:
    def test_advice_intents_caught(self):
        for q in [
            "Should I deduct my home office?",
            "Can I write off my car?",
            "Is this laptop deductible?",
            "Are these meals deductible?",
            "How do I file my taxes?",
            "What can I claim?",
            "How much can I deduct for mileage?",
        ]:
            assert is_tax_advice_request(q), q

    def test_factual_questions_pass(self):
        for q in [
            "How much did I tag to the office bucket?",
            "What is my tagged business income?",
            "Show me my deductions by bucket.",
            "What did I tag to Schedule C line 18?",
            "How much is in my meals bucket this year?",
        ]:
            assert not is_tax_advice_request(q), q

    def test_resource_is_organize_only(self):
        assert "tax advice" in TAX_RESOURCE["body"].lower()
        assert "professional" in TAX_RESOURCE["body"].lower()


# ── output backstop: advice still blocked, factual survives ──────────────────

class TestOutputFirewallBoundary:
    def test_genuine_advice_blocked(self):
        for out in [
            "You should claim the home office on your taxes.",
            "I recommend you write off your car.",
            "You can deduct this, so claim it on your taxes.",
        ]:
            # Even after the tax post-processor, advice must stay blocked.
            assert screen_output(soften_tax_narration(out), plain=True).blocked, out

    def test_factual_summary_survives(self):
        for out in [
            "Schedule C line 18 (Office) totals $1,140 across 9 tagged transactions.",
            "Your tagged business income is $58,000; tagged deductions are $12,300.",
            "That $600 meal is a tax deduction, so $300 is tagged as deductible.",
            "This Staples charge is a tax write-off tagged to the Office bucket.",
        ]:
            assert not screen_output(
                soften_tax_narration(out), plain=True
            ).blocked, out
