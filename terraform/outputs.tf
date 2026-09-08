output "api_base_url" {
  description = "Base URL for the HTTP API - use this in the frontend"
  value       = aws_apigatewayv2_api.main.api_endpoint
}

output "documents_bucket_name" {
  value = aws_s3_bucket.documents.bucket
}

output "ingestion_queue_url" {
  value = aws_sqs_queue.ingestion_queue.url
}

output "ingestion_dlq_url" {
  value = aws_sqs_queue.ingestion_dlq.url
}

output "tenants_table_name" {
  value = aws_dynamodb_table.tenants.name
}

output "users_table_name" {
  value = aws_dynamodb_table.users.name
}
