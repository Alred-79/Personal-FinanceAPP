"""Pillar 3 de-risk prerequisite (kept as a regression).

The single highest-judgment risk: the output firewall blocks the literal
substring "tax deduction" / "tax write-off" on *every* model output
(``game/firewall.py:58``), so a perfectly factual tax summary that happens to
phrase a number as "$4,200 in tax deductions" gets the whole sentence replaced
by the generic redirect — reading as the feature being broken.

This test is the MEASURED GATE, not just a pass/fail. It:
  1. quantifies how often realistic factual narration is WRONGLY blocked by the
     raw firewall (the problem),
  2. asserts the tax-narration post-processor (``tax/narration.py``) drives that
     wrongly-blocked rate to ZERO (the fix), and
  3. asserts that GENUINE advice ("you should claim…", "I recommend you write
     off…") is STILL blocked after the post-processor — i.e. the fix narrows the
     factual phrasings off the blocked substrings without ever laundering advice
     past the firewall.
"""

from __future__ import annotations

from server.src.services.game.firewall import screen_output
from server.src.services.tax.narration import soften_tax_narration

# ── representative engine fact sheets, narrated the way a 70B model realistically
# phrases them. EVERY one of these is FACTUAL organization (a sum, a bucket, a
# tagged total, an estimate) and SHOULD survive the firewall. Several deliberately
# use the natural-but-blocked phrasing ("in tax deductions", "tax write-offs")
# that an LLM intermittently emits — exactly the wrongly-blocked case.
FACTUAL_NARRATIONS = [
    "You have $4,200 tagged to the home-office bucket this year.",
    "Your tagged business income is $58,000; tagged deductions are $12,300.",
    "Schedule C line 18 (Office) totals $1,140 across 9 tagged transactions.",
    "Your estimated quarterly figure based on tagged data is $2,950 (estimate only).",
    # the natural-but-blocked phrasings — the crux of the risk. MEASURED finding
    # (see the spike below): the firewall's pattern is \btax\s+(...deduction...
    # write[- ]off...)\b, so the SINGULAR forms ("a tax deduction", "the tax
    # write-off") are blocked while the PLURAL forms ("tax deductions", "tax
    # write-offs") slip the \b boundary on the trailing 's'. A 70B model emits
    # BOTH registers interchangeably, so the singular phrasings are the real
    # wrongly-blocked cases this corpus must cover.
    "That $600 meal is a 50% tax deduction, so $300 is tagged as deductible.",
    "This Staples charge is a tax write-off tagged to the Office bucket.",
    "Each tagged Office charge is a tax deduction in your Schedule C line 18 total.",
    "The home-office portion is a tax write-off tagged at 100% business.",
    # plural register (factual, not blocked by the raw firewall — but the
    # post-processor must still leave it factual and unblocked):
    "Across your tagged transactions there are $12,300 in tax deductions this year.",
    "Your tagged business expenses include $850 of tax write-offs in the supplies bucket.",
    "You logged 1,200 business miles, a deductible amount tagged for the year.",
    "Your 1099-NEC box 1 compensation is $58,000 and federal withholding is $4,100.",
]

# ── genuine advice — these MUST stay blocked even after the post-processor. The
# post-processor must not launder any of these into something that survives.
ADVICE_NARRATIONS = [
    "You should claim the home office on your taxes.",
    "I recommend you write off your car.",
    "That's a great tax deduction — you should take it.",
    "You can deduct this, so claim it on your taxes.",
    "You should take the home-office tax write-off this year.",
    "This qualifies as a tax deduction; you should claim it.",
]


def _blocked(text: str) -> bool:
    return screen_output(text, plain=True).blocked


def test_raw_firewall_wrongly_blocks_factual_narration():
    """Document the problem: the RAW firewall wrongly blocks factual narration.

    This is the measurement that justifies the post-processor. If this rate were
    zero we wouldn't need the fix; it is non-trivial, so we do.
    """
    wrongly_blocked = [n for n in FACTUAL_NARRATIONS if _blocked(n)]
    rate = len(wrongly_blocked) / len(FACTUAL_NARRATIONS)
    # MEASURED: the singular "a tax deduction" / "tax write-off" forms ARE wrongly
    # blocked (the plural forms slip the \b boundary). A 70B model emits the
    # singular register routinely, so the raw wrongly-blocked rate on realistic
    # factual narration is non-trivial — this is the risk the post-processor
    # exists to neutralize. (The gate is the NEXT test: post-processor → 0.)
    assert wrongly_blocked, (
        "Expected the raw firewall to wrongly block some factual narration "
        "(that is the risk this pillar mitigates); none were blocked."
    )
    # Sanity: a meaningful fraction, not a fluke of one phrasing. Measured ~30%.
    assert rate >= 0.20, f"raw wrongly-blocked rate unexpectedly low: {rate:.0%}"


def test_post_processor_drives_factual_block_rate_to_zero():
    """The gate: AFTER the post-processor, NO factual narration is blocked."""
    still_blocked = [
        n for n in FACTUAL_NARRATIONS if _blocked(soften_tax_narration(n))
    ]
    assert not still_blocked, (
        "Tax-narration post-processor failed to rescue factual summaries; these "
        f"are still wrongly blocked: {still_blocked}"
    )


def test_post_processor_never_launders_genuine_advice():
    """The safety invariant: genuine advice is STILL blocked after softening.

    The post-processor narrows factual phrasings off the blocked substrings; it
    must never turn advice into something that survives the firewall.
    """
    leaked = [
        n for n in ADVICE_NARRATIONS if not _blocked(soften_tax_narration(n))
    ]
    assert not leaked, (
        "Post-processor laundered genuine advice past the firewall: "
        f"{leaked}"
    )


def test_post_processor_is_idempotent():
    """Softening twice equals softening once (no runaway rewriting)."""
    for n in FACTUAL_NARRATIONS + ADVICE_NARRATIONS:
        once = soften_tax_narration(n)
        assert soften_tax_narration(once) == once


def test_post_processor_leaves_clean_factual_text_unchanged():
    """Factual text that never touches the blocked substrings is untouched."""
    clean = "Schedule C line 18 (Office) totals $1,140 across 9 tagged transactions."
    assert soften_tax_narration(clean) == clean
