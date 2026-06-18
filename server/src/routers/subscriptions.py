"""Subscriptions router.

Surfaces the recurring charges we detect (last and next charge, cadence) for the
"Subscriptions" view and its "cancel?" nudges. Detection happens on read from
the user's expense history, and nothing is saved.

F2: when the Merchant Lifecycle Engine is enabled, each detected subscription is
ENRICHED with its lifecycle snapshot — ``probability_alive`` + a ``status``
stamp (active / lapsing / dormant) and the deterministic price-creep figures.
The snapshot is read-only here (the fit runs in F3's nightly job); reads never
fit inline.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from server.src.db.session import get_db
from server.src.models import UserInDB
from server.src.money import cents_to_dollars
from server.src.services.auth_service import AuthService
from server.src.services.merchant_lifecycle_service import MerchantLifecycleService
from server.src.services.subscription_service import SubscriptionService
from server.src.settings import settings

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.get("/")
def get_subscriptions(
    current_user: Annotated[
        UserInDB, Depends(AuthService.get_current_active_user)
    ],
    db: Session = Depends(get_db),
):
    """Return detected subscriptions, sorted by next expected charge date, each
    enriched with its lifecycle snapshot when the feature is on."""
    subs = SubscriptionService(db).list_subscriptions(current_user.id)
    if not settings.merchant_lifecycle_enabled:
        return subs

    snaps = {
        s["merchant"]: s
        for s in MerchantLifecycleService(db).list_snapshots(current_user.id)
    }
    for sub in subs:
        snap = snaps.get(sub["merchant"])
        if snap is None:
            continue
        sub["probability_alive"] = snap["probability_alive"]
        sub["lifecycle_status"] = snap["status"]
        sub["expected_purchases"] = snap["expected_purchases"]
        if snap.get("price_change_pct") is not None:
            sub["price_change_pct"] = snap["price_change_pct"]
            sub["last_amount"] = cents_to_dollars(snap["last_amount"])
            sub["prev_amount"] = (
                cents_to_dollars(snap["prev_amount"])
                if snap.get("prev_amount")
                else None
            )
    return subs
