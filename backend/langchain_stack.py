from __future__ import annotations

"""Selective LangChain layer for CGI AIO Phase 2.

Purpose:
- standardize chat model access (OpenAI primary, Ollama fallback)
- standardize doc retrieval via LangChain Chroma retriever
- preserve existing app behavior via safe fallbacks to current modules

This module is intentionally thin: LangGraph remains the orchestrator,
LangChain provides model and retrieval components.
"""

from functools import lru_cache
import os
from typing import Any, Dict, Iterable, List

from backend import llm_router, rag

try:  # LangChain chat model wrappers
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
except Exception:  # pragma: no cover
    ChatOpenAI = None  # type: ignore
    OpenAIEmbeddings = None  # type: ignore

try:
    from langchain_ollama import ChatOllama
except Exception:  # pragma: no cover
    ChatOllama = None  # type: ignore

try:
    from langchain_chroma import Chroma
except Exception:  # pragma: no cover
    Chroma = None  # type: ignore

try:
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
except Exception:  # pragma: no cover
    SystemMessage = HumanMessage = AIMessage = None  # type: ignore

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover
    SentenceTransformer = None  # type: ignore

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").strip().lower() or "openai"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")
CHROMA_DIR = os.getenv("CHROMA_DIR", "/app/vector_store")
DOC_COLLECTION = os.getenv("DOC_COLLECTION", "docs")
USE_LANGCHAIN_COMPONENTS = str(os.getenv("USE_LANGCHAIN_COMPONENTS", "1")).strip().lower() in {"1", "true", "yes", "on"}
LANGCHAIN_RAG_K = int(os.getenv("LANGCHAIN_RAG_K", "4"))


class _MiniLMEmbeddings:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        if SentenceTransformer is None:
            raise RuntimeError("sentence-transformers is required for local fallback embeddings")
        self._model = SentenceTransformer(model_name)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        arr = [str(t or "") for t in texts]
        embeds = self._model.encode(arr, normalize_embeddings=True)
        return [list(map(float, row)) for row in embeds]

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]


@lru_cache(maxsize=1)
def _lc_embeddings():
    if not USE_LANGCHAIN_COMPONENTS:
        raise RuntimeError("LangChain components disabled")
    if OPENAI_API_KEY and OpenAIEmbeddings is not None:
        return OpenAIEmbeddings(model=OPENAI_EMBED_MODEL, api_key=OPENAI_API_KEY)
    return _MiniLMEmbeddings()


def _to_lc_messages(messages: Iterable[Dict[str, str]]) -> List[Any]:
    out: List[Any] = []
    for m in messages:
        role = (m.get("role") or "user").strip().lower()
        content = m.get("content") or ""
        if role == "system" and SystemMessage is not None:
            out.append(SystemMessage(content=content))
        elif role == "assistant" and AIMessage is not None:
            out.append(AIMessage(content=content))
        else:
            out.append(HumanMessage(content=content) if HumanMessage is not None else content)
    return out


@lru_cache(maxsize=4)
def _chat_model(provider_hint: str = ""):
    provider = (provider_hint or LLM_PROVIDER).strip().lower() or "openai"

    if provider != "ollama" and OPENAI_API_KEY and ChatOpenAI is not None:
        return ChatOpenAI(model=OPENAI_MODEL, api_key=OPENAI_API_KEY, temperature=0)

    if ChatOllama is not None:
        try:
            return ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL, temperature=0)
        except TypeError:
            return ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL)

    raise RuntimeError("No LangChain chat model is available")


def chat_completion(
    *,
    messages: List[Dict[str, str]],
    temperature: float = 0.0,
    max_tokens: int = 400,
    tags: List[str] | None = None,
    metadata: Dict[str, Any] | None = None,
) -> tuple[str, Dict[str, Any]]:
    """LangChain-first chat completion with safe fallback to existing llm_router."""
    dbg: Dict[str, Any] = {"component_stack": "langchain", "model_impl": "fallback_llm_router"}

    if USE_LANGCHAIN_COMPONENTS:
        lc_messages = _to_lc_messages(messages)
        # OpenAI primary then Ollama fallback, mirroring current behavior.
        for provider in ([LLM_PROVIDER] if LLM_PROVIDER == "ollama" else ["openai", "ollama"]):
            try:
                model = _chat_model(provider)
                # bind runtime parameters where supported
                try:
                    runnable = model.bind(temperature=temperature, max_tokens=max_tokens)
                except Exception:
                    runnable = model
                resp = runnable.invoke(lc_messages, config={"tags": tags or [], "metadata": metadata or {}})
                text = getattr(resp, "content", resp)
                if isinstance(text, list):
                    text = "\n".join([getattr(x, "text", str(x)) for x in text])
                dbg.update({"model_impl": "langchain", "model_provider": provider})
                return (str(text or "").strip(), dbg)
            except Exception as e:
                dbg[f"{provider}_error"] = str(e)

    # final fallback to current app path
    text = llm_router.chat_completion(messages=messages, temperature=temperature, max_tokens=max_tokens)
    return (text, dbg)


@lru_cache(maxsize=1)
def _vectorstore():
    if not USE_LANGCHAIN_COMPONENTS or Chroma is None:
        raise RuntimeError("LangChain Chroma is unavailable")
    return Chroma(
        collection_name=DOC_COLLECTION,
        embedding_function=_lc_embeddings(),
        persist_directory=CHROMA_DIR,
    )


def retrieve_docs(question: str, k: int | None = None) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """LangChain-first retrieval with fallback to existing rag.retrieve()."""
    k = int(k or LANGCHAIN_RAG_K)
    dbg: Dict[str, Any] = {"component_stack": "langchain", "retriever_impl": "fallback_rag"}

    if USE_LANGCHAIN_COMPONENTS:
        try:
            vs = _vectorstore()
            retriever = vs.as_retriever(search_kwargs={"k": k})
            docs = retriever.invoke(question)
            hits: List[Dict[str, Any]] = []
            for d in docs:
                meta = dict(getattr(d, "metadata", {}) or {})
                hits.append({
                    "text": getattr(d, "page_content", "") or "",
                    "meta": meta,
                })
            dbg.update({"retriever_impl": "langchain_chroma", "k": k, "collection": DOC_COLLECTION})
            return hits, dbg
        except Exception as e:
            dbg["retriever_error"] = str(e)

    hits = rag.retrieve(question, k=k)
    return hits, dbg
