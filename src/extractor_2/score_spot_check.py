"""Score a filled-in spot-check CSV and print precision by axis.

Usage:
    python -m extractor.score_spot_check data/spot_check.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="extractor.score_spot_check", description=__doc__)
    parser.add_argument("csv_path", type=Path)
    args = parser.parse_args(argv)

    rows = list(csv.DictReader(args.csv_path.read_text(encoding="utf-8").splitlines()))
    filled = [
        r for r in rows
        if r.get("verdict_in_transcript", "").strip()
        and r.get("verdict_in_scope", "").strip()
        and r.get("verdict_category_correct", "").strip()
    ]

    if not filled:
        print("No filled rows found. Fill in the verdict_* columns first.")
        return 1

    def pct(key: str) -> float:
        yes = sum(1 for r in filled if r[key].strip().lower() == "yes")
        return yes / len(filled) * 100

    print(f"\nSpot-check results — {len(filled)} labeled claims\n")
    print(f"  In transcript:      {pct('verdict_in_transcript'):.1f}%")
    print(f"  In scope:           {pct('verdict_in_scope'):.1f}%")
    print(f"  Category correct:   {pct('verdict_category_correct'):.1f}%")

    axes = ["verdict_in_transcript", "verdict_in_scope", "verdict_category_correct"]
    failures = [r for r in filled if any(r[a].strip().lower() == "no" for a in axes)]

    if failures:
        print(f"\nFailure cases ({len(failures)}):")
        for r in failures:
            print(f"\n  [{r['ticker']} {r['call_date']}] {r['source_span'][:80]}...")
            print(f"    in_transcript={r['verdict_in_transcript']}  "
                  f"in_scope={r['verdict_in_scope']}  "
                  f"category_correct={r['verdict_category_correct']}")
            if r.get("notes"):
                print(f"    notes: {r['notes']}")
    else:
        print("\nNo failures — all labeled claims passed all three checks.")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
