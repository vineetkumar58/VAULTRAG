# VaultRAG

Multi-tenant RAG platform. See `VaultRAG_Technical_Specification.md` (shared separately)
for the full architecture reasoning — this README is just setup/run instructions.

## Folder structure

```
vaultrag/
├── terraform/              All AWS infrastructure as code
│   ├── main.tf              Provider config
│   ├── s3.tf                 Document bucket + event notification -> SQS
│   ├── sqs.tf                Ingestion queue + dead-letter queue
│   ├── dynamodb.tf           Tenants / Users / Invites / ConversationHistory tables
│   ├── lambda.tf             All 3 Lambda functions + shared layer
│   ├── api_gateway.tf        HTTP API routes (/auth/*, /query)
│   ├── iam.tf                Lambda execution role + scoped permissions
│   ├── variables.tf          Input variables (secrets, region, etc.)
│   └── outputs.tf            Printed after `terraform apply` (API URL, etc.)
│
├── lambdas/
│   ├── shared/                Packaged as a Lambda Layer, imported by all 4 functions
│   │   ├── jwt_utils.py         Sign/verify tenant-scoped JWTs
│   │   ├── dynamo_utils.py      DynamoDB read/write helpers (incl. Documents table)
│   │   ├── pinecone_utils.py    Tenant-namespaced vector search/upsert/delete
│   │   └── gemini_utils.py      Embedding, generation, prompt assembly, cost routing
│   │
│   ├── ingestion/              Triggered by SQS
│   │   ├── handler.py            marks documents ready/failed in DynamoDB as it processes them
│   │   ├── chunking.py           PDF/DOCX/TXT extraction + chunking
│   │   └── requirements.txt
│   │
│   ├── query/                  Triggered by API Gateway (POST /query)
│   │   ├── handler.py
│   │   └── requirements.txt
│   │
│   ├── auth/                   Triggered by API Gateway (POST /auth/*)
│   │   ├── handler.py           signup / login / invite
│   │   └── requirements.txt
│   │
│   └── documents/              Triggered by API Gateway (/documents/*)
│       ├── handler.py           presigned upload URL, list, delete (S3 + Pinecone + DynamoDB)
│       └── requirements.txt
│
├── frontend/                    Plain HTML/CSS/JS - no build step, no framework
│   ├── index.html                 Login/signup screen + main app shell
│   ├── style.css
│   ├── app.js                     All API calls live here
│   └── config.js                  <- YOU MUST EDIT THIS with your deployed API URL
│
├── .github/workflows/deploy.yml   CI/CD: terraform plan on PR, apply on merge to main
├── .env.example                    Template for local env vars / GitHub secrets
└── README.md
```

## Prerequisites

- AWS account + AWS CLI configured (`aws configure`)
- Terraform >= 1.5
- A Pinecone account (free tier) — create an index first:
  - Dimension: **768** (matches Gemini's `text-embedding-004` output size)
  - Metric: **cosine**
  - Copy the index host URL for `.env` / Terraform vars
- A Google AI Studio API key for Gemini (free tier available)
- Python 3.12 (matches the Lambda runtime)

## First-time setup

1. **Copy env template:**
   ```bash
   cp .env.example .env
   # fill in GEMINI_API_KEY, PINECONE_API_KEY, PINECONE_INDEX_HOST, JWT_SECRET
   ```

2. **Set Terraform variables** (either `terraform/terraform.tfvars` — gitignored — or env vars):
   ```bash
   export TF_VAR_gemini_api_key="..."
   export TF_VAR_pinecone_api_key="..."
   export TF_VAR_pinecone_index_host="..."
   export TF_VAR_jwt_secret="$(openssl rand -hex 32)"
   ```

3. **Install Lambda dependencies locally** (Terraform zips these folders as-is,
   so packages must be installed into each Lambda directory before `terraform apply`):
   ```bash
   pip install -r lambdas/shared/requirements.txt -t lambdas/shared --upgrade
   pip install -r lambdas/ingestion/requirements.txt -t lambdas/ingestion --upgrade
   pip install -r lambdas/auth/requirements.txt -t lambdas/auth --upgrade
   # documents/ and query/ have no extra deps beyond the shared layer
   ```

4. **Deploy infrastructure:**
   ```bash
   cd terraform
   terraform init
   terraform plan     # review what will be created
   terraform apply
   ```

5. **Grab the API URL** from the output:
   ```bash
   terraform output api_base_url
   ```

6. **Run the frontend:**
   - Open `frontend/config.js` and paste your `api_base_url` into `API_BASE_URL`.
   - Open `frontend/index.html` directly in a browser (double-click it), or serve it
     with any static server, e.g. `python3 -m http.server 8000` from inside `frontend/`.
   - Sign up (creates a new org), upload a document from the sidebar, wait a few
     seconds for its status to flip to "ready", then ask a question in the chat panel.

## Testing the flow end to end

You can test either through the frontend (`frontend/index.html`, recommended) or via curl:

```bash
API=$(terraform output -raw api_base_url)

# 1. Sign up (creates a new org + admin user)
curl -X POST $API/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"testpass123","org_name":"Test Org"}'
# -> returns { "token": "...", "tenant_id": "org-xxxxx", "user_id": "u-xxxx" }

# 2. Get a presigned upload URL, then upload the file directly to S3
curl -X POST $API/documents/upload-url \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"filename":"handbook.pdf"}'
# -> returns { "upload_url": "...", "document_id": "doc-xxxx" }

curl -X PUT "<upload_url from above>" --upload-file handbook.pdf
# -> this PUT triggers the S3 event -> SQS -> ingestion Lambda automatically

# 3. Check ingestion status
curl $API/documents -H "Authorization: Bearer <token>"
# -> status will be "pending" then "ready" a few seconds later

# 4. Ask a question
curl -X POST $API/query \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"question":"What does this document say about remote work?"}'

# 5. Delete the document (removes S3 file + Pinecone vectors + DynamoDB record)
curl -X DELETE $API/documents/doc-xxxx -H "Authorization: Bearer <token>"
```

## Local Lambda testing (without deploying)

Each handler is a plain function — you can invoke it directly in a Python shell
after setting the env vars from `.env`:

```python
import os
os.environ.update({"GEMINI_API_KEY": "...", "PINECONE_API_KEY": "...", ...})

from lambdas.query.handler import lambda_handler
event = {
    "headers": {"authorization": "Bearer <token>"},
    "body": '{"question": "test question"}',
}
print(lambda_handler(event, None))
```

## Known gaps (tracked, not hidden — see Section 10 of the technical spec)

- IAM-scoped per-tenant roles (defense-in-depth) — not yet implemented
- Load testing under concurrent multi-tenant traffic — not yet run
- Retrieval accuracy evaluation set — not yet built
- Role-based access within a tenant — future scope extension
- Document *update* (re-upload same doc, re-embed) still requires manual delete + re-upload — no dedicated "replace" endpoint yet, though `DELETE /documents/{id}` + re-upload achieves the same result
- CORS is wide open (`*`) for development — restrict to your actual frontend domain before treating this as production-ready
- Invite emails are not actually sent (no SES wired up) — the invite token is returned directly in the API response / shown in the modal for manual sharing
