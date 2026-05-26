"""
src/profiles/app.py
Streamlit app — renders the interactive HTML dashboard.

Run with:
    streamlit run src/profiles/app.py
"""
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Management Truthfulness Profiles | FINM 33200",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── strip every visible piece of Streamlit chrome ────────────────────────────
st.markdown("""
<style>
#MainMenu                          { display: none !important; }
header[data-testid="stHeader"]     { display: none !important; }
footer                             { display: none !important; }
[data-testid="stToolbar"]          { display: none !important; }
[data-testid="stDecoration"]       { display: none !important; }
section[data-testid="stSidebar"]   { display: none !important; }
[data-testid="collapsedControl"]   { display: none !important; }
.main .block-container {
    padding: 0 !important;
    max-width: 100% !important;
}
body, .main { background: #fff !important; }
iframe { display: block !important; border: none !important; }
</style>
""", unsafe_allow_html=True)

# ── locate repo root and add src/ to path ────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from profiles.dashboard import build_data, generate_html   # noqa: E402


@st.cache_data(show_spinner="Building dashboard...")
def get_dashboard_html() -> str:
    data = build_data(
        str(ROOT / "data/verdicts/combined_55_final.csv"),
        str(ROOT / "data/claims/55_full_run.csv"),
        str(ROOT / "data/eval/runs"),
    )
    # No patches needed — with scrolling=True the iframe has its own scroll
    # container, so the sticky navbar sticks correctly and anchor links
    # (#overview, #companies, etc.) navigate natively without any JS tricks.
    return generate_html(data)


html_content = get_dashboard_html()

# scrolling=True  → the iframe has its own scrollbar; anchor nav works natively.
# height          → fills a typical laptop viewport; CSS below removes the gap.
components.html(html_content, height=900, scrolling=True)
