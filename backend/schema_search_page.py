# schema_search_page.py
"""
Streamlit demo for:
- Schema nearest-neighbour search (uses backend.fetch_schema_neighbors)
- NL->SQL synth + safe execution (uses backend.synthesize_sql & backend.run_sql)
- Simple RAG demo (vectorstore.search + backend.synthesize_answer)
- Feedback + golden_queries capture into Chroma
- Conversational memory (last N turns)
"""

import streamlit as st
from typing import List, Dict, Any
import re
import json
import time

# Attempt to import expected project modules; degrade gracefully if not available.
try:
    import backend
except Exception as e:
    backend = None

try:
    import vectorstore
except Exception as e:
    vectorstore = None

# Chroma client usage for golden queries
try:
    import chromadb
    from chromadb.config import Settings
    chroma_client = chromadb.Client(Settings(chroma_db_impl="duckdb+parquet", persist_directory="./chroma_db"))
except Exception:
    chroma_client = None

# Constants
MAX_MEMORY_TURNS = 6
SQL_SAFE_WHITELIST = ["SELECT", "WITH"]  # only allow queries starting with these
SQL_BLOCK_PATTERNS = [
    r"\bDROP\b", r"\bDELETE\b", r"\bUPDATE\b", r"\bTRUNCATE\b", r"\bALTER\b",
    r"\bINSERT\b", r"\bCREATE\b", r"\bMERGE\b", r";"  # block multi-statement attempts via semicolon
]

# Helpers

def sql_is_safe(sql: str) -> (bool, str):
    """Simple heuristic SQL safety check: only allow SELECT/ WITH, block destructive keywords, semicolons, etc."""
    s = sql.strip().upper()
    # allow starting with SELECT or WITH
    if not any(s.startswith(p) for p in SQL_SAFE_WHITELIST):
        return False, "Only read-only queries (SELECT / WITH) are allowed."
    for pat in SQL_BLOCK_PATTERNS:
        if re.search(pat, s, re.IGNORECASE):
            return False, f"SQL contains forbidden pattern: {pat}"
    return True, ""

def ensure_golden_collection():
    if chroma_client is None:
        return None, "Chroma client not configured in this environment."
    try:
        coll = chroma_client.get_collection("golden_queries")
    except Exception:
        coll = chroma_client.create_collection("golden_queries")
    return coll, None

def save_golden_question(question: str, correct_sql: str, embedding: List[float] = None):
    coll, err = ensure_golden_collection()
    if coll is None:
        return False, err
    meta = {"question": question, "sql": correct_sql, "created_at": time.time()}
    if embedding is None:
        # Try to compute embedding via backend if available
        if backend and hasattr(backend, "embed_text"):
            embedding = backend.embed_text(correct_sql)
    try:
        coll.add(
            documents=[correct_sql],
            metadatas=[meta],
            ids=[f"golden-{int(time.time()*1000)}"],
            embeddings=[embedding] if embedding is not None else None
        )
        chroma_client.persist()
        return True, None
    except Exception as e:
        return False, str(e)


# Streamlit UI layout
st.set_page_config(page_title="Schema Search + NL→SQL + RAG demo", layout="wide")
st.title("Schema Search · NL→SQL · RAG · Feedback")

st.sidebar.header("Controls")
mode = st.sidebar.radio("Demo Mode", ["Schema Search", "NL → SQL", "RAG Demo", "Golden Queries"])
show_sources = st.sidebar.checkbox("Show provenance sources", value=True)
memory_turns = st.sidebar.slider("Conversation memory (last turns)", 1, MAX_MEMORY_TURNS, 4)

if "transcript" not in st.session_state:
    st.session_state.transcript = []  # list of (role, text)

st.sidebar.markdown("### Debug / Backend")
if backend is None:
    st.sidebar.error("`backend` module not found. Provide backend.synthesize_sql, backend.run_sql, backend.fetch_schema_neighbors, backend.synthesize_answer, backend.embed_text.")
else:
    st.sidebar.write("`backend` OK")

if vectorstore is None:
    st.sidebar.warning("`vectorstore` module not found. RAG demo will be disabled.")
else:
    st.sidebar.write("`vectorstore` OK")

if chroma_client is None:
    st.sidebar.info("Chroma DB not found — golden queries will not persist. Install chromadb to enable.")
