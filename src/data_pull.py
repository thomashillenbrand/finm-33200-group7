"""
Download earnings call transcripts and Compustat annual fundamentals for a
single company, identified by ticker.

Usage:
    python -m data_pull AMZN --start 2018-01-01

Tables used (S&P Capital IQ):
  - ciq_transcripts.wrds_transcript_detail   : transcript metadata
  - ciq_transcripts.ciqtranscriptcomponent   : full transcript text
  - ciq_transcripts.ciqtranscript            : links keydev to transcript
  - ciq_transcripts.ciqtranscriptperson      : speaker info
  - ciq_transcripts.ciqtranscriptcomponenttype / ciqtranscriptspeakertype : lookups
  - ciq_common.ciqsecurity / ciqtradingitem / ciqexchange : ticker -> companyid lookup

Tables used (Compustat):
  - comp.security / comp.company             : ticker -> gvkey lookup
  - comp.funda                               : annual fundamentals
  - comp.fundq                               : quarterly fundamentals

SEC EDGAR endpoints:
  - https://www.sec.gov/files/company_tickers.json   : ticker -> CIK lookup
  - https://data.sec.gov/submissions/CIK{cik}.json   : filings index per company
  - https://www.sec.gov/Archives/edgar/data/...      : actual filing documents
"""


import argparse
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests
import wrds
from dotenv import load_dotenv

load_dotenv()  # walks up from cwd to find the project-root .env

BASE_DIR = "pulled_data"


def ticker_dirs(ticker: str) -> dict[str, str]:
    """Return the per-ticker directory layout under BASE_DIR/<ticker>/."""
    root = os.path.join(BASE_DIR, ticker)
    return {
        "root":       root,
        "transcript": os.path.join(root, "transcript"),
        "sec":        os.path.join(root, "SEC"),
        "compustat":  os.path.join(root, "Compustat"),
    }


def resolve_ticker(db, ticker: str) -> tuple[int, str]:
    """Resolve a US-listed ticker to (companyid, companyname). Picks the primary
    trading item if multiple matches exist."""
    rows = db.raw_sql(
        """
        SELECT DISTINCT s.companyid, ti.tickersymbol, ti.primaryflag AS ti_primary,
               s.primaryflag AS sec_primary
        FROM ciq_common.ciqtradingitem ti
        JOIN ciq_common.ciqsecurity s ON ti.securityid = s.securityid
        JOIN ciq_common.ciqexchange e ON ti.exchangeid = e.exchangeid
        WHERE UPPER(ti.tickersymbol) = UPPER(%(ticker)s)
          AND e.countryid = 213
        """,
        params={"ticker": ticker},
    )
    if rows.empty:
        raise SystemExit(f"No US-listed company found for ticker {ticker!r}.")

    rows = rows.sort_values(["sec_primary", "ti_primary"], ascending=[False, False])
    companyid = int(rows.iloc[0]["companyid"])

    name_df = db.raw_sql(
        """
        SELECT DISTINCT companyname
        FROM ciq_transcripts.wrds_transcript_detail
        WHERE companyid = %(cid)s
        LIMIT 1
        """,
        params={"cid": companyid},
    )
    companyname = name_df.iloc[0]["companyname"] if not name_df.empty else ticker
    return companyid, companyname


