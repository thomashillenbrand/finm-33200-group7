"""
src/profiles/app.py
Streamlit dashboard for Management Truthfulness Profiles.

Run with:
    streamlit run src/profiles/app.py
"""
from __future__ import annotations

import glob
import json
import math
import os
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ── page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="Management Truthfulness Profiles | FINM 33200",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── UChicago colour palette ───────────────────────────────────────────────────
MAROON   = "#800000"
D_MAROON = "#350E20"
BRICK    = "#8F3931"
ORANGE   = "#C16622"
GOLD     = "#8B7536"
LAKE     = "#155F83"
FOREST   = "#58593F"
MED_GRAY = "#767676"

VERDICT_COLORS = {
    "verified":           "#2E7D32",
    "partially_verified": ORANGE,
    "not_yet_resolvable": MED_GRAY,
    "contradicted":       MAROON,
}
VERDICT_NICE = {
    "verified":           "Verified",
    "partially_verified": "Partially Verified",
    "not_yet_resolvable": "Not Yet Resolvable",
    "contradicted":       "Contradicted",
}
VERDICT_ORDER = ["verified", "partially_verified", "not_yet_resolvable", "contradicted"]

TICKER_META = {
    "AMZN": {"name": "Amazon",    "color": MAROON, "sector": "Technology / Consumer"},
    "TSLA": {"name": "Tesla",     "color": ORANGE, "sector": "Automotive / EV"},
    "KO":   {"name": "Coca-Cola", "color": LAKE,   "sector": "Consumer Staples"},
    "LLY":  {"name": "Eli Lilly", "color": GOLD,   "sector": "Healthcare / Pharma"},
}
TICKERS = ["AMZN", "TSLA", "KO", "LLY"]

