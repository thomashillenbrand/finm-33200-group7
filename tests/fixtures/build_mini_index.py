"""Generate the tiny `sec_filings_index.parquet` for the mini_filings fixture.

Run once during development; the resulting parquet is checked in. Re-run
manually if the fixture HTMLs change.

Usage:
    mamba run -n truth python tests/fixtures/build_mini_index.py
"""

from pathlib import Path

import pandas as pd

FIXTURE_DIR = Path(__file__).parent / "mini_filings"
OUT = FIXTURE_DIR / "sec_filings_index.parquet"


def main() -> None:
    rows = [
        {
            "accessionNumber": "0000000000-23-000010",
            "filingDate": "2024-02-20",
            "reportDate": "2023-12-31",
            "form": "10-K",
            "primaryDocument": "sample_10K.htm",
            "primaryDocDescription": "Annual report",
            "localPath": "sample_10K.htm",
        },
        {
            "accessionNumber": "0000000000-24-000005",
            "filingDate": "2024-04-30",
            "reportDate": "2024-03-31",
            "form": "10-Q",
            "primaryDocument": "sample_10Q.htm",
            "primaryDocDescription": "Quarterly report",
            "localPath": "sample_10Q.htm",
        },
        {
            "accessionNumber": "0000000000-24-000015",
            "filingDate": "2024-06-14",
            "reportDate": "2024-06-14",
            "form": "8-K",
            "primaryDocument": "sample_8K.htm",
            "primaryDocDescription": "Buyback authorization",
            "localPath": "sample_8K.htm",
        },
    ]
    pd.DataFrame(rows).to_parquet(OUT, index=False)
    print(f"wrote {OUT} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
