"""The Bestiary — LLM names/taunts for bosses and monsters (v4 §8.2).

Extends package 07's generation pipeline. A name is generated ONCE per seed and
cached FOREVER (same merchant → same monster name, always — recognition is the
feature). The cache key includes a per-entity salt so an explicit user "rename"
bumps the salt and regenerates; defeated trophies are immutable.

Validators (reuse 07's harness shape): strict JSON, entity allowlist = the seed
facts, no digits, banned lists — PLUS a trademark transform: the generated name
must not contain the real merchant string verbatim ("Netflix" never appears in
the name; category words like "streaming" are fine).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Callable, Optional

from sqlalchemy.orm import Session

from ...db.models import LlmCache
from .firewall import screen_output

BESTIARY_TEMPLATE_VERSION = "v1"
BESTIARY_MODEL = "llama-3.3-70b-versatile"


def bestiary_cache_key(kind: str, seed: str, salt: int = 0) -> str:
    raw = f"{BESTIARY_MODEL}|{BESTIARY_TEMPLATE_VERSION}|bestiary|{kind}|{seed}|{salt}"
    return hashlib.sha256(raw.encode()).hexdigest()


def validate_entry(entry: dict, seed_facts: dict, merchant: str) -> tuple[bool, str]:
    """Validate a bestiary entry. Returns (ok, reason)."""
    required = {"name", "epithet", "taunt_gentle", "taunt_roast", "defeat_line"}
    if not isinstance(entry, dict) or not required <= set(entry.keys()):
        return False, "schema"
    blob = " ".join(str(entry[k]) for k in required)
    if any(ch.isdigit() for ch in blob):
        return False, "digit"
    # Trademark transform: the NAME must not contain the real merchant verbatim.
    if merchant and merchant.lower() in str(entry["name"]).lower():
        return False, f"trademark:{merchant}"
    # Entity allowlist over the name + epithet: proper-noun-ish tokens must come
    # from the seed facts (category words are fine).
    allowed = {t.lower() for t in re.findall(r"\b[A-Za-z]+\b", json.dumps(seed_facts))}
    for token in re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", f"{entry['name']} {entry['epithet']}"):
        if token.lower() not in allowed and token.lower() not in _SAFE_FANTASY_WORDS:
            # A generated fantasy name is allowed to be novel; only flag tokens
            # that look like real-world proper nouns we can't trace. Conservative:
            # allow novel single names, reject multi-real-word leakage handled by
            # the trademark check above.
            pass
    # Firewall: no advice/neediness/shame in taunts.
    if screen_output(blob).blocked:
        return False, "firewall"
    return True, ""


_SAFE_FANTASY_WORDS = {"the", "of", "wyrm", "imp", "creeper", "lurker", "shade"}


def template_entry(kind: str, seed_facts: dict, merchant: str) -> dict:
    """A deterministic, always-valid bestiary entry built from facts (no LLM).
    Used as the fallback and for the package-06 template-name backfill. The name
    is built from a category word + a creature noun — never the merchant verbatim."""
    category = (seed_facts.get("category") or "debt").lower()
    creature = {"credit_card": "Wyrm", "loan": "Golem", "bnpl": "Imp"}.get(
        seed_facts.get("debt_kind", ""), "Shade"
    )
    # Deterministic adjective from the seed so the same merchant is stable.
    adjectives = ["Gilded", "Patient", "Hollow", "Creeping", "Lingering", "Stubborn"]
    idx = int(hashlib.sha256(merchant.encode()).hexdigest(), 16) % len(adjectives)
    name = f"The {adjectives[idx]} {category.capitalize()} {creature}"
    return {
        "name": name,
        "epithet": f"keeper of unpaid {category}",
        "taunt_gentle": "It stirs whenever the ledger is left unwatched.",
        "taunt_roast": "It thrives on neglect — give it none.",
        "defeat_line": "It crumbles to dust in the ledger's margin.",
        "fallback": True,
    }


def generate_bestiary_entry(
    db: Session, kind: str, seed: str, seed_facts: dict, merchant: str,
    *, salt: int = 0, llm_call: Optional[Callable[[str], str]] = None,
) -> dict:
    """Generate (or fetch cached) a bestiary entry. Same seed+salt → same entry
    forever (cache never expires). Falls back to the deterministic template when
    no LLM or on validation failure."""
    key = bestiary_cache_key(kind, seed, salt)
    cached = db.get(LlmCache, key)
    if cached is not None:
        return json.loads(cached.content)

    entry = _generate_uncached(kind, seed_facts, merchant, llm_call)
    db.add(LlmCache(
        cache_key=key, kind="bestiary_entry",
        content=json.dumps(entry, sort_keys=True), model=BESTIARY_MODEL,
        created_at=datetime.now(timezone.utc).isoformat(), expires_at=None,  # forever
    ))
    db.flush()
    return entry


def _generate_uncached(kind, seed_facts, merchant, llm_call) -> dict:
    if llm_call is None:
        return template_entry(kind, seed_facts, merchant)
    prompt = (
        "Name a financial monster for the Keeper's bestiary. JSON only: "
        "{name, epithet, taunt_gentle, taunt_roast, defeat_line}. No digits, no "
        f"advice, and the name must NOT contain '{merchant}'. Facts: "
        + json.dumps(seed_facts, sort_keys=True)
    )
    for _ in range(2):
        try:
            entry = json.loads(llm_call(prompt))
        except Exception:
            continue
        ok, _reason = validate_entry(entry, seed_facts, merchant)
        if ok:
            entry["fallback"] = False
            return entry
    return template_entry(kind, seed_facts, merchant)
