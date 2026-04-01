from __future__ import annotations

"""LangGraph-primary deterministic workflow.

This version keeps LangGraph as the primary orchestrator while restoring the
Phase 1 safety semantics that matter for the demo:
- classify policy/doc/tooling questions first
- only run destructive DB guard on the data path
- preserve golden SQL -> NL->SQL -> SQL safety -> execute order
- allow RAG fallback when the SQL path is empty/placeholder or errors on a doc-ish prompt

Drop-in replacement for backend/router_graph.py.
"""

from functools import lru_cache
from typing import Any, Dict, List, Literal, TypedDict
import re

from langgraph.graph import END, START, StateGraph

from backend import feedback_store, llm_router, nl_to_sql, rag
from backend.hybrid_qa import (
    _db_down_response,
    _is_db_unavailable_error,
    _looks_like_destructive_intent,
    _looks_like_policy_question,
    _sql_is_placeholder_answer,
)
from backend.langsmith_observability import traceable


class RouterState(TypedDict, total=False):
    question: str
    debug: Dict[str, Any]
    route: Literal["data", "rag", "blocked", "none"]
    enable_langsmith: bool
    schema_context: str
    sql: str
    rows: List[Dict[str, Any]]
    columns: List[str]
    sources: List[str]
    hits: List[Dict[str, Any]]
    answer: str
    final: Dict[str, Any]
    golden_hit: bool
    empty_or_placeholder_sql: bool


DOC_TOOLING_HINTS = {
    "bamboo", "jira", "confluence", "bitbucket", "atlassian",
    "repository", "repo", "source repository", "build plan", "pipeline",
    "deployment", "agent", "branch", "checkout", "artifact", "plan",
    "documentation", "docs", "guide", "manual", "knowledge base", "kb",
    "vpn", "onboarding", "policy", "pto", "holiday", "hr",
}
PROCEDURAL_PREFIX_RE = re.compile(r"^(how\s+to|how\s+do\s+i|steps\s+to|process\s+for|procedure\s+for)\b", re.I)


def _looks_like_doc_or_tooling_question(q: str) -> bool:
    ql = (q or "").strip().lower()
    if not ql:
        return False
    if _looks_like_policy_question(ql):
        return True
    if PROCEDURAL_PREFIX_RE.search(ql) and any(k in ql for k in DOC_TOOLING_HINTS):
        return True
    if any(k in ql for k in DOC_TOOLING_HINTS):
        # Questions about product/tool usage, docs, or internal KB content should not
        # be blocked by the DB destructive guard merely because they contain words like
        # "create" or "delete" in a procedural context.
        return True
    return False


@traceable(name="normalize_question", run_type="chain")
def normalize_question(state: RouterState) -> RouterState:
    q = (state.get("question") or "").strip()
    if not q:
        return {
            "route": "none",
            "final": {
                "mode": "none",
                "answer": "Please enter a question.",
                "sql": "",
                "rows": [],
                "columns": [],
                "sources": [],
                "debug": {"reason": "empty_question", "router": "langgraph", "router_impl": "langgraph_primary"},
            },
        }
    return {"question": q, "debug": {"router": "langgraph", "router_impl": "langgraph_primary"}}


@traceable(name="classify_route", run_type="chain")
def classify_route(state: RouterState) -> RouterState:
    q = state["question"]
    if _looks_like_doc_or_tooling_question(q):
        return {
            "route": "rag",
            "debug": {
                **state.get("debug", {}),
                "route": "rag",
                "route_reason": "policy_or_tooling_keywords",
            },
        }
    return {
        "route": "data",
        "debug": {
            **state.get("debug", {}),
            "route": "data",
            "route_reason": "default_data_path",
        },
    }


@traceable(name="destructive_guard", run_type="chain")
def destructive_guard(state: RouterState) -> RouterState:
    q = state["question"]
    if _looks_like_destructive_intent(q):
        return {
            "route": "blocked",
            "final": {
                "mode": "sql",
                "sql": "",
                "rows": [],
                "columns": [],
                "answer": (
                    "For safety, I can’t run destructive database actions (DELETE/DROP/TRUNCATE/etc.). "
                    "I can help with read-only questions like:\n"
                    "- \"Show all users\"\n"
                    "- \"How many users are there?\"\n"
                    "- \"List user emails\""
                ),
                "sources": [],
                "debug": {**state.get("debug", {}), "reason": "blocked_destructive_intent", "route": "blocked"},
            },
        }
    return {}