COMPUSTAT_VARS = [
    # Identifiers / metadata
    "gvkey", "datadate", "fyear", "fyr", "tic", "cusip", "cik", "conm",
    "indfmt", "consol", "popsrc", "datafmt", "curcd",
    "sich", "naicsh",
    # Assets
    "at",      # Total Assets
    "act",     # Current Assets - Total
    "che",     # Cash and Short-Term Investments
    "ch",      # Cash
    "ivst",    # Short-Term Investments
    "rect",    # Receivables - Total
    "invt",    # Inventories - Total
    "ppent",   # Property, Plant & Equipment - Net
    "ppegt",   # Property, Plant & Equipment - Gross
    "intan",   # Intangible Assets - Total
    "gdwl",    # Goodwill
    "ivao",    # Investment and Advances - Other
    # Liabilities & equity
    "lt",      # Total Liabilities
    "lct",     # Current Liabilities - Total
    "ap",      # Accounts Payable
    "dlc",     # Debt in Current Liabilities (short-term debt)
    "dltt",    # Long-Term Debt - Total
    "txditc",  # Deferred Taxes & Investment Tax Credit
    "ceq",     # Common Equity - Total
    "seq",     # Stockholders' Equity - Parent
    "pstk",    # Preferred Stock - Total
    "re",      # Retained Earnings
    "tstk",    # Treasury Stock - Total
    # Income statement
    "sale",    # Sales/Turnover (Net)
    "revt",    # Revenue - Total
    "cogs",    # Cost of Goods Sold
    "xsga",    # Selling, General & Administrative Expense
    "xrd",     # R&D Expense
    "xint",    # Interest Expense
    "xopr",    # Operating Expenses - Total
    "oibdp",   # Operating Income Before Depreciation
    "oiadp",   # Operating Income After Depreciation
    "ebit",    # Earnings Before Interest & Taxes
    "ebitda",  # Earnings Before Interest, Taxes, D&A
    "pi",      # Pretax Income
    "ib",      # Income Before Extraordinary Items
    "ni",      # Net Income (Loss)
    "txt",     # Income Taxes - Total
    "dp",      # Depreciation & Amortization
    "dvc",     # Dividends Common
    "dvp",     # Dividends Preferred
    "dv",      # Cash Dividends (Cash Flow)
    "dvt",     # Dividends - Total
    "epspx",   # EPS Basic - excl. Extraordinary Items
    "epsfx",   # EPS Diluted - excl. Extraordinary Items
    "epspi",   # EPS Basic - incl. Extraordinary Items
    "epsfi",   # EPS Diluted - incl. Extraordinary Items
    # Cash flow
    "oancf",   # Operating Activities - Net Cash Flow
    "ivncf",   # Investing Activities - Net Cash Flow
    "fincf",   # Financing Activities - Net Cash Flow
    "capx",    # Capital Expenditures
    "dpc",     # Depreciation & Amortization (Cash Flow)
    "sppe",    # Sale of Property
    "aqc",     # Acquisitions
    "sstk",    # Sale of Common & Preferred Stock
    "prstkc",  # Purchase of Common & Preferred Stock
    "dltis",   # Long-Term Debt - Issuance
    "dltr",    # Long-Term Debt - Reduction
    # Market
    "csho",    # Common Shares Outstanding
    "prcc_f",  # Price Close - Annual - Fiscal
    "mkvalt",  # Market Value - Total - Fiscal
]


def resolve_gvkey(db, ticker: str) -> tuple[str | None, str | None]:
    """Resolve a ticker to Compustat ``(gvkey, conm)``. If the ticker has been
    reused historically, prefer the still-active gvkey, then the most recently
    delisted one. Returns ``(None, None)`` if the ticker is not in Compustat."""
    rows = db.raw_sql(
        """
        SELECT s.gvkey, c.conm, c.dldte
        FROM comp.security s
        JOIN comp.company c ON s.gvkey = c.gvkey
        WHERE UPPER(s.tic) = UPPER(%(ticker)s)
        ORDER BY c.dldte DESC NULLS FIRST
        """,
        params={"ticker": ticker},
    )
    if rows.empty:
        return None, None
    return rows.iloc[0]["gvkey"], rows.iloc[0]["conm"]


def download_compustat(db, ticker: str, start: str, out_dir: str) -> None:
    """Download Compustat annual fundamentals (``comp.funda``) for ``ticker``
    and save to parquet. Uses the standard industrial/financial-services filter
    (datafmt='STD', popsrc='D', consol='C')."""
    out_path = os.path.join(out_dir, f"{ticker}_compustat_annual.parquet")
    if os.path.exists(out_path):
        print(f"Compustat data already exists at {out_path}, skipping.")
        return

    gvkey, conm = resolve_gvkey(db, ticker)
    if gvkey is None:
        print(f"No Compustat gvkey for ticker {ticker!r}, skipping Compustat.")
        return
    print(f"Resolved {ticker} -> gvkey={gvkey} ({conm})")

    cols = ", ".join(COMPUSTAT_VARS)
    print("Downloading Compustat annual fundamentals...", end=" ", flush=True)
    t0 = time.time()
    df = db.raw_sql(
        f"""
        SELECT {cols}
        FROM comp.funda
        WHERE gvkey = %(gvkey)s
          AND indfmt IN ('INDL', 'FS')
          AND datafmt = 'STD'
          AND popsrc  = 'D'
          AND consol  = 'C'
          AND datadate >= %(start)s
        ORDER BY datadate
        """,
        params={"gvkey": gvkey, "start": start},
    )
    elapsed = time.time() - t0
    df.to_parquet(out_path, index=False)
    print(f"{len(df):,} rows in {elapsed:.1f}s -> {out_path}")


