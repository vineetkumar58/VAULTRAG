"""
handler.py (auth)

Handles all three onboarding endpoints (Section 5 of the technical spec):
  POST /auth/signup   { email, password, org_name? , invite_token? }
  POST /auth/login     { email, password }
  POST /auth/invite     { email }  (requires Authorization header - admin only)

CRITICAL INVARIANT: tenant_id is only ever assigned by this backend -
from a brand-new tenant record (first signup), or read off an invite record
(subsequent signups). It is never accepted as raw input from the client.
"""

import json
import bcrypt

from jwt_utils import create_token, get_verified_tenant_context
from dynamo_utils import (
    create_tenant, create_user, get_user_by_email,
    create_invite, get_invite, mark_invite_accepted,
)
// these are the headers cors
CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}


def _response(status_code: int, body: dict):
    return {"statusCode": status_code, "headers": CORS_HEADERS, "body": json.dumps(body)}


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def handle_signup(body: dict):
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")
    org_name = body.get("org_name")
    invite_token = body.get("invite_token")

    if not email or not password:
        return _response(400, {"error": "email and password are required"})

    if get_user_by_email(email):
        return _response(409, {"error": "An account with this email already exists"})

    # Case A: joining via an invite -> tenant_id comes from the invite record
    if invite_token:
        invite = get_invite(invite_token)
        if not invite or invite["status"] != "pending":
            return _response(400, {"error": "Invalid or already-used invite token"})
        if invite["email"] != email:
            return _response(400, {"error": "Invite was issued to a different email address"})

        tenant_id = invite["tenant_id"]
        mark_invite_accepted(invite_token)

    # Case B: first user of a brand-new org -> a new tenant is created
    elif org_name:
        tenant_id = create_tenant(org_name)

    else:
        return _response(400, {"error": "Provide either an invite_token or an org_name"})

    password_hash = _hash_password(password)
    user_id = create_user(email=email, password_hash=password_hash, tenant_id=tenant_id)

    token = create_token(user_id=user_id, tenant_id=tenant_id, email=email)
    return _response(201, {"token": token, "tenant_id": tenant_id, "user_id": user_id})


def handle_login(body: dict):
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")

    user = get_user_by_email(email)
    if not user or not _verify_password(password, user["password_hash"]):
        # Same error for "no such user" and "wrong password" - don't leak which one
        return _response(401, {"error": "Invalid email or password"})

    token = create_token(user_id=user["user_id"], tenant_id=user["tenant_id"], email=email)
    return _response(200, {"token": token, "tenant_id": user["tenant_id"]})


def handle_invite(event, body: dict):
    # Only an already-authenticated user (an org admin) can invite others.
    # tenant_id for the invite comes from the INVITER's own verified token -
    # so a user can only ever invite people into their own org.
    try:
        identity = get_verified_tenant_context(event)
    except Exception as e:
        return _response(401, {"error": f"Unauthorized: {e}"})

    invited_email = body.get("email", "").strip().lower()
    if not invited_email:
        return _response(400, {"error": "email is required"})

    invite_token = create_invite(email=invited_email, tenant_id=identity["tenant_id"])
    # In production: email `invite_token` to invited_email via SES rather than returning it.
    return _response(201, {"invite_token": invite_token})


def lambda_handler(event, context):
    path = event.get("rawPath", "")
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "Invalid JSON body"})

    if path.endswith("/auth/signup"):
        return handle_signup(body)
    if path.endswith("/auth/login"):
        return handle_login(body)
    if path.endswith("/auth/invite"):
        return handle_invite(event, body)

    return _response(404, {"error": f"Unknown route: {path}"})
