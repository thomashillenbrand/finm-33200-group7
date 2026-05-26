"""Truthfulness profile visualizations.

Reads a combined verdicts CSV (autochecker + verifier output merged),
joins it with the claims CSV for metadata, and produces a full set of
publication-quality charts saved to data/profiles/.

Usage:
    python -m profiles.visualize \
        --verdicts data/autochecker/55_full_run_verdict_autochecker-v1.csv \
        --claims   data/claims/55_full_run.csv \
        --out      data/profiles/

The script is designed to be re-run as new verdict files land — just
point --verdicts at the latest combined output.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns

# ── Palette & style ───────────────────────────────────────────────────────────

VERDICT_COLORS = {
    "verified":            "#2ecc71",   # green
    "partially_verified":  "#f39c12",   # amber
    "contradicted":        "#e74c3c",   # red
    "not_yet_resolvable":  "#95a5a6",   # grey
    "insufficient_data":   "#bdc3c7",   # light grey
}

VERDICT_LABELS = {
    "verified":            "Verified",
    "partially_verified":  "Partially Verified",
    "contradicted":        "Contradicted",
    "not_yet_resolvable":  "Not Yet Resolvable",
    "insufficient_data":   "Insufficient Data",
}

TICKER_COLORS = {
    "AMZN": "#FF9900",   # Amazon orange
    "TSLA": "#CC0000",   # Tesla red
    "KO":   "#F40009",   # Coke red (use distinct shade)
    "LLY":  "#C8102E",   # Lilly red
}

TICKER_COLORS = {
    "AMZN": "#e67e22",
    "TSLA": "#2c3e50",
    "KO":   "#c0392b",
    "LLY":  "#8e44ad",
}

COMPANY_NAMES = {
    "AMZN": "Amazon",
    "TSLA": "Tesla",
    "KO":   "Coca-Cola",
    "LLY":  "Eli Lilly",
}

VERDICT_ORDER = [
    "verified",
    "partially_verified",
    "contradicted",
    "not_yet_resolvable",
    "insufficient_data",
]

sns.set_theme(style="whitegrid", font="DejaVu Sans")
plt.rcParams.update({
    "figure.dpi": 150,
    "savefig.dpi": 180,
    "savefig.bbox": "tight",
    "font.size": 11,
    "axes.titlesize": 14,
    "axes.labelsize": 12,
    "axes.titlepad": 12,
})


# ── Data loading & prep ───────────────────────────────────────────────────────

def load_data(verdicts_path: Path, claims_path: Path) -> pd.DataFrame:
    """Load and join verdicts + claim metadata. Returns one row per claim."""
    verdicts = pd.read_csv(verdicts_path)
    claims   = pd.read_csv(claims_path)

    # Keep only claims that got a verdict (skip screened-out ones)
    verdicts = verdicts[verdicts["verdict"].notna() & (verdicts["verdict"] != "")]

    df = verdicts.merge(
        claims[["claim_id", "company", "verbatim_quote", "summary",
                "horizon_raw", "horizon_period", "speaker_name",
                "speaker_type", "call_date"]],
        on="claim_id", how="left",
        suffixes=("", "_claim"),
    )

    # Use call_date from verdicts if available; fall back to claims
    if "call_date_claim" in df.columns:
        df["call_date"] = df["call_date"].fillna(df["call_date_claim"])
        df = df.drop(columns=["call_date_claim"])

    df["call_date"] = pd.to_datetime(df["call_date"], errors="coerce")
    df["year"]      = df["call_date"].dt.year
    df["company"]   = df.get("company", df["ticker"].map(COMPANY_NAMES))

    # Normalise verdict strings (lowercase, strip)
    df["verdict"] = df["verdict"].str.strip().str.lower()
    df["verdict"] = df["verdict"].where(df["verdict"].isin(VERDICT_ORDER),
                                         other="not_yet_resolvable")

    # Truth score: verified=1, partially=0.5, everything else=0
    df["truth_score"] = df["verdict"].map({
        "verified": 1.0,
        "partially_verified": 0.5,
        "contradicted": 0.0,
        "not_yet_resolvable": np.nan,
        "insufficient_data": np.nan,
    })

    return df


def verdict_counts(df: pd.DataFrame, groupby: str) -> pd.DataFrame:
    """Percentage breakdown of verdicts for each group value."""
    ct = (df.groupby([groupby, "verdict"])
            .size()
            .reset_index(name="n"))
    total = ct.groupby(groupby)["n"].transform("sum")
    ct["pct"] = ct["n"] / total * 100
    return ct


# ── Individual charts ─────────────────────────────────────────────────────────

def fig_overview_donut(df: pd.DataFrame, out: Path) -> None:
    """Overall verdict breakdown — one donut per company, in a 2×2 grid."""
    tickers = sorted(df["ticker"].unique())
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    axes = axes.flatten()

    fig.suptitle("Truthfulness Profiles — All Companies", fontsize=18,
                 fontweight="bold", y=1.01)

    for ax, ticker in zip(axes, tickers):
        sub = df[df["ticker"] == ticker]
        counts = sub["verdict"].value_counts()
        present = [v for v in VERDICT_ORDER if v in counts.index]
        sizes  = [counts[v] for v in present]
        colors = [VERDICT_COLORS[v] for v in present]
        labels = [f"{VERDICT_LABELS[v]}\n({counts[v]})" for v in present]

        wedges, texts, autotexts = ax.pie(
            sizes, colors=colors, labels=None,
            autopct=lambda p: f"{p:.1f}%" if p > 4 else "",
            startangle=90, pctdistance=0.75,
            wedgeprops={"linewidth": 1.5, "edgecolor": "white"},
        )
        for at in autotexts:
            at.set_fontsize(9)
            at.set_fontweight("bold")
            at.set_color("white")

        # Draw inner circle for donut
        centre = plt.Circle((0, 0), 0.50, fc="white")
        ax.add_patch(centre)

        # Score in centre
        scored = sub["truth_score"].dropna()
        score  = scored.mean() * 100 if len(scored) else 0
        ax.text(0, 0.08, f"{score:.0f}%", ha="center", va="center",
                fontsize=22, fontweight="bold",
                color=TICKER_COLORS.get(ticker, "#2c3e50"))
        ax.text(0, -0.18, "truth score", ha="center", va="center",
                fontsize=9, color="#666666")

        ax.set_title(f"{COMPANY_NAMES.get(ticker, ticker)} ({ticker})",
                     fontsize=13, fontweight="bold", pad=10)

        ax.legend(wedges, labels, loc="lower center",
                  bbox_to_anchor=(0.5, -0.22), fontsize=8,
                  ncol=2, frameon=False)

    fig.tight_layout(pad=2.5)
    fig.savefig(out / "01_overview_donuts.png")
    plt.close(fig)
    print(f"  Saved 01_overview_donuts.png")


def fig_company_bars(df: pd.DataFrame, out: Path) -> None:
    """100% stacked bar — one bar per company, side by side."""
    ct = verdict_counts(df, "ticker")
    tickers = ["AMZN", "TSLA", "KO", "LLY"]
    tickers = [t for t in tickers if t in df["ticker"].unique()]

    fig, ax = plt.subplots(figsize=(11, 6))
    bar_w = 0.55
    x = np.arange(len(tickers))
    bottoms = np.zeros(len(tickers))

    for verdict in VERDICT_ORDER:
        sub = ct[ct["verdict"] == verdict].set_index("ticker")
        vals = np.array([sub.loc[t, "pct"] if t in sub.index else 0
                         for t in tickers])
        bars = ax.bar(x, vals, bar_w, bottom=bottoms,
                      color=VERDICT_COLORS[verdict],
                      label=VERDICT_LABELS[verdict],
                      edgecolor="white", linewidth=0.8)

        # Label segments >8%
        for xi, (val, bot) in enumerate(zip(vals, bottoms)):
            if val > 8:
                ax.text(xi, bot + val / 2, f"{val:.0f}%",
                        ha="center", va="center",
                        fontsize=9, fontweight="bold", color="white")
        bottoms += vals

    # Truth score annotation above bars
    for xi, ticker in enumerate(tickers):
        scored = df[df["ticker"] == ticker]["truth_score"].dropna()
        score  = scored.mean() * 100 if len(scored) else 0
        n      = len(df[df["ticker"] == ticker])
        ax.text(xi, 103, f"Score: {score:.0f}%", ha="center", va="bottom",
                fontsize=9, color=TICKER_COLORS.get(ticker, "#333"),
                fontweight="bold")
        ax.text(xi, -6, f"n={n}", ha="center", va="top",
                fontsize=8, color="#888")

    ax.set_xticks(x)
    ax.set_xticklabels([COMPANY_NAMES.get(t, t) for t in tickers],
                       fontsize=12, fontweight="bold")
    ax.set_ylim(-10, 115)
    ax.set_ylabel("Share of Claims (%)", fontsize=11)
    ax.set_title("Verdict Breakdown by Company", fontsize=15, fontweight="bold")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter())
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    sns.despine(ax=ax, left=True, bottom=True)

    legend = ax.legend(loc="upper right", fontsize=9, framealpha=0.9,
                       edgecolor="#ccc", ncol=1)
    fig.tight_layout()
    fig.savefig(out / "02_company_verdict_bars.png")
    plt.close(fig)
    print(f"  Saved 02_company_verdict_bars.png")


def fig_claim_type_breakdown(df: pd.DataFrame, out: Path) -> None:
    """Side-by-side: verdict breakdown by claim type, per company."""
    tickers = sorted(df["ticker"].unique())
    claim_types = ["numerical_guidance", "capital_allocation"]
    type_labels = {"numerical_guidance": "Numerical Guidance",
                   "capital_allocation": "Capital Allocation"}

    fig, axes = plt.subplots(1, len(tickers), figsize=(14, 5), sharey=True)
    if len(tickers) == 1:
        axes = [axes]

    fig.suptitle("Verdict Breakdown by Claim Type", fontsize=15,
                 fontweight="bold", y=1.02)

    for ax, ticker in zip(axes, tickers):
        sub = df[df["ticker"] == ticker]
        ct  = verdict_counts(sub, "claim_type")

        x = np.arange(len(claim_types))
        bar_w = 0.55
        bottoms = np.zeros(len(claim_types))

        for verdict in VERDICT_ORDER:
            v_sub = ct[ct["verdict"] == verdict].set_index("claim_type")
            vals  = np.array([v_sub.loc[ct_,"pct"] if ct_ in v_sub.index else 0
                              for ct_ in claim_types])
            ax.bar(x, vals, bar_w, bottom=bottoms,
                   color=VERDICT_COLORS[verdict],
                   label=VERDICT_LABELS[verdict],
                   edgecolor="white", linewidth=0.8)
            for xi, (val, bot) in enumerate(zip(vals, bottoms)):
                if val > 10:
                    ax.text(xi, bot + val / 2, f"{val:.0f}%",
                            ha="center", va="center",
                            fontsize=8, color="white", fontweight="bold")
            bottoms += vals

        ax.set_xticks(x)
        ax.set_xticklabels([type_labels.get(ct_, ct_).replace(" ", "\n")
                            for ct_ in claim_types], fontsize=9)
        ax.set_title(COMPANY_NAMES.get(ticker, ticker),
                     fontsize=12, fontweight="bold",
                     color=TICKER_COLORS.get(ticker, "#333"))
        ax.set_ylim(0, 108)
        ax.yaxis.set_major_formatter(mticker.PercentFormatter())
        ax.grid(axis="y", alpha=0.25)
        ax.set_axisbelow(True)
        sns.despine(ax=ax, left=True, bottom=True)

        # n labels
        for xi, ct_ in enumerate(claim_types):
            n = len(sub[sub["claim_type"] == ct_])
            ax.text(xi, -5, f"n={n}", ha="center", fontsize=7.5, color="#999")

    handles = [mpatches.Patch(color=VERDICT_COLORS[v],
                               label=VERDICT_LABELS[v])
               for v in VERDICT_ORDER if v in df["verdict"].values]
    axes[-1].legend(handles=handles, loc="upper right",
                    bbox_to_anchor=(1.02, 1), fontsize=8,
                    framealpha=0.9, edgecolor="#ccc")
    axes[0].set_ylabel("Share of Claims (%)", fontsize=10)

    fig.tight_layout()
    fig.savefig(out / "03_claim_type_breakdown.png")
    plt.close(fig)
    print(f"  Saved 03_claim_type_breakdown.png")


def fig_truth_score_over_time(df: pd.DataFrame, out: Path) -> None:
    """Line chart: truth score per company per year (2020–2025)."""
    scored = df[df["truth_score"].notna()].copy()
    if scored.empty or "year" not in scored.columns:
        print("  Skipped time chart (no scored data with year)")
        return

    years   = sorted(scored["year"].dropna().unique())
    tickers = sorted(scored["ticker"].unique())

    fig, ax = plt.subplots(figsize=(11, 6))

    for ticker in tickers:
        ts = (scored[scored["ticker"] == ticker]
              .groupby("year")["truth_score"]
              .mean() * 100)
        ts = ts.reindex(years)
        ax.plot(years, ts.values,
                marker="o", markersize=7, linewidth=2.2,
                color=TICKER_COLORS.get(ticker, None),
                label=COMPANY_NAMES.get(ticker, ticker))

        # Annotate last point
        last_year = ts.last_valid_index()
        if last_year is not None:
            ax.annotate(f"{ts[last_year]:.0f}%",
                        xy=(last_year, ts[last_year]),
                        xytext=(6, 0), textcoords="offset points",
                        fontsize=8.5, color=TICKER_COLORS.get(ticker, "#333"),
                        fontweight="bold", va="center")

    ax.set_xlabel("Year of Earnings Call", fontsize=11)
    ax.set_ylabel("Truth Score (%)", fontsize=11)
    ax.set_title("Truthfulness Over Time by Company", fontsize=15,
                 fontweight="bold")
    ax.set_xticks(years)
    ax.set_ylim(0, 105)
    ax.yaxis.set_major_formatter(mticker.PercentFormatter())
    ax.axhline(50, color="#ccc", linestyle="--", linewidth=1, zorder=0)
    ax.text(years[0], 51.5, "50% baseline", fontsize=8, color="#aaa")
    ax.grid(alpha=0.3)
    ax.set_axisbelow(True)
    ax.legend(fontsize=10, framealpha=0.9, edgecolor="#ddd")
    sns.despine(ax=ax)

    fig.tight_layout()
    fig.savefig(out / "04_truth_score_over_time.png")
    plt.close(fig)
    print(f"  Saved 04_truth_score_over_time.png")


def fig_heatmap(df: pd.DataFrame, out: Path) -> None:
    """Heatmap: truth score per company × year."""
    scored = df[df["truth_score"].notna()].copy()
    if scored.empty:
        return

    pivot = (scored.groupby(["ticker", "year"])["truth_score"]
                   .mean() * 100
                   .reset_index()
                   if False   # placeholder
             else scored.pivot_table(values="truth_score", index="ticker",
                                     columns="year", aggfunc="mean") * 100)

    # Reorder rows
    row_order = [t for t in ["AMZN", "TSLA", "KO", "LLY"]
                 if t in pivot.index]
    pivot = pivot.loc[row_order]
    pivot.index = [COMPANY_NAMES.get(t, t) for t in pivot.index]

    fig, ax = plt.subplots(figsize=(11, 4))
    sns.heatmap(pivot, ax=ax, annot=True, fmt=".0f", cmap="RdYlGn",
                vmin=0, vmax=100, linewidths=0.5, linecolor="#eee",
                cbar_kws={"label": "Truth Score (%)", "shrink": 0.8},
                annot_kws={"size": 11, "weight": "bold"})
    ax.set_title("Truth Score Heatmap (Company × Year)", fontsize=15,
                 fontweight="bold")
    ax.set_xlabel("Year", fontsize=11)
    ax.set_ylabel("")
    ax.tick_params(axis="y", rotation=0, labelsize=11)
    ax.tick_params(axis="x", labelsize=10)

    fig.tight_layout()
    fig.savefig(out / "05_heatmap_company_year.png")
    plt.close(fig)
    print(f"  Saved 05_heatmap_company_year.png")


def fig_verdict_counts_summary(df: pd.DataFrame, out: Path) -> None:
    """Horizontal bar: total claims per verdict, all companies combined."""
    counts = df["verdict"].value_counts()
    present = [v for v in VERDICT_ORDER if v in counts.index]
    vals    = [counts[v] for v in present]
    colors  = [VERDICT_COLORS[v] for v in present]
    labels  = [VERDICT_LABELS[v] for v in present]

    fig, ax = plt.subplots(figsize=(9, 4))
    bars = ax.barh(labels[::-1], vals[::-1], color=colors[::-1],
                   edgecolor="white", linewidth=0.8, height=0.55)

    for bar, val in zip(bars, vals[::-1]):
        ax.text(bar.get_width() + 2, bar.get_y() + bar.get_height() / 2,
                str(val), va="center", fontsize=10, fontweight="bold")

    total = len(df)
    ax.set_title(f"Overall Verdict Distribution  (n={total} claims)",
                 fontsize=14, fontweight="bold")
    ax.set_xlabel("Number of Claims", fontsize=11)
    ax.set_xlim(0, max(vals) * 1.15)
    ax.grid(axis="x", alpha=0.3)
    ax.set_axisbelow(True)
    sns.despine(ax=ax, left=True, bottom=True)

    fig.tight_layout()
    fig.savefig(out / "06_overall_verdict_counts.png")
    plt.close(fig)
    print(f"  Saved 06_overall_verdict_counts.png")


def fig_score_comparison(df: pd.DataFrame, out: Path) -> None:
    """Dot plot: truth score per company with confidence interval."""
    tickers = [t for t in ["AMZN", "TSLA", "KO", "LLY"]
               if t in df["ticker"].unique()]

    scores, cis, ns = [], [], []
    for ticker in tickers:
        sub = df[(df["ticker"] == ticker) & df["truth_score"].notna()]
        s   = sub["truth_score"].mean() * 100
        n   = len(sub)
        se  = sub["truth_score"].std() * 100 / np.sqrt(n) if n > 1 else 0
        scores.append(s)
        cis.append(se * 1.96)   # 95% CI
        ns.append(n)

    fig, ax = plt.subplots(figsize=(8, 5))
    y = np.arange(len(tickers))

    for yi, (ticker, score, ci, n) in enumerate(
            zip(tickers, scores, cis, ns)):
        color = TICKER_COLORS.get(ticker, "#333")
        ax.barh(yi, score, height=0.45, color=color, alpha=0.85,
                edgecolor="white")
        ax.errorbar(score, yi, xerr=ci, fmt="none",
                    color="#333", capsize=4, linewidth=1.5)
        ax.text(score + ci + 1, yi,
                f"{score:.1f}%  (n={n})",
                va="center", fontsize=10, color=color, fontweight="bold")

    ax.axvline(50, color="#bbb", linestyle="--", linewidth=1.2)
    ax.text(50.5, len(tickers) - 0.1, "50%", fontsize=8, color="#aaa")
    ax.set_yticks(y)
    ax.set_yticklabels([COMPANY_NAMES.get(t, t) for t in tickers],
                       fontsize=12, fontweight="bold")
    ax.set_xlabel("Truth Score (%, 95% CI)", fontsize=11)
    ax.set_title("Company Truth Score Comparison", fontsize=15,
                 fontweight="bold")
    ax.set_xlim(0, 115)
    ax.grid(axis="x", alpha=0.3)
    ax.set_axisbelow(True)
    sns.despine(ax=ax, left=True, bottom=True)

    fig.tight_layout()
    fig.savefig(out / "07_score_comparison.png")
    plt.close(fig)
    print(f"  Saved 07_score_comparison.png")


def print_summary_table(df: pd.DataFrame) -> None:
    """Print a clean summary table to stdout."""
    tickers = [t for t in ["AMZN", "TSLA", "KO", "LLY"]
               if t in df["ticker"].unique()]
    print("\n" + "="*72)
    print(f"  {'Company':<18} {'n':>4}  "
          f"{'Verified':>9} {'Partial':>9} {'Contra.':>9} "
          f"{'Unresolv.':>10} {'Score':>7}")
    print("="*72)
    for ticker in tickers:
        sub  = df[df["ticker"] == ticker]
        n    = len(sub)
        vc   = sub["verdict"].value_counts()
        def p(v): return f"{vc.get(v,0)/n*100:5.1f}%"
        scored = sub["truth_score"].dropna()
        score  = f"{scored.mean()*100:.1f}%" if len(scored) else "—"
        print(f"  {COMPANY_NAMES.get(ticker,ticker):<18} {n:>4}  "
              f"{p('verified'):>9} {p('partially_verified'):>9} "
              f"{p('contradicted'):>9} {p('not_yet_resolvable'):>10} "
              f"{score:>7}")
    print("="*72)

    total_n      = len(df)
    total_scored = df["truth_score"].dropna()
    total_score  = f"{total_scored.mean()*100:.1f}%" if len(total_scored) else "—"
    vc = df["verdict"].value_counts()
    def p(v): return f"{vc.get(v,0)/total_n*100:5.1f}%"
    print(f"  {'TOTAL':<18} {total_n:>4}  "
          f"{p('verified'):>9} {p('partially_verified'):>9} "
          f"{p('contradicted'):>9} {p('not_yet_resolvable'):>10} "
          f"{total_score:>7}")
    print("="*72 + "\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="profiles.visualize",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--verdicts", required=True, type=Path,
                        help="Combined verdicts CSV (autochecker or merged output).")
    parser.add_argument("--claims", required=True, type=Path,
                        help="Claims CSV (e.g. data/claims/55_full_run.csv).")
    parser.add_argument("--out", default=Path("data/profiles"), type=Path,
                        help="Output directory for PNG charts (default: data/profiles/).")
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)

    print(f"\nLoading data...")
    df = load_data(args.verdicts, args.claims)
    print(f"  {len(df)} verdicted claims across "
          f"{df['ticker'].nunique()} companies")

    print_summary_table(df)

    print("Generating charts...")
    fig_overview_donut(df, args.out)
    fig_company_bars(df, args.out)
    fig_claim_type_breakdown(df, args.out)
    fig_truth_score_over_time(df, args.out)
    fig_heatmap(df, args.out)
    fig_verdict_counts_summary(df, args.out)
    fig_score_comparison(df, args.out)

    print(f"\nDone. All charts saved to {args.out}/\n")


if __name__ == "__main__":
    main()
