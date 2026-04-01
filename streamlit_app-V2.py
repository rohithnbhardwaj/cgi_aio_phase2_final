import os
import uuid
import math
import base64
import json
import inspect
from copy import deepcopy

import streamlit as st

st.set_page_config(page_title="CGI AIO Assistant", layout="wide")

from ui.branding import apply_branding

apply_branding()

try:
    from backend.entrypoint import answer_question  # type: ignore  # noqa: E402
    ANSWER_BACKEND = "entrypoint"
except Exception:
    from backend.hybrid_qa import answer_question  # type: ignore  # noqa: E402
    ANSWER_BACKEND = "hybrid_qa"

# optional feedback store
try:
    from backend.feedback_store import save_feedback  # type: ignore
except Exception:
    save_feedback = None  # type: ignore

# optional document ingest (UI upload -> /app/uploads -> Chroma docs)
try:
    from backend.doc_ingest import (  # type: ignore
        save_to_uploads,
        ingest_file,
        ingest_staged_files,
    )
except Exception:
    save_to_uploads = None  # type: ignore
    ingest_file = None  # type: ignore
    ingest_staged_files = None  # type: ignore

# optional SQL execution helpers for corrected-SQL preview
try:
    from backend import nl_to_sql as _ui_sql_backend  # type: ignore
except Exception:
    _ui_sql_backend = None  # type: ignore


# -----------------------------
# Layout constants (no UI sliders)
# -----------------------------
SIDEBAR_WIDTH_PX = int(os.getenv("SIDEBAR_WIDTH_PX", "430"))
LAYOUT_GUTTER_REM = float(os.getenv("LAYOUT_GUTTER_REM", "1.2"))


