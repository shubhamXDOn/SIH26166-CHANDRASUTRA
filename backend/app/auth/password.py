"""M10 password policy.

Reuses the established M0 ``hash_password``/``verify_password``
PBKDF2-HMAC-SHA256 implementation unchanged. Parameter changes would be
configuration-driven and versioned (the stored hash string already encodes
the iteration count). Passwords are never logged, stored in plaintext,
returned through APIs, included in errors, or written to audit/provenance.
"""

from __future__ import annotations

import re

from ..errors import ValidationError
from ..security import hash_password, verify_password
from .config import PasswordPolicy

_UPPER_OR_LOWER_RE = re.compile(r"[A-Za-z]")
_DIGIT_RE = re.compile(r"\d")


def validate_password_policy(
    password: str, *, policy: PasswordPolicy, username: str = "", strict: bool = True
) -> list[str]:
    """Return a list of policy violations (empty when the password passes)."""
    problems: list[str] = []
    if len(password) < policy.min_length:
        problems.append(f"password must be at least {policy.min_length} characters long.")
    if strict or policy.require_letter:
        if policy.require_letter and not _UPPER_OR_LOWER_RE.search(password):
            problems.append("password must contain at least one letter.")
    if policy.require_digit and not _DIGIT_RE.search(password):
        problems.append("password must contain at least one digit.")
    if policy.disallow_username and username and username.lower() in password.lower():
        problems.append("password must not contain the username.")
    return problems


def assert_password_policy(password: str, *, policy: PasswordPolicy, username: str = "") -> None:
    problems = validate_password_policy(password, policy=policy, username=username)
    if problems:
        raise ValidationError(" ".join(problems), details={"password_policy": policy.model_dump()})


def hash_user_password(password: str) -> str:
    """Hash a password with the M0 PBKDF2-HMAC-SHA256 scheme (unique salt)."""
    return hash_password(password)


def verify_user_password(password: str, stored: str) -> bool:
    """Constant-time verify against a stored hash string."""
    try:
        return bool(verify_password(password, stored))
    except (ValueError, TypeError):
        return False


__all__ = [
    "validate_password_policy",
    "assert_password_policy",
    "hash_user_password",
    "verify_user_password",
]