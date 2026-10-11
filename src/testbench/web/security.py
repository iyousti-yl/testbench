"""Passwords, secret encryption and CSRF tokens. Standard library plus ``cryptography``."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken

# scrypt parameters (n=2**14, r=8, p=1) follow OWASP's minimum recommendation.
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
MIN_PASSWORD_LENGTH = 12


class SecretError(Exception):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), **_SCRYPT)
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


# A hash to verify against when the user does not exist, so timing does not reveal accounts.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def check_password_strength(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must have at least {MIN_PASSWORD_LENGTH} characters")


class SecretBox:
    """Encrypts connection secrets at rest with a key derived from the app secret."""

    def __init__(self, app_secret: str) -> None:
        key = hashlib.sha256(b"testbench-secrets:" + app_secret.encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(key))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise SecretError("cannot decrypt secret: was TESTBENCH_SECRET_KEY changed?") from exc


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_matches(expected: str | None, received: str | None) -> bool:
    return bool(expected and received) and hmac.compare_digest(expected, received)
