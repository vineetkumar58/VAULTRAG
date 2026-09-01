# Shared execution role assumed by all Lambda functions.
resource "aws_iam_role" "lambda_exec" {
  name = "${local.name_prefix}-lambda-exec-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "basic_logs" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Scoped permissions - only what the Lambdas actually need, not admin access.
resource "aws_iam_role_policy" "lambda_permissions" {
  name = "${local.name_prefix}-lambda-permissions"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3Access"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.documents.arn}/*"
      },
      {
        Sid    = "SQSAccess"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = aws_sqs_queue.ingestion_queue.arn
      },
      {
        Sid    = "DynamoDBAccess"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query"
        ]
        Resource = [
          aws_dynamodb_table.tenants.arn,
          aws_dynamodb_table.users.arn,
          "${aws_dynamodb_table.users.arn}/index/*",
          aws_dynamodb_table.invites.arn,
          aws_dynamodb_table.conversation_history.arn,
          aws_dynamodb_table.documents.arn
        ]
      }
    ]
  })
}

# NOTE on future hardening (see Section 10 of the technical spec):
# Currently, tenant isolation is enforced entirely in application code
# (Lambda reads tenant_id from JWT, scopes S3 key + Pinecone namespace by it).
# A future improvement is per-tenant scoped IAM roles via sts:AssumeRole +
# session tags, so AWS itself blocks cross-tenant S3 access even if application
# code has a bug. Not implemented yet - flagged here intentionally.
