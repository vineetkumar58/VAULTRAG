# HTTP API (cheaper + simpler than REST API) exposing:
#   POST /auth/signup
#   POST /auth/login
#   POST /auth/invite
#   POST /documents/upload-url   -> returns a pre-signed S3 URL for direct upload
#   POST /query                  -> the main question-answering endpoint

resource "aws_apigatewayv2_api" "main" {
  name          = "${local.name_prefix}-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = ["*"] # tighten to your actual frontend domain before production
    allow_methods = ["POST", "GET", "OPTIONS"]
    allow_headers = ["content-type", "authorization"]
  }
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true
}

# --- Auth routes ---
resource "aws_apigatewayv2_integration" "auth" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.auth.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "signup" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "POST /auth/signup"
  target    = "integrations/${aws_apigatewayv2_integration.auth.id}"
}

resource "aws_apigatewayv2_route" "login" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "POST /auth/login"
  target    = "integrations/${aws_apigatewayv2_integration.auth.id}"
}

resource "aws_apigatewayv2_route" "invite" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "POST /auth/invite"
  target    = "integrations/${aws_apigatewayv2_integration.auth.id}"
}

# --- Query route ---
resource "aws_apigatewayv2_integration" "query" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.query.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "query" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "POST /query"
  target    = "integrations/${aws_apigatewayv2_integration.query.id}"
}

# --- Document routes ---
resource "aws_apigatewayv2_integration" "documents" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.documents.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "upload_url" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "POST /documents/upload-url"
  target    = "integrations/${aws_apigatewayv2_integration.documents.id}"
}

resource "aws_apigatewayv2_route" "list_documents" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "GET /documents"
  target    = "integrations/${aws_apigatewayv2_integration.documents.id}"
}

resource "aws_apigatewayv2_route" "delete_document" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "DELETE /documents/{document_id}"
  target    = "integrations/${aws_apigatewayv2_integration.documents.id}"
}

resource "aws_lambda_permission" "apigw_documents" {
  statement_id  = "AllowAPIGatewayInvokeDocuments"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.documents.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

resource "aws_lambda_permission" "apigw_auth" {
  statement_id  = "AllowAPIGatewayInvokeAuth"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.auth.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}

resource "aws_lambda_permission" "apigw_query" {
  statement_id  = "AllowAPIGatewayInvokeQuery"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.query.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}
