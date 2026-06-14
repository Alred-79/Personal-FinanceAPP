"""Tax-document extraction via Groq vision. Mirrors ``receipt_service``.

Upload a W-2 / 1099-* / 1098 image → Groq vision → structured money boxes →
a ``pending_review`` ``TaxDocument`` the user reviews and confirms.

PII STANCE — STRICTER THAN RECEIPTS (the acute part of Pillar 3)
---------------------------------------------------------------
1. **Bytes never persisted** — identical to receipts/statements; the image lives
   only in memory for the request and is dropped after extraction.
2. **Full SSN/TIN/EIN never stored** — the issuer identifier is reduced to a
   masked ``last4`` AT EXTRACTION TIME; the full identifier never reaches
   storage and is never trusted to the LLM to redact. Every stored string field
   is run through ``pii.scrub_secrets`` (now incl. the EIN rule) so the persisted
   row is structurally incapable of holding a full SSN/EIN.
3. ``fields_json`` holds money boxes (INTEGER CENTS) + non-PII labels ONLY, and
   is validated against the scrubber before write.

The Groq call is injected as ``vision_fn`` so tests never need the SDK.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Callable, Optional

from server.src.money import dollars_to_cents

from ..extraction_utils import parse_amount as _parse_amount
from ..pii import scrub_secrets

# (image_base64, content_type, form_hint) -> structured dict from the vision model.
VisionFn = Callable[[str, str, str], dict]

ALLOWED_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "application/pdf",
}

# The supported forms and which money boxes we pull. Box labels are non-PII.
FORM_TYPES = ("W-2", "1099-NEC", "1099-MISC", "1099-K", "1098", "1099-B")

# Per-form extraction guidance, appended to the base prompt. We ask the model to
# return the issuer/payer NAME (a business name, not a personal identifier) and
# the money boxes — and EXPLICITLY to return only the LAST 4 of any TIN/EIN/SSN.
# The prompt instruction is defense-in-depth only; the deterministic mask below
# is the real control.
_FORM_GUIDANCE = {
    "W-2": (
        'employer name as "issuer_name"; box 1 wages as "box1_wages"; box 2 '
        'federal income tax withheld as "box2_fed_withholding"; box 17 state '
        'income tax as "box17_state_withholding".'
    ),
    "1099-NEC": (
        'payer name as "issuer_name"; box 1 nonemployee compensation as '
        '"box1_compensation"; box 4 federal income tax withheld as '
        '"box4_fed_withholding".'
    ),
    "1099-MISC": (
        'payer name as "issuer_name"; box 3 other income as "box3_other_income"; '
        'box 4 federal income tax withheld as "box4_fed_withholding".'
    ),
    "1099-K": (
        'PSE/payer name as "issuer_name"; box 1a gross amount as "box1a_gross".'
    ),
    "1098": (
        'lender name as "issuer_name"; box 1 mortgage interest received as '
        '"box1_mortgage_interest".'
    ),
    "1099-B": (
        'payer name as "issuer_name"; proceeds as "proceeds"; cost basis as '
        '"cost_basis"; and "term" as "short" or "long".'
    ),
}

# The money-box keys per form, in integer-cents after normalization.
_FORM_BOXES = {
    "W-2": ("box1_wages", "box2_fed_withholding", "box17_state_withholding"),
    "1099-NEC": ("box1_compensation", "box4_fed_withholding"),
    "1099-MISC": ("box3_other_income", "box4_fed_withholding"),
    "1099-K": ("box1a_gross",),
    "1098": ("box1_mortgage_interest",),
    "1099-B": ("proceeds", "cost_basis"),
}

_BASE_PROMPT = (
    "You are a tax-document extraction assistant. Read this US tax form image and "
    "respond with ONLY a JSON object, no prose. The form is a {form}. Extract: "
    "{guidance} Also return the 4-digit tax year as an integer \"tax_year\". For "
    "any taxpayer identification number (SSN/EIN/TIN), return ONLY the last 4 "
    'digits as a string "tin_last4" — NEVER the full number. Use null for any '
    "field you cannot read. All money amounts are plain numbers in dollars."
)

# Last-4 extractor: if the model returns a full identifier despite the prompt, we
# keep ONLY the trailing 4 digits. Belt-and-suspenders to the deterministic mask.
_DIGITS = re.compile(r"\d")


def _mask_last4(value) -> Optional[str]:
    """Return ONLY the last 4 digits of any identifier-looking value, or None.

    Deterministic — never trusts the model to have redacted. A full SSN/EIN that
    sneaks into the ``tin_last4`` field is reduced to its last 4 here, so the
    stored value is structurally incapable of holding a full identifier.
    """
    if value is None:
        return None
    digits = "".join(_DIGITS.findall(str(value)))
    if not digits:
        return None
    return digits[-4:]


def _default_vision_fn(image_b64: str, content_type: str, form_hint: str) -> dict:
    """Call Groq's vision model. Imported lazily so tests never need the SDK."""
    from groq import Groq

    from ...settings import settings

    form = form_hint if form_hint in FORM_TYPES else "tax form"
    guidance = _FORM_GUIDANCE.get(form_hint, "the issuer name and all money boxes.")
    prompt = _BASE_PROMPT.format(form=form, guidance=guidance)

    client = Groq(api_key=settings.groq_api_key)
    response = client.chat.completions.create(
        model=settings.groq_vision_model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{content_type};base64,{image_b64}"
                        },
                    },
                ],
            }
        ],
    )
    content = response.choices[0].message.content
    if not content:
        return {}
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class TaxDocService:
    """Extracts the reviewable fields of a tax form. Mirrors ``ReceiptService``."""

    def __init__(self, vision_fn: Optional[VisionFn] = None) -> None:
        self.vision_fn = vision_fn or _default_vision_fn

    def extract(
        self, image_bytes: bytes, content_type: str, form_type: str
    ) -> dict:
        """Return a normalized, PII-safe review payload for a tax form.

        ``form_type`` is the classifier's guess; the result echoes it back. The
        returned dict carries: ``form_type``, ``issuer_name`` (scrubbed),
        ``issuer_tin_last4`` (last 4 only), ``tax_year``, and ``fields`` (money
        boxes in INTEGER CENTS + non-PII labels). NO full identifier is ever in
        the result. May raise from ``vision_fn``.
        """
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        raw = self.vision_fn(image_b64, content_type, form_type) or {}
        return self._normalize(raw, form_type)

    @staticmethod
    def _normalize(raw: dict, form_type: str) -> dict:
        if not isinstance(raw, dict):
            raw = {}

        ft = form_type if form_type in FORM_TYPES else "1099-NEC"

        # issuer name — a business name, but scrubbed anyway (a stray SSN/EIN in
        # the OCR'd label must never survive into storage).
        issuer = raw.get("issuer_name")
        if isinstance(issuer, str):
            issuer = scrub_secrets(issuer.strip()) or ""
        else:
            issuer = ""

        # TIN/EIN — keep ONLY the last 4, deterministically. Never the full id.
        tin_last4 = _mask_last4(raw.get("tin_last4"))

        # tax year — coerce to int when sane, else None (caller may patch).
        ty = raw.get("tax_year")
        try:
            tax_year = int(ty) if ty is not None else None
        except (TypeError, ValueError):
            tax_year = None
        if tax_year is not None and not (1900 <= tax_year <= 2200):
            tax_year = None

        # money boxes → INTEGER CENTS. Only the boxes this form defines; non-money
        # labels (e.g. 1099-B "term") pass through as scrubbed strings.
        fields: dict = {}
        for box in _FORM_BOXES.get(ft, ()):  # money boxes
            dollars = _parse_amount(raw.get(box))
            if dollars is not None:
                fields[box] = dollars_to_cents(dollars)
        # 1099-B carries a non-money "term" label.
        if ft == "1099-B":
            term = raw.get("term")
            if isinstance(term, str):
                term = scrub_secrets(term.strip().lower())
                if term in ("short", "long"):
                    fields["term"] = term

        return {
            "form_type": ft,
            "issuer_name": issuer,
            "issuer_tin_last4": tin_last4,
            "tax_year": tax_year,
            "fields": fields,
        }