@traceable(name="fetch_schema_context", run_type="retriever")
def fetch_schema_context_node(state: RouterState) -> RouterState:
    try:
        return {"schema_context": nl_to_sql.fetch_schema_context()}
    except Exception as e:
        return {"schema_context": "", "debug": {**state.get("debug", {}), "schema_context_error": str(e)}}


@traceable(name="golden_lookup", run_type="retriever")
def golden_lookup_node(state: RouterState) -> RouterState:
    q = state["question"]
    hit = feedback_store.find_best_golden_sql(q)
    if not hit:
        return {"golden_hit": False}

    sql, gdbg = hit
    return {"golden_hit": True, "sql": sql, "debug": {**state.get("debug", {}), **gdbg}}


@traceable(name="nl_to_sql", run_type="llm")
def nl2sql_node(state: RouterState) -> RouterState:
    sql, sdbg = nl_to_sql.generate_sql(state["question"], schema_context=state.get("schema_context") or None)
    return {"sql": sql, "debug": {**state.get("debug", {}), **sdbg}}


@traceable(name="sql_safety", run_type="chain")
def sql_safety_node(state: RouterState) -> RouterState:
    try:
        sql_norm = nl_to_sql.validate_and_normalize_sql(state["sql"])
        return {"sql": sql_norm}
    except Exception as e:
        return {
            "final": {
                "mode": "sql",
                "sql": state.get("sql", ""),
                "rows": [],
                "columns": [],
                "answer": f"SQL blocked by safety rules: {e}",
                "sources": [],
                "debug": {**state.get("debug", {}), "reason": "sql_safety_blocked", "sql_error": str(e)},
            }
        }


@traceable(name="execute_sql", run_type="tool")
def execute_sql_node(state: RouterState) -> RouterState:
    try:
        rows, cols = nl_to_sql.execute_sql(state["sql"])
        empty_or_placeholder = _sql_is_placeholder_answer(state["sql"], rows, cols)

        # Legacy-compatible fallback: if the SQL path looks fake/empty and the prompt
        # is actually doc-ish/tooling-ish, pivot to RAG.
        if empty_or_placeholder or (len(rows) == 0 and _looks_like_doc_or_tooling_question(state["question"])):
            return {
                "empty_or_placeholder_sql": True,
                "debug": {**state.get("debug", {}), "route": "rag", "route_reason": "sql_empty_or_placeholder_fallback"},
            }

        return {
            "rows": rows,
            "columns": cols,
            "final": {
                "mode": "sql",
                "sql": state["sql"],
                "rows": rows,
                "columns": cols,
                "answer": f"Returned {len(rows)} row(s).",
                "sources": [],
                "debug": {
                    **state.get("debug", {}),
                    "reason": "golden_sql_success" if state.get("golden_hit") else "sql_success",
                    "route": "data",
                },
            },
        }
    except Exception as e:
        if _is_db_unavailable_error(e):
            return {
                "final": _db_down_response(
                    debug={**state.get("debug", {}), "sql_provider": state.get("debug", {}).get("sql_provider", "unknown")},
                    sql=state.get("sql", ""),
                )
            }
        if _looks_like_doc_or_tooling_question(state["question"]):
            return {
                "debug": {**state.get("debug", {}), "sql_error": str(e), "route": "rag", "route_reason": "sql_error_doc_fallback"},
                "empty_or_placeholder_sql": True,
            }
        return {
            "final": {
                "mode": "sql",
                "sql": state.get("sql", ""),
                "rows": [],
                "columns": [],
                "answer": f"SQL execution error: {e}",
                "sources": [],
                "debug": {**state.get("debug", {}), "reason": "sql_execution_error", "sql_error": str(e)},
            }
        }


@traceable(name="rag_retrieve", run_type="retriever")
def rag_retrieve_node(state: RouterState) -> RouterState:
    hits = rag.retrieve(state["question"], k=4)
    return {"hits": hits}