else:
    st.sidebar.write("Chroma OK (./chroma_db)")

# Utility to append to transcript
def add_turn(role: str, text: str):
    st.session_state.transcript.append((role, text))
    # keep only last memory_turns
    st.session_state.transcript = st.session_state.transcript[-(memory_turns*2):]  # *2 for Q/A pairs

# --- Schema Search Mode ---
if mode == "Schema Search":
    st.header("Schema nearest-neighbour search")
    question = st.text_input("Ask (e.g., \"where's the employee email?\")", value="", key="schema_q")
    if st.button("Search schema"):
        add_turn("user", question)
        if backend is None or not hasattr(backend, "fetch_schema_neighbors"):
            st.error("backend.fetch_schema_neighbors not found. Please implement `fetch_schema_neighbors(question, top_k=5)` returning list of {table, column, snippet, example_sql, score}.")
        else:
            with st.spinner("Searching schema..."):
                neighbors = backend.fetch_schema_neighbors(question, top_k=8)
            if not neighbors:
                st.info("No schema matches found.")
            else:
                st.success(f"Found {len(neighbors)} schema items")
                for idx, n in enumerate(neighbors):
                    col1, col2 = st.columns([3, 2])
                    with col1:
                        st.markdown(f"**{n.get('table','<table>')}.{n.get('column','<column>')}** — _{n.get('score', ''):.3f}_")
                        st.caption(n.get("snippet",""))
                    with col2:
                        suggested_sql = n.get("example_sql") or f"SELECT {n.get('column')} FROM {n.get('table')} LIMIT 10;"
                        st.code(suggested_sql, language="sql")
                        if st.button(f"Use SQL (#{idx})", key=f"use_sql_{idx}"):
                            st.session_state["sql_in_progress"] = suggested_sql
                            st.experimental_rerun()

# --- NL -> SQL Mode ---
if mode == "NL → SQL":
    st.header("Natural Language → SQL")
    q = st.text_input("Question (natural language)", key="nlq")
    schema_context = st.text_area("Schema context (optional) — paste table/column definitions", height=120)
    col1, col2 = st.columns([3,1])
    with col1:
        if st.button("Synthesize SQL"):
            add_turn("user", q)
            if backend is None or not hasattr(backend, "synthesize_sql"):
                st.error("backend.synthesize_sql not found. Provide `synthesize_sql(schema_context, question, few_shot_examples=None)`.")
            else:
                # include any golden queries as few-shot
                few_shot = None
                if chroma_client is not None:
                    try:
                        coll = chroma_client.get_collection("golden_queries")
                        hits = coll.query(query_texts=[q], n_results=3)
                        # hits structure: dict with 'metadatas', 'documents', 'ids'
                        shots = []
                        if hits and hits.get("documents"):
                            for doc, meta in zip(hits['documents'][0], hits['metadatas'][0]):
                                shots.append({"question": meta.get("question"), "sql": meta.get("sql")})
                            few_shot = shots
                    except Exception:
                        few_shot = None

                with st.spinner("Generating SQL..."):
                    try:
                        generated = backend.synthesize_sql(schema_context or None, q, few_shot_examples=few_shot)
                    except Exception as e:
                        st.error(f"Error calling synth: {e}")
                        generated = {"sql": "", "explain": ""}
                sql = generated.get("sql", "").strip()
                add_turn("assistant_sql", sql)
                if not sql:
                    st.warning("No SQL generated.")
                else:
                    safe, reason = sql_is_safe(sql)
                    if not safe:
                        st.error(f"SQL blocked by safety rules: {reason}")
                        st.code(sql, language="sql")
                    else:
                        st.subheader("Generated SQL")
                        st.code(sql, language="sql")
                        if st.button("Run SQL"):
                            if backend is None or not hasattr(backend, "run_sql"):
                                st.error("backend.run_sql not found. Implement run_sql(sql) to execute and return rows & columns.")
                            else:
                                with st.spinner("Running SQL..."):
                                    try:
                                        rows, cols = backend.run_sql(sql)
                                        st.write(f"Returned {len(rows)} rows")
                                        st.dataframe([dict(zip(cols, r)) for r in rows])
                                    except Exception as e:
                                        st.error(f"SQL execution error: {e}")

                    # Feedback UI
                    fb_col1, fb_col2, fb_col3 = st.columns([1,1,4])
                    with fb_col1:
                        if st.button("👍 Good", key="good_sql"):
                            st.success("Thanks for the feedback (saved locally).")
                            # TODO: increment metrics or send telemetry
                    with fb_col2:
                        if st.button("👎 Bad", key="bad_sql"):
                            st.session_state["last_bad_sql"] = sql
                            st.warning("Please paste corrected SQL below and click Save.")
                            st.experimental_rerun()
                    with fb_col3:
                        corrected = st.text_area("Correct SQL (if any)", value=st.session_state.get("last_bad_sql", ""), height=80)
                        if st.button("Save corrected SQL to golden queries"):
                            ok, err = save_golden_question(q, corrected)
                            if ok:
                                st.success("Saved corrected SQL to golden_queries.")
                            else:
                                st.error(f"Failed to save golden: {err}")

