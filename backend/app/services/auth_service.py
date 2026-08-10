from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from pwdlib import PasswordHash


password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    return password_hash.verify(password, encoded_hash)


def create_access_token(
    user_id: UUID,
    *,
    secret_key: str,
    algorithm: str,
    expires_delta: timedelta,
    now: datetime | None = None,
) -> str:
    issued_at = now or datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": issued_at,
        "exp": issued_at + expires_delta,
    }
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def decode_access_token(
    token: str,
    *,
    secret_key: str,
    algorithm: str,
) -> dict[str, Any]:
    return jwt.decode(
        token,
        secret_key,
        algorithms=[algorithm],
        options={"require": ["sub", "iat", "exp"]},
    )
