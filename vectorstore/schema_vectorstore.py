# vectorstore/schema_vectorstore.py
import os
from typing import List, Dict, Any

import chromadb

from backend.embeddings import embed_text

CHROMA_DIR = os.getenv("CHROMA_DIR", "/app/vector_store")
COLLECTION_NAME = os.getenv("SCHEMA_COLLECTION", "db_schema")

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=CHROMA_DIR)
    return _client

def search(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Returns list of:
      { "text": ..., "metadata": {...}, "score": distance, "source": id }
    """
    client = _get_client()
    coll = client.get_or_create_collection(COLLECTION_NAME)

    q_emb = embed_text(query)

    res = coll.query(
        query_embeddings=[q_emb],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],  # do NOT include "ids"
    )

    docs_list = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    ids = (res.get("ids") or [[]])[0]  # many Chroma versions still return ids even if not requested

    out: List[Dict[str, Any]] = []
    for i, doc in enumerate(docs_list):
        out.append(
            {
                "text": doc,
                "metadata": metas[i] if i < len(metas) else {},
                "score": float(dists[i]) if i < len(dists) and dists[i] is not None else None,
                "source": ids[i] if i < len(ids) else None,
            }
        )
    return out