@traceable(name="rag_answer", run_type="llm")
def rag_answer_node(state: RouterState) -> RouterState:
    hits = state.get("hits") or []
    if not hits:
        return {
            "final": {
                "mode": "rag",
                "sql": "",
                "rows": [],
                "columns": [],
                "answer": "I couldn't find anything relevant in the knowledge documents.",
                "sources": [],
                "debug": {**state.get("debug", {}), "reason": "no_hits", "k": 4, "collection": "docs", "route": "rag"},
            }
        }

    sources: List[str] = []
    context_blocks: List[str] = []
    for i, h in enumerate(hits, start=1):
        meta = h.get("meta") or {}
        src = meta.get("source") or meta.get("file") or "document"
        if src and src not in sources:
            sources.append(src)
        context_blocks.append(f"[{i}] {src}\n{(h.get('text') or '').strip()}")

    context = "\n\n---\n\n".join(context_blocks)
    content = llm_router.chat_completion(
        messages=[
            {
                "role": "system",
                "content": (
                    "You are CGI AIO Assistant. Answer the user's question using ONLY the provided context "
                    "from internal documents. If the answer is not in the context, say you don't know. "
                    "Be concise and actionable."
                ),
            },
            {"role": "user", "content": f"Question: {state['question']}\n\nContext:\n{context}\n\nAnswer:"},
        ],
        temperature=0.2,
        max_tokens=400,
    )

    return {
        "sources": sources,
        "final": {
            "mode": "rag",
            "sql": "",
            "rows": [],
            "columns": [],
            "answer": (content or "").strip(),
            "sources": sources,
            "debug": {
                **state.get("debug", {}),
                "reason": "policy_rag" if _looks_like_doc_or_tooling_question(state["question"]) else "rag_success",
                "k": 4,
                "collection": "docs",
                "route": "rag",
            },
        },
    }


def after_classify(state: RouterState) -> str:
    if state.get("route") == "rag":
        return "rag_retrieve"
    return "guardrails"


def after_guardrails(state: RouterState) -> str:
    if state.get("final"):
        return "finalize"
    return "fetch_schema_context"


def after_golden_lookup(state: RouterState) -> str:
    if state.get("golden_hit"):
        return "sql_safety"
    return "nl_to_sql"


def after_sql_safety(state: RouterState) -> str:
    if state.get("final"):
        return "finalize"
    return "execute_sql"


def after_execute_sql(state: RouterState) -> str:
    if state.get("final"):
        return "finalize"
    return "rag_retrieve"


def finalize_node(state: RouterState) -> RouterState:
    final = state.get("final") or {
        "mode": "error",
        "sql": state.get("sql", ""),
        "rows": state.get("rows", []),
        "columns": state.get("columns", []),
        "answer": "Something went wrong while answering. Try again or check logs.",
        "sources": state.get("sources", []),
        "debug": {**state.get("debug", {}), "reason": "unhandled_state"},
    }
    return {"final": final}


@lru_cache(maxsize=1)
def get_compiled_graph():
    graph = StateGraph(RouterState)

    graph.add_node("normalize", normalize_question)
    graph.add_node("classify", classify_route)
    graph.add_node("guardrails", destructive_guard)
    graph.add_node("fetch_schema_context", fetch_schema_context_node)
    graph.add_node("golden_lookup", golden_lookup_node)
    graph.add_node("nl_to_sql", nl2sql_node)
    graph.add_node("sql_safety", sql_safety_node)
    graph.add_node("execute_sql", execute_sql_node)
    graph.add_node("rag_retrieve", rag_retrieve_node)
    graph.add_node("rag_answer", rag_answer_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "normalize")
    graph.add_edge("normalize", "classify")
    graph.add_conditional_edges("classify", after_classify, {
        "rag_retrieve": "rag_retrieve",
        "guardrails": "guardrails",
    })
    graph.add_conditional_edges("guardrails", after_guardrails, {
        "fetch_schema_context": "fetch_schema_context",
        "finalize": "finalize",
    })
    graph.add_edge("fetch_schema_context", "golden_lookup")
    graph.add_conditional_edges("golden_lookup", after_golden_lookup, {
        "sql_safety": "sql_safety",
        "nl_to_sql": "nl_to_sql",
    })
    graph.add_edge("nl_to_sql", "sql_safety")
    graph.add_conditional_edges("sql_safety", after_sql_safety, {
        "execute_sql": "execute_sql",
        "finalize": "finalize",
    })
    graph.add_conditional_edges("execute_sql", after_execute_sql, {
        "finalize": "finalize",
        "rag_retrieve": "rag_retrieve",
    })
    graph.add_edge("rag_retrieve", "rag_answer")
    graph.add_edge("rag_answer", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()
