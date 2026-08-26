"""
pinecone_utils.py

Wraps Pinecone read/write calls. Every function requires an explicit
tenant_id and always maps it 1:1 to a Pinecone namespace.

CRITICAL INVARIANT: there is no function here that searches or writes across
namespaces. A query for tenant_id="org-a-8f3d" is structurally incapable of
returning vectors from any other tenant - see Section 4 of the technical spec.
"""

import os
from pinecone import Pinecone

_pc = None
_index = None


def _get_index():
    global _pc, _index
    if _index is None:
        _pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
        _index = _pc.Index(host=os.environ["PINECONE_INDEX_HOST"])
    return _index


def upsert_chunk(tenant_id: str, chunk_id: str, vector: list, metadata: dict):
    """
    Writes one embedded chunk into the tenant's namespace.
    metadata should include: document_id, document_name, page_number,
    section, chunk_text (so retrieval results are self-contained and citable).
    """
    index = _get_index()
    metadata = {**metadata, "tenant_id": tenant_id}
    index.upsert(
        vectors=[{"id": chunk_id, "values": vector, "metadata": metadata}],
        namespace=tenant_id,
    )


def search(tenant_id: str, query_vector: list, top_k: int = 5):
    """
    Searches ONLY within the given tenant's namespace. Returns a list of
    matches, each with .metadata containing document_name/page/chunk_text.
    """
    index = _get_index()
    results = index.query(
        vector=query_vector,
        top_k=top_k,
        namespace=tenant_id,
        include_metadata=True,
    )
    return results.get("matches", [])


def delete_document(tenant_id: str, document_id: str):
    """
    Deletes all chunks belonging to one document, scoped to the tenant's
    namespace. Used for the document update/delete flow (Section 10, gap #4
    in the spec - re-embedding on update should call this before re-ingesting).
    """
    index = _get_index()
    index.delete(namespace=tenant_id, filter={"document_id": {"$eq": document_id}})
