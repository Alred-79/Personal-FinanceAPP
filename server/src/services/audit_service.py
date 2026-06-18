"""F3 — the Nightly Auditor (compose the detectors + narrate).

Proactive beats reactive: rather than wait for the user to open a screen, a
nightly job runs the whole detector battery, assembles a deduped/ranked/capped
batch of findings, and hands a deterministic fact sheet to the narration layer.

**Zero LLM in detection.** Every number is computed by a detector; the LLM (when
wired) only phrases the batch, behind the firewall — the same Law-2 discipline as
the Chronicler. The Auditor composes, it does not compute:

* anomalies + budget overruns — ``NotificationService.generate`` (existing).
* F1 — the calibrated overdraft probability crossing a threshold.
* F2 — zombie standing orders + price creep from the ``MerchantLifecycle``
  snapshot, which this job also REFRESHES (it owns the periodic fit).

Each finding becomes one typed, idempotent notification (stable ``ref`` →
``_add_if_new`` dedups a re-fire). The auditor-specific findings are ranked by
severity and **capped** per night (alert fatigue is the real constraint — the
user's attention, not compute). Finally one narration of the batch is screened by
``firewall.screen_output`` and cached in ``LlmCache``, then written as the
``audit_digest`` notice. Deterministic + idempotent for the scheduler.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from ..money import cents_to_dollars
from ..settings import settings
from .game.firewall import screen_output

logger = logging.getLogger(__name__)

# Fixed seed for the overdraft probe so a nightly re-check on unchanged reality is
# noise-free (the same discipline the drift job uses).
_AUDIT_SEED = 0
MODEL_NAME = "llama-3.3-70b-versatile"
TEMPLATE_VERSION = "v1"


@dataclass(frozen=True)
class Finding:
    """One detector result, pre-narration. ``severity`` orders the cap."""

    type: str
    title: str
    message: str
    ref: str
    severity: int  # higher = surfaced first when the batch is capped
    deep_link: Optional[str] = None


class AuditService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── detection (pure composition; no LLM) ────────────────────────────────

    def _overdraft_finding(self, user, as_of: date) -> Optional[Finding]:
        """F1: raise a notice when the calibrated overdraft probability crosses
        the threshold over the Safe-to-Spend horizon."""
        from .spend_service import SpendService

        s2s = SpendService(self.db).safe_to_spend(
            user, as_of, include_outlook=True, rng=random.Random(_AUDIT_SEED)
        )
        prob = s2s.get("overdraft_probability")
        if prob is None or prob < settings.auditor_overdraft_threshold:
            return None
        low = s2s.get("trough_band", {}).get("low")
        period = as_of.strftime("%Y-%m")
        pct = round(prob * 100)
        floor = f" Your low point could reach {low:,.0f}." if low is not None else ""
        return Finding(
            type="overdraft_risk",
            title="Overdraft risk on the horizon",
            message=(
                f"There's about a {pct}% chance your balance dips below zero "
                f"before {s2s['horizon_end']}.{floor}"
            ),
            ref=f"audit:overdraft:{user.id}:{period}",
            severity=100,
            deep_link="/forecast",
        )

    def _lifecycle_findings(self, user, as_of: date) -> list[Finding]:
        """F2: refresh the lifecycle snapshot (this job owns the fit), then flag
        zombie standing orders + price creep from it."""
        from .merchant_lifecycle_service import MerchantLifecycleService

        if not settings.merchant_lifecycle_enabled:
            return []
        svc = MerchantLifecycleService(self.db)
        snaps = svc.refresh(user.id, as_of=as_of)
        period = as_of.strftime("%Y-%m")
        findings: list[Finding] = []
        for s in snaps:
            # Nudge on any non-active standing order (lapsing OR dormant) — the
            # status comes straight from the BG/NBD snapshot's probability_alive.
            if s["status"] != "active":
                pct = round(s["probability_alive"] * 100)
                dormant = s["status"] == "dormant"
                label = "looks dormant" if dormant else "may have lapsed"
                findings.append(
                    Finding(
                        type="merchant_lifecycle",
                        title=f"Standing order {label}: {s['title']}",
                        message=(
                            f"{s['title']} usually recurs but has gone quiet — "
                            f"about a {pct}% chance it's still active. "
                            "Check whether it should be cancelled."
                        ),
                        ref=f"audit:lifecycle:{user.id}:{s['merchant']}:{period}",
                        # the deader it looks, the higher it ranks
                        severity=(90 if dormant else 70) + (100 - pct) // 20,
                        deep_link="/subscriptions",
                    )
                )
            if s.get("price_change_pct"):
                rise = round(s["price_change_pct"] * 100)
                last = cents_to_dollars(s["last_amount"])
                prev = (
                    cents_to_dollars(s["prev_amount"])
                    if s.get("prev_amount")
                    else None
                )
                was = f" (was {prev:,.2f})" if prev is not None else ""
                findings.append(
                    Finding(
                        type="price_creep",
                        title=f"Price increase: {s['title']}",
                        message=(
                            f"{s['title']} rose about {rise}% this cycle to "
                            f"{last:,.2f}{was}."
                        ),
                        ref=f"audit:price_creep:{user.id}:{s['merchant']}:{s['last_date']}",
                        severity=60,
                        deep_link="/subscriptions",
                    )
                )
        return findings

    def _rank_and_cap(self, findings: list[Finding]) -> list[Finding]:
        """Highest severity first, then capped — the alert-fatigue guard. The cap
        is logged (never a silent truncation)."""
        ranked = sorted(findings, key=lambda f: f.severity, reverse=True)
        cap = settings.auditor_max_findings
        if len(ranked) > cap:
            logger.info(
                "auditor cap: %d findings, surfacing top %d", len(ranked), cap
            )
            ranked = ranked[:cap]
        return ranked

    # ── narration (deterministic facts → optional LLM → firewall → cache) ────

    def _fact_sheet(self, findings: list[Finding], as_of: date) -> dict:
        counts: dict[str, int] = {}
        for f in findings:
            counts[f.type] = counts.get(f.type, 0) + 1
        return {
            "date": as_of.isoformat(),
            "n_findings": len(findings),
            "counts": dict(sorted(counts.items())),
        }

    def _narrate(
        self,
        fact_sheet: dict,
        llm_call: Optional[Callable[[str], str]],
    ) -> str:
        """One narration of the batch. Deterministic template by default; an
        optional ``llm_call`` may phrase it. Either way it is screened by the
        advice firewall and the result is cached in ``LlmCache``."""
        from ..db.models import LlmCache

        cache_key = _digest_cache_key(fact_sheet)
        cached = self.db.get(LlmCache, cache_key)
        if cached is not None:
            return cached.content

        text = _template_digest(fact_sheet)
        if llm_call is not None:
            try:
                raw = llm_call(_digest_prompt(fact_sheet))
                if raw and raw.strip():
                    text = raw.strip()
            except Exception:  # noqa: BLE001 — fall back to the template
                logger.exception("auditor narration llm_call failed")

        # Firewall: the narration must never carry advice/shame/neediness.
        verdict = screen_output(text)
        safe = verdict.safe_text if verdict.blocked else text

        self.db.add(
            LlmCache(
                cache_key=cache_key,
                kind="audit_digest",
                content=safe,
                model=MODEL_NAME,
                created_at=datetime.now(timezone.utc).isoformat(),
                expires_at=None,
            )
        )
        return safe

    # ── orchestration ──────────────────────────────────────────────────────

    def run(
        self,
        user_id: int,
        *,
        as_of: Optional[date] = None,
        llm_call: Optional[Callable[[str], str]] = None,
    ) -> dict[str, Any]:
        """Run the nightly audit for one user. Idempotent + deterministic.

        Writes one typed notification per finding (deduped by ``ref``) plus one
        ``audit_digest`` notice carrying the narrated batch summary. Returns the
        counts for the scheduler."""
        from .notification_service import NotificationService
        from .read_queries import query_user

        as_of = as_of or date.today()
        user = query_user(self.db, user_id)
        if user is None:
            return {"findings": 0, "created": 0}

        notif = NotificationService(self.db)
        # Existing detectors (anomaly + budget overrun) — idempotent on their refs.
        base = notif.generate(user_id, as_of)

        # Auditor-specific findings: F1 overdraft + F2 lifecycle/price-creep.
        findings: list[Finding] = []
        try:
            od = self._overdraft_finding(user, as_of)
            if od is not None:
                findings.append(od)
        except Exception:  # noqa: BLE001 — one detector can't abort the batch
            logger.exception("auditor overdraft probe failed: user=%s", user_id)
        try:
            findings.extend(self._lifecycle_findings(user, as_of))
        except Exception:  # noqa: BLE001
            logger.exception("auditor lifecycle probe failed: user=%s", user_id)

        ranked = self._rank_and_cap(findings)
        created = list(base)
        for f in ranked:
            row = notif._add_if_new(
                user_id, type=f.type, title=f.title, message=f.message, ref=f.ref
            )
            if row is not None:
                created.append(row)

        # Narrate the batch (one call, firewalled + cached) → digest notice.
        digest_written = False
        all_new = len(created)
        if all_new:
            fact_sheet = self._fact_sheet(ranked, as_of)
            narration = self._narrate(fact_sheet, llm_call)
            digest = notif._add_if_new(
                user_id,
                type="audit_digest",
                title="The night's review",
                message=narration,
                ref=f"audit:digest:{user_id}:{as_of.isoformat()}",
            )
            digest_written = digest is not None

        self.db.flush()
        return {
            "findings": len(ranked),
            "base": len(base),
            "created": len(created),
            "digest": digest_written,
        }


# ── module-level narration helpers (pure) ───────────────────────────────────


def _digest_cache_key(fact_sheet: dict) -> str:
    fs_hash = hashlib.sha256(
        json.dumps(fact_sheet, sort_keys=True).encode()
    ).hexdigest()
    raw = f"{MODEL_NAME}|{TEMPLATE_VERSION}|audit|{fs_hash}"
    return hashlib.sha256(raw.encode()).hexdigest()


_KIND_PHRASE = {
    "overdraft_risk": "an overdraft risk on the horizon",
    "merchant_lifecycle": "standing orders that have gone quiet",
    "price_creep": "a subscription whose price has crept up",
    "anomaly": "an unusual charge",
    "budget_overrun": "a budget run past its limit",
}


def _template_digest(fact_sheet: dict) -> str:
    """A fully deterministic, factual digest — no advice, so the firewall passes
    it. The app owns the numbers (this template IS the app)."""
    counts: dict[str, int] = fact_sheet.get("counts", {})
    if not counts:
        return "The night's review found nothing new to flag."
    parts: list[str] = []
    for kind, n in counts.items():
        phrase = _KIND_PHRASE.get(kind, "a finding")
        parts.append(f"{n} ({phrase})" if n > 1 else phrase)
    joined = "; ".join(parts)
    return f"The night's review surfaced {joined}. Details are in your notices."


def _digest_prompt(fact_sheet: dict) -> str:
    return (
        "You are an even-handed financial auditor writing a one-sentence summary "
        "of tonight's findings. State only what the fact sheet says, give NO "
        "advice, never shame the user, and do not invent numbers.\n\n"
        f"FACT SHEET:\n{json.dumps(fact_sheet, sort_keys=True)}\n\n"
        "Return a single plain-text sentence."
    )