COMPUSTAT_VARS_Q = [
    # Identifiers / metadata
    "gvkey", "datadate", "fyearq", "fqtr", "fyr", "tic", "cusip", "cik",
    "conm", "indfmt", "consol", "popsrc", "datafmt", "curcdq",
    "rdq",     # Report date of quarterly earnings
    # Balance sheet (end-of-quarter, 'q' suffix)
    "atq",     # Total Assets
    "actq",    # Current Assets - Total
    "cheq",    # Cash and Short-Term Investments
    "chq",     # Cash
    "ivstq",   # Short-Term Investments
    "rectq",   # Receivables - Total
    "invtq",   # Inventories - Total
    "ppentq",  # PP&E - Net
    "ppegtq",  # PP&E - Gross
    "intanq",  # Intangible Assets - Total
    "gdwlq",   # Goodwill
    "ivaoq",   # Investments and Advances - Other
    "ltq",     # Total Liabilities
    "lctq",    # Current Liabilities - Total
    "apq",     # Accounts Payable
    "dlcq",    # Debt in Current Liabilities
    "dlttq",   # Long-Term Debt - Total
    "txditcq", # Deferred Taxes & ITC
    "ceqq",    # Common Equity - Total
    "seqq",    # Stockholders' Equity - Parent
    "pstkq",   # Preferred Stock - Total
    "req",     # Retained Earnings
    "tstkq",   # Treasury Stock - Total
    # Income statement - quarterly values ('q' suffix)
    "saleq",   # Sales/Turnover (Net)
    "revtq",   # Revenue - Total
    "cogsq",   # Cost of Goods Sold
    "xsgaq",   # SG&A Expense
    "xrdq",    # R&D Expense
    "xintq",   # Interest Expense
    "xoprq",   # Operating Expenses - Total
    "oibdpq",  # Operating Income Before Depreciation
    "oiadpq",  # Operating Income After Depreciation
    "piq",     # Pretax Income
    "ibq",     # Income Before Extraordinary Items
    "niq",     # Net Income (Loss)
    "txtq",    # Income Taxes - Total
    "dpq",     # Depreciation & Amortization
    "epspxq",  # EPS Basic - excl. Extraordinary Items
    "epsfxq",  # EPS Diluted - excl. Extraordinary Items
    "epspiq",  # EPS Basic - incl. Extraordinary Items
    "epsfiq",  # EPS Diluted - incl. Extraordinary Items
    "dvpsxq",  # Dividends per Share - Ex-Date
    # Cash flow (reported year-to-date in comp.fundq, 'y' suffix)
    "oancfy",  # Operating Cash Flow - YTD
    "ivncfy",  # Investing Cash Flow - YTD
    "fincfy",  # Financing Cash Flow - YTD
    "capxy",   # Capital Expenditures - YTD
    "dpcy",    # Depreciation & Amortization (Cash Flow) - YTD
    "sppey",   # Sale of Property - YTD
    "aqcy",    # Acquisitions - YTD
    "sstky",   # Sale of Common & Preferred Stock - YTD
    "prstkcy", # Purchase of Common & Preferred Stock - YTD
    "dltisy",  # Long-Term Debt Issuance - YTD
    "dltry",   # Long-Term Debt Reduction - YTD
    "dvy",     # Cash Dividends - YTD
    # Market
    "cshoq",   # Common Shares Outstanding (end of quarter)
    "prccq",   # Price Close - Quarter
    "mkvaltq", # Market Value - Total - End of Quarter
]


