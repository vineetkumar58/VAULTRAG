"""
jwt_utils.py

Handles signing and verifying JWTs that carry verified identity:
  { "user_id": "...", "tenant_id": "...", "email": "..." }

CRITICAL INVARIANT: tenant_id must NEVER be read from a request body or query
parameter anywhere in this project. It must only ever be read from a verified
JWT (via decode_token below). This is the mechanical foundation of tenant
isolation - see Section 5 of the technical spec.
"""

import os
import time
import jwt  # PyJWT

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me")
JWT_ALGORITHM = "HS256"
TOKEN_TTL_SECONDS = 60 * 60 * 12  # 12 hours


def create_token(user_id: str, tenant_id: str, email: str) -> str:
    """Issue a signed JWT after a successful login."""
    now = int(time.time())
    payload = {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "email": email,
        "iat": now,
        "exp": now + TOKEN_TTL_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Verify and decode a JWT. Raises jwt.InvalidTokenError (or subclasses)
    if the token is expired, tampered with, or malformed.
    Callers MUST let this raise -> caught in handler.py -> return 401.
    """
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def extract_token_from_headers(headers: dict) -> str:
    """
    Pulls the bearer token out of API Gateway's event['headers'].
    Header lookup is case-insensitive since API Gateway can lowercase them.
    """
    auth_header = None
    for key, value in (headers or {}).items():
        if key.lower() == "authorization":
            auth_header = value
            break

    if not auth_header or not auth_header.startswith("Bearer "):
        raise ValueError("Missing or malformed Authorization header")

    return auth_header.split("Bearer ", 1)[1].strip()


def get_verified_tenant_context(event: dict) -> dict:
    """
    Convenience wrapper for Lambda handlers: extract + verify the token from
    the incoming API Gateway event, return {user_id, tenant_id, email}.
    This is the ONLY sanctioned way any handler should learn a request's tenant_id.
    """
    token = extract_token_from_headers(event.get("headers", {}))
    payload = decode_token(token)
    return {
        "user_id": payload["user_id"],
        "tenant_id": payload["tenant_id"],
        "email": payload["email"],
    }
