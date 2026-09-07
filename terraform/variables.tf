variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "ap-south-1"
}

variable "project_name" {
  description = "Prefix used for naming all resources"
  type        = string
  default     = "vaultrag"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "dev"
}

variable "gemini_api_key" {
  description = "Google Gemini API key (set via TF_VAR_gemini_api_key or terraform.tfvars, never commit this)"
  type        = string
  sensitive   = true
}

variable "pinecone_api_key" {
  description = "Pinecone API key (set via TF_VAR_pinecone_api_key or terraform.tfvars, never commit this)"
  type        = string
  sensitive   = true
}

variable "pinecone_index_host" {
  description = "Pinecone index host URL (from Pinecone console after creating the index)"
  type        = string
}

variable "jwt_secret" {
  description = "Secret used to sign JWTs"
  type        = string
  sensitive   = true
}
