"""Plaid API client. Wraps the ``plaid-python`` SDK.

Sign convention (spelled out for clarity):
    Plaid ``amount > 0``  → money **leaving** the user's account (an expense or debit)
    Plaid ``amount < 0``  → money **entering** the user's account (income or a credit)

This module does NOT interpret the sign; the callers (PlaidService) do that.
"""

import plaid
from dataclasses import dataclass, field
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.item_public_token_exchange_request import (
    ItemPublicTokenExchangeRequest,
)
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest

from server.src.settings import settings

# Connect / read timeout (seconds) for every Plaid HTTP call. plaid-python 40.x
# passes this straight to urllib3 as a (connect, read) pair. Without it a hung
# Plaid endpoint would block the sync BackgroundTask thread indefinitely (B4).
_PLAID_TIMEOUT = (5, 30)


@dataclass
class SyncResult:
    """Container for a Plaid /transactions/sync response cycle."""

    added: list = field(default_factory=list)
    modified: list = field(default_factory=list)
    removed: list = field(default_factory=list)
    next_cursor: str = ""


@dataclass
class SyncPage:
    """One page of a Plaid /transactions/sync cycle (L5 per-page checkpointing).

    ``next_cursor`` is the cursor to persist AFTER applying this page; ``has_more``
    says whether another page follows. The service applies+commits each page under
    its own cursor so a mid-pagination failure resumes from the last good page
    rather than re-pulling from the start.
    """

    added: list = field(default_factory=list)
    modified: list = field(default_factory=list)
    removed: list = field(default_factory=list)
    next_cursor: str = ""
    has_more: bool = False


class PlaidClient:
    def __init__(self):
        self.config = plaid.Configuration(
            host=(
                plaid.Environment.Sandbox
                if settings.plaid_environment == "sandbox"
                else plaid.Environment.Production
            ),
            api_key={
                "clientId": settings.plaid_client_id,
                "secret": settings.plaid_client_secret,
            },
        )
        self.api_client = plaid.ApiClient(self.config)
        self.client = plaid_api.PlaidApi(self.api_client)

    def create_link_token(self, user_id: str) -> str:
        """
        Create a link token for initializing Plaid Link

        Args:
            user_id: The ID of the user to create the link token for

        Returns:
            str: The link token to be used on the client side
        """
        request = LinkTokenCreateRequest(
            user=LinkTokenCreateRequestUser(client_user_id=user_id),
            client_name="Finance-Tracker",
            products=[
                Products("transactions")
            ],  # List of Plaid products you want to use
            country_codes=[CountryCode("US")],  # List of supported country codes
            language="en",  # Language for the Link interface
        )

        response = self.client.link_token_create(
            request, _request_timeout=_PLAID_TIMEOUT
        )
        return response["link_token"]

    def exchange_public_token(self, public_token: str) -> str:
        request = ItemPublicTokenExchangeRequest(public_token=public_token)
        response = self.client.item_public_token_exchange(
            request, _request_timeout=_PLAID_TIMEOUT
        )
        return response["access_token"]

    def get_balance(self, token: str):
        request = AccountsBalanceGetRequest(access_token=token)
        response = self.client.accounts_balance_get(
            request, _request_timeout=_PLAID_TIMEOUT
        )
        return response["accounts"]

    def sync_transactions(self, access_token: str, cursor: str = "") -> SyncResult:
        """Incremental sync driven by a cursor via Plaid ``/transactions/sync``.

        Paginates until ``has_more`` is ``False``, then returns all added,
        modified, and removed transactions along with the new cursor to
        persist for the next call.

        Args:
            access_token: Plaid access token for the item.
            cursor: The cursor from the previous sync call.  Pass ``""``
                (empty string) for the initial historical pull.

        Returns:
            SyncResult with added/modified/removed dicts and next_cursor.
        """
        added: list = []
        modified: list = []
        removed: list = []
        has_more = True

        while has_more:
            request = TransactionsSyncRequest(
                access_token=access_token,
                cursor=cursor,
            )
            response = self.client.transactions_sync(
                request, _request_timeout=_PLAID_TIMEOUT
            )

            added.extend([t.to_dict() for t in response["added"]])
            modified.extend([t.to_dict() for t in response["modified"]])
            removed.extend([t.to_dict() for t in response["removed"]])
            cursor = response["next_cursor"]
            has_more = response["has_more"]

        return SyncResult(
            added=added,
            modified=modified,
            removed=removed,
            next_cursor=cursor,
        )

    def sync_transactions_pages(self, access_token: str, cursor: str = ""):
        """Yield Plaid /transactions/sync results ONE PAGE at a time (L5).

        Unlike :meth:`sync_transactions` (which accumulates every page in memory
        and returns one result), this is a generator so the caller can apply and
        commit each page under its own cursor before the next is fetched — bounding
        memory on a large initial pull and making a mid-pagination failure
        resumable from the last persisted cursor instead of restarting from ``""``.
        """
        has_more = True
        while has_more:
            request = TransactionsSyncRequest(
                access_token=access_token,
                cursor=cursor,
            )
            response = self.client.transactions_sync(
                request, _request_timeout=_PLAID_TIMEOUT
            )
            cursor = response["next_cursor"]
            has_more = response["has_more"]
            yield SyncPage(
                added=[t.to_dict() for t in response["added"]],
                modified=[t.to_dict() for t in response["modified"]],
                removed=[t.to_dict() for t in response["removed"]],
                next_cursor=cursor,
                has_more=has_more,
            )