# -----------------------------
# Professional SVG badge avatars (NO external URLs)
# -----------------------------
def _svg_avatar(text: str, bg: str, fg: str) -> str:
    """Returns a data: URI for an SVG circle avatar with centered text."""
    text = (text or "").strip()[:3]
    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">
      <circle cx="32" cy="32" r="30" fill="{bg}" />
      <text x="32" y="40" font-size="22" text-anchor="middle"
            font-family="Arial, sans-serif" fill="{fg}" font-weight="700">{text}</text>
    </svg>
    """.strip()
    b64 = base64.b64encode(svg.encode("utf-8")).decode("utf-8")
    return f"data:image/svg+xml;base64,{b64}"


USER_AVATAR = _svg_avatar("RM", bg="#374151", fg="#F9FAFB")
BOT_AVATAR = _svg_avatar("CGI", bg="#E31837", fg="#FFFFFF")


# -----------------------------
# Capability detection for Phase 2 flags
# -----------------------------
try:
    _ANSWER_SIG = inspect.signature(answer_question)
    _ANSWER_PARAMS = _ANSWER_SIG.parameters
    _ANSWER_ACCEPTS_VAR_KW = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in _ANSWER_PARAMS.values())
except Exception:
    _ANSWER_PARAMS = {}
    _ANSWER_ACCEPTS_VAR_KW = False


def _env_flag(name: str, default: str = "0") -> bool:
    return str(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "on"}


def _rollback_allowed() -> bool:
    return _env_flag("ALLOW_LEGACY_ROLLBACK", "1") and (
        "use_langgraph" in _ANSWER_PARAMS or _ANSWER_ACCEPTS_VAR_KW
    )


def _legacy_rollback_enabled() -> bool:
    return bool(st.session_state.get("use_legacy_router", False)) and _rollback_allowed()


def _routing_engine_label() -> str:
    if ANSWER_BACKEND == "entrypoint":
        return "Legacy rollback" if _legacy_rollback_enabled() else "LangGraph Primary"
    return "Legacy Hybrid Fallback"


def _call_answer_question(question: str) -> dict:
    kwargs: dict = {}

    if "use_langgraph" in _ANSWER_PARAMS or _ANSWER_ACCEPTS_VAR_KW:
        kwargs["use_langgraph"] = not _legacy_rollback_enabled()

    if "enable_langsmith" in _ANSWER_PARAMS or _ANSWER_ACCEPTS_VAR_KW:
        kwargs["enable_langsmith"] = bool(st.session_state.get("enable_langsmith", False))
    elif "langsmith_enabled" in _ANSWER_PARAMS or _ANSWER_ACCEPTS_VAR_KW:
        kwargs["langsmith_enabled"] = bool(st.session_state.get("enable_langsmith", False))

    try:
        if kwargs:
            return answer_question(question, **kwargs)
        return answer_question(question)
    except TypeError:
        return answer_question(question)


# -----------------------------
# CSS / Layout (stable left panel, form input pinned bottom)
# -----------------------------
def _inject_css() -> None:
    st.markdown(
        f"""
        <style>
        :root {{
          --cgi-leftpanel-width: clamp(360px, 24vw, {SIDEBAR_WIDTH_PX}px);
          --cgi-gutter: {LAYOUT_GUTTER_REM}rem;
          --cgi-page-pad: 1rem;
          --cgi-brand-red: #E31837;
          --cgi-brand-purple: #6E4BD8;
          --cgi-sidebar-bg-top: #e5ebf4;
          --cgi-sidebar-bg-bottom: #d8e1ed;
        }}

        html {{
          scroll-behavior: smooth;
        }}

        /* Hide Streamlit chrome safely */
        #MainMenu {{visibility: hidden;}}
        footer {{visibility: hidden;}}
        [data-testid="stHeader"] {{display: none;}}

        /* Wider layout with room for fixed dock */
        .block-container {{
            max-width: 100% !important;
            padding-left: 1.0rem !important;
            padding-right: 1.0rem !important;
            padding-top: 4.85rem !important;
            padding-bottom: 12.0rem !important;
        }}

        /* Page scrollbars */
        * {{
          scrollbar-width: thin;
          scrollbar-color: #b7c3d7 #edf2f7;
        }}

        *::-webkit-scrollbar {{
          width: 10px;
          height: 10px;
        }}

        *::-webkit-scrollbar-track {{
          background: #edf2f7;
          border-radius: 999px;
        }}

        *::-webkit-scrollbar-thumb {{
          background: #b7c3d7;
          border-radius: 999px;
          border: 2px solid #edf2f7;
        }}

        *::-webkit-scrollbar-thumb:hover {{
          background: #9aa9c4;
        }}

        .st-key-cgi_shell > div[data-testid="stHorizontalBlock"] {{
            align-items: flex-start !important;
            flex-wrap: nowrap !important;
            gap: var(--cgi-gutter) !important;
        }}

        .st-key-cgi_shell > div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {{
            align-self: flex-start !important;
        }}

        div[data-testid="column"]:has(.st-key-cgi_left_sidebar) {{
            align-self: flex-start !important;
            position: relative !important;
        }}

        @media (min-width: 1200px) {{
          .st-key-cgi_shell > div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:first-child {{
              flex: 0 0 var(--cgi-leftpanel-width) !important;
              width: var(--cgi-leftpanel-width) !important;
              max-width: var(--cgi-leftpanel-width) !important;
          }}
          .st-key-cgi_shell > div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:nth-child(2) {{
              flex: 1 1 0 !important;
              min-width: 0 !important;
          }}
        }}

        /* Left sidebar container: fixed operator rail on desktop */
        .st-key-cgi_left_sidebar {{
            width: 100%;
            background: linear-gradient(180deg, var(--cgi-sidebar-bg-top) 0%, var(--cgi-sidebar-bg-bottom) 100%);
            border: 1px solid rgba(148, 163, 184, 0.55);
            border-radius: 18px;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.10);
            padding: 0.95rem;
            z-index: 1002;
        }}

        @media (min-width: 1200px) {{
          .st-key-cgi_left_sidebar {{
              position: fixed !important;
              top: 86px !important;
              left: 1rem !important;
              width: var(--cgi-leftpanel-width) !important;
              max-height: none !important;
              overflow: visible !important;
          }}
        }}

        @media (min-width: 900px) and (max-width: 1199px) {{
          .st-key-cgi_left_sidebar {{
              position: fixed !important;
              top: 86px !important;
              left: 1rem !important;
              width: 320px !important;
              max-height: none !important;
              overflow: visible !important;
          }}
        }}

        .st-key-cgi_left_sidebar > div {{
            opacity: 1 !important;
            filter: none !important;
        }}

        .st-key-cgi_left_sidebar h2,
        .st-key-cgi_left_sidebar h3,
        .st-key-cgi_left_sidebar p,
        .st-key-cgi_left_sidebar span,
        .st-key-cgi_left_sidebar label,
        .st-key-cgi_left_sidebar div {{
            color: #0f172a;
        }}

        .st-key-cgi_left_sidebar .stCaptionContainer,
        .st-key-cgi_left_sidebar [data-testid="stCaptionContainer"] {{
            color: rgba(15, 23, 42, 0.75) !important;
        }}

        .st-key-cgi_left_sidebar hr {{
            border: none !important;
            height: 1px !important;
            background: rgba(15, 23, 42, 0.10) !important;
            margin: 1rem 0 !important;
        }}

        .st-key-cgi_left_sidebar .stExpander {{
            background: rgba(255,255,255,0.35);
            border: 1px solid rgba(148,163,184,0.32);
            border-radius: 12px;
            overflow: hidden;
        }}

        .st-key-cgi_left_sidebar [data-testid="stExpander"] details {{
            border: none !important;
        }}

        .st-key-cgi_left_sidebar [data-testid="stExpander"] summary {{
            background: rgba(255,255,255,0.28) !important;
            border-radius: 12px !important;
        }}

        .cgi-status-row {{
            display:flex;
            flex-wrap:wrap;
            gap:0.45rem;
            margin:0.25rem 0 0.45rem 0;
        }}

        .cgi-status-pill {{
            display:inline-flex;
            align-items:center;
            gap:0.38rem;
            padding:0.34rem 0.62rem;
            border-radius:999px;
            font-size:0.79rem;
            font-weight:700;
            border:1px solid transparent;
            line-height:1;
        }}

        .cgi-status-pill.red {{
            background:#fef2f2;
            border-color:#fecaca;
            color:#b91c1c;
        }}

        .cgi-status-pill.blue {{
            background:#eff6ff;
            border-color:#bfdbfe;
            color:#1d4ed8;
        }}

        .cgi-status-pill.green {{
            background:#ecfdf5;
            border-color:#bbf7d0;
            color:#166534;
        }}

        .cgi-status-pill.slate {{
            background:#f8fafc;
            border-color:#cbd5e1;
            color:#334155;
        }}

        .cgi-setting-note {{
            color: rgba(15, 23, 42, 0.82);
            font-size: 0.83rem;
            line-height: 1.35;
        }}

        /* Sidebar action buttons */
        .st-key-cgi_left_sidebar div.stButton > button,
        .st-key-cgi_left_sidebar div.stDownloadButton > button {{
            border: 1px solid rgba(15,23,42,0.12) !important;
            box-shadow: 0 1px 8px rgba(0,0,0,0.07) !important;
            border-radius: 10px !important;
            font-size: 0.93rem !important;
            line-height: 1.12 !important;
            padding: 0.52rem 0.72rem !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            background: rgba(255,255,255,0.78) !important;
        }}

        /* Main column */
        .st-key-cgi_main_panel {{
            min-width: 0;
            padding-bottom: 9.0rem;
        }}

        @media (min-width: 1200px) {{
          .st-key-cgi_main_panel [data-testid="stChatMessage"] {{
              max-width: min(1180px, 100%);
          }}
        }}

        /* Welcome header */
        .cgi-center {{
            text-align: center;
        }}

        .muted {{
            color: rgba(17,24,39,0.72);
            font-size: 0.86rem;
        }}

        /* Chat message width */
        [data-testid="stChatMessageContent"] {{
            max-width: 100% !important;
        }}

        /* Avatar sizing */
        [data-testid="stChatMessageAvatar"] img {{
            width: 36px !important;
            height: 36px !important;
            border-radius: 999px !important;
            border: 1px solid rgba(0,0,0,0.08);
        }}

        /* Fixed bottom chat dock */
        .st-key-cgi_chat_dock {{
            background: #ffffff;
            border: 1px solid rgba(227, 24, 55, 0.18);
            border-radius: 18px;
            box-shadow: 0 18px 38px rgba(15, 23, 42, 0.10), 0 0 0 4px rgba(227,24,55,0.04);
            padding: 0.78rem 0.9rem 0.22rem 0.9rem;
            opacity: 1 !important;
            filter: none !important;
        }}

        @media (min-width: 1200px) {{
          .st-key-cgi_chat_dock {{
              position: fixed;
              bottom: 18px;
                /* start after the left panel */
                left: calc(var(--cgi-leftpanel-width) + var(--cgi-gutter) + 1.5rem) !important;

                /* end near the right edge */
                right: 1.5rem !important;

                /* fill the whole available width */
                width: auto !important;
                max-width: none !important;

                /* stop center-shifting */
                transform: none !important;

                z-index: 25;
              
          }}
        }}

        @media (min-width: 900px) and (max-width: 1199px) {{
          .st-key-cgi_chat_dock {{
              position: fixed;
              bottom: 18px;
              left: calc(var(--cgi-page-pad) + 340px + var(--cgi-gutter) + 0.15rem) !important;
              right: 1.0rem !important;
              width: auto !important;
              max-width: none !important;
              z-index: 25;
          }}
        }}
        .st-key-cgi_chat_dock textarea {{
            min-height: 100px !important;
            padding-top: 15px !important;
            padding-bottom: 15px !important;
            line-height: 1.5 !important;
        }}


        .st-key-cgi_chat_dock form {{
            border: 0 !important;
        }}

        .st-key-cgi_chat_dock [data-testid="stForm"] {{
            border: 0 !important;
            padding: 0 !important;
            background: transparent !important;
        }}

        .st-key-cgi_chat_dock div[data-testid="stTextArea"] textarea {{
            min-height: 74px !important;
            border-radius: 14px !important;
            border: 1px solid #d8deeb !important;
            background: #fbfbfe !important;
            box-shadow: none !important;
            resize: vertical !important;
            line-height: 1.45 !important;
            padding-top: 0.7rem !important;
            padding-bottom: 0.7rem !important;
        }}

        .st-key-cgi_chat_dock div[data-testid="stTextArea"] label {{
            display: none !important;
        }}

        .st-key-cgi_chat_dock div[data-testid="stFormSubmitButton"] > button {{
            width: 100% !important;
            min-height: 46px !important;
            border: none !important;
            border-radius: 999px !important;
            background: linear-gradient(90deg, #E31837 0%, #C81E63 46%, #6E4BD8 100%) !important;
            color: white !important;
            font-weight: 700 !important;
            box-shadow: 0 12px 24px rgba(110, 75, 216, 0.18) !important;
        }}

        .st-key-cgi_chat_dock div[data-testid="stFormSubmitButton"] > button:hover {{
            filter: brightness(1.02) !important;
            transform: translateY(-1px);
        }}

        .st-key-cgi_sidebar_quick_prompts {{
            position: sticky;
            bottom: -0.15rem;
            z-index: 8;
            margin-top: 0.8rem;
            padding-top: 0.7rem;
            background: linear-gradient(
                180deg,
                rgba(216,225,237,0.00) 0%,
                rgba(216,225,237,0.88) 22%,
                rgba(216,225,237,0.98) 100%
            );
        }}

        .st-key-cgi_sidebar_quick_prompts div.stButton > button {{
            background: rgba(255,255,255,0.92) !important;
            border: 1px solid rgba(15,23,42,0.10) !important;
            border-radius: 999px !important;
            min-height: 34px !important;
            padding-top: 0.15rem !important;
            padding-bottom: 0.15rem !important;
            text-align: left !important;
            justify-content: flex-start !important;
            font-size: 0.82rem !important;
        }}

        .cgi-upload-hint {{
            display:flex;
            align-items:center;
            gap:0.75rem;
            background: rgba(255,255,255,0.72);
            border:1px solid rgba(148,163,184,0.28);
            border-radius: 14px;
            padding: 0.75rem 0.85rem;
            margin: 0.35rem 0 0.55rem 0;
        }}
        .cgi-upload-hint .icon {{
            width: 38px; height: 38px; border-radius: 999px;
            display:flex; align-items:center; justify-content:center;
            background: #ffffff; border:1px solid rgba(148,163,184,0.30);
            font-size: 1.1rem;
        }}
        .cgi-upload-hint .title {{
            font-weight:700; font-size:0.92rem; color:#0f172a;
        }}
        .cgi-upload-hint .sub {{
            font-size:0.78rem; color:rgba(15,23,42,0.74); margin-top:0.1rem;
        }}

        .cgi-footer-note {{
            position: fixed;
            left: 1.1rem;
            bottom: 0.55rem;
            z-index: 12;
            color: rgba(15,23,42,0.82);
            font-size: 0.84rem;
            font-weight: 500;
            background: rgba(255,255,255,0.82);
            border: 1px solid rgba(148,163,184,0.16);
            border-radius: 10px;
            padding: 0.22rem 0.55rem;
            backdrop-filter: blur(2px);
        }}

        .cgi-source-badges span {{
            display:inline-block;
            margin:0.2rem 0.35rem 0.2rem 0;
            padding:0.24rem 0.55rem;
            border-radius:999px;
            background:#f1f5f9;
            border:1px solid #dbeafe;
            font-size:0.78rem;
            color:#334155;
        }}

        .cgi-feedback-form {{
            border: 1px solid rgba(148, 163, 184, 0.35);
            border-left: 4px solid #E31837;
            border-radius: 12px;
            padding: 0.75rem 0.85rem 0.2rem 0.85rem;
            background: rgba(255,255,255,0.92);
            margin-top: 0.6rem;
            max-width: min(980px, calc(100% - 1rem));
            margin-left: auto;
            margin-right: auto;
        }}

        @media (max-width: 899px) {{
          .st-key-cgi_left_sidebar {{
              position: relative !important;
              top: 0 !important;
              left: auto !important;
              width: 100% !important;
              max-height: none !important;
              overflow: visible !important;
              padding-bottom: 1rem !important;
          }}
          .st-key-cgi_chat_dock {{
              position: relative;
              left: auto;
              right: auto;
              bottom: auto;
              margin-top: 1rem;
              width: auto !important;
              transform: none !important;
          }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# -----------------------------
# Lightweight UX helpers
# -----------------------------
def _toast(msg: str, icon: str = "✅") -> None:
    try:
        st.toast(msg, icon=icon)
    except Exception:
        st.success(msg)


def _enqueue_toast(msg: str, icon: str = "✅") -> None:
    st.session_state["_pending_toast"] = {"msg": msg, "icon": icon}


def _flush_toast() -> None:
    t = st.session_state.pop("_pending_toast", None)
    if t:
        _toast(t["msg"], icon=t.get("icon", "✅"))


def _safe_cache_clear() -> None:
    try:
        st.cache_data.clear()
    except Exception:
        pass


def _apply_correction_preview(msg: dict, corrected_sql: str | None, corrected_answer: str | None) -> None:
    """Apply the user's correction immediately to the current assistant card.

    - corrected SQL: validate + execute and replace the current SQL result preview
    - corrected answer: replace the visible assistant text for doc / RAG style fixes
    """
    out = msg.setdefault('out', {})
    debug = out.setdefault('debug', {})

    final_answer = (corrected_answer or '').strip()
    final_sql = (corrected_sql or '').strip()

    if final_sql and _ui_sql_backend is not None:
        sql_norm = _ui_sql_backend.validate_and_normalize_sql(final_sql)
        rows, cols = _ui_sql_backend.execute_sql(sql_norm)
        out.update({
            'mode': 'sql',
            'sql': sql_norm,
            'rows': rows,
            'columns': cols,
            'sources': [],
            'answer': final_answer or f'Returned {len(rows)} row(s) from corrected SQL.',
        })
        debug.update({
            'reason': 'feedback_correction_preview',
            'correction_type': 'sql',
            'sql_provider': 'feedback_correction',
        })
        msg['content'] = final_answer or out['answer']
        return

    if final_answer:
        out.update({
            'mode': out.get('mode') or 'rag',
            'answer': final_answer,
        })
        debug.update({
            'reason': 'feedback_correction_preview',
            'correction_type': 'answer',
        })
        msg['content'] = final_answer


# -----------------------------
# Feedback stats (Chroma)
# -----------------------------
@st.cache_data(ttl=15)
def _get_feedback_overview() -> dict:
    try:
        import chromadb  # type: ignore

        chroma_dir = os.getenv("CHROMA_DIR", "/app/vector_store")
        feedback_collection = os.getenv("FEEDBACK_COLLECTION", "feedback_events")
        golden_collection = os.getenv("GOLDEN_COLLECTION", "golden_queries")

        # IMPORTANT: use the same simple PersistentClient signature as backend.rag and
        # backend.feedback_store to avoid: "An instance of Chroma already exists ... with different settings"
        client = chromadb.PersistentClient(path=chroma_dir)

        fb = client.get_or_create_collection(name=feedback_collection, metadata={"hnsw:space": "cosine"})
        res = fb.get(include=["metadatas"])
        metas = res.get("metadatas") or []

        good = 0
        bad = 0
        for m in metas:
            rating = (m or {}).get("rating")
            if rating is None:
                continue
            try:
                r = int(rating)
            except Exception:
                continue
            if r == 1:
                good += 1
            elif r == 0:
                bad += 1

        total = good + bad

        gold = client.get_or_create_collection(name=golden_collection, metadata={"hnsw:space": "cosine"})
        golden_count = int(getattr(gold, "count", lambda: 0)() or 0)

        return {"good": good, "bad": bad, "total": total, "golden": golden_count}
    except Exception:
        return {"good": 0, "bad": 0, "total": 0, "golden": 0}


def _ring_svg(percent: float, size: int = 76, stroke: int = 10) -> str:
    pct = max(0.0, min(100.0, float(percent)))
    r = (size - stroke) / 2
    c = 2 * math.pi * r
    dash = (pct / 100.0) * c
    gap = c - dash

    return f"""
    <div style=\"display:flex; gap:14px; align-items:center;\">
      <svg width=\"{size}\" height=\"{size}\" viewBox=\"0 0 {size} {size}\">
        <circle cx=\"{size/2}\" cy=\"{size/2}\" r=\"{r}\" fill=\"none\" stroke=\"#e5e7eb\" stroke-width=\"{stroke}\" />
        <circle cx=\"{size/2}\" cy=\"{size/2}\" r=\"{r}\" fill=\"none\" stroke=\"#E31837\" stroke-width=\"{stroke}\"
                stroke-linecap=\"round\" stroke-dasharray=\"{dash} {gap}\"
                transform=\"rotate(-90 {size/2} {size/2})\" />
        <text x=\"50%\" y=\"52%\" text-anchor=\"middle\" font-size=\"16\" font-family=\"Arial\" fill=\"#111827\" font-weight=\"700\">{pct:.0f}%</text>
      </svg>
      <div>
        <div style=\"font-weight:700; color:#111827;\">Positive rate</div>
        <div class=\"muted\">👍 Good / Total</div>
      </div>
    </div>
    """


def _bars_html(good: int, bad: int, total: int, golden: int) -> str:
    good = int(good)
    bad = int(bad)
    total = int(total)
    golden = int(golden)
    denom = max(1, total)
    good_w = 100.0 * good / denom
    bad_w = 100.0 * bad / denom
    track = "#e5e7eb"

    return f"""
    <div style=\"margin-top:6px;\">
      <div style=\"display:flex; justify-content:space-between; color:#111827;\">
        <span>👍 Good</span><b>{good}</b>
      </div>
      <div style=\"height:8px; background:{track}; border-radius:99px; overflow:hidden; margin:6px 0 12px;\">
        <div style=\"height:100%; width:{good_w:.1f}%; background:#16a34a;\"></div>
      </div>

      <div style=\"display:flex; justify-content:space-between; color:#111827;\">
        <span>👎 Bad</span><b>{bad}</b>
      </div>
      <div style=\"height:8px; background:{track}; border-radius:99px; overflow:hidden; margin:6px 0 12px;\">
        <div style=\"height:100%; width:{bad_w:.1f}%; background:#dc2626;\"></div>
      </div>

      <div style=\"display:flex; justify-content:space-between; color:#111827; opacity:0.95; margin-top:4px;\">
        <span>Total</span><b>{total}</b>
      </div>
      <div style=\"display:flex; justify-content:space-between; color:#111827; opacity:0.95; margin-top:4px;\">
        <span>⭐ Promoted</span><b>{golden}</b>
      </div>
    </div>
    """


def _recent_user_prompts() -> tuple[list[str], bool]:
    chat = st.session_state.get("chat") or []
    prompts = [m.get("content") for m in chat if m.get("role") == "user" and m.get("content")]
    if prompts:
        return prompts, False

    backup = st.session_state.get("chat_backup")
    if backup:
        prompts = [m.get("content") for m in backup if m.get("role") == "user" and m.get("content")]
        return prompts, True

    return [], False


def _render_quick_prompts(max_items: int = 6) -> None:
    prompts, from_backup = _recent_user_prompts()
    if not prompts:
        return

    with st.container(key="cgi_sidebar_quick_prompts"):
        st.markdown("### Recent prompts")
        st.caption("Tap any prompt to re-run it without scrolling back up.")
        if from_backup:
            st.caption("From last cleared chat")

        for i, p in enumerate(reversed(prompts[-max_items:])):
            label = p if len(p) <= 60 else p[:60] + "…"
            if st.button(label, key=f"side_quick_prompt_{i}", use_container_width=True):
                st.session_state.pending_question = p
                _enqueue_toast("Re-running selected prompt…", icon="💬")
                st.rerun()



# -----------------------------
# Sidebar sections
# -----------------------------
def _render_doc_upload_panel() -> None:
    st.markdown("### Upload documents")

    if save_to_uploads is None or ingest_file is None:
        st.caption("Document upload is not available in this build.")
        return

    uploaded = st.file_uploader(
        "Upload documents",
        type=["pdf", "docx", "txt"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )

    replace_existing = st.checkbox("Replace existing", value=True)

    b1, b2 = st.columns(2)
    did_work = False

    with b1:
        if st.button("⬆️ Upload & ingest", use_container_width=True):
            if not uploaded:
                st.warning("Please select at least one file.")
            else:
                total_files = 0
                total_chunks = 0
                any_error = False

                for f in uploaded:
                    try:
                        path = save_to_uploads(f.name, f.getvalue())
                        res = ingest_file(path, replace_existing=replace_existing)
                        if res.get("ok"):
                            total_files += 1
                            total_chunks += int(res.get("chunks") or 0)
                        else:
                            any_error = True
                            st.error(f"{res.get('file')}: {res.get('reason')}")
                    except Exception as e:
                        any_error = True
                        st.error(f"{getattr(f, 'name', 'file')}: {e}")

                if total_files:
                    st.session_state["last_ingest_summary"] = (
                        f"Last ingest: {total_files} file(s) ingested ({total_chunks} chunks)."
                    )
                    _enqueue_toast(f"Ingested {total_files} file(s) ({total_chunks} chunks).", icon="✅")
                    did_work = True
                elif not any_error:
                    st.warning("No files were ingested.")

    with b2:
        if ingest_staged_files is not None:
            if st.button("🔄 Ingest staged", use_container_width=True):
                results = ingest_staged_files(replace_existing=replace_existing)
                ok = [r for r in results if r.get("ok")]
                total_files = len(ok)
                total_chunks = sum(int(r.get("chunks") or 0) for r in ok)

                for r in results:
                    if not r.get("ok"):
                        st.error(f"{r.get('file')}: {r.get('reason')}")

                if total_files:
                    st.session_state["last_ingest_summary"] = (
                        f"Last ingest: {total_files} file(s) ingested ({total_chunks} chunks)."
                    )
                    _enqueue_toast(
                        f"Ingested {total_files} staged file(s) ({total_chunks} chunks).",
                        icon="✅",
                    )
                    did_work = True
                else:
                    st.info("No staged files were ingested.")

    if st.session_state.get("last_ingest_summary"):
        st.success(st.session_state["last_ingest_summary"])

    if did_work:
        _safe_cache_clear()


def _render_system_settings() -> None:
    with st.expander("⚙️ System settings", expanded=False):
        st.toggle(
            "Show technical details",
            value=bool(st.session_state.get("show_tech", False)),
            key="show_tech",
            help="Show generated SQL, route/debug metadata, and trace context during the demo.",
        )

        st.toggle(
            "Capture LangSmith trace",
            value=bool(st.session_state.get("enable_langsmith", False)),
            key="enable_langsmith",
            help="Capture a LangSmith trace for observability and evaluation when the backend supports it.",
        )

        st.caption(
            "LangGraph is the primary orchestration engine for this demo. "
            "LangSmith can be turned on when you want to show traceability and evaluation readiness."
        )


def _render_feedback_panel() -> None:
    st.markdown("### Feedback & learning")
    st.caption("Live demo health, promotion, and operator controls")

    stats = _get_feedback_overview()
    good = stats["good"]
    bad = stats["bad"]
    total = stats["total"]
    golden = stats["golden"]
    positive = (good / total * 100.0) if total > 0 else 0.0

    st.markdown(_ring_svg(positive), unsafe_allow_html=True)
    st.markdown(_bars_html(good, bad, total, golden), unsafe_allow_html=True)

    def _on_refresh() -> None:
        _safe_cache_clear()
        _enqueue_toast("Feedback refreshed.", icon="↻")

    st.button("↻ Refresh", use_container_width=True, on_click=_on_refresh)

    st.divider()
    _render_system_settings()

    st.divider()
    with st.expander(" Conversation exports", expanded=False):
        if st.button("🧹 Clear chat", use_container_width=True):
            st.session_state.chat_backup = deepcopy(st.session_state.chat)
            st.session_state.chat = []
            st.session_state.feedback_ack = {}
            _enqueue_toast("Chat cleared. You can restore it from this panel.", icon="🧹")

        if st.session_state.get("chat_backup"):
            if st.button("↩ Restore last cleared chat", use_container_width=True):
                st.session_state.chat = deepcopy(st.session_state.chat_backup)
                st.session_state.chat_backup = None
                _enqueue_toast("Chat restored.", icon="✅")

        chat_json = json.dumps(st.session_state.get("chat", []), indent=2, ensure_ascii=False, default=str)
        st.download_button(
            "⬇️ Download current chat (JSON)",
            data=chat_json,
            file_name="cgi_aio_chat_transcript.json",
            mime="application/json",
            use_container_width=True,
        )

        if st.session_state.get("chat_backup"):
            backup_json = json.dumps(st.session_state.chat_backup, indent=2, ensure_ascii=False, default=str)
            st.download_button(
                "⬇️ Download last cleared (JSON)",
                data=backup_json,
                file_name="cgi_aio_chat_last_cleared.json",
                mime="application/json",
                use_container_width=True,
            )

    st.divider()
    _render_doc_upload_panel()

    st.divider()
    _render_quick_prompts(max_items=5)


# -----------------------------
# Assistant message rendering
# -----------------------------
def _render_feedback_button_styles(mid: str) -> None:
    safe_mid = mid.replace("-", "_")
    st.markdown(
        f"""
        <style>
        .st-key-fb_good_wrap_{safe_mid} div[data-testid="stButton"] > button {{
            background: linear-gradient(180deg, #edfdf2 0%, #dcfce7 100%) !important;
            border: 1px solid rgba(22, 163, 74, 0.35) !important;
            color: #166534 !important;
            font-weight: 700 !important;
            border-radius: 12px !important;
            min-height: 40px !important;
        }}
        .st-key-fb_good_wrap_{safe_mid} div[data-testid="stButton"] > button:hover {{
            background: linear-gradient(180deg, #e2f9ea 0%, #d3f5df 100%) !important;
        }}
        .st-key-fb_bad_wrap_{safe_mid} div[data-testid="stButton"] > button {{
            background: linear-gradient(180deg, #fff1f2 0%, #fee2e2 100%) !important;
            border: 1px solid rgba(220, 38, 38, 0.30) !important;
            color: #b91c1c !important;
            font-weight: 700 !important;
            border-radius: 12px !important;
            min-height: 40px !important;
        }}
        .st-key-fb_bad_wrap_{safe_mid} div[data-testid="stButton"] > button:hover {{
            background: linear-gradient(180deg, #ffe5e7 0%, #fecfd4 100%) !important;
        }}
        .st-key-fb_inline_form_{safe_mid} {{
            border: 1px solid rgba(148, 163, 184, 0.35);
            border-left: 4px solid #E31837;
            border-radius: 12px;
            background: rgba(255,255,255,0.94);
            padding: 0.75rem 0.85rem 0.2rem 0.85rem;
            margin-top: 0.6rem;
            max-width: min(860px, calc(100% - 1rem));
            margin-left: auto;
            margin-right: auto;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

def _render_assistant(msg: dict, show_tech: bool) -> None:
    out = msg.get("out") or {}
    mode = out.get("mode")
    answer = msg.get("content") or ""

    st.markdown(answer if answer else "—")

    if out.get("sources"):
        badges = " ".join(
            f"<span>{s}</span>" for s in (out.get("sources") or [])[:4]
        )
        st.markdown(f"<div class='cgi-source-badges'>{badges}</div>", unsafe_allow_html=True)

    rows = out.get("rows")
    if rows:
        st.markdown("**Result**")
        with st.expander("Open result table", expanded=True):
            try:
                import pandas as pd  # type: ignore
                import datetime
                from decimal import Decimal

                df = pd.DataFrame(rows)
                cols = out.get("columns") or []
                if cols:
                    ordered = [c for c in cols if c in df.columns]
                    rest = [c for c in df.columns if c not in ordered]
                    df = df[ordered + rest]

                def _coerce(v):
                    if v is None:
                        return ""
                    if isinstance(v, (int, float, bool, str)):
                        return v
                    if isinstance(v, (datetime.datetime, datetime.date)):
                        return v.isoformat()
                    if isinstance(v, Decimal):
                        return float(v)
                    return str(v)

                df = df.apply(lambda col: col.map(_coerce))
                df = df.reset_index(drop=True)
                st.table(df)
            except Exception:
                st.code(json.dumps(rows, indent=2, default=str), language="json")

    if show_tech:
        with st.expander("Technical details", expanded=False):
            tech = out.get("debug") or {}

            router = tech.get("router") or tech.get("router_impl")
            if router:
                st.markdown(f"**Router:** `{router}`")

            if mode:
                st.markdown(f"**Mode:** `{mode}`")

            if mode in {"sql", "hybrid"} and out.get("sql"):
                st.code(out.get("sql"), language="sql")

            if out.get("sources"):
                st.markdown("**Sources:**")
                for s in out["sources"]:
                    st.write(f"- {s}")

            st.json(tech)

        st.markdown("---")

        mid = msg.get("id")
        if not mid:
            mid = uuid.uuid4().hex
            msg["id"] = mid
        q = msg.get("question") or ""
        sql = out.get("sql")
        model = (out.get("debug") or {}).get("model") or "demo"
        safe_mid = mid.replace("-", "_")

        _render_feedback_button_styles(safe_mid)

        ack = st.session_state.feedback_ack.get(mid)
        if ack:
            st.success(ack, icon="✅")

        st.markdown("**Was this helpful?**")
        c1, c2 = st.columns([1, 1], gap="small")

        def _on_helpful_click(_mid: str, _q: str, _mode: str, _model: str, _sql: str | None, _answer: str) -> None:
            if save_feedback and _q:
                try:
                    save_feedback(
                        question=_q,
                        mode=_mode or "unknown",
                        rating=1,
                        model=_model,
                        sql=_sql,
                        answer=_answer,
                    )
                except Exception as e:
                    st.session_state["_feedback_error"] = f"Feedback save failed: {e}"

            _safe_cache_clear()
            st.session_state.feedback_ack[_mid] = "Thanks for your feedback. Saved as helpful."
            _enqueue_toast("Thanks for your feedback. Saved as helpful.", icon="✅")

        def _toggle_bad_form(_mid: str) -> None:
            key = f"fb_open_{_mid}"
            st.session_state[key] = not bool(st.session_state.get(key, False))

        with c1:
            with st.container(key=f"fb_good_wrap_{safe_mid}"):
                st.button(
                    "👍 Helpful",
                    key=f"good_{mid}",
                    use_container_width=True,
                    on_click=_on_helpful_click,
                    args=(mid, q, mode or "unknown", model, sql, answer),
                )

        with c2:
            with st.container(key=f"fb_bad_wrap_{safe_mid}"):
                st.button(
                    "👎 Not helpful",
                    key=f"bad_toggle_{mid}",
                    use_container_width=True,
                    on_click=_toggle_bad_form,
                    args=(mid,),
                )

        if st.session_state.get(f"fb_open_{mid}", False):
            with st.container(key=f"fb_inline_form_{safe_mid}"):
                st.caption("Tell us what went wrong and optionally provide a correction.")
                with st.form(key=f"fb_form_{mid}", clear_on_submit=True):
                    what = st.selectbox(
                        "Issue type",
                        ["Missing data", "Wrong answer", "Wrong SQL", "Other"],
                        index=0,
                        key=f"fb_issue_{mid}",
                    )
                    comment = st.text_area("Comment", key=f"fb_comment_{mid}")
                    corrected_sql = st.text_area("Correct SQL (optional)", key=f"fb_sql_{mid}")
                    corrected_answer = st.text_area("Correct answer (optional)", key=f"fb_answer_{mid}")

                    submit_cols = st.columns([1, 1], gap="small")
                    with submit_cols[0]:
                        submitted = st.form_submit_button("Submit feedback", use_container_width=True)
                    with submit_cols[1]:
                        close_now = st.form_submit_button("Close", use_container_width=True)

                    if close_now:
                        st.session_state[f"fb_open_{mid}"] = False
                        st.rerun()

                    if submitted:
                        try:
                            result = {}
                            if save_feedback and q:
                                result = save_feedback(
                                    question=q,
                                    mode=mode or "unknown",
                                    rating=0,
                                    model=model,
                                    sql=sql,
                                    answer=answer,
                                    corrected_sql=(corrected_sql or None),
                                    corrected_answer=(corrected_answer or None),
                                    what_went_wrong=what,
                                    comment=comment,
                                ) or {}
                                _safe_cache_clear()

                            if (corrected_sql or corrected_answer):
                                _apply_correction_preview(msg, corrected_sql, corrected_answer)

                            promoted = bool((result or {}).get("golden_id")) and bool((corrected_sql or corrected_answer))
                            if promoted:
                                ack_msg = "Feedback saved and promoted. Preview updated below."
                                toast_msg = "Promoted correction saved. Preview updated."
                            elif (corrected_sql or corrected_answer):
                                ack_msg = "Feedback saved. Preview updated below."
                                toast_msg = "Feedback saved. Preview updated."
                            else:
                                ack_msg = "Thanks for your feedback. Saved as not helpful."
                                toast_msg = "Thanks for your feedback. Saved as not helpful."

                            st.session_state.feedback_ack[mid] = ack_msg
                            st.session_state[f"fb_open_{mid}"] = False
                            _enqueue_toast(toast_msg, icon="✅")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Feedback save failed: {e}")


# -----------------------------
# App start
# -----------------------------
_inject_css()

if "chat" not in st.session_state:
    st.session_state.chat = []

if "chat_backup" not in st.session_state:
    st.session_state.chat_backup = None

if "pending_question" not in st.session_state:
    st.session_state.pending_question = None

if "feedback_ack" not in st.session_state:
    st.session_state.feedback_ack = {}

if "show_tech" not in st.session_state:
    st.session_state.show_tech = False

if "use_legacy_router" not in st.session_state:
    st.session_state.use_legacy_router = False

if "enable_langsmith" not in st.session_state:
    st.session_state.enable_langsmith = _env_flag("ENABLE_LANGSMITH_DEFAULT", "0")

_flush_toast()

show_tech = bool(st.session_state.get("show_tech", False))

with st.container(key="cgi_shell"):
    left, main = st.columns([1, 3.4], gap="small")

    with left:
        with st.container(key="cgi_left_sidebar"):
            _render_feedback_panel()

    with main:
        with st.container(key="cgi_main_panel"):
            st.markdown(
                """
                <div class="cgi-center">
                  <h2 style="margin-bottom:0.2rem;">Welcome to CGI AIO Assistant</h2>
                  <div class="muted">Ask questions about policies (RAG), data (SQL), and combined hybrid prompts.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            st.markdown(
                "<hr style='border:none;height:3px;background:#E31837;margin:0.55rem 0 0.9rem 0;' />",
                unsafe_allow_html=True,
            )

            show_tech = bool(st.session_state.get("show_tech", False))

            for msg in st.session_state.chat:
                avatar = USER_AVATAR if msg["role"] == "user" else BOT_AVATAR
                with st.chat_message(msg["role"], avatar=avatar):
                    if msg["role"] == "assistant":
                        _render_assistant(msg, show_tech=show_tech)
                    else:
                        st.markdown(msg.get("content") or "")

            if len(st.session_state.chat) == 0:
                st.markdown("<div style='height: 38vh;'></div>", unsafe_allow_html=True)


            pending = st.session_state.pending_question
            if pending:
                st.session_state.pending_question = None
                question = pending
            else:
                question = None

            with st.container(key="cgi_chat_dock"):
                with st.form("chat_form", clear_on_submit=True):
                    c1, c2 = st.columns([0.87, 0.13], vertical_alignment="center")
                    with c1:
                        user_text = st.text_area(
                            "Message",
                            placeholder="Type your message...",
                            label_visibility="collapsed",
                            key="chat_text_input",
                            height=74,
                        )
                    with c2:
                        submitted = st.form_submit_button("Submit", use_container_width=True)

                if submitted and user_text.strip():
                    st.session_state.pending_question = user_text.strip()
                    st.rerun()

            if question:
                user_msg = {"id": uuid.uuid4().hex, "role": "user", "content": question}
                st.session_state.chat.append(user_msg)

                with st.chat_message("user", avatar=USER_AVATAR):
                    st.markdown(question)

                with st.chat_message("assistant", avatar=BOT_AVATAR):
                    with st.spinner("Consulting internal knowledge base..."):
                        try:
                            out = _call_answer_question(question)
                        except Exception as e:
                            out = {
                                "mode": "error",
                                "answer": "Something went wrong while answering. Try again or check logs.",
                                "debug": {"exception": str(e)},
                            }

                    answer = out.get("answer") or ""
                    a_msg = {
                        "id": uuid.uuid4().hex,
                        "role": "assistant",
                        "content": answer,
                        "out": out,
                        "question": question,
                    }
                    st.session_state.chat.append(a_msg)
                    _render_assistant(a_msg, show_tech=show_tech)
st.markdown("<div class='cgi-footer-note'>© 2026 CGI Inc.</div>", unsafe_allow_html=True)