# ── custom CSS ────────────────────────────────────────────────────────────────
st.markdown(f"""
<style>
/* ── global ── */
[data-testid="stAppViewContainer"] {{ background: #fff; }}
[data-testid="stSidebar"] {{ background: {D_MAROON} !important; }}
[data-testid="stSidebar"] * {{ color: rgba(255,255,255,0.85) !important; }}
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stTextInput label {{ color: rgba(255,255,255,0.65) !important; font-size: 0.78rem !important; }}
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {{ color: #fff !important; }}
[data-testid="stSidebar"] hr {{ border-color: rgba(255,255,255,0.15) !important; }}

/* ── hero ── */
.hero-wrap {{
    background: linear-gradient(135deg, {D_MAROON} 0%, {MAROON} 55%, {BRICK} 100%);
    border-radius: 12px; color: #fff;
    padding: 36px 40px 32px; margin-bottom: 28px;
}}
.hero-badge {{
    display: inline-block; background: rgba(255,255,255,0.15);
    border: 1px solid rgba(255,255,255,0.28); border-radius: 20px;
    padding: 3px 14px; font-size: 0.75rem; font-weight: 600;
    letter-spacing: 0.07em; text-transform: uppercase; margin-bottom: 14px;
}}
.hero-title {{
    font-family: Georgia, serif; font-size: 2.3rem; font-weight: 700;
    line-height: 1.2; margin-bottom: 8px;
}}
.hero-sub {{
    font-size: 0.97rem; opacity: 0.78; max-width: 600px; margin-bottom: 22px;
}}
.hero-meta {{ display: flex; flex-wrap: wrap; gap: 28px; align-items: flex-start; }}
.hero-meta-group {{ display: flex; flex-direction: column; gap: 2px; }}
.hero-meta-label {{
    font-size: 0.68rem; text-transform: uppercase;
    letter-spacing: 0.1em; opacity: 0.55;
}}
.hero-meta-value {{ font-size: 0.88rem; font-weight: 600; }}
.team-pills {{ display: flex; flex-wrap: wrap; gap: 7px; margin-top: 4px; }}
.team-pill {{
    background: rgba(255,255,255,0.14); border: 1px solid rgba(255,255,255,0.22);
    border-radius: 18px; padding: 3px 11px; font-size: 0.8rem;
}}

/* ── section headings ── */
.section-heading {{
    font-family: Georgia, serif; font-size: 1.4rem; font-weight: 700;
    color: {MAROON}; border-left: 4px solid {MAROON};
    padding-left: 14px; margin: 8px 0 4px;
}}
.section-sub {{
    font-size: 0.85rem; color: #666; padding-left: 18px; margin-bottom: 16px;
}}

/* ── metric cards ── */
[data-testid="metric-container"] {{
    background: #fff; border: 1px solid #ececec;
    border-radius: 10px; padding: 16px 20px !important;
    box-shadow: 0 1px 8px rgba(0,0,0,0.06);
}}
[data-testid="stMetricLabel"] {{ font-size: 0.78rem !important; color: #888 !important;
    text-transform: uppercase; letter-spacing: 0.06em; }}
[data-testid="stMetricValue"] {{ font-size: 1.9rem !important; color: {MAROON} !important;
    font-family: Georgia, serif; }}

/* ── company cards ── */
.co-card {{
    background: #fff; border-radius: 10px; border-top: 5px solid var(--accent);
    box-shadow: 0 2px 14px rgba(0,0,0,0.07); padding: 18px 20px 14px;
    margin-bottom: 8px;
}}
.co-name {{ font-family: Georgia, serif; font-size: 1.15rem; font-weight: 700; }}
.co-ticker {{ font-size: 0.72rem; color: #888; text-transform: uppercase; letter-spacing: 0.1em; }}
.co-sector {{ font-size: 0.76rem; color: #777; margin-top: 2px; margin-bottom: 10px; }}
.co-score {{ font-family: Georgia, serif; font-size: 2rem; font-weight: 700; }}
.co-n {{ font-size: 0.75rem; color: #aaa; }}

/* ── verdict badges ── */
.vbadge {{
    display: inline-block; border-radius: 12px; padding: 2px 9px;
    font-size: 0.73rem; font-weight: 600; white-space: nowrap;
}}
.vbadge-verified     {{ background:#E8F5E9; color:#2E7D32; }}
.vbadge-partial      {{ background:#FFF3E0; color:{ORANGE}; }}
.vbadge-unresolvable {{ background:#F5F5F5; color:#555; }}
.vbadge-contradicted {{ background:#FCE4EC; color:{MAROON}; }}

/* ── tab styling ── */
[data-baseweb="tab-list"] {{ border-bottom: 2px solid {MAROON}40; }}
[data-baseweb="tab"] {{ font-size: 0.9rem !important; font-weight: 500; }}
[aria-selected="true"] {{ color: {MAROON} !important; border-bottom: 2px solid {MAROON} !important; }}

/* ── sidebar nav label ── */
.sidebar-label {{
    font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.1em;
    opacity: 0.5; margin-bottom: 6px;
}}
</style>
""", unsafe_allow_html=True)


# ── data loading ──────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parents[2]   # repo root

@st.cache_data
def load_verdicts() -> pd.DataFrame:
    p = BASE / "data/verdicts/combined_55_final.csv"
    df = pd.read_csv(p)
    df["year"] = pd.to_datetime(df["call_date"]).dt.year
    return df

@st.cache_data
def load_claims() -> pd.DataFrame:
    return pd.read_csv(BASE / "data/claims/55_full_run.csv")

@st.cache_data
def load_eval_runs() -> list[dict]:
    runs = []
    runs_dir = BASE / "data/eval/runs"
    for fp in sorted(glob.glob(str(runs_dir / "*/summary.json"))):
        try:
            with open(fp) as f:
                d = json.load(f)
            label = os.path.basename(os.path.dirname(fp))
            runs.append({
                "label":           d.get("label", label),
                "recall":          d.get("mean_recall_at_k"),
                "precision":       d.get("mean_precision"),
                "verdict_accuracy": d.get("verdict_accuracy"),
                "n":               d.get("n_claims"),
            })
        except Exception:
            pass
    for fp in sorted(glob.glob(str(runs_dir / "*_summary.json"))):
        try:
            with open(fp) as f:
                d = json.load(f)
            runs.append({
                "label":           d.get("label", os.path.basename(fp)),
                "recall":          d.get("mean_recall_at_k"),
                "precision":       d.get("mean_precision"),
                "verdict_accuracy": d.get("verdict_accuracy"),
                "n":               d.get("n_claims"),
            })
        except Exception:
            pass
    return runs

