"""
dynamo_utils.py

Thin wrappers around DynamoDB for the four tables described in Section 3 of
the technical spec: Tenants, Users, Invites, ConversationHistory.

Table names are read from environment variables so the same code works across
dev/staging/prod without changes (Terraform injects these at deploy time).
"""

import os
import time
import uuid
import boto3
from boto3.dynamodb.conditions import Key

dynamodb = boto3.resource("dynamodb")

TENANTS_TABLE = os.environ.get("TENANTS_TABLE", "vaultrag-dev-Tenants")
USERS_TABLE = os.environ.get("USERS_TABLE", "vaultrag-dev-Users")
INVITES_TABLE = os.environ.get("INVITES_TABLE", "vaultrag-dev-Invites")
HISTORY_TABLE = os.environ.get("HISTORY_TABLE", "vaultrag-dev-ConversationHistory")
DOCUMENTS_TABLE = os.environ.get("DOCUMENTS_TABLE", "vaultrag-dev-Documents")


# --- Tenants ---

def create_tenant(org_name: str) -> str:
    tenant_id = f"org-{uuid.uuid4().hex[:8]}"
    table = dynamodb.Table(TENANTS_TABLE)
    table.put_item(Item={
        "tenant_id": tenant_id,
        "org_name": org_name,
        "created_at": int(time.time()),
    })
    return tenant_id


# --- Users ---

def get_user_by_email(email: str):
    """
    Looks up a user via the EmailIndex GSI (base table is keyed by user_id,
    which we don't know yet at login time - see Section 3.2 of the spec).
    """
    table = dynamodb.Table(USERS_TABLE)
    response = table.query(
        IndexName="EmailIndex",
        KeyConditionExpression=Key("email").eq(email),
    )
    items = response.get("Items", [])
    return items[0] if items else None


def create_user(email: str, password_hash: str, tenant_id: str) -> str:
    """
    tenant_id is written onto the user's own row, once, here. This is the only
    place tenant_id is ever assigned to a user - never chosen by the user.
    """
    user_id = f"u-{uuid.uuid4().hex[:12]}"
    table = dynamodb.Table(USERS_TABLE)
    table.put_item(Item={
        "user_id": user_id,
        "email": email,
        "password_hash": password_hash,
        "tenant_id": tenant_id,
        "created_at": int(time.time()),
    })
    return user_id


# --- Invites ---

def create_invite(email: str, tenant_id: str) -> str:
    invite_token = uuid.uuid4().hex
    table = dynamodb.Table(INVITES_TABLE)
    table.put_item(Item={
        "invite_token": invite_token,
        "email": email,
        "tenant_id": tenant_id,
        "status": "pending",
        "created_at": int(time.time()),
        "expires_at": int(time.time()) + 60 * 60 * 24 * 7,  # 7 days, matches DynamoDB TTL attribute
    })
    return invite_token


def get_invite(invite_token: str):
    table = dynamodb.Table(INVITES_TABLE)
    response = table.get_item(Key={"invite_token": invite_token})
    return response.get("Item")


def mark_invite_accepted(invite_token: str):
    table = dynamodb.Table(INVITES_TABLE)
    table.update_item(
        Key={"invite_token": invite_token},
        UpdateExpression="SET #s = :accepted",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":accepted": "accepted"},
    )


# --- Conversation history ---

def get_recent_turns(tenant_id: str, session_id: str, limit: int = 3):
    """
    Fetches the last `limit` turns for this session, scoped by tenant_id.
    Partition key is prefixed with tenant_id (see Section 3.4 of the spec)
    so history for different tenants never collides even if session_ids clash.
    """
    scoped_session_id = f"{tenant_id}#{session_id}"
    table = dynamodb.Table(HISTORY_TABLE)
    response = table.query(
        KeyConditionExpression=Key("session_id").eq(scoped_session_id),
        ScanIndexForward=False,  # most recent first
        Limit=limit,
    )
    items = response.get("Items", [])
    return list(reversed(items))  # chronological order for prompt assembly


def save_turn(tenant_id: str, session_id: str, turn_number: int, question: str, answer: str):
    scoped_session_id = f"{tenant_id}#{session_id}"
    table = dynamodb.Table(HISTORY_TABLE)
    table.put_item(Item={
        "session_id": scoped_session_id,
        "turn_number": turn_number,
        "tenant_id": tenant_id,
        "question": question,
        "answer": answer,
        "timestamp": int(time.time()),
    })


# --- Documents (tracks upload -> ingestion status, enables list/delete) ---

def create_document_record(tenant_id: str, document_id: str, filename: str, s3_key: str):
    """Called at upload time (status='pending'), before ingestion has run."""
    table = dynamodb.Table(DOCUMENTS_TABLE)
    table.put_item(Item={
        "tenant_id": tenant_id,
        "document_id": document_id,
        "filename": filename,
        "s3_key": s3_key,
        "status": "pending",
        "uploaded_at": int(time.time()),
    })


def update_document_status(tenant_id: str, document_id: str, status: str, chunk_count: int = None):
    """Called by the ingestion Lambda once chunking/embedding finishes (or fails)."""
    table = dynamodb.Table(DOCUMENTS_TABLE)
    update_expr = "SET #s = :status"
    expr_values = {":status": status}
    expr_names = {"#s": "status"}

    if chunk_count is not None:
        update_expr += ", chunk_count = :cc"
        expr_values[":cc"] = chunk_count

    table.update_item(
        Key={"tenant_id": tenant_id, "document_id": document_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )


def list_documents(tenant_id: str):
    """Lists all documents for a tenant - scoped by partition key, cannot leak across tenants."""
    table = dynamodb.Table(DOCUMENTS_TABLE)
    response = table.query(KeyConditionExpression=Key("tenant_id").eq(tenant_id))
    return response.get("Items", [])


def get_document(tenant_id: str, document_id: str):
    table = dynamodb.Table(DOCUMENTS_TABLE)
    response = table.get_item(Key={"tenant_id": tenant_id, "document_id": document_id})
    return response.get("Item")


def delete_document_record(tenant_id: str, document_id: str):
    table = dynamodb.Table(DOCUMENTS_TABLE)
    table.delete_item(Key={"tenant_id": tenant_id, "document_id": document_id})