def download_compustat_quarterly(db, ticker: str, start: str, out_dir: str) -> None:
    """Download Compustat quarterly fundamentals (``comp.fundq``) for ``ticker``
    and save to parquet. Standard filter (datafmt='STD', popsrc='D', consol='C').
    Note: cash-flow items in fundq are reported year-to-date (``y`` suffix); take
    first differences within each fiscal year to get the per-quarter values."""
    out_path = os.path.join(out_dir, f"{ticker}_compustat_quarterly.parquet")
    if os.path.exists(out_path):
        print(f"Compustat quarterly data already exists at {out_path}, skipping.")
        return

    gvkey, conm = resolve_gvkey(db, ticker)
    if gvkey is None:
        print(f"No Compustat gvkey for ticker {ticker!r}, skipping Compustat.")
        return
    print(f"Resolved {ticker} -> gvkey={gvkey} ({conm})")

    cols = ", ".join(COMPUSTAT_VARS_Q)
    print("Downloading Compustat quarterly fundamentals...", end=" ", flush=True)
    t0 = time.time()
    df = db.raw_sql(
        f"""
        SELECT {cols}
        FROM comp.fundq
        WHERE gvkey = %(gvkey)s
          AND indfmt IN ('INDL', 'FS')
          AND datafmt = 'STD'
          AND popsrc  = 'D'
          AND consol  = 'C'
          AND datadate >= %(start)s
        ORDER BY datadate
        """,
        params={"gvkey": gvkey, "start": start},
    )
    elapsed = time.time() - t0
    df.to_parquet(out_path, index=False)
    print(f"{len(df):,} rows in {elapsed:.1f}s -> {out_path}")


