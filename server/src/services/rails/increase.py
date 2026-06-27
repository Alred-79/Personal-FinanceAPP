"""Increase ACH adapter (parent design §3.3) — SANDBOX ONLY.

Originates an ACH credit/debit between the user's own linked accounts via
Increase's ``POST /transfers/ach``. Reads ``increase_sandbox_base_url`` /
``increase_sandbox_api_key`` from settings; there is NO production credential path
in this slice. The Bridge's stable ``verify_ref`` is sent as Increase's
``Idempotency-Key`` header, so a retried ``execute()`` can't double-send at the
rail either. Any HTTP/network failure maps to ``RailError`` so the caller never
sees a half-state.

Unit tests use a ``FakeRail`` (in-memory) double — no live sandbox call. The one
``@pytest.mark.integration`` test that hits the real sandbox is skipped whenever
``increase_sandbox_api_key`` is empty (CI).
"""

from __future__ import annotations

import httpx

from server.src.services.rails.base import (
    FundingDest,
    FundingSource,
    OriginationResult,
    RailError,
)
from server.src.settings import settings

_NAME = "increase"
# Increase ACH transfers are next-day, so origination acceptance is "submitted";
# settlement (and any later return) arrives asynchronously via the webhook.
_SUBMITTED = "submitted"
_TIMEOUT_SECONDS = 20.0


class IncreaseAdapter:
    """Concrete ``RailAdapter`` for Increase's sandbox ACH transfers."""

    name = _NAME

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        # Sandbox host + key only. Empty key is allowed (CI) — a real originate()
        # then simply fails auth at the rail and surfaces as RailError; unit tests
        # never reach here (they use FakeRail).
        self._base_url = (base_url or settings.increase_sandbox_base_url).rstrip("/")
        self._api_key = api_key if api_key is not None else settings.increase_sandbox_api_key
        self._client = client

    def originate(
        self,
        *,
        amount_cents: int,
        source: FundingSource,
        dest: FundingDest,
        idempotency_key: str,
        memo: str,
    ) -> OriginationResult:
        # Increase ACH: a credit FROM the user's source account number TO the
        # destination external account. Sandbox amounts are in cents (positive =
        # credit). We never let a non-positive amount reach the rail.
        if amount_cents <= 0:
            raise RailError("amount_cents must be positive")
        payload = {
            "account_id": source.external_id,
            "destination_account_number_id": dest.external_id,
            "amount": int(amount_cents),
            "statement_descriptor": (memo or "Transfer")[:10],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Idempotency-Key": idempotency_key,
        }
        try:
            resp = self._post("/transfers/ach", json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()
        except httpx.HTTPStatusError as exc:  # 4xx/5xx from the rail
            raise RailError(
                f"increase rejected origination: {exc.response.status_code}"
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:  # network / bad JSON
            raise RailError(f"increase origination failed: {exc}") from exc

        rail_ref = body.get("id")
        if not rail_ref:
            raise RailError("increase returned no transfer id")
        return OriginationResult(
            rail=_NAME, rail_ref=str(rail_ref), settlement_status=_SUBMITTED
        )

    def _post(self, path: str, *, json: dict, headers: dict) -> httpx.Response:
        url = f"{self._base_url}{path}"
        if self._client is not None:
            return self._client.post(url, json=json, headers=headers)
        with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
            return client.post(url, json=json, headers=headers)
