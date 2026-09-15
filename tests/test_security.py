"""Authentication/authorization foundation tests."""

from __future__ import annotations

import pytest

from backend.app.config import Settings
from backend.app.errors import UnauthorizedError
from backend.app.security import (
    Role,
    UserCreate,
    UserInDB,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_user_schema_rejects_weak_password():
    with pytest.raises(Exception):
        UserCreate(username="alice", password="short", role=Role.ANALYST)


def test_user_in_db_never_serializes_password_hash():
    user = UserInDB(
        username="alice",
        display_name="Alice",
        role=Role.ANALYST,
        password_hash="pbkdf2_sha256$...",
    )
    public = user.public_view()
    assert "password_hash" not in public
    assert public["username"] == "alice"


def test_password_hash_roundtrip_and_no_plaintext():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert "correct horse battery staple" not in hashed
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_salts_make_hashes_unique():
    a = hash_password("same-password")
    b = hash_password("same-password")
    assert a != b


def test_token_roundtrip_with_configured_secret():
    settings = Settings(
        auth_secret_key="t0ken-test-secret-000000000000000000000000000000000000", _env_file=None
    )
    token = create_access_token(settings, subject="alice", role=Role.ANALYST)
    claims = decode_access_token(settings, token)
    assert claims["sub"] == "alice"
    assert claims["role"] == "analyst"
    assert claims["iss"] == "SIH26166"


def test_token_forged_does_not_verify():
    secret = "t0ken-test-secret-000000000000000000000000000000000000"
    settings = Settings(auth_secret_key=secret, _env_file=None)
    other = Settings(auth_secret_key="different-secret-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", _env_file=None)
    token = create_access_token(settings, subject="alice", role=Role.ANALYST)
    with pytest.raises(UnauthorizedError):
        decode_access_token(other, token)


def test_token_create_requires_configured_secret():
    settings = Settings(auth_secret_key="", _env_file=None)
    with pytest.raises(UnauthorizedError):
        create_access_token(settings, subject="alice", role=Role.ANALYST)