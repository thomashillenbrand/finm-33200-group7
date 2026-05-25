"""Compustat quarterly loader + post-call slicing + YTD→quarterly conversion.

The parquet files under ``src/pulled_data/<TICKER>/Compustat/`` carry both
point-in-time fields (saleq, niq, atq, ...) and year-to-date cash-flow-statement
fields ending in ``y`` (capxy, oancfy, dvy, prstkcy, ...). For the verifier we
want each row to express that quarter's activity, so we convert the YTD fields
to per-quarter deltas before handing data to the LLM.

Time-leak rule: ``slice_post_call`` keeps only rows with ``datadate > call_date``
and (if provided) ``datadate <= horizon_end_date``. The agent never sees a
quarter that ended before the call was held.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

# Project root resolved relative to this file: src/autochecker/compustat.py -> project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PULLED_DATA_DIR = _PROJECT_ROOT / "src" / "pulled_data"

# Compustat fields the LLM is told about in stage 1. Code -> short human label.
# Restricted to fields likely to be referenced by management guidance / capital
# allocation claims; the parquet has 72 columns but most are bookkeeping that
# would only crowd the prompt.
FIELD_LABELS: dict[str, str] = {
    # Income statement (quarterly, in millions $ unless noted)
    "saleq":   "Sales — net (quarterly, $M)",
    "revtq":   "Total revenue (quarterly, $M)",
    "cogsq":   "Cost of goods sold (quarterly, $M)",
    "xsgaq":   "Selling, general & admin expense (quarterly, $M)",
    "xrdq":    "R&D expense (quarterly, $M)",
    "xintq":   "Interest expense (quarterly, $M)",
    "oibdpq":  "Operating income before D&A (quarterly, $M)",
    "oiadpq":  "Operating income after D&A (quarterly, $M)",
    "piq":     "Pretax income (quarterly, $M)",
    "ibq":     "Income before extraordinary items (quarterly, $M)",
    "niq":     "Net income (quarterly, $M)",
    "txtq":    "Income tax expense (quarterly, $M)",
    "dpq":     "Depreciation & amortization (quarterly, $M)",
    "epspxq":  "EPS basic, excl. extraordinary ($/share)",
    "epsfxq":  "EPS diluted, excl. extraordinary ($/share)",
    # Balance sheet (point-in-time, $M)
    "atq":     "Total assets ($M, EOQ)",
    "actq":    "Total current assets ($M, EOQ)",
    "ltq":     "Total liabilities ($M, EOQ)",
    "lctq":    "Total current liabilities ($M, EOQ)",
    "ceqq":    "Common equity ($M, EOQ)",
    "seqq":    "Stockholders' equity ($M, EOQ)",
    "cheq":    "Cash & short-term investments ($M, EOQ)",
    "rectq":   "Receivables ($M, EOQ)",
    "invtq":   "Inventory ($M, EOQ)",
    "ppentq":  "Net property, plant & equipment ($M, EOQ)",
    "dlcq":    "Debt in current liabilities ($M, EOQ)",
    "dlttq":   "Long-term debt ($M, EOQ)",
    # Cash flow / capital actions — these are reported YTD in the raw data;
    # the loader converts each to a per-quarter delta. The label below refers
    # to the converted (quarterly) value.
    "oancf_q":   "Operating cash flow (quarterly, $M)",
    "ivncf_q":   "Investing cash flow (quarterly, $M)",
    "fincf_q":   "Financing cash flow (quarterly, $M)",
    "capx_q":    "Capital expenditures (quarterly, $M)",
    "sstk_q":    "Sale of common/preferred stock — issuance (quarterly, $M)",
    "prstkc_q":  "Purchase of common/preferred stock — buybacks (quarterly, $M)",
    "dltis_q":   "Long-term debt issuance (quarterly, $M)",
    "dltr_q":    "Long-term debt reduction (quarterly, $M)",
    "dv_q":      "Cash dividends paid (quarterly, $M)",
    # Market data
    "cshoq":   "Common shares outstanding (M, EOQ)",
    "prccq":   "Closing price at quarter end ($/share)",
    "mkvaltq": "Market value of equity ($M, EOQ)",
}

# Codebook string injected into LLM prompts so the model picks Compustat codes,
# not free-text field names.
FIELD_CODEBOOK: str = "\n".join(f"  {code}: {label}" for code, label in FIELD_LABELS.items())

# YTD-source fields in the raw parquet → per-quarter delta column we emit.
_YTD_TO_Q: dict[str, str] = {
    "oancfy":  "oancf_q",
    "ivncfy":  "ivncf_q",
    "fincfy":  "fincf_q",
    "capxy":   "capx_q",
    "sstky":   "sstk_q",
    "prstkcy": "prstkc_q",
    "dltisy":  "dltis_q",
    "dltry":   "dltr_q",
    "dvy":     "dv_q",
}


def parquet_path_for(ticker: str) -> Path:
    """Resolve the quarterly parquet for one ticker."""
    t = ticker.upper()
    return _PULLED_DATA_DIR / t / "Compustat" / f"{t}_compustat_quarterly.parquet"


def _ytd_to_quarterly(df: pd.DataFrame) -> pd.DataFrame:
    """Add per-quarter delta columns for the YTD fields.

    Compustat reports cash-flow items as a running year-to-date total per
    fiscal year. fqtr=1 → use as-is; fqtr>1 → subtract the prior quarter's
    YTD value within the same ``fyearq``. Done after the rows are sorted by
    fiscal time so the prior-quarter lookup is deterministic.
    """
    df = df.sort_values(["fyearq", "fqtr"]).reset_index(drop=True)
    for src, dst in _YTD_TO_Q.items():
        if src not in df.columns:
            df[dst] = pd.NA
            continue
        prev = df.groupby("fyearq")[src].shift(1)
        # Q1 has no prior quarter in the YTD series → equal to YTD itself.
        df[dst] = df[src].where(df["fqtr"] == 1, df[src] - prev)
    return df


def load_panel(ticker: str) -> pd.DataFrame:
    """Load the full quarterly panel for one ticker with YTD→Q conversion applied.

    Raises ``FileNotFoundError`` if the parquet does not exist (mis-spelled
    ticker, or data not yet pulled). ``datadate`` is converted to ``date`` so
    downstream comparisons against ``call_date`` are pure-date semantics.
    """
    path = parquet_path_for(ticker)
    if not path.exists():
        raise FileNotFoundError(f"Compustat panel missing for {ticker}: {path}")
    df = pd.read_parquet(path)
    df["datadate"] = pd.to_datetime(df["datadate"]).dt.date
    df = _ytd_to_quarterly(df)
    return df


@dataclass(frozen=True)
class CompustatSlice:
    """The pre+post-call slice handed to stage 2.

    ``post_rows`` are fiscal quarters that ended after the call and on/before
    the horizon — the evidence the agent grades the claim against.
    ``base_rows`` are the four fiscal quarters immediately before the call —
    the YoY baseline the LLM needs to compute "growth of X%" claims. Both are
    sourced from the same panel and labelled by ``period`` ('base' vs 'post')
    when serialised.
    """
    ticker: str
    call_date: date
    horizon_end_date: Optional[date]
    post_rows: pd.DataFrame
    base_rows: pd.DataFrame

    @property
    def is_empty(self) -> bool:
        return self.post_rows.empty

    @property
    def rows(self) -> pd.DataFrame:
        """Combined view (base then post) — kept for citation scrubbing."""
        return pd.concat([self.base_rows, self.post_rows], ignore_index=True)


# Number of pre-call quarters included as YoY base for stage 2. Four covers a
# full prior-year cycle, which is what guidance-style claims compare against.
_BASE_QUARTERS = 4


def slice_post_call(
    panel: pd.DataFrame,
    *,
    ticker: str,
    call_date: date,
    horizon_end_date: Optional[date],
    base_quarters: int = _BASE_QUARTERS,
) -> CompustatSlice:
    """Build base (pre-call) and post-call slices around ``call_date``.

    The strict ``>`` (not ``>=``) on the post-call cutoff guarantees the agent
    only treats as 'evidence' quarters that were unknown at the time of the
    call. ``base_quarters`` rows immediately before the call are included as
    a YoY baseline — these were already public when the claim was made, so
    surfacing them is not a time leak. ``horizon_end_date`` bounds the post
    slice only; the base window is fixed relative to the call.
    """
    base_rows = panel[panel["datadate"] <= call_date].tail(base_quarters)
    post = panel[panel["datadate"] > call_date]
    if horizon_end_date is not None:
        post = post[post["datadate"] <= horizon_end_date]
    return CompustatSlice(
        ticker=ticker,
        call_date=call_date,
        horizon_end_date=horizon_end_date,
        post_rows=post.reset_index(drop=True),
        base_rows=base_rows.reset_index(drop=True),
    )


def _format_rows(rows: pd.DataFrame, fields: list[str]) -> str:
    """Render ``rows`` as CSV with ``datadate, fyearq, fqtr`` plus ``fields``."""
    base_cols = ["datadate", "fyearq", "fqtr"]
    keep = base_cols + [f for f in fields if f in rows.columns]
    if rows.empty:
        return "(no rows)"
    sub = rows[keep].copy()
    for col in sub.columns:
        if col in base_cols:
            continue
        if pd.api.types.is_numeric_dtype(sub[col]):
            sub[col] = sub[col].astype("Float64").round(1)
    return sub.to_csv(index=False)


def format_table(panel_slice: CompustatSlice, fields: list[str]) -> str:
    """Render the slice as two clearly-labelled sub-tables for the LLM prompt.

    Always includes ``datadate, fyearq, fqtr`` so the model can cite specific
    quarters. Stage-1 candidate fields not present in the panel are silently
    skipped rather than crashing the run.
    """
    base = _format_rows(panel_slice.base_rows, fields)
    post = _format_rows(panel_slice.post_rows, fields)
    return (
        "Base period — quarters BEFORE the call (use only as YoY/level "
        "baseline, not as evidence the claim came true):\n"
        f"```csv\n{base}```\n\n"
        "Post-call period — quarters AFTER the call within the claim's "
        "horizon (this is the evidence the claim is graded against):\n"
        f"```csv\n{post}```"
    )
