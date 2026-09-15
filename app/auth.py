"""Per-user authentication and role-based access control.

Two credential paths are accepted on protected routes:
  - X-API-Key: settings.admin_api_key  (unchanged; treated as full admin —
    kept for the trusted machine/service integrations and demo scripts that
    already use it, so nothing existing breaks).
  - Authorization: Bearer <JWT>  (new; per-user, carries a role).

Roles, least to most privileged: viewer < auditor < admin.
  - viewer:  read-only (dashboard, orders, products, metrics)
  - auditor: viewer + can decide manual-review audits
  - admin:   auditor + order intake, retries, user management
"""
import hashlib
import hmac
import secrets
import time
from datetime import timedelta
from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
import jwt
from app.config import settings

ROLE_RANK = {"viewer": 0, "auditor": 1, "admin": 2}

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()
    return f"pbkdf2_sha256$200000${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
        return hmac.compare_digest(candidate, digest)
    except (ValueError, AttributeError):
        return False


def create_access_token(user_id: str, email: str, role: str) -> str:
    now = int(time.time())
    payload = {"sub": user_id, "email": email, "role": role, "iat": now,
               "exp": now + int(timedelta(minutes=settings.jwt_expire_minutes).total_seconds())}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


class Principal:
    def __init__(self, role: str, email: str | None = None, user_id: str | None = None):
        self.role, self.email, self.user_id = role, email, user_id


def require_role(minimum: str):
    """FastAPI dependency: accepts a valid admin API key (always sufficient)
    or a valid Bearer JWT whose role meets the minimum rank."""
    def dependency(api_key: str | None = Depends(_api_key_header),
                   creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Principal:
        if api_key and secrets.compare_digest(api_key, settings.admin_api_key):
            return Principal(role="admin")
        if creds:
            payload = decode_access_token(creds.credentials)
            if payload and ROLE_RANK.get(payload.get("role"), -1) >= ROLE_RANK[minimum]:
                return Principal(role=payload["role"], email=payload.get("email"), user_id=payload.get("sub"))
        raise HTTPException(401, "Missing or insufficient credentials")
    return dependency
