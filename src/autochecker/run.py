"""CLI: ``python -m autochecker.run --claims data/claims/pilot_gpt55.csv``.

Runs stage 1 (screen) on every claim and stage 2 (verify) on the subset the
screen accepted *and* for which we have a horizon and post-call rows. Writes:

  - JSONL per claim with both stages' full payloads (the audit artifact).
  - A flat summary CSV for spreadsheet inspection.

The CSV columns intentionally mirror the upstream extractor schema so the
output can be joined back to ``data/claims/<input>.csv`` on ``claim_id``.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

from autochecker.compustat import CompustatSlice, load_panel, slice_post_call
from autochecker.llm import resolve_model
from autochecker.prompts import PROMPT_VERSION
from autochecker.schema import AutocheckRecord, ScreenResult
from autochecker.screen import build_screener, screen_claim
from autochecker.verify import build_verifier, verify_claim


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_OUT_DIR = _PROJECT_ROOT / "data" / "autochecker"


def _parse_date(value) -> Optional[date]:
    """Parse a YYYY-MM-DD string / pandas Timestamp / NaN into ``date|None``."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return None
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def _load_claims(claims_csv: Path) -> list[dict]:
    df = pd.read_csv(claims_csv)
    required = {
        "claim_id", "ticker", "company", "call_date", "horizon_end_date",
        "claim_type", "verbatim_quote", "summary",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Claims CSV missing required columns: {sorted(missing)}")
    return df.to_dict(orient="records")


def _summary_row(rec: AutocheckRecord) -> dict:
    """One flat row for the summary CSV."""
    citations = []
    if rec.evidence is not None:
        citations = rec.evidence.citations
    elif rec.verdict is not None:
        citations = rec.verdict.citations
    return {
        "claim_id": rec.claim_id,
        "ticker": rec.ticker,
        "call_date": rec.call_date.isoformat(),
        "horizon_end_date": rec.horizon_end_date.isoformat() if rec.horizon_end_date else "",
        "claim_type": rec.claim_type,
        "is_compustat_relevant": rec.screen.is_compustat_relevant,
        "assertion_kind": rec.screen.assertion_kind,
        "candidate_fields": ";".join(rec.screen.candidate_fields),
        "skipped_reason": rec.skipped_reason or "",
        "verdict": rec.verdict.verdict if rec.verdict else "",
        "n_citations": len(citations),
        "model": rec.model,
        "mode": rec.mode,
    }


def _process_one(
    row: dict,
    *,
    mode: str,
    model_name: str,
    screener,
    verifier,
    panel_cache: dict[str, "pd.DataFrame"],
) -> AutocheckRecord:
    ticker = str(row["ticker"]).upper()
    call_date = _parse_date(row["call_date"])
    horizon_end_date = _parse_date(row.get("horizon_end_date"))

    # Stage 1 — always runs.
    screen = screen_claim(
        ticker=ticker,
        company=str(row.get("company", "")),
        call_date=call_date,
        claim_type=str(row["claim_type"]),
        verbatim_quote=str(row["verbatim_quote"]),
        summary=str(row.get("summary", "")),
        screener=screener,
    )

    rec_base = dict(
        claim_id=str(row["claim_id"]),
        ticker=ticker,
        call_date=call_date,
        horizon_end_date=horizon_end_date,
        claim_type=str(row["claim_type"]),
        verbatim_quote=str(row["verbatim_quote"]),
        summary=str(row.get("summary", "")),
        mode=mode,
        model=model_name,
        screen=screen,
    )

    # Stage 2 — early-skip conditions.
    if not screen.is_compustat_relevant:
        return AutocheckRecord(**rec_base, skipped_reason="screen_false")
    if horizon_end_date is None:
        return AutocheckRecord(**rec_base, skipped_reason="no_horizon")

    if ticker not in panel_cache:
        try:
            panel_cache[ticker] = load_panel(ticker)
        except FileNotFoundError:
            return AutocheckRecord(**rec_base, skipped_reason="unknown_ticker")

    panel_slice: CompustatSlice = slice_post_call(
        panel_cache[ticker],
        ticker=ticker,
        call_date=call_date,
        horizon_end_date=horizon_end_date,
    )
    if panel_slice.is_empty:
        return AutocheckRecord(**rec_base, skipped_reason="empty_panel")

    stage2 = verify_claim(
        mode=mode,
        ticker=ticker,
        company=str(row.get("company", "")),
        call_date=call_date,
        horizon_end_date=horizon_end_date,
        claim_type=str(row["claim_type"]),
        verbatim_quote=str(row["verbatim_quote"]),
        summary=str(row.get("summary", "")),
        screen=screen,
        panel_slice=panel_slice,
        verifier=verifier,
    )
    if mode == "evidence":
        return AutocheckRecord(**rec_base, evidence=stage2)
    return AutocheckRecord(**rec_base, verdict=stage2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autochecker.run", description=__doc__)
    parser.add_argument("--claims", required=True, type=Path,
                        help="Path to a claims CSV (e.g. data/claims/pilot_gpt55.csv).")
    parser.add_argument("--mode", default="evidence", choices=["evidence", "verdict"],
                        help="evidence (safe for labeling, default) or verdict.")
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR,
                        help=f"Output directory (default: {_DEFAULT_OUT_DIR}).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only the first N claims (smoke testing).")
    parser.add_argument("--tickers", type=str, default=None,
                        help="Comma-separated tickers to restrict to (e.g. 'TSLA,AMZN').")
    args = parser.parse_args(argv)

    load_dotenv()
    model_name = resolve_model()

    claims = _load_claims(args.claims)
    if args.tickers:
        wanted = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}
        claims = [c for c in claims if str(c["ticker"]).upper() in wanted]
    if args.limit is not None:
        claims = claims[: args.limit]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.claims.stem}_{args.mode}_{PROMPT_VERSION}"
    jsonl_path = args.out_dir / f"{stem}.jsonl"
    csv_path = args.out_dir / f"{stem}.csv"

    screener = build_screener(model_name=model_name)
    verifier = build_verifier(args.mode, model_name=model_name)
    panel_cache: dict[str, "pd.DataFrame"] = {}

    summary_rows: list[dict] = []
    with jsonl_path.open("w", encoding="utf-8") as jf:
        for i, row in enumerate(claims, start=1):
            cid = str(row["claim_id"])
            print(f"[{i}/{len(claims)}] {cid} ({row['ticker']})", flush=True)
            try:
                rec = _process_one(
                    row,
                    mode=args.mode,
                    model_name=model_name,
                    screener=screener,
                    verifier=verifier,
                    panel_cache=panel_cache,
                )
            except Exception as exc:
                print(f"  ERROR: {exc!r}", flush=True)
                raise
            jf.write(rec.model_dump_json() + "\n")
            jf.flush()
            summary_rows.append(_summary_row(rec))
            tag = rec.skipped_reason or (rec.verdict.verdict if rec.verdict else "evidence")
            print(f"  -> screen={rec.screen.is_compustat_relevant} stage2={tag}", flush=True)

    fieldnames = list(summary_rows[0].keys()) if summary_rows else []
    with csv_path.open("w", encoding="utf-8", newline="") as cf:
        writer = csv.DictWriter(cf, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)

    print()
    print(f"Wrote {jsonl_path}")
    print(f"Wrote {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
