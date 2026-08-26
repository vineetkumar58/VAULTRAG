"""
gemini_utils.py

Wraps all Gemini SDK calls: embeddings (used in both ingestion and query),
generation (query only), and the cost-aware routing decision between
Gemini Flash and Gemini Pro.

Uses the official `google-generativeai` SDK - no raw REST/JSON payloads,
per the project's actual implementation choice.
"""

import os
import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

EMBEDDING_MODEL = "models/text-embedding-004"
FLASH_MODEL = "gemini-1.5-flash"
PRO_MODEL = "gemini-1.5-pro"

# Threshold used for cost-aware routing (Section 7, step 6 of the spec).
# Below this many chunks/tokens -> cheap model. At/above -> stronger model.
# Tune this after real usage - it's a placeholder starting point.
ROUTING_CHUNK_THRESHOLD = 4
ROUTING_TOKEN_THRESHOLD = 2000


def embed_text(text: str) -> list:
    """Used for both document chunks (ingestion) and questions (query)."""
    result = genai.embed_content(model=EMBEDDING_MODEL, content=text)
    return result["embedding"]


def choose_model(retrieved_chunks: list) -> str:
    """
    Cost-aware routing: if the question needed a lot of context to answer
    (many chunks, or a lot of total text), it's likely complex/multi-part,
    so route to Pro. Otherwise, Flash is enough and far cheaper.
    """
    total_chars = sum(len(c["metadata"].get("chunk_text", "")) for c in retrieved_chunks)
    approx_tokens = total_chars / 4  # rough chars-to-tokens estimate

    if len(retrieved_chunks) >= ROUTING_CHUNK_THRESHOLD or approx_tokens >= ROUTING_TOKEN_THRESHOLD:
        return PRO_MODEL
    return FLASH_MODEL


SYSTEM_PROMPT_TEMPLATE = """SYSTEM INSTRUCTIONS:
You are an assistant that answers questions using ONLY the provided
document excerpts. Do not use outside knowledge. If the answer isn't
contained in the excerpts, say you don't have enough information -
do not guess or make up an answer. For every claim in your answer,
cite which excerpt it came from using [Source: filename, page X].

{history_block}
CONTEXT (retrieved chunks):
{context_block}

USER QUESTION:
{question}

ANSWER:"""


def build_prompt(question: str, retrieved_chunks: list, history_turns: list = None) -> str:
    """Assembles the exact prompt template described in Section 7 of the spec."""
    if not retrieved_chunks:
        context_block = "No relevant documents were found for this question."
    else:
        parts = []
        for i, chunk in enumerate(retrieved_chunks, start=1):
            meta = chunk["metadata"]
            parts.append(
                f"[Excerpt {i} - {meta.get('document_name')}, "
                f"Page {meta.get('page_number')}, Section {meta.get('section', 'N/A')}]\n"
                f"\"{meta.get('chunk_text')}\""
            )
        context_block = "\n\n".join(parts)

    history_block = ""
    if history_turns:
        lines = ["PREVIOUS CONVERSATION:"]
        for turn in history_turns:
            lines.append(f"Q: {turn['question']}")
            lines.append(f"A: {turn['answer']}")
        history_block = "\n".join(lines) + "\n"

    return SYSTEM_PROMPT_TEMPLATE.format(
        history_block=history_block,
        context_block=context_block,
        question=question,
    )


def generate_answer(prompt: str, model_name: str) -> str:
    model = genai.GenerativeModel(model_name)
    response = model.generate_content(prompt)
    return response.text
