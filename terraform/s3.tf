# S3 bucket where all tenant documents are stored, namespaced by tenant_id as a key prefix:
# s3://<bucket>/<tenant_id>/<filename>

resource "aws_s3_bucket" "documents" {
  bucket = "${local.name_prefix}-documents"
  tags   = local.common_tags
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id
  versioning_configuration {
    status = "Enabled" # keeps old versions if a doc is re-uploaded/overwritten
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket                  = aws_s3_bucket.documents.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Event notification: every object created under any prefix fires into SQS.
# The ingestion Lambda is subscribed to that queue, not to S3 directly, so that
# bursts of uploads get buffered instead of invoking Lambda synchronously per upload.
resource "aws_s3_bucket_notification" "documents_notification" {
  bucket = aws_s3_bucket.documents.id

  queue {
    queue_arn = aws_sqs_queue.ingestion_queue.arn
    events    = ["s3:ObjectCreated:*"]
  }

  depends_on = [aws_sqs_queue_policy.allow_s3]
}
