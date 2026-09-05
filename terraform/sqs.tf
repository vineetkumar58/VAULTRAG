# Dead-letter queue: messages that fail processing maxReceiveCount times land here
# instead of retrying forever. Inspect this queue manually when documents fail repeatedly.
resource "aws_sqs_queue" "ingestion_dlq" {
  name                      = "${local.name_prefix}-ingestion-dlq"
  message_retention_seconds = 1209600 # 14 days
  tags                      = local.common_tags
}

# Main ingestion queue. S3 upload events land here; the ingestion Lambda polls this queue.
resource "aws_sqs_queue" "ingestion_queue" {
  name                       = "${local.name_prefix}-ingestion-queue"
  visibility_timeout_seconds = 90 # must be >= ingestion Lambda's timeout
  message_retention_seconds  = 345600 # 4 days

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ingestion_dlq.arn
    maxReceiveCount      = 5 # after 5 failed attempts, message goes to DLQ
  })

  tags = local.common_tags
}

# Allows the S3 bucket to publish events into this queue
resource "aws_sqs_queue_policy" "allow_s3" {
  queue_url = aws_sqs_queue.ingestion_queue.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.ingestion_queue.arn
      Condition = {
        ArnEquals = { "aws:SourceArn" = aws_s3_bucket.documents.arn }
      }
    }]
  })
}

# Wires the queue as a trigger for the ingestion Lambda.
# batch_size controls how many messages one Lambda invocation processes at once.
resource "aws_lambda_event_source_mapping" "ingestion_trigger" {
  event_source_arn                   = aws_sqs_queue.ingestion_queue.arn
  function_name                      = aws_lambda_function.ingestion.arn
  batch_size                         = 5
  maximum_batching_window_in_seconds = 5
  # Lets the Lambda report which specific messages in a batch failed, so SQS
  # only retries those - not the whole batch. Handler must return
  # {"batchItemFailures": [...]} to match (see ingestion/handler.py).
  function_response_types = ["ReportBatchItemFailures"]
}