# --- RAG Demo Mode ---
if mode == "RAG Demo":
    st.header("Retrieval-Augmented Generation (RAG) demo")
    rag_q = st.text_input("Question for RAG", key="rag_q")
    top_k = st.slider("Top k documents", 1, 10, 4)
    if st.button("Search & Synthesize"):
        add_turn("user", rag_q)
        if vectorstore is None or not hasattr(vectorstore, "search"):
            st.error("vectorstore.search(query, top_k) not implemented. Provide your document vector search function.")
        else:
            with st.spinner("Searching docs..."):
                docs = vectorstore.search(rag_q, top_k=top_k)
            if not docs:
                st.info("No docs returned for query.")
            else:
                st.write(f"Found {len(docs)} doc chunks")
                # show provenance
                for d in docs:
                    st.markdown(f"**Source:** {d.get('source','?')} — _score: {d.get('score',''):.3f}_")
                    st.caption(d.get("text","")[:800])
                # synthesize
                if backend is None or not hasattr(backend, "synthesize_answer"):
                    st.error("backend.synthesize_answer not found. Implement it to synthesize an answer from query + docs.")
                else:
                    with st.spinner("Synthesizing answer..."):
                        try:
                            answer = backend.synthesize_answer(rag_q, docs, show_sources=show_sources)
                        except Exception as e:
                            st.error(f"Synth error: {e}")
                            answer = {"answer": "", "sources": []}
                    st.subheader("Answer (synthesized)")
                    st.write(answer.get("answer"))
                    if show_sources:
                        st.subheader("Provenance used in synthesis")
                        for s in answer.get("sources", []):
                            st.markdown(f"- {s.get('source')} (score {s.get('score','')})")

                    # feedback for RAG
                    if st.button("👍 Good answer", key="good_rag"):
                        st.success("Thanks!")
                    if st.button("👎 Bad answer", key="bad_rag"):
                        st.warning("Please paste a corrected answer below and Save.")
                        st.session_state["last_bad_rag"] = True
                    corrected_rag = st.text_area("Corrected answer (optional)", value="", height=80)
                    if st.button("Save corrected RAG (local)"):
                        # Could persist corrected answers to a 'golden_answers' collection similarly
                        st.info("Saved corrected answer locally (not persisted).")

# --- Golden Queries Viewer ---
if mode == "Golden Queries":
    st.header("Golden Queries (Chroma)")
    coll, err = ensure_golden_collection()
    if coll is None:
        st.error(f"Golden queries not available: {err}")
    else:
        try:
            all_ids = coll.get(include=["metadatas", "documents", "ids"])
            n = len(all_ids.get("ids", []))
            st.write(f"{n} golden items")
            for doc, meta, id_ in zip(all_ids.get("documents", []), all_ids.get("metadatas", []), all_ids.get("ids", [])):
                with st.expander(f"{meta.get('question','<q>')}"):
                    st.write("SQL:")
                    st.code(doc)
                    st.json(meta)
        except Exception as e:
            st.error(f"Error reading golden collection: {e}")

# show transcript / memory
with st.expander("Conversation transcript (recent)"):
    for role, text in st.session_state.transcript:
        if role.startswith("assistant"):
            st.info(f"Assistant: {text}")
        else:
            st.write(f"User: {text}")

st.markdown("---")
st.caption("Streamlit demo by your team — plug backend.* and vectorstore.* to enable full functionality.")