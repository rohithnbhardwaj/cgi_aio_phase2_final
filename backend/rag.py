import os
from typing import Any, Dict, List, Optional

import chromadb
from openai import OpenAI

from backend.llm_router import chat_completion

CHROMA_DIR = os.getenv("CHROMA_DIR", "/app/vector_store")
DOC_COLLECTION = os.getenv("DOC_COLLECTION", "docs")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
RAG_ANSWER_MODEL = os.getenv("RAG_ANSWER_MODEL")  # optional override

_openai_client: Optional[OpenAI] = None
_chroma_client: Optional[chromadb.PersistentClient] = None


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set (required for RAG embeddings).")
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


def _embed_texts(texts: List[str]) -> List[List[float]]:
    """Embed a batch of texts with OpenAI.

    We compute embeddings ourselves and pass them to Chroma via
    `query_embeddings=` to avoid relying on Chroma's EmbeddingFunction
    interface (which changed in 0.4.16).
    """
    if not texts:
        return []
    resp = _get_openai_client().embeddings.create(model=OPENAI_EMBED_MODEL, input=texts)
    data = sorted(resp.data, key=lambda d: d.index)
    return [d.embedding for d in data]


def _get_chroma_client() -> chromadb.PersistentClient:
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
    return _chroma_client


def _collection():
    # Do NOT attach an embedding_function.
    # We always provide explicit embeddings when querying.
    return _get_chroma_client().get_or_create_collection(
        name=DOC_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


def retrieve(query: str, k: int = 4) -> List[Dict[str, Any]]:
    q_emb = _embed_texts([query])[0]
    res = _collection().query(
        query_embeddings=[q_emb],
        n_results=k,
        include=["documents", "metadatas", "distances"],
    )

    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]

    hits = []
    for doc, meta, dist in zip(docs, metas, dists):
        hits.append({"text": doc or "", "meta": meta or {}, "distance": dist})
    return hits


def answer(query: str, k: int = 4) -> Dict[str, Any]:
    hits = retrieve(query, k=k)
    if not hits:
        return {
            "mode": "rag",
            "answer": "I couldn't find anything relevant in the knowledge documents.",
            "sources": [],
            "debug": {"reason": "no_hits", "k": k, "collection": DOC_COLLECTION},
        }

    sources: List[str] = []
    context_blocks: List[str] = []

    for i, h in enumerate(hits, start=1):
        meta = h.get("meta") or {}
        src = meta.get("source") or meta.get("file") or "document"
        if src and src not in sources:
            sources.append(src)

        label = f"[{i}] {src}"
        context_blocks.append(label + "\n" + (h.get("text") or "").strip())

    context = "\n\n---\n\n".join(context_blocks)

    system = (
        "You are CGI AIO Assistant. Answer the user's question using ONLY the provided context "
        "from internal documents. If the answer is not in the context, say you don't know. "
        "Be concise and actionable."
    )
    user = f"Question: {query}\n\nContext:\n{context}\n\nAnswer:"

    content = chat_completion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        model=RAG_ANSWER_MODEL,
        temperature=0.2,
        max_tokens=400,
    )

    return {
        "mode": "rag",
        "answer": content.strip(),
        "sources": sources,
        "debug": {"reason": "rag_success", "k": k, "collection": DOC_COLLECTION},
    }