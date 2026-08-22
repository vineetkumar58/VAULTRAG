"""
handler.py (documents)

Handles document lifecycle management (Section 10, gap #4 of the technical
spec - this closes that gap):

  POST   /documents/upload-url   { filename }        -> presigned S3 PUT URL
  GET    /documents                                     -> list this tenant's documents
  DELETE /documents/{document_id}                      -> removes from S3 + Pinecone + DynamoDB

Why presigned URLs instead of uploading through API Gateway/Lambda:
API Gateway has a ~10MB payload limit and Lambda isn't built for streaming
large file bodies. A presigned URL lets the browser upload the file directly
to S3 - Lambda's only job is to generate a short-lived, tenant-scoped URL
authorizing that one specific upload.

All three routes derive tenant_id from the verified JWT - never from the
request body/path - same invariant as every other handler in this project.
"""

import json
import uuid
import boto3
from botocore.config import Config
import jwt as pyjwt

from jwt_utils import get_verified_tenant_context
from dynamo_utils import (
    create_document_record, list_documents, get_document, delete_document_record,
)
from pinecone_utils import delete_document as delete_document_vectors

s3 = boto3.client("s3", config=Config(signature_version="s3v4"))
BUCKET_NAME = None  # set from env at import time below

import os
BUCKET_NAME = os.environ["DOCUMENTS_BUCKET"]

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}


def _response(status_code: int, body: dict):
    return {"statusCode": status_code, "headers": CORS_HEADERS, "body": json.dumps(body)}


def handle_upload_url(tenant_id: str, body: dict):
    filename = body.get("filename", "").strip()
    if not filename:
        return _response(400, {"error": "filename is required"})

    if not filename.lower().endswith((".pdf", ".docx", ".txt")):
        return _response(400, {"error": "Only .pdf, .docx, .txt files are supported"})

    document_id = f"doc-{uuid.uuid4().hex[:12]}"
    # Tenant prefix is baked into the S3 key server-side - the client never
    # supplies or controls this path.
    s3_key = f"{tenant_id}/{document_id}-{filename}"

    presigned_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET_NAME, "Key": s3_key},
        ExpiresIn=300,  # 5 minutes to complete the upload
    )

    create_document_record(tenant_id=tenant_id, document_id=document_id, filename=filename, s3_key=s3_key)

    return _response(200, {
        "upload_url": presigned_url,
        "document_id": document_id,
        "s3_key": s3_key,
    })


def handle_list(tenant_id: str):
    documents = list_documents(tenant_id)
    return _response(200, {"documents": documents})


def handle_delete(tenant_id: str, document_id: str):
    document = get_document(tenant_id, document_id)
    if not document:
        return _response(404, {"error": "Document not found"})

    # 1. Delete the file from S3
    s3.delete_object(Bucket=BUCKET_NAME, Key=document["s3_key"])

    # 2. Delete all its chunks from Pinecone (tenant-scoped - see pinecone_utils.py)
    delete_document_vectors(tenant_id=tenant_id, document_id=document_id)

    # 3. Delete the tracking record from DynamoDB
    delete_document_record(tenant_id, document_id)

    return _response(200, {"message": f"Document {document_id} deleted"})


def lambda_handler(event, context):
    try:
        identity = get_verified_tenant_context(event)
    except (pyjwt.InvalidTokenError, ValueError) as e:
        return _response(401, {"error": f"Unauthorized: {e}"})

    tenant_id = identity["tenant_id"]
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("rawPath", "")

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        body = {}

    if method == "POST" and path.endswith("/upload-url"):
        return handle_upload_url(tenant_id, body)

    if method == "GET" and path.endswith("/documents"):
        return handle_list(tenant_id)

    if method == "DELETE":
        document_id = event.get("pathParameters", {}).get("document_id")
        if not document_id:
            return _response(400, {"error": "document_id path parameter is required"})
        return handle_delete(tenant_id, document_id)

    return _response(404, {"error": f"Unknown route: {method} {path}"})
