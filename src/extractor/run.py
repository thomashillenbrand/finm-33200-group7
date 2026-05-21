"""CLI: extract forward-looking claims from transcript CSV(s).

Examples::

    # 5-call pilot on one firm
    python -m extractor.run \\
        --input data/Transcript/Tesla_2018_2022.csv \\
        --output data/claims/pilot_claims.csv --limit 5

    # full run over every transcript CSV in a directory
    python -m extractor.run \\
        --input data/Transcript --output data/claims/all_claims.csv

``--input`` may be a single CSV or a directory of CSVs. ``--limit`` caps the
number of calls processed per file (use ``--limit 5`` for the day-4 pilot).
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
    """Resolve ``--input`` to a sorted list of CSV files."""
    if path.is_dir():
        return sorted(path.glob("*.csv"))
    return [path]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="extractor.run", description=__doc__)
    parser.add_argument(
        "--input", required=True, type=Path,
        help="Transcript CSV file or a directory of transcript CSVs.",
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
        print(f"No CSV files found at {args.input}", file=sys.stderr)
        return 1

    all_claims = []
    for csv_file in files:
        print(f"\n=== {csv_file.name} ===")

        def _report(call, claims):
            print(
                f"  {call.fiscal_period:<10} {call.call_date}  "
                f"->  {len(claims):>3} claims"
            )

        claims = extract_transcript(
            csv_file, limit=args.limit, model_name=args.model, on_call=_report
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