def truth_score(df: pd.DataFrame) -> float | None:
    score_map = {"verified": 1.0, "partially_verified": 0.5, "contradicted": 0.0}
    scores = df["verdict"].map(score_map).dropna()
    return round(float(scores.mean() * 100), 1) if len(scores) else None

def ci_95(df: pd.DataFrame) -> float:
    score_map = {"verified": 1.0, "partially_verified": 0.5, "contradicted": 0.0}
    scores = df["verdict"].map(score_map).dropna()
    if len(scores) < 2:
        return 0.0
    return round(1.96 * scores.std() / math.sqrt(len(scores)) * 100, 1)

LAYOUT = dict(
    paper_bgcolor="#fff", plot_bgcolor="#fff",
    font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
              size=12, color="#333"),
    margin=dict(l=16, r=16, t=24, b=16),
)


# ── load data ─────────────────────────────────────────────────────────────────
verdicts = load_verdicts()
claims   = load_claims()
eval_runs = load_eval_runs()

merged = verdicts.merge(
    claims[["claim_id", "company", "summary", "speaker_name", "horizon_raw"]],
    on="claim_id", how="left"
)

# ── sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"""
    <div style="padding:8px 0 16px;">
      <div style="font-size:1.1rem;font-weight:700;letter-spacing:.02em;">FINM 33200</div>
      <div style="font-size:.75rem;opacity:.55;margin-top:2px;">Group 7 — Spring 2026</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown('<div class="sidebar-label">Team</div>', unsafe_allow_html=True)
    for name in ["Brendan Kehoe", "Seback Oh", "Tejaswini Shashidhar", "Thomas Hillenbrand"]:
        st.markdown(f"<div style='font-size:.85rem;padding:2px 0;'>{name}</div>",
                    unsafe_allow_html=True)

    st.markdown("---")
    st.markdown('<div class="sidebar-label">Claims Filter</div>', unsafe_allow_html=True)
    sb_company = st.selectbox("Company", ["All"] + ["Amazon","Tesla","Coca-Cola","Eli Lilly"])
    sb_verdict = st.selectbox("Verdict", ["All"] + list(VERDICT_NICE.values()))
    sb_type    = st.selectbox("Claim Type", ["All", "Numerical Guidance", "Capital Allocation"])
    sb_year    = st.selectbox("Year", ["All"] + [str(y) for y in range(2020, 2026)])
    sb_search  = st.text_input("Search summaries", placeholder="keyword...")

    st.markdown("---")
    st.markdown('<div class="sidebar-label">Data</div>', unsafe_allow_html=True)
    st.markdown(
        f"<div style='font-size:.78rem;opacity:.6;line-height:1.6;'>"
        f"451 graded claims<br>4 companies<br>2020–2025<br>"
        f"WRDS transcripts<br>SEC EDGAR<br>Compustat</div>",
        unsafe_allow_html=True,
    )

# ── hero ──────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="hero-wrap">
  <div class="hero-badge">FINM 33200 &mdash; Generative and Agentic AI for Finance &mdash; Spring 2026</div>
  <div class="hero-title">Management Truthfulness Profiles</div>
  <div class="hero-sub">
    Do executives keep their word? An agentic NLP pipeline that extracts forward-looking
    claims from earnings calls and verifies them against SEC filings.
  </div>
  <div class="hero-meta">
    <div class="hero-meta-group">
      <span class="hero-meta-label">Project</span>
      <span class="hero-meta-value">Forward-Claim Verification via Agentic SEC Retrieval</span>
    </div>
    <div class="hero-meta-group">
      <span class="hero-meta-label">Team</span>
      <div class="team-pills">
        <span class="team-pill">Brendan Kehoe</span>
        <span class="team-pill">Seback Oh</span>
        <span class="team-pill">Tejaswini Shashidhar</span>
        <span class="team-pill">Thomas Hillenbrand</span>
      </div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ── KPI metrics ───────────────────────────────────────────────────────────────
