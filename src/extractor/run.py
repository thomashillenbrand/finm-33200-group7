"""CLI: extract forward-looking claims from transcript parquet file(s).

Examples::

    # 5-call pilot on one firm
    python -m extractor.run \\
        --input Pulled_data/TSLA/transcript/TSLA_transcripts.parquet \\
        --output data/claims/pilot_claims.csv --limit 5

    # full run over every transcript parquet under a directory
    python -m extractor.run \\
        --input Pulled_data --output data/claims/all_claims.csv

``--input`` may be a single transcript parquet or a directory. A directory is
searched recursively for ``*_transcripts.parquet`` (the file ``data_pull.py``
writes), so the metadata and Compustat parquets that share those directories
are skipped. ``--limit`` caps the number of calls processed per file (use
``--limit 5`` for the day-4 pilot).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

from extractor.extract import MODEL_NAME, extract_transcript
from extractor.output import write_claims_csv


def _input_files(path: Path) -> list[Path]:
    """Resolve ``--input`` to a sorted list of transcript parquet files.

    A directory is searched recursively for ``*_transcripts.parquet`` so that
    pointing ``--input`` at ``Pulled_data`` picks up every firm at once.
    """
    if path.is_dir():
        return sorted(path.rglob("*_transcripts.parquet"))
    return [path]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="extractor.run", description=__doc__)
    parser.add_argument(
        "--input", required=True, type=Path,
        help="Transcript parquet, or a directory searched for *_transcripts.parquet.",
    )
    parser.add_argument(
        "--output", required=True, type=Path,
        help="Path to write the claims CSV.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Max calls to process per input file (e.g. 5 for the pilot).",
    )
    parser.add_argument(
        "--model", default=MODEL_NAME,
        help=f"Chat model for init_chat_model (default: {MODEL_NAME}).",
    )
    args = parser.parse_args(argv)

    load_dotenv()

    files = _input_files(args.input)
    if not files:
        print(f"No transcript parquet files found at {args.input}", file=sys.stderr)
        return 1

    all_claims = []
    for parquet_file in files:
        print(f"\n=== {parquet_file.name} ===")

        def _report(call, claims):
            print(
                f"  {call.fiscal_period:<10} {call.call_date}  "
                f"->  {len(claims):>3} claims"
            )

        claims = extract_transcript(
            parquet_file, limit=args.limit, model_name=args.model, on_call=_report
        )
        print(f"  subtotal: {len(claims)} claims")
        all_claims.extend(claims)

    out_path = write_claims_csv(all_claims, args.output)

    print(f"\nWrote {len(all_claims)} claims -> {out_path}")

    breakdown = Counter(c.claim_type for c in all_claims)
    for claim_type, count in breakdown.most_common():
        print(f"  {claim_type:<20} {count}")

    if all_claims:
        exact = sum(1 for c in all_claims if c.quote_verbatim)
        located = sum(1 for c in all_claims if c.component_id)
        print(
            f"  provenance: {exact} exact-quote, "
            f"{located - exact} fuzzy-located, "
            f"{len(all_claims) - located} unlocated"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
