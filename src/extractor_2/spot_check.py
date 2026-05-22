"""Sample claims from extraction runs for manual spot-checking.

Usage:
    python -m extractor.spot_check data/extraction_runs/*.json --out data/spot_check.csv

Writes a CSV with 30 randomly sampled claims. Fill in the empty
verdict_* columns by hand, then run score_spot_check.py.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path


_OUT_FIELDS = [
    "claim_id",
    "ticker",
    "call_date",
    "category",
    "source_span",
    "horizon",
    "value_or_amount",
    "speaker",
    "verdict_in_transcript",   # fill in: yes / no
    "verdict_in_scope",        # fill in: yes / no
    "verdict_category_correct", # fill in: yes / no
    "notes",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="extractor.spot_check", description=__doc__)
    parser.add_argument("files", nargs="+", type=Path, help="Extraction JSON files.")
    parser.add_argument("--out", type=Path, default=Path("data/spot_check.csv"))
    parser.add_argument("--n", type=int, default=30, help="Number of claims to sample.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility.")
    args = parser.parse_args(argv)

    all_claims: list[dict] = []
    for path in args.files:
        data = json.loads(path.read_text(encoding="utf-8"))
        for claim in data.get("claims", []):
            all_claims.append({
                "claim_id": claim.get("claim_id", ""),
                "ticker": data.get("ticker", ""),
                "call_date": data.get("call_date", ""),
                "category": claim.get("category") or claim.get("subcategory") or "",
                "source_span": claim.get("source_span", ""),
                "horizon": claim.get("horizon", ""),
                "value_or_amount": claim.get("value_or_amount") or "",
                "speaker": claim.get("speaker") or "",
                "verdict_in_transcript": "",
                "verdict_in_scope": "",
                "verdict_category_correct": "",
                "notes": "",
            })

    if not all_claims:
        print("No claims found in the provided files.")
        return 1

    random.seed(args.seed)
    sample = random.sample(all_claims, min(args.n, len(all_claims)))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_OUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sample)

    print(f"Sampled {len(sample)} of {len(all_claims)} total claims -> {args.out}")
    print("Fill in the verdict_* columns by hand, then run: python -m extractor.score_spot_check")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