overall_ts  = truth_score(verdicts)
best_ticker = max(TICKERS, key=lambda t: truth_score(verdicts[verdicts["ticker"]==t]) or 0)
best_co     = TICKER_META[best_ticker]
best_ts     = truth_score(verdicts[verdicts["ticker"]==best_ticker])
best_run    = max(eval_runs, key=lambda r: r.get("verdict_accuracy") or 0) if eval_runs else {}

m1, m2, m3, m4 = st.columns(4)
m1.metric("Claims Graded", f"{len(verdicts):,}", help="Total claims with a verdict (2020–2025, 4 companies)")
m2.metric("Overall Truth Score", f"{overall_ts}%", help="Verified + 0.5 × Partially Verified, over resolved claims")
m3.metric(f"Top Performer", best_co["name"], delta=f"{best_ts}% truth score", delta_color="off")
m4.metric("Agent Verdict Accuracy", f"{round((best_run.get('verdict_accuracy') or 0)*100)}%",
          help="Best eval run (discipline pass) vs 28-claim gold set")

st.markdown("<br>", unsafe_allow_html=True)

# ── tabs ──────────────────────────────────────────────────────────────────────
tab_overview, tab_companies, tab_trends, tab_eval, tab_claims = st.tabs([
    "Overview", "Company Profiles", "Trends & Heatmap", "Agent Evaluation", "Browse Claims"
])

# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ════════════════════════════════════════════════════════════════════════════════
with tab_overview:
    st.markdown('<div class="section-heading">Overall Truthfulness</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Verdict distribution and ranked truth scores across all 451 graded claims.</div>', unsafe_allow_html=True)

    col_left, col_right = st.columns(2)

    # ── donut
    with col_left:
        counts = [verdicts["verdict"].value_counts().get(k, 0) for k in VERDICT_ORDER]
        colors = [VERDICT_COLORS[k] for k in VERDICT_ORDER]
        labels = [VERDICT_NICE[k] for k in VERDICT_ORDER]

        fig = go.Figure(go.Pie(
            values=counts, labels=labels,
            hole=0.6,
            marker=dict(colors=colors, line=dict(color="#fff", width=2)),
            textinfo="label+percent",
            textfont=dict(size=12),
            hovertemplate="<b>%{label}</b><br>%{value} claims (%{percent})<extra></extra>",
            sort=False,
        ))
        fig.update_layout(
            **LAYOUT,
            title=dict(text="Verdict Distribution — All Claims", font=dict(size=13), x=0, xref="paper"),
            showlegend=False,
            annotations=[dict(
                text=f"<b>{len(verdicts)}</b><br>claims",
                x=0.5, y=0.5, font=dict(size=17, color="#1a1a1a"),
                showarrow=False,
            )],
            height=360,
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── company bar
    with col_right:
        cos = sorted(
            [{"ticker": t, "name": TICKER_META[t]["name"], "color": TICKER_META[t]["color"],
              "score": truth_score(verdicts[verdicts["ticker"]==t]),
              "ci": ci_95(verdicts[verdicts["ticker"]==t])}
             for t in TICKERS],
            key=lambda x: x["score"] or 0
        )

        fig2 = go.Figure(go.Bar(
            orientation="h",
            x=[c["score"] for c in cos],
            y=[c["name"] for c in cos],
            error_x=dict(type="data", array=[c["ci"] for c in cos],
                         arrayminus=[c["ci"] for c in cos],
                         color="#bbb", thickness=1.5, width=6),
            marker=dict(color=[c["color"] for c in cos], opacity=0.88),
            text=[f"{c['score']}%" for c in cos],
            textposition="outside",
            textfont=dict(size=13),
            hovertemplate="<b>%{y}</b><br>Truth Score: %{x}%<extra></extra>",
        ))
        fig2.update_layout(
            **LAYOUT,
            title=dict(text="Truth Score by Company (95% CI)", font=dict(size=13), x=0, xref="paper"),
            xaxis=dict(range=[0, 108], ticksuffix="%", gridcolor="#f0f0f0"),
            yaxis=dict(automargin=True),
            bargap=0.4, height=360,
        )
        st.plotly_chart(fig2, use_container_width=True)

    # ── stacked verdict bars per company
    st.markdown('<div class="section-heading" style="margin-top:12px;">Verdict Breakdown per Company</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Absolute verdict counts, stacked by category.</div>', unsafe_allow_html=True)

    traces = []
    for vk in VERDICT_ORDER:
        traces.append(go.Bar(
            name=VERDICT_NICE[vk],
            x=[TICKER_META[t]["name"] for t in TICKERS],
            y=[int(verdicts[(verdicts["ticker"]==t)]["verdict"].value_counts().get(vk, 0)) for t in TICKERS],
            marker=dict(color=VERDICT_COLORS[vk]),
            hovertemplate="<b>%{x}</b><br>" + VERDICT_NICE[vk] + ": %{y}<extra></extra>",
        ))
    fig3 = go.Figure(traces)
    fig3.update_layout(
        **LAYOUT,
        barmode="stack",
        xaxis=dict(automargin=True),
        yaxis=dict(title="Number of Claims", gridcolor="#f0f0f0"),
        legend=dict(orientation="h", y=-0.18, x=0.5, xanchor="center"),
        margin=dict(l=40, r=16, t=24, b=70),
        height=340,
    )
    st.plotly_chart(fig3, use_container_width=True)


# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 — COMPANY PROFILES
# ════════════════════════════════════════════════════════════════════════════════
with tab_companies:
    st.markdown('<div class="section-heading">Company Profiles</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Detailed verdict breakdown and truth score per company. Hover charts for exact counts.</div>', unsafe_allow_html=True)

    for row_tickers in [["AMZN", "TSLA"], ["KO", "LLY"]]:
        cols = st.columns(2)
        for col, t in zip(cols, row_tickers):
            with col:
                meta = TICKER_META[t]
                sub  = verdicts[verdicts["ticker"] == t]
                ts   = truth_score(sub)
                ci   = ci_95(sub)
                ct   = sub["claim_type"].value_counts().to_dict()

                # header card
                st.markdown(f"""
                <div class="co-card" style="--accent:{meta['color']}">
                  <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                    <div>
                      <div class="co-name">{meta['name']}</div>
                      <div class="co-ticker">{t}</div>
                      <div class="co-sector">{meta['sector']}</div>
                    </div>
                    <div style="text-align:right;">
                      <div class="co-score" style="color:{meta['color']}">{ts}%</div>
                      <div class="co-n">truth score &plusmn; {ci}%<br>{len(sub)} claims</div>
                    </div>
                  </div>
                </div>
                """, unsafe_allow_html=True)

                # donut
                vcounts = [int(sub["verdict"].value_counts().get(k, 0)) for k in VERDICT_ORDER]
                fig = go.Figure(go.Pie(
                    values=vcounts,
                    labels=[VERDICT_NICE[k] for k in VERDICT_ORDER],
                    hole=0.58,
                    marker=dict(
                        colors=[VERDICT_COLORS[k] for k in VERDICT_ORDER],
                        line=dict(color="#fff", width=1.5)
                    ),
                    textinfo="percent",
                    textfont=dict(size=11),
                    hovertemplate="<b>%{label}</b><br>%{value} claims<extra></extra>",
                    sort=False,
                ))
                fig.update_layout(
                    **LAYOUT,
                    showlegend=True,
                    legend=dict(orientation="h", y=-0.12, x=0.5, xanchor="center",
                                font=dict(size=10)),
                    annotations=[dict(
                        text=f"<b>{ts}%</b>",
                        x=0.5, y=0.5, font=dict(size=18, color=meta["color"]),
                        showarrow=False,
                    )],
                    height=280,
                    margin=dict(l=10, r=10, t=10, b=50),
                )
                st.plotly_chart(fig, use_container_width=True)

                # claim type pills
                ct_html = ""
                for ctype, n in ct.items():
                    lbl = "Numerical" if ctype == "numerical_guidance" else "Cap. Alloc."
                    ct_html += f'<span style="background:#f5f5f5;color:#555;border-radius:12px;padding:2px 9px;font-size:.75rem;font-weight:600;margin-right:6px;">{n} {lbl}</span>'
                st.markdown(ct_html, unsafe_allow_html=True)
                st.markdown("<br>", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# TAB 3 — TRENDS & HEATMAP
# ════════════════════════════════════════════════════════════════════════════════
with tab_trends:
    st.markdown('<div class="section-heading">Truthfulness Over Time</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Year-by-year truth score per company (2020–2025). Missing markers = no resolvable claims that year.</div>', unsafe_allow_html=True)

    years = list(range(2020, 2026))
    ticker_colors = {t: TICKER_META[t]["color"] for t in TICKERS}

    trend_traces = []
    for t in TICKERS:
        sub = verdicts[verdicts["ticker"] == t]
        xs, ys = [], []
        for y in years:
            sy = sub[sub["year"] == y]
            ts_y = truth_score(sy)
            if ts_y is not None:
                xs.append(y)
                ys.append(ts_y)
        trend_traces.append(go.Scatter(
            x=xs, y=ys, mode="lines+markers",
            name=TICKER_META[t]["name"],
            line=dict(color=ticker_colors[t], width=2.5),
            marker=dict(size=9, color=ticker_colors[t],
                        line=dict(color="#fff", width=1.5)),
            hovertemplate=f"<b>{TICKER_META[t]['name']}</b><br>%{{x}}: %{{y:.1f}}%<extra></extra>",
        ))

    fig_line = go.Figure(trend_traces)
    fig_line.update_layout(
        **LAYOUT,
        xaxis=dict(title="Year", dtick=1, tickformat="d", gridcolor="#f0f0f0"),
        yaxis=dict(title="Truth Score (%)", range=[0, 110], ticksuffix="%", gridcolor="#f0f0f0"),
        legend=dict(orientation="h", y=-0.15, x=0.5, xanchor="center"),
        hovermode="x unified",
        height=380,
        margin=dict(l=50, r=20, t=24, b=70),
    )
    st.plotly_chart(fig_line, use_container_width=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="section-heading">Company x Year Heatmap</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Grey cells indicate no resolvable claims for that year.</div>', unsafe_allow_html=True)

    co_names = [TICKER_META[t]["name"] for t in TICKERS]
    z, text = [], []
    for t in TICKERS:
        sub = verdicts[verdicts["ticker"] == t]
        row_z, row_t = [], []
        for y in years:
            sy = sub[sub["year"] == y]
            ts_y = truth_score(sy)
            row_z.append(ts_y)
            row_t.append(f"{ts_y:.1f}%" if ts_y is not None else "N/A")
        z.append(row_z)
        text.append(row_t)

    fig_heat = go.Figure(go.Heatmap(
        z=z, x=years, y=co_names, text=text,
        texttemplate="%{text}",
        textfont=dict(size=12, color="#fff"),
        colorscale=[[0, MAROON], [0.35, "#D4875A"], [0.5, "#F5E6B2"], [0.65, "#A5C882"], [1, "#2E7D32"]],
        zmin=0, zmax=100,
        hoverongaps=False,
        hovertemplate="<b>%{y} %{x}</b><br>Truth Score: %{text}<extra></extra>",
        colorbar=dict(title="Score", ticksuffix="%", len=0.85),
    ))
    fig_heat.update_layout(
        **LAYOUT,
        xaxis=dict(dtick=1, tickformat="d"),
        yaxis=dict(automargin=True),
        height=300,
        margin=dict(l=80, r=80, t=24, b=40),
    )
    st.plotly_chart(fig_heat, use_container_width=True)

    # ── claim type section
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="section-heading">Claim Type Breakdown</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Numerical guidance vs. capital allocation — volume and verdict mix.</div>', unsafe_allow_html=True)

    col_ct1, col_ct2 = st.columns(2)

    with col_ct1:
        num_vals = [int(verdicts[(verdicts["ticker"]==t) & (verdicts["claim_type"]=="numerical_guidance")].shape[0]) for t in TICKERS]
        cap_vals = [int(verdicts[(verdicts["ticker"]==t) & (verdicts["claim_type"]=="capital_allocation")].shape[0]) for t in TICKERS]
        names_   = [TICKER_META[t]["name"] for t in TICKERS]

        fig_ct = go.Figure([
            go.Bar(name="Numerical Guidance", x=names_, y=num_vals,
                   marker=dict(color=LAKE, opacity=0.85),
                   hovertemplate="<b>%{x}</b><br>Numerical: %{y}<extra></extra>"),
            go.Bar(name="Capital Allocation", x=names_, y=cap_vals,
                   marker=dict(color=GOLD, opacity=0.85),
                   hovertemplate="<b>%{x}</b><br>Cap. Alloc.: %{y}<extra></extra>"),
        ])
        fig_ct.update_layout(**LAYOUT, barmode="stack",
                             title=dict(text="Volume by Claim Type", font=dict(size=12), x=0, xref="paper"),
                             yaxis=dict(title="Claims", gridcolor="#f0f0f0"),
                             legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"),
                             height=320, margin=dict(l=40, r=10, t=30, b=70))
        st.plotly_chart(fig_ct, use_container_width=True)

    with col_ct2:
        type_keys = ["numerical_guidance", "capital_allocation"]
        type_nice = ["Numerical Guidance", "Capital Allocation"]
        bytype = {ct: {vk: 0 for vk in VERDICT_ORDER} for ct in type_keys}
        for _, row in verdicts.iterrows():
            ct = row.get("claim_type", "")
            vk = row.get("verdict", "")
            if ct in bytype and vk in bytype[ct]:
                bytype[ct][vk] += 1

        fig_vtm = go.Figure([
            go.Bar(
                name=VERDICT_NICE[vk],
                x=type_nice,
                y=[bytype[ct][vk] for ct in type_keys],
                marker=dict(color=VERDICT_COLORS[vk]),
                hovertemplate="<b>%{x}</b><br>" + VERDICT_NICE[vk] + ": %{y}<extra></extra>",
            ) for vk in VERDICT_ORDER
        ])
        fig_vtm.update_layout(**LAYOUT, barmode="stack",
                              title=dict(text="Verdict Mix by Claim Type", font=dict(size=12), x=0, xref="paper"),
                              yaxis=dict(title="Claims", gridcolor="#f0f0f0"),
                              legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"),
                              height=320, margin=dict(l=40, r=10, t=30, b=70))
        st.plotly_chart(fig_vtm, use_container_width=True)


# ════════════════════════════════════════════════════════════════════════════════
# TAB 4 — AGENT EVALUATION
# ════════════════════════════════════════════════════════════════════════════════
with tab_eval:
    st.markdown('<div class="section-heading">Agent Performance</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Retrieval and verdict accuracy on a 28-claim gold set (LLM-labeled, capital allocation).</div>', unsafe_allow_html=True)

    valid_runs = [r for r in eval_runs if r.get("recall") is not None]
    if valid_runs:
        run_labels = []
        for r in valid_runs:
            lbl = r.get("label", "")
            if "baseline" in lbl.lower():
                run_labels.append("Baseline")
            elif "discipline" in lbl.lower() and "citation" not in lbl.lower():
                run_labels.append("Discipline Pass")
            elif "citation" in lbl.lower():
                run_labels.append("Citation Pass")
            else:
                run_labels.append(lbl[:22])

        metrics = [
            ("recall",           "Recall @ 8",       MAROON),
            ("precision",        "Precision",         ORANGE),
            ("verdict_accuracy", "Verdict Accuracy",  LAKE),
        ]

        fig_eval = go.Figure([
            go.Bar(
                name=nice,
                x=run_labels,
                y=[round((r.get(key) or 0) * 100, 1) for r in valid_runs],
                marker=dict(color=color, opacity=0.88),
                text=[f"{round((r.get(key) or 0)*100, 1)}%" for r in valid_runs],
                textposition="outside",
                hovertemplate=f"<b>%{{x}}</b><br>{nice}: %{{y:.1f}}%<extra></extra>",
            ) for key, nice, color in metrics
        ])
        fig_eval.update_layout(
            **LAYOUT,
            barmode="group",
            xaxis=dict(automargin=True),
            yaxis=dict(title="Score (%)", range=[0, 108], ticksuffix="%", gridcolor="#f0f0f0"),
            legend=dict(orientation="h", y=-0.18, x=0.5, xanchor="center"),
            bargap=0.25, bargroupgap=0.08,
            height=380, margin=dict(l=50, r=20, t=24, b=70),
        )
        st.plotly_chart(fig_eval, use_container_width=True)

        # summary table
        st.markdown("<br>", unsafe_allow_html=True)
        summary_rows = []
        for lbl, r in zip(run_labels, valid_runs):
            summary_rows.append({
                "Run":              lbl,
                "Recall @ 8":      f"{round((r.get('recall') or 0)*100, 1)}%",
                "Precision":       f"{round((r.get('precision') or 0)*100, 1)}%",
                "Verdict Accuracy": f"{round((r.get('verdict_accuracy') or 0)*100, 1)}%",
                "N Claims":        r.get("n", ""),
            })
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No evaluation run summaries found in data/eval/runs/.")

    st.markdown(f"""
    <div style="background:#fff8f0;border:1px solid rgba(193,102,34,.25);border-radius:8px;
                padding:14px 18px;font-size:.85rem;color:#555;margin-top:20px;max-width:700px;">
      <strong>Gold set note:</strong> The 28-claim evaluation set was labeled by GPT-5.5 using
      the project rubric — not hand-labeled. Verdict accuracy measures agreement between the
      graded agent (gpt-5.1) and those gold labels. Recall@8 measures whether the correct SEC
      filing appears in the top-8 retrieved chunks.
    </div>
    """, unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════════════════════════
# TAB 5 — BROWSE CLAIMS
# ════════════════════════════════════════════════════════════════════════════════
with tab_claims:
    st.markdown('<div class="section-heading">Browse Claims</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">All 451 graded claims. Use the sidebar filters or search below.</div>', unsafe_allow_html=True)

    # map sidebar filters
    COMPANY_MAP = {"Amazon": "AMZN", "Tesla": "TSLA", "Coca-Cola": "KO", "Eli Lilly": "LLY"}
    VERDICT_REV = {v: k for k, v in VERDICT_NICE.items()}
    TYPE_MAP    = {"Numerical Guidance": "numerical_guidance", "Capital Allocation": "capital_allocation"}

    tbl = merged.copy()
    if sb_company != "All":
        tbl = tbl[tbl["ticker"] == COMPANY_MAP.get(sb_company, sb_company)]
    if sb_verdict != "All":
        tbl = tbl[tbl["verdict"] == VERDICT_REV.get(sb_verdict, sb_verdict)]
    if sb_type != "All":
        tbl = tbl[tbl["claim_type"] == TYPE_MAP.get(sb_type, sb_type)]
    if sb_year != "All":
        tbl = tbl[tbl["year"] == int(sb_year)]
    if sb_search:
        mask = tbl["summary"].fillna("").str.lower().str.contains(sb_search.lower(), na=False)
        tbl = tbl[mask]

    st.caption(f"Showing {len(tbl):,} of {len(merged):,} claims")

    # build display df
    display = pd.DataFrame({
        "Company":    tbl["ticker"].map(lambda t: TICKER_META.get(t, {}).get("name", t)),
        "Year":       tbl["year"].fillna(0).astype(int),
        "Type":       tbl["claim_type"].map({"numerical_guidance": "Numerical", "capital_allocation": "Cap. Alloc."}).fillna(tbl["claim_type"]),
        "Verdict":    tbl["verdict"].map(VERDICT_NICE).fillna(tbl["verdict"]),
        "Summary":    tbl["summary"].fillna("").str[:200],
        "Horizon":    tbl["horizon_raw"].fillna("").str[:60],
        "Source":     tbl["source"].map({"autochecker": "Compustat", "agent": "SEC Agent"}).fillna(tbl.get("source", "")),
    })

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        height=520,
        column_config={
            "Company":  st.column_config.TextColumn("Company",  width="small"),
            "Year":     st.column_config.NumberColumn("Year",   width="small", format="%d"),
            "Type":     st.column_config.TextColumn("Type",     width="small"),
            "Verdict":  st.column_config.TextColumn("Verdict",  width="medium"),
            "Summary":  st.column_config.TextColumn("Summary",  width="large"),
            "Horizon":  st.column_config.TextColumn("Horizon",  width="medium"),
            "Source":   st.column_config.TextColumn("Source",   width="small"),
        },
    )
