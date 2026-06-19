"""One-shot re-encrypt of stored Plaid access tokens to the ACTIVE key (L6).

Graceful key rotation: after setting a new ``PLAID_TOKEN_KEY`` and moving the old
key into ``PLAID_TOKEN_KEYS_RETIRED``, run this to rewrite every token row to
v2 ciphertext under the new active key. Rows already on the active keyid (and, by
default, legacy plaintext rows) are left untouched.

    python -m server.src.services.plaid_reencrypt           # migrate
    python -m server.src.services.plaid_reencrypt --dry-run # report only

Idempotent: a second run is a no-op once every row is on the active key. It NEVER
logs a token or a key — only counts.
"""

from __future__ import annotations

import argparse
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.src.db.models import Token as TokenORM
from server.src.services import plaid_crypto

log = logging.getLogger(__name__)


def reencrypt_all(session: Session, *, dry_run: bool = False) -> dict[str, int]:
    """Re-encrypt every Token to the active key. Returns a counts summary.

    ``{"total", "rewritten", "already_active", "plaintext_skipped", "errors"}``.
    A row whose ciphertext already carries the active keyid is skipped. Legacy
    plaintext rows are counted and skipped (they're handled by the Step-08
    plaintext→ciphertext migration / ``plaid_require_encrypted_tokens``), not
    silently encrypted here.
    """
    active_keyid = plaid_crypto._active_keyid()
    counts = {
        "total": 0,
        "rewritten": 0,
        "already_active": 0,
        "plaintext_skipped": 0,
        "errors": 0,
    }
    tokens = session.execute(select(TokenORM)).scalars().all()
    for token in tokens:
        counts["total"] += 1
        stored = token.key
        if not plaid_crypto.is_encrypted(stored):
            counts["plaintext_skipped"] += 1
            continue
        # Already on the active key? (v2 with a matching keyid) — nothing to do.
        if stored.startswith(plaid_crypto._ENC_PREFIX_V2):
            keyid = stored[len(plaid_crypto._ENC_PREFIX_V2):].partition(":")[0]
            if keyid == active_keyid:
                counts["already_active"] += 1
                continue
        try:
            plaintext = plaid_crypto.decrypt(stored)
        except Exception:
            # Can't decrypt under any available key — surface as an error count;
            # do NOT drop or rewrite the row (a retired key may be missing).
            counts["errors"] += 1
            log.error("re-encrypt: token id=%s could not be decrypted", token.id)
            continue
        if not dry_run:
            token.key = plaid_crypto.encrypt(plaintext)
        counts["rewritten"] += 1
    return counts


def _main() -> int:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Re-encrypt Plaid tokens to the active key.")
    parser.add_argument(
        "--dry-run", action="store_true", help="report counts without writing"
    )
    args = parser.parse_args()

    from server.src.db.session import SessionLocal

    session = SessionLocal()
    try:
        counts = reencrypt_all(session, dry_run=args.dry_run)
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    log.info("plaid re-encrypt %s: %s", "(dry-run)" if args.dry_run else "done", counts)
    return 1 if counts["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(_main())
