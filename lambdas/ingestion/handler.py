"""
handler.py (ingestion)

Triggered by SQS (see terraform/sqs.tf -> aws_lambda_event_source_mapping).
One invocation processes a batch of SQS messages (batch_size=5 in Terraform).

Flow per message (Section 6 of the technical spec):
  1. Read {tenant_id, s3_key, document_id} from the message
  2. Download the file from S3
  3. Extract text + split into chunks (chunking.py)
  4. Embed each chunk via Gemini
  5. Write each embedded chunk into Pinecone, into that tenant's namespace

If any message in the batch raises an exception, only THAT message is
reported as failed (via batchItemFailures) - SQS will retry only the failed
ones, not the whole batch. This is what makes per-document failure isolation
actually work in practice, not just in theory.
"""

import json
import boto3
from chunking import chunk_document
from gemini_utils import embed_text
from pinecone_utils import upsert_chunk
from dynamo_utils import update_document_status

s3 = boto3.client("s3")


def process_message(body: dict):
    tenant_id = body["tenant_id"]
    s3_key = body["s3_key"]
    document_id = body["document_id"]
    bucket = body["bucket"]

    # Defensive check: the S3 key MUST be prefixed with this tenant_id.
    # If it isn't, something upstream is broken - refuse rather than process
    # a document into the wrong tenant's namespace.
    if not s3_key.startswith(f"{tenant_id}/"):
        raise ValueError(
            f"Refusing to process: s3_key '{s3_key}' does not match tenant_id '{tenant_id}'"
        )

    try:
        obj = s3.get_object(Bucket=bucket, Key=s3_key)
        file_bytes = obj["Body"].read()
        filename = s3_key.split("/")[-1]

        chunks = chunk_document(file_bytes, filename)

        for i, chunk in enumerate(chunks):
            vector = embed_text(chunk["text"])
            chunk_id = f"{document_id}-chunk-{i}"
            upsert_chunk(
                tenant_id=tenant_id,
                chunk_id=chunk_id,
                vector=vector,
                metadata={
                    "document_id": document_id,
                    "document_name": filename,
                    "page_number": chunk["page_number"],
                    "chunk_text": chunk["text"],
                },
            )

        update_document_status(tenant_id=tenant_id, document_id=document_id, status="ready", chunk_count=len(chunks))
        print(f"Ingested document {document_id} for tenant {tenant_id}: {len(chunks)} chunks")

    except Exception:
        # Mark as failed so the frontend can show it, then re-raise so SQS
        # still retries this message (visibility timeout + maxReceiveCount).
        try:
            update_document_status(tenant_id=tenant_id, document_id=document_id, status="failed")
        except Exception as inner_e:
            print(f"Also failed to update status to 'failed': {inner_e}")
        raise


def lambda_handler(event, context):
    batch_item_failures = []

    for record in event.get("Records", []):
        message_id = record["messageId"]
        try:
            body = json.loads(record["body"])
            # S3 event notifications wrap the actual info; unwrap if needed.
            if "Records" in body:  # raw S3 event notification format
                s3_record = body["Records"][0]["s3"]
                bucket = s3_record["bucket"]["name"]
                key = s3_record["object"]["key"]
                tenant_id = key.split("/")[0]
                document_id = key.split("/")[-1]
                process_message({
                    "tenant_id": tenant_id,
                    "s3_key": key,
                    "document_id": document_id,
                    "bucket": bucket,
                })
            else:  # custom message format {tenant_id, s3_key, document_id, bucket}
                process_message(body)

        except Exception as e:
            print(f"FAILED processing message {message_id}: {e}")
            batch_item_failures.append({"itemIdentifier": message_id})

    # Returning only the failed message IDs tells SQS to retry just those,
    # not the entire batch - this requires "Report batch item failures"
    # enabled on the event source mapping (functionResponseTypes = ["ReportBatchItemFailures"]).
    return {"batchItemFailures": batch_item_failures}
