"""L6 — Fernet key-id ciphertext versioning + graceful rotation.

Covers the v2 ``enc:v2:<keyid>:`` format, v1 back-compat, decrypt-by-keyid with a
retired key (rotation), wrong-key failure, and the one-shot re-encrypt command.
"""

from __future__ import annotations

import base64
import hashlib

import pytest
from cryptography.fernet import Fernet, InvalidToken

from server.src.db.models import Token as TokenORM, User as UserORM
from server.src.services import plaid_crypto
from server.src.services.plaid_reencrypt import reencrypt_all
from server.src.settings import settings


@pytest.fixture
def _reset_keys():
    """Snapshot + restore key settings and clear caches around each test."""
    orig_key = settings.plaid_token_key
    orig_retired = settings.plaid_token_keys_retired
    plaid_crypto.reset_key_cache()
    yield
    settings.plaid_token_key = orig_key
    settings.plaid_token_keys_retired = orig_retired
    plaid_crypto.reset_key_cache()


def _v1(plaintext: str, key: bytes) -> str:
    """Build an old-format v1 ciphertext under *key*."""
    return "enc:v1:" + Fernet(key).encrypt(plaintext.encode()).decode()


def test_encrypt_writes_v2_with_keyid(_reset_keys):
    settings.plaid_token_key = Fernet.generate_key().decode()
    plaid_crypto.reset_key_cache()
    ct = plaid_crypto.encrypt("access-secret")
    assert ct.startswith("enc:v2:")
    keyid = ct.split(":")[2]
    assert len(keyid) == 8
    assert plaid_crypto.decrypt(ct) == "access-secret"


def test_v1_ciphertext_still_decrypts(_reset_keys):
    """A row written in the original v1 format decrypts under the derived key."""
    settings.plaid_token_key = None  # use the derived key
    plaid_crypto.reset_key_cache()
    derived = base64.urlsafe_b64encode(
        hashlib.sha256(settings.jwt_secret_key.encode()).digest()
    )
    v1 = _v1("legacy-v1-token", derived)
    assert plaid_crypto.is_encrypted(v1)
    assert plaid_crypto.decrypt(v1) == "legacy-v1-token"


def test_rotation_retired_key_still_decrypts(_reset_keys):
    """After rotating to a new active key with the old one retired, old ciphertext
    still decrypts and new writes use the new keyid."""
    key_a = Fernet.generate_key().decode()
    key_b = Fernet.generate_key().decode()

    settings.plaid_token_key = key_a
    settings.plaid_token_keys_retired = None
    plaid_crypto.reset_key_cache()
    ct_a = plaid_crypto.encrypt("token-under-A")
    keyid_a = ct_a.split(":")[2]

    # Rotate: B active, A retired (decrypt-only).
    settings.plaid_token_key = key_b
    settings.plaid_token_keys_retired = key_a
    plaid_crypto.reset_key_cache()

    assert plaid_crypto.decrypt(ct_a) == "token-under-A"  # via retired key
    ct_b = plaid_crypto.encrypt("token-under-B")
    assert ct_b.split(":")[2] != keyid_a  # stamped with the new keyid
    assert plaid_crypto.decrypt(ct_b) == "token-under-B"


def test_wrong_key_raises_invalid_token(_reset_keys):
    key_a = Fernet.generate_key().decode()
    settings.plaid_token_key = key_a
    settings.plaid_token_keys_retired = None
    plaid_crypto.reset_key_cache()
    ct_a = plaid_crypto.encrypt("token")

    # Swap to an unrelated key with nothing retired — A is gone.
    settings.plaid_token_key = Fernet.generate_key().decode()
    plaid_crypto.reset_key_cache()
    with pytest.raises(InvalidToken):
        plaid_crypto.decrypt(ct_a)


def test_reencrypt_migrates_v1_and_retired_to_active(_reset_keys, db_session):
    """The one-shot command rewrites v1 + retired-key rows to the active keyid,
    leaves already-active rows and plaintext untouched, and is idempotent."""
    key_a = Fernet.generate_key().decode()
    key_b = Fernet.generate_key().decode()

    user = UserORM(username="reenc", full_name="R", email="r@x.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()

    # Row 1: v1 ciphertext under key A. Row 2: v2 under A. Row 3: plaintext.
    v1_row = TokenORM(user_id=user.id, name="t1", key=_v1("aaa", key_a.encode()))
    settings.plaid_token_key = key_a
    plaid_crypto.reset_key_cache()
    v2a_row = TokenORM(user_id=user.id, name="t2", key=plaid_crypto.encrypt("bbb"))
    plain_row = TokenORM(user_id=user.id, name="t3", key="plain-token")
    db_session.add_all([v1_row, v2a_row, plain_row])
    db_session.flush()

    # Rotate to B active, A retired, then re-encrypt.
    settings.plaid_token_key = key_b
    settings.plaid_token_keys_retired = key_a
    plaid_crypto.reset_key_cache()
    active_keyid = plaid_crypto._active_keyid()

    counts = reencrypt_all(db_session, dry_run=False)
    db_session.flush()

    assert counts["total"] == 3
    assert counts["rewritten"] == 2  # the v1(A) and v2(A) rows
    assert counts["plaintext_skipped"] == 1
    assert counts["errors"] == 0

    # All ciphertext rows now carry the active (B) keyid and still decrypt.
    db_session.refresh(v1_row)
    db_session.refresh(v2a_row)
    for row, expected in [(v1_row, "aaa"), (v2a_row, "bbb")]:
        assert row.key.startswith(f"enc:v2:{active_keyid}:")
        assert plaid_crypto.decrypt(row.key) == expected
    db_session.refresh(plain_row)
    assert plain_row.key == "plain-token"  # untouched

    # Idempotent: a second run rewrites nothing.
    counts2 = reencrypt_all(db_session, dry_run=False)
    assert counts2["rewritten"] == 0
    assert counts2["already_active"] == 2


def test_reencrypt_dry_run_writes_nothing(_reset_keys, db_session):
    key_a = Fernet.generate_key().decode()
    key_b = Fernet.generate_key().decode()
    user = UserORM(username="dry", full_name="D", email="d@x.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    settings.plaid_token_key = key_a
    plaid_crypto.reset_key_cache()
    row = TokenORM(user_id=user.id, name="t", key=plaid_crypto.encrypt("ccc"))
    db_session.add(row)
    db_session.flush()
    before = row.key

    settings.plaid_token_key = key_b
    settings.plaid_token_keys_retired = key_a
    plaid_crypto.reset_key_cache()
    counts = reencrypt_all(db_session, dry_run=True)
    assert counts["rewritten"] == 1  # would rewrite
    db_session.refresh(row)
    assert row.key == before  # but didn't
