# One row per organization.
resource "aws_dynamodb_table" "tenants" {
  name         = "${local.name_prefix}-Tenants"
  billing_mode = "PAY_PER_REQUEST" # serverless pricing, matches the rest of the stack
  hash_key     = "tenant_id"

  attribute {
    name = "tenant_id"
    type = "S"
  }

  tags = local.common_tags
}

# One row per user. tenant_id lives directly on this row - written once at signup,
# read at every login. EmailIndex GSI lets us look this up by email at login time
# (base table is keyed by user_id, which we don't know yet at login).
resource "aws_dynamodb_table" "users" {
  name         = "${local.name_prefix}-Users"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_id"

  attribute {
    name = "user_id"
    type = "S"
  }

  attribute {
    name = "email"
    type = "S"
  }

  global_secondary_index {
    name            = "EmailIndex"
    hash_key        = "email"
    projection_type = "ALL"
  }

  tags = local.common_tags
}

# Pending invites: admin invites a teammate -> row created here -> consumed at signup.
resource "aws_dynamodb_table" "invites" {
  name         = "${local.name_prefix}-Invites"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "invite_token"

  attribute {
    name = "invite_token"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  tags = local.common_tags
}

# Conversation history for multi-turn support.
# Partition key is prefixed with tenant_id (e.g. "org-a-8f3d#session-456") -
# standard DynamoDB multi-tenancy pattern, keeps each tenant's items grouped.
resource "aws_dynamodb_table" "conversation_history" {
  name         = "${local.name_prefix}-ConversationHistory"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"
  range_key    = "turn_number"

  attribute {
    name = "session_id"
    type = "S"
  }

  attribute {
    name = "turn_number"
    type = "N"
  }

  tags = local.common_tags
}

# Tracks uploaded documents per tenant: status (pending/ready/failed), so the
# frontend can list documents and know when ingestion has finished, and so
# delete/update operations know which Pinecone chunks to clean up.
resource "aws_dynamodb_table" "documents" {
  name         = "${local.name_prefix}-Documents"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "tenant_id"
  range_key    = "document_id"

  attribute {
    name = "tenant_id"
    type = "S"
  }

  attribute {
    name = "document_id"
    type = "S"
  }

  tags = local.common_tags
}