# ── SEC EDGAR ──────────────────────────────────────────────────────────────
# SEC requires a User-Agent that identifies the requester. Override via env var
# SEC_USER_AGENT (e.g. "Jane Doe jane@example.com").
SEC_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "FINM33200 Research Project contact@uchicago.edu",
)
SEC_HEADERS = {"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}
SEC_FORMS_DEFAULT = ("10-K", "10-Q", "8-K")
SEC_RATE_LIMIT_SEC = 0.11  # SEC fair-access policy: max ~10 req/sec.


def _sec_get(url: str) -> requests.Response:
    """GET an SEC URL with the required User-Agent and a small delay to stay
    under the fair-access rate limit."""
    r = requests.get(url, headers=SEC_HEADERS, timeout=60)
    r.raise_for_status()
    time.sleep(SEC_RATE_LIMIT_SEC)
    return r


def resolve_cik(ticker: str) -> tuple[str | None, str | None]:
    """Resolve a ticker to ``(cik_10digit, company_name)`` via SEC's official
    ticker map. Returns ``(None, None)`` if no match."""
    data = _sec_get("https://www.sec.gov/files/company_tickers.json").json()
    for entry in data.values():
        if entry["ticker"].upper() == ticker.upper():
            return f"{int(entry['cik_str']):010d}", entry["title"]
    return None, None


def _safe_filename(name: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", name)


def download_sec_filings(
    ticker: str,
    start: str,
    out_dir: str,
    forms: tuple[str, ...] = SEC_FORMS_DEFAULT,
) -> None:
    """Download SEC EDGAR filings (default: 10-K, 10-Q, 8-K) for ``ticker``
    filed on or after ``start`` (YYYY-MM-DD). Saves the primary document of
    each filing (typically HTML) under ``<out_dir>/<form>/`` and writes
    ``<out_dir>/<ticker>_sec_filings_index.parquet`` summarizing all filings.
    ``localPath`` in the index is relative to ``out_dir``."""
    base = Path(out_dir)
    base.mkdir(parents=True, exist_ok=True)
    index_path = base / f"{ticker}_sec_filings_index.parquet"

    cik, name = resolve_cik(ticker)
    if cik is None:
        print(f"No SEC CIK for ticker {ticker!r}, skipping SEC filings.")
        return
    print(f"Resolved {ticker} -> CIK={cik} ({name})")

    # Pull the submissions index. "recent" holds the last ~1000 filings; any
    # older filings are paginated in "files".
    subs = _sec_get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()
    pages = [subs["filings"]["recent"]]
    for f in subs["filings"].get("files", []):
        pages.append(_sec_get(f"https://data.sec.gov/submissions/{f['name']}").json())

    cols = ["accessionNumber", "filingDate", "reportDate", "form",
            "primaryDocument", "primaryDocDescription"]
    df = pd.concat([pd.DataFrame({c: p.get(c, []) for c in cols}) for p in pages],
                   ignore_index=True)

    df = df[df["form"].isin(forms) & (df["filingDate"] >= start)]
    df = df.sort_values("filingDate").reset_index(drop=True)
    print(f"Found {len(df):,} filings ({', '.join(forms)}) since {start}.")

    cik_int = int(cik)
    local_paths: list[str] = []
    n_dl = 0
    print("Downloading primary documents...", flush=True)
    t0 = time.time()
    for _, row in df.iterrows():
        acc = row["accessionNumber"]
        acc_nodash = acc.replace("-", "")
        primary = row["primaryDocument"]
        if not primary:
            local_paths.append("")
            continue
        form_dir = base / _safe_filename(row["form"])
        form_dir.mkdir(parents=True, exist_ok=True)
        fname = _safe_filename(
            f"{row['filingDate']}_{acc}_{os.path.basename(primary)}"
        )
        local = form_dir / fname
        local_paths.append(str(local.relative_to(base)))
        if local.exists():
            continue
        doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{primary}"
        try:
            r = _sec_get(doc_url)
            local.write_bytes(r.content)
            n_dl += 1
        except requests.HTTPError as e:
            print(f"  failed {row['form']} {row['filingDate']} ({acc}): {e}")
            local_paths[-1] = ""

    df["localPath"] = local_paths
    df.to_parquet(index_path, index=False)
    elapsed = time.time() - t0
    print(f"Downloaded {n_dl} new filings in {elapsed:.0f}s; "
          f"index ({len(df)} rows) -> {index_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ticker", help="US-listed ticker symbol (e.g. AAPL)")
    parser.add_argument("--start", default="2004-01-01",
                        help="Earliest call date (YYYY-MM-DD, default 2004-01-01)")
    args = parser.parse_args()

    ticker = args.ticker.upper()
    dirs = ticker_dirs(ticker)
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)

    db = wrds.Connection(wrds_username=os.environ["WRDS_USERNAME"])

    companyid, companyname = resolve_ticker(db, ticker)
    print(f"Resolved {ticker} -> companyid={companyid} ({companyname})")

    # ── Compustat quarterly fundamentals ──
    download_compustat_quarterly(db, ticker, args.start, dirs["compustat"])

    # ── SEC EDGAR filings (10-K, 10-Q, 8-K) ──
    download_sec_filings(ticker, args.start, dirs["sec"])

    # ── Earnings-call metadata ──
    meta_path = os.path.join(dirs["transcript"], f"{ticker}_metadata.parquet")
    if os.path.exists(meta_path):
        print(f"Metadata already exists at {meta_path}, skipping.")
    else:
        print("Downloading earnings call metadata...")
        meta = db.raw_sql(
            """
            SELECT *
            FROM ciq_transcripts.wrds_transcript_detail
            WHERE companyid = %(cid)s
              AND keydeveventtypename = 'Earnings Calls'
              AND mostimportantdateutc >= %(start)s
            """,
            params={"cid": companyid, "start": args.start},
        )
        meta.to_parquet(meta_path, index=False)
        print(f"Saved {len(meta):,} metadata rows to {meta_path}")

    # ── Full transcript text ──
    out_path = os.path.join(dirs["transcript"], f"{ticker}_transcripts.parquet")
    if os.path.exists(out_path):
        print(f"Transcripts already exist at {out_path}, skipping.")
        db.close()
        return

    print("Downloading full transcript text...", end=" ", flush=True)
    t0 = time.time()
    df = db.raw_sql(
        """
        SELECT
            d.companyid,
            d.companyname,
            d.keydevid,
            d.transcriptid,
            d.headline,
            d.mostimportantdateutc,
            c.transcriptcomponentid,
            c.componentorder,
            ct.transcriptcomponenttypename,
            p.transcriptpersonname,
            p.companyname AS speaker_company,
            st.speakertypename,
            c.componenttext
        FROM ciq_transcripts.ciqtranscriptcomponent c
        JOIN ciq_transcripts.ciqtranscript t
            ON c.transcriptid = t.transcriptid
        JOIN ciq_transcripts.wrds_transcript_detail d
            ON t.transcriptid = d.transcriptid
        LEFT JOIN ciq_transcripts.ciqtranscriptperson p
            ON c.transcriptpersonid = p.transcriptpersonid
        LEFT JOIN ciq_transcripts.ciqtranscriptcomponenttype ct
            ON c.transcriptcomponenttypeid = ct.transcriptcomponenttypeid
        LEFT JOIN ciq_transcripts.ciqtranscriptspeakertype st
            ON p.speakertypeid = st.speakertypeid
        WHERE d.companyid = %(cid)s
          AND d.keydeveventtypename = 'Earnings Calls'
          AND d.mostimportantdateutc >= %(start)s
        ORDER BY d.transcriptid, c.componentorder
        """,
        params={"cid": companyid, "start": args.start},
    )
    elapsed = time.time() - t0
    df.to_parquet(out_path, index=False)
    print(f"{len(df):,} rows in {elapsed:.0f}s -> {out_path}")

    db.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
