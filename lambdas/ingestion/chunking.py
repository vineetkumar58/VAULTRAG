"""
chunking.py

Splits extracted document text into overlapping chunks before embedding.
Overlap prevents a sentence from being cut in half exactly at a chunk boundary.

Also handles raw text extraction from PDF/DOCX so handler.py stays focused
on orchestration.
"""

import io
from pypdf import PdfReader
import docx


def extract_text(file_bytes: bytes, filename: str) -> list:
    """
    Returns a list of (page_number, text) tuples. page_number is 1-indexed.
    DOCX has no native page concept, so it's returned as a single "page" (1).
    """
    if filename.lower().endswith(".pdf"):
        reader = PdfReader(io.BytesIO(file_bytes))
        return [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]

    if filename.lower().endswith(".docx"):
        document = docx.Document(io.BytesIO(file_bytes))
        full_text = "\n".join(p.text for p in document.paragraphs)
        return [(1, full_text)]

    if filename.lower().endswith(".txt"):
        return [(1, file_bytes.decode("utf-8", errors="ignore"))]

    raise ValueError(f"Unsupported file type: {filename}")


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list:
    """
    Naive whitespace-token chunking with overlap.
    chunk_size / overlap are in approximate words, not exact LLM tokens -
    fine for this project's scale; swap for a tokenizer-based splitter if
    retrieval accuracy testing (spec Section 10, gap #5) shows it matters.
    """
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        if chunk.strip():
            chunks.append(chunk)
        start += chunk_size - overlap  # step forward, leaving `overlap` words repeated

    return chunks


def chunk_document(file_bytes: bytes, filename: str) -> list:
    """
    Full pipeline: extract text per page, chunk each page's text, and return
    a flat list of dicts ready to be embedded, each carrying its page number
    for citation purposes.
    """
    pages = extract_text(file_bytes, filename)
    all_chunks = []
    for page_number, page_text in pages:
        for chunk in chunk_text(page_text):
            all_chunks.append({
                "text": chunk,
                "page_number": page_number,
            })
    return all_chunks
