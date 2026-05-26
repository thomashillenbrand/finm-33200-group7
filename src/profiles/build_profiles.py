"""
src/profiles/build_profiles.py
Build per-firm truthfulness profile CSVs and an aggregate summary.

Outputs (written to --out-dir, default data/profiles/):
  <TICKER>_profile.csv   — one row per claim: full claim details + verdict + grader reasoning
  summary.csv            — one row per firm: aggregate verdict counts + truth score

CLI:
    python -m profiles.build_profiles
    python -m profiles.build_profiles \\
        --verdicts data/verdicts/combined_55_final.csv \\
        --claims   data/claims/55_full_run.csv \\
        --agent-jsonl  data/verdicts/agent_screenfalse_55.jsonl \\
        --autocheck-jsonl data/autochecker/55_full_run_verdict_autochecker-v1.jsonl \\
        --out-dir  data/profiles/
"""

import argparse
import json
from pathlib import Path

import pandas as pd

# ── defaults ───────────────────────────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parents[2]
_VERDICTS      = _ROOT / "data/verdicts/combined_55_final.csv"
_CLAIMS        = _ROOT / "data/claims/55_full_run.csv"
_AGENT_JSONL   = _ROOT / "data/verdicts/agent_screenfalse_55.jsonl"
_AUTOCHECK_JSONL = _ROOT / "data/autochecker/55_full_run_verdict_autochecker-v1.jsonl"
_OUT_DIR       = _ROOT / "data/profiles"

# verdict labels in display order
_VERDICT_ORDER = [
    "verified",
    "partially_verified",
    "contradicted",
    "not_yet_resolvable",
    "insufficient_data",
]

# ── helpers ────────────────────────────────────────────────────────────────────

def _load_reasoning(agent_jsonl: Path, autocheck_jsonl: Path) -> dict[str, str]:
    """
    Returns {claim_id: reasoning_text} from both grader outputs.
    Agent reasoning is stored at top level; autochecker inside verdict dict.
    """
    reasoning: dict[str, str] = {}

    if agent_jsonl.exists():
        with agent_jsonl.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    text = row.get("reasoning") or ""
                    if text and row.get("claim_id"):
                        reasoning[row["claim_id"]] = str(text).strip()
                except json.JSONDecodeError:
                    pass

    if autocheck_jsonl.exists():
        with autocheck_jsonl.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    verdict = row.get("verdict") or {}
                    if isinstance(verdict, dict):
                        text = verdict.get("reasoning") or ""
                    else:
                        text = ""
                    if text and row.get("claim_id"):
                        # only set if not already populated by agent
                        reasoning.setdefault(row["claim_id"], str(text).strip())
                except json.JSONDecodeError:
                    pass

    return reasoning


def _truth_score(group: pd.DataFrame) -> float:
    """(verified + partially_verified) / total, rounded to 3 dp."""
    total = len(group)
    if total == 0:
        return 0.0
    positive = group["verdict"].isin(["verified", "partially_verified"]).sum()
    return round(positive / total, 3)


def build_profiles(
    verdicts_path: str | Path,
    claims_path: str | Path,
    agent_jsonl: str | Path,
    autocheck_jsonl: str | Path,
    out_dir: str | Path,
) -> None:
    verdicts_path   = Path(verdicts_path)
    claims_path     = Path(claims_path)
    agent_jsonl     = Path(agent_jsonl)
    autocheck_jsonl = Path(autocheck_jsonl)
    out_dir         = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── load & merge ───────────────────────────────────────────────────────────
    verdicts = pd.read_csv(verdicts_path)
    claims   = pd.read_csv(claims_path)

    # keep only useful claim columns
    claim_cols = [
        "claim_id", "company", "fiscal_period", "speaker_name",
        "verbatim_quote", "summary", "horizon_raw", "horizon_end_date",
    ]
    claim_cols = [c for c in claim_cols if c in claims.columns]
    claims_slim = claims[claim_cols].drop_duplicates(subset="claim_id")

    df = verdicts.merge(claims_slim, on="claim_id", how="left")

    # rename "source" → "grader" for clarity
    df = df.rename(columns={"source": "grader"})

    # attach reasoning text
    reasoning = _load_reasoning(agent_jsonl, autocheck_jsonl)
    df["reasoning"] = df["claim_id"].map(reasoning).fillna("")

    # clean column order for the profile CSVs
    profile_cols = [
        "claim_id",
        "company",
        "ticker",
        "call_date",
        "fiscal_period",
        "claim_type",
        "speaker_name",
        "verbatim_quote",
        "summary",
        "horizon_raw",
        "horizon_end_date",
        "verdict",
        "grader",
        "reasoning",
    ]
    profile_cols = [c for c in profile_cols if c in df.columns]
    df = df[profile_cols].sort_values(["ticker", "call_date", "claim_type"])

    # ── per-firm CSVs ──────────────────────────────────────────────────────────
    for ticker, group in df.groupby("ticker"):
        out_path = out_dir / f"{ticker}_profile.csv"
        group.to_csv(out_path, index=False)
        print(f"  Wrote {out_path}  ({len(group)} claims)")

    # ── aggregate summary ──────────────────────────────────────────────────────
    summary_rows = []
    for ticker, group in df.groupby("ticker"):
        company = group["company"].dropna().iloc[0] if "company" in group.columns else ticker
        counts  = group["verdict"].value_counts()
        row = {
            "ticker":               ticker,
            "company":              company,
            "total_claims":         len(group),
            "truth_score":          _truth_score(group),
        }
        for v in _VERDICT_ORDER:
            row[v] = int(counts.get(v, 0))
        summary_rows.append(row)

    summary = pd.DataFrame(summary_rows).sort_values("ticker")
    summary_path = out_dir / "summary.csv"
    summary.to_csv(summary_path, index=False)
    print(f"  Wrote {summary_path}")

    # ── print summary table ────────────────────────────────────────────────────
    print()
    print(f"{'Ticker':<6}  {'Company':<26}  {'Total':>5}  {'Score':>6}  "
          f"{'Verified':>8}  {'Partial':>7}  {'Contradicted':>12}  {'NYR':>4}")
    print("-" * 88)
    for _, r in summary.iterrows():
        print(
            f"{r['ticker']:<6}  {str(r['company']):<26}  {r['total_claims']:>5}  "
            f"{r['truth_score']:>6.1%}  "
            f"{r['verified']:>8}  {r['partially_verified']:>7}  "
            f"{r['contradicted']:>12}  {r['not_yet_resolvable']:>4}"
        )
    print()
    print(f"Total claims: {summary['total_claims'].sum()}  |  "
          f"Overall truth score: "
          f"{_truth_score(df):.1%}")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main(argv=None):
    p = argparse.ArgumentParser(
        prog="profiles.build_profiles",
        description="Build per-firm truthfulness profile CSVs + summary.",
    )
    p.add_argument("--verdicts",         type=Path, default=_VERDICTS)
    p.add_argument("--claims",           type=Path, default=_CLAIMS)
    p.add_argument("--agent-jsonl",      type=Path, default=_AGENT_JSONL)
    p.add_argument("--autocheck-jsonl",  type=Path, default=_AUTOCHECK_JSONL)
    p.add_argument("--out-dir",          type=Path, default=_OUT_DIR)
    args = p.parse_args(argv)

    print("Building per-firm truthfulness profiles...")
    build_profiles(
        verdicts_path   = args.verdicts,
        claims_path     = args.claims,
        agent_jsonl     = args.agent_jsonl,
        autocheck_jsonl = args.autocheck_jsonl,
        out_dir         = args.out_dir,
    )


if __name__ == "__main__":
    main()
