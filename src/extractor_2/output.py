"""Write extraction results to CSV for manual review and spot-checking."""

from __future__ import annotations

import csv
import json
from pathlib import Path


_CSV_FIELDS = [
    "claim_id",
    "ticker",
    "call_date",
    "type",
    "category",
    "metric",
    "subcategory",
    "source_span",
    "horizon",
    "horizon_start",
    "horizon_end",
    "value_or_amount",
    "confidence_language",
    "speaker",
    "speaker_type",
]


def write_csv(enriched: dict, path: Path) -> None:
    """Write an enriched result dict (from extract.enrich_result) to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for claim in enriched["claims"]:
        row = {f: claim.get(f, "") or "" for f in _CSV_FIELDS}
        row["ticker"] = enriched["ticker"]
        row["call_date"] = enriched["call_date"]
        rows.append(row)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(enriched: dict, path: Path) -> None:
    """Write an enriched result dict to JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(enriched, indent=2, default=str), encoding="utf-8")
