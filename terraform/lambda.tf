# Table names, injected as env vars so lambdas/shared/dynamo_utils.py never
# has to guess/hardcode a name - it reads these via os.environ.
locals {
  dynamo_env_vars = {
    TENANTS_TABLE   = aws_dynamodb_table.tenants.name
    USERS_TABLE     = aws_dynamodb_table.users.name
    INVITES_TABLE   = aws_dynamodb_table.invites.name
    HISTORY_TABLE   = aws_dynamodb_table.conversation_history.name
    DOCUMENTS_TABLE = aws_dynamodb_table.documents.name
  }
}

# Shared code (jwt/dynamo/pinecone/gemini utils) packaged as a Lambda Layer,
# so it's not duplicated inside every function's zip.
data "archive_file" "shared_layer" {
  type        = "zip"
  source_dir  = "../lambdas/shared"
  output_path = "../build/shared_layer.zip"
}

resource "aws_lambda_layer_version" "shared" {
  layer_name          = "${local.name_prefix}-shared"
  filename            = data.archive_file.shared_layer.output_path
  source_code_hash    = data.archive_file.shared_layer.output_base64sha256
  compatible_runtimes = ["python3.12"]
}

# --- Ingestion Lambda: triggered by SQS, chunks + embeds + stores documents ---
data "archive_file" "ingestion" {
  type        = "zip"
  source_dir  = "../lambdas/ingestion"
  output_path = "../build/ingestion.zip"
}

resource "aws_lambda_function" "ingestion" {
  function_name    = "${local.name_prefix}-ingestion"
  filename         = data.archive_file.ingestion.output_path
  source_code_hash = data.archive_file.ingestion.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = 60 # gives headroom under the SQS visibility_timeout (90s)
  memory_size      = 512
  role             = aws_iam_role.lambda_exec.arn
  layers           = [aws_lambda_layer_version.shared.arn]

  environment {
    variables = merge(local.dynamo_env_vars, {
      GEMINI_API_KEY      = var.gemini_api_key
      PINECONE_API_KEY    = var.pinecone_api_key
      PINECONE_INDEX_HOST = var.pinecone_index_host
    })
  }

  tags = local.common_tags
}

# --- Query Lambda: triggered by API Gateway, does retrieval + routing + generation ---
data "archive_file" "query" {
  type        = "zip"
  source_dir  = "../lambdas/query"
  output_path = "../build/query.zip"
}

resource "aws_lambda_function" "query" {
  function_name    = "${local.name_prefix}-query"
  filename         = data.archive_file.query.output_path
  source_code_hash = data.archive_file.query.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = 30
  memory_size      = 512
  role             = aws_iam_role.lambda_exec.arn
  layers           = [aws_lambda_layer_version.shared.arn]

  environment {
    variables = merge(local.dynamo_env_vars, {
      GEMINI_API_KEY      = var.gemini_api_key
      PINECONE_API_KEY    = var.pinecone_api_key
      PINECONE_INDEX_HOST = var.pinecone_index_host
      JWT_SECRET          = var.jwt_secret
    })
  }

  tags = local.common_tags
}

# --- Auth Lambda: signup / login / invite ---
data "archive_file" "auth" {
  type        = "zip"
  source_dir  = "../lambdas/auth"
  output_path = "../build/auth.zip"
}

resource "aws_lambda_function" "auth" {
  function_name    = "${local.name_prefix}-auth"
  filename         = data.archive_file.auth.output_path
  source_code_hash = data.archive_file.auth.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = 15
  memory_size      = 256
  role             = aws_iam_role.lambda_exec.arn
  layers           = [aws_lambda_layer_version.shared.arn]

  environment {
    variables = merge(local.dynamo_env_vars, {
      JWT_SECRET = var.jwt_secret
    })
  }

  tags = local.common_tags
}

# --- Documents Lambda: presigned upload URLs, list, delete ---
data "archive_file" "documents" {
  type        = "zip"
  source_dir  = "../lambdas/documents"
  output_path = "../build/documents.zip"
}

resource "aws_lambda_function" "documents" {
  function_name    = "${local.name_prefix}-documents"
  filename         = data.archive_file.documents.output_path
  source_code_hash = data.archive_file.documents.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = 15
  memory_size      = 256
  role             = aws_iam_role.lambda_exec.arn
  layers           = [aws_lambda_layer_version.shared.arn]

  environment {
    variables = merge(local.dynamo_env_vars, {
      JWT_SECRET          = var.jwt_secret
      DOCUMENTS_BUCKET    = aws_s3_bucket.documents.bucket
      PINECONE_API_KEY    = var.pinecone_api_key
      PINECONE_INDEX_HOST = var.pinecone_index_host
    })
  }

  tags = local.common_tags
}

resource "aws_lambda_permission" "allow_sqs_invoke" {
  statement_id  = "AllowSQSInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingestion.function_name
  principal     = "sqs.amazonaws.com"
  source_arn    = aws_sqs_queue.ingestion_queue.arn
}
