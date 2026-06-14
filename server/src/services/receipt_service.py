"""Receipt scanning via Groq multimodal vision.

Upload a receipt image → Groq vision model → structured fields (merchant, total,
date, category, line items) → a prefilled transaction draft the user can review
and save.

PII NOTE
--------
Receipt images often hold sensitive PII (the cardholder name, the last four
digits of a card, an address, the itemized purchases). To keep our PII footprint
small we **do not save the raw image**: the bytes live only in memory for the
length of the request and are dropped once we pull the fields out. Only the
structured draft is returned, and nothing is written to the database until the
user chooses to save the transaction.

The Groq call is injected as ``vision_fn`` so it is trivially mockable in tests
(Mock all Groq calls in tests).
"""

from __future__ import annotations

import base64
import json
from typing import Callable, Optional

from .extraction_utils import parse_amount as _parse_amount
from .extraction_utils import parse_date as _parse_date

# (image_base64, content_type) -> structured dict from the vision model.
VisionFn = Callable[[str, str], dict]

# Upload validation limits.
ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB

_PROMPT = (
    "You are a receipt-scanning assistant. Extract the following fields from "
    "this receipt image and respond with ONLY a JSON object, no prose:\n"
    '{"merchant": string, "total": number, "date": "YYYY-MM-DD", '
    '"category": string, "line_items": [{"description": string, "amount": number}]}\n'
    "Use null for any field you cannot read. 'total' is the final amount paid."
)


def _default_vision_fn(image_b64: str, content_type: str) -> dict:
    """Call Groq's vision model. Imported lazily so tests never need the SDK."""
    from groq import Groq

    from ..settings import settings

    client = Groq(api_key=settings.groq_api_key)
    response = client.chat.completions.create(
        model=settings.groq_vision_model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _PROMPT},
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
    # The model is asked for a JSON object, but guard against prose / fenced /
    # non-object output so a bad scan yields an empty draft, not a 500/502.
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class ReceiptService:
    """Extracts a transaction draft from a receipt image."""

    def __init__(self, vision_fn: Optional[VisionFn] = None) -> None:
        self.vision_fn = vision_fn or _default_vision_fn

    def extract(self, image_bytes: bytes, content_type: str) -> dict:
        """Return a normalized transaction draft. May raise from ``vision_fn``."""
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        raw = self.vision_fn(image_b64, content_type) or {}
        return self._normalize(raw)

    @staticmethod
    def _normalize(raw: dict) -> dict:
        # Defend against a vision_fn that hands back a non-dict (list, string).
        if not isinstance(raw, dict):
            raw = {}
        merchant = (raw.get("merchant") or None)
        if isinstance(merchant, str):
            merchant = merchant.strip() or None

        line_items = []
        for item in raw.get("line_items") or []:
            if not isinstance(item, dict):
                continue
            line_items.append(
                {
                    "description": item.get("description"),
                    "amount": _parse_amount(item.get("amount")),
                }
            )

        category = raw.get("category")
        if isinstance(category, str):
            category = category.strip() or None

        return {
            "merchant": merchant,
            "title": merchant,  # prefill the transaction title from the merchant
            "amount": _parse_amount(raw.get("total")),
            "date": _parse_date(raw.get("date")),
            "category": category,
            "line_items": line_items,
        }
