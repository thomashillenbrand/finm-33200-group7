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
iframe { display: block; border: none; }
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
    html = generate_html(data)

    # ── patches for the Streamlit / iframe context ────────────────────────
    # 1. Remove sticky navbar (sticky only works in the element's own scroll
    #    container; inside a tall iframe the outer page scrolls, not the iframe,
    #    so sticky has no effect — use relative instead).
    html = html.replace(
        "position: sticky; top: 0; z-index: 100;",
        "position: relative;",
    )

    # 2. Inject scripts for the Streamlit / iframe context.
    iframe_js = """
<script>
(function () {
    // ── auto-height: tell Streamlit how tall to make the iframe ────────────
    function postHeight() {
        var h = Math.max(
            document.body.scrollHeight,
            document.documentElement.scrollHeight
        );
        window.parent.postMessage(
            { isStreamlitMessage: true, type: "streamlit:setFrameHeight", height: h },
            "*"
        );
    }
    postHeight();
    window.addEventListener("load",   postHeight);
    window.addEventListener("resize", postHeight);
    setTimeout(postHeight,  400);
    setTimeout(postHeight, 1200);
    setTimeout(postHeight, 2500);

    // ── nav-link fix: scroll the OUTER page, not the inner iframe ──────────
    // When a user clicks "#overview" etc. inside an iframe with
    // overflow:hidden, the browser scrolls the iframe's own document —
    // clipping the top of the page and making it look "smaller".
    // Instead, we intercept the click, work out where the target element
    // sits in the outer (Streamlit) page, and scroll that page smoothly.
    if (window.parent === window) return;   // not inside an iframe — skip

    function attachNavFix() {
        var links = document.querySelectorAll('a[href^="#"]');
        links.forEach(function (link) {
            link.addEventListener("click", function (e) {
                var href = link.getAttribute("href");
                if (!href || href.length < 2) return;
                var target = document.getElementById(href.slice(1));
                if (!target) return;

                e.preventDefault();
                e.stopPropagation();

                // Distance from top of the iframe document to the target
                var targetOffsetInIframe =
                    target.getBoundingClientRect().top + window.scrollY;

                // Distance from top of the outer (Streamlit) page to
                // the top edge of this iframe
                var iframeTopInPage = 0;
                try {
                    var rect = window.frameElement.getBoundingClientRect();
                    iframeTopInPage = rect.top + window.parent.scrollY;
                } catch (err) { /* cross-origin guard — shouldn't fire on localhost */ }

                window.parent.scrollTo({
                    top: iframeTopInPage + targetOffsetInIframe,
                    behavior: "smooth"
                });
            });
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", attachNavFix);
    } else {
        attachNavFix();
    }
})();
</script>
"""
    return html.replace("</body>", iframe_js + "\n</body>")


html_content = get_dashboard_html()

# Initial height is a generous fallback; the auto-height script will correct it.
components.html(html_content, height=6000, scrolling=False)
