from pathlib import Path
import base64
import streamlit as st

ASSETS_DIR = Path(__file__).resolve().parent
LOGO_PATH = ASSETS_DIR / "CGI-logo.png"

@st.cache_data(show_spinner=False)
def _b64_png(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")

def apply_branding():
    st.set_page_config(
        page_title="CGI AIO Assistant",
        page_icon=str(LOGO_PATH) if LOGO_PATH.exists() else "🤖",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    logo_b64 = _b64_png(LOGO_PATH) if LOGO_PATH.exists() else ""

    st.markdown(
        f"""
        <style>
          /* Keep content below fixed header */
          .main > div:first-child {{ padding-top: 92px; }}

          /* Make content nicer */
          .block-container {{
            max-width: 1050px;
            padding-top: 1rem;
          }}
          [data-testid="stChatInput"] {{
            border-radius: 14px;
          }}
          [data-testid="stExpander"] {{
            border-radius: 14px;
            border: 1px solid #e5e7eb;
          }}

          /* Fixed top header */
          .cgi-header {{
            position: fixed;
            top: 0; left: 0; right: 0;
            height: 72px;
            background: #ffffff;
            z-index: 9999;
            border-bottom: 1px solid #e5e7eb;
            display: flex;
            align-items: center;
            padding: 0 24px;
            gap: 14px;
          }}
          .cgi-badge {{
            width: 10px; height: 42px;
            background: #E31837;
            border-radius: 8px;
          }}
          .cgi-title {{
            font-size: 18px;
            font-weight: 700;
            color: #111827;
            margin: 0;
            line-height: 1.1;
          }}
          .cgi-subtitle {{
            font-size: 12px;
            color: #6b7280;
            margin: 0;
          }}
          .cgi-spacer {{ flex: 1; }}

          body {{ background: #fafafa; }}

          #MainMenu {{ visibility: hidden; }}
          footer {{ visibility: hidden; }}
        </style>

        <div class="cgi-header">
          <div class="cgi-badge"></div>
          {"<img src='data:image/png;base64," + logo_b64 + "' style='height:42px;' />" if logo_b64 else ""}
          <div>
            <p class="cgi-title">CGI AIO Assistant</p>
            <p class="cgi-subtitle">Internal demo portal © 2026 CGI Inc.</p>
          </div>
          <div class="cgi-spacer"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )