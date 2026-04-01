from __future__ import annotations

"""Document ingest utilities for CGI AIO Assistant.

Purpose
-------
Enable Streamlit users to upload knowledge documents (PDF/DOCX/TXT) from the UI,
stage them in /app/uploads (bind-mounted to ./uploads), and ingest them into the
same persistent Chroma collection used by backend.rag.

Notes
-----
- Uses OpenAI embeddings via backend.rag._embed_texts (consistent with current RAG).
- Writes to DOC_COLLECTION (default: "docs") at CHROMA_DIR (default: /app/vector_store).
- If replace_existing=True, deletes previously ingested chunks for the same filename
  (prevents stale/duplicate content when re-uploading a file).
"""

import hashlib
import os
from typing import Any, Dict, List


# Reuse the exact same Chroma collection + embedding logic as RAG.
from backend.rag import _collection, _embed_texts  # noqa: WPS450


UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/app/uploads")


def _chunk_text(text: str, chunk_size: int = 1200, overlap: int = 150) -> List[str]:
    """Simple character-based chunker with overlap."""

    text = (text or "").strip()
    if not text:
        return []

    chunks: List[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(n, start + chunk_size)
        chunks.append(text[start:end])
        if end >= n:
            break
        start = max(0, end - overlap)
    return chunks


def _read_txt(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _read_docx(path: str) -> str:
    import docx  # python-docx

    d = docx.Document(path)
    parts: List[str] = []
    for p in d.paragraphs:
        t = (p.text or "").strip()
        if t:
            parts.append(t)
    return "\n".join(parts)


def _read_pdf(path: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(path)
    parts: List[str] = []
    for page in reader.pages:
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        t = t.strip()
        if t:
            parts.append(t)
    return "\n\n".join(parts)


def _sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def save_to_uploads(filename: str, data: bytes) -> str:
    """Save bytes to UPLOAD_DIR and return the absolute path."""

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe_name = os.path.basename(filename)
    path = os.path.join(UPLOAD_DIR, safe_name)
    with open(path, "wb") as f:
        f.write(data)
    return path


def list_staged_files() -> List[str]:
    """Return filenames currently staged in UPLOAD_DIR."""
    if not os.path.isdir(UPLOAD_DIR):
        return []
    out = []
    for name in sorted(os.listdir(UPLOAD_DIR)):
        p = os.path.join(UPLOAD_DIR, name)
        if os.path.isfile(p):
            out.append(name)
    return out


def ingest_file(path: str, *, replace_existing: bool = True) -> Dict[str, Any]:
    """Parse + chunk + embed + upsert into Chroma docs collection."""

    filename = os.path.basename(path)
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    if ext not in {"pdf", "docx", "txt"}:
        return {"ok": False, "file": filename, "reason": f"Unsupported file type: .{ext}"}

    # Parse
    try:
        if ext == "txt":
            text = _read_txt(path)
        elif ext == "docx":
            text = _read_docx(path)
        else:
            text = _read_pdf(path)
    except Exception as e:
        return {"ok": False, "file": filename, "reason": f"Parse failed: {e}"}

    if not (text or "").strip():
        return {"ok": False, "file": filename, "reason": "No extractable text found."}

    chunks = _chunk_text(text)
    if not chunks:
        return {"ok": False, "file": filename, "reason": "Chunking produced 0 chunks."}

    # Embed
    try:
        embeds = _embed_texts(chunks)
    except Exception as e:
        return {"ok": False, "file": filename, "reason": f"Embedding failed: {e}"}

    # Ids + metadata
    try:
        with open(path, "rb") as f:
            raw = f.read()
        sha = _sha256_bytes(raw)
    except Exception:
        sha = hashlib.sha256(filename.encode("utf-8")).hexdigest()

    ids = [f"{sha}:{i}" for i in range(len(chunks))]
    metas = [
        {
            "source": filename,
            "file": filename,
            "path": path,
            "sha256": sha,
            "chunk_index": i,
            "file_type": ext,
        }
        for i in range(len(chunks))
    ]

    col = _collection()

    # Optional replace-by-filename to avoid duplicates when the same file is re-uploaded.
    if replace_existing:
        try:
            col.delete(where={"file": filename})
        except Exception:
            # Safe to ignore if the backend doesn't support metadata delete.
            pass

    # Upsert (or add fallback)
    try:
        col.upsert(ids=ids, documents=chunks, metadatas=metas, embeddings=embeds)
    except Exception:
        # If upsert isn't supported, try add.
        try:
            col.add(ids=ids, documents=chunks, metadatas=metas, embeddings=embeds)
        except Exception as e:
            return {"ok": False, "file": filename, "reason": f"Chroma write failed: {e}"}

    return {"ok": True, "file": filename, "chunks": len(chunks), "sha256": sha}


def ingest_staged_files(*, replace_existing: bool = True) -> List[Dict[str, Any]]:
    """Ingest every supported file currently staged in UPLOAD_DIR."""
    results: List[Dict[str, Any]] = []
    if not os.path.isdir(UPLOAD_DIR):
        return results

    for name in list_staged_files():
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        if ext not in {"pdf", "docx", "txt"}:
            continue
        path = os.path.join(UPLOAD_DIR, name)
        results.append(ingest_file(path, replace_existing=replace_existing))
    return results
