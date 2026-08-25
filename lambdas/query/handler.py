"""
handler.py (query)

Triggered synchronously by API Gateway on POST /query.
This path never touches SQS - the user is waiting live for a response
(Section 7 of the technical spec explains why this must stay synchronous).

Request body: { "question": "...", "session_id": "optional-for-multi-turn" }
Auth: Authorization: Bearer <jwt>   (tenant_id is derived from this, never from the body)

Flow:
  1. Verify JWT -> get tenant_id
  2. Embed the question
  3. Search ONLY that tenant's Pinecone namespace
  4. (optional) pull last few turns of conversation history
  5. Choose Gemini Flash or Pro based on how much context was retrieved
  6. Assemble the prompt and call Gemini
  7. Save the turn to history, return the answer + sources
"""

import json
import jwt as pyjwt

from jwt_utils import get_verified_tenant_context
from gemini_utils import embed_text, choose_model, build_prompt, generate_answer
from pinecone_utils import search
from dynamo_utils import get_recent_turns, save_turn

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}


def _response(status_code: int, body: dict):
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body),
    }


def lambda_handler(event, context):
    # --- 1. Identity check ---
    try:
        identity = get_verified_tenant_context(event)
    except (pyjwt.InvalidTokenError, ValueError) as e:
        return _response(401, {"error": f"Unauthorized: {e}"})

    tenant_id = identity["tenant_id"]

    # --- Parse request ---
    try:
        body = json.loads(event.get("body") or "{}")
        question = body["question"].strip()
    except (KeyError, json.JSONDecodeError):
        return _response(400, {"error": "Request body must include 'question'"})

    if not question:
        return _response(400, {"error": "'question' cannot be empty"})

    session_id = body.get("session_id", "default")

    # --- 2 & 3. Embed question, search tenant-scoped namespace only ---
    question_vector = embed_text(question)
    matches = search(tenant_id=tenant_id, query_vector=question_vector, top_k=5)

    # Reshape matches into the {metadata: {...}} form gemini_utils.build_prompt expects
    retrieved_chunks = [{"metadata": m["metadata"]} for m in matches]

    # --- 4. Conversation history (optional multi-turn) ---
    history_turns = get_recent_turns(tenant_id=tenant_id, session_id=session_id, limit=3)

    # --- 5. Cost-aware model routing ---
    model_name = choose_model(retrieved_chunks)

    # --- 6. Prompt assembly + generation ---
    prompt = build_prompt(question=question, retrieved_chunks=retrieved_chunks, history_turns=history_turns)
    answer_text = generate_answer(prompt, model_name)

    # --- 7. Persist turn + respond ---
    next_turn_number = len(history_turns) + 1
    save_turn(tenant_id, session_id, next_turn_number, question, answer_text)

    sources = [
        {
            "document_name": m["metadata"].get("document_name"),
            "page_number": m["metadata"].get("page_number"),
            "relevance_score": m.get("score"),
        }
        for m in matches
    ]

    return _response(200, {
        "answer": answer_text,
        "sources": sources,
        "model_used": model_name,
    })
