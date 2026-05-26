#!/usr/bin/env python3
"""
src/profiles/dashboard.py
Generate a self-contained interactive HTML dashboard for truthfulness profiles.

Usage:
    python -m profiles.dashboard \
        --verdicts data/verdicts/combined_55_final.csv \
        --claims   data/claims/55_full_run.csv \
        --out      data/profiles/dashboard.html
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# UChicago colour palette
# ---------------------------------------------------------------------------
MAROON   = "#800000"
D_MAROON = "#350E20"
BRICK    = "#8F3931"
ORANGE   = "#C16622"
GOLD     = "#8B7536"
LAKE     = "#155F83"
FOREST   = "#58593F"
WARM_GRAY = "#D6D6CE"
MED_GRAY  = "#767676"

VERDICT_COLORS = {
    "verified":           "#2E7D32",
    "partially_verified": ORANGE,
    "not_yet_resolvable": MED_GRAY,
    "contradicted":       MAROON,
}
VERDICT_LABELS = {
    "verified":           "Verified",
    "partially_verified": "Partially Verified",
    "not_yet_resolvable": "Not Yet Resolvable",
    "contradicted":       "Contradicted",
}
VERDICT_ORDER = ["verified", "partially_verified", "not_yet_resolvable", "contradicted"]

TICKER_META = {
    "AMZN": {"name": "Amazon",     "color": MAROON, "sector": "Technology / Consumer"},
    "TSLA": {"name": "Tesla",      "color": ORANGE, "sector": "Automotive / EV"},
    "KO":   {"name": "Coca-Cola",  "color": LAKE,   "sector": "Consumer Staples"},
    "LLY":  {"name": "Eli Lilly",  "color": GOLD,   "sector": "Healthcare / Pharma"},
}
TICKERS = ["AMZN", "TSLA", "KO", "LLY"]

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def truth_score(df: pd.DataFrame) -> float | None:
    score_map = {"verified": 1.0, "partially_verified": 0.5, "contradicted": 0.0}
    scores = df["verdict"].map(score_map).dropna()
    return round(float(scores.mean() * 100), 1) if len(scores) else None


def ci_95(df: pd.DataFrame) -> tuple[float, float]:
    score_map = {"verified": 1.0, "partially_verified": 0.5, "contradicted": 0.0}
    scores = df["verdict"].map(score_map).dropna()
    if len(scores) < 2:
        return (0.0, 0.0)
    se = scores.std() / math.sqrt(len(scores))
    half = round(1.96 * se * 100, 1)
    return (half, half)


def build_data(verdicts_path: str, claims_path: str, runs_dir: str) -> dict:
    v = pd.read_csv(verdicts_path)
    c = pd.read_csv(claims_path)

    v["year"] = pd.to_datetime(v["call_date"]).dt.year

    # Merge to get summary text and speaker
    merged = v.merge(
        c[["claim_id", "company", "summary", "speaker_name", "horizon_raw"]],
        on="claim_id", how="left"
    )

    # ---- overall --------------------------------------------------------
    overall_counts = {k: int(v["verdict"].value_counts().get(k, 0)) for k in VERDICT_ORDER}
    overall_ts = truth_score(v)
    best  = max(TICKERS, key=lambda t: truth_score(v[v["ticker"] == t]) or 0)
    worst = min(TICKERS, key=lambda t: truth_score(v[v["ticker"] == t]) or 100)

    # ---- per-company ----------------------------------------------------
    companies = []
    for t in TICKERS:
        sub = v[v["ticker"] == t]
        vcounts = {k: int(sub["verdict"].value_counts().get(k, 0)) for k in VERDICT_ORDER}
        ct = sub["claim_type"].value_counts().to_dict()
        ts = truth_score(sub)
        lo, hi = ci_95(sub)
        companies.append({
            "ticker": t,
            "name":   TICKER_META[t]["name"],
            "color":  TICKER_META[t]["color"],
            "sector": TICKER_META[t]["sector"],
            "n":      int(len(sub)),
            "truth_score": ts,
            "ci_lo":  lo,
            "ci_hi":  hi,
            "verdicts": vcounts,
            "claim_types": {k: int(v2) for k, v2 in ct.items()},
        })

    # ---- year x ticker -------------------------------------------------
    years = [2020, 2021, 2022, 2023, 2024, 2025]
    year_by_ticker: dict[str, list] = {}
    for t in TICKERS:
        sub = v[v["ticker"] == t]
        row = []
        for y in years:
            sy = sub[sub["year"] == y]
            ts_y = truth_score(sy)
            row.append(ts_y)
        year_by_ticker[t] = row

    # ---- eval runs ------------------------------------------------------
    # Only show Baseline and Discipline Pass — citation-discipline was a
    # documented regression and is excluded to avoid confusing the chart.
    def _run_label(raw: str) -> str | None:
        s = raw.lower()
        if "baseline" in s:
            return "Baseline"
        if "discipline" in s and "citation" not in s:
            return "Discipline Pass"
        return None   # None = skip this run

    eval_runs: list[dict] = []
    for fp in sorted(glob.glob(f"{runs_dir}/*/summary.json")):
        try:
            with open(fp) as f:
                d = json.load(f)
            raw   = d.get("label", os.path.basename(os.path.dirname(fp)))
            label = _run_label(raw)
            if label is None:
                continue
            eval_runs.append({
                "label":            label,
                "recall":           d.get("mean_recall_at_k"),
                "precision":        d.get("mean_precision"),
                "verdict_accuracy": d.get("verdict_accuracy"),
                "n":                d.get("n_claims"),
            })
        except Exception:
            pass
    for fp in sorted(glob.glob(f"{runs_dir}/*_summary.json")):
        try:
            with open(fp) as f:
                d = json.load(f)
            raw   = d.get("label", os.path.basename(fp))
            label = _run_label(raw)
            if label is None:
                continue
            eval_runs.append({
                "label":            label,
                "recall":           d.get("mean_recall_at_k"),
                "precision":        d.get("mean_precision"),
                "verdict_accuracy": d.get("verdict_accuracy"),
                "n":                d.get("n_claims"),
            })
        except Exception:
            pass

    # ---- claims table ---------------------------------------------------
    claims_rows = []
    for _, row in merged.iterrows():
        verdict = row["verdict"]
        claims_rows.append({
            "ticker":     row["ticker"],
            "company":    TICKER_META.get(row["ticker"], {}).get("name", row["ticker"]),
            "year":       int(row["year"]) if not pd.isna(row["year"]) else 0,
            "call_date":  str(row["call_date"])[:10] if not pd.isna(row.get("call_date","")) else "",
            "claim_type": str(row.get("claim_type", "")),
            "verdict":    verdict,
            "summary":    str(row.get("summary", ""))[:220],
            "horizon":    str(row.get("horizon_raw", ""))[:60],
            "source":     str(row.get("source", "")),
        })

    return {
        "overall": {
            "total_claims": int(len(v)),
            "truth_score":  overall_ts,
            "best":         best,
            "worst":        worst,
            "verdicts":     overall_counts,
        },
        "companies":     companies,
        "years":         years,
        "year_by_ticker": year_by_ticker,
        "eval_runs":      eval_runs,
        "claims":         claims_rows,
        "verdict_colors": VERDICT_COLORS,
        "verdict_labels": VERDICT_LABELS,
        "ticker_meta":    TICKER_META,
    }


# ---------------------------------------------------------------------------
# HTML generator
# ---------------------------------------------------------------------------

def generate_html(data: dict) -> str:
    data_json = json.dumps(data, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Management Truthfulness Profiles | FINM 33200 Group 7</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
/* ── Reset ─────────────────────────────────────────────────────────────── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ scroll-behavior: smooth; font-size: 16px; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: #fff; color: #1a1a1a; line-height: 1.6; }}
a {{ color: inherit; text-decoration: none; }}

/* ── Navbar ─────────────────────────────────────────────────────────────── */
.navbar {{
  position: sticky; top: 0; z-index: 100;
  background: {MAROON}; color: #fff;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 40px; height: 56px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.3);
}}
.nav-brand {{ display: flex; align-items: center; gap: 12px; font-weight: 600; font-size: 0.95rem; letter-spacing: 0.02em; }}
.nav-shield {{
  width: 32px; height: 32px; border: 2px solid rgba(255,255,255,0.7);
  border-radius: 2px; display: flex; align-items: center; justify-content: center;
  font-size: 0.7rem; font-weight: 700; letter-spacing: 0.08em; color: rgba(255,255,255,0.9);
}}
.nav-links {{ display: flex; gap: 28px; font-size: 0.85rem; opacity: 0.9; }}
.nav-links a {{ transition: opacity .2s; }}
.nav-links a:hover {{ opacity: 0.7; }}

/* ── Hero ───────────────────────────────────────────────────────────────── */
.hero {{
  background: linear-gradient(135deg, {D_MAROON} 0%, {MAROON} 55%, {BRICK} 100%);
  color: #fff; padding: 64px 40px 0;
}}
.hero-inner {{ max-width: 1200px; margin: 0 auto; }}
.hero-badge {{
  display: inline-block; background: rgba(255,255,255,0.15);
  border: 1px solid rgba(255,255,255,0.3); border-radius: 20px;
  padding: 4px 14px; font-size: 0.78rem; font-weight: 600;
  letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 18px;
}}
.hero h1 {{
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 2.8rem; font-weight: 700; line-height: 1.2;
  margin-bottom: 10px; letter-spacing: -0.01em;
}}
.hero-sub {{
  font-size: 1.05rem; opacity: 0.82; max-width: 640px; margin-bottom: 28px;
}}
.hero-meta {{ display: flex; flex-wrap: wrap; gap: 20px; align-items: center; margin-bottom: 40px; }}
.meta-group {{ display: flex; flex-direction: column; gap: 2px; }}
.meta-label {{ font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.1em; opacity: 0.6; }}
.meta-value {{ font-size: 0.9rem; font-weight: 600; }}
.team-pills {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.team-pill {{
  background: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.25);
  border-radius: 20px; padding: 4px 12px; font-size: 0.82rem;
}}

/* ── Hero Stat Cards ─────────────────────────────────────────────────────── */
.stat-strip {{
  display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 1px; background: rgba(255,255,255,0.1);
  border-top: 1px solid rgba(255,255,255,0.15);
  margin: 0 -40px;
}}
.stat-card {{
  background: rgba(255,255,255,0.07);
  padding: 28px 32px; text-align: center;
  transition: background .2s;
}}
.stat-card:hover {{ background: rgba(255,255,255,0.13); }}
.stat-num {{
  font-family: Georgia, serif; font-size: 2.4rem; font-weight: 700;
  line-height: 1; margin-bottom: 6px;
}}
.stat-lbl {{ font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.08em; opacity: 0.7; }}
.stat-note {{ font-size: 0.72rem; opacity: 0.5; margin-top: 2px; }}

/* ── Sections ───────────────────────────────────────────────────────────── */
.section {{ padding: 64px 40px; max-width: 1200px; margin: 0 auto; }}
.section-full {{ padding: 64px 40px; }}
.section-full .section-inner {{ max-width: 1200px; margin: 0 auto; }}
.bg-light {{ background: #FAF8F5; }}
.section-title {{
  font-family: Georgia, serif; font-size: 1.65rem; font-weight: 700;
  color: {MAROON}; border-left: 4px solid {MAROON};
  padding-left: 16px; margin-bottom: 8px;
}}
.section-desc {{ font-size: 0.92rem; color: #555; margin-bottom: 32px; padding-left: 20px; }}

/* ── Two-column grid ─────────────────────────────────────────────────────── */
.two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 32px; align-items: start; }}
.chart-card {{
  background: #fff; border-radius: 12px;
  box-shadow: 0 2px 16px rgba(0,0,0,0.07);
  padding: 24px; overflow: hidden;
}}
.chart-card-title {{ font-size: 0.85rem; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.07em; color: #555; margin-bottom: 16px; }}

/* ── Company Cards ───────────────────────────────────────────────────────── */
.company-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
.company-card {{
  background: #fff; border-radius: 12px;
  box-shadow: 0 2px 16px rgba(0,0,0,0.07);
  overflow: hidden; transition: box-shadow .2s, transform .15s;
}}
.company-card:hover {{ box-shadow: 0 6px 28px rgba(0,0,0,0.12); transform: translateY(-2px); }}
.company-card-top {{
  padding: 20px 24px 0; border-top: 5px solid var(--accent);
  display: flex; justify-content: space-between; align-items: flex-start;
}}
.company-name {{ font-family: Georgia, serif; font-size: 1.3rem; font-weight: 700; }}
.company-ticker {{ font-size: 0.75rem; color: #888; text-transform: uppercase; letter-spacing: 0.1em; }}
.company-sector {{ font-size: 0.78rem; color: #777; margin-top: 2px; }}
.company-score {{ text-align: right; }}
.score-num {{ font-family: Georgia, serif; font-size: 2rem; font-weight: 700; color: var(--accent); line-height: 1; }}
.score-lbl {{ font-size: 0.7rem; color: #888; text-transform: uppercase; letter-spacing: 0.06em; }}
.company-donut {{ padding: 0 8px; }}
.company-pills {{ padding: 8px 24px 20px; display: flex; flex-wrap: wrap; gap: 6px; }}

/* ── Verdict Pills ───────────────────────────────────────────────────────── */
.vpill {{
  display: inline-flex; align-items: center; gap: 5px;
  border-radius: 14px; padding: 3px 10px; font-size: 0.75rem; font-weight: 600;
}}
.vpill-verified      {{ background: #E8F5E9; color: #2E7D32; }}
.vpill-partial       {{ background: #FFF3E0; color: {ORANGE}; }}
.vpill-unresolvable  {{ background: #F5F5F5; color: #555; }}
.vpill-contradicted  {{ background: #FCE4EC; color: {MAROON}; }}

/* ── Eval Section ───────────────────────────────────────────────────────── */
.eval-note {{
  background: #fff8f0; border: 1px solid rgba(193,102,34,0.25);
  border-radius: 8px; padding: 14px 18px; font-size: 0.85rem;
  color: #555; margin-top: 24px; max-width: 680px;
}}

/* ── Claims Table ───────────────────────────────────────────────────────── */
.filter-bar {{
  display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 20px;
  align-items: center;
}}
.filter-bar select, .filter-bar input {{
  padding: 8px 12px; border: 1px solid #ddd; border-radius: 6px;
  font-size: 0.85rem; color: #333; background: #fff;
  outline: none; transition: border-color .2s;
}}
.filter-bar select:focus, .filter-bar input:focus {{ border-color: {MAROON}; }}
.filter-bar input {{ width: 240px; }}
.table-wrap {{ overflow-x: auto; border-radius: 10px; box-shadow: 0 2px 12px rgba(0,0,0,0.07); }}
.claims-tbl {{
  width: 100%; border-collapse: collapse; font-size: 0.84rem;
  background: #fff;
}}
.claims-tbl thead tr {{ background: {MAROON}; color: #fff; }}
.claims-tbl th {{
  padding: 12px 14px; text-align: left; font-weight: 600;
  font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.05em;
  white-space: nowrap;
}}
.claims-tbl td {{ padding: 11px 14px; border-bottom: 1px solid #f0f0f0; vertical-align: top; }}
.claims-tbl tbody tr:hover {{ background: #FFF8F0; }}
.claims-tbl .col-company {{ font-weight: 600; white-space: nowrap; }}
.claims-tbl .col-summary {{ max-width: 340px; color: #333; }}
.tbl-badge {{
  display: inline-block; border-radius: 10px; padding: 2px 8px;
  font-size: 0.73rem; font-weight: 600; white-space: nowrap;
}}
.tbl-count {{ font-size: 0.8rem; color: #777; margin-bottom: 8px; }}

/* ── Footer ─────────────────────────────────────────────────────────────── */
footer {{
  background: {D_MAROON}; color: rgba(255,255,255,0.65);
  text-align: center; padding: 32px 40px; font-size: 0.82rem;
  line-height: 1.8;
}}
footer strong {{ color: rgba(255,255,255,0.9); }}

/* ── Responsive ─────────────────────────────────────────────────────────── */
@media (max-width: 900px) {{
  .stat-strip {{ grid-template-columns: repeat(2, 1fr); }}
  .two-col {{ grid-template-columns: 1fr; }}
  .company-grid {{ grid-template-columns: 1fr; }}
  .hero h1 {{ font-size: 2rem; }}
  .section, .section-full {{ padding: 40px 20px; }}
  .navbar {{ padding: 0 20px; }}
  .stat-strip {{ margin: 0 -20px; }}
}}
</style>
</head>
<body>

<!-- ── NAVBAR ─────────────────────────────────────────────────────────── -->
<nav class="navbar">
  <div class="nav-brand">
    <div class="nav-shield">UChicago</div>
    <span>FINM 33200 &mdash; Group 7</span>
  </div>
  <div class="nav-links">
    <a href="#overview">Overview</a>
    <a href="#companies">Companies</a>
    <a href="#trends">Trends</a>
    <a href="#claims">Claims</a>
    <a href="#eval">Agent Eval</a>
  </div>
</nav>

<!-- ── HERO ───────────────────────────────────────────────────────────── -->
<header class="hero">
  <div class="hero-inner">
    <div class="hero-badge">FINM 33200 &mdash; Generative and Agentic AI for Finance &mdash; Spring 2026</div>
    <h1>Management Truthfulness Profiles</h1>
    <p class="hero-sub">
      Do executives keep their word? An agentic NLP pipeline that extracts forward-looking claims
      from earnings calls and verifies them against SEC filings for four S&amp;P 500 companies.
    </p>
    <div class="hero-meta">
      <div class="meta-group">
        <span class="meta-label">Project</span>
        <span class="meta-value">Forward-Claim Verification via Agentic SEC Retrieval</span>
      </div>
      <div class="meta-group">
        <span class="meta-label">Team</span>
        <div class="team-pills">
          <span class="team-pill">Brendan Kehoe</span>
          <span class="team-pill">Seback Oh</span>
          <span class="team-pill">Tejaswini Shashidhar</span>
          <span class="team-pill">Thomas Hillenbrand</span>
        </div>
      </div>
    </div>
  </div>

  <!-- stat strip sits at bottom of hero -->
  <div class="hero-inner">
    <div class="stat-strip">
      <div class="stat-card">
        <div class="stat-num" id="hero-total"></div>
        <div class="stat-lbl">Claims Graded</div>
        <div class="stat-note">4 companies, 2020&ndash;2025</div>
      </div>
      <div class="stat-card">
        <div class="stat-num" id="hero-score"></div>
        <div class="stat-lbl">Overall Truth Score</div>
        <div class="stat-note">Excludes unresolvable</div>
      </div>
      <div class="stat-card">
        <div class="stat-num" id="hero-best"></div>
        <div class="stat-lbl">Top Performer</div>
        <div class="stat-note" id="hero-best-score"></div>
      </div>
      <div class="stat-card">
        <div class="stat-num" id="hero-accuracy"></div>
        <div class="stat-lbl">Agent Verdict Accuracy</div>
        <div class="stat-note">Discipline-pass configuration</div>
      </div>
    </div>
  </div>
</header>

<!-- ── OVERVIEW ───────────────────────────────────────────────────────── -->
<div id="overview" class="section">
  <div class="section-title">Overall Truthfulness</div>
  <p class="section-desc">Verdict distribution across all 451 graded claims and ranked truth scores by company.</p>
  <div class="two-col">
    <div class="chart-card">
      <div class="chart-card-title">Verdict Distribution &mdash; All Claims</div>
      <div id="chart-donut-overall" style="height:340px;"></div>
    </div>
    <div class="chart-card">
      <div class="chart-card-title">Truth Score by Company (95% CI)</div>
      <div id="chart-bar-company" style="height:340px;"></div>
    </div>
  </div>
</div>

<!-- ── COMPANY PROFILES ───────────────────────────────────────────────── -->
<div id="companies" class="section-full bg-light">
  <div class="section-inner">
    <div class="section-title">Company Profiles</div>
    <p class="section-desc">Verdict breakdown and truth score for each firm. Hover charts for exact counts.</p>
    <div class="company-grid" id="company-grid"></div>
  </div>
</div>

<!-- ── TRENDS ─────────────────────────────────────────────────────────── -->
<div id="trends" class="section">
  <div class="section-title">Truthfulness Over Time</div>
  <p class="section-desc">Year-by-year truth score (verified + 0.5 × partial) for claims resolvable in that year. Missing markers indicate no resolvable claims that year.</p>
  <div class="chart-card">
    <div id="chart-trend" style="height:380px;"></div>
  </div>
</div>

<!-- ── HEATMAP ────────────────────────────────────────────────────────── -->
<div class="section-full bg-light">
  <div class="section-inner">
    <div class="section-title">Company &times; Year Heatmap</div>
    <p class="section-desc">Colour intensity reflects truth score. Grey cells have no resolvable claims for that year.</p>
    <div class="chart-card">
      <div id="chart-heatmap" style="height:310px;"></div>
    </div>
  </div>
</div>

<!-- ── CLAIM TYPES ─────────────────────────────────────────────────────── -->
<div class="section">
  <div class="section-title">Claim Type Breakdown</div>
  <p class="section-desc">Volume and verdict split by claim type: numerical guidance vs. capital allocation.</p>
  <div class="two-col">
    <div class="chart-card">
      <div class="chart-card-title">Claim Type Volume per Company</div>
      <div id="chart-claimtype-vol" style="height:320px;"></div>
    </div>
    <div class="chart-card">
      <div class="chart-card-title">Verdict Mix by Claim Type</div>
      <div id="chart-claimtype-verdict" style="height:320px;"></div>
    </div>
  </div>
</div>

<!-- ── AGENT EVAL ──────────────────────────────────────────────────────── -->
<div id="eval" class="section-full bg-light">
  <div class="section-inner">
    <div class="section-title">Agent Performance</div>
    <p class="section-desc">Retrieval and verdict accuracy evaluated on a 28-claim gold set (LLM-labeled, cap-alloc only).</p>
    <div class="chart-card">
      <div id="chart-eval" style="height:340px;"></div>
    </div>
    <div class="eval-note">
      <strong>Gold set note:</strong> The 28-claim evaluation set was labeled by GPT-5.5 using the project rubric
      (not hand-labeled &mdash; a deliberate, time-constrained substitution). Verdict accuracy measures agreement
      between the graded agent (gpt-5.1) and the gold labels. Recall@8 measures whether the correct
      SEC filing appears in the top-8 retrieved chunks.
    </div>
  </div>
</div>

<!-- ── CLAIMS TABLE ────────────────────────────────────────────────────── -->
<div id="claims" class="section">
  <div class="section-title">Browse Claims</div>
  <p class="section-desc">All 451 graded claims. Filter by company, verdict, or claim type; search by keyword.</p>

  <div class="filter-bar">
    <select id="f-company" onchange="filterTable()">
      <option value="">All Companies</option>
      <option value="Amazon">Amazon</option>
      <option value="Tesla">Tesla</option>
      <option value="Coca-Cola">Coca-Cola</option>
      <option value="Eli Lilly">Eli Lilly</option>
    </select>
    <select id="f-verdict" onchange="filterTable()">
      <option value="">All Verdicts</option>
      <option value="verified">Verified</option>
      <option value="partially_verified">Partially Verified</option>
      <option value="contradicted">Contradicted</option>
      <option value="not_yet_resolvable">Not Yet Resolvable</option>
    </select>
    <select id="f-type" onchange="filterTable()">
      <option value="">All Types</option>
      <option value="numerical_guidance">Numerical Guidance</option>
      <option value="capital_allocation">Capital Allocation</option>
    </select>
    <select id="f-year" onchange="filterTable()">
      <option value="">All Years</option>
      <option value="2020">2020</option>
      <option value="2021">2021</option>
      <option value="2022">2022</option>
      <option value="2023">2023</option>
      <option value="2024">2024</option>
      <option value="2025">2025</option>
    </select>
    <input id="f-search" type="text" placeholder="Search summaries..." oninput="filterTable()">
  </div>

  <div class="tbl-count" id="tbl-count"></div>
  <div class="table-wrap">
    <table class="claims-tbl" id="claims-table">
      <thead>
        <tr>
          <th>Company</th>
          <th>Year</th>
          <th>Type</th>
          <th>Verdict</th>
          <th>Summary</th>
          <th>Horizon</th>
          <th>Source</th>
        </tr>
      </thead>
      <tbody id="claims-tbody"></tbody>
    </table>
  </div>
</div>

<!-- ── FOOTER ─────────────────────────────────────────────────────────── -->
<footer>
  <strong>FINM 33200 &mdash; Generative and Agentic AI for Finance &mdash; Spring 2026</strong><br>
  <strong>Group 7:</strong> Brendan Kehoe &nbsp;&bull;&nbsp; Seback Oh &nbsp;&bull;&nbsp; Tejaswini Shashidhar &nbsp;&bull;&nbsp; Thomas Hillenbrand<br>
  University of Chicago &mdash; Department of Statistics and the College<br>
  Data sources: WRDS earnings call transcripts, SEC EDGAR, Compustat
</footer>

<!-- ── DATA + CHARTS ──────────────────────────────────────────────────── -->
<script>
const D = {data_json};

// ── helpers ────────────────────────────────────────────────────────────────
const VERDICT_NICE = {{
  verified: 'Verified', partially_verified: 'Partially Verified',
  not_yet_resolvable: 'Not Yet Resolvable', contradicted: 'Contradicted'
}};
const VERDICT_COLORS = D.verdict_colors;
const TICKER_NAMES = {{ AMZN:'Amazon', TSLA:'Tesla', KO:'Coca-Cola', LLY:'Eli Lilly' }};
const TICKER_COLORS = {{ AMZN:'{MAROON}', TSLA:'{ORANGE}', KO:'{LAKE}', LLY:'{GOLD}' }};

const LAYOUT_BASE = {{
  paper_bgcolor: '#fff', plot_bgcolor: '#fff',
  font: {{ family: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif", size: 12, color: '#333' }},
  margin: {{ l:16, r:16, t:16, b:16 }},
  legend: {{ bgcolor: 'rgba(0,0,0,0)', borderwidth: 0 }},
}};
const CFG = {{ responsive: true, displayModeBar: false }};

// ── hero stats ──────────────────────────────────────────────────────────────
document.getElementById('hero-total').textContent = D.overall.total_claims.toLocaleString();
document.getElementById('hero-score').textContent = D.overall.truth_score + '%';
const bestCo = D.companies.find(c => c.ticker === D.overall.best);
document.getElementById('hero-best').textContent  = bestCo ? bestCo.name : D.overall.best;
document.getElementById('hero-best-score').textContent = bestCo ? bestCo.truth_score + '% truth score' : '';

const bestRun = D.eval_runs.reduce((a,b) => ((b.verdict_accuracy||0) > (a.verdict_accuracy||0) ? b : a), D.eval_runs[0] || {{}});
document.getElementById('hero-accuracy').textContent = bestRun && bestRun.verdict_accuracy
  ? Math.round(bestRun.verdict_accuracy * 100) + '%' : 'N/A';

// ── chart 1 — overall donut ─────────────────────────────────────────────────
(function() {{
  const order = ['verified','partially_verified','contradicted','not_yet_resolvable'];
  const counts = order.map(k => D.overall.verdicts[k] || 0);
  const colors = order.map(k => VERDICT_COLORS[k]);
  const labels = order.map(k => VERDICT_NICE[k]);

  const trace = {{
    type: 'pie', hole: 0.58,
    values: counts, labels: labels,
    marker: {{ colors: colors, line: {{ color: '#fff', width: 2 }} }},
    textinfo: 'label+percent',
    textfont: {{ size: 12 }},
    hovertemplate: '<b>%{{label}}</b><br>%{{value}} claims (%{{percent}})<extra></extra>',
    sort: false,
  }};

  const layout = Object.assign({{}}, LAYOUT_BASE, {{
    annotations: [{{
      text: '<b>' + D.overall.total_claims + '</b><br><span style="font-size:11px">claims</span>',
      x: 0.5, y: 0.5, xref: 'paper', yref: 'paper',
      showarrow: false, font: {{ size: 18, color: '#1a1a1a' }},
    }}],
    showlegend: true,
    legend: {{ orientation: 'v', x: 1.0, y: 0.5, xanchor: 'left' }},
    margin: {{ l: 10, r: 120, t: 20, b: 20 }},
  }});

  Plotly.newPlot('chart-donut-overall', [trace], layout, CFG);
}})();

// ── chart 2 — company bar comparison ───────────────────────────────────────
(function() {{
  const cos = [...D.companies].sort((a,b) => (b.truth_score||0) - (a.truth_score||0));
  const names  = cos.map(c => c.name);
  const scores = cos.map(c => c.truth_score);
  const errors = cos.map(c => c.ci_hi);
  const colors = cos.map(c => c.color);

  const trace = {{
    type: 'bar', orientation: 'h',
    x: scores, y: names,
    error_x: {{
      type: 'data', array: errors, arrayminus: cos.map(c => c.ci_lo),
      color: '#aaa', thickness: 1.5, width: 6,
    }},
    marker: {{
      color: colors,
      line: {{ color: colors.map(c => c), width: 0 }},
      opacity: 0.9,
    }},
    text: scores.map(s => s + '%'),
    textposition: 'outside',
    textfont: {{ size: 13, color: '#333' }},
    hovertemplate: '<b>%{{y}}</b><br>Truth Score: %{{x}}%<extra></extra>',
  }};

  const layout = Object.assign({{}}, LAYOUT_BASE, {{
    xaxis: {{
      range: [0, 100], title: 'Truth Score (%)',
      ticksuffix: '%', gridcolor: '#f0f0f0',
    }},
    yaxis: {{ automargin: true }},
    margin: {{ l: 10, r: 60, t: 20, b: 50 }},
    bargap: 0.35,
  }});

  Plotly.newPlot('chart-bar-company', [trace], layout, CFG);
}})();

// ── company profile cards ───────────────────────────────────────────────────
(function() {{
  const grid = document.getElementById('company-grid');
  const VERDICT_ORDER_DISPLAY = ['verified','partially_verified','not_yet_resolvable','contradicted'];

  D.companies.forEach(co => {{
    const card = document.createElement('div');
    card.className = 'company-card';
    card.style.setProperty('--accent', co.color);

    const ts   = co.truth_score !== null ? co.truth_score + '%' : 'N/A';
    const ci   = co.ci_hi > 0 ? ' <span style="font-size:.75rem;color:#aaa">± ' + co.ci_hi + '%</span>' : '';

    const pillsHtml = VERDICT_ORDER_DISPLAY.map(k => {{
      const n = co.verdicts[k] || 0;
      if (n === 0) return '';
      const cls = k === 'verified' ? 'verified'
                : k === 'partially_verified' ? 'partial'
                : k === 'not_yet_resolvable' ? 'unresolvable'
                : 'contradicted';
      return `<span class="vpill vpill-${{cls}}">${{n}} ${{VERDICT_NICE[k]}}</span>`;
    }}).join('');

    const ctHtml = Object.entries(co.claim_types).map(([t, n]) => {{
      const lbl = t === 'numerical_guidance' ? 'Numerical' : 'Cap. Alloc.';
      return `<span class="vpill" style="background:#f5f5f5;color:#555">${{n}} ${{lbl}}</span>`;
    }}).join('');

    card.innerHTML = `
      <div class="company-card-top">
        <div>
          <div class="company-name">${{co.name}}</div>
          <div class="company-ticker">${{co.ticker}}</div>
          <div class="company-sector">${{co.sector}}</div>
        </div>
        <div class="company-score">
          <div class="score-num">${{ts}}</div>
          <div class="score-lbl">truth score</div>
        </div>
      </div>
      <div class="company-donut"><div id="donut-${{co.ticker}}" style="height:220px;"></div></div>
      <div class="company-pills">${{pillsHtml}}</div>
      <div class="company-pills" style="padding-top:0;border-top:1px solid #f5f5f5;">${{ctHtml}}&nbsp;&nbsp;<span style="font-size:.75rem;color:#aaa;align-self:center">${{co.n}} total claims</span></div>
    `;
    grid.appendChild(card);

    // render mini donut
    const order = ['verified','partially_verified','not_yet_resolvable','contradicted'];
    const vals   = order.map(k => co.verdicts[k] || 0);
    const colors = order.map(k => VERDICT_COLORS[k]);
    const labels = order.map(k => VERDICT_NICE[k]);

    Plotly.newPlot('donut-' + co.ticker, [{{
      type: 'pie', hole: 0.55,
      values: vals, labels: labels,
      marker: {{ colors: colors, line: {{ color: '#fff', width: 1.5 }} }},
      textinfo: 'percent',
      textfont: {{ size: 11 }},
      hovertemplate: '<b>%{{label}}</b><br>%{{value}} claims<extra></extra>',
      sort: false,
    }}], Object.assign({{}}, LAYOUT_BASE, {{
      showlegend: false,
      annotations: [{{
        text: '<b>' + ts + '</b>',
        x: 0.5, y: 0.5, xref: 'paper', yref: 'paper',
        showarrow: false, font: {{ size: 16, color: co.color }},
      }}],
      margin: {{ l: 10, r: 10, t: 10, b: 10 }},
    }}), CFG);
  }});
}})();

// ── chart — trend lines ─────────────────────────────────────────────────────
(function() {{
  const traces = Object.entries(D.year_by_ticker).map(([ticker, scores]) => {{
    const ys = scores.map((s,i) => s !== null ? D.years[i] : null).filter(x => x !== null);
    const vs = scores.filter(s => s !== null);
    return {{
      type: 'scatter', mode: 'lines+markers',
      name: TICKER_NAMES[ticker],
      x: ys, y: vs,
      line: {{ color: TICKER_COLORS[ticker], width: 2.5 }},
      marker: {{ size: 9, color: TICKER_COLORS[ticker], line: {{ color: '#fff', width: 1.5 }} }},
      hovertemplate: '<b>' + (TICKER_NAMES[ticker]||ticker) + '</b><br>%{{x}}: %{{y:.1f}}%<extra></extra>',
    }};
  }});

  const layout = Object.assign({{}}, LAYOUT_BASE, {{
    xaxis: {{ title: 'Year', dtick: 1, gridcolor: '#f0f0f0', tickformat: 'd' }},
    yaxis: {{ title: 'Truth Score (%)', range: [0, 108], ticksuffix: '%', gridcolor: '#f0f0f0' }},
    legend: {{ orientation: 'h', y: -0.15, x: 0.5, xanchor: 'center' }},
    margin: {{ l: 50, r: 20, t: 20, b: 60 }},
    hovermode: 'x unified',
  }});

  Plotly.newPlot('chart-trend', traces, layout, CFG);
}})();

// ── chart — heatmap ─────────────────────────────────────────────────────────
(function() {{
  const tickers = ['AMZN','TSLA','KO','LLY'];
  const names   = tickers.map(t => TICKER_NAMES[t]);
  const years   = D.years;

  const z = tickers.map(t => years.map((_,i) => {{
    const s = D.year_by_ticker[t][i];
    return s !== null ? s : null;
  }}));

  const text = tickers.map((t,ti) => years.map((y,yi) => {{
    const s = z[ti][yi];
    return s !== null ? s.toFixed(1) + '%' : 'N/A';
  }}));

  const trace = {{
    type: 'heatmap',
    z: z, x: years, y: names, text: text,
    texttemplate: '%{{text}}',
    textfont: {{ size: 12, color: '#fff' }},
    colorscale: [
      [0,    '{MAROON}'],
      [0.35, '#D4875A'],
      [0.5,  '#F5E6B2'],
      [0.65, '#A5C882'],
      [1,    '#2E7D32'],
    ],
    zmin: 0, zmax: 100,
    hoverongaps: false,
    hovertemplate: '<b>%{{y}} %{{x}}</b><br>Truth Score: %{{text}}<extra></extra>',
    showscale: true,
    colorbar: {{
      title: 'Score', titleside: 'right',
      ticksuffix: '%', len: 0.8,
    }},
  }};

  const layout = Object.assign({{}}, LAYOUT_BASE, {{
    xaxis: {{ tickformat: 'd', dtick: 1, side: 'bottom' }},
    yaxis: {{ automargin: true }},
    margin: {{ l: 80, r: 80, t: 20, b: 40 }},
  }});

  Plotly.newPlot('chart-heatmap', [trace], layout, CFG);
}})();

// ── chart — claim type volume ───────────────────────────────────────────────
(function() {{
  const companies = D.companies;
  const names = companies.map(c => c.name);

  const numTrace = {{
    type: 'bar', name: 'Numerical Guidance',
    x: names,
    y: companies.map(c => c.claim_types['numerical_guidance'] || 0),
    marker: {{ color: '{LAKE}', opacity: 0.85 }},
    hovertemplate: '<b>%{{x}}</b><br>Numerical: %{{y}}<extra></extra>',
  }};
  const capTrace = {{
    type: 'bar', name: 'Capital Allocation',
    x: names,
    y: companies.map(c => c.claim_types['capital_allocation'] || 0),
    marker: {{ color: TICKER_COLORS['LLY'], opacity: 0.85 }},
    hovertemplate: '<b>%{{x}}</b><br>Cap. Alloc.: %{{y}}<extra></extra>',
  }};

  const layout = Object.assign({{}}, LAYOUT_BASE, {{
    barmode: 'stack',
    xaxis: {{ automargin: true }},
    yaxis: {{ title: 'Number of Claims', gridcolor: '#f0f0f0' }},
    legend: {{ orientation: 'h', y: -0.2, x: 0.5, xanchor: 'center' }},
    margin: {{ l: 50, r: 20, t: 20, b: 60 }},
  }});

  Plotly.newPlot('chart-claimtype-vol', [numTrace, capTrace], layout, CFG);
}})();

// ── chart — verdict mix by claim type ──────────────────────────────────────
(function() {{
  const claimTypes = ['numerical_guidance', 'capital_allocation'];
  const niceTypes  = ['Numerical Guidance', 'Capital Allocation'];
  const vkeys = ['verified','partially_verified','contradicted','not_yet_resolvable'];

  // compute verdicts per claim type across all companies
  const byType = {{}};
  claimTypes.forEach(ct => {{
    byType[ct] = {{}};
    vkeys.forEach(vk => {{ byType[ct][vk] = 0; }});
  }});
  D.claims.forEach(cl => {{
    const ct = cl.claim_type;
    const v  = cl.verdict;
    if (byType[ct] && byType[ct][v] !== undefined) byType[ct][v]++;
  }});

  const traces = vkeys.map(vk => ({{
    type: 'bar', name: VERDICT_NICE[vk],
    x: niceTypes,
    y: claimTypes.map(ct => byType[ct][vk] || 0),
    marker: {{ color: VERDICT_COLORS[vk] }},
    hovertemplate: '<b>%{{x}}</b><br>' + VERDICT_NICE[vk] + ': %{{y}}<extra></extra>',
  }}));

  const layout = Object.assign({{}}, LAYOUT_BASE, {{
    barmode: 'stack',
    xaxis: {{ automargin: true }},
    yaxis: {{ title: 'Number of Claims', gridcolor: '#f0f0f0' }},
    legend: {{ orientation: 'h', y: -0.2, x: 0.5, xanchor: 'center' }},
    margin: {{ l: 50, r: 20, t: 20, b: 60 }},
  }});

  Plotly.newPlot('chart-claimtype-verdict', traces, layout, CFG);
}})();

// ── chart — agent eval ──────────────────────────────────────────────────────
(function() {{
  const runs = D.eval_runs.filter(r => r.recall !== null);
  if (!runs.length) return;

  const labels = runs.map(r => {{
    const s = r.label || '';
    // labels are already humanised in Python — pass through as-is
    return s || label.substring(0, 24);
  }});

  const metrics = [
    {{ key: 'recall',           nice: 'Recall @ 8',        color: '{MAROON}'  }},
    {{ key: 'precision',        nice: 'Precision',         color: '{ORANGE}'  }},
    {{ key: 'verdict_accuracy', nice: 'Verdict Accuracy',  color: '{LAKE}'    }},
  ];

  const traces = metrics.map(m => ({{
    type: 'bar', name: m.nice,
    x: labels,
    y: runs.map(r => r[m.key] !== null ? parseFloat((r[m.key] * 100).toFixed(1)) : null),
    marker: {{ color: m.color, opacity: 0.88 }},
    text: runs.map(r => r[m.key] !== null ? (r[m.key]*100).toFixed(1)+'%' : ''),
    textposition: 'outside',
    hovertemplate: '<b>%{{x}}</b><br>' + m.nice + ': %{{y:.1f}}%<extra></extra>',
  }}));

  const layout = Object.assign({{}}, LAYOUT_BASE, {{
    barmode: 'group',
    xaxis: {{ automargin: true }},
    yaxis: {{ title: 'Score (%)', range: [0, 105], ticksuffix: '%', gridcolor: '#f0f0f0' }},
    legend: {{ orientation: 'h', y: -0.18, x: 0.5, xanchor: 'center' }},
    margin: {{ l: 50, r: 20, t: 20, b: 70 }},
    bargap: 0.25,
    bargroupgap: 0.08,
  }});

  Plotly.newPlot('chart-eval', traces, layout, CFG);
}})();

// ── claims table ─────────────────────────────────────────────────────────────
(function() {{
  const BADGE_CLS = {{
    verified:           'vpill vpill-verified',
    partially_verified: 'vpill vpill-partial',
    not_yet_resolvable: 'vpill vpill-unresolvable',
    contradicted:       'vpill vpill-contradicted',
  }};
  const TYPE_NICE = {{ numerical_guidance:'Numerical', capital_allocation:'Cap. Alloc.' }};

  let filtered = D.claims;

  function buildRow(cl) {{
    const badge = `<span class="${{BADGE_CLS[cl.verdict] || 'vpill'}}">${{VERDICT_NICE[cl.verdict] || cl.verdict}}</span>`;
    const type  = TYPE_NICE[cl.claim_type] || cl.claim_type;
    const src   = cl.source === 'autochecker' ? '<span style="color:#555;font-size:.72rem">Compustat</span>' : '<span style="color:#555;font-size:.72rem">SEC Agent</span>';
    return `<tr>
      <td class="col-company">${{cl.company}}</td>
      <td>${{cl.year}}</td>
      <td style="font-size:.8rem;white-space:nowrap">${{type}}</td>
      <td>${{badge}}</td>
      <td class="col-summary">${{cl.summary}}</td>
      <td style="font-size:.78rem;color:#888;max-width:140px">${{cl.horizon}}</td>
      <td>${{src}}</td>
    </tr>`;
  }}

  function filterTable() {{
    const company = document.getElementById('f-company').value;
    const verdict = document.getElementById('f-verdict').value;
    const ctype   = document.getElementById('f-type').value;
    const year    = document.getElementById('f-year').value;
    const search  = document.getElementById('f-search').value.toLowerCase();

    filtered = D.claims.filter(cl => {{
      if (company && cl.company !== company) return false;
      if (verdict && cl.verdict !== verdict) return false;
      if (ctype   && cl.claim_type !== ctype) return false;
      if (year    && String(cl.year) !== year) return false;
      if (search  && !cl.summary.toLowerCase().includes(search)) return false;
      return true;
    }});

    document.getElementById('claims-tbody').innerHTML = filtered.map(buildRow).join('');
    document.getElementById('tbl-count').textContent =
      'Showing ' + filtered.length.toLocaleString() + ' of ' + D.claims.length.toLocaleString() + ' claims';
  }}

  window.filterTable = filterTable;  // expose for onchange handlers
  filterTable();  // initial render
}})();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Generate interactive HTML dashboard")
    ap.add_argument("--verdicts", default="data/verdicts/combined_55_final.csv")
    ap.add_argument("--claims",   default="data/claims/55_full_run.csv")
    ap.add_argument("--runs-dir", default="data/eval/runs")
    ap.add_argument("--out",      default="data/profiles/dashboard.html")
    args = ap.parse_args()

    print(f"Loading {args.verdicts} ...")
    data = build_data(args.verdicts, args.claims, args.runs_dir)

    print(f"Writing dashboard to {args.out} ...")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    html = generate_html(data)
    Path(args.out).write_text(html, encoding="utf-8")

    print(f"Done. Open in browser: file://{Path(args.out).resolve()}")


if __name__ == "__main__":
    main()
