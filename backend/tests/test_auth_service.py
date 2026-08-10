from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from app.services.auth_service import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


TEST_SECRET = "unit-test-jwt-secret-at-least-32-bytes"
OTHER_TEST_SECRET = "different-unit-test-jwt-secret-32-bytes"


def test_argon2_password_hash_and_verify():
    encoded = hash_password("correct-password")

    assert encoded != "correct-password"
    assert encoded.startswith("$argon2")
    assert verify_password("correct-password", encoded) is True
    assert verify_password("wrong-password", encoded) is False


def test_access_token_contains_only_required_identity_and_time_claims():
    user_id = uuid4()
    issued_at = datetime.now(UTC).replace(microsecond=0)
    token = create_access_token(
        user_id,
        secret_key=TEST_SECRET,
        algorithm="HS256",
        expires_delta=timedelta(minutes=60),
        now=issued_at,
    )

    payload = decode_access_token(
        token,
        secret_key=TEST_SECRET,
        algorithm="HS256",
    )

    assert payload["sub"] == str(user_id)
    assert payload["iat"] == int(issued_at.timestamp())
    assert payload["exp"] == int((issued_at + timedelta(minutes=60)).timestamp())
    assert set(payload) == {"sub", "iat", "exp"}


def test_access_token_rejects_invalid_signature():
    token = create_access_token(
        uuid4(),
        secret_key=TEST_SECRET,
        algorithm="HS256",
        expires_delta=timedelta(minutes=60),
    )

    with pytest.raises(jwt.InvalidSignatureError):
        decode_access_token(
            token,
            secret_key=OTHER_TEST_SECRET,
            algorithm="HS256",
        )


def test_access_token_rejects_expired_token():
    token = create_access_token(
        uuid4(),
        secret_key=TEST_SECRET,
        algorithm="HS256",
        now=datetime.now(UTC) - timedelta(minutes=2),
        expires_delta=timedelta(minutes=1),
    )

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(
            token,
            secret_key=TEST_SECRET,
            algorithm="HS256",
        